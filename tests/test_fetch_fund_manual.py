import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

import fetch_fund_manual as fetcher
from api import server


def write_nav_js(path: Path, code="110022") -> Path:
    unit = [
        {"x": 1577836800000, "y": 1.0},
        {"x": 1577923200000, "y": 1.01},
        {"x": 1578009600000, "y": 1.02},
    ]
    cumulative = [[row["x"], row["y"]] for row in unit]
    path.write_text(
        f'var fS_name = "测试基金{code}";\n'
        f"var Data_netWorthTrend = {json.dumps(unit)};\n"
        f"var Data_ACWorthTrend = {json.dumps(cumulative)};\n",
        encoding="utf-8",
    )
    return path


class FakeAkshare:
    @staticmethod
    def fund_portfolio_hold_em(symbol, date):
        return pd.DataFrame(
            [{"股票代码": "000001", "股票名称": "测试", "占净值比例": 1.2, "季度": f"{date}年1季度"}]
        )

    @staticmethod
    def fund_portfolio_industry_allocation_em(symbol, date):
        return pd.DataFrame(
            [{"行业类别": "电子", "占净值比例": 1.2, "截止时间": f"{date}-03-31"}]
        )


def test_first_time_fund_initialization_creates_all_validated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "fetch_dividends", lambda code: None)
    monkeypatch.setattr(fetcher.time, "sleep", lambda seconds: None)
    js_path = write_nav_js(tmp_path / "fund.js")
    result = fetcher.main(
        "110022",
        js_path,
        root=tmp_path,
        ak_module=FakeAkshare,
        logs_dir=tmp_path / "logs",
    )
    fund_dir = tmp_path / "funds" / "110022"
    assert result["status"] == "SUCCESS"
    assert result["nav_rows"] == 3
    assert result["holdings_rows"] == 5
    assert result["industry_alloc_rows"] == 5
    assert set(pd.read_csv(fund_dir / "nav.csv").columns) >= {"nav_unit", "nav_cum", "nav_adj"}
    assert (fund_dir / "holdings.csv").is_file()
    assert (fund_dir / "industry_alloc.csv").is_file()
    assert json.loads((fund_dir / "_fund_manifest.json").read_text(encoding="utf-8"))["fund_name"]
    assert list((tmp_path / "logs").glob("fetch_110022_*.log"))


def test_nav_parser_rejects_empty_response(tmp_path):
    path = tmp_path / "empty.js"
    path.write_text("var Data_netWorthTrend = [];", encoding="utf-8")
    with pytest.raises(fetcher.FetchError) as caught:
        fetcher.parse_nav(path)
    assert caught.value.stage == fetcher.STAGE_NAV
    assert caught.value.code == "PUBLIC_NAV_EMPTY"


def test_missing_holdings_fields_are_rejected(monkeypatch):
    monkeypatch.setattr(fetcher.time, "sleep", lambda seconds: None)
    with pytest.raises(fetcher.FetchError) as caught:
        fetcher.fetch_yearly_table(
            "110022",
            ["2025"],
            lambda **kwargs: pd.DataFrame([{"unexpected": 1}]),
            fetcher.STAGE_HOLDINGS,
            "PUBLIC_HOLDINGS_FETCH_FAILED",
            ("股票代码", "季度"),
            retries=1,
            timeout_seconds=1,
        )
    assert caught.value.stage == fetcher.STAGE_HOLDINGS


def test_empty_industry_allocation_returns_stage_error(monkeypatch):
    monkeypatch.setattr(fetcher.time, "sleep", lambda seconds: None)
    with pytest.raises(fetcher.FetchError) as caught:
        fetcher.fetch_yearly_table(
            "110022",
            ["2025"],
            lambda **kwargs: pd.DataFrame(),
            fetcher.STAGE_INDUSTRY,
            "PUBLIC_INDUSTRY_ALLOCATION_FETCH_FAILED",
            ("行业类别", "截止时间"),
            retries=1,
            timeout_seconds=1,
        )
    assert caught.value.code == "PUBLIC_INDUSTRY_ALLOCATION_FETCH_FAILED"


def test_failed_atomic_save_keeps_existing_file(tmp_path, monkeypatch):
    destination = tmp_path / "holdings.csv"
    destination.write_text("stable", encoding="utf-8")

    def fail_to_csv(self, *args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_to_csv)
    with pytest.raises(fetcher.FetchError) as caught:
        fetcher.atomic_write_csv(pd.DataFrame([{"x": 1}]), destination)
    assert caught.value.stage == fetcher.STAGE_SAVE
    assert destination.read_text(encoding="utf-8") == "stable"


def test_failed_holdings_fetch_does_not_replace_cached_holdings(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "fetch_dividends", lambda code: None)
    monkeypatch.setattr(fetcher.time, "sleep", lambda seconds: None)
    fund_dir = tmp_path / "funds" / "110022"
    fund_dir.mkdir(parents=True)
    cached = fund_dir / "holdings.csv"
    cached.write_text("stable-cache", encoding="utf-8")

    class EmptyHoldings(FakeAkshare):
        @staticmethod
        def fund_portfolio_hold_em(symbol, date):
            return pd.DataFrame()

    with pytest.raises(fetcher.FetchError) as caught:
        fetcher.main(
            "110022",
            write_nav_js(tmp_path / "fund.js"),
            root=tmp_path,
            ak_module=EmptyHoldings,
            logs_dir=tmp_path / "logs",
        )
    assert caught.value.stage == fetcher.STAGE_HOLDINGS
    assert cached.read_text(encoding="utf-8") == "stable-cache"


@pytest.mark.parametrize("code", ["../110022", "110022;calc", "11002", "1100220"])
def test_fund_code_injection_is_rejected(code):
    with pytest.raises(fetcher.FetchError) as caught:
        fetcher.normalize_fund_code(code)
    assert caught.value.code == "INVALID_FUND_CODE"


def test_api_parses_structured_fetch_error():
    payload = {
        "stage": "HOLDINGS",
        "code": "PUBLIC_HOLDINGS_FETCH_FAILED",
        "message": "基金净值已获取，但公开持仓数据获取失败",
    }
    result = subprocess.CompletedProcess(
        ["python"], 1, b"", ("FETCH_ERROR_JSON " + json.dumps(payload, ensure_ascii=False)).encode()
    )
    assert server.parse_fetch_error(result) == payload


def test_existing_complete_cache_remains_usable(tmp_path, monkeypatch):
    fund_dir = tmp_path / "funds" / "110022"
    fund_dir.mkdir(parents=True)
    (fund_dir / "nav.csv").write_text("date,nav_adj", encoding="utf-8")
    (fund_dir / "holdings.csv").write_text("股票代码,季度", encoding="utf-8")
    monkeypatch.setattr(server, "FUNDS_DIR", tmp_path / "funds")
    assert server._has_local_data("110022") is True
