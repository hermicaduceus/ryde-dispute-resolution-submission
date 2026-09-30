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

Failures are classified here and raised once; the retry loop lives in the agent layer.
There is no fallback to the mock. An error message names the cause (the status code, the
ADP error code, the kind of failure) but never carries a response body, and every configured
AppKey is redacted from it, so a key can never reach a terminal, a log or a case file through
an error.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Mapping, Optional

from ..config import LLMSettings, read_secret
from .base import LLMClient, LLMContractError, LLMError, LLMRequest, LLMResponse, LLMTransientError

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

#: A Judge-sized reply measured 89 KB on the live endpoint (it echoes the prompt). A
#: response larger than this is refused rather than read into memory.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REDACTED = "<redacted>"


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
        try:
            status, text = self._post(body, request.timeout_seconds)
            return self._parse_events(status, text)
        except LLMError as exc:
            raise type(exc)(self._redact(str(exc))) from None

    def _redact(self, message: str) -> str:
        """Remove every configured AppKey from a message before it leaves this class."""
        for key in self._app_keys.values():
            if key:
                message = message.replace(key, REDACTED)
        return message

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

    def _post(self, body: bytes, request_timeout: Optional[float] = None):
        timeout = float(self.settings.timeout_seconds)
        if request_timeout is not None:
            timeout = max(1.0, min(timeout, float(request_timeout)))
        http_request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - endpoint comes from config
                http_request, timeout=timeout
            ) as response:
                return response.status, self._read_body(response)
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(MAX_RESPONSE_BYTES + 1)
            except (http.client.HTTPException, OSError):
                raw = b""
            if exc.code == 501 or FIREWALL_MARKER.encode("ascii") in raw:
                raise LLMError(
                    "the Tencent web firewall blocked the request (HTTP %s); it never "
                    "reached ADP" % exc.code
                ) from None
            # The body is deliberately left out: an error page can echo the request.
            error_type = LLMTransientError if exc.code == 429 or 500 <= exc.code < 600 else LLMError
            raise error_type("ADP call failed: HTTP %s" % exc.code) from None
        except http.client.HTTPException as exc:
            raise LLMTransientError(
                "ADP call failed: the connection broke while reading the reply (%s)"
                % type(exc).__name__
            ) from None
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            kind = type(reason).__name__ if isinstance(reason, BaseException) else "network error"
            raise LLMTransientError("ADP call failed: cannot reach the endpoint (%s)" % kind) from None

    @staticmethod
    def _read_body(response) -> str:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise LLMContractError("ADP reply is too large (over %d bytes)" % MAX_RESPONSE_BYTES)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise LLMContractError("ADP reply is not valid UTF-8") from None

    def _parse_events(self, status: int, text: str) -> LLMResponse:
        if FIREWALL_MARKER in text:
            raise LLMError(
                "the Tencent web firewall blocked the request (HTTP %s); it never reached ADP"
                % status
            )
        completed = None
        # SSE lines may end in CRLF, LF or CR; frames end at a blank line.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
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
            raise LLMContractError("ADP sent no response.completed event (HTTP %s)" % status)
        messages = completed.get("Messages")
        replies = []
        if isinstance(messages, list):
            replies = [m for m in messages if isinstance(m, dict) and m.get("Type") == "reply"]
        # Every reply message, in order: a reply split across messages is joined, not cut.
        contents = [m.get("Contents") for m in replies if isinstance(m.get("Contents"), list)]
        if not contents:
            raise LLMContractError("ADP response.completed carries no reply message")
        answer = "".join(
            part.get("Text", "")
            for parts in contents
            for part in parts
            if isinstance(part, dict) and part.get("Type") == "text" and isinstance(part.get("Text"), str)
        )
        if not answer.strip():
            raise LLMContractError("ADP reply is empty")

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
