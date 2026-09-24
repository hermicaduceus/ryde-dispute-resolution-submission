"""Command-line entry point.

    python -m app.cli --dispute NS-0201                       # id in the default pack
    python -m app.cli --pack ryde-synth-v1 --dispute RD-0101   # id in a named pack
    python -m app.cli --dispute data/packs/ryde-synth-v1/disputes/RD-0101.json
    python -m app.cli --dispute <path> --policy docs/policy.md --llm tencent

--dispute takes either a path to a record file, as it always has, or a bare dispute id,
which is looked up as <pack_dir>/disputes/<id>.json in the selected pack. The pack comes
from app/config.json unless --pack names another one for this run.

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

from .config import ConfigError, load_config, resolve_pack_dir
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
    parser.add_argument(
        "--dispute",
        required=True,
        help="a dispute id within the selected pack (e.g. NS-0201), or a path to a record file",
    )
    parser.add_argument(
        "--pack",
        default=None,
        help="dataset pack to read disputes from, under data/packs/ (default: app/config.json)",
    )
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


def dispute_path(value: str, pack_dir: Path) -> Path:
    """Where --dispute points: a record file, or an id inside the selected pack.

    Anything that names a file — an existing path, a path separator, or a .json suffix —
    is used as given, so every command that worked before still means what it meant. A
    bare token is a dispute id, which keeps the demo's commands short and makes the pack
    the only place a case can come from.
    """
    if value.endswith(".json") or "/" in value or Path(value).exists():
        return Path(value)
    return Path(pack_dir) / "disputes" / ("%s.json" % value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config()
        pack_dir = resolve_pack_dir(args.pack) if args.pack else config.dataset_pack_dir
        dispute = load_dispute(dispute_path(args.dispute, pack_dir))
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
    ruling = resolution["ruling"] or resolution["withheld_candidate"]
    llm = (ruling.get("llm") or {}).get("provider") if ruling else None
    if llm is None and resolution["outcome"] == "needs_info":
        filed_by = (case_file.intake or {}).get("filed_by")
        filing_claim = {
            "rider": case_file.rider_case,
            "driver": case_file.driver_case,
        }.get(filed_by)
        llm = ((filing_claim or {}).get("llm") or {}).get("provider")
    print("")
    print("RYDE DISPUTE RESOLUTION — %s (%s)" % (case_file.dispute_id, case_file.category))
    print("run: %s   llm: %s   threshold: %.2f"
          % (case_file.run_id, llm or "n/a",
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
