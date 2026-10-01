"""Evaluate every labelled dispute in a dataset pack.

The evaluator deliberately keeps labels outside the dispute pipeline.  It reads the
labels only after the pack has been validated, runs each record through the same
pipeline as :mod:`app.cli`, and scores the resulting resolution afterwards.

A case that stops to ask the party is not a miss any more: the harness answers every
question with a fixed "I have nothing more to add" and runs round two, scoring the
final ruling.  It also reports how many cases were decided without a human, and with
``repeat`` it can run every case more than once to measure whether rulings stay the
same.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .agents import RetryPolicy
from .config import ConfigError, load_config, resolve_pack_dir
from .dispute import is_organiser_record, parse_dispute
from .events import EventLog
from .llm import LLMError, build_llm_client
from .pipeline import run_dispute
from .policy import PolicyError, load_policy


MOCK_WARNING = (
    "MOCK RUN: the mock is a deterministic stand-in, not a solver. "
    "This score checks the wiring, not the system."
)
CAVEAT = (
    "Measured on a synthesised demonstration corpus against the team's own labels: "
    "a check of internal consistency, not real-world accuracy."
)
#: The fixed answer the harness gives to every round-two question.
NOTHING_MORE_TO_ADD = "I have nothing more to add"
#: The most times one case may be repeated in a single run.
MAX_REPEAT = 5
#: The folder a round-two run writes into, inside the case's own directory.
ROUND_TWO_DIR = "round-2"
REASONS = [
    "match",
    "wrong outcome",
    "wrong action",
    "wrong amount",
    "asked the party",
    "model failed",
    "run failed",
]


class EvalError(RuntimeError):
    """The evaluation labels are missing, unreadable, or inconsistent with the pack."""


def _is_number(value: Any) -> bool:
    """True only for a real number. bool is an int subclass; a numeric string is not one."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass
class CaseScore:
    dispute_id: str
    expected: str
    got: str
    reason: str
    decision_match: bool
    grounded: Optional[bool]
    rules_missing: List[str]
    error: Optional[str] = None
    case_file: Optional[str] = None
    #: True when round one stopped to ask the party, whatever happened afterwards.
    asked_in_round_one: bool = False
    #: True only when the scored outcome is "ruled": who decided, not whether right.
    decided_without_human: bool = False
    #: Every repeat's decision text, in run order, when the case was repeated.
    repeat_got: Optional[List[str]] = None
    #: True only when every repeat decided identically and none failed.
    consistent: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dispute_id": self.dispute_id,
            "expected": self.expected,
            "got": self.got,
            "reason": self.reason,
            "decision_match": self.decision_match,
            "grounded": self.grounded,
            "rules_missing": list(self.rules_missing),
            "error": self.error,
            "case_file": self.case_file,
            "asked_in_round_one": self.asked_in_round_one,
            "decided_without_human": self.decided_without_human,
            "repeat_got": list(self.repeat_got) if self.repeat_got is not None else None,
            "consistent": self.consistent,
        }


@dataclass
class EvalReport:
    pack: str
    provider: str
    threshold: float
    autonomous_cap_sgd: float
    generated_at: str
    cases: List[CaseScore]
    totals: Dict[str, Any]
    repeat: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pack": self.pack,
            "provider": self.provider,
            "threshold": self.threshold,
            "autonomous_cap_sgd": self.autonomous_cap_sgd,
            "repeat": self.repeat,
            "generated_at": self.generated_at,
            "totals": self.totals,
            "cases": [case.to_dict() for case in self.cases],
        }


# --------------------------------------------------------------------------- labels


