# Session fourteen brief: the Tencent Cloud ADP adapter

Deliverable: every agent calls a real Tencent model. Replace the unverified guess in
`app/llm/tencent.py` with a working adapter for Tencent Cloud ADP (Agent Development
Platform), add an `--llm` flag to the server, and update config, the env template and
the docs to match. The RED acceptance tests are already committed at
`tests/test_adp_adapter.py`, with three real endpoint captures under
`tests/fixtures/adp/`. Your job is to make them green without breaking any existing test.

## Background, verified against the live endpoint on 2026-09-28

- Each agent is its own published ADP app: Ryde Rider Advocate, Ryde Driver Advocate,
  Ryde Judge. One AppKey per app. The apps carry only a short role card, so our code
  still sends the full role prompt on every call. The prompts live in this repo.
- `POST https://wss.lke.tencentcloud.com/adp/v2/chat`. The AppKey travels in the JSON
  body. There is no auth header and no request signing.
- The reply is Server-Sent Events even with `"Stream": "disable"`. The answer is in the
  `response.completed` event, at `Response.Messages[Type=reply].Contents[].Text`.
  See `tests/fixtures/adp/adp_sse_reply.txt`.
- ADP reports errors as an `error` event inside an HTTP 200. See
  `tests/fixtures/adp/adp_sse_error.txt`.
- **Tencent's web firewall** sits in front of the endpoint. When a prompt mixes
  backticks with ASCII brackets (our `docs/policy.md` does), it answers **HTTP 501**
  with a small HTML page that redirects to `waf-captcha.cloud.tencent.com`. The request
  never reaches ADP. See `tests/fixtures/adp/adp_firewall_501.html`. Escaping and gzip
  do not help. What works: drop backticks and send `( ) < > ; | $` as their full-width
  forms `（ ） ＜ ＞ ； ｜ ＄`. The model reads them identically.
- The free plan allows **10 calls a minute**. One case is 2 to 3 calls.

## Operator rulings for this session (2026-09-28, final)

1. **Replace, do not add.** The ADP adapter replaces the old TokenHub guess in
   `app/llm/tencent.py`. The provider string stays `"tencent"`, so a real ruling hides
   the demo notice through the existing rule in `app/server.py`, with no change to that
   rule or its tests.
2. **A string amount is rejected, never converted.** If a model sends
   `"requested_amount_sgd": "0.00"`, the run fails. Do not loosen `_require_number` in
   `app/schemas.py`. `StringAmountRulingTest` pins this and is green on arrival.
3. **A failed call is an explicit `LLMError`.** Firewall block, HTTP error, network
   failure, ADP error event or an unreadable reply all raise `LLMError` with a message
   naming the cause. **No retry, no fallback to the mock.** The party sees today's
   generic error. Routing a failed call to a human is a later item and is **out of
   scope** here.
4. **`--llm` flag on the server.** `python3 -m app.server --llm tencent` selects the
   real model. `app/config.json` keeps `"provider": "mock"` so the tests and a fresh
   checkout need no keys.
5. **Keys live in `.env` only**, as `TENCENT_ADP_RIDER_APP_KEY`,
   `TENCENT_ADP_DRIVER_APP_KEY` and `TENCENT_ADP_JUDGE_APP_KEY`. You do not have them and
   must not ask for them. **Do not run anything with `--llm tencent`**: the live smoke
   test is the operator's, after your work is done.

## What to build

### 1. `app/llm/tencent.py`: replace the whole file with exactly this

