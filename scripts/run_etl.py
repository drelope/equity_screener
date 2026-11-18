import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.crispdm.etl import load_dividends, load_prices
from src.crispdm.pit import pit_manifest_metadata
from src.crispdm.run_manifest import build_run_manifest, get_git_state, write_manifest_file

p = argparse.ArgumentParser()
p.add_argument("--symbols", required=True)
p.add_argument("--start", required=True)
p.add_argument("--end")
a = p.parse_args()
symbols = [x.strip().upper() for x in a.symbols.split(",")]
results = {}
for t in symbols:
    prices = load_prices(t, a.start, a.end)
    dividends = load_dividends(t, a.start, a.end)
    results[t] = {"prices": prices, "dividends": dividends}
    print(t, "prices", prices)
    print(t, "dividends", dividends)

try:
    git_state = get_git_state(Path(__file__).resolve().parents[1])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest = build_run_manifest(
        run_type="run_etl",
        code_sha=git_state.get("sha"),
        code_dirty=git_state.get("dirty"),
        parameters={"symbols": symbols, "start": a.start, "end": a.end},
        inputs={
            "source": "src.crispdm.etl",
            "pit": pit_manifest_metadata(
                as_of=a.end,
                universe_mode="symbol_arguments_draft",
                feature_timing_mode="input_date_range_draft",
                notes="Draft PIT metadata: simple ETL wrapper over requested date range; PIT controls not implemented.",
            ),
        },
        outputs={"symbol_results": results},
        environment={"script": "scripts.run_etl"},
        status="completed",
    )
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "runs"
        / f"run_etl_{stamp}"
        / "manifest.json"
    )
    write_manifest_file(manifest, manifest_path)
    print(f"Manifest: {manifest_path}")
except Exception as exc:
    print(f"Manifest write failed: {exc}")
