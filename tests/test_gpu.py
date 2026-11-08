import os
from pathlib import Path

import httpx
import pytest
import respx

from llm_price_mcp import gpu

real_fetch_runcrate_rows = gpu.fetch_runcrate_rows

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
    assert out["snapshot_date"] == out["data_date"] == "2026-11-02"
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


# Trimmed copy of https://www.runcrate.ai/api/gpu-pricing as fetched on 2026-11-08.
RUNCRATE_FEED = {
    "fetched_at": "2026-11-08T06:37:49.328Z",
    "gpus": [
        {"gpu_type": "MI350X", "name": "MI350X", "min_price_hr": 5.72, "available_options": 0},
        {"gpu_type": "H200", "name": "H200", "min_price_hr": 5.13, "available_options": 15},
        {"gpu_type": "H200_nvl", "name": "H200 NVL", "min_price_hr": 4.67, "available_options": 4},
        {"gpu_type": "H100", "name": "H100", "min_price_hr": 3.58, "available_options": 15},
        {"gpu_type": "L40S", "name": "L40S", "min_price_hr": 0.55, "available_options": 9},
        {"gpu_type": "RTX4090", "name": "RTX 4090", "min_price_hr": 0.58, "available_options": 10},
        {"gpu_type": "RTXPro6000", "name": "RTX PRO 6000", "min_price_hr": 2.41, "available_options": 22},
        {"gpu_type": "A6000", "name": "A6000", "min_price_hr": 0.57, "available_options": 47},
        {"gpu_type": "V100", "name": "V100 16GB", "min_price_hr": 3.35, "available_options": 1},
    ],
}


def test_parse_runcrate_maps_unambiguous_in_stock_types_only():
    rows, fetched_at = gpu.parse_runcrate(RUNCRATE_FEED)
    assert fetched_at == "2026-11-08T06:37:49.328Z"
    # H100 (SXM vs PCIe unknown), V100 (two sizes) and out-of-stock MI350X are skipped
    assert [(r["gpu"], r["usd_per_hour"]) for r in rows] == [
        ("H200", 5.13), ("H200 NVL", 4.67), ("L40S", 0.55),
        ("RTX 4090", 0.58), ("RTX Pro 6000", 2.41), ("RTX A6000", 0.57)]
    row = rows[0]
    assert row["provider"] == "Runcrate" and row["currency"] == "USD" and row["fetch_date"] == "2026-11-08"
    assert row["source"] == "https://www.runcrate.ai/pricing"


def test_parse_runcrate_rejects_unexpected_shape():
    with pytest.raises(ValueError):
        gpu.parse_runcrate({"error": "nope"})


@pytest.fixture
def live_feed(monkeypatch):
    monkeypatch.setattr(gpu, "fetch_runcrate_rows", real_fetch_runcrate_rows)


def test_runcrate_rows_are_merged_from_live_feed(tracker, live_feed):
    with respx.mock() as router:
        route = router.get(gpu.RUNCRATE_FEED_URL).mock(return_value=httpx.Response(200, json=RUNCRATE_FEED))
        out = gpu.gpu_rental_prices(gpu="4090", env={gpu.ENV_TRACKER_DIR: str(tracker)})
    assert route.called
    assert [(r["provider"], r["usd_per_hour"]) for r in out["prices"]] == [
        ("AutoDL", pytest.approx(0.3133)), ("Runcrate", 0.58)]
    assert out["live_sources"] == [{
        "provider": "Runcrate", "url": gpu.RUNCRATE_FEED_URL, "fetched_at": "2026-11-08T06:37:49.328Z"}]
    assert out["data_date"] == "2026-10-28" and "live_error" not in out


def test_runcrate_provider_filter(tracker, live_feed):
    with respx.mock() as router:
        router.get(gpu.RUNCRATE_FEED_URL).mock(return_value=httpx.Response(200, json=RUNCRATE_FEED))
        out = gpu.gpu_rental_prices(provider="runcrate", env={gpu.ENV_TRACKER_DIR: str(tracker)})
    assert {r["provider"] for r in out["prices"]} == {"Runcrate"} and out["count"] == 6


def test_runcrate_not_fetched_for_other_providers_or_explicit_csv(tracker, tmp_path, live_feed):
    with respx.mock(assert_all_called=False) as router:
        route = router.get(gpu.RUNCRATE_FEED_URL).mock(return_value=httpx.Response(200, json=RUNCRATE_FEED))
        gpu.gpu_rental_prices(provider="lambda", env={gpu.ENV_TRACKER_DIR: str(tracker)})
        custom = write(tmp_path / "custom.csv", "Acme,L4,x,0.5,USD,n,https://acme,2026-01-02\n")
        out = gpu.gpu_rental_prices(env={gpu.ENV_CSV: str(custom)})
    assert not route.called
    assert [r["provider"] for r in out["prices"]] == ["Acme"] and "live_sources" not in out


def test_runcrate_feed_failure_keeps_csv_rows(tracker, live_feed):
    with respx.mock() as router:
        router.get(gpu.RUNCRATE_FEED_URL).mock(return_value=httpx.Response(503))
        out = gpu.gpu_rental_prices(gpu="h100", env={gpu.ENV_TRACKER_DIR: str(tracker)})
    assert [r["provider"] for r in out["prices"]] == ["Lambda", "RunPod"]
    assert "Runcrate live feed unavailable" in out["live_error"] and "live_sources" not in out
