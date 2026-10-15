"""EdgeOne Makers entry for the LIVE site: /api/* served by the shipped, unmodified Ryde handler
on the real Tencent ADP provider, with two credit guards in front of it.

Deploy-only adapter. The application (app/, data/, docs/policy.md) is copied byte-for-byte from
the build repo. This file supplies what the local server normally provides (the per-server state),
points run output at the function's writable /tmp, and adds:

  * provider: Tencent ADP. The three app keys come from the EdgeOne project's environment
    variables (TENCENT_ADP_RIDER_APP_KEY / _DRIVER_ / _JUDGE_); none ever ride in this bundle.
  * a 100 s case budget, so a slow case is escalated by the app itself ("still under review")
    before the platform's 120 s request ceiling cuts it off with a bare error.
  * filing limits on NEW filings that reach the agents (route deviation, no-show charge):
    PER_VISITOR_LIMIT per visitor in any rolling hour, DAILY_LIMIT per Singapore calendar day.
    Follow-up answers, out-of-scope reports and every console action are never limited. A filing
    the app refuses (any non-2xx answer) gives its slot back.

Counts live in this function instance's /tmp, the same place as the cases: a platform restart
resets them, which only ever makes the limits more generous.
"""
import fcntl
import io
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

_ROOT = Path(__file__).resolve().parent.parent  # cloud-functions/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import load_config  # noqa: E402
from app.dispute import AGENT_CATEGORIES  # noqa: E402
from app.llm import build_llm_client  # noqa: E402
from app.policy import load_policy  # noqa: E402
from app.server import MAX_BODY_BYTES, RydeRequestHandler, _ServerState  # noqa: E402

LIVE_PROVIDER = "tencent"
CASE_BUDGET_SECONDS = 100
PER_VISITOR_LIMIT = 10
VISITOR_WINDOW_SECONDS = 3600
DAILY_LIMIT = 50
SGT = timezone(timedelta(hours=8))

RUNTIME_ROOT = Path(os.environ.get("RYDE_RUNTIME_ROOT", "/tmp/ryde"))

VISITOR_LIMIT_MESSAGE = (
    "You have reached this demo's limit of %d live filings per hour. "
    "Please try again a little later." % PER_VISITOR_LIMIT
)
DAILY_LIMIT_MESSAGE = (
    "Today's live AI limit for this demo has been reached. "
    "It resets at midnight Singapore time."
)
NOT_CONFIGURED_MESSAGE = "The live AI is not available right now. Please try again later."

_STATE_LOCK = threading.Lock()


class _Shim:
    ryde_state = None


_SHIM = _Shim()


def _make_llm(config):
    """The live provider. Tests replace this seam with the keyless mock."""
    return build_llm_client(LIVE_PROVIDER, settings=config.llm)


def _materialise_policy():
    """Write docs/policy.md under the runtime root from its Python carrier, bytes verified.

    The bundle drops .md files and the docs/ folder and its root is read-only, so the policy is
    re-created at <runtime>/docs/policy.md, and pipeline's repo-root anchor is pointed at the
    runtime root so the case file records "docs/policy.md", exactly as a local run does.
    """
    import hashlib
    import app.pipeline as pipeline
    import ryde_deploy_policy as carrier
    data = carrier.TEXT.encode("utf-8")
    if hashlib.sha256(data).hexdigest() != carrier.SHA256:
        raise RuntimeError("policy carrier digest mismatch")
    root = RUNTIME_ROOT
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()  # pipeline resolves the policy path, so the anchor must be resolved too
    target = root / "docs" / "policy.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    pipeline._REPO_ROOT = root
    return target


def _build_state():
    config = load_config()
    policy_path = _materialise_policy()
    out_dir = RUNTIME_ROOT / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    return _ServerState(
        pack_dir=config.dataset_pack_dir,
        out_dir=out_dir,
        llm=_make_llm(config),
        confidence_threshold=config.confidence_threshold,
        autonomous_cap_sgd=config.autonomous_cap_sgd,
        case_budget_seconds=CASE_BUDGET_SECONDS,
        policy=load_policy(policy_path),
    )


def _state():
    """Build once per instance; a failed build (e.g. keys not set yet) is retried next request."""
    with _STATE_LOCK:
        if _SHIM.ryde_state is None:
            _SHIM.ryde_state = _build_state()
        return _SHIM.ryde_state


# ------------------------------------------------------------------ filing limits


def _now():
    return time.time()


def _limits_path():
    return RUNTIME_ROOT / "limits.json"


def _with_counts(update):
    """Run update(counts) under an exclusive file lock and persist what it returns.

    Each call opens its own file description, so flock serialises threads of this process as
    well as any other process sharing the instance's /tmp.
    """
    path = _limits_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read()
            try:
                counts = json.loads(raw) if raw.strip() else {}
            except ValueError:
                counts = {}
            if not isinstance(counts, dict):
                counts = {}
            result, counts = update(counts)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(counts))
            handle.flush()
            return result
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _today(now):
    return datetime.fromtimestamp(now, SGT).strftime("%Y-%m-%d")


