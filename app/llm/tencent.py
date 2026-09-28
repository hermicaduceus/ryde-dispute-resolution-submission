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
