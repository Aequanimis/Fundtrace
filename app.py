#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基金高频持仓分析的本地 Streamlit 界面。

本文件只负责校验输入、调用现有脚本和展示已有结果，不包含模型算法。
"""

from __future__ import annotations

import csv
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent
BASE_DIR = PROJECT_ROOT / "base"
FUNDS_DIR = PROJECT_ROOT / "funds"
OUTPUT_DIR = PROJECT_ROOT / "output"

REQUIRED_BASE_FILES = ("sw_industry_index.csv", "stock_industry_map.csv")
REQUIRED_FUND_FILES = ("nav.csv", "holdings.csv")
PRIMARY_RESULT_FILES = ("report.md", "positions.png", "weekly_positions.csv")
FUND_CODE_RE = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def as_log(self) -> str:
        command = subprocess.list2cmdline(list(self.command))
        parts = [f"> {command}"]
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append("[stderr]\n" + self.stderr.rstrip())
        parts.append(f"[退出代码 {self.returncode}]")
        return "\n".join(parts)


def validate_fund_code(value: str) -> tuple[bool, str]:
    """只接受恰好六位数字，防止路径和命令注入。"""
    code = value.strip()
    if not code:
        return False, "请输入 6 位基金代码。"
    if not FUND_CODE_RE.fullmatch(code):
        return False, "基金代码必须是恰好 6 位数字，例如 161005。"
    return True, code


def _decode_output(data: bytes | None) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "gb18030", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def run_project_script(
    args: Sequence[str],
    timeout: int = 7200,
    output_callback=None,
) -> CommandResult:
    """用当前 Python 调用项目脚本；不经过 shell。"""
    command = (sys.executable, *map(str, args))
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(PROJECT_ROOT),
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if output_callback is None:
            stdout, stderr = process.communicate(timeout=timeout)
        else:
            messages: queue.Queue[tuple[str, bytes | None]] = queue.Queue()

            def read_stream(name, stream):
                for line in iter(stream.readline, b""):
                    messages.put((name, line))
                messages.put((name, None))

            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                threading.Thread(
                    target=read_stream, args=(name, stream), daemon=True
                ).start()
            chunks = {"stdout": [], "stderr": []}
            closed = set()
            started = time.monotonic()
            while len(closed) < 2 or process.poll() is None:
                if time.monotonic() - started >= timeout:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    name, line = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    closed.add(name)
                    continue
                chunks[name].append(line)
                output_callback(_decode_output(line).rstrip())
            stdout = b"".join(chunks["stdout"])
            stderr = b"".join(chunks["stderr"])
        return CommandResult(
            command=command,
            returncode=process.returncode,
            stdout=_decode_output(stdout),
            stderr=_decode_output(stderr),
        )
    except subprocess.TimeoutExpired:
        # Windows 的 venv python.exe 可能再启动基础解释器；必须结束整棵树，
        # 否则页面显示超时后模型仍会在后台占用 CPU。
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        else:
            process.kill()
        stdout, stderr = process.communicate()
        return CommandResult(
            command=command,
            returncode=124,
            stdout=_decode_output(stdout),
            stderr=_decode_output(stderr) + "\n操作等待时间过长，已停止。",
        )
    except Exception as exc:  # 页面不能因为单一步骤失败而崩溃
        return CommandResult(command, 1, "", f"{type(exc).__name__}: {exc}")


def base_data_exists(root: Path = PROJECT_ROOT) -> bool:
    base_dir = root / "base"
    return all((base_dir / name).is_file() for name in REQUIRED_BASE_FILES)


def fund_data_exists(code: str, root: Path = PROJECT_ROOT) -> bool:
    fund_dir = root / "funds" / code
    return all((fund_dir / name).is_file() for name in REQUIRED_FUND_FILES)


def base_latest_date(root: Path = PROJECT_ROOT) -> str | None:
    """读取行业指数表最后的有效日期，失败时退回抓取清单日期。"""
    index_path = root / "base" / "sw_industry_index.csv"
    latest: str | None = None
    try:
        with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                value = (row.get("date") or "").strip()
                if value and (latest is None or value > latest):
                    latest = value
        if latest:
            return latest[:10]
    except (OSError, UnicodeError, csv.Error):
        pass

    manifest_path = root / "base" / "_base_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(manifest.get("fetched_at", ""))[:10] or None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def result_paths(code: str, root: Path = PROJECT_ROOT) -> dict[str, Path]:
    directory = root / "output" / code
    return {name: directory / name for name in PRIMARY_RESULT_FILES}


def analyzed_funds(root: Path = PROJECT_ROOT) -> list[str]:
    output_dir = root / "output"
    if not output_dir.is_dir():
        return []
    codes = []
    for child in output_dir.iterdir():
        if (
            child.is_dir()
            and FUND_CODE_RE.fullmatch(child.name)
            and any((child / name).is_file() for name in PRIMARY_RESULT_FILES)
        ):
            codes.append(child.name)
    return sorted(codes, reverse=True)


def extract_confidence(report: str) -> str | None:
    patterns = (
        r"(?:模型)?可信度评级[^A-D\n]{0,30}([A-D])(?:级)?",
        r"模型可信度[^A-D\n]{0,30}([A-D])(?:级)?",
    )
    for pattern in patterns:
        match = re.search(pattern, report, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def friendly_error(stage: str, result: CommandResult) -> str:
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if stage == "base":
        return "未能准备申万行业基础数据，请检查网络连接后重试。"
    if stage == "fund":
        if "timeout" in combined or "超时" in combined or "下载失败" in combined:
            return "未能获取该基金数据，请检查基金代码是否正确或当前网络连接是否正常。"
        return "该基金的数据未能完整获取，请检查基金代码和网络连接后重试。"
    return "分析程序未能完成。已有数据不会被删除，可展开技术错误信息进行排查。"


def _download_button(st, label: str, path: Path, mime: str, key: str) -> None:
    try:
        st.download_button(
            label,
            data=path.read_bytes(),
            file_name=path.name,
            mime=mime,
            key=key,
        )
    except OSError as exc:
        st.info(f"暂时无法读取 {path.name}：{exc}")


def display_results(st, code: str) -> None:
    paths = result_paths(code)
    st.divider()
    st.success(f"分析完成 · 基金代码：{code}")

    report_text = ""
    if paths["report.md"].is_file():
        try:
            report_text = paths["report.md"].read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            st.info(f"报告文件暂时无法读取：{exc}")
    if report_text:
        confidence = extract_confidence(report_text)
        if confidence:
            st.metric("模型可信度", confidence)
        st.subheader("模型结论")
        st.markdown(report_text)
        _download_button(st, "下载分析报告", paths["report.md"], "text/markdown", f"report-{code}")
    else:
        st.info("本次结果中没有 report.md，其他可用结果仍会继续显示。")

    st.warning(
        "本工具根据基金公开净值、定期披露持仓及申万行业收益进行统计估算。"
        "模型结果反映的是隐含收益暴露，不等同于基金真实实时持仓，仅供研究参考。"
    )

    st.subheader("行业暴露变化")
    if paths["positions.png"].is_file():
        st.image(str(paths["positions.png"]), width="stretch")
    else:
        st.info("本次结果中没有 positions.png，报告和表格仍可正常使用。")

    st.subheader("每周估算数据")
    if paths["weekly_positions.csv"].is_file():
        try:
            import pandas as pd

            frame = pd.read_csv(paths["weekly_positions.csv"])
            if not frame.empty:
                date_col = next(
                    (column for column in frame.columns if str(column).lower() in {"date", "日期"}),
                    frame.columns[0],
                )
                frame = frame.sort_values(date_col, ascending=False)
            st.dataframe(frame, width="stretch", hide_index=True)
            _download_button(
                st,
                "下载 weekly_positions.csv",
                paths["weekly_positions.csv"],
                "text/csv",
                f"weekly-{code}",
            )
        except Exception as exc:
            st.info(f"每周估算数据暂时无法读取：{exc}")
    else:
        st.info("本次结果中没有 weekly_positions.csv。")

    extra_files = ("diagnostics.csv", "sim_portfolio.csv", "calibration.csv")
    available = [OUTPUT_DIR / code / name for name in extra_files if (OUTPUT_DIR / code / name).is_file()]
    if available:
        with st.expander("下载更多研究数据"):
            for path in available:
                _download_button(st, f"下载 {path.name}", path, "text/csv", f"extra-{code}-{path.name}")


def _show_logs(st, logs: Iterable[str], label: str = "查看运行日志") -> None:
    text = "\n\n".join(logs).strip()
    if text:
        with st.expander(label):
            st.code(text, language="text")


def run_analysis_flow(st, code: str, update_fund: bool, calibrate: bool, update_base: bool) -> None:
    logs: list[str] = []
    progress = st.progress(0, text="正在检查基础数据……")

    try:
        if update_base or not base_data_exists():
            result = run_project_script(("fetch_data.py", "base"))
            logs.append(result.as_log())
            if not result.ok or not base_data_exists():
                progress.empty()
                st.error(friendly_error("base", result))
                _show_logs(st, logs, "查看技术错误信息")
                return
        progress.progress(25, text="正在获取基金净值及持仓数据……")

        if update_fund or not fund_data_exists(code):
            result = run_project_script(("fetch_fund_manual.py", code))
            logs.append(result.as_log())
            if not result.ok or not fund_data_exists(code):
                progress.empty()
                st.error(friendly_error("fund", result))
                _show_logs(st, logs, "查看技术错误信息")
                return
        else:
            logs.append(f"基金 {code} 的本地数据已存在，本次直接使用。")

        progress.progress(55, text="正在运行高频持仓模型……")
        arguments = ["run_analysis.py", code]
        if calibrate:
            arguments.append("--calibrate")
        analysis_timeout = 420 if calibrate else 7200

        def show_calibration_progress(line: str) -> None:
            match = re.search(r"已完成：(\d+) / (\d+)", line)
            if match:
                done, total = map(int, match.groups())
                percent = 55 + int(30 * done / max(total, 1))
                progress.progress(percent, text=line)

        result = run_project_script(
            arguments,
            timeout=analysis_timeout,
            output_callback=show_calibration_progress if calibrate else None,
        )
        logs.append(result.as_log())
        if not result.ok:
            progress.empty()
            st.error(friendly_error("analysis", result))
            _show_logs(st, logs, "查看技术错误信息")
            return

        combined_output = f"{result.stdout}\n{result.stderr}"
        if "TIMEOUT_SAFE_STOP" in combined_output or "TIMEOUT_HARD_KILL" in combined_output:
            st.warning(
                "本次完整标定未能在5分钟限制内完成，已安全停止。\n\n"
                "未完成结果不会用于正式分析。\n\n"
                "快速分析继续使用默认参数或已有有效参数。"
            )

        progress.progress(90, text="正在生成分析报告……")
        st.session_state["selected_result_code"] = code
        st.session_state["last_logs"] = logs
        progress.progress(100, text="分析完成。")
        display_results(st, code)
        _show_logs(st, logs)
    except Exception as exc:
        progress.empty()
        logs.append(f"GUI 异常：{type(exc).__name__}: {exc}")
        st.error("操作未能完成，但软件和已有结果未受影响。")
        _show_logs(st, logs, "查看技术错误信息")


def render_app() -> None:
    import streamlit as st

    st.set_page_config(page_title="基金高频持仓分析", page_icon="📊", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {max-width: 1120px; padding-top: 2rem; padding-bottom: 4rem;}
        div[data-testid="stMetric"] {background: #f6f8fb; border: 1px solid #e5eaf0; padding: 0.8rem 1rem; border-radius: 0.6rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("基金高频持仓分析")
    st.caption("基于公开净值与行业收益数据，估算主动基金近期隐含行业暴露变化")

    history = analyzed_funds()
    if history:
        with st.expander("已分析基金", expanded=False):
            historical_code = st.selectbox("选择已有结果", history, key="history_code")
            if st.button("查看已有分析", width="content"):
                st.session_state["selected_result_code"] = historical_code

    with st.container(border=True):
        st.subheader("开始一次分析")
        code_input = st.text_input(
            "基金代码",
            placeholder="请输入 6 位基金代码",
            help="例如：161005",
            max_chars=64,
        )

        st.markdown("**分析设置**")
        update_fund = st.checkbox("自动获取 / 更新该基金数据", value=True)
        analysis_mode = st.radio(
            "分析模式",
            (
                "快速追踪（推荐）",
                "重新标定模型（高级，最长5分钟）",
            ),
            index=0,
            help="完整标定超时会自动停止并保存进度；未完成结果不会投入正式分析。",
        )
        calibrate = analysis_mode.startswith("重新标定模型")
        update_base = st.checkbox("更新申万行业基础数据", value=False)
        st.caption("基础数据无需每次更新，仅当距离上次更新时间较久时再执行。")
        latest = base_latest_date()
        if latest:
            st.caption(f"基础行业数据更新至：{latest}")
        elif not base_data_exists():
            st.caption("尚未找到完整的基础行业数据，首次分析时会自动准备。")

        clicked = st.button("开始分析", type="primary", width="stretch")

    if clicked:
        valid, value = validate_fund_code(code_input)
        if not valid:
            st.error(value)
        else:
            run_analysis_flow(st, value, update_fund, calibrate, update_base)
            return

    selected_code = st.session_state.get("selected_result_code")
    if selected_code and selected_code in analyzed_funds():
        display_results(st, selected_code)
        logs = st.session_state.get("last_logs", [])
        _show_logs(st, logs)


if __name__ == "__main__":
    render_app()
