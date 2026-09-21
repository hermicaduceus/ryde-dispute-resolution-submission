"""Tencent Cloud LLM adapter.

STATUS: UNVERIFIED. The concrete Tencent service name, endpoint, auth header and
payload shape are NOT pinned yet. This adapter exists so the rest of the system can be
built and tested against the `LLMClient` interface; it has never been run against a live
endpoint and must not be presented as working until the TODOs below are resolved and a
real call has been exercised.

TODO(service-pin)   Which Tencent Cloud service this targets — Tencent Cloud's LLM
                    offering, an Agent Sandbox runtime, or another product. This decides
                    everything else in this file.
TODO(endpoint-pin)  The exact base URL, and whether the model id belongs in the path or
                    the body.
TODO(auth-pin)      The exact auth scheme. Currently assumed: `Authorization: Bearer
                    <TENCENT_LLM_API_KEY>`. Replace if the service signs requests another
                    way.
TODO(payload-pin)   The request body shape. Currently assumed OpenAI-style chat
                    completions. Confirm field names for system/user messages and
                    token limits.
TODO(response-pin)  Where the assistant text lives in the response. Currently assumed
                    `choices[0].message.content`. Confirm, and confirm the error shape.

Resolution procedure: pin the five items above, set llm.endpoint and llm.model in
app/config.json (or TENCENT_LLM_ENDPOINT / TENCENT_LLM_MODEL in .env), put
TENCENT_LLM_API_KEY in .env, then run
`python -m app.cli --llm tencent --dispute <path>` and check the real response.

Nothing outside this file needs to change when that happens: agents only ever call
`LLMClient.complete`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..config import LLMSettings, read_secret
from .base import LLMClient, LLMError, LLMRequest, LLMResponse

API_KEY_ENV_VAR = "TENCENT_LLM_API_KEY"
ENDPOINT_ENV_VAR = "TENCENT_LLM_ENDPOINT"
MODEL_ENV_VAR = "TENCENT_LLM_MODEL"

# Markers left in app/config.json until the service is pinned. Calling with any of
# these still present is a configuration error, not something to paper over.
PLACEHOLDER_MARKERS = ("TODO-pin", "example/v1")


class TencentLLMClient(LLMClient):
    """Thin adapter over the Tencent Cloud LLM HTTP API. See the module docstring."""

    provider_name = "tencent"

    def __init__(self, settings: LLMSettings, api_key: Optional[str] = None, **_ignored: Any):
        self.settings = settings
        self.api_key = api_key if api_key is not None else read_secret(API_KEY_ENV_VAR)
        self.endpoint = read_secret(ENDPOINT_ENV_VAR) or settings.endpoint
        self.model = read_secret(MODEL_ENV_VAR) or settings.model
        self._check_configuration()

    def _check_configuration(self) -> None:
        """Fail loudly and early — never a silent fallback to mock."""
        if not self.api_key:
            raise LLMError(
                "%s is not set. Put it in .env (see .env.example) or export it. "
                "To run without a key, use --llm mock." % API_KEY_ENV_VAR
            )
        if not self.endpoint or any(marker in self.endpoint for marker in PLACEHOLDER_MARKERS):
            raise LLMError(
                "llm.endpoint is not pinned yet (%r). The Tencent service name and endpoint "
                "must be decided first — see the TODO block at the top of app/llm/tencent.py."
                % (self.endpoint,)
            )
        if not self.model or any(marker in self.model for marker in PLACEHOLDER_MARKERS):
            raise LLMError(
                "llm.model is not pinned yet (%r). See the TODO block at the top of "
                "app/llm/tencent.py." % (self.model,)
            )

    # ------------------------------------------------------------------ interface

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._build_payload(request)
        raw = self._post(payload)
        return self._parse_response(raw)

    # ------------------------------------------------------------ request / response

    def _build_payload(self, request: LLMRequest) -> Dict[str, Any]:
        # TODO(payload-pin): confirm the message field names and token-limit field.
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            # TODO(auth-pin): confirm the auth scheme.
            "Authorization": "Bearer %s" % self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        http_request = urllib.request.Request(
            self.endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - endpoint comes from config
                http_request, timeout=self.settings.timeout_seconds
            ) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(
                "Tencent LLM call failed: HTTP %s from %s: %s" % (exc.code, self.endpoint, detail)
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMError("Tencent LLM call failed: cannot reach %s: %s" % (self.endpoint, exc)) from exc

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(
                "Tencent LLM returned a non-JSON body: %r" % (text[:400],)
            ) from exc
        if not isinstance(parsed, dict):
            raise LLMError("Tencent LLM returned %s, expected a JSON object" % type(parsed).__name__)
        if "error" in parsed:
            raise LLMError("Tencent LLM returned an error: %s" % json.dumps(parsed["error"])[:500])
        return parsed

    def _parse_response(self, raw: Dict[str, Any]) -> LLMResponse:
        # TODO(response-pin): confirm the path to the assistant text.
        text = ""
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first.get("message"), dict) else {}
            text = message.get("content") or first.get("text") or ""
        if not text:
            raise LLMError(
                "could not find assistant text in the Tencent response; "
                "check the response shape (TODO(response-pin) in app/llm/tencent.py): %s"
                % json.dumps(raw)[:400]
            )

        finish_reason = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            finish_reason = choices[0].get("finish_reason")

        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=str(raw.get("model") or self.model),
            usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else {},
            finish_reason=finish_reason,
        )
