"""GPU rental prices (per GPU-hour) from a price-tracker CSV, plus self-hosting cost math.

CSV format (produced by price-tracker's ``fetch_gpu.py``)::

    provider,gpu,variant,price_per_hour,currency,note,source,fetch_date

A row with ``provider == "FX"`` and ``gpu == "USD/CNY"`` carries the exchange rate
used to convert CNY prices to USD.

Lookup order for the CSV:

1. ``LLM_PRICE_GPU_CSV`` environment variable (explicit file path);
2. the newest ``<tracker>/data/<YYYY-MM-DD>/gpu_prices.csv`` where ``<tracker>`` is
   ``LLM_PRICE_TRACKER_DIR`` (default ``/workspace/price-tracker``);
3. the snapshot bundled with this package (``data/gpu_prices_snapshot.csv``).

Runcrate (an AI cloud) rows are not read from the CSV. Unless ``LLM_PRICE_GPU_CSV`` is set, they are
fetched live from https://www.runcrate.ai/api/gpu-pricing (public JSON, no key) and merged in.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import httpx

ENV_CSV = "LLM_PRICE_GPU_CSV"
ENV_TRACKER_DIR = "LLM_PRICE_TRACKER_DIR"
DEFAULT_TRACKER_DIR = "/workspace/price-tracker"
SNAPSHOT_NAME = "gpu_prices_snapshot.csv"
_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PER_MILLION = 1_000_000
RUNCRATE_FEED_URL = "https://www.runcrate.ai/api/gpu-pricing"
RUNCRATE_PRICING_URL = "https://www.runcrate.ai/pricing"
RUNCRATE_PROVIDER = "Runcrate"
RUNCRATE_TIMEOUT = 10.0
# Feed ``gpu_type`` -> GPU name used in the CSV. Only types whose name the feed makes unambiguous
# are mapped: the feed does not say SXM vs PCIe, so H100 and A100 are left out, and V100 comes
# in two memory sizes.
RUNCRATE_GPUS = {
    "B300": "B300",
    "B200": "B200",
    "H200": "H200",
    "H200_nvl": "H200 NVL",
    "L40S": "L40S",
    "L40": "L40",
    "RTX5090": "RTX 5090",
    "RTX4090": "RTX 4090",
    "RTX3090": "RTX 3090",
    "RTX6000Ada": "RTX 6000 Ada",
    "RTXPro6000": "RTX Pro 6000",
    "A6000": "RTX A6000",
    "A40": "A40",
    "L4": "L4",
    "A10": "A10",
}


@dataclass
class GpuSource:
    path: Path | None
    kind: str  # "env" | "price-tracker" | "bundled-snapshot" | "missing"
    error: str | None = None


@dataclass
class GpuTable:
    source: GpuSource
    rows: list[dict[str, Any]] = field(default_factory=list)
    usd_cny: float | None = None
    fetch_dates: list[str] = field(default_factory=list)


def _snapshot_path() -> Path:
    return Path(str(resources.files("llm_price_mcp") / "data" / SNAPSHOT_NAME))


def latest_tracker_csv(tracker_dir: str | os.PathLike[str]) -> Path | None:
    """Return the gpu_prices.csv in the newest data/<YYYY-MM-DD>/ folder, if any."""
    data_dir = Path(tracker_dir) / "data"
    if not data_dir.is_dir():
        return None
    dated = sorted(
        (d for d in data_dir.iterdir() if d.is_dir() and _DATE_DIR.match(d.name)),
        key=lambda d: d.name,
        reverse=True,
    )
    for d in dated:
        f = d / "gpu_prices.csv"
        if f.is_file():
            return f
    return None


def resolve_source(env: dict[str, str] | None = None, use_snapshot: bool = True) -> GpuSource:
    env = os.environ if env is None else env
    explicit = env.get(ENV_CSV)
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return GpuSource(p, "env")
        # An explicit path that does not exist is an error; do not silently substitute data.
        return GpuSource(None, "missing", f"{ENV_CSV} points to a file that does not exist: {p}")
    tracker = latest_tracker_csv(env.get(ENV_TRACKER_DIR) or DEFAULT_TRACKER_DIR)
    if tracker:
        return GpuSource(tracker, "price-tracker")
    if use_snapshot:
        snap = _snapshot_path()
        if snap.is_file():
            return GpuSource(snap, "bundled-snapshot")
    return GpuSource(None, "missing", "No GPU price CSV found (no env path, no price-tracker data, no bundled snapshot).")


def _float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def load_table(source: GpuSource) -> GpuTable:
    table = GpuTable(source=source)
    if source.path is None:
        return table
    with open(source.path, newline="", encoding="utf-8") as fh:
        raw = list(csv.DictReader(fh))
    dates: set[str] = set()
    for r in raw:
        provider = (r.get("provider") or "").strip()
        gpu = (r.get("gpu") or "").strip()
        if provider == "FX" and gpu.upper() == "USD/CNY":
            table.usd_cny = _float(r.get("price_per_hour"))
            continue
        price = _float(r.get("price_per_hour"))
        if not provider or not gpu or price is None:
            continue  # e.g. Vast.ai "缺失" rows with an empty price
        if r.get("fetch_date"):
            dates.add(r["fetch_date"].strip())
        table.rows.append({
            "provider": provider,
            "gpu": gpu,
            "variant": (r.get("variant") or "").strip(),
            "price_per_hour": price,
            "currency": (r.get("currency") or "USD").strip().upper(),
            "note": (r.get("note") or "").strip(),
            "source": (r.get("source") or "").strip(),
            "fetch_date": (r.get("fetch_date") or "").strip(),
        })
    table.fetch_dates = sorted(dates)
    for row in table.rows:
        if row["currency"] == "USD":
            row["usd_per_hour"] = row["price_per_hour"]
        elif row["currency"] == "CNY" and table.usd_cny:
            row["usd_per_hour"] = round(row["price_per_hour"] / table.usd_cny, 4)
        else:
            row["usd_per_hour"] = None
    return table


def parse_runcrate(payload: Any) -> tuple[list[dict[str, Any]], str]:
    """Turn the Runcrate feed into table rows plus its ``fetched_at`` timestamp.

    ``min_price_hr`` is the live on-demand price per GPU-hour. Types with no available
    options are skipped because their price is stale.
    """
    gpus = payload.get("gpus") if isinstance(payload, dict) else None
    if not isinstance(gpus, list):
        raise ValueError("unexpected Runcrate feed shape")
    fetched_at = str(payload.get("fetched_at") or "")
    rows = []
    for g in gpus:
        name = RUNCRATE_GPUS.get(g.get("gpu_type"))
        price = _float(g.get("min_price_hr"))
        if name is None or price is None or not (_float(g.get("available_options")) or 0) >= 1:
            continue
        rows.append({
            "provider": RUNCRATE_PROVIDER,
            "gpu": name,
            "variant": "On-demand",
            "price_per_hour": price,
            "currency": "USD",
            "note": f"live feed {RUNCRATE_FEED_URL}",
            "source": RUNCRATE_PRICING_URL,
            "fetch_date": fetched_at[:10],
            "usd_per_hour": price,
        })
    return rows, fetched_at


def fetch_runcrate_rows() -> tuple[list[dict[str, Any]], str]:
    resp = httpx.get(RUNCRATE_FEED_URL, timeout=RUNCRATE_TIMEOUT, headers={"User-Agent": "llm-price-mcp/0.2"})
    resp.raise_for_status()
    return parse_runcrate(resp.json())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _matches_gpu(query: str, gpu: str) -> bool:
    """Every whitespace-separated term must appear in the GPU name (ignoring case/spaces/dashes)."""
    target = _norm(gpu)
    return all(_norm(t) in target for t in query.split())


def gpu_rental_prices(
    gpu: str | None = None,
    provider: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = resolve_source(env)
    if source.path is None:
        return {"ok": False, "message": source.error, "count": 0, "prices": []}
    table = load_table(source)
    live_sources: list[dict[str, str]] = []
    live_error = None
    if source.kind != "env" and (not provider or provider.strip().lower() in RUNCRATE_PROVIDER.lower()):
        try:
            live_rows, fetched_at = fetch_runcrate_rows()
        except (httpx.HTTPError, ValueError) as e:
            live_error = f"{RUNCRATE_PROVIDER} live feed unavailable: {e}"
        else:
            table.rows.extend(live_rows)
            live_sources.append({"provider": RUNCRATE_PROVIDER, "url": RUNCRATE_FEED_URL, "fetched_at": fetched_at})
    rows = table.rows
    if provider:
        p = provider.strip().lower()
        rows = [r for r in rows if p in r["provider"].lower()]
    if gpu:
        rows = [r for r in rows if _matches_gpu(gpu, r["gpu"])]
    rows = sorted(rows, key=lambda r: (r["usd_per_hour"] is None, r["usd_per_hour"] or 0, r["provider"], r["gpu"]))
    data_date = table.fetch_dates[-1] if table.fetch_dates else None
    out: dict[str, Any] = {
        "ok": bool(rows),
        "source_kind": source.kind,
        "source_file": str(source.path),
        "data_date": data_date,
        "usd_cny": table.usd_cny,
        "unit": "price per GPU per hour (on-demand); usd_per_hour converts CNY at usd_cny",
        "count": len(rows),
        "prices": rows,
    }
    if live_sources:
        out["live_sources"] = live_sources
    if live_error:
        out["live_error"] = live_error
    if source.kind == "bundled-snapshot":
        out["snapshot_date"] = data_date
        out["notice"] = (
            f"Using the snapshot bundled with llm-price-mcp (fetched {data_date}); prices may be stale. "
            f"Set {ENV_CSV} or {ENV_TRACKER_DIR} to use fresher data."
        )
    if not rows:
        filt = ", ".join(f"{k}={v!r}" for k, v in (("gpu", gpu), ("provider", provider)) if v)
        available = sorted({r["provider"] for r in table.rows})
        out["message"] = (
            f"No GPU prices matched ({filt or 'no filter'}) in {source.path}. "
            f"Providers in this file: {', '.join(available) or 'none'}. No data was invented."
        )
    return out


def self_host_cost_per_million(
    tokens_per_second: float, gpu_hourly_usd: float, utilization: float = 1.0
) -> float:
    """USD per 1M tokens = hourly cost / tokens actually produced per hour * 1M."""
    if tokens_per_second <= 0:
        raise ValueError("tokens_per_second must be > 0")
    if gpu_hourly_usd < 0:
        raise ValueError("gpu_hourly_usd must be >= 0")
    if not 0 < utilization <= 1:
        raise ValueError("utilization must be in (0, 1]")
    tokens_per_hour = tokens_per_second * 3600 * utilization
    return round(gpu_hourly_usd / tokens_per_hour * PER_MILLION, 6)
