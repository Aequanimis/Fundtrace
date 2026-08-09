# -*- coding: utf-8 -*-
"""V4 Phase A calibration orchestration.

This module changes calibration execution only.  It does not change the
solver, parameter grid, Ground Truth construction, or score mathematics.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .calibrate import _real_industry_matrix, _ts_cv_split, score_params
from .regress import rolling_positions


MODEL_VERSION = "FundTrace-V4-PhaseA"
WINDOWS = (60, 90, 120, 180, 250)
HALF_LIVES = (0, 20, 40, 80)
ALPHAS = (0.0, 1e-7, 1e-6, 1e-5)
ANCHOR_MULTS = (None, 2.5)


def parameter_combinations(
    windows=WINDOWS,
    half_lives=HALF_LIVES,
    alphas=ALPHAS,
    anchor_mults=ANCHOR_MULTS,
):
    return list(itertools.product(windows, half_lives, alphas, anchor_mults))


def combo_id(combo):
    window, half_life, alpha, anchor = combo
    anchor_text = "none" if anchor is None else f"{anchor:g}"
    return f"w{window}_h{half_life}_a{alpha:.12g}_anchor{anchor_text}"


def _sha256_text(values) -> str:
    payload = "\n".join(map(str, values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_sha256(paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(map(Path, paths), key=lambda item: str(item).lower()):
        digest.update(path.name.encode("utf-8"))
        digest.update(file_sha256(path).encode("ascii"))
    return digest.hexdigest()


def build_rebalance_dates(fund_ret, factor_ret, freq="W-FRI", min_obs=60):
    idx = fund_ret.index.intersection(factor_ret.index)
    if len(idx) < min_obs:
        return pd.DatetimeIndex([])
    rebal = pd.Series(1, index=idx).resample(freq).last().dropna().index
    return pd.DatetimeIndex([date for date in rebal if date >= idx[min_obs - 1]])


def build_score_target_dates(
    fund_ret,
    factor_ret,
    periods,
    window_days=5,
    freq="W-FRI",
    min_obs=60,
):
    """Return the real weekly dates that can enter ``score_params``."""
    rebal = build_rebalance_dates(fund_ret, factor_ret, freq=freq, min_obs=min_obs)
    selected = set()
    span = pd.Timedelta(days=window_days * 2)
    for period in pd.DatetimeIndex(periods):
        selected.update(rebal[(rebal >= period - span) & (rebal <= period + span)])
    return pd.DatetimeIndex(sorted(selected))


def score_errors_by_period(W, real_mat, window_days=5):
    """The per-period components of the unchanged ``score_params`` MAE."""
    errors = {}
    top5_hits = {}
    span = pd.Timedelta(days=window_days * 2)
    for period in real_mat.index:
        near = W.index[(W.index >= period - span) & (W.index <= period + span)]
        key = pd.Timestamp(period).strftime("%Y-%m-%d")
        if len(near) == 0:
            errors[key] = np.nan
            top5_hits[key] = np.nan
            continue
        estimate = W.loc[near].mean()
        truth = real_mat.loc[period]
        columns = sorted(set(estimate.index) | set(truth.index))
        left = estimate.reindex(columns).fillna(0.0)
        right = truth.reindex(columns).fillna(0.0)
        errors[key] = float((left - right).abs().mean())
        top5_hits[key] = float(
            len(set(left.nlargest(5).index) & set(right.nlargest(5).index))
        )
    return pd.Series(errors, dtype=float), pd.Series(top5_hits, dtype=float)


def fold_scores_from_error_matrix(error_matrix, folds):
    """Compute the legacy fold means without any additional regression."""
    result = {}
    for combo_name, row in error_matrix.iterrows():
        scores = []
        for _, test_periods in folds:
            columns = [pd.Timestamp(period).strftime("%Y-%m-%d") for period in test_periods]
            values = pd.to_numeric(row.reindex(columns), errors="coerce").dropna()
            if len(values):
                scores.append(float(values.mean()))
        if scores:
            result[str(combo_name)] = scores
    return result


def _atomic_write_text(path: Path, text: str, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding=encoding, newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(data, path: str | Path):
    _atomic_write_text(Path(path), json.dumps(data, ensure_ascii=False, indent=2))


def atomic_write_csv(frame, path: str | Path, index=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        frame.to_csv(handle, index=index)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _load_resume(output_dir: Path, identity, combo_columns):
    meta_path = output_dir / "calibration_meta.json"
    checkpoint_path = output_dir / "calibration_checkpoint.csv"
    matrix_path = output_dir / "error_matrix.csv"
    empty_checkpoint = pd.DataFrame(columns=combo_columns)
    empty_matrix = pd.DataFrame()
    if not (meta_path.exists() and checkpoint_path.exists() and matrix_path.exists()):
        return empty_checkpoint, empty_matrix, False
    try:
        previous_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if previous_meta.get("identity") != identity:
            return empty_checkpoint, empty_matrix, False
        checkpoint = pd.read_csv(checkpoint_path)
        matrix = pd.read_csv(matrix_path, index_col=0)
        return checkpoint, matrix, True
    except (OSError, ValueError, json.JSONDecodeError):
        return empty_checkpoint, empty_matrix, False


def _progress_line(done, total, combo, elapsed, durations):
    window, half_life, alpha, anchor = combo
    average = float(np.mean(durations)) if durations else 0.0
    eta = average * max(total - done, 0)
    return (
        f"已完成：{done} / {total} | 当前组合：window={window} "
        f"half_life={half_life} alpha={alpha:.1e} anchor={anchor} | "
        f"已耗时：{_format_seconds(elapsed)} | 平均每组合：{average:.2f} 秒 | "
        f"预计剩余：{_format_seconds(eta)} | 硬上限：05:00"
    )


def _format_seconds(seconds):
    seconds = max(int(round(seconds)), 0)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def timeout_statistics(checkpoint, total_combos):
    done = checkpoint[checkpoint.get("status", pd.Series(dtype=str)) == "DONE"].copy()
    durations = pd.to_numeric(done.get("duration_seconds"), errors="coerce").dropna()
    stats = {
        "completed_combos": int(len(done)),
        "total_combos": int(total_combos),
        "avg_sec_per_combo": float(durations.mean()) if len(durations) else 0.0,
        "median_sec_per_combo": float(durations.median()) if len(durations) else 0.0,
        "p90_sec_per_combo": float(durations.quantile(0.9)) if len(durations) else 0.0,
    }
    stats["estimated_total_seconds"] = stats["avg_sec_per_combo"] * total_combos
    return stats


def write_timeout_report(output_dir, checkpoint, meta, watchdog=False, residual_process=False):
    output_dir = Path(output_dir)
    stats = timeout_statistics(checkpoint, meta.get("total_combos", 160))
    done = checkpoint[checkpoint.get("status", pd.Series(dtype=str)) == "DONE"].copy()

    def grouped(column):
        if done.empty or column not in done:
            return "无已完成组合"
        values = done.copy()
        values["duration_seconds"] = pd.to_numeric(values["duration_seconds"], errors="coerce")
        result = values.groupby(column, dropna=False)["duration_seconds"].mean()
        return ", ".join(f"{key}: {value:.3f}s" for key, value in result.items())

    slowest = done.sort_values("duration_seconds", ascending=False).head(10) if not done.empty else done
    slow_lines = [
        f"- `{row.combo_id}`: {float(row.duration_seconds):.3f}s"
        for row in slowest.itertuples()
    ] or ["- 无已完成组合"]
    text = "\n".join([
        "# Phase A calibration timeout report",
        "",
        f"- status: `{meta.get('status')}`",
        f"- completed combos: {stats['completed_combos']} / {stats['total_combos']}",
        f"- target dates: {meta.get('identity', {}).get('target_dates_count', 0)}",
        f"- total elapsed seconds: {float(meta.get('elapsed_seconds', 0.0)):.3f}",
        f"- average seconds/combo: {stats['avg_sec_per_combo']:.3f}",
        f"- median seconds/combo: {stats['median_sec_per_combo']:.3f}",
        f"- p90 seconds/combo: {stats['p90_sec_per_combo']:.3f}",
        f"- estimated full seconds: {stats['estimated_total_seconds']:.3f}",
        f"- checkpoint saved: {bool((output_dir / 'calibration_checkpoint.csv').exists())}",
        f"- watchdog hard kill: {bool(watchdog)}",
        f"- residual worker process: {bool(residual_process)}",
        "",
        "## Mean duration by dimension",
        "",
        f"- anchor: {grouped('anchor_mult')}",
        f"- window: {grouped('window')}",
        f"- half_life: {grouped('half_life')}",
        f"- alpha: {grouped('alpha')}",
        "",
        "## Slowest 10 combinations",
        "",
        *slow_lines,
        "",
        "Partial calibration results are diagnostic only and are not production parameters.",
    ])
    _atomic_write_text(output_dir / "performance_timeout_report.md", text)
    if output_dir.parent.name == "output":
        project_root = output_dir.parent.parent
        _atomic_write_text(project_root / "docs" / "development" / "performance_timeout_report.md", text)


def run_phase_a_grid(
    fund_ret,
    factor_ret,
    sim_mat,
    real_holdings,
    stock2sw,
    output_dir,
    fund_code,
    base_identity,
    windows=WINDOWS,
    half_lives=HALF_LIVES,
    alphas=ALPHAS,
    anchor_mults=ANCHOR_MULTS,
    max_calibration_seconds=300.0,
    safe_stop_seconds=285.0,
    start_monotonic=None,
    verbose=True,
    combo_limit=None,
):
    """Run each combo once, checkpointing its per-period error row."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic() if start_monotonic is None else start_monotonic
    real_mat = _real_industry_matrix(real_holdings, stock2sw)
    periods = sorted(real_mat.index)
    if not periods:
        raise ValueError("没有真实全持股数据，无法标定参数。")
    cv_folds = 3 if len(periods) >= 4 else 2
    folds = _ts_cv_split(periods, cv_folds)
    if not folds:
        raise ValueError("真实持仓期数不足，无法构建时间序列交叉验证。")

    targets = build_score_target_dates(fund_ret, factor_ret, periods)
    combos = parameter_combinations(windows, half_lives, alphas, anchor_mults)
    period_columns = [pd.Timestamp(period).strftime("%Y-%m-%d") for period in periods]
    grid = {
        "windows": list(windows),
        "half_lives": list(half_lives),
        "alphas": list(alphas),
        "anchor_mults": list(anchor_mults),
    }
    identity = dict(base_identity)
    identity.update({
        "fund_code": str(fund_code),
        "model_version": MODEL_VERSION,
        "parameter_grid": grid,
        "target_dates_count": int(len(targets)),
        "target_dates_hash": _sha256_text(date.isoformat() for date in targets),
        "max_calibration_seconds": float(max_calibration_seconds),
    })
    columns = [
        "combo_id", "window", "half_life", "alpha", "anchor_mult",
        "duration_seconds", "elapsed_seconds", "solver_calls", "status", "error",
    ]
    checkpoint, error_matrix, resumed = _load_resume(output_dir, identity, columns)
    if error_matrix.empty:
        error_matrix = pd.DataFrame(columns=period_columns, dtype=float)
    else:
        error_matrix = error_matrix.reindex(columns=period_columns)
    completed = set(
        checkpoint.loc[checkpoint.get("status", pd.Series(dtype=str)).isin(["DONE", "ERROR"]), "combo_id"]
        .astype(str)
    ) if not checkpoint.empty else set()
    durations = list(pd.to_numeric(checkpoint.get("duration_seconds"), errors="coerce").dropna()) if not checkpoint.empty else []

    meta_path = output_dir / "calibration_meta.json"
    meta = {
        "identity": identity,
        "identity_hash": hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "status": "RUNNING",
        "resumed": bool(resumed),
        "completed_combos": len(completed),
        "total_combos": len(combos),
        "elapsed_seconds": float(time.monotonic() - started),
    }
    atomic_write_json(meta, meta_path)
    if verbose:
        print(f"  Phase A：{len(combos)} 组参数 × {len(targets)} 个目标日期；断点续跑={resumed}", flush=True)

    attempted_this_run = 0
    for combo in combos:
        name = combo_id(combo)
        if name in completed:
            continue
        combo_started = time.monotonic()
        window, half_life, alpha, anchor = combo
        status = "DONE"
        error_text = ""
        try:
            weights, _ = rolling_positions(
                fund_ret,
                factor_ret,
                sim_mat=sim_mat,
                window=window,
                half_life=half_life,
                alpha=alpha,
                equity_cap="auto",
                anchor_mult=anchor,
                verbose=False,
                target_dates=targets,
            )
            errors, _ = score_errors_by_period(weights, real_mat)
            # Direct equivalence guard against accidental score drift.
            direct = score_params(weights, real_mat)
            if direct is not None and abs(float(errors.mean()) - direct["mae"]) > 1e-12:
                raise AssertionError("error-matrix score differs from score_params")
            error_matrix.loc[name, period_columns] = errors.reindex(period_columns).values
        except Exception as exc:
            status = "ERROR"
            error_text = f"{type(exc).__name__}: {exc}"
            error_matrix.loc[name, period_columns] = np.nan

        duration = time.monotonic() - combo_started
        elapsed = time.monotonic() - started
        durations.append(duration)
        row = pd.DataFrame([{
            "combo_id": name,
            "window": window,
            "half_life": half_life,
            "alpha": alpha,
            "anchor_mult": anchor,
            "duration_seconds": duration,
            "elapsed_seconds": elapsed,
            "solver_calls": len(targets),
            "status": status,
            "error": error_text,
        }])
        checkpoint = pd.concat([checkpoint, row], ignore_index=True)
        completed.add(name)
        attempted_this_run += 1
        atomic_write_csv(checkpoint, output_dir / "calibration_checkpoint.csv", index=False)
        atomic_write_csv(error_matrix, output_dir / "error_matrix.csv", index=True)
        meta.update({
            "status": "RUNNING",
            "completed_combos": len(completed),
            "elapsed_seconds": elapsed,
            "last_combo": name,
        })
        atomic_write_json(meta, meta_path)
        if verbose:
            print(_progress_line(len(completed), len(combos), combo, elapsed, durations), flush=True)

        if combo_limit is not None and attempted_this_run >= combo_limit:
            meta["status"] = "INTERRUPTED_TEST"
            atomic_write_json(meta, meta_path)
            return {
                "status": meta["status"], "completed_combos": len(completed),
                "total_combos": len(combos), "target_dates_count": len(targets),
                "solver_calls": int(pd.to_numeric(checkpoint["solver_calls"], errors="coerce").fillna(0).sum()),
                "error_matrix_shape": tuple(error_matrix.shape),
            }
        if elapsed >= safe_stop_seconds:
            meta["status"] = "TIMEOUT_SAFE_STOP"
            meta["elapsed_seconds"] = elapsed
            atomic_write_json(meta, meta_path)
            write_timeout_report(output_dir, checkpoint, meta, watchdog=False)
            return {
                "status": meta["status"], "completed_combos": len(completed),
                "total_combos": len(combos), "target_dates_count": len(targets),
                "solver_calls": int(pd.to_numeric(checkpoint["solver_calls"], errors="coerce").fillna(0).sum()),
                "error_matrix_shape": tuple(error_matrix.shape),
            }

    fold_scores = fold_scores_from_error_matrix(error_matrix, folds)
    complete_scores = {
        name: float(np.mean(values))
        for name, values in fold_scores.items()
        if len(values) == len(folds)
    }
    if not complete_scores:
        complete_scores = {name: float(np.mean(values)) for name, values in fold_scores.items()}
    if not complete_scores:
        raise ValueError("Phase A error matrix did not produce any fold scores")
    ordered = sorted(complete_scores.items(), key=lambda item: item[1])
    best_name, cv_mae = ordered[0]
    lookup = {combo_id(combo): combo for combo in combos}
    best_combo = lookup[best_name]
    candidate = {
        "model_version": MODEL_VERSION,
        "status": "PHASE_A_CANDIDATE_ONLY",
        "fund_code": str(fund_code),
        "window": best_combo[0],
        "half_life": best_combo[1],
        "alpha": best_combo[2],
        "anchor_mult": best_combo[3],
        "cv_mae": cv_mae,
        "n_folds": len(folds),
        "n_periods": len(periods),
        "top5_combo_ids": [name for name, _ in ordered[:5]],
        "production_eligible": False,
    }
    atomic_write_json(candidate, output_dir / "best_params_phaseA_candidate.json")
    meta.update({
        "status": "COMPLETED",
        "completed_combos": len(completed),
        "elapsed_seconds": float(time.monotonic() - started),
        "candidate_file": "best_params_phaseA_candidate.json",
    })
    atomic_write_json(meta, meta_path)
    return {
        "status": meta["status"], "completed_combos": len(completed),
        "total_combos": len(combos), "target_dates_count": len(targets),
        "solver_calls": int(pd.to_numeric(checkpoint["solver_calls"], errors="coerce").fillna(0).sum()),
        "error_matrix_shape": tuple(error_matrix.shape), "best": candidate,
        "elapsed_seconds": meta["elapsed_seconds"],
    }
