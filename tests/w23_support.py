"""Shared helpers for the human-decision acceptance tests (non-app; nothing imports it from app/).

Every run these tests read is produced by the real pipeline: filed through the real server on
the mock, run through the real command-line runner, or driven by a scripted LLM where the mock
cannot reach a state. Where a test hand-edits a copied run it says so at the edit, and only for
shapes no pipeline produces (corrupt files, clock positions, duplicate runs).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from app.llm import LLMError, LLMResponse
from app.llm.mock import MockLLMClient

REPO = Path(__file__).resolve().parent.parent
ORG_DIR = REPO / "data" / "packs" / "organiser-style-v1"
SYNTH_DIR = REPO / "data" / "packs" / "ryde-synth-v1"
POLICY_PATH = REPO / "docs" / "policy.md"
PARTY_UI = REPO / "ui" / "party"

PARTY_VIEW_KEYS = ["run_id", "dispute_id", "status", "message", "questions"]
ACCOUNT_ENTRY_KEYS = PARTY_VIEW_KEYS + ["filed_at", "category", "trip_label"]
RECORD_KEYS = ["schema_version", "run_id", "dispute_id", "decision", "reviewer", "reason",
               "action", "amount_sgd", "proposed", "decided_at"]
QUEUE_KEYS = ["run_id", "dispute_id", "category", "safety", "amount_sgd", "amount_source",
              "waiting_seconds", "held_by", "proposed", "can_approve"]
EVENT_KEYS = ["schema_version", "seq", "ts", "run_id", "type", "from", "to", "summary", "payload_ref"]

SENTINEL_REASON = "SENTINEL-REASON-7731"
SENTINEL_REVIEWER = "Reviewer-Quill-4417"

UNDER_REVIEW = "Your case is still under review. We will let you know as soon as a decision is made."
HUMAN_SENTENCE = "A member of our team reviewed your case."


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strip_js_comments(source: str) -> str:
    """Drop /* */ and // comments so a comment can never satisfy a pin."""
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?<![:\"'])//[^\n]*", "", source)


