#!/usr/bin/env python3
"""Build the two MIS-sourced snapshots the app ships with:

  performance_live_data.json  the Performance Assessment rounds newer than
                              the curated baseline in performance_data.json
  meds_data.json              the whole Essential Meds & Supplies dataset
                              (checklist structure + every scored round)

The app reads these files and makes **no API calls at runtime** — so the
deployed instance needs no MIS credentials, loads instantly, and does not
depend on the MIS being reachable. The tradeoff is that the data is as-of
the moment this script last ran: re-run it and commit the output whenever
new assessments have come in.

This is the same pattern build_jmp_data.py already uses — a thin CLI wrapper
around fetch logic that lives elsewhere (performance_live.py, meds_live.py),
so there is one implementation of "how to read this form", not two.

Requires a `.env` in this same folder (see .env.example), or
.streamlit/secrets.toml, with MIS credentials, plus network access to the
MIS (see mis_client.get_base_url for how that URL is resolved).

Run manually: `python3 build_live_data.py`. Prints a summary — read it
before committing the output. It refuses to overwrite a snapshot that has
data with one that has less (pass `--force` if the drop is genuine), and
aborts outright if no registration can be matched to a canonical site.
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


class BuildAborted(RuntimeError):
    """A sanity check failed -- nothing was written."""


def _existing_site_count(path):
    """Total sites across all rounds in an already-committed snapshot, or 0
    if it doesn't exist / can't be read."""
    try:
        rounds = json.loads(path.read_text()).get("rounds", {})
    except (OSError, ValueError):
        return 0
    return sum(len(sites) for sites in rounds.values())


def _check_no_regression(path, label, new_rounds, force):
    """Refuse to replace a snapshot that has data with one that has none.

    A total collapse means something structural broke -- the Sept 2026
    migration renumbered every datapoint id, the site join silently resolved
    nothing, and this script cheerfully wrote two empty files and printed
    "Commit both files". Losing real data to a silent join failure is the
    one outcome worth stopping the build for.
    """
    before = _existing_site_count(path)
    after = sum(len(sites) for sites in new_rounds.values())
    if after < before and not force:
        raise BuildAborted(
            f"{label}: the fetch produced {after} site-round(s) but {path.name} already has "
            f"{before}. Nothing was written. This usually means the site join broke (renamed or "
            f"renumbered registrations), not that data was deleted. Investigate, then re-run with "
            f"--force if the drop is genuine."
        )
    if after < before:
        print(f"WARNING {label}: overwriting {before} site-round(s) with {after} (--force).", flush=True)


def main(force=False):
    t0 = time.monotonic()
    static = json.loads(STATIC_PATH.read_text())
    client = MISClient.login()

    # One registration listing, shared by both fetches -- the same datapoints
    # either way, so fetching it twice would just be extra round trips.
    reg_rows = client.list_form_data(performance_live.REG_FORM_ID)

    # Every submission is attributed to a site through this join, so if it
    # resolves nothing then every form below looks like it has no registered
    # sites and quietly produces an empty snapshot. Check it before fetching
    # anything else.
    resolved = performance_live.resolve_site_uuids(reg_rows, static["sites"])
    missing = [s["display_name"] for s in static["sites"] if s["site_key"] not in resolved]
    print(f"\nSite join: resolved {len(resolved)} of {len(static['sites'])} registrations.", flush=True)
    if missing:
        print(f"  unresolved: {', '.join(missing)}", flush=True)
    if not resolved:
        raise BuildAborted(
            "Not one registration could be matched to a canonical site, so every submission "
            "would be discarded as unregistered. Check that performance_data.json's sites still "
            "match the registration form on this MIS instance. Nothing was written."
        )

    print("\n--- Performance Assessment ---", flush=True)
    live_rounds, live_meta = performance_live.fetch_live_rounds(
        client, static["sites"], static["rounds"], reg_rows=reg_rows,
    )
    perf_payload = {"fetched_at": _stamp(), "rounds": live_rounds, "meta": live_meta}

    print("\n--- Essential Meds & Supplies ---", flush=True)
    meds_payload = meds_live.fetch_meds_rounds(client, static["sites"], reg_rows=reg_rows)
    meds_payload["fetched_at"] = _stamp()

    _check_no_regression(PERF_OUTPUT_PATH, "Performance Assessment", live_rounds, force)
    _check_no_regression(MEDS_OUTPUT_PATH, "Essential Meds & Supplies", meds_payload["rounds"], force)

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
        main(force="--force" in sys.argv[1:])
    except BuildAborted as e:
        print(f"\nABORTED: {e}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        raise SystemExit(1)