def reserve_slot(visitor):
    """Take one live-filing slot for this visitor. Returns (stamp, None) or (None, refusal)."""
    now = _now()

    def update(counts):
        day = _today(now)
        if counts.get("day") != day or not isinstance(counts.get("daily"), int):
            # A new Singapore day resets the daily total only. Visitor stamps are kept, so the
            # rolling hour keeps rolling across midnight.
            counts = {"day": day, "daily": 0, "visitors": counts.get("visitors")}
        visitors = counts.get("visitors")
        if not isinstance(visitors, dict):
            visitors = {}
        stamps = visitors.get(visitor)
        recent = [t for t in (stamps if isinstance(stamps, list) else [])
                  if isinstance(t, (int, float)) and now - t < VISITOR_WINDOW_SECONDS]
        if counts["daily"] >= DAILY_LIMIT:
            return (None, DAILY_LIMIT_MESSAGE), counts
        if len(recent) >= PER_VISITOR_LIMIT:
            return (None, VISITOR_LIMIT_MESSAGE), counts
        recent.append(now)
        visitors[visitor] = recent
        counts["visitors"] = {
            key: value for key, value in visitors.items()
            if isinstance(value, list)
            and any(isinstance(t, (int, float)) and now - t < VISITOR_WINDOW_SECONDS for t in value)
        }
        counts["daily"] += 1
        return (now, None), counts

    return _with_counts(update)


def release_slot(visitor, stamp):
    """Give back a slot whose filing the app refused."""
    def update(counts):
        if counts.get("day") == _today(stamp) and isinstance(counts.get("daily"), int):
            counts["daily"] = max(0, counts["daily"] - 1)
        visitors = counts.get("visitors")
        if isinstance(visitors, dict) and isinstance(visitors.get(visitor), list):
            if stamp in visitors[visitor]:
                visitors[visitor].remove(stamp)
        return None, counts

    _with_counts(update)


def _counts_toward_limit(raw_body):
    """Only a new filing in a category the agents argue spends model calls."""
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return isinstance(body, dict) and isinstance(body.get("category"), str) \
        and body["category"] in AGENT_CATEGORIES


# The platform registers a route for a file carrying this literal entry line, so the
# shipped handler is bound to that name and extended below.
BaseHTTPRequestHandler = RydeRequestHandler


class handler(BaseHTTPRequestHandler):
    @property
    def server(self):
        return _SHIM

    @server.setter
    def server(self, value):
        self._platform_server = value

    def send_response(self, code, message=None):
        self._eo_status = code
        super().send_response(code, message)

    def _visitor(self):
        """The visitor's address as EdgeOne's edge saw it.

        Measured on the live platform: Eo-Connecting-Ip carries the real client address and the
        edge OVERWRITES any value the client sends, while EO-Client-IP and the first
        X-Forwarded-For hop are copied from the request (spoofable) and X-Real-IP is an internal
        proxy shared by everyone. Without the trusted header every request shares one bucket,
        which errs on the strict side rather than letting one visitor mint fresh identities.
        """
        value = (self.headers.get("Eo-Connecting-Ip") or "").strip()
        return value or "unknown"

    def _restore_api_prefix(self):
        if not self.path.startswith("/api/"):
            self.path = "/api" + (self.path if self.path.startswith("/") else "/" + self.path)

    def _refuse(self, status, message):
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _ready(self):
        try:
            _state()
            return True
        except Exception as exc:  # noqa: BLE001 - keys missing or provider unbuildable
            # Platform log only; the visitor gets the fixed message.
            sys.stderr.write("ryde live: state not ready: %s: %s\n" % (type(exc).__name__, exc))
            self._refuse(503, NOT_CONFIGURED_MESSAGE)
            return False

    def do_GET(self):  # noqa: N802
        self._restore_api_prefix()
        if self._ready():
            super().do_GET()

    def do_POST(self):  # noqa: N802
        self._restore_api_prefix()
        if not self._ready():
            return
        # Route exactly as the app does (urlsplit drops the query AND any fragment), so the
        # adapter and the app can never disagree about what is a filing.
        if urlsplit(self.path).path != "/api/disputes":
            super().do_POST()
            return
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            super().do_POST()  # the app refuses the malformed or oversized request itself
            return
        raw = self.rfile.read(length)
        self.rfile = io.BytesIO(raw)
        if not _counts_toward_limit(raw):
            super().do_POST()
            return
        visitor = self._visitor()
        stamp, refusal = reserve_slot(visitor)
        if refusal is not None:
            self._refuse(429, refusal)
            return
        self._eo_status = None
        try:
            super().do_POST()
        finally:
            status = self._eo_status
            if not (isinstance(status, int) and 200 <= status < 300):
                release_slot(visitor, stamp)