def js_function_body(source: str, name: str) -> str:
    """The brace-matched body of `function <name>(...) { ... }`, comments stripped."""
    code = strip_js_comments(source)
    match = re.search(r"function\s+%s\s*\(" % re.escape(name), code)
    if match is None:
        raise AssertionError("no function %s" % name)
    start = code.index("{", match.end())
    depth = 0
    for index in range(start, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if depth == 0:
                return code[start:index + 1]
    raise AssertionError("unbalanced braces in function %s" % name)


def html_text(html: str) -> str:
    """Visible text of an HTML page, tags dropped and whitespace collapsed."""
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# ------------------------------------------------------------------- LLM stand-ins


class JudgeScript(MockLLMClient):
    """The mock for both advocates; the Judge answers with a fixed payload.

    Used where a test needs a proposal the mock never makes (an amount that differs from
    the claim, particular rule citations).
    """

    def __init__(self, judge: Dict[str, Any]):
        super().__init__()
        self.judge = judge

    def complete(self, request):
        if request.agent == "judge":
            return LLMResponse(text=json.dumps(self.judge), provider="mock", model="judge-script")
        return super().complete(request)


def judge_payload(action="refund", amount=55.16, cited=("RD-1", "RD-2", "RD-3"), confidence=0.9):
    return {
        "action": action,
        "recommended_amount_sgd": amount,
        "confidence": confidence,
        "explanation": "scripted ruling",
        "cited_rule_ids": list(cited),
        "cited_evidence_refs": [],
    }


class JudgeFails(MockLLMClient):
    """Every Judge call fails permanently: the real model-failure escalation path."""

    def complete(self, request):
        if request.agent == "judge":
            raise LLMError("the endpoint refused the request (HTTP 501)")
        return super().complete(request)


# ------------------------------------------------------------------------ server


class Server:
    """The real server, in process, on an ephemeral loopback port."""

    def __init__(self, llm=None, pack_dir=None):
        from app.server import make_server

        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.httpd = make_server(port=0, pack_dir=pack_dir, out_dir=self.out,
                                 llm=llm if llm is not None else MockLLMClient())
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def set_llm(self, llm):
        self.httpd.ryde_state.llm = llm

    def raw(self, method, path, body=None, data=None):
        """(status, headers, raw bytes)."""
        if data is None and body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    def json(self, method, path, body=None, data=None):
        status, _headers, raw = self.raw(method, path, body, data)
        return status, (json.loads(raw) if raw else None)

    # ---------------------------------------------------------------- filings

    def file(self, trip_id="T-RD0109", claim=55.16, safety="No", filed_by="rider",
             category="route_deviation", answers=None, expected_route="Expressway, about 31 km."):
        if answers is None:
            if category == "route_deviation":
                answers = {"expected_route": expected_route, "was_route_agreed": "No",
                           "asked_driver_to_stop": "No", "safety_concern": safety}
            elif category == "no_show_charge":
                answers = {"where_were_you": "At the pickup point.", "did_driver_contact_you": "No",
                           "safety_concern": safety}
            else:
                answers = {}
        body = {"category": category, "filed_by": filed_by, "trip_id": trip_id,
                "description": "He went a very long way round.", "claim_amount_sgd": claim,
                "answers": answers}
        status, view = self.json("POST", "/api/disputes", body)
        if status != 200:
            raise AssertionError("filing refused: %s %s" % (status, view))
        return view

    def run_dir(self, run_id) -> Path:
        return self.out / run_id

    def case(self, run_id) -> Dict[str, Any]:
        return json.loads((self.out / run_id / "case_file.json").read_text(encoding="utf-8"))

    def decide(self, run_id, body):
        return self.json("POST", "/api/review/%s/decision" % run_id, body)

    def cli_run(self, dispute="RD-0109", pack="ryde-synth-v1", run_id="cli-run-0001"):
        """A run made by the real command-line runner into the server's output folder."""
        from app import cli

        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["--pack", pack, "--dispute", dispute, "--out", str(self.out),
                             "--run-id", run_id, "--llm", "mock"])
        if code not in (0, None):
            raise AssertionError("cli run failed with %r" % code)
        return run_id

    def copy_run(self, run_id, new_name, *, edit_case=None, edit_dispute=None, parent=None) -> Path:
        """HAND-MADE SHAPE: a copy of a real run under another folder name, with the run id
        inside rewritten to match, plus optional edits. Callers say why they need one."""
        src = self.out / run_id
        dst = (parent if parent is not None else self.out) / new_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
        case = json.loads((dst / "case_file.json").read_text(encoding="utf-8"))
        case["run_id"] = new_name
        if edit_case:
            edit_case(case)
        (dst / "case_file.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        if edit_dispute and (dst / "dispute.json").exists():
            record = json.loads((dst / "dispute.json").read_text(encoding="utf-8"))
            edit_dispute(record)
            (dst / "dispute.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return dst


def body(decision="change", reviewer="Ana Lim", reason="The detour was not agreed.", **extra):
    out: Dict[str, Any] = {"decision": decision, "reviewer": reviewer, "reason": reason}
    out.update(extra)
    return out


def events(run_dir: Path):
    return [json.loads(line) for line in (Path(run_dir) / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


_POLICY = None


def policy():
    global _POLICY
    if _POLICY is None:
        from app.policy import load_policy

        _POLICY = load_policy(POLICY_PATH)
    return _POLICY


def pipeline_case(pack_dir: Path, name: str, *, claim: Optional[float] = None, llm=None,
                  run_id="w23-pipeline", tmp: Optional[Path] = None) -> Dict[str, Any]:
    """A case file produced by the real pipeline on one pack record (claim optionally set)."""
    import copy

    from app.dispute import is_organiser_record, parse_dispute
    from app.events import EventLog
    from app.pipeline import run_dispute

    record = copy.deepcopy(json.loads((pack_dir / "disputes" / name).read_text(encoding="utf-8")))
    if claim is not None:
        if is_organiser_record(record):
            record.setdefault("ryde_extensions", {}).setdefault("claim", {})["amount_sgd"] = claim
        else:
            record.setdefault("claim", {})["amount_sgd"] = claim
    with tempfile.TemporaryDirectory() as scratch:
        case = run_dispute(
            dispute=parse_dispute(record),
            llm=llm if llm is not None else MockLLMClient(),
            policy=policy(),
            events=EventLog(Path(tmp or scratch) / run_id, run_id),
            confidence_threshold=0.65,
            autonomous_cap_sgd=50.00,
        )
        return case.to_dict()
