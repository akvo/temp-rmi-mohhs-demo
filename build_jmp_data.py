#!/usr/bin/env python3
"""Build jmp_data.json -- the offline fallback snapshot for the JMP WASH
Facility Assessment tab, used when the live MIS fetch (jmp_wash_tab.py, via
jmp_fetch.py) is unavailable at runtime.

Pulls the already-submitted JMP WASH Facility Assessment records (form
1783393878133, mohhs-mis.akvotest.org) plus their parent registration data
(form 1783289494205, for atoll/island names), and computes each facility's
JMP-2018 "basic / limited / no service" ladder per domain (water,
sanitation, hygiene, health-care waste, environmental cleaning) using
formulas ported from the documented JS engine formulas -- see
JMP_SCORING.md (in this same folder) for the full per-domain rationale.
The actual fetch + scoring logic lives in jmp_fetch.py, shared with the
live-at-runtime path in jmp_wash_tab.py -- this script is just a CLI
wrapper that writes the result to disk.

Requires a `.env` in this same folder (see .env.example), or
.streamlit/secrets.toml, with MIS credentials, plus network access to
mohhs-mis.akvotest.org.

Run manually: `python3 build_jmp_data.py`.
"""
import json
from pathlib import Path

import jmp_fetch
from mis_client import MISClient

HERE = Path(__file__).resolve().parent
OUTPUT_PATH = HERE / "jmp_data.json"


def main():
    client = MISClient.login()
    print("Logged in. Fetching JMP WASH submissions ...")
    data = jmp_fetch.build_jmp_dataset(client)
    OUTPUT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    print(f"\nWrote {OUTPUT_PATH} -- {len(data['sites'])} sites.")
    print(jmp_fetch.validation_summary(data["sites"]))


if __name__ == "__main__":
    main()
