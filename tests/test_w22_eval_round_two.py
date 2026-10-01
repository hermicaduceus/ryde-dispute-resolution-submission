"""Session A acceptance target (W22): the evaluation harness answers round two, and reports
autonomy and consistency.

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/session-nineteen-brief.md. Grill rulings 2026-10-01:

- Q2/Q10: when round one stops to ask the party (needs_info), the harness answers every
  question with "I have nothing more to add", runs round two, and scores the FINAL ruling.
  The round-one stop is reported on its own line, never hidden.
- N4: the report states how many cases were decided without a human (outcome "ruled").
- N2: --repeat N runs every case N times and reports how many cases gave the same
  decision every time. The score itself is the first run's.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.dispute import parse_dispute
from app.llm import LLMError, MockLLMClient
from app.policy import load_policy

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "data" / "packs"
POLICY = REPO / "docs" / "policy.md"


def _ev():
    import app.eval as ev  # lazy, so each test is RED on its own

    return ev


def _tmp(test: unittest.TestCase) -> Path:
    path = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, path, True)
    return path


def _pack_with_blank_answer(test, dispute_id="NS-0202", key="where_were_you") -> Path:
    """A copy of ryde-synth-v1 where one case left one intake answer blank.

    The mock's advocate asks about a blank intake answer, so round one stops on that case
    and only that case. Labels are copied unchanged.
    """
    pack = _tmp(test) / "ryde-synth-v1"
    shutil.copytree(PACKS / "ryde-synth-v1", pack)
    path = pack / "disputes" / ("%s.json" % dispute_id)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["intake"][key] = ""
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return pack


def _run(test, pack_dir, llm=None, repeat=None):
    out = _tmp(test)
    kwargs = {} if repeat is None else {"repeat": repeat}
    report = _ev().run_eval(pack_dir=pack_dir, llm=llm or MockLLMClient(),
                            policy=load_policy(POLICY), out_dir=out,
                            confidence_threshold=0.65, autonomous_cap_sgd=50.0, **kwargs)
    return report, out


class Recording(MockLLMClient):
    def __init__(self):
        super().__init__()
        self.prompts = []

    def complete(self, request):
        self.prompts.append((request.agent, request.user_prompt))
        return super().complete(request)


# ------------------------------------------------------------------ round two


class RoundTwoAnswer(unittest.TestCase):
    def test_the_fixed_answer(self):
        self.assertEqual("I have nothing more to add", _ev().NOTHING_MORE_TO_ADD)

    def test_answers_land_where_a_synth_record_carries_them(self):
        record = json.loads((PACKS / "ryde-synth-v1" / "disputes" / "NS-0202.json").read_text())
        before = copy.deepcopy(record)
        answered = _ev().with_round_two_answers(record, ["Q one?", "Q two?"])
        self.assertEqual(before, record, "the input record must not be modified")
        expected = [{"question": "Q one?", "answer": "I have nothing more to add"},
                    {"question": "Q two?", "answer": "I have nothing more to add"}]
        self.assertEqual(expected, answered["follow_up_answers"])
        self.assertEqual(expected, parse_dispute(answered).follow_up_answers)

    def test_answers_land_where_an_organiser_record_carries_them(self):
        record = json.loads((PACKS / "organiser-style-v1" / "disputes" / "NS-0202.json").read_text())
        before = copy.deepcopy(record)
        answered = _ev().with_round_two_answers(record, ["Q one?"])
        self.assertEqual(before, record, "the input record must not be modified")
        self.assertNotIn("follow_up_answers", answered)
        self.assertEqual([{"question": "Q one?", "answer": "I have nothing more to add"}],
                         answered["ryde_extensions"]["follow_up_answers"])
        self.assertEqual(1, len(parse_dispute(answered).follow_up_answers))

    def test_order_is_kept(self):
        record = json.loads((PACKS / "ryde-synth-v1" / "disputes" / "NS-0202.json").read_text())
        questions = ["c?", "a?", "b?"]
        answered = _ev().with_round_two_answers(record, questions)
        self.assertEqual(questions, [a["question"] for a in answered["follow_up_answers"]])


class RoundTwoRun(unittest.TestCase):
    def test_a_stop_is_answered_and_the_final_ruling_scored(self):
        report, out = _run(self, _pack_with_blank_answer(self))
        case = next(c for c in report.cases if c.dispute_id == "NS-0202")
        self.assertTrue(case.asked_in_round_one)
        self.assertEqual("match", case.reason)
        self.assertEqual("ruled: refund 6.61", case.got)
        self.assertTrue(case.decision_match)
        self.assertEqual("ryde-synth-v1/NS-0202/round-2/case_file.json", case.case_file)
        final = json.loads((out / case.case_file).read_text(encoding="utf-8"))
        self.assertEqual("ruled", final["resolution"]["outcome"])
        first = json.loads((out / "ryde-synth-v1" / "NS-0202" / "case_file.json").read_text())
        self.assertEqual("needs_info", first["resolution"]["outcome"], "round one is kept on disk")

    def test_only_the_stopped_case_is_marked(self):
        report, _ = _run(self, _pack_with_blank_answer(self))
        marked = [c.dispute_id for c in report.cases if c.asked_in_round_one]
        self.assertEqual(["NS-0202"], marked)
        self.assertEqual(1, report.totals["round_one_stops"])
        others = [c for c in report.cases if c.dispute_id != "NS-0202"]
        self.assertTrue(all(c.case_file and "round-2" not in c.case_file for c in others
                            if c.reason != "run failed"))

    def test_round_two_sends_the_fixed_answer_to_the_agents(self):
        llm = Recording()
        _run(self, _pack_with_blank_answer(self), llm=llm)
        ns0202 = [prompt for agent, prompt in llm.prompts if "NS-0202" in prompt]
        with_answer = [p for p in ns0202 if "I have nothing more to add" in p]
        # Round one: two advocates. Round two: two advocates and the Judge, all carrying it.
        self.assertEqual(5, len(ns0202))
        self.assertEqual(3, len(with_answer))
        judge_prompts = [p for a, p in llm.prompts if a == "judge" and "NS-0202" in p]
        self.assertEqual(1, len(judge_prompts), "the Judge runs once, in round two only")
        self.assertIn("I have nothing more to add", judge_prompts[0])

    def test_asked_the_party_no_longer_appears_on_a_stop(self):
        report, _ = _run(self, _pack_with_blank_answer(self))
        self.assertEqual(0, report.totals["by_reason"]["asked the party"])

    def test_a_round_two_model_failure_is_scored_as_one(self):
        class FailsInRoundTwo(MockLLMClient):
            def complete(self, request):
                if "NS-0202" in request.user_prompt and "I have nothing more to add" in request.user_prompt:
                    raise LLMError("round two outage")
                return super().complete(request)

        report, _ = _run(self, _pack_with_blank_answer(self), llm=FailsInRoundTwo())
        case = next(c for c in report.cases if c.dispute_id == "NS-0202")
        self.assertTrue(case.asked_in_round_one)
        self.assertEqual("model failed", case.reason)
        self.assertFalse(case.decision_match)

    def test_a_crash_in_round_two_does_not_stop_the_pack(self):
        class CrashesInRoundTwo(MockLLMClient):
            def complete(self, request):
                if "NS-0202" in request.user_prompt and "I have nothing more to add" in request.user_prompt:
                    raise TypeError("bug in round two")
                return super().complete(request)

        report, _ = _run(self, _pack_with_blank_answer(self), llm=CrashesInRoundTwo())
        by_id = {c.dispute_id: c for c in report.cases}
        self.assertEqual(17, len(report.cases))
        self.assertEqual("run failed", by_id["NS-0202"].reason)
        self.assertIn("bug in round two", by_id["NS-0202"].error)
        self.assertEqual("match", by_id["NS-0203"].reason)


# ------------------------------------------------------------------ autonomy


class Autonomy(unittest.TestCase):
    def test_decided_without_a_human_counts_ruled_outcomes_only(self):
        report, _ = _run(self, PACKS / "organiser-style-v1")
        decided = [c.dispute_id for c in report.cases if c.decided_without_human]
        # Not decided: OS-0301 (human_review), RD-0106 (RD-5 gate), RD-0108 (ESC-2),
        # RD-0109 (ESC-4). Measured on the reference build.
        self.assertEqual(14, len(decided))
        for held in ("OS-0301", "RD-0106", "RD-0108", "RD-0109"):
            self.assertNotIn(held, decided)
        self.assertEqual(14, report.totals["decided_without_human"])

    def test_a_wrong_ruling_still_counts_as_decided(self):
        # Autonomy measures who decided, not whether it was right: NS-0201 is a wrong
        # action on the mock and was still decided without a human.
        report, _ = _run(self, PACKS / "organiser-style-v1")
        case = next(c for c in report.cases if c.dispute_id == "NS-0201")
        self.assertEqual(("wrong action", True), (case.reason, case.decided_without_human))

    def test_a_needs_info_never_counts_and_a_round_two_ruling_does(self):
        report, _ = _run(self, _pack_with_blank_answer(self))
        case = next(c for c in report.cases if c.dispute_id == "NS-0202")
        self.assertTrue(case.decided_without_human)
        res = _ev().score_case({"dispute_id": "X", "expected_outcome": "ruled",
                                "expected_action": "refund", "expected_amount_sgd": 1.0,
                                "decisive_rule_ids": []},
                               {"outcome": "needs_info", "ruling": None, "withheld_candidate": None})
        self.assertFalse(res.decided_without_human)

    def test_model_failure_and_run_failure_never_count(self):
        label = {"dispute_id": "X", "expected_outcome": "ruled", "expected_action": "refund",
                 "expected_amount_sgd": 1.0, "decisive_rule_ids": []}
        self.assertFalse(_ev().score_error(label, "boom").decided_without_human)
        failed = _ev().score_case(label, {"outcome": "withheld", "ruling": None,
                                          "withheld_candidate": None,
                                          "model_failure": {"message": "down"}})
        self.assertFalse(failed.decided_without_human)

    def test_headlines_on_the_mock(self):
        report, _ = _run(self, PACKS / "organiser-style-v1")
        md = _ev().render_markdown(report).splitlines()
        self.assertIn("Decided without a human: 14 of 18", md)
        self.assertIn("Stopped to ask the party in round one: 0 of 18", md)
        self.assertFalse(any(line.startswith("Same decision on all") for line in md),
                         "no consistency line without --repeat")


# ------------------------------------------------------------------ repeat


class FlipsOnFirstRun(MockLLMClient):
    """The mock, except the Judge's FIRST ruling on RD-0101 is a different amount."""

    def __init__(self):
        super().__init__()
        self.judged = {}

    def complete(self, request):
        response = super().complete(request)
        if request.agent == "judge" and "RD-0101" in request.user_prompt:
            self.judged["RD-0101"] = self.judged.get("RD-0101", 0) + 1
            if self.judged["RD-0101"] == 1:
                payload = json.loads(response.text)
                payload["recommended_amount_sgd"] = 4.00
                response = dataclasses.replace(response, text=json.dumps(payload))
        return response