```python
"""Tencent Cloud ADP adapter: the real LLM provider.

The three agents are three published Tencent Cloud ADP (Agent Development Platform)
apps, one per role: Ryde Rider Advocate, Ryde Driver Advocate and Ryde Judge. Each app
carries only a short role card. This code still sends the full role prompt on every
call, so the repo stays the source of truth for what each agent is told, and every gate
that moves money stays in Python.

Protocol (checked against the live endpoint on 2026-09-28):

- ``POST <llm.endpoint>`` with a JSON body. The app's AppKey travels in the body; there
  is no auth header and no request signing.
- The reply is Server-Sent Events even with ``"Stream": "disable"``. The answer is in
  the ``response.completed`` event, at ``Response.Messages[Type=reply].Contents[].Text``.
- ADP reports errors as an ``error`` event inside an HTTP 200. The status code alone
  never proves success.
- Tencent's web firewall sits in front of the endpoint. A blocked request never
  reaches ADP: it comes back as HTTP 501 with an HTML redirect to
  ``waf-captcha.cloud.tencent.com``. The trigger is prompt content (backticks together
  with ASCII brackets), not size, so every prompt is cleaned before sending
  (``clean_for_firewall``).
- The free plan allows 10 calls a minute, so calls are spaced at least
  ``MIN_CALL_INTERVAL_SECONDS`` apart.

Every failure raises ``LLMError``. There is no retry loop and no fallback to the mock.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Mapping, Optional

from ..config import LLMSettings, read_secret
from .base import LLMClient, LLMError, LLMRequest, LLMResponse

#: One ADP app per agent. The environment variable holds that app's AppKey.
APP_KEY_ENV_VARS = {
    "rider_advocate": "TENCENT_ADP_RIDER_APP_KEY",
    "driver_advocate": "TENCENT_ADP_DRIVER_APP_KEY",
    "judge": "TENCENT_ADP_JUDGE_APP_KEY",
}
ENDPOINT_ENV_VAR = "TENCENT_ADP_ENDPOINT"

#: The free plan allows 10 calls per minute. 6.5 s between call starts stays under it.
MIN_CALL_INTERVAL_SECONDS = 6.5

#: Sent as the ADP VisitorId. Each call also gets a fresh ConversationId, so no agent
#: ever shares conversation context with another agent or with an earlier call.
VISITOR_ID = "ryde-dispute-system"

#: Values left in app/config.json until the endpoint is set. Calling with any of these
#: still present is a configuration error.
PLACEHOLDER_MARKERS = ("TODO-pin", "example/v1")

#: The firewall blocks prompts where backticks and ASCII brackets occur together. The
#: model reads the full-width forms exactly as it reads the ASCII ones.
FIREWALL_SAFE_CHARACTERS = str.maketrans(
    {
        "`": None,
        "(": "\uff08",
        ")": "\uff09",
        "<": "\uff1c",
        ">": "\uff1e",
        ";": "\uff1b",
        "|": "\uff5c",
        "$": "\uff04",
    }
)
FIREWALL_MARKER = "waf-captcha"


def clean_for_firewall(text: str) -> str:
    """Drop backticks and swap ( ) < > ; | $ for their full-width forms."""
    return text.translate(FIREWALL_SAFE_CHARACTERS)


