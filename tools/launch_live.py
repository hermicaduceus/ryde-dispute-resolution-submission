"""Start the Ryde server against the reviewed Tencent ADP provider."""
from __future__ import annotations

import argparse
import errno
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app.server as server  # noqa: E402
from app.config import ConfigError, load_config, load_env_file  # noqa: E402
from app.llm import LLMError  # noqa: E402

LIVE_PORT = 8030
PARTY_PATH = "/party/"
PROVIDER = "tencent"
ROLE_KEY_ENV_VARS = (
    "TENCENT_ADP_RIDER_APP_KEY",
    "TENCENT_ADP_DRIVER_APP_KEY",
    "TENCENT_ADP_JUDGE_APP_KEY",
)
ENDPOINT_ENV_VAR = "TENCENT_ADP_ENDPOINT"
ALLOWED_ENV_VARS = ROLE_KEY_ENV_VARS + (ENDPOINT_ENV_VAR,)
REVIEWED_ENDPOINT = "https://wss.lke.tencentcloud.com/adp/v2/chat"
START_FAILED = "The live Ryde server could not start. Check the private credentials and reviewed configuration."

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class CredentialError(ValueError):
    """The selected live sidecar is unreadable or does not meet its contract."""


def credentials_path(repo: Path, explicit: Optional[Path]) -> Path:
    return Path(explicit) if explicit is not None else Path(repo) / ".env.live"


def _read_sidecar(path: Path) -> str:
    try:
        raw = Path(path).read_bytes()
    except (OSError, IOError):
        raise CredentialError("credentials file %s could not be read" % Path(path).name) from None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CredentialError("credentials file %s is not valid UTF-8" % Path(path).name) from None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_credentials(path: Path) -> Dict[str, str]:
    """Validate one sidecar before letting the application's env parser read it."""
    text = _read_sidecar(Path(path))
    seen = set()
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            raise CredentialError("malformed assignment on line %d" % number)
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise CredentialError("malformed assignment on line %d" % number)
        if key not in ALLOWED_ENV_VARS:
            raise CredentialError("unsupported variable name %s" % key)
        if key in seen:
            raise CredentialError("duplicate variable name %s" % key)
        seen.add(key)
        value = value.strip()
        if value.startswith(("'", '"')) or value.endswith(("'", '"')):
            if not (len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"):
                raise CredentialError("malformed assignment on line %d" % number)

    try:
        parsed = load_env_file(Path(path))
    except (OSError, IOError, UnicodeError):
        raise CredentialError("credentials file %s could not be read" % Path(path).name) from None
    return {key: parsed.get(key, "") for key in seen}


def _is_placeholder(value: object) -> bool:
    if not isinstance(value, str):
        return True
    marker = value.strip().lower()
    if not marker:
        return True
    if marker in {
        "todo",
        "placeholder",
        "your-key-here",
        "your_key_here",
        "your-app-key-here",
        "your_app_key_here",
        "change-me",
        "changeme",
        "replace-me",
    }:
        return True
    return marker.startswith("todo-") or marker.startswith("your-") or marker.startswith("your_") or marker.startswith("<")


def missing_role_keys(values: Dict[str, str]):
    return [key for key in ROLE_KEY_ENV_VARS if _is_placeholder(values.get(key))]


def endpoint_is_bad(values: Dict[str, str]) -> bool:
    if ENDPOINT_ENV_VAR not in values:
        return False
    return values.get(ENDPOINT_ENV_VAR) != REVIEWED_ENDPOINT


def apply_credentials(values: Dict[str, str]) -> None:
    for name in ALLOWED_ENV_VARS:
        os.environ.pop(name, None)
    for name in ROLE_KEY_ENV_VARS:
        if name in values:
            os.environ[name] = values[name]
    if ENDPOINT_ENV_VAR in values:
        os.environ[ENDPOINT_ENV_VAR] = values[ENDPOINT_ENV_VAR]


def shipped_endpoint():
    try:
        return load_config().llm.endpoint
    except (ConfigError, AttributeError):
        return None


def shipped_endpoint_ok() -> bool:
    try:
        return shipped_endpoint() == REVIEWED_ENDPOINT
    except Exception:
        return False


def _port_number(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer between 1 and 65535") from None
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return value


def _answer(url: str):
    try:
        with _opener.open(url, timeout=1.0) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def _open(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def open_when_ready(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if _answer(url) == 200:
            break
        if time.monotonic() >= deadline:
            print("Could not open a browser. Open %s yourself." % url)
            return
        time.sleep(0.1)
    if not _open(url):
        print("Could not open a browser. Open %s yourself." % url)


def _close(httpd) -> None:
    try:
        httpd.server_close()
    except Exception:
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 tools/launch_live.py",
        description="Start the local Ryde server with Tencent AI and a private .env.live sidecar.",
    )
    parser.add_argument("--credentials", type=Path, default=None, metavar="PATH",
                        help="live credential sidecar (default: <package-root>/.env.live)")
    parser.add_argument("--port", type=_port_number, default=LIVE_PORT,
                        help="TCP port to bind on 127.0.0.1 (default: %(default)s)")
    args = parser.parse_args(argv)

    path = credentials_path(REPO_ROOT, args.credentials)
    try:
        values = parse_credentials(path)
    except CredentialError as exc:
        print(str(exc))
        return 1

    missing = missing_role_keys(values)
    if missing:
        print("missing required credential variable(s): %s" % ", ".join(missing))
        return 1
    if endpoint_is_bad(values):
        print("%s must equal the reviewed Tencent ADP endpoint" % ENDPOINT_ENV_VAR)
        return 1
    if not shipped_endpoint_ok():
        print("app/config.json does not use the reviewed Tencent ADP endpoint")
        return 1

    apply_credentials(values)
    os.environ[ENDPOINT_ENV_VAR] = REVIEWED_ENDPOINT

    try:
        httpd = server.make_server(args.port, provider=PROVIDER)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, 10048):
            print("Port %d is already in use. Choose another port." % args.port)
            return 1
        raise
    except (LLMError, ConfigError):
        print(START_FAILED)
        return 1

    state = getattr(httpd, "ryde_state", None)
    llm = getattr(state, "llm", None)
    if getattr(llm, "provider_name", None) != PROVIDER:
        _close(httpd)
        print("The live launcher requires the Tencent provider; no fallback was used.")
        return 1

    port = httpd.server_address[1]
    party_url = "http://127.0.0.1:%d%s" % (port, PARTY_PATH)
    console_url = "http://127.0.0.1:%d/" % port
    status_url = "http://127.0.0.1:%d/party/status.html" % port
    print("Ryde live server on http://127.0.0.1:%d" % port)
    print("  party page:   %s" % party_url)
    print("  console:      %s" % console_url)
    print("  status page:  %s" % status_url)
    print("  llm provider: %s" % PROVIDER)

    browser_thread = threading.Thread(target=open_when_ready, args=(party_url,), daemon=True)
    browser_thread.start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _close(httpd)
        browser_thread.join(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