def load_labels(pack_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load labels and verify that they cover exactly the pack's dispute files."""
    pack_path = Path(pack_dir)
    labels_path = pack_path / "ground-truth.json"
    try:
        raw = labels_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise EvalError("unable to read labels at %s: %s" % (labels_path, exc)) from exc

    try:
        document = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise EvalError("labels file is not valid JSON: %s" % labels_path) from exc

    if not isinstance(document, dict):
        raise EvalError("labels file must contain an object: %s" % labels_path)
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise EvalError("labels file has no cases list: %s" % labels_path)

    labels: Dict[str, Dict[str, Any]] = {}
    for index, label in enumerate(cases, start=1):
        if not isinstance(label, dict):
            raise EvalError("label %d in %s is not an object" % (index, labels_path))
        dispute_id = label.get("dispute_id")
        if not isinstance(dispute_id, str) or not dispute_id.strip():
            raise EvalError("label %d in %s has no dispute_id" % (index, labels_path))
        if dispute_id in labels:
            raise EvalError("duplicate label for dispute %s" % dispute_id)
        if label.get("expected_outcome") == "ruled" and not _is_number(
            label.get("expected_amount_sgd")
        ):
            raise EvalError(
                "label for dispute %s has a non-numeric expected_amount_sgd (%r): a ruled "
                "label must state the amount as a number"
                % (dispute_id, label.get("expected_amount_sgd"))
            )
        labels[dispute_id] = label

    disputes_dir = pack_path / "disputes"
    dispute_paths = sorted(disputes_dir.glob("*.json"), key=lambda path: path.name)
    dispute_ids = [path.stem for path in dispute_paths]
    dispute_id_set = set(dispute_ids)

    without_labels = [dispute_id for dispute_id in dispute_ids if dispute_id not in labels]
    without_files = sorted(dispute_id for dispute_id in labels if dispute_id not in dispute_id_set)
    if without_labels or without_files:
        details = []
        if without_labels:
            details.append("dispute files without labels: %s" % ", ".join(without_labels))
        if without_files:
            details.append("labels without dispute files: %s" % ", ".join(without_files))
        raise EvalError("label set does not match %s: %s" % (pack_path, "; ".join(details)))

    return labels


# -------------------------------------------------------------------------- scoring


def _expected_text(label: Dict[str, Any]) -> str:
    outcome = label.get("expected_outcome")
    if outcome != "ruled":
        return str(outcome)
    action = label.get("expected_action")
    amount = label.get("expected_amount_sgd")
    if not _is_number(amount):
        return "ruled: %s invalid amount" % action
    return "ruled: %s %.2f" % (action, amount)


def _candidate(resolution: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ruling = resolution.get("ruling")
    if ruling is not None:
        return ruling
    return resolution.get("withheld_candidate")


def _decision_text(resolution: Dict[str, Any]) -> str:
    outcome = resolution.get("outcome")
    if outcome == "needs_info":
        return str(outcome)
    candidate = _candidate(resolution)
    if candidate is None:
        return str(outcome)
    amount = candidate.get("recommended_amount_sgd")
    rendered = "%.2f" % amount if _is_number(amount) else "invalid amount"
    return "%s: %s %s" % (outcome, candidate.get("action"), rendered)


def _grounding(
    label: Dict[str, Any], resolution: Dict[str, Any]
) -> Tuple[Optional[bool], List[str]]:
    if resolution.get("outcome") == "needs_info":
        return None, []
    candidate = _candidate(resolution)
    if candidate is None:
        return None, []

    cited = candidate.get("cited_rule_ids") or []
    cited_ids = set(cited)
    rules_missing = [
        rule_id
        for rule_id in label.get("decisive_rule_ids", [])
        if not rule_id.startswith("ESC-") and rule_id not in cited_ids
    ]
    return not rules_missing, rules_missing


def _amount_matches(candidate: Optional[Dict[str, Any]], label: Dict[str, Any]) -> bool:
    """Cent-exact comparison that never coerces: a malformed amount is a mismatch."""
    if candidate is None:
        return False
    amount = candidate.get("recommended_amount_sgd")
    expected = label.get("expected_amount_sgd")
    if not _is_number(amount) or not _is_number(expected):
        return False
    return round(amount, 2) == round(expected, 2)


def score_case(label: Dict[str, Any], resolution: Dict[str, Any]) -> CaseScore:
    """Compare one pipeline resolution with its label."""
    expected = _expected_text(label)
    got = _decision_text(resolution)
    outcome = resolution.get("outcome")
    candidate = _candidate(resolution)
    failure = resolution.get("model_failure")

    if failure is not None:
        return CaseScore(
            dispute_id=label["dispute_id"],
            expected=expected,
            got=got,
            reason="model failed",
            decision_match=False,
            grounded=None,
            rules_missing=[],
            error=failure.get("message") if isinstance(failure, dict) else str(failure),
        )

    if outcome == "needs_info":
        reason = "asked the party"
        decision_match = False
    else:
        comparable_outcome = "escalated" if outcome == "withheld" else outcome
        if comparable_outcome != label.get("expected_outcome"):
            reason = "wrong outcome"
            decision_match = False
        elif outcome == "ruled" and (
            candidate is None or candidate.get("action") != label.get("expected_action")
        ):
            reason = "wrong action"
            decision_match = False
        elif outcome == "ruled" and not _amount_matches(candidate, label):
            reason = "wrong amount"
            decision_match = False
        else:
            reason = "match"
            decision_match = True

    grounded, rules_missing = _grounding(label, resolution)
    return CaseScore(
        dispute_id=label["dispute_id"],
        expected=expected,
        got=got,
        reason=reason,
        decision_match=decision_match,
        grounded=grounded,
        rules_missing=rules_missing,
        # Autonomy measures who decided, not whether the decision was right: a ruled
        # outcome was decided by the system, however it scored against the label.
        decided_without_human=outcome == "ruled",
    )


def score_error(label: Dict[str, Any], message: str) -> CaseScore:
    """Turn one per-case pipeline failure into a score without stopping the pack."""
    return CaseScore(
        dispute_id=label["dispute_id"],
        expected=_expected_text(label),
        got="run failed",
        reason="run failed",
        decision_match=False,
        grounded=None,
        rules_missing=[],
        error=str(message),
    )


# --------------------------------------------------------------------------- running


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-") or "case"


def _case_file_relative(pack_name: str, dispute_id: str, *parts: str) -> str:
    return str(Path(pack_name).joinpath(dispute_id, *parts, "case_file.json"))


def _totals(cases: List[CaseScore], repeat: int = 1) -> Dict[str, Any]:
    by_reason = {reason: 0 for reason in REASONS}
    for case in cases:
        by_reason[case.reason] = by_reason.get(case.reason, 0) + 1
    return {
        "cases": len(cases),
        "decisions_matching": sum(1 for case in cases if case.decision_match),
        "grounding_applicable": sum(1 for case in cases if case.grounded is not None),
        "grounded": sum(1 for case in cases if case.grounded is True),
        "decided_without_human": sum(1 for case in cases if case.decided_without_human),
        "round_one_stops": sum(1 for case in cases if case.asked_in_round_one),
        "consistent": (
            sum(1 for case in cases if case.consistent is True) if repeat > 1 else None
        ),
        "by_reason": by_reason,
    }


def _refuse_existing_output(pack_out: Path) -> EvalError:
    """The refusal for a pack output directory a previous run already owns."""
    return EvalError(
        "refusing to reuse evaluation output %s: it already exists. "
        "Move it aside or choose another --out directory." % pack_out
    )


def _validate_repeat(repeat: Any) -> int:
    """Refuse anything that is not a real int from 1 to MAX_REPEAT.

    bool is an int subclass and is refused: `True` must never read as one run.
    """
    if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= MAX_REPEAT:
        raise EvalError(
            "repeat must be an integer between 1 and %d, got %r" % (MAX_REPEAT, repeat)
        )
    return repeat


def with_round_two_answers(record: Dict[str, Any], questions: List[str]) -> Dict[str, Any]:
    """A deep copy of the raw record carrying one fixed answer per question.

    The answers go where the record's own shape carries them, exactly as
    :mod:`app.server` attaches a party's answers: under ``ryde_extensions`` for an
    organiser-shaped record, at the top level otherwise. The input record is left
    unchanged.
    """
    answered = copy.deepcopy(record)
    answers = [
        {"question": question, "answer": NOTHING_MORE_TO_ADD} for question in questions
    ]
    if is_organiser_record(answered):
        answered.setdefault("ryde_extensions", {})["follow_up_answers"] = answers
    else:
        answered["follow_up_answers"] = answers
    return answered


def _run_once(
    record: Dict[str, Any],
    *,
    run_dir: Path,
    run_id: str,
    llm: Any,
    policy: Any,
    confidence_threshold: float,
    autonomous_cap_sgd: float,
    retry_policy: Optional[RetryPolicy],
) -> Dict[str, Any]:
    """Run one record through the pipeline, write its case file, return the resolution."""
    events = EventLog(run_dir, run_id)
    case_file = run_dispute(
        dispute=parse_dispute(record),
        llm=llm,
        policy=policy,
        events=events,
        confidence_threshold=confidence_threshold,
        autonomous_cap_sgd=autonomous_cap_sgd,
        retry_policy=retry_policy,
    )
    case_file.write(run_dir)
    return case_file.to_dict()["resolution"]


def run_eval(
    *,
    pack_dir: Path,
    llm: Any,
    policy: Any,
    out_dir: Path,
    confidence_threshold: float,
    autonomous_cap_sgd: float,
    retry_policy: Optional[RetryPolicy] = None,
    repeat: int = 1,
) -> EvalReport:
    """Run and score all cases in one validated pack.

    With ``repeat`` above 1 every case runs that many times: run 1 lives at
    ``<pack>/<id>/``, run n at ``<pack>/<id>/run-<n>/``, and the case's score is run
    1's. A round-one stop is answered with the fixed round-two answer, and the final
    ruling is what gets scored; the round-one stop is counted on its own.
    """
    repeat = _validate_repeat(repeat)
    pack_path = Path(pack_dir)
    out_path = Path(out_dir)
    labels = load_labels(pack_path)
    dispute_paths = sorted((pack_path / "disputes").glob("*.json"), key=lambda path: path.name)
    pack_name = pack_path.name
    pack_out = out_path / pack_name
    # Exclusive creation: a second run must never append to a first run's event log or
    # overwrite its payloads. The directory is never deleted, merged or overwritten.
    try:
        pack_out.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise _refuse_existing_output(pack_out) from exc

    scores: List[CaseScore] = []
    for dispute_path in dispute_paths:
        dispute_id = dispute_path.stem
        case_dir = pack_out / dispute_id
        label = labels[dispute_id]
        try:
            record = json.loads(dispute_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            scores.append(score_error(label, str(exc)))
            continue

        run_scores: List[CaseScore] = []
        asked = False
        for run_number in range(1, repeat + 1):
            run_dir = case_dir if run_number == 1 else case_dir / ("run-%d" % run_number)
            run_id = "%s-%s%s" % (
                _now().replace(":", "").replace("+00:00", "Z"),
                _slug(dispute_id),
                "" if run_number == 1 else "-run-%d" % run_number,
            )
            asked_this_run = False
            round_two = False
            try:
                resolution = _run_once(
                    record,
                    run_dir=run_dir,
                    run_id=run_id,
                    llm=llm,
                    policy=policy,
                    confidence_threshold=confidence_threshold,
                    autonomous_cap_sgd=autonomous_cap_sgd,
                    retry_policy=retry_policy,
                )
                if resolution.get("outcome") == "needs_info":
                    # Round two: answer every question and run again. The final
                    # ruling is what gets scored; round one's files stay on disk.
                    asked_this_run = True
                    answered = with_round_two_answers(
                        record, resolution.get("questions_for_party") or []
                    )
                    round_two = True
                    resolution = _run_once(
                        answered,
                        run_dir=run_dir / ROUND_TWO_DIR,
                        run_id=run_id + "-round-2",
                        llm=llm,
                        policy=policy,
                        confidence_threshold=confidence_threshold,
                        autonomous_cap_sgd=autonomous_cap_sgd,
                        retry_policy=retry_policy,
                    )
                run_score = score_case(label, resolution)
                # Only a run that wrote its file gets a path; a failed run keeps None.
                if run_number == 1:
                    run_score.case_file = _case_file_relative(
                        pack_name, dispute_id, *((ROUND_TWO_DIR,) if round_two else ())
                    )
            except Exception as exc:
                # Deliberately broad: a provider or scoring bug outside the known error
                # types must not abort the pack. BaseException is not caught, so Ctrl-C
                # still stops. A failing repetition is recorded, never skipped.
                run_score = score_error(label, str(exc))
            if run_number == 1:
                asked = asked_this_run
            run_scores.append(run_score)

        score = run_scores[0]
        score.asked_in_round_one = asked
        if repeat > 1:
            score.repeat_got = [run.got for run in run_scores]
            # Failing the same way every time is not a decision.
            score.consistent = (
                not any(run.reason in ("model failed", "run failed") for run in run_scores)
                and len(set(score.repeat_got)) == 1
            )
        scores.append(score)

    report = EvalReport(
        pack=pack_name,
        provider=llm.provider_name,
        threshold=confidence_threshold,
        autonomous_cap_sgd=autonomous_cap_sgd,
        generated_at=_now(),
        cases=scores,
        totals=_totals(scores, repeat),
        repeat=repeat,
    )
    pack_out.joinpath("report.json").write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    pack_out.joinpath("report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


# ------------------------------------------------------------------------- reports


def _headlines(report: EvalReport) -> List[str]:
    totals = report.totals
    lines = [
        "Decisions matching the label: %d of %d"
        % (totals["decisions_matching"], totals["cases"]),
        "Rulings citing every decisive rule: %d of %d"
        % (totals["grounded"], totals["grounding_applicable"]),
        "Decided without a human: %d of %d"
        % (totals["decided_without_human"], totals["cases"]),
        "Stopped to ask the party in round one: %d of %d"
        % (totals["round_one_stops"], totals["cases"]),
    ]
    if report.repeat > 1:
        lines.append(
            "Same decision on all %d runs: %d of %d"
            % (report.repeat, totals["consistent"], totals["cases"])
        )
    return lines


def render_markdown(report: EvalReport) -> str:
    """Render the human-readable report without percentages."""
    lines = ["# Evaluation: %s, provider %s" % (report.pack, report.provider), ""]
    if report.provider == "mock":
        lines.append(MOCK_WARNING)
    lines.append(CAVEAT)
    lines.extend(["", *_headlines(report), ""])
    lines.extend([
        "| Case | Expected | Got | Result | Missing rules | Asked in round one |",
        "|---|---|---|---|---|---|",
    ])
    for case in report.cases:
        lines.append(
            "| %s | %s | %s | %s | %s | %s |"
            % (
                case.dispute_id,
                case.expected,
                case.got,
                case.reason,
                ", ".join(case.rules_missing),
                "yes" if case.asked_in_round_one else "",
            )
        )
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------ CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval",
        description="Evaluate labelled dispute dataset packs through the resolution pipeline.",
    )
    parser.add_argument(
        "--pack",
        action="append",
        default=None,
        metavar="NAME",
        help="dataset pack to evaluate; repeat for multiple packs",
    )
    parser.add_argument(
        "--llm",
        default=None,
        help="LLM provider: mock or tencent (default: app/config.json)",
    )
    parser.add_argument("--out", default=None, metavar="DIR", help="evaluation output directory")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="run every case N times (1-%d) and report whether the decision repeats" % MAX_REPEAT,
    )
    return parser


def _print_report(report: EvalReport, out_dir: Path) -> None:
    print("Evaluation: %s, provider %s" % (report.pack, report.provider))
    if report.provider == "mock":
        print(MOCK_WARNING)
    print(CAVEAT)
    for case in report.cases:
        print(
            "%s | expected: %s | got: %s | %s"
            % (case.dispute_id, case.expected, case.got, case.reason)
        )
    for headline in _headlines(report):
        print(headline)
    print("report: %s" % (out_dir / report.pack / "report.md"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    pack_names = args.pack or ["organiser-style-v1", "ryde-synth-v1"]

    try:
        config = load_config()
        pack_dirs = [resolve_pack_dir(name) for name in pack_names]
        # Preflight every requested label set before constructing output or calling a case.
        for pack_dir in pack_dirs:
            load_labels(pack_dir)
        policy = load_policy(config.policy_path)
        provider = args.llm or config.llm.provider
        llm = (
            build_llm_client(provider, settings=config.llm)
            if provider == "tencent"
            else build_llm_client(provider)
        )
        out_dir = (
            Path(args.out)
            if args.out
            else config.out_dir
            / ("eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        )
        # Preflight every requested output path too: an existing pack directory belongs
        # to an earlier run and must be refused before the first case runs. run_eval
        # still creates each directory exclusively, so the check-and-create has no race.
        for pack_dir in pack_dirs:
            pack_out = out_dir / pack_dir.name
            if pack_out.exists():
                raise _refuse_existing_output(pack_out)
    except (ConfigError, EvalError, LLMError, PolicyError, OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    reports: List[EvalReport] = []
    try:
        for pack_dir in pack_dirs:
            reports.append(
                run_eval(
                    pack_dir=pack_dir,
                    llm=llm,
                    policy=policy,
                    out_dir=out_dir,
                    confidence_threshold=config.confidence_threshold,
                    autonomous_cap_sgd=config.autonomous_cap_sgd,
                    retry_policy=RetryPolicy(budget_seconds=config.llm.case_budget_seconds),
                    repeat=args.repeat,
                )
            )
    except (ConfigError, EvalError, LLMError, PolicyError, OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    for report in reports:
        _print_report(report, out_dir)
    if any(case.reason in ("model failed", "run failed") for report in reports for case in report.cases):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
