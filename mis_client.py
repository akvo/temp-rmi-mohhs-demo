"""Shared MIS API client — credentials, login, pagination.

Used by both the offline ETL scripts (build_performance_data.py,
build_jmp_data.py) and the live-at-runtime paths in performance_tab.py /
jmp_wash_tab.py, so there is exactly one implementation of "how to talk to
the MOHHS MIS" instead of one copy per script.
"""
import concurrent.futures
import os
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
# The instance moved from mohhs-mis.akvotest.org to here in Sept 2026. It is
# overridable (see get_base_url) so the next move needs a config change, not
# a code change.
DEFAULT_BASE_URL = "https://mohhs.mis.akvo.org"
BASE_URL_ENV_VAR = "MIS_BASE_URL"
DEFAULT_ENV_PATH = HERE / ".env"


def _log(msg):
    """Console-only progress logging (stdout of the `streamlit run` process
    -- never shown in the browser UI). This API is slow enough on the test
    instance (multi-second round trips per call) that silent multi-call
    fetches look "stuck" without some visible progress."""
    print(f"[mis_client] {msg}", flush=True)


class MISCredentialsError(RuntimeError):
    """No usable credentials found in st.secrets or .env."""


class MISClientError(RuntimeError):
    """A request to the MIS API failed (bad status, timeout, etc.)."""


def load_env(path):
    """Tiny hand-rolled .env parser (not python-dotenv) — `user="..."` /
    `password="..."` per line."""
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _secret(key):
    """st.secrets['mis'][key], or None -- never raises just because there is
    no secrets.toml at all (the build scripts run outside Streamlit)."""
    try:
        import streamlit as st
        if "mis" in st.secrets:
            return st.secrets["mis"].get(key)
    except Exception:
        return None
    return None


def get_credentials(env_path=DEFAULT_ENV_PATH):
    """st.secrets['mis'] first (Streamlit Community Cloud deployment, or a
    local .streamlit/secrets.toml), then .env (local `streamlit run` / the
    standalone build scripts). Never raises just because no secrets.toml
    exists at all -- only a genuinely missing credential does."""
    user, password = _secret("user"), _secret("password")
    if user and password:
        return user, password
    if env_path.exists():
        env = load_env(env_path)
        if "user" in env and "password" in env:
            return env["user"], env["password"]
    raise MISCredentialsError(
        "No MIS credentials found -- set .streamlit/secrets.toml ([mis] user/password, "
        "see .streamlit/secrets.toml.example) for a deployment, or .env (see .env.example) "
        "for local dev."
    )


def get_base_url(env_path=DEFAULT_ENV_PATH):
    """Which MIS to talk to, resolved the same way as the credentials:
    MIS_BASE_URL in the environment (handy for a one-off run or CI), then
    st.secrets['mis']['base_url'], then `base_url` in .env, then
    DEFAULT_BASE_URL. Resolved per login rather than at import time, so a
    test or a late-set variable can still override it."""
    for value in (
        os.environ.get(BASE_URL_ENV_VAR),
        _secret("base_url"),
        (load_env(env_path).get("base_url") if env_path.exists() else None),
    ):
        if value:
            return value.rstrip("/")  # so a trailing slash can't produce '//api/v1/...'
    return DEFAULT_BASE_URL


class MISClient:
    """A logged-in session against the MIS API."""

    def __init__(self, session, headers, base_url=DEFAULT_BASE_URL):
        self.session = session
        self.headers = headers
        self.base_url = base_url

    @classmethod
    def login(cls, env_path=DEFAULT_ENV_PATH):
        user, password = get_credentials(env_path)
        base_url = get_base_url(env_path)
        # Logged so pointing at the wrong instance shows up here rather than
        # as a puzzling 404 three calls later.
        _log(f"Logging in as {user} at {base_url} ...")
        t0 = time.monotonic()
        session = requests.Session()
        try:
            resp = session.post(
                f"{base_url}/api/v1/login", json={"email": user, "password": password}, timeout=30,
            )
        except requests.RequestException as e:
            raise MISClientError(f"Could not reach the MIS ({e})") from e
        if resp.status_code != 200:
            raise MISClientError(f"MIS login failed ({resp.status_code})")
        token = resp.json().get("token")
        if not token:
            raise MISClientError("MIS login response had no token")
        _log(f"Login OK ({time.monotonic() - t0:.1f}s)")
        return cls(session, {"Authorization": f"Bearer {token}"}, base_url)

    def _get(self, path, **kwargs):
        t0 = time.monotonic()
        try:
            resp = self.session.get(f"{self.base_url}{path}", headers=self.headers, timeout=30, **kwargs)
        except requests.RequestException as e:
            raise MISClientError(f"Request to {path} failed ({e})") from e
        if resp.status_code != 200:
            raise MISClientError(f"Request to {path} failed ({resp.status_code})")
        _log(f"GET {path} -> 200 ({time.monotonic() - t0:.1f}s)")
        return resp.json()

    def list_form_data(self, form_id, perpage=50):
        """Paginated listing of a form's datapoints (list rows, not full
        answers -- see data_details for that)."""
        rows = []
        page = 1
        while True:
            _log(f"Listing form {form_id}, page {page} ...")
            j = self._get(f"/api/v1/form-data/{form_id}", params={"page": page, "perpage": perpage})
            rows.extend(j["data"])
            total_page = j.get("total_page", 1)
            if page >= total_page:
                break
            page += 1
        _log(f"Form {form_id}: {len(rows)} datapoint(s) listed.")
        return rows

    def data_details(self, record_id):
        """Full record (answers, uuid, administration, geo) for one FormData id."""
        return self._get(f"/api/v1/data-details/{record_id}")

    def data_details_many(self, record_ids, max_workers=6):
        """data_details() for many ids at once, run concurrently.

        Each call is independent and this test instance takes several
        seconds per call -- a plain sequential loop over a dozen-plus
        records takes minutes. `requests.Session` is safe to share across
        threads for concurrent requests, so a small worker pool here just
        shortens wall-clock time without changing what's fetched or how
        many calls are made."""
        results = [None] * len(record_ids)

        def _fetch(i, record_id):
            results[i] = self.data_details(record_id)

        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_fetch, i, rid) for i, rid in enumerate(record_ids)]
            for f in concurrent.futures.as_completed(futures):
                f.result()  # re-raise the first exception, if any, after all threads finish
        _log(f"Fetched {len(record_ids)} record detail(s) concurrently ({time.monotonic() - t0:.1f}s)")
        return results

    def form_schema(self, form_id):
        """The published form definition (question groups, questions, option
        lists). Used to derive a form's structure -- category labels, item
        labels, per-category maxima -- instead of hardcoding a copy of it."""
        return self._get(f"/api/v1/form/{form_id}")

    def administration(self, admin_id):
        """Resolve an administration (location-hierarchy) id to its name/full_name."""
        return self._get(f"/api/v1/administration/{admin_id}")
