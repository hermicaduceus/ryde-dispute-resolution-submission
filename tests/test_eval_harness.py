"""Session seventeen acceptance target: W4, the evaluation harness (app/eval.py).

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/session-seventeen-brief.md. The harness runs every labelled case in a pack through the
real pipeline and scores the result against ground-truth.json, case by case, with a named
reason. It is the ONLY reader of ground-truth.json under app/.

the operator rulings 2026-09-29: a needs_info stop is a miss ("asked the party") and stays in the
denominator; citing every decisive rule is a separate line, never part of "match".
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import tokenize
import unittest
from pathlib import Path

from app.llm import LLMError, MockLLMClient
from app.policy import load_policy

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "data" / "packs"
POLICY = REPO / "docs" / "policy.md"
REASONS = ["match", "wrong outcome", "wrong action", "wrong amount", "asked the party", "run failed"]


def _ev():
    import app.eval as ev  # lazy, so each test is RED on its own rather than one import error

    return ev


def _tmp(test: unittest.TestCase) -> Path:
    path = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, path, True)
    return path


def _res(outcome, action=None, amount=None, rules=(), withheld=False):
    ruling = None
    if action is not None:
        ruling = {"action": action, "recommended_amount_sgd": amount, "confidence": 0.9,
                  "cited_rule_ids": list(rules)}
    return {"outcome": outcome,
            "ruling": None if withheld else ruling,
            "withheld_candidate": ruling if withheld else None}


REFUND = {"dispute_id": "RD-0101", "expected_outcome": "ruled", "expected_action": "refund",
          "expected_amount_sgd": 5.81, "decisive_rule_ids": ["RD-1", "RD-2", "RD-3"]}
ESCALATED = {"dispute_id": "RD-0109", "expected_outcome": "escalated", "expected_action": None,
             "expected_amount_sgd": None, "decisive_rule_ids": ["RD-1", "RD-3", "ESC-4"]}
HUMAN = {"dispute_id": "OS-0301", "expected_outcome": "human_review", "expected_action": None,
         "expected_amount_sgd": None, "decisive_rule_ids": ["GEN-1", "ESC-1"]}


class FailsOnNS0202(MockLLMClient):
    """The mock, except every call about NS-0202 raises as a live outage would."""

    def complete(self, request):
        if "NS-0202" in request.user_prompt:
            raise LLMError("simulated outage")
        return super().complete(request)


class UnexpectedFailureOnNS0202(MockLLMClient):
    """A provider bug outside the five exception types the first harness listed."""

    def __init__(self, exception):
        super().__init__()
        self.exception = exception

    def complete(self, request):
        if "NS-0202" in request.user_prompt:
            raise self.exception
        return super().complete(request)


# ------------------------------------------------------------------ scoring


class ScoreCase(unittest.TestCase):
    def s(self, label, res):
        return _ev().score_case(label, res)

    def test_exact_ruling_matches_and_is_grounded(self):
        got = self.s(REFUND, _res("ruled", "refund", 5.81, ["RD-1", "RD-2", "RD-3"]))
        self.assertEqual(("match", True, True, []),
                         (got.reason, got.decision_match, got.grounded, got.rules_missing))

    def test_amount_compared_to_the_cent(self):
        self.assertEqual("match", self.s(REFUND, _res("ruled", "refund", 5.814)).reason)
        self.assertEqual("wrong amount", self.s(REFUND, _res("ruled", "refund", 5.82)).reason)
        self.assertEqual("wrong amount", self.s(REFUND, _res("ruled", "refund", 5.8)).reason)

    def test_string_amount_never_matches_numeric_label(self):
        for amount, expected in (("5.81", 5.81), (None, 5.81), ([], 5.81), ({}, 5.81),
                                 (True, 1.0), (False, 0.0)):
            with self.subTest(amount=amount):
                label = dict(REFUND, expected_amount_sgd=expected)
                got = self.s(label, _res("ruled", "refund", amount))
                self.assertEqual(("wrong amount", False), (got.reason, got.decision_match))

    def test_action_comparison_is_exact_not_case_or_separator_normalised(self):
        for action in ("Refund", "REFUND", "re fund", "re_fund"):
            with self.subTest(action=action):
                got = self.s(REFUND, _res("ruled", action, 5.81))
                self.assertEqual(("wrong action", False), (got.reason, got.decision_match))

    def test_wrong_action(self):
        got = self.s(REFUND, _res("ruled", "no action", 0.0))
        self.assertEqual(("wrong action", False), (got.reason, got.decision_match))

    def test_withheld_is_the_labels_escalated(self):
        got = self.s(ESCALATED, _res("withheld", "refund", 55.16, ["RD-1", "RD-3"], withheld=True))
        self.assertEqual(("match", True, True, []),
                         (got.reason, got.decision_match, got.grounded, got.rules_missing))

    def test_ruling_where_label_says_escalated(self):
        got = self.s(ESCALATED, _res("ruled", "refund", 55.16))
        self.assertEqual(("wrong outcome", False), (got.reason, got.decision_match))

    def test_withheld_where_label_says_ruled(self):
        got = self.s(REFUND, _res("withheld", "refund", 5.81, withheld=True))
        self.assertEqual(("wrong outcome", False), (got.reason, got.decision_match))

    def test_needs_info_is_a_named_miss_with_no_grounding(self):
        for label in (REFUND, ESCALATED, HUMAN):
            with self.subTest(label=label["dispute_id"]):
                got = self.s(label, _res("needs_info"))
                self.assertEqual(("asked the party", False, None, []),
                                 (got.reason, got.decision_match, got.grounded, got.rules_missing))

    def test_human_review_matches_without_grounding(self):
        got = self.s(HUMAN, _res("human_review"))
        self.assertEqual(("match", True, None, []),
                         (got.reason, got.decision_match, got.grounded, got.rules_missing))

    def test_human_review_where_label_says_ruled(self):
        self.assertEqual("wrong outcome", self.s(REFUND, _res("human_review")).reason)

    def test_missing_rules_named_in_label_order_and_decision_still_matches(self):
        got = self.s(REFUND, _res("ruled", "refund", 5.81, ["RD-3", "RD-1"]))
        self.assertEqual(("match", True, False, ["RD-2"]),
                         (got.reason, got.decision_match, got.grounded, got.rules_missing))
        got = self.s(REFUND, _res("ruled", "refund", 5.81, []))
        self.assertEqual(["RD-1", "RD-2", "RD-3"], got.rules_missing)

    def test_missing_rules_keep_label_order_not_sorted_order(self):
        label = dict(REFUND, decisive_rule_ids=["NS-3", "GEN-7"])  # sorted would be GEN-7, NS-3
        self.assertEqual(["NS-3", "GEN-7"], self.s(label, _res("ruled", "refund", 5.81)).rules_missing)

    def test_escalation_rules_never_count_against_grounding(self):
        got = self.s(ESCALATED, _res("withheld", "refund", 55.16, ["RD-1"], withheld=True))
        self.assertEqual((False, ["RD-3"]), (got.grounded, got.rules_missing))

    def test_run_failure_is_recorded_not_raised(self):
        got = _ev().score_error(REFUND, "simulated outage")
        self.assertEqual(("RD-0101", "run failed", False, None, [], "simulated outage"),
                         (got.dispute_id, got.reason, got.decision_match, got.grounded,
                          got.rules_missing, got.error))


# ------------------------------------------------------------------ labels


class LoadLabels(unittest.TestCase):
    def _pack(self, disputes, labels):
        tmp = _tmp(self)
        (tmp / "disputes").mkdir()
        for dispute_id in disputes:
            (tmp / "disputes" / (dispute_id + ".json")).write_text("{}", encoding="utf-8")
        cases = [dict(REFUND, dispute_id=i) for i in labels]
        (tmp / "ground-truth.json").write_text(json.dumps({"cases": cases}), encoding="utf-8")
        return tmp

    def test_real_packs_load_every_label(self):
        self.assertEqual(18, len(_ev().load_labels(PACKS / "organiser-style-v1")))
        self.assertEqual(17, len(_ev().load_labels(PACKS / "ryde-synth-v1")))

    def test_dispute_without_a_label_fails_by_name(self):
        with self.assertRaises(_ev().EvalError) as ctx:
            _ev().load_labels(self._pack(["A-1", "B-2"], ["A-1"]))
        self.assertIn("B-2", str(ctx.exception))

    def test_label_without_a_dispute_fails_by_name(self):
        with self.assertRaises(_ev().EvalError) as ctx:
            _ev().load_labels(self._pack(["A-1"], ["A-1", "C-3"]))
        self.assertIn("C-3", str(ctx.exception))

    def test_duplicate_label_fails_by_name(self):
        with self.assertRaises(_ev().EvalError) as ctx:
            _ev().load_labels(self._pack(["A-1"], ["A-1", "A-1"]))
        self.assertIn("A-1", str(ctx.exception))

    def test_missing_labels_file_fails(self):
        tmp = _tmp(self)
        (tmp / "disputes").mkdir()
        with self.assertRaises(_ev().EvalError):
            _ev().load_labels(tmp)

    def test_ruled_label_requires_a_numeric_amount(self):
        tmp = self._pack(["A-1"], ["A-1"])
        path = tmp / "ground-truth.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["cases"][0]["expected_amount_sgd"] = None
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(_ev().EvalError) as ctx:
            _ev().load_labels(tmp)
        self.assertIn("A-1", str(ctx.exception))
        self.assertIn("amount", str(ctx.exception).lower())


# ------------------------------------------------------------ the real corpus

#: (dispute_id, reason) in file order, measured on the mock at build 370cbef. A list, not
#: a dict: a duplicated or reordered case must show up.
MOCK_ORGANISER = [
    ("DISP-002", "match"), ("NS-0201", "wrong action"), ("NS-0202", "match"),
    ("NS-0203", "match"), ("NS-0204", "match"), ("NS-0205", "wrong outcome"),
    ("NS-0206", "match"), ("NS-0207", "wrong action"), ("OS-0301", "match"),
    ("RD-0101", "match"), ("RD-0102", "wrong action"), ("RD-0103", "wrong action"),
    ("RD-0104", "match"), ("RD-0105", "wrong action"), ("RD-0106", "wrong amount"),
    ("RD-0107", "wrong action"), ("RD-0108", "match"), ("RD-0109", "match"),
]
MOCK_RYDE = [pair for pair in MOCK_ORGANISER if pair[0] != "DISP-002"]


def _run(test, pack, llm=None):
    out = _tmp(test)
    report = _ev().run_eval(pack_dir=PACKS / pack, llm=llm or MockLLMClient(),
                            policy=load_policy(POLICY), out_dir=out,
                            confidence_threshold=0.65, autonomous_cap_sgd=50.0)
    return report, out


class MockCorpusRun(unittest.TestCase):
    def test_organiser_pack_per_case_reasons(self):
        report, _ = _run(self, "organiser-style-v1")
        self.assertEqual(MOCK_ORGANISER, [(c.dispute_id, c.reason) for c in report.cases])

    def test_organiser_pack_totals(self):
        report, _ = _run(self, "organiser-style-v1")
        self.assertEqual({"cases": 18, "decisions_matching": 10, "grounding_applicable": 17,
                          "grounded": 0,
                          "by_reason": {"match": 10, "wrong outcome": 1, "wrong action": 6,
                                        "wrong amount": 1, "asked the party": 0, "run failed": 0}},
                         report.totals)
        self.assertEqual(REASONS, list(report.totals["by_reason"]))

    def test_ryde_pack_per_case_and_totals(self):
        report, _ = _run(self, "ryde-synth-v1")
        self.assertEqual(MOCK_RYDE, [(c.dispute_id, c.reason) for c in report.cases])
        self.assertEqual((17, 9, 16, 0), tuple(report.totals[k] for k in
                         ("cases", "decisions_matching", "grounding_applicable", "grounded")))

    def test_report_names_the_pack_and_provider(self):
        report, _ = _run(self, "organiser-style-v1")
        self.assertEqual(("organiser-style-v1", "mock"), (report.pack, report.provider))

    def test_every_case_leaves_its_case_file(self):
        _, out = _run(self, "organiser-style-v1")
        for dispute_id, _ in MOCK_ORGANISER:
            path = out / "organiser-style-v1" / dispute_id / "case_file.json"
            self.assertTrue(path.exists(), dispute_id)
            self.assertEqual(dispute_id, json.loads(path.read_text())["dispute_id"])

    def test_one_failed_case_does_not_stop_the_run(self):
        report, _ = _run(self, "organiser-style-v1", FailsOnNS0202())
        by_id = {c.dispute_id: c for c in report.cases}
        self.assertEqual(18, len(report.cases))
        self.assertEqual("run failed", by_id["NS-0202"].reason)
        self.assertIn("simulated outage", by_id["NS-0202"].error)
        self.assertEqual("match", by_id["NS-0203"].reason, "the case after the failure still ran")
        self.assertEqual((9, 1), (report.totals["by_reason"]["match"],
                                  report.totals["by_reason"]["run failed"]))
        self.assertEqual(9, report.totals["decisions_matching"])

    def test_unexpected_exception_is_also_contained_per_case(self):
        for exception in (TypeError("malformed reply"), KeyError("missing key"), OSError("I/O bug")):
            with self.subTest(kind=type(exception).__name__):
                report, _ = _run(self, "organiser-style-v1", UnexpectedFailureOnNS0202(exception))
                by_id = {c.dispute_id: c for c in report.cases}
                self.assertEqual(18, len(report.cases))
                self.assertEqual("run failed", by_id["NS-0202"].reason)
                self.assertIn(str(exception), by_id["NS-0202"].error or "")
                self.assertEqual("match", by_id["NS-0203"].reason)

    def test_run_failed_case_file_is_null_and_partial_events_remain(self):
        report, out = _run(self, "organiser-style-v1", FailsOnNS0202())
        failed = next(c for c in report.cases if c.dispute_id == "NS-0202")
        self.assertIsNone(failed.case_file)
        partial = out / "organiser-style-v1" / "NS-0202"
        self.assertFalse((partial / "case_file.json").exists())
        self.assertTrue((partial / "events.jsonl").exists())


# ------------------------------------------------------------------- leaks


class NoLabelLeak(unittest.TestCase):
    """The labels must never reach a prompt, and only app/eval.py may read them."""

    def test_no_prompt_carries_a_label(self):
        prompts = []

        class Recording(MockLLMClient):
            def complete(self, request):
                prompts.append(request.system_prompt + "\n" + request.user_prompt)
                return super().complete(request)

        _run(self, "organiser-style-v1", Recording())
        labels = json.loads((PACKS / "organiser-style-v1" / "ground-truth.json")
                            .read_text(encoding="utf-8"))["cases"]
        blob = "\n".join(prompts)
        self.assertGreater(len(prompts), 30)
        for token in ("expected_outcome", "expected_action", "decisive_rule_ids",
                      "ground-truth", "ground_truth"):
            self.assertNotIn(token, blob)
        for label in labels:
            self.assertNotIn(label["rationale"], blob, label["dispute_id"])

    def test_only_the_harness_reads_ground_truth(self):
        offenders = []
        for path in sorted((REPO / "app").rglob("*.py")):
            if path.name == "eval.py":
                continue
            source = path.read_text(encoding="utf-8")
            code = [t.string for t in tokenize.generate_tokens(io.StringIO(source).readline)
                    if t.type != tokenize.COMMENT]
            if any("ground-truth" in s or "ground_truth" in s for s in code):
                offenders.append(str(path.relative_to(REPO)))
        self.assertEqual([], offenders)


# ----------------------------------------------------------------- reports


class Reports(unittest.TestCase):
    def test_json_report_shape(self):
        out = _tmp(self)
        with contextlib.redirect_stdout(io.StringIO()):
            _ev().main(["--llm", "mock", "--pack", "organiser-style-v1", "--out", str(out)])
        data = json.loads((out / "organiser-style-v1" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual({"pack", "provider", "threshold", "autonomous_cap_sgd", "generated_at",
                          "totals", "cases"}, set(data))
        self.assertEqual(("organiser-style-v1", "mock", 0.65, 50.0),
                         (data["pack"], data["provider"], data["threshold"],
                          data["autonomous_cap_sgd"]))
        self.assertEqual({"dispute_id", "expected", "got", "reason", "decision_match", "grounded",
                          "rules_missing", "error", "case_file"}, set(data["cases"][0]))
        self.assertEqual(MOCK_ORGANISER, [(c["dispute_id"], c["reason"]) for c in data["cases"]])
        self.assertEqual(10, data["totals"]["decisions_matching"])
        for case in data["cases"]:
            # Relative to --out, so the report stays valid when the folder is moved.
            self.assertEqual("organiser-style-v1/%s/case_file.json" % case["dispute_id"],
                             case["case_file"])
            self.assertTrue((out / case["case_file"]).exists(), case["dispute_id"])

    def test_markdown_headline_caveat_and_no_percentages(self):
        report, _ = _run(self, "organiser-style-v1")
        md = _ev().render_markdown(report)
        lines = md.splitlines()
        self.assertEqual("# Evaluation: organiser-style-v1, provider mock", lines[0])
        self.assertIn("Decisions matching the label: 10 of 18", lines)
        self.assertIn("Rulings citing every decisive rule: 0 of 17", lines)
        self.assertIn(_ev().CAVEAT, lines)
        self.assertIn(_ev().MOCK_WARNING, lines)
        self.assertNotIn("%", md)
        for dispute_id, reason in MOCK_ORGANISER:
            rows = [line for line in lines if line.startswith("| %s |" % dispute_id)]
            self.assertEqual(1, len(rows), dispute_id)
            self.assertIn("| %s |" % reason, rows[0], dispute_id)

    def test_markdown_expected_and_got_cells(self):
        report, _ = _run(self, "organiser-style-v1")
        lines = _ev().render_markdown(report).splitlines()

        def row(dispute_id):
            return [c.strip() for c in next(l for l in lines
                                             if l.startswith("| %s |" % dispute_id)).split("|")[1:-1]]

        self.assertEqual(["RD-0101", "ruled: refund 5.81", "ruled: refund 5.81", "match"],
                         row("RD-0101")[:4])
        self.assertEqual(["RD-0109", "escalated", "withheld: refund 55.16", "match"],
                         row("RD-0109")[:4])
        self.assertEqual(["OS-0301", "human_review", "human_review", "match"], row("OS-0301")[:4])

    def test_mock_warning_only_for_the_mock(self):
        class LooksReal(MockLLMClient):
            provider_name = "tencent"

        report, _ = _run(self, "organiser-style-v1", LooksReal())
        md = _ev().render_markdown(report)
        self.assertNotIn(_ev().MOCK_WARNING, md)
        self.assertIn(_ev().CAVEAT, md)
        self.assertEqual("# Evaluation: organiser-style-v1, provider tencent", md.splitlines()[0])

    def test_stdout_mock_warning_only_for_the_mock(self):
        class LooksReal(MockLLMClient):
            provider_name = "tencent"

        import app.eval as ev

        out = _tmp(self)
        original = ev.build_llm_client
        ev.build_llm_client = lambda *a, **k: LooksReal()
        self.addCleanup(setattr, ev, "build_llm_client", original)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = ev.main(["--llm", "mock", "--pack", "organiser-style-v1", "--out", str(out)])
        self.assertEqual(0, code)
        self.assertNotIn(ev.MOCK_WARNING, stdout.getvalue())
        self.assertIn(ev.CAVEAT, stdout.getvalue())

    def test_fixed_strings(self):
        self.assertEqual("MOCK RUN: the mock is a deterministic stand-in, not a solver. "
                         "This score checks the wiring, not the system.", _ev().MOCK_WARNING)
        self.assertEqual("Measured on a synthesised demonstration corpus against the team's own "
                         "labels: a check of internal consistency, not real-world accuracy.",
                         _ev().CAVEAT)


# --------------------------------------------------------------------- CLI


class Main(unittest.TestCase):
    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _ev().main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_both_packs_by_default_exit_0(self):
        tmp = _tmp(self)
        code, out, _ = self._main(["--llm", "mock", "--out", str(tmp)])
        self.assertEqual(0, code)
        for pack in ("organiser-style-v1", "ryde-synth-v1"):
            self.assertTrue((tmp / pack / "report.md").exists(), pack)
            self.assertTrue((tmp / pack / "report.json").exists(), pack)
        self.assertIn("Decisions matching the label: 10 of 18", out)
        self.assertIn("Decisions matching the label: 9 of 17", out)
        self.assertLess(out.index("10 of 18"), out.index("9 of 17"), "organiser pack runs first")
        self.assertIn(_ev().MOCK_WARNING, out)
        self.assertIn(_ev().CAVEAT, out)
        self.assertNotIn("%", out)

    def test_one_pack_only(self):
        tmp = _tmp(self)
        code, out, _ = self._main(["--llm", "mock", "--pack", "ryde-synth-v1", "--out", str(tmp)])
        self.assertEqual(0, code)
        self.assertFalse((tmp / "organiser-style-v1").exists())
        self.assertIn("Decisions matching the label: 9 of 17", out)

    def test_unknown_pack_exit_1(self):
        code, _, err = self._main(["--llm", "mock", "--pack", "no-such-pack",
                                   "--out", str(_tmp(self))])
        self.assertEqual(1, code)
        self.assertTrue(err.startswith("error:"), err)

    def test_unknown_llm_exit_1_not_the_run_failed_code(self):
        code, _, err = self._main(["--llm", "openai", "--pack", "organiser-style-v1",
                                   "--out", str(_tmp(self))])
        self.assertEqual(1, code)
        self.assertTrue(err.startswith("error:"), err)
        self.assertNotIn("usage:", err)

    def test_existing_pack_output_is_refused_before_a_case_runs(self):
        out = _tmp(self)
        existing = out / "organiser-style-v1"
        existing.mkdir()
        sentinel = existing / "keep-me.txt"
        sentinel.write_text("old run", encoding="utf-8")
        code, _, err = self._main(["--llm", "mock", "--pack", "organiser-style-v1",
                                   "--out", str(out)])
        self.assertEqual(1, code)
        self.assertIn("already exists", err)
        self.assertEqual("old run", sentinel.read_text(encoding="utf-8"))
        self.assertEqual([sentinel], list(existing.iterdir()))

    def test_run_eval_itself_refuses_an_existing_pack_output(self):
        out = _tmp(self)
        existing = out / "organiser-style-v1"
        existing.mkdir()
        sentinel = existing / "keep-me.txt"
        sentinel.write_text("old run", encoding="utf-8")
        with self.assertRaises(_ev().EvalError) as ctx:
            _ev().run_eval(pack_dir=PACKS / "organiser-style-v1", llm=MockLLMClient(),
                           policy=load_policy(POLICY), out_dir=out,
                           confidence_threshold=0.65, autonomous_cap_sgd=50.0)
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual([sentinel], list(existing.iterdir()))

    def test_second_requested_pack_existing_prevents_first_pack_run(self):
        out = _tmp(self)
        existing = out / "ryde-synth-v1"
        existing.mkdir()
        sentinel = existing / "keep-me.txt"
        sentinel.write_text("old run", encoding="utf-8")
        code, _, err = self._main(["--llm", "mock", "--pack", "organiser-style-v1",
                                   "--pack", "ryde-synth-v1", "--out", str(out)])
        self.assertEqual(1, code)
        self.assertIn("already exists", err)
        self.assertFalse((out / "organiser-style-v1").exists(), "all outputs preflight before case one")
        self.assertEqual("old run", sentinel.read_text(encoding="utf-8"))

    def test_broken_labels_exit_1_before_any_case_runs(self):
        import app.eval as ev

        broken = _tmp(self)
        shutil.copytree(PACKS / "ryde-synth-v1" / "disputes", broken / "disputes")
        (broken / "ground-truth.json").write_text(json.dumps({"cases": []}), encoding="utf-8")
        original = ev.resolve_pack_dir
        # A GOOD pack first, the broken one second: without a preflight over every pack,
        # the good pack's cases would run (and burn live calls) before the error surfaced.
        ev.resolve_pack_dir = lambda name: broken if name == "broken" else original(name)
        self.addCleanup(setattr, ev, "resolve_pack_dir", original)
        out = _tmp(self)
        code, _, err = self._main(["--llm", "mock", "--pack", "ryde-synth-v1", "--pack", "broken",
                                   "--out", str(out)])
        self.assertEqual(1, code)
        self.assertTrue(err.startswith("error:"), err)
        self.assertIn("RD-0101", err)
        self.assertEqual([], list(out.iterdir()), "no case may run against a broken label file")

    def test_any_failed_case_exit_2(self):
        import app.eval as ev

        original = ev.build_llm_client
        ev.build_llm_client = lambda *a, **k: FailsOnNS0202()
        self.addCleanup(setattr, ev, "build_llm_client", original)
        code, out, _ = self._main(["--llm", "mock", "--pack", "organiser-style-v1",
                                   "--out", str(_tmp(self))])
        self.assertEqual(2, code)
        self.assertIn("run failed", out)


class Docs(unittest.TestCase):
    def test_dataset_doc_names_the_command(self):
        text = (REPO / "docs" / "dataset.md").read_text(encoding="utf-8")
        self.assertIn("### Evaluation", text)
        self.assertIn("python3 -m app.eval", text)


if __name__ == "__main__":
    unittest.main()
