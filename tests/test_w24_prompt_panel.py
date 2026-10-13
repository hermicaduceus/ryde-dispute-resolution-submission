"""W24 acceptance target: the console panel that shows what each agent was asked.

Written RED-first by the planner's RED-test preparer against BASE 023d2cc. the operator rulings in force
(2026-10-06): R1(a) the console deep link ?run=<run_id> is in scope; R5(a) ui/styles.css is
untouched, so the panel reuses existing classes.

The contract (the brief carries it in full):

  * app/prompt_view.py exposes build_prompt_view(run_dir: Path, policy) -> dict. It rebuilds
    each agent's system and user prompt with the UNCHANGED builders, from the run's stored
    payloads (dispute.filed, evidence.pack_built, the two advocate.case_submitted payloads and
    the Judge's ruling payload) plus the policy the server loaded, and compares
    LLMRequest(agent, system_prompt, user_prompt).fingerprint() to the stored
    llm.request_fingerprint. It never calls a model and never writes.
  * GET /api/review/<run_id>/prompts answers 200 with {"run_id", "agents": [rider, driver,
    judge]} through _resolve_run_dir (404 for unknown or traversal), never a 500.
  * ui/index.html gains #prompts-section between #evidence-section and #claims-section;
    ui/app.js renders one <article> per agent with a status badge, a <dl> summary and the full
    text inside <details><summary>Show full text</summary><pre>, guards stale responses with
    one generation-checked settle path, and opens ?run=<id> through the queue-open path.
  * No party route carries a prompt; party JS never requests /prompts; the agent, model,
    pipeline, schema, dispute, policy and evidence sources stay byte-identical.

Which payload holds a given advocate's case is found by event type and sender, never by a fixed
sequence number: on a needs_info stop the driver's case is payload 0008, not 0007, because the
rider's follow-up request sits between them.

The fake-DOM driver below extends tests/w23_b2_support.HARNESS (the console instrument), not the
application. Its context provides window.location (search, pathname, hash, href), a global
`location` (the same object), URLSearchParams and URL, so app.js may read the deep link through
any of them. Real-browser behaviour is tests/browser/w24_prompt_panel.cjs, driven by
RealBrowserPromptPanel below when PUPPETEER_MODULE and BROWSER_EXECUTABLE are set (the planner
runs it; it skips otherwise).

Run: env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w24_prompt_panel -v
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from app.agents.base import HARD_RULES
from app.dispute import parse_dispute
from app.events import EventLog
from app.llm.base import LLMRequest
from app.llm.mock import MockLLMClient
from app.llm.tencent import TencentLLMClient
from app.pipeline import run_dispute
from app.policy import PolicySet
from tests.w23_b2_support import HARNESS, NODE, base_routes, ok, queue_row
from tests.w23_support import ORG_DIR, JudgeFails, Server, policy, strip_js_comments

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "ui"

AGENTS = ["rider_advocate", "driver_advocate", "judge"]
LABELS = ["Rider Advocate", "Driver Advocate", "Judge"]
STATUSES = {"match", "changed", "not_called", "unavailable"}
ENTRY_KEYS = {"agent", "label", "status", "recorded_fingerprint", "rebuilt_fingerprint",
              "summary", "system_prompt", "user_prompt"}
SUMMARY_KEYS = {"role", "hard_rules", "case_facts", "advocate_positions", "policy",
                "asked_to_return"}
ROLES = {
    "rider_advocate": "Argues the rider's side from the Evidence Pack and the policy.",
    "driver_advocate": "Argues the driver's side from the Evidence Pack and the policy.",
    "judge": "Weighs both cases and issues one ruling. Python gates decide whether it reaches the parties.",
}
HARD_RULE_LINES = [
    "1. Never do arithmetic. Every number you state must be copied verbatim from the Evidence "
    "Pack. If a number you want is not in the pack, say it is unavailable \u2014 do not compute it.",
    "2. Cite evidence only by the exact dotted references listed under CITABLE EVIDENCE REFS.",
    "3. Cite policy only by rule IDs listed under POLICY RULE IDS. Never invent a rule ID.",
    "4. Return exactly one JSON object matching the schema below. No prose around it, no code "
    "fence, no commentary.",
]
ADVOCATE_RETURNS = ["claim_summary", "evidence_cited", "policy_rule_ids", "argument",
                    "requested_outcome", "requested_amount_sgd", "follow_up_slots"]
JUDGE_RETURNS = ["action", "recommended_amount_sgd", "confidence", "explanation",
                 "cited_rule_ids", "cited_evidence_refs"]

BADGE_CHANGED = "The prompts have changed since this run. Showing today's version."
BADGE_NOT_CALLED = "This agent was not called in this run."
BADGE_UNAVAILABLE = "Not available for this run."
FAILURE = "Not available: open this case through the local server."
UNKNOWN_RUN = "Unknown run."
SHOW_FULL_TEXT = "Show full text"

# Measured on BASE 023d2cc through the real CLI runner on the mock (organiser-style-v1).
NS0202_FACTS = {"evidence_sections": ["route", "duration", "fare", "cancellation", "chat",
                                      "profiles", "filing"],
                "citable_refs": 56, "form_answers": 4, "claim_amount_sgd": 6.61}
RD0109_FACTS = {"evidence_sections": ["route", "duration", "fare", "chat", "profiles", "filing"],
                "citable_refs": 59, "form_answers": 5, "claim_amount_sgd": 55.16}
NS0202_POSITIONS = [{"side": "rider", "outcome": "refund", "amount_sgd": 6.61},
                    {"side": "driver", "outcome": "no action", "amount_sgd": 0.0}]

# The runtime the panel must not touch, hashed at BASE 023d2cc.
FROZEN_RUNTIME = {
    "app/agents/__init__.py": "3880e0f6bddf40af77c0c8fc224cde247c7b98e617aff17d0336d2eda1d2dd0b",
    "app/agents/base.py": "a0398140287d42673034e09ea8438129793c6492b6d1745d4509d3f0cae34fd5",
    "app/agents/driver_advocate.py": "b104c5afce054f7f2fb7cedec55ae80c04defb015e9cfdff7e7fc8a185cbd117",
    "app/agents/judge.py": "f3d03f6664389178dbdb35f6f12483f647cc1495469f72150eaae72e367d59c0",
    "app/agents/rider_advocate.py": "0b782098a399861315be03768f88cc6b821a43556a5fd278c0b6b5e27c03281d",
    "app/dispute.py": "1705daa66a897b7f4c265a506b592d153a8888e8ebf112e57631007cd31bae8c",
    "app/evidence/__init__.py": "befc73254285cb0e6fb5039b5bd7c96cf321430e643a9295022ce17f34e3e6c4",
    "app/evidence/compute.py": "7875ef3282371575a3092eb9746c08d2ebca0d919af3a16a9fb77e958c73d559",
    "app/evidence/schema.py": "c43dde67551b751c98383700b98d0c305c9a970031e109713108430044ca59f3",
    "app/llm/__init__.py": "014cc053124a4bf057bba9c3f2760c83eae0f37f3a7ac729d8e782db34c258ac",
    "app/llm/base.py": "dda8c03d2a79d37ac68d1a4f848937533af9a49f982d2bb26535d8269cf1aae4",
    "app/llm/mock.py": "37777c29c01460750df771d446b673ddb00245356e5a4f4568d069aa3a05d496",
    "app/llm/tencent.py": "fc1d122fce5bb4b73827786598a8825432b80faf33c7e88278d977f2c732a851",
    "app/pipeline.py": "1725249bde875d9d3b317e5b414d35042756bd85f8cfab8b2baee5664386f0f0",
    "app/policy.py": "0d2899305cf68260f3748fa030f304183edcbb8a44fddeaedda7ed3bdd00c4e5",
    "app/schemas.py": "371334cabd7a75f23dd2f6cb353adccfef48b16fb0197befe5e80e6b33360ce5",
}
# W35 lane C released STYLES_CSS_SHA: that round edits ui/styles.css (tests/test_w35_C.py pins it).

PROMPT_LEAK_TOKENS = ("system_prompt", "user_prompt", "HARD RULES", "Never do arithmetic",
                      "POLICY DOCUMENT", "OUTPUT SCHEMA", "CITABLE EVIDENCE REFS", "/prompts")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(run_dir: Path):
    return [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def _payload_path(run_dir: Path, event_type: str, sender=None) -> Path:
    for event in _events(run_dir):
        if event["type"] == event_type and (sender is None or event["from"] == sender):
            return run_dir / event["payload_ref"]
    raise AssertionError("fixture run %s has no %s event" % (run_dir.name, event_type))


def _stored_fingerprint(run_dir: Path, agent: str) -> str:
    """The fingerprint the run recorded for this agent, read straight from its payload."""
    if agent == "judge":
        for kind, key in (("judge.ruling_issued", "ruling"), ("judge.ruling_withheld", "withheld_candidate")):
            try:
                data = json.loads(_payload_path(run_dir, kind).read_text(encoding="utf-8"))
            except AssertionError:
                continue
            return data[key]["llm"]["request_fingerprint"]
        raise AssertionError("no Judge ruling payload in %s" % run_dir.name)
    data = json.loads(_payload_path(run_dir, "advocate.case_submitted", agent).read_text(encoding="utf-8"))
    return data["llm"]["request_fingerprint"]


def _tree_digest(root: Path):
    return {str(p.relative_to(root)): _sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


class _Runs:
    """One real server per test class, with every run shape the contract names."""

    @classmethod
    def make(cls):
        server = Server()
        runs = {}
        # Filed through the real server: its mock keeps the exact LLMRequests it was sent.
        view = server.file()  # T-RD0109, claim 55.16: withheld by ESC-4
        runs["filed"] = view["run_id"]
        calls = list(server.httpd.ryde_state.llm.calls)
        runs["ruled"] = server.cli_run(dispute="NS-0202", pack="organiser-style-v1", run_id="w24-ruled")
        runs["withheld"] = server.cli_run(dispute="RD-0109", pack="organiser-style-v1", run_id="w24-withheld")
        runs["oos"] = server.cli_run(dispute="OS-0301", pack="organiser-style-v1", run_id="w24-oos")
        record = json.loads((ORG_DIR / "disputes" / "RD-0101.json").read_text(encoding="utf-8"))
        record["ryde_extensions"]["intake"]["expected_route"] = "   "  # the mock asks the filer
        runs["needs_info"] = cls._pipeline(server, record, "w24-needs-info", MockLLMClient())
        record = json.loads((ORG_DIR / "disputes" / "RD-0109.json").read_text(encoding="utf-8"))
        runs["judge_failed"] = cls._pipeline(server, record, "w24-judge-failed", JudgeFails())
        return server, runs, calls

    @staticmethod
    def _pipeline(server, record, run_id, llm):
        run_dir = server.out / run_id
        case = run_dispute(dispute=parse_dispute(record), llm=llm, policy=policy(),
                           events=EventLog(run_dir, run_id), confidence_threshold=0.65,
                           autonomous_cap_sgd=50.00)
        case.write(run_dir)
        return run_id


class _ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.runs, cls.calls = _Runs.make()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def prompts(self, run_id, expect=200):
        status, body = self.server.json("GET", "/api/review/%s/prompts" % run_id)
        self.assertEqual(expect, status, "GET /api/review/%s/prompts answered %s: %r" % (run_id, status, body))
        return body

    def agents(self, run_id):
        body = self.prompts(run_id)
        self.assertIsInstance(body, dict)
        entries = body.get("agents")
        self.assertIsInstance(entries, list)
        self.assertEqual(AGENTS, [e.get("agent") for e in entries])
        return {e["agent"]: e for e in entries}

    def copy(self, key, name, edit):
        dst = self.server.copy_run(self.runs[key], name)
        edit(dst)
        return name


# ============================================================ route and module


class PromptRoute(_ServerCase):
    def test_answers_the_three_agents_in_contract_order_with_their_labels(self):
        body = self.prompts(self.runs["ruled"])
        self.assertEqual(self.runs["ruled"], body.get("run_id"))
        self.assertEqual({"run_id", "agents"}, set(body))
        self.assertEqual(AGENTS, [e.get("agent") for e in body["agents"]])
        self.assertEqual(LABELS, [e.get("label") for e in body["agents"]])
        for entry in body["agents"]:
            self.assertEqual(ENTRY_KEYS, set(entry))
            self.assertEqual(SUMMARY_KEYS, set(entry["summary"]))

    def test_ruled_run_rebuilds_every_fingerprint_it_recorded(self):
        run_dir = self.server.run_dir(self.runs["ruled"])
        for name, entry in self.agents(self.runs["ruled"]).items():
            with self.subTest(agent=name):
                stored = _stored_fingerprint(run_dir, name)
                self.assertEqual("match", entry["status"])
                self.assertEqual(stored, entry["recorded_fingerprint"])
                self.assertEqual(stored, entry["rebuilt_fingerprint"])
                rebuilt = LLMRequest(agent=name, system_prompt=entry["system_prompt"],
                                     user_prompt=entry["user_prompt"]).fingerprint()
                self.assertEqual(stored, rebuilt, "the prompts shown must be the ones fingerprinted")

    def test_withheld_run_matches_through_the_withheld_candidate(self):
        run_dir = self.server.run_dir(self.runs["withheld"])
        for name, entry in self.agents(self.runs["withheld"]).items():
            with self.subTest(agent=name):
                self.assertEqual("match", entry["status"])
                self.assertEqual(_stored_fingerprint(run_dir, name), entry["recorded_fingerprint"])

    def test_prompts_are_exactly_what_the_model_was_sent(self):
        self.assertEqual(AGENTS, [c.agent for c in self.calls], "fixture: one call per agent")
        entries = self.agents(self.runs["filed"])
        for call in self.calls:
            with self.subTest(agent=call.agent):
                entry = entries[call.agent]
                self.assertEqual("match", entry["status"])
                self.assertEqual(call.system_prompt, entry["system_prompt"])
                self.assertEqual(call.user_prompt, entry["user_prompt"])
                self.assertEqual(call.fingerprint(), entry["recorded_fingerprint"])

    def test_needs_info_stop_finds_the_driver_case_by_type_and_the_judge_was_not_called(self):
        run_dir = self.server.run_dir(self.runs["needs_info"])
        self.assertEqual("payloads/0008-advocate-case-submitted.json",
                         str(_payload_path(run_dir, "advocate.case_submitted", "driver_advocate")
                             .relative_to(run_dir)), "fixture: the driver case is payload 0008")
        entries = self.agents(self.runs["needs_info"])
        for name in ("rider_advocate", "driver_advocate"):
            with self.subTest(agent=name):
                self.assertEqual("match", entries[name]["status"])
                self.assertEqual(_stored_fingerprint(run_dir, name), entries[name]["recorded_fingerprint"])
        judge = entries["judge"]
        self.assertEqual("not_called", judge["status"])
        for key in ("recorded_fingerprint", "rebuilt_fingerprint", "system_prompt", "user_prompt"):
            self.assertIsNone(judge[key], key)

    def test_out_of_scope_routing_called_no_agent(self):
        for name, entry in self.agents(self.runs["oos"]).items():
            with self.subTest(agent=name):
                self.assertEqual("not_called", entry["status"])
                for key in ("recorded_fingerprint", "rebuilt_fingerprint", "system_prompt", "user_prompt"):
                    self.assertIsNone(entry[key], key)

    def test_a_judge_model_failure_still_answers_with_a_legal_status(self):
        entries = self.agents(self.runs["judge_failed"])
        self.assertEqual("match", entries["rider_advocate"]["status"])
        self.assertEqual("match", entries["driver_advocate"]["status"])
        self.assertIn(entries["judge"]["status"], {"not_called", "unavailable"})
        self.assertIsNone(entries["judge"]["system_prompt"])
        self.assertIsNone(entries["judge"]["user_prompt"])

    def test_changed_when_the_loaded_policy_is_not_the_one_the_run_used(self):
        state = self.server.httpd.ryde_state
        original = state.policy
        marker = "\nW24-TODAY-POLICY-MARKER\n"
        state.policy = PolicySet(source_path=original.source_path, text=original.text + marker,
                                 rules=original.rules)
        try:
            entries = self.agents(self.runs["ruled"])
        finally:
            state.policy = original
        run_dir = self.server.run_dir(self.runs["ruled"])
        for name, entry in entries.items():
            with self.subTest(agent=name):
                self.assertEqual("changed", entry["status"])
                self.assertEqual(_stored_fingerprint(run_dir, name), entry["recorded_fingerprint"])
                self.assertNotEqual(entry["recorded_fingerprint"], entry["rebuilt_fingerprint"])
                self.assertIn("W24-TODAY-POLICY-MARKER", entry["user_prompt"], "today's version is shown")
                self.assertEqual(entry["rebuilt_fingerprint"],
                                 LLMRequest(agent=name, system_prompt=entry["system_prompt"],
                                            user_prompt=entry["user_prompt"]).fingerprint())

    def test_changed_when_the_stored_fingerprint_differs_and_the_two_are_not_swapped(self):
        real = _stored_fingerprint(self.server.run_dir(self.runs["ruled"]), "judge")
        tampered = "0123456789abcdef"

        def edit(run_dir):
            # HAND-MADE SHAPE: a stored Judge fingerprint no rebuild can produce, in both places
            # it lives. The Judge is chosen because the advocates' fingerprints are part of the
            # case text the Judge's own prompt embeds, so tampering one would move the Judge too.
            path = _payload_path(run_dir, "judge.ruling_issued")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["ruling"]["llm"]["request_fingerprint"] = tampered
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            case = json.loads((run_dir / "case_file.json").read_text(encoding="utf-8"))
            case["resolution"]["ruling"]["llm"]["request_fingerprint"] = tampered
            (run_dir / "case_file.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")

        entries = self.agents(self.copy("ruled", "w24-tampered", edit))
        judge = entries["judge"]
        self.assertEqual("changed", judge["status"])
        self.assertEqual(tampered, judge["recorded_fingerprint"])
        self.assertEqual(real, judge["rebuilt_fingerprint"])
        self.assertIsInstance(judge["system_prompt"], str)
        self.assertIsInstance(judge["user_prompt"], str)
        self.assertEqual("match", entries["rider_advocate"]["status"])
        self.assertEqual("match", entries["driver_advocate"]["status"])

    def test_the_judge_prompt_embeds_the_stored_advocate_cases(self):
        real = _stored_fingerprint(self.server.run_dir(self.runs["ruled"]), "rider_advocate")

        def edit(run_dir):
            # HAND-MADE SHAPE: the rider's stored fingerprint altered in its payload only.
            path = _payload_path(run_dir, "advocate.case_submitted", "rider_advocate")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["llm"]["request_fingerprint"] = "fedcba9876543210"
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        entries = self.agents(self.copy("ruled", "w24-rider-tampered", edit))
        self.assertEqual("changed", entries["rider_advocate"]["status"])
        self.assertEqual("fedcba9876543210", entries["rider_advocate"]["recorded_fingerprint"])
        self.assertEqual(real, entries["rider_advocate"]["rebuilt_fingerprint"])
        self.assertEqual("match", entries["driver_advocate"]["status"])
        self.assertEqual("changed", entries["judge"]["status"])
        self.assertIn('"request_fingerprint": "fedcba9876543210"', entries["judge"]["user_prompt"])

    def test_unknown_and_traversal_run_ids_are_404(self):
        for raw in ("no-such-run", "%2E%2E", "..%2F..%2Fetc", "a%2Fb", "%2E"):
            with self.subTest(run_id=raw):
                status, body = self.server.json("GET", "/api/review/%s/prompts" % raw)
                self.assertEqual(404, status)
                self.assertIsInstance(body, dict)
                self.assertIn("error", body)


class PromptSummary(_ServerCase):
    def test_role_lines_are_exact(self):
        for name, entry in self.agents(self.runs["ruled"]).items():
            with self.subTest(agent=name):
                self.assertEqual(ROLES[name], entry["summary"]["role"])

    def test_hard_rules_are_the_four_numbered_rules_each_on_one_line(self):
        self.assertTrue(HARD_RULES.startswith("HARD RULES\n1. Never do arithmetic."), "fixture drifted")
        for key in ("ruled", "oos"):
            for name, entry in self.agents(self.runs[key]).items():
                with self.subTest(run=key, agent=name):
                    self.assertEqual(HARD_RULE_LINES, entry["summary"]["hard_rules"])

    def test_case_facts_follow_pack_order_and_skip_null_sections(self):
        for key, facts in (("ruled", NS0202_FACTS), ("withheld", RD0109_FACTS)):
            for name, entry in self.agents(self.runs[key]).items():
                with self.subTest(run=key, agent=name):
                    self.assertEqual(facts, entry["summary"]["case_facts"])

    def test_advocate_positions_only_on_the_judge_rider_first(self):
        entries = self.agents(self.runs["ruled"])
        self.assertIsNone(entries["rider_advocate"]["summary"]["advocate_positions"])
        self.assertIsNone(entries["driver_advocate"]["summary"]["advocate_positions"])
        self.assertEqual(NS0202_POSITIONS, entries["judge"]["summary"]["advocate_positions"])

    def test_policy_and_asked_to_return(self):
        rule_count = len(policy().rule_ids())
        self.assertEqual(33, rule_count, "fixture: docs/policy.md rule count at BASE")
        for key in ("ruled", "oos", "needs_info"):
            entries = self.agents(self.runs[key])
            for name, entry in entries.items():
                with self.subTest(run=key, agent=name):
                    self.assertEqual({"rule_count": rule_count, "source": "docs/policy.md"},
                                     entry["summary"]["policy"])
                    self.assertEqual(JUDGE_RETURNS if name == "judge" else ADVOCATE_RETURNS,
                                     entry["summary"]["asked_to_return"])
                    self.assertEqual(ROLES[name], entry["summary"]["role"])

    def test_rule_count_comes_from_the_policy_the_server_loaded(self):
        state = self.server.httpd.ryde_state
        original = state.policy
        state.policy = PolicySet(source_path=original.source_path, text=original.text,
                                 rules=original.rules[:5])
        try:
            entries = self.agents(self.runs["ruled"])
        finally:
            state.policy = original
        for name, entry in entries.items():
            with self.subTest(agent=name):
                self.assertEqual(5, entry["summary"]["policy"]["rule_count"])


class UnavailableNeverA500(_ServerCase):
    """A payload the rebuild needs is missing, corrupt or not an object: 'unavailable', 200."""

    def corrupt(self, name, mutate):
        return self.agents(self.copy("ruled", name, mutate))

    def assert_unavailable(self, entry):
        self.assertEqual("unavailable", entry["status"])
        for key in ("rebuilt_fingerprint", "system_prompt", "user_prompt"):
            self.assertIsNone(entry[key], key)

    def test_corrupt_evidence_pack_payload(self):
        def edit(run_dir):
            _payload_path(run_dir, "evidence.pack_built").write_text("{not json", encoding="utf-8")
        for name, entry in self.corrupt("w24-bad-pack", edit).items():
            with self.subTest(agent=name):
                self.assert_unavailable(entry)

    def test_evidence_pack_payload_that_is_not_an_object(self):
        for index, shape in enumerate(("[1, 2]", "null", "\"pack\"", "7")):
            def edit(run_dir, shape=shape):
                _payload_path(run_dir, "evidence.pack_built").write_text(shape, encoding="utf-8")
            entries = self.corrupt("w24-pack-shape-%d" % index, edit)
            for name, entry in entries.items():
                with self.subTest(shape=shape, agent=name):
                    self.assert_unavailable(entry)

    def test_missing_dispute_payload(self):
        def edit(run_dir):
            _payload_path(run_dir, "dispute.filed").unlink()
        for name, entry in self.corrupt("w24-no-dispute", edit).items():
            with self.subTest(agent=name):
                self.assert_unavailable(entry)

    def test_corrupt_rider_case_takes_the_rider_and_the_judge_only(self):
        def edit(run_dir):
            _payload_path(run_dir, "advocate.case_submitted", "rider_advocate").write_text("{", encoding="utf-8")
        entries = self.corrupt("w24-bad-rider", edit)
        self.assert_unavailable(entries["rider_advocate"])
        self.assertEqual("match", entries["driver_advocate"]["status"])
        self.assert_unavailable(entries["judge"])

    def test_driver_case_that_is_not_an_object_takes_the_driver_and_the_judge_only(self):
        def edit(run_dir):
            _payload_path(run_dir, "advocate.case_submitted", "driver_advocate").write_text("null", encoding="utf-8")
        entries = self.corrupt("w24-null-driver", edit)
        self.assertEqual("match", entries["rider_advocate"]["status"])
        self.assert_unavailable(entries["driver_advocate"])
        self.assert_unavailable(entries["judge"])

    def test_missing_ruling_payload_takes_the_judge_only(self):
        def edit(run_dir):
            _payload_path(run_dir, "judge.ruling_issued").unlink()
        entries = self.corrupt("w24-no-ruling", edit)
        self.assertEqual("match", entries["rider_advocate"]["status"])
        self.assertEqual("match", entries["driver_advocate"]["status"])
        self.assert_unavailable(entries["judge"])

    def test_corrupt_event_log_still_answers_200_with_legal_statuses(self):
        def edit(run_dir):
            (run_dir / "events.jsonl").write_text("{broken\n[]\n", encoding="utf-8")
        entries = self.corrupt("w24-bad-log", edit)
        for name, entry in entries.items():
            with self.subTest(agent=name):
                self.assertIn(entry["status"], STATUSES)
                if entry["status"] not in ("match", "changed"):
                    self.assertIsNone(entry["system_prompt"])

    def test_an_empty_run_directory_is_never_a_500(self):
        (self.server.out / "w24-empty").mkdir()
        status, _body = self.server.json("GET", "/api/review/w24-empty/prompts")
        self.assertIn(status, (200, 404))


class ReadOnlyAndNoModel(_ServerCase):
    def test_the_route_never_calls_a_model(self):
        seen = []

        def record(client, request):
            seen.append(request.agent)
            raise AssertionError("the prompts route called a model")

        with mock.patch.object(MockLLMClient, "complete", autospec=True, side_effect=record), \
                mock.patch.object(TencentLLMClient, "complete", autospec=True, side_effect=record):
            for key in ("ruled", "withheld", "needs_info", "oos", "filed"):
                with self.subTest(run=key):
                    self.prompts(self.runs[key])
        self.assertEqual([], seen)

    def test_the_route_writes_nothing(self):
        before = _tree_digest(self.server.out)
        for key in ("ruled", "withheld", "needs_info", "oos", "filed", "judge_failed"):
            self.prompts(self.runs[key])
        self.server.json("GET", "/api/review/no-such-run/prompts")
        self.assertEqual(before, _tree_digest(self.server.out))

    def test_the_module_is_the_route(self):
        try:
            from app.prompt_view import build_prompt_view
        except ImportError as exc:
            self.fail("app.prompt_view.build_prompt_view must exist: %s" % exc)
        run_id = self.runs["ruled"]
        direct = build_prompt_view(self.server.run_dir(run_id), self.server.httpd.ryde_state.policy)
        self.assertEqual(json.loads(json.dumps(direct)), self.prompts(run_id))


# ================================================================== party safety


class PartySafety(_ServerCase):
    def assert_clean(self, label, raw):
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        for token in PROMPT_LEAK_TOKENS:
            self.assertNotIn(token, text, "%s carries %r" % (label, token))

    def test_no_party_route_carries_a_prompt(self):
        # The routes must work, or a clean body proves nothing.
        status, view = self.server.json("GET", "/api/disputes/%s" % self._dispute_id())
        self.assertEqual(200, status)
        paths = ["/api/disputes/%s" % self._dispute_id(), "/api/demo/rider", "/api/demo/driver",
                 "/api/trips?category=route_deviation", "/api/trips?category=no_show_charge"]
        for path in paths:
            with self.subTest(path=path):
                status, _headers, raw = self.server.raw("GET", path)
                self.assertEqual(200, status)
                self.assert_clean(path, raw)

    def test_a_filing_response_carries_no_prompt(self):
        status, _headers, raw = self.server.raw("POST", "/api/disputes", {
            "category": "route_deviation", "filed_by": "rider", "trip_id": "T-RD0109",
            "description": "He went a very long way round.", "claim_amount_sgd": 12.5,
            "answers": {"expected_route": "Expressway.", "was_route_agreed": "No",
                        "asked_driver_to_stop": "No", "safety_concern": "No"}})
        self.assertEqual(200, status)
        self.assert_clean("POST /api/disputes", raw)

    def _dispute_id(self):
        case = self.server.case(self.runs["filed"])
        return case["dispute_id"]

    def test_party_pages_never_request_prompts(self):
        party = UI / "party"
        files = sorted(p for p in party.rglob("*") if p.suffix in (".js", ".html"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path=path.name):
                code = strip_js_comments(path.read_text(encoding="utf-8"))
                self.assertIsNone(re.search(r"prompts", code), "%s mentions prompts" % path.name)


# ======================================================================== freeze


class RuntimeFreeze(unittest.TestCase):
    def test_agent_model_pipeline_and_evidence_sources_are_byte_identical(self):
        actual = {}
        for folder in ("app/agents", "app/llm", "app/evidence"):
            for path in sorted((REPO / folder).rglob("*.py")):
                actual[str(path.relative_to(REPO))] = _sha(path)
        for rel in ("app/pipeline.py", "app/schemas.py", "app/dispute.py", "app/policy.py"):
            actual[rel] = _sha(REPO / rel)
        self.assertEqual(FROZEN_RUNTIME, actual)


# ================================================================== console page


SECTION_RE = re.compile(r"<section\b[^>]*\bid=\"([^\"]+)\"")


class ConsoleMarkup(unittest.TestCase):
    def setUp(self):
        self.html = (UI / "index.html").read_text(encoding="utf-8")

    def section(self, section_id):
        match = re.search(r"<section\b[^>]*\bid=\"%s\"[\s\S]*?</section>" % re.escape(section_id), self.html)
        self.assertIsNotNone(match, "no #%s" % section_id)
        return match.group(0)

    def test_section_sits_between_evidence_and_claims(self):
        workspace = self.html[self.html.index('id="case-workspace"'):]
        self.assertEqual(["case-summary", "grievance-section", "evidence-section", "prompts-section",
                          "claims-section", "resolution-section", "decision-section", "events-section"],
                         SECTION_RE.findall(workspace))

    def test_section_tag_heading_and_container_are_exact(self):
        self.assertEqual(1, self.html.count('id="prompts-section"'))
        block = self.section("prompts-section")
        self.assertTrue(block.startswith(
            '<section id="prompts-section" class="story-section" aria-labelledby="prompts-title">'), block[:120])
        self.assertIn('<h2 id="prompts-title">What each agent was asked</h2>', block)
        self.assertIn('<div id="prompts-content"></div>', block)

    def test_existing_section_numbers_are_kept(self):
        # Decision recorded in the brief: the new section carries no section-index, so the
        # numbering 01-06 that tests/test_w23_b2_console_queue.py pins stays as it is.
        self.assertEqual(["01", "02", "03", "04", "05", "06"],
                         re.findall(r'<p class="section-index">(\d+)</p>', self.html))

    def test_new_markup_reuses_existing_classes(self):
        css = (UI / "styles.css").read_text(encoding="utf-8")
        block = self.section("prompts-section")
        for attr in re.findall(r'class="([^"]+)"', block):
            for token in attr.split():
                with self.subTest(cls=token):
                    self.assertRegex(css, r"\.%s(?![\w-])" % re.escape(token))


# ----------------------------------------------------------- the fake-DOM driver

H = HARNESS
for old, new in (
    ('if(r.reject)return Promise.reject(new Error("offline"));return Promise.resolve({',
     'return new Promise((resolve,reject)=>setTimeout(()=>{if(r.reject){reject(new Error("offline"));return}resolve({'),
    ('json:()=>Promise.resolve(r.body)});};', 'json:()=>Promise.resolve(r.body)});},r.delay||0));};'),
    ('const scenario=JSON.parse(process.env.SCENARIO), requests=[], counters={};',
     'const scenario=JSON.parse(process.env.SCENARIO), requests=[], counters={}; const checkpoints=[];'
     ' const LOC={search:scenario.search||"",pathname:"/",hash:"",'
     'href:"http://127.0.0.1:18700/"+(scenario.search||"")};'),
    ('window:{},fetch,Promise,setTimeout,',
     'window:{matchMedia:()=>({matches:true}),location:LOC},location:LOC,URLSearchParams,URL,'
     'fetch,Promise,setTimeout,clearTimeout,'),
    ('for(const a of (scenario.actions||[])){let n;',
     'for(const a of (scenario.actions||[])){if(a.op==="wait"){await new Promise(r=>setTimeout(r,a.ms));continue}'
     'if(a.op==="snapshot"){checkpoints.push({prompts:snap(doc.getElementById("prompts-content")),'
     'status:ids["load-status"].textContent,requests:requests.map(r=>r.url)});continue}let n;'),
    ('JSON.stringify({ids:', 'JSON.stringify({checkpoints,ids:'),
):
    assert H.count(old) == 1, old
    H = H.replace(old, new)


def drive(routes, actions=(), search=""):
    env = dict(os.environ, APP_JS=str(UI / "app.js"),
               SCENARIO=json.dumps({"routes": routes, "actions": list(actions), "search": search}))
    result = subprocess.run([NODE, "-e", H], env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError("app.js prompt-panel driver failed: " + result.stderr)
    return json.loads(result.stdout)


def walk(node):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def by_tag(node, tag):
    """Descendants of `node` (never the node itself) with this tag, in document order."""
    return [n for n in list(walk(node))[1:] if n.get("tag") == tag.upper()]


def heading(node):
    for n in walk(node):
        if n.get("tag") in ("H1", "H2", "H3", "H4", "H5", "H6"):
            return n.get("text")
    return None


def panel(out):
    return out["ids"].get("prompts-content", {"children": [], "text": ""})


def articles(node):
    return by_tag(node, "article")


def entry(agent, status, fp="", system=None, user=None, rebuilt=None):
    label = LABELS[AGENTS.index(agent)]
    shown = status in ("match", "changed")
    return {
        "agent": agent, "label": label, "status": status,
        "recorded_fingerprint": fp or None,
        "rebuilt_fingerprint": (rebuilt or fp) if shown else None,
        "summary": {
            "role": ROLES[agent], "hard_rules": HARD_RULE_LINES,
            "case_facts": dict(NS0202_FACTS),
            "advocate_positions": copy.deepcopy(NS0202_POSITIONS) if agent == "judge" else None,
            "policy": {"rule_count": 33, "source": "docs/policy.md"},
            "asked_to_return": JUDGE_RETURNS if agent == "judge" else ADVOCATE_RETURNS,
        },
        "system_prompt": (system or "SYSTEM %s" % agent) if shown else None,
        "user_prompt": (user or "USER %s" % agent) if shown else None,
    }


def view(run_id, tag, statuses=("match", "match", "match")):
    out = []
    for i, (agent, status) in enumerate(zip(AGENTS, statuses)):
        fp = ("%s%d%s" % (tag, i, "0123456789abcdef"))[:16] if status != "not_called" else ""
        rebuilt = ("f" * 16) if status == "changed" else None
        out.append(entry(agent, status, fp, "SYS-%s-%s\nline two" % (tag, agent),
                         "USR-%s-%s\n{\"x\": 1}" % (tag, agent), rebuilt))
    return {"run_id": run_id, "agents": out}


def case_for(run_id, outcome="withheld"):
    return {"run_id": run_id, "dispute_id": "D-" + run_id, "category": "route_deviation",
            "generated_at": "2026-10-06T00:00:00Z", "intake": {}, "evidence_pack": {"fare": {"charged_sgd": 9.5}},
            "claims": {}, "policy": {}, "events": [],
            "resolution": {"outcome": outcome, "party_message": "waiting",
                           "withheld_candidate": {"action": "refund", "recommended_amount_sgd": 55.16,
                                                  "confidence": 0.9, "explanation": "x"}}}


def routes_for(*runs, prompts=None):
    rows = [queue_row(run_id=r, dispute_id="D-" + r) for r in runs]
    routes = base_routes(rows)
    for r in runs:
        routes["/api/review/%s/case" % r] = [ok({"case_file": case_for(r), "human_decision": None})]
        routes["/api/review/%s/prompts" % r] = [ok(view(r, r.lower()))]
    routes.update(prompts or {})
    return routes


OPEN = {"className": "queue-open", "op": "click"}
OPEN_B = {"className": "queue-open", "op": "click", "index": 1}
WAIT = {"op": "wait", "ms": 60}
SNAP = {"op": "snapshot"}


def badge(fp):
    return "Matches what was sent (fingerprint %s)" % fp[:8]


class PromptPanelDom(unittest.TestCase):
    def test_a_queue_open_requests_the_prompts_of_the_case_files_run_id(self):
        routes = routes_for("A")
        routes["/api/review/A/case"] = [ok({"case_file": case_for("CF-A"), "human_decision": None})]
        out = drive(routes, [OPEN, WAIT])
        urls = [r["url"] for r in out["requests"]]
        self.assertIn("/api/review/CF-A/prompts", urls)
        self.assertNotIn("/api/review/A/prompts", urls)

    def test_one_article_per_agent_in_order_headed_by_its_label(self):
        out = drive(routes_for("A"), [OPEN, WAIT])
        found = articles(panel(out))
        self.assertEqual(3, len(found))
        self.assertEqual(LABELS, [heading(a) for a in found])

    def test_badges_are_exact_for_every_status(self):
        body = view("A", "a", ("match", "changed", "not_called"))
        out = drive(routes_for("A", prompts={"/api/review/A/prompts": [ok(body)]}), [OPEN, WAIT])
        found = articles(panel(out))
        self.assertEqual(3, len(found))
        rider, driver, judge = (a["text"] for a in found)
        self.assertIn(badge(body["agents"][0]["recorded_fingerprint"]), rider)
        self.assertNotIn(body["agents"][0]["recorded_fingerprint"][:9] + ")", rider)
        self.assertIn(BADGE_CHANGED, driver)
        self.assertNotIn("Matches what was sent", driver)
        self.assertIn(BADGE_NOT_CALLED, judge)
        self.assertNotIn(BADGE_CHANGED, judge)
        body = view("A", "a", ("unavailable", "unavailable", "unavailable"))
        out = drive(routes_for("A", prompts={"/api/review/A/prompts": [ok(body)]}), [OPEN, WAIT])
        found = articles(panel(out))
        self.assertEqual(3, len(found))
        for a in found:
            self.assertIn(BADGE_UNAVAILABLE, a["text"])
            self.assertNotIn(BADGE_NOT_CALLED, a["text"])

    def test_summary_is_a_definition_list(self):
        out = drive(routes_for("A"), [OPEN, WAIT])
        found = articles(panel(out))
        self.assertEqual(3, len(found))
        for agent, a in zip(AGENTS, found):
            with self.subTest(agent=agent):
                lists = by_tag(a, "dl")
                self.assertTrue(lists, "the summary is rendered as a <dl>")
                text = " ".join(dl["text"] for dl in lists)
                self.assertIn(ROLES[agent], text)
                for rule in HARD_RULE_LINES:
                    self.assertIn(rule, text)
                for key in (JUDGE_RETURNS if agent == "judge" else ADVOCATE_RETURNS):
                    self.assertIn(key, text)
                if agent == "judge":
                    self.assertIn("refund", text)
                    self.assertIn("no action", text)

    def test_full_text_sits_in_details_with_the_exact_summary(self):
        body = view("A", "a", ("match", "changed", "not_called"))
        out = drive(routes_for("A", prompts={"/api/review/A/prompts": [ok(body)]}), [OPEN, WAIT])
        found = articles(panel(out))
        self.assertEqual(3, len(found))
        for item, a in zip(body["agents"][:2], found[:2]):
            with self.subTest(agent=item["agent"]):
                details = by_tag(a, "details")
                self.assertEqual(1, len(details))
                summaries = by_tag(details[0], "summary")
                self.assertEqual(1, len(summaries))
                self.assertEqual(SHOW_FULL_TEXT, summaries[0]["text"])
                pres = by_tag(details[0], "pre")
                self.assertEqual(1, len(pres))
                self.assertEqual(item["system_prompt"] + "\n\n" + item["user_prompt"], pres[0]["text"])
        self.assertEqual([], by_tag(found[2], "pre"), "no full text for an agent that was not called")

    def test_fetch_failure_or_a_malformed_answer_shows_the_one_sentence(self):
        for name, response in (("offline", {"reject": True}), ("404", {"status": 404, "body": {"error": "x"}}),
                               ("500", {"status": 500, "body": {}}), ("null", ok(None)), ("empty", ok({})),
                               ("array", ok([])), ("agents-string", ok({"run_id": "A", "agents": "x"}))):
            with self.subTest(response=name):
                out = drive(routes_for("A", prompts={"/api/review/A/prompts": [response]}), [OPEN, WAIT])
                self.assertIn("/api/review/A/prompts", [r["url"] for r in out["requests"]])
                self.assertEqual(FAILURE, panel(out)["text"])

    def test_a_local_file_without_the_server_shows_the_one_sentence(self):
        out = drive(base_routes([]), [{"id": "run-folder-picker", "op": "pick", "path": "local/case_file.json",
                                       "body": case_for("LOCAL-1")}, WAIT])
        self.assertIn("/api/review/LOCAL-1/prompts", [r["url"] for r in out["requests"]])
        self.assertFalse(out["ids"]["case-workspace"]["hidden"])
        self.assertEqual(FAILURE, panel(out)["text"])

    def test_a_slow_success_for_the_previous_case_never_renders(self):
        routes = routes_for("A", "B")
        routes["/api/review/A/prompts"] = [dict(ok(view("A", "a")), delay=250)]
        routes["/api/review/B/prompts"] = [ok(view("B", "b"))]
        out = drive(routes, [OPEN, WAIT, OPEN_B, {"op": "wait", "ms": 400}])
        text = panel(out)["text"]
        self.assertIn(badge(view("B", "b")["agents"][0]["recorded_fingerprint"]), text)
        self.assertNotIn("SYS-a-", text)
        self.assertEqual(3, len(articles(panel(out))))

    def test_a_slow_failure_for_the_previous_case_never_renders(self):
        routes = routes_for("A", "B")
        routes["/api/review/A/prompts"] = [{"reject": True, "delay": 250}]
        out = drive(routes, [OPEN, WAIT, OPEN_B, {"op": "wait", "ms": 400}])
        text = panel(out)["text"]
        self.assertNotIn(FAILURE, text)
        self.assertIn(badge(view("B", "b")["agents"][0]["recorded_fingerprint"]), text)

    def test_a_slow_success_cannot_replace_the_current_failure(self):
        routes = routes_for("A", "B")
        routes["/api/review/A/prompts"] = [dict(ok(view("A", "a")), delay=250)]
        routes["/api/review/B/prompts"] = [{"reject": True}]
        out = drive(routes, [OPEN, WAIT, OPEN_B, {"op": "wait", "ms": 400}])
        self.assertEqual(FAILURE, panel(out)["text"])

    def test_opening_a_case_clears_the_previous_panel_while_its_own_is_pending(self):
        routes = routes_for("A", "B")
        routes["/api/review/B/prompts"] = [dict(ok(view("B", "b")), delay=300)]
        out = drive(routes, [OPEN, WAIT, OPEN_B, {"op": "wait", "ms": 100}, SNAP, {"op": "wait", "ms": 400}])
        self.assertEqual(1, len(out["checkpoints"]))
        pending = out["checkpoints"][0]["prompts"]["text"]
        self.assertNotIn("SYS-a-", pending)
        self.assertNotIn(badge(view("A", "a")["agents"][0]["recorded_fingerprint"]), pending)
        self.assertIn("SYS-b-", panel(out)["text"])

    def test_deep_link_opens_the_run_through_the_queue_open_path(self):
        out = drive(routes_for("A"), [WAIT], search="?run=A")
        urls = [r["url"] for r in out["requests"]]
        self.assertIn("/api/review/A/case", urls)
        self.assertIn("/api/review/A/prompts", urls)
        self.assertEqual("A", out["ids"]["loaded-file"]["text"])
        self.assertFalse(out["ids"]["case-workspace"]["hidden"])
        self.assertFalse(out["ids"]["decision-section"]["hidden"], "a withheld deep link gets the decision form")
        self.assertEqual(3, len(articles(panel(out))))

    def test_deep_link_accepts_128_characters(self):
        run = "r" * 128
        out = drive(routes_for(run), [WAIT], search="?run=" + run)
        self.assertIn("/api/review/%s/case" % run, [r["url"] for r in out["requests"]])

    def test_an_invalid_deep_link_says_unknown_run_and_renders_nothing(self):
        for search in ("?run=..%2Fx", "?run=a%20b", "?run=a%2Fb", "?run=" + "r" * 129, "?run=%3Cb%3E", "?run=a.b%0A"):
            with self.subTest(search=search):
                out = drive(routes_for("A"), [WAIT], search=search)
                urls = [r["url"] for r in out["requests"]]
                self.assertEqual([], [u for u in urls if u.endswith("/case") or u.endswith("/prompts")])
                self.assertEqual(UNKNOWN_RUN, out["ids"]["load-status"]["text"])
                self.assertTrue(out["ids"]["case-workspace"]["hidden"])

    def test_no_deep_link_opens_nothing(self):
        out = drive(routes_for("A"), [WAIT], search="")
        urls = [r["url"] for r in out["requests"]]
        self.assertEqual([], [u for u in urls if u.endswith("/case") or u.endswith("/prompts")])
        self.assertNotEqual(UNKNOWN_RUN, out["ids"]["load-status"]["text"])

    def test_rendered_panel_uses_only_existing_classes(self):
        css = (UI / "styles.css").read_text(encoding="utf-8")
        body = view("A", "a", ("match", "changed", "unavailable"))
        out = drive(routes_for("A", prompts={"/api/review/A/prompts": [ok(body)]}), [OPEN, WAIT])
        self.assertEqual(3, len(articles(panel(out))))
        tokens = sorted({t for n in walk(panel(out)) for t in n.get("className", "").split()})
        self.assertTrue(tokens, "the panel reuses existing classes")
        for token in tokens:
            with self.subTest(cls=token):
                self.assertRegex(css, r"\.%s(?![\w-])" % re.escape(token))


# ------------------------------------------------------------- the real browser

BROWSER_SCRIPT = REPO / "tests" / "browser" / "w24_prompt_panel.cjs"


@unittest.skipUnless(os.environ.get("PUPPETEER_MODULE") and os.environ.get("BROWSER_EXECUTABLE"),
                     "real-browser pass: set PUPPETEER_MODULE and BROWSER_EXECUTABLE (run by the planner)")
class RealBrowserPromptPanel(_ServerCase):
    def test_real_browser_contract(self):
        import tempfile

        runs = self.runs
        expect = {
            "ruled": runs["ruled"], "a": runs["filed"], "b": runs["withheld"],
            "fingerprints": {key: [_stored_fingerprint(self.server.run_dir(runs[key]), a) for a in AGENTS]
                             for key in ("ruled", "filed", "withheld")},
            "labels": LABELS, "badgeFailure": FAILURE, "unknown": UNKNOWN_RUN, "summary": SHOW_FULL_TEXT,
        }
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            env = dict(os.environ, W24_EXPECT=json.dumps(expect))
            result = subprocess.run([NODE, str(BROWSER_SCRIPT), self.server.base, str(report_path)],
                                    env=env, capture_output=True, text=True, timeout=240)
            self.assertTrue(report_path.exists(), "browser driver wrote no report: " + result.stderr[-2000:])
            report = json.loads(report_path.read_text(encoding="utf-8"))
        keep = os.environ.get("W24_BROWSER_REPORT")
        if keep:
            Path(keep).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.assertTrue(report.get("passed"), json.dumps(report, indent=1)[:4000])
        self.assertEqual(6, len(report.get("cases", [])), "every browser case ran")


if __name__ == "__main__":
    unittest.main()