class TencentLLMClient(LLMClient):
    """Calls the ADP app that belongs to the requesting agent. See the module docstring."""

    provider_name = "tencent"

    def __init__(
        self,
        settings: LLMSettings,
        app_keys: Optional[Mapping[str, str]] = None,
        min_interval_seconds: float = MIN_CALL_INTERVAL_SECONDS,
        **_ignored: Any,
    ):
        self.settings = settings
        self.endpoint = read_secret(ENDPOINT_ENV_VAR) or settings.endpoint
        self.model = settings.model
        if app_keys is None:
            app_keys = {agent: read_secret(var) for agent, var in APP_KEY_ENV_VARS.items()}
        self._app_keys = {agent: (app_keys.get(agent) or "") for agent in APP_KEY_ENV_VARS}
        self.min_interval_seconds = float(min_interval_seconds)
        self._pace_lock = threading.Lock()
        self._last_call_started: Optional[float] = None
        self._check_configuration()

    def _check_configuration(self) -> None:
        """Fail loudly and early. Never a silent fallback to the mock."""
        missing = [APP_KEY_ENV_VARS[agent] for agent, key in self._app_keys.items() if not key]
        if missing:
            raise LLMError(
                "missing ADP app key(s): %s. Put them in .env (see .env.example) or export "
                "them. To run without keys, use --llm mock." % ", ".join(missing)
            )
        if not self.endpoint or any(marker in self.endpoint for marker in PLACEHOLDER_MARKERS):
            raise LLMError("llm.endpoint is not set (%r); see app/config.json." % (self.endpoint,))
        if not self.model or any(marker in self.model for marker in PLACEHOLDER_MARKERS):
            raise LLMError("llm.model is not set (%r); see app/config.json." % (self.model,))

    # ------------------------------------------------------------------ interface

    def complete(self, request: LLMRequest) -> LLMResponse:
        app_key = self._app_keys.get(request.agent)
        if not app_key:
            raise LLMError("no ADP app is configured for agent %r" % (request.agent,))
        body = self._build_body(request, app_key)
        self._pace()
        status, text = self._post(body)
        return self._parse_events(status, text)

    # ------------------------------------------------------------ request / response

    def _build_body(self, request: LLMRequest, app_key: str) -> bytes:
        prompt = (
            "SYSTEM INSTRUCTIONS (follow exactly):\n"
            + request.system_prompt
            + "\n\n---\nINPUT:\n"
            + request.user_prompt
        )
        payload = {
            "RequestId": str(uuid.uuid4()),
            "ConversationId": str(uuid.uuid4()),
            "AppKey": app_key,
            "VisitorId": VISITOR_ID,
            "Contents": [{"Type": "text", "Text": clean_for_firewall(prompt)}],
            "Incremental": False,
            "Stream": "disable",
        }
        return json.dumps(payload).encode("utf-8")

    def _pace(self) -> None:
        """Hold the call until MIN interval has passed since the previous call started."""
        with self._pace_lock:
            now = time.monotonic()
            if self._last_call_started is not None:
                wait = self._last_call_started + self.min_interval_seconds - now
                if wait > 0:
                    time.sleep(wait)
                    now = time.monotonic()
            self._last_call_started = now

    def _post(self, body: bytes):
        http_request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - endpoint comes from config
                http_request, timeout=self.settings.timeout_seconds
            ) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            if exc.code == 501 or FIREWALL_MARKER in text:
                raise LLMError(
                    "the Tencent web firewall blocked the request (HTTP %s); it never "
                    "reached ADP" % exc.code
                ) from exc
            raise LLMError("ADP call failed: HTTP %s: %s" % (exc.code, text[:300])) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise LLMError("ADP call failed: cannot reach %s: %s" % (self.endpoint, exc)) from exc

    def _parse_events(self, status: int, text: str) -> LLMResponse:
        if FIREWALL_MARKER in text:
            raise LLMError(
                "the Tencent web firewall blocked the request (HTTP %s); it never reached ADP"
                % status
            )
        completed = None
        for block in text.split("\n\n"):
            data = "\n".join(
                line[len("data:"):].strip()
                for line in block.splitlines()
                if line.startswith("data:")
            )
            if not data:
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue  # the closing "data: [DONE]" frame, or noise
            if not isinstance(event, dict):
                continue
            if event.get("Type") == "error":
                error = event.get("Error") if isinstance(event.get("Error"), dict) else {}
                raise LLMError(
                    "ADP returned error %s: %s" % (error.get("Code"), error.get("Message"))
                )
            if event.get("Type") == "response.completed":
                completed = event.get("Response")

        if not isinstance(completed, dict):
            raise LLMError("ADP sent no response.completed event (HTTP %s)" % status)
        messages = completed.get("Messages")
        reply = None
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict) and message.get("Type") == "reply":
                    reply = message
        contents = reply.get("Contents") if isinstance(reply, dict) else None
        if not isinstance(contents, list):
            raise LLMError("ADP response.completed carries no reply message")
        answer = "".join(
            part.get("Text", "")
            for part in contents
            if isinstance(part, dict) and part.get("Type") == "text" and isinstance(part.get("Text"), str)
        )
        if not answer.strip():
            raise LLMError("ADP reply is empty")

        usage: Dict[str, Any] = {}
        stat = completed.get("StatInfo")
        if isinstance(stat, dict):
            tokens = stat.get("TotalTokens")
            if isinstance(tokens, int) and not isinstance(tokens, bool):
                usage["total_tokens"] = tokens

        return LLMResponse(
            text=answer,
            provider=self.provider_name,
            model=self.model,
            usage=usage,
            finish_reason=str(completed.get("Status") or "") or None,
        )
