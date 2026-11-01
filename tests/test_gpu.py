import os
from pathlib import Path

import pytest

from llm_price_mcp import gpu

HEADER = "provider,gpu,variant,price_per_hour,currency,note,source,fetch_date\n"


def write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + body, encoding="utf-8")
    return path


@pytest.fixture
def tracker(tmp_path):
    write(tmp_path / "data" / "2026-10-21" / "gpu_prices.csv",
          "RunPod,H100 SXM,Secure,9.99,USD,old,https://x,2026-10-21\n")
    write(tmp_path / "data" / "2026-10-28" / "gpu_prices.csv",
          "RunPod,H100 SXM,Secure Cloud,3.99,USD,n,https://www.runpod.io/pricing,2026-10-28\n"
          "Lambda,H100 PCIe,1x,3.29,USD,n,https://lambda.ai/pricing,2026-10-28\n"
          "Vast.ai,B200,缺失,,USD,无报价,https://console.vast.ai,2026-10-28\n"
          "AutoDL,RTX 4090 24GB,首页标价,1.88,CNY,n,https://www.autodl.com/home,2026-10-28\n"
          "FX,USD/CNY,er-api,6.0,CNY,汇率,https://open.er-api.com,2026-10-28\n")
    (tmp_path / "data" / "notadate").mkdir()
    return tmp_path


def test_picks_latest_dated_folder(tracker):
    assert gpu.latest_tracker_csv(tracker).parent.name == "2026-10-28"
    out = gpu.gpu_rental_prices(env={gpu.ENV_TRACKER_DIR: str(tracker)})
    assert out["source_kind"] == "price-tracker" and out["data_date"] == "2026-10-28"
    assert "snapshot_date" not in out
    # empty-price row dropped, FX row not listed, sorted by USD price
    assert [(r["provider"], r["usd_per_hour"]) for r in out["prices"]] == [
        ("AutoDL", pytest.approx(0.3133)), ("Lambda", 3.29), ("RunPod", 3.99)]
    assert out["usd_cny"] == 6.0
    row = out["prices"][0]
    assert row["price_per_hour"] == 1.88 and row["currency"] == "CNY"
    assert row["source"] == "https://www.autodl.com/home" and row["fetch_date"] == "2026-10-28"


def test_filters(tracker):
    env = {gpu.ENV_TRACKER_DIR: str(tracker)}
    assert [r["gpu"] for r in gpu.gpu_rental_prices(gpu="h100", env=env)["prices"]] == ["H100 PCIe", "H100 SXM"]
    assert [r["gpu"] for r in gpu.gpu_rental_prices(gpu="H100-sxm", env=env)["prices"]] == ["H100 SXM"]
    assert [r["provider"] for r in gpu.gpu_rental_prices(provider="lambda", env=env)["prices"]] == ["Lambda"]
    assert gpu.gpu_rental_prices(gpu="4090", provider="autodl", env=env)["count"] == 1


def test_no_match_is_explicit(tracker):
    out = gpu.gpu_rental_prices(gpu="TPU v5", env={gpu.ENV_TRACKER_DIR: str(tracker)})
    assert out["ok"] is False and out["count"] == 0 and out["prices"] == []
    assert "No GPU prices matched" in out["message"] and "RunPod" in out["message"]


def test_env_csv_overrides_tracker(tracker, tmp_path):
    custom = write(tmp_path / "custom.csv", "Acme,L4,x,0.5,USD,n,https://acme,2026-01-02\n")
    out = gpu.gpu_rental_prices(env={gpu.ENV_CSV: str(custom), gpu.ENV_TRACKER_DIR: str(tracker)})
    assert out["source_kind"] == "env" and out["source_file"] == str(custom)
    assert [r["provider"] for r in out["prices"]] == ["Acme"]


def test_env_csv_missing_file_errors_without_fallback(tmp_path):
    out = gpu.gpu_rental_prices(env={gpu.ENV_CSV: str(tmp_path / "nope.csv")})
    assert out["ok"] is False and out["prices"] == []
    assert gpu.ENV_CSV in out["message"]


def test_falls_back_to_bundled_snapshot(tmp_path):
    out = gpu.gpu_rental_prices(gpu="H100", env={gpu.ENV_TRACKER_DIR: str(tmp_path / "empty")})
    assert out["source_kind"] == "bundled-snapshot"
    assert out["snapshot_date"] == out["data_date"] == "2026-11-01"
    assert "snapshot" in out["notice"] and out["count"] > 0
    assert all(r["source"].startswith("https://") for r in out["prices"])


def test_nothing_available(tmp_path, monkeypatch):
    src = gpu.resolve_source(env={gpu.ENV_TRACKER_DIR: str(tmp_path)}, use_snapshot=False)
    assert src.kind == "missing" and src.path is None
    monkeypatch.setattr(gpu, "_snapshot_path", lambda: tmp_path / "missing.csv")
    out = gpu.gpu_rental_prices(env={gpu.ENV_TRACKER_DIR: str(tmp_path)})
    assert out["ok"] is False and "No GPU price CSV found" in out["message"]


def test_self_host_cost():
    # $2/h, 1000 tok/s => 3.6M tok/h => $0.5556 per 1M
    assert gpu.self_host_cost_per_million(1000, 2.0) == pytest.approx(0.555556)
    # 50% utilization doubles the cost
    assert gpu.self_host_cost_per_million(1000, 2.0, 0.5) == pytest.approx(1.111111)
    for bad in [(0, 1.0, 1.0), (10, -1, 1.0), (10, 1.0, 0), (10, 1.0, 1.5)]:
        with pytest.raises(ValueError):
            gpu.self_host_cost_per_million(*bad)