class Repeat(unittest.TestCase):
    def test_default_is_one_run(self):
        report, out = _run(self, PACKS / "ryde-synth-v1")
        self.assertEqual(1, report.repeat)
        self.assertIsNone(report.totals["consistent"])
        self.assertTrue(all(c.consistent is None and c.repeat_got is None for c in report.cases))
        self.assertFalse((out / "ryde-synth-v1" / "RD-0101" / "run-2").exists())

    def test_three_identical_runs_are_all_consistent(self):
        report, out = _run(self, PACKS / "ryde-synth-v1", repeat=3)
        self.assertEqual(3, report.repeat)
        self.assertEqual(17, report.totals["consistent"])
        case = next(c for c in report.cases if c.dispute_id == "RD-0101")
        self.assertEqual(["ruled: refund 5.81"] * 3, case.repeat_got)
        for run in ("run-2", "run-3"):
            self.assertTrue((out / "ryde-synth-v1" / "RD-0101" / run / "case_file.json").exists(), run)
        self.assertTrue((out / "ryde-synth-v1" / "RD-0101" / "case_file.json").exists())

    def test_a_flip_is_inconsistent_and_the_score_is_the_first_run(self):
        report, _ = _run(self, PACKS / "ryde-synth-v1", llm=FlipsOnFirstRun(), repeat=3)
        case = next(c for c in report.cases if c.dispute_id == "RD-0101")
        self.assertEqual(["ruled: refund 4.00", "ruled: refund 5.81", "ruled: refund 5.81"],
                         case.repeat_got)
        self.assertFalse(case.consistent)
        self.assertEqual("wrong amount", case.reason, "the score is the first run's")
        self.assertEqual("ruled: refund 4.00", case.got)
        self.assertEqual(16, report.totals["consistent"])
        md = _ev().render_markdown(report).splitlines()
        self.assertIn("Same decision on all 3 runs: 16 of 17", md)

    def test_a_failed_repetition_is_never_consistent(self):
        class FailsOnThirdNS0202(MockLLMClient):
            def __init__(self):
                super().__init__()
                self.n = 0

            def complete(self, request):
                if request.agent == "rider_advocate" and "NS-0202" in request.user_prompt:
                    self.n += 1
                    if self.n == 3:
                        raise TypeError("bug on run three")
                return super().complete(request)

        report, _ = _run(self, PACKS / "ryde-synth-v1", llm=FailsOnThirdNS0202(), repeat=3)
        case = next(c for c in report.cases if c.dispute_id == "NS-0202")
        self.assertEqual("match", case.reason)
        self.assertEqual("run failed", case.repeat_got[2])
        self.assertFalse(case.consistent)

    def test_identical_failures_are_never_consistent(self):
        class AlwaysDownOnNS0202(MockLLMClient):
            def complete(self, request):
                if "NS-0202" in request.user_prompt:
                    raise LLMError("down every time")
                return super().complete(request)

        report, _ = _run(self, PACKS / "ryde-synth-v1", llm=AlwaysDownOnNS0202(), repeat=2)
        case = next(c for c in report.cases if c.dispute_id == "NS-0202")
        self.assertEqual("model failed", case.reason)
        self.assertEqual(1, len(set(case.repeat_got)), "both runs read the same")
        self.assertFalse(case.consistent, "failing the same way twice is not a decision")
        self.assertEqual(16, report.totals["consistent"])

    def test_repeat_out_of_range_is_refused_before_anything_runs(self):
        for bad in (0, -1, 6, True, 1.5, "3", None):
            with self.subTest(repeat=bad):
                out = _tmp(self)
                with self.assertRaises(_ev().EvalError):
                    _ev().run_eval(pack_dir=PACKS / "ryde-synth-v1", llm=MockLLMClient(),
                                   policy=load_policy(POLICY), out_dir=out,
                                   confidence_threshold=0.65, autonomous_cap_sgd=50.0, repeat=bad)
                self.assertEqual([], list(out.iterdir()))

    def test_max_repeat_constant(self):
        self.assertEqual(5, _ev().MAX_REPEAT)


