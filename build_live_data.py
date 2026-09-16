#!/usr/bin/env python3
"""Build the two MIS-sourced snapshots the app ships with:

  performance_live_data.json  the Performance Assessment rounds newer than
                              the curated baseline in performance_data.json
  meds_data.json              the whole Essential Meds & Supplies dataset
                              (checklist structure + every scored round)

The app reads these files and makes **no API calls at runtime** — so the
deployed instance needs no MIS credentials, loads instantly, and keeps
working when mohhs-mis.akvotest.org is down (it returns 502s often enough
that runtime fetching was a real availability risk). The tradeoff is that
the data is as-of the moment this script last ran: re-run it and commit the
output whenever new assessments have come in.

This is the same pattern build_jmp_data.py already uses — a thin CLI wrapper
around fetch logic that lives elsewhere (performance_live.py, meds_live.py),
so there is one implementation of "how to read this form", not two.

Requires a `.env` in this same folder (see .env.example), or
.streamlit/secrets.toml, with MIS credentials, plus network access.

Run manually: `python3 build_live_data.py`. Prints a summary — read it
before committing the output.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import meds_live
import performance_live
from mis_client import MISClient

HERE = Path(__file__).resolve().parent
STATIC_PATH = HERE / "performance_data.json"
PERF_OUTPUT_PATH = HERE / "performance_live_data.json"
MEDS_OUTPUT_PATH = HERE / "meds_data.json"


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    t0 = time.monotonic()
    static = json.loads(STATIC_PATH.read_text())
    client = MISClient.login()

    # One registration listing, shared by both fetches -- it is the same 22
    # datapoints either way, and this instance is slow enough that fetching
    # it twice is a pointless 3 extra round trips.
    reg_rows = client.list_form_data(performance_live.REG_FORM_ID)

    print("\n--- Performance Assessment ---", flush=True)
    live_rounds, live_meta = performance_live.fetch_live_rounds(
        client, static["sites"], static["rounds"], reg_rows=reg_rows,
    )
    perf_payload = {"fetched_at": _stamp(), "rounds": live_rounds, "meta": live_meta}

    print("\n--- Essential Meds & Supplies ---", flush=True)
    meds_payload = meds_live.fetch_meds_rounds(client, static["sites"], reg_rows=reg_rows)
    meds_payload["fetched_at"] = _stamp()

    PERF_OUTPUT_PATH.write_text(json.dumps(perf_payload, indent=1))
    MEDS_OUTPUT_PATH.write_text(json.dumps(meds_payload, indent=1))

    # ------------------------------------------------------------- summary
    names = {s["site_key"]: s["display_name"] for s in static["sites"]}
    print("\n" + "=" * 70)
    print(f"Fetched in {time.monotonic() - t0:.0f}s at {perf_payload['fetched_at']}")

    print(f"\n{PERF_OUTPUT_PATH.name} ({PERF_OUTPUT_PATH.stat().st_size / 1024:.0f} KB)")
    if not live_rounds:
        print("  no rounds newer than the curated baseline "
              f"({static['rounds'][-1]}) — the tab will show static rounds only")
    for rk in sorted(live_rounds):
        m = live_meta[rk]
        print(f"  {rk}: {m['n_sites']} of {m['total_sites']} health centers")

    print(f"\n{MEDS_OUTPUT_PATH.name} ({MEDS_OUTPUT_PATH.stat().st_size / 1024:.0f} KB)")
    for sec in meds_payload["schema"]["sections"]:
        print(f"  section {sec['key']:<9} {len(sec['categories']):>2} categories, {sec['max_points']:>3} items")
    for rk, m in sorted(meds_payload["meta"]["rounds"].items()):
        print(f"  {rk}: {m['n_sites']} of {m['total_sites']} health centers")
        for k in m["inferred_sites"]:
            print(f"      ! {names.get(k, k)} — round inferred from the form date, not stated on the record")
    mm = meds_payload["meta"]
    if mm["skipped_unknown_site"]:
        print(f"  {mm['skipped_unknown_site']} submission(s) skipped: not a registered health center")
    if mm["skipped_no_round"]:
        print(f"  {mm['skipped_no_round']} submission(s) skipped: no round and no usable date")
    print("=" * 70)
    print("Commit both files to update the deployed app.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        raise SystemExit(1)
