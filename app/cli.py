"""Command-line entry point.

    python -m app.cli --dispute tests/fixtures/dispute_route_deviation.json
    python -m app.cli --dispute <path> --policy docs/policy.md --llm tencent

Runs one dispute through the full pipeline and writes the run's artifacts:

    <out>/<run_id>/events.jsonl      append-only event log (the observable traffic)
    <out>/<run_id>/payloads/*.json   full payload for each event
    <out>/<run_id>/case_file.json    assembled record: evidence, claims, resolution, strip

Defaults come from app/config.json; the flags override them for a single run.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from .config import ConfigError, load_config
from .dispute import DisputeError, load_dispute
from .events import EventLog
from .llm import LLMError, build_llm_client
from .pipeline import run_dispute
from .policy import PolicyError, load_policy

EXIT_OK = 0
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Run one ride-hailing dispute through the multi-agent resolution pipeline.",
    )
    parser.add_argument("--dispute", required=True, help="path to one dispute JSON file")
    parser.add_argument(
        "--policy", default=None, help="path to the policy document (default: app/config.json)"
    )
    parser.add_argument(
        "--llm",
        default=None,
        choices=["mock", "tencent"],
        help="LLM provider (default: app/config.json). 'mock' needs no API key.",
    )
    parser.add_argument("--out", default=None, help="output directory for run artifacts")
    parser.add_argument("--run-id", default=None, help="override the generated run id")
    return parser


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-") or "run"


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config()
        dispute = load_dispute(Path(args.dispute))
        policy = load_policy(Path(args.policy) if args.policy else config.policy_path)
        provider = args.llm or config.llm.provider
        llm = (
            build_llm_client(provider, settings=config.llm)
            if provider == "tencent"
            else build_llm_client(provider)
        )
    except (ConfigError, DisputeError, PolicyError, LLMError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_FAILED

    out_dir = Path(args.out) if args.out else config.out_dir
    run_id = args.run_id or "%s-%s" % (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        _slug(dispute.dispute_id),
    )
    run_dir = out_dir / run_id
    events = EventLog(run_dir, run_id)

    try:
        case_file = run_dispute(
            dispute=dispute,
            llm=llm,
            policy=policy,
            events=events,
            confidence_threshold=config.confidence_threshold,
            autonomous_cap_sgd=config.autonomous_cap_sgd,
        )
    except (DisputeError, PolicyError, LLMError, RuntimeError, ValueError) as exc:
        print("error: the run failed: %s" % exc, file=sys.stderr)
        print("partial event log: %s" % events.events_path, file=sys.stderr)
        return EXIT_FAILED

    case_path = case_file.write(run_dir)
    _print_report(case_file, events, case_path)
    return EXIT_OK


def _print_report(case_file, events: EventLog, case_path: Path) -> None:
    resolution = case_file.resolution
    print("")
    print("RYDE DISPUTE RESOLUTION — %s (%s)" % (case_file.dispute_id, case_file.category))
    print("run: %s   llm: %s   threshold: %.2f"
          % (case_file.run_id, resolution["ruling"]["llm"]["provider"] if resolution["ruling"] else "n/a",
             case_file.confidence_threshold))
    print("")
    print("EVENT STRIP")
    for event in events.snapshot():
        print(
            "%3d  %-24s %-18s -> %-16s %s"
            % (event["seq"], event["ts"], event["from"], event["to"], event["summary"])
        )
    print("")
    print("RESOLUTION")
    print("  outcome:  %s" % resolution["outcome"])
    if resolution["ruling"]:
        ruling = resolution["ruling"]
        print("  ruling:   %s of SGD %.2f (confidence %.2f)"
              % (ruling["action"], ruling["recommended_amount_sgd"], ruling["confidence"]))
        print("  rules:    %s" % (", ".join(ruling["cited_rule_ids"]) or "(none cited)"))
    if resolution["withheld_candidate"]:
        candidate = resolution["withheld_candidate"]
        print("  withheld: %s of SGD %.2f at confidence %.2f — not delivered to the parties"
              % (candidate["action"], candidate["recommended_amount_sgd"], candidate["confidence"]))
    print("  parties:  %s" % resolution["party_message"])
    print("")
    print("ARTIFACTS")
    print("  event log: %s" % events.events_path)
    print("  case file: %s" % case_path)
    print("")


if __name__ == "__main__":
    sys.exit(main())