# ------------------------------------------------------------------ reports + CLI


class ReportShape(unittest.TestCase):
    def test_json_carries_the_new_fields(self):
        out = _tmp(self)
        with contextlib.redirect_stdout(io.StringIO()):
            code = _ev().main(["--llm", "mock", "--pack", "ryde-synth-v1", "--repeat", "2",
                               "--out", str(out)])
        self.assertEqual(0, code)
        data = json.loads((out / "ryde-synth-v1" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(2, data["repeat"])
        for key in ("decided_without_human", "round_one_stops", "consistent"):
            self.assertIn(key, data["totals"])
        self.assertEqual(17, data["totals"]["consistent"])
        case = data["cases"][0]
        for key in ("asked_in_round_one", "decided_without_human", "repeat_got", "consistent"):
            self.assertIn(key, case)
        self.assertEqual(2, len(case["repeat_got"]))

    def test_markdown_table_has_the_round_one_column(self):
        report, _ = _run(self, _pack_with_blank_answer(self))
        lines = _ev().render_markdown(report).splitlines()
        self.assertIn("| Case | Expected | Got | Result | Missing rules | Asked in round one |", lines)
        row = next(l for l in lines if l.startswith("| NS-0202 |"))
        self.assertEqual("yes", row.split("|")[-2].strip())
        row = next(l for l in lines if l.startswith("| NS-0203 |"))
        self.assertEqual("", row.split("|")[-2].strip())

    def test_stdout_prints_every_headline(self):
        out = _tmp(self)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            _ev().main(["--llm", "mock", "--pack", "ryde-synth-v1", "--repeat", "2", "--out", str(out)])
        text = stdout.getvalue()
        for line in ("Decided without a human: 13 of 17",
                     "Stopped to ask the party in round one: 0 of 17",
                     "Same decision on all 2 runs: 17 of 17"):
            self.assertIn(line, text)
        self.assertNotIn("%", text)


class Cli(unittest.TestCase):
    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _ev().main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_bad_repeat_exits_1_and_writes_nothing(self):
        for bad in ("0", "6", "-2"):
            with self.subTest(repeat=bad):
                out = _tmp(self)
                code, _, err = self._main(["--llm", "mock", "--pack", "ryde-synth-v1",
                                           "--repeat", bad, "--out", str(out)])
                self.assertEqual(1, code)
                self.assertTrue(err.startswith("error:"), err)
                self.assertEqual([], list(out.iterdir()))

    def test_help_names_repeat(self):
        self.assertIn("--repeat", _ev().build_parser().format_help())


class Docs(unittest.TestCase):
    def test_dataset_doc_explains_the_new_lines(self):
        text = (REPO / "docs" / "dataset.md").read_text(encoding="utf-8")
        section = text.split("### Evaluation", 1)[1]
        for needle in ("--repeat", "I have nothing more to add", "Decided without a human",
                       "Same decision on all"):
            self.assertIn(needle, section)


if __name__ == "__main__":
    unittest.main()