```

### 2. Everything else: apply this diff exactly

Six files: `app/server.py` (the `--llm` flag and a `provider` argument on
`make_server`), `app/config.json` (the real endpoint, a model label, and a new readme
note), `.env.example` (three keys), `app/llm/__init__.py` (docstring only),
`docs/architecture.md` (the LLM provider section and two lines under Limits) and
`README.md` (the caveat paragraph).

```diff
--- a/app/server.py
+++ b/app/server.py
@@ -26,6 +26,7 @@
 
 from __future__ import annotations
 
+import argparse
 import copy
 import json
 import os
@@ -777,17 +778,20 @@
     pack_dir: Optional[Path] = None,
     out_dir: Optional[Path] = None,
     llm: Optional[LLMClient] = None,
+    provider: Optional[str] = None,
 ) -> ThreadingHTTPServer:
     """An HTTP server bound to 127.0.0.1 only.
 
     `None` means the app/config.json default for that setting; `llm=None` builds the
-    configured provider. Tests pass port=0 and read the bound port back.
+    provider named by `provider`, or the configured one when that is None too. A real
+    provider is built here, at startup, so missing keys stop the server before any
+    party files a dispute. Tests pass port=0 and read the bound port back.
     """
     config = load_config()
     resolved_pack = Path(pack_dir) if pack_dir is not None else config.dataset_pack_dir
     resolved_out = Path(out_dir) if out_dir is not None else config.out_dir
     if llm is None:
-        provider = config.llm.provider
+        provider = provider or config.llm.provider
         if provider == "tencent":
             llm = build_llm_client(provider, settings=config.llm)
         else:
@@ -806,12 +810,29 @@
     return httpd
 
 
-def main() -> int:
-    httpd = make_server(DEFAULT_PORT)
+def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
+    parser = argparse.ArgumentParser(
+        prog="python3 -m app.server",
+        description="Serve the party page and the operator console on 127.0.0.1.",
+    )
+    parser.add_argument(
+        "--llm",
+        choices=["mock", "tencent"],
+        default=None,
+        help="LLM provider (default: app/config.json). 'tencent' calls the three ADP apps "
+        "and needs their keys in .env.",
+    )
+    return parser.parse_args(argv)
+
+
+def main(argv: Optional[List[str]] = None) -> int:
+    args = parse_args(argv)
+    httpd = make_server(DEFAULT_PORT, provider=args.llm)
     port = httpd.server_address[1]
     print("Ryde party surface on http://127.0.0.1:%d" % port)
     print("  party page:   http://127.0.0.1:%d/party/" % port)
     print("  console:      http://127.0.0.1:%d/" % port)
+    print("  llm provider: %s" % httpd.ryde_state.llm.provider_name)  # type: ignore[attr-defined]
     try:
         httpd.serve_forever()
     except KeyboardInterrupt:
--- a/app/config.json
+++ b/app/config.json
@@ -9,9 +9,10 @@
     "dataset_pack: which corpus under data/packs/ the CLI reads disputes from. The pack",
     "holds disputes/, ground-truth.json and pack.json; swapping corpora is a directory",
     "copy, never a code change. Override for one run with --pack <name>.",
-    "llm.endpoint / llm.model: placeholders. The Tencent service name and endpoint are not",
-    "pinned yet -- see the TODO in app/llm/tencent.py. The API key never goes here: it lives",
-    "in .env as TENCENT_LLM_API_KEY and .env is never committed."
+    "llm.provider: mock by default, so the tests and a fresh checkout need no keys. Run the",
+    "real model with --llm tencent (CLI or server). llm.endpoint is the Tencent Cloud ADP chat",
+    "endpoint; llm.model is the label recorded on each ruling. The three ADP app keys never",
+    "go here: they live in .env (see .env.example) and .env is never committed."
   ],
 
   "confidence_threshold": 0.65,
@@ -20,8 +21,8 @@
 
   "llm": {
     "provider": "mock",
-    "endpoint": "https://TODO-pin-tencent-llm-endpoint.example/v1/chat/completions",
-    "model": "TODO-pin-tencent-model-id",
+    "endpoint": "https://wss.lke.tencentcloud.com/adp/v2/chat",
+    "model": "tencent-adp/deepseek",
     "temperature": 0.2,
     "max_tokens": 1500,
     "timeout_seconds": 60
--- a/.env.example
+++ b/.env.example
@@ -6,10 +6,12 @@
 # .env is listed in .gitignore and the submission repo is PUBLIC. No credentials,
 # tokens or personal data in this file, ever.
 
-# Tencent Cloud LLM API key. Required when running with a real LLM provider
-# (--llm tencent). Not required for --llm mock.
-TENCENT_LLM_API_KEY=
+# Tencent Cloud ADP app keys, one per agent. Each agent is its own published ADP app,
+# and each app's AppKey is shown on its publish page. Required for --llm tencent;
+# not required for --llm mock.
+TENCENT_ADP_RIDER_APP_KEY=
+TENCENT_ADP_DRIVER_APP_KEY=
+TENCENT_ADP_JUDGE_APP_KEY=
 
-# Optional overrides. Leave blank to use the values in app/config.json.
-# TENCENT_LLM_ENDPOINT=
-# TENCENT_LLM_MODEL=
+# Optional override. Leave blank to use llm.endpoint in app/config.json.
+# TENCENT_ADP_ENDPOINT=
--- a/app/llm/__init__.py
+++ b/app/llm/__init__.py
@@ -6,8 +6,8 @@
 
 Providers:
     mock      deterministic canned responses; proves the plumbing with no API key
-    tencent   Tencent Cloud LLM API; concrete service details still to be pinned
-              (see the TODO block at the top of tencent.py)
+    tencent   Tencent Cloud ADP: one published agent app per role, called over HTTP
+              (see the module docstring of tencent.py)
 """
 
 from __future__ import annotations
@@ -22,7 +22,7 @@
 def build_llm_client(provider: str, **kwargs):
     """Build an LLM client by name.
 
-    kwargs are passed through to the adapter (e.g. settings=..., api_key=... for
+    kwargs are passed through to the adapter (e.g. settings=..., app_keys=... for
     tencent, judge_confidence=... for mock).
     """
     name = (provider or "").strip().lower()
--- a/docs/architecture.md
+++ b/docs/architecture.md
@@ -74,7 +74,7 @@
 | Output contracts | `app/schemas.py` | The typed shapes agents must produce; builds the party-facing decision message |
 | Policy loader | `app/policy.py` | Reads the policy document, extracts rule IDs, fails loudly when it is missing |
 | Mock LLM | `app/llm/mock.py` | Deterministic stand-in provider; its free-text fields — claim summaries, arguments, the Judge's explanation — carry a `MOCK` prefix, while actions, rule IDs and evidence refs do not |
-| Tencent adapter | `app/llm/tencent.py` | The real provider over HTTP; the endpoint is not pinned yet, so it is never called |
+| Tencent adapter | `app/llm/tencent.py` | The real provider: calls one Tencent Cloud ADP app per agent over HTTP |
 | HTTP server | `app/server.py` | The intake API, the party view allowlist, and static files for both pages |
 | Command-line runner | `app/cli.py` | Runs one dispute from the terminal and prints the event strip |
 | Runtime configuration | `app/config.json` | Confidence threshold, autonomous cap, default dataset pack, provider settings |
@@ -231,19 +231,28 @@
 the decision came from an illustrative run and is not a live review, shown whenever the
 ruling's LLM record does not prove the Tencent provider, and only a record whose provider
 field is exactly `tencent` shows a decision with no notice. The Tencent adapter,
-`app/llm/tencent.py`, implements the same
-interface over HTTP — and is honest about its status: the concrete service, endpoint, auth
-scheme and payload shape are not pinned yet, the configuration still carries placeholder
-values, and the adapter fails loudly rather than silently falling back to the mock. To be
-plain: the Tencent endpoint has not been called. Every run to date is a mock run, a
-plumbing demonstration rather than a model judgement.
+`app/llm/tencent.py`, implements the same interface over Tencent Cloud ADP (Agent
+Development Platform). Each agent is its own published ADP app with its own key: Rider
+Advocate, Driver Advocate and Judge. The apps carry only a short role card; the adapter
+sends the full role prompt on every call, so the prompts live in this repo and every gate
+stays in Python. Three things about the endpoint shape the adapter. Tencent's web firewall
+blocks prompts that mix backticks with ASCII brackets, so the adapter drops backticks and
+sends full-width brackets, which the model reads the same way; a blocked call raises an
+error and is never retried. ADP reports errors inside a successful HTTP response, so the
+adapter reads every event rather than trusting the status code. The free plan allows 10
+calls a minute, so calls are spaced at least 6.5 seconds apart. Any failure raises an
+error, and there is no silent fallback to the mock. The mock stays the default provider,
+so the tests and a fresh checkout need no keys; `--llm tencent` selects the real model.
 
 ## Limits
 
 What the system does not do yet, stated plainly:
 
-- **No real LLM calls.** The mock provider answers every agent. Nothing here has reasoned
-  about a dispute; the machinery around the reasoning is what is built and tested.
+- **A failed model call is an error, not a referral.** If a live call fails (the firewall,
+  the rate limit, an ADP error or a reply that breaks the output contract), the run stops
+  and the party sees a generic error. It is not yet routed to a human reviewer.
+- **Amounts must come back as JSON numbers.** A model reply carrying an amount as a string
+  is rejected, never converted, because the value moves money.
 - **Two categories only.** Route deviation and no-show charge. Property damage and safety
   incidents route to human review by design.
 - **The driver-side form is not built.** The party page files as the rider only; the
--- a/README.md
+++ b/README.md
@@ -115,8 +115,9 @@
 python3 -m app.cli --pack ryde-synth-v1 --dispute RD-0108   # withheld: no deviation to measure
 ```
 
-**One caveat while the build is in progress.** Every mock string is prefixed `MOCK`, because the
-Tencent endpoint is not pinned yet (see the TODO block in `app/llm/tencent.py`) — a mock run is a
-plumbing demonstration, never a real ruling.
+**Mock by default.** The default provider is a deterministic mock, and every mock string is
+prefixed `MOCK`: a mock run is a plumbing demonstration, never a real ruling. The real model is
+Tencent Cloud ADP, one app per agent: put the three app keys in `.env` (see `.env.example`), then
+run `python3 -m app.server --llm tencent` or `python3 -m app.cli --llm tencent --dispute <id>`.
 
 The demo walkthrough and its recording land once the case-file UI and the real LLM call are in.
```

## Out of scope: do not touch

- `app/schemas.py`, `app/pipeline.py`, `app/agents/`, `app/llm/base.py`,
  `app/llm/mock.py`, `app/cli.py` (it already has `--llm tencent`), `ui/`, `data/`,
  `docs/policy.md`, `evidence/`.
- Anything under `tests/`. The build lane never edits tests.
- The demo-notice rule in `party_view`. It already does the right thing for a
  `"tencent"` provider.
- No retry loop, no failure routing to a human, no streaming, no new dependencies.
  Standard library only.

## Constraints (standing project rules)

- The code above is the spec. If something in it looks wrong, **stop and report it**
  rather than improving it: every line is pinned by a test, and a mutation battery of
  40 corruptions against this exact code turned the suite red every time.
- The shape checks in `_parse_events` are deliberate. `isinstance(x, dict)` and
  `isinstance(x, list)` guard each level because a malformed event must raise
  `LLMError`, never `AttributeError` or `TypeError`. The tests probe 16 wrong shapes.
- Never print, log or store an AppKey. The keys are secrets, and the repo goes public.

## Verification (run these yourself before declaring done)

- `python3 -m unittest tests.test_adp_adapter -v` → 38 tests, all green.
- `python3 -m unittest discover -s tests -t .` → **475 tests, all green** (437 existing
  plus the 38 new). This count was observed on a scratch build of exactly this change.
- `python3 -m app.server --help` shows `--llm {mock,tencent}`.
- `python3 -m app.cli --dispute RD-0103` still runs on the mock and prints `llm: mock`.
- `grep -rn "not pinned yet\|TENCENT_LLM_API_KEY\|TODO(" app docs README.md .env.example`
  returns nothing.
- Report `git status` and `git diff --stat` at the end. Do not commit.
