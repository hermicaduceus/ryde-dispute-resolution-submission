"""Session twenty round two (W22 review fix): the same class, the inputs round one missed.

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/build-briefs/session-twenty-round-two-brief.md. Ruled by the operator on 2026-10-01 (night) after the
review of round one reproduced:

1. MAJOR: a JSON integer too large for a float (json.loads returns a Python int of any size)
   was silently dropped from the tariff rates, the fare was recomputed from the remainder,
   and RD-5 enforced the manufactured difference: a refund of SGD 9.96 reached the party.
   An integer too large for a float is an unreadable number, exactly like NaN.
2. A route case whose record STATES a fare input it cannot read (a tariff rate or the promo)
   is held under ESC-2: the overcharge is unprovable either way, so RD-5 has nothing to hold
   the ruling to. A record with no rates at all stays with the model (RD-3, residue).
3. The evidence layer's own arithmetic can overflow (a huge distance over a tiny one) and put
   Infinity into the pack. A computed figure that is not finite reads as missing.
4. An unreadable number in an intake answer, or as a party's identifier, is blanked when the
   dispute is parsed, so it never reaches a prompt or the case file.
5. A model reply whose amount is an integer too large for a float is a contract failure, not
   a crash.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import tempfile
import unittest
from pathlib import Path

from app.dispute import parse_dispute
from app.events import EventLog
from app.evidence import build_evidence_pack
from app.llm.mock import MockLLMClient
from app.pipeline import run_dispute
from app.policy import load_policy
from app.schemas import UNDER_REVIEW_MESSAGE

from tests.support import ScriptedLLM

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "data" / "packs"
SYNTH = PACKS / "ryde-synth-v1" / "disputes"
ORGANISER = PACKS / "organiser-style-v1" / "disputes"
POLICY = REPO / "docs" / "policy.md"

HUGE = 10 ** 400
UNREADABLE = (float("nan"), float("inf"), float("-inf"), HUGE, -HUGE)
RATES = ("base_sgd", "per_km_sgd", "per_min_sgd", "surge_multiplier")


def _record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _set(record: dict, path, value) -> dict:
    out = copy.deepcopy(record)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


def _delete(record: dict, path) -> dict:
    out = copy.deepcopy(record)
    node = out
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return out


def _pack(record: dict):
    return build_evidence_pack(parse_dispute(record), generated_at="2026-10-01T00:00:00+00:00")


def _numeric_leaves(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _numeric_leaves(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _numeric_leaves(value, path + (index,))
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield path


def _unreadable(node, path=()):
    """Every path holding a float that is not finite, or an int too large for a float."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _unreadable(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _unreadable(value, path + (index,))
    elif isinstance(node, float) and not math.isfinite(node):
        yield path
    elif isinstance(node, int) and not isinstance(node, bool) and abs(node) > 10 ** 300:
        yield path


_ADVOCATE = {
    "claim_summary": "stand-in", "evidence_cited": [], "policy_rule_ids": [],
    "argument": "stand-in", "requested_outcome": "refund", "requested_amount_sgd": 1.0,
    "follow_up_slots": [],
}


def _judge(amount, action="refund", rules=("RD-5",), refs=("fare.charged_sgd",)):
    return {
        "action": action, "recommended_amount_sgd": amount, "confidence": 0.9,
        "explanation": "stand-in", "cited_rule_ids": list(rules),
        "cited_evidence_refs": list(refs),
    }


def _run(record, llm):
    with tempfile.TemporaryDirectory() as tmp:
        events = EventLog(Path(tmp) / "run", "s20b")
        case = run_dispute(
            dispute=parse_dispute(record), llm=llm, policy=load_policy(POLICY), events=events,
            confidence_threshold=0.65, autonomous_cap_sgd=50.0,
        ).to_dict()
        withheld = [e for e in events.events() if e.type == "judge.ruling_withheld"]
        gates = events.read_payload(withheld[0])["gates_failed"] if withheld else []
        summary = withheld[0].summary if withheld else None
        return case, gates, summary


def _scripted(amount):
    return ScriptedLLM({"rider_advocate": _ADVOCATE, "driver_advocate": _ADVOCATE,
                        "judge": _judge(amount)})


# ------------------------------------------------------------- evidence layer


class HugeIntegersAreUnreadable(unittest.TestCase):
    """An integer too large for a float is unreadable, exactly like NaN."""

    def setUp(self):
        self.rd = _record(SYNTH / "RD-0106.json")
        self.ns = _record(SYNTH / "NS-0205.json")

    def test_a_huge_rate_voids_the_recomputed_fare(self):
        # The review's MAJOR: dropping the rate and computing from the rest gave 9.20
        # recomputed and a 9.96 "overcharge" that RD-5 then enforced.
        for rate in RATES:
            for value in (HUGE, -HUGE):
                with self.subTest(rate=rate, value=value > 0):
                    pack = _pack(_set(self.rd, ("trip", "fare", "rates", rate), value))
                    fare = pack.fare
                    self.assertIsNone(fare.recomputed_sgd)
                    self.assertIsNone(fare.difference_sgd)
                    self.assertIsNone(fare.deviation_fare_delta_sgd)
                    self.assertNotIn(rate, fare.rates)
                    named = [n for n in pack.notes if rate in n and "not a finite number" in n]
                    self.assertEqual(1, len(named), pack.notes)

    def test_a_huge_component_voids_the_sum(self):
        for component in ("base_sgd", "distance_sgd", "time_sgd"):
            with self.subTest(component=component):
                pack = _pack(_set(self.rd, ("trip", "fare", "breakdown", component), HUGE))
                self.assertIsNone(pack.fare.component_sum_sgd)
                self.assertIsNone(pack.fare.breakdown_consistent)
                named = [n for n in pack.notes if component in n and "not a finite number" in n]
                self.assertEqual(1, len(named), pack.notes)

    def test_huge_profile_counts_are_missing_not_a_crash(self):
        # Round one fixed NaN here; a huge int still raised OverflowError in the rates.
        for key in ("disputes_total", "disputes_upheld", "trips_completed", "fraud_flags",
                    "account_age_days"):
            for value in (HUGE, -HUGE):
                with self.subTest(key=key, value=value > 0):
                    pack = _pack(_set(self.ns, ("profiles", "rider", key), value))
                    self.assertIsNone(getattr(pack.profiles.rider, key))

    def test_a_huge_case_policy_term_is_left_out(self):
        record = _record(ORGANISER / "DISP-002.json")
        key = sorted(k for k, v in record["cancellation_policy"].items()
                     if isinstance(v, (int, float)) and not isinstance(v, bool))[0]
        pack = _pack(_set(record, ("cancellation_policy", key), HUGE))
        self.assertNotIn(key, pack.cancellation.case_policy)

    def test_a_huge_fee_is_missing(self):
        both = _set(_set(self.ns, ("cancellation", "cancellation_fee_sgd"), HUGE),
                    ("trip", "fare", "breakdown", "cancellation_sgd"), HUGE)
        self.assertIsNone(_pack(both).cancellation.cancellation_fee_sgd)

    def test_a_huge_claimed_amount_reads_as_not_stated(self):
        record = _set(self.ns, ("claim", "amount_sgd"), HUGE)
        self.assertEqual(0.0, parse_dispute(record).claim_amount_sgd)


class UnreadableInputsAreListed(unittest.TestCase):
    """fare.unreadable_inputs names the fare-formula inputs the record states but cannot read."""

    def setUp(self):
        self.rd = _record(SYNTH / "RD-0106.json")

    def test_a_clean_pack_lists_nothing(self):
        self.assertEqual([], _pack(self.rd).fare.unreadable_inputs)

    def test_each_unreadable_rate_is_listed(self):
        for rate in RATES:
            for value in UNREADABLE:
                with self.subTest(rate=rate, value=repr(value)[:6]):
                    pack = _pack(_set(self.rd, ("trip", "fare", "rates", rate), value))
                    self.assertEqual(["rates.%s" % rate], pack.fare.unreadable_inputs)

    def test_several_are_listed_sorted(self):
        record = _set(_set(self.rd, ("trip", "fare", "rates", "surge_multiplier"), HUGE),
                      ("trip", "fare", "rates", "base_sgd"), float("nan"))
        self.assertEqual(["rates.base_sgd", "rates.surge_multiplier"],
                         _pack(record).fare.unreadable_inputs)

    def test_an_unreadable_promo_is_listed(self):
        record = _set(self.rd, ("trip", "fare", "breakdown", "promo_sgd"), HUGE)
        pack = _pack(record)
        self.assertEqual(["breakdown.promo_sgd"], pack.fare.unreadable_inputs)
        self.assertIsNone(pack.fare.recomputed_sgd)

    def test_another_unreadable_component_is_not_a_fare_input(self):
        # A non-promo component feeds only the breakdown sum, never the formula.
        record = _set(self.rd, ("trip", "fare", "breakdown", "distance_sgd"), HUGE)
        pack = _pack(record)
        self.assertEqual([], pack.fare.unreadable_inputs)
        self.assertEqual(15.76, pack.fare.recomputed_sgd)

    def test_missing_rates_are_not_unreadable(self):
        pack = _pack(_delete(self.rd, ("trip", "fare", "rates")))
        self.assertEqual([], pack.fare.unreadable_inputs)
        self.assertIsNone(pack.fare.recomputed_sgd)

    def test_it_is_not_citable(self):
        # A list of record defects is provenance, not evidence a ruling can rest on.
        record = _set(self.rd, ("trip", "fare", "rates", "per_km_sgd"), HUGE)
        refs = _pack(record).field_refs()
        self.assertFalse([r for r in refs if "unreadable_inputs" in r], refs)

    def test_the_schema_version_moved(self):
        from app.evidence.schema import EVIDENCE_SCHEMA_VERSION

        self.assertEqual("1.4", EVIDENCE_SCHEMA_VERSION)


class ComputedOverflowReadsAsMissing(unittest.TestCase):
    """The layer's own arithmetic can overflow from finite inputs; the result is not a figure."""

    def test_round_up_overflow_is_missing(self):
        from app.evidence.compute import _round_up

        self.assertIsNone(_round_up(1e308, 1))
        self.assertEqual(1.3, _round_up(1.234, 1))

    def setUp(self):
        record = _record(SYNTH / "RD-0106.json")
        record = _delete(record, ("trip", "actual_route"))
        self.record = record

    def test_a_deviation_that_overflows_is_missing(self):
        record = _set(_set(self.record, ("trip", "actual_distance_km"), 1e308),
                      ("trip", "estimated_distance_km"), 1e-300)
        pack = _pack(record)
        self.assertIsNone(pack.route.deviation_pct)
        self.assertNotIn("Infinity", json.dumps(pack.to_dict()))

    def test_a_fare_that_overflows_is_missing(self):
        record = _set(self.record, ("trip", "fare", "rates", "per_km_sgd"), 1e308)
        record = _set(record, ("trip", "actual_distance_km"), 1e10)
        pack = _pack(record)
        self.assertIsNone(pack.fare.recomputed_sgd)
        self.assertIsNone(pack.fare.difference_sgd)
        self.assertEqual([], list(_unreadable(pack.to_dict())))

    def test_a_component_sum_that_overflows_is_missing(self):
        record = _set(_set(self.record, ("trip", "fare", "breakdown", "base_sgd"), 1.7e308),
                      ("trip", "fare", "breakdown", "distance_sgd"), 1.7e308)
        pack = _pack(record)
        self.assertIsNone(pack.fare.component_sum_sgd)
        self.assertIsNone(pack.fare.breakdown_consistent)

    def test_finite_figures_still_round(self):
        # Positive control: the guard must not void ordinary figures.
        fare = _pack(_record(SYNTH / "RD-0106.json")).fare
        self.assertEqual((19.16, 15.76, 3.4), (fare.charged_sgd, fare.recomputed_sgd,
                                               fare.difference_sgd))


class ParsedRecordCarriesNoUnreadableNumber(unittest.TestCase):
    """Intake answers and party identifiers are blanked at parse time."""

    def setUp(self):
        self.rd = _record(SYNTH / "RD-0103.json")

    def test_an_unreadable_intake_answer_becomes_none(self):
        key = sorted(self.rd["intake"])[0]
        for value in UNREADABLE:
            with self.subTest(value=repr(value)[:6]):
                dispute = parse_dispute(_set(self.rd, ("intake", key), value))
                self.assertIsNone(dispute.intake[key])
                # The other answers survive untouched, in order.
                self.assertEqual(list(self.rd["intake"]), list(dispute.intake))
                for other in self.rd["intake"]:
                    if other != key:
                        self.assertEqual(self.rd["intake"][other], dispute.intake[other])

    def test_a_nested_unreadable_intake_value_becomes_none(self):
        record = _set(self.rd, ("intake", "nested_probe"), {"a": [1, HUGE, float("nan")]})
        self.assertEqual({"a": [1, None, None]}, parse_dispute(record).intake["nested_probe"])

    def test_finite_intake_numbers_survive(self):
        record = _set(self.rd, ("intake", "number_probe"), 12.5)
        self.assertEqual(12.5, parse_dispute(record).intake["number_probe"])

    def test_an_unreadable_party_id_becomes_none(self):
        ns = _record(SYNTH / "NS-0205.json")
        for value in UNREADABLE:
            with self.subTest(value=repr(value)[:6]):
                dispute = parse_dispute(_set(ns, ("profiles", "rider", "party_id"), value))
                self.assertIsNone(dispute.profiles["rider"]["party_id"])
                self.assertEqual(ns["profiles"]["driver"]["party_id"],
                                 dispute.profiles["driver"]["party_id"])

    def test_an_unreadable_profile_id_alias_becomes_none(self):
        ns = _record(SYNTH / "NS-0205.json")
        record = _delete(ns, ("profiles", "rider", "party_id"))
        record = _set(record, ("profiles", "rider", "id"), HUGE)
        dispute = parse_dispute(record)
        self.assertIsNone(dispute.profiles["rider"]["id"])

    def test_an_unreadable_organiser_rider_id_becomes_none(self):
        org = _record(ORGANISER / "NS-0205.json")
        dispute = parse_dispute(_set(org, ("rider_profile", "rider_id"), float("nan")))
        self.assertIsNone(_pack_from(dispute).profiles.rider.party_id)

    def test_the_raw_record_is_left_as_filed(self):
        # `raw` keeps the record exactly as it arrived; only the parsed fields are cleaned.
        key = sorted(self.rd["intake"])[0]
        record = _set(self.rd, ("intake", key), HUGE)
        self.assertEqual(HUGE, parse_dispute(record).raw["intake"][key])


def _pack_from(dispute):
    return build_evidence_pack(dispute, generated_at="2026-10-01T00:00:00+00:00")


# --------------------------------------------------------------- judge gate


class UnreadableFareInputHeldByEsc2(unittest.TestCase):
    """The ruled ESC-2 clause: a stated fare input the record cannot read goes to a human."""

    def setUp(self):
        self.rd = _record(SYNTH / "RD-0106.json")

    def test_the_review_repro_is_held(self):
        # A refund of SGD 9.96 reached the party on round one.
        for value in UNREADABLE:
            with self.subTest(value=repr(value)[:6]):
                record = _set(self.rd, ("trip", "fare", "rates", "per_km_sgd"), value)
                case, gates, summary = _run(record, _scripted(9.96))
                resolution = case["resolution"]
                self.assertEqual("withheld", resolution["outcome"])
                self.assertIsNone(resolution["ruling"])
                self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])
                self.assertEqual(["ESC-2"], gates)
                self.assertEqual(
                    "Judge withheld the ruling: the fare inputs in the record could not be "
                    "read (ESC-2)", summary)

    def test_the_mock_short_refund_is_held_too(self):
        record = _set(self.rd, ("trip", "fare", "rates", "per_km_sgd"), float("nan"))
        case, gates, _summary = _run(record, MockLLMClient())
        self.assertEqual("withheld", case["resolution"]["outcome"])
        self.assertEqual(["ESC-2"], gates)

    def test_an_unreadable_promo_is_held(self):
        record = _set(self.rd, ("trip", "fare", "breakdown", "promo_sgd"), HUGE)
        _case, gates, _summary = _run(record, _scripted(3.40))
        self.assertEqual(["ESC-2"], gates)

    def test_the_note_names_the_input_and_ev1(self):
        record = _set(self.rd, ("trip", "fare", "rates", "per_km_sgd"), HUGE)
        case, _gates, _summary = _run(record, _scripted(9.96))
        notes = [n for n in case["resolution"]["notes"] if "ESC-2" in n]
        self.assertEqual(1, len(notes), case["resolution"]["notes"])
        self.assertIn("fare.rates.per_km_sgd", notes[0])
        self.assertIn("EV-1", notes[0])
        self.assertNotIn("route.deviation_pct", notes[0])
        self.assertNotIn("fare.charged_sgd", notes[0])

    def test_one_entry_with_the_charge_also_missing(self):
        record = _set(_set(self.rd, ("trip", "fare", "rates", "per_km_sgd"), HUGE),
                      ("trip", "fare", "charged_sgd"), float("nan"))
        case, gates, summary = _run(record, _scripted(9.96))
        self.assertEqual(["ESC-2"], gates)
        self.assertEqual(1, summary.count("(ESC-2)"))
        self.assertIn("the fare charged could not be established", summary)
        self.assertIn("the fare inputs in the record could not be read", summary)
        notes = [n for n in case["resolution"]["notes"] if "ESC-2" in n]
        self.assertEqual(1, len(notes))
        self.assertIn("fare.charged_sgd", notes[0])
        self.assertIn("fare.rates.per_km_sgd", notes[0])

    def test_a_record_with_no_rates_is_not_this_clause(self):
        # The operator's RD-3 ruling: an absent input stays with the model.
        record = _delete(self.rd, ("trip", "fare", "rates"))
        case, gates, _summary = _run(record, _scripted(3.40))
        self.assertEqual("ruled", case["resolution"]["outcome"])
        self.assertEqual([], gates)

    def test_an_unreadable_non_promo_component_is_not_this_clause(self):
        record = _set(self.rd, ("trip", "fare", "breakdown", "distance_sgd"), HUGE)
        case, gates, _summary = _run(record, _scripted(3.40))
        self.assertEqual("ruled", case["resolution"]["outcome"])
        self.assertEqual([], gates)

    def test_no_show_cases_are_not_gated_on_fare_inputs(self):
        ns = _record(SYNTH / "NS-0201.json")
        self.assertIn("fare", ns["trip"])
        pack = _pack(ns)
        grafted = dataclasses.replace(
            pack, fare=dataclasses.replace(pack.fare, unreadable_inputs=["rates.per_km_sgd"]))
        from app.agents.judge import Judge
        from app.schemas import AdvocateCase

        def advocate(party):
            return AdvocateCase(party=party, agent="%s_advocate" % party, claim_summary="s",
                                argument="s", requested_outcome="no action",
                                requested_amount_sgd=0.0)

        for dispute_path, expect_gate in ((SYNTH / "NS-0201.json", False),
                                          (SYNTH / "RD-0106.json", True)):
            with self.subTest(dispute=dispute_path.name):
                with tempfile.TemporaryDirectory() as tmp:
                    events = EventLog(Path(tmp) / "run", "s20b")
                    judge = Judge(llm=ScriptedLLM({"judge": _judge(
                        0.0, action="no action", rules=("NS-1",),
                        refs=("cancellation.driver_wait_minutes",))}),
                        events=events, policy=load_policy(POLICY))
                    pack_for = grafted if not expect_gate else dataclasses.replace(
                        _pack(self.rd), fare=dataclasses.replace(
                            _pack(self.rd).fare, unreadable_inputs=["rates.per_km_sgd"]))
                    judge.run(parse_dispute(_record(dispute_path)), pack_for, advocate("rider"),
                              advocate("driver"), confidence_threshold=0.65,
                              autonomous_cap_sgd=50.0)
                    withheld = [e for e in events.events() if e.type == "judge.ruling_withheld"]
                    gates = events.read_payload(withheld[0])["gates_failed"] if withheld else []
                    self.assertEqual(expect_gate, "ESC-2" in gates, gates)


class HugeModelAmountIsAContractFailure(unittest.TestCase):
    def test_a_huge_amount_is_a_model_failure_not_a_crash(self):
        record = _record(SYNTH / "NS-0205.json")
        case, _gates, _summary = _run(record, _scripted(HUGE))
        resolution = case["resolution"]
        self.assertEqual("withheld", resolution["outcome"])
        self.assertIsNone(resolution["ruling"])
        failure = resolution["model_failure"]
        self.assertEqual("judge", failure["agent"])
        self.assertIn("finite number", failure["message"])


# ---------------------------------------------------------------- the class


class NoUnreadableNumberAnywhere(unittest.TestCase):
    def test_every_corpus_leaf_broken_five_ways_builds_a_clean_pack(self):
        records = sorted(SYNTH.glob("*.json")) + sorted(ORGANISER.glob("*.json"))
        self.assertEqual(35, len(records))
        tried = 0
        for path in records:
            record = _record(path)
            for leaf in _numeric_leaves(record):
                for value in UNREADABLE:
                    tried += 1
                    try:
                        pack = _pack(_set(record, leaf, value))
                    except Exception as exc:  # noqa: BLE001 - the crash IS the finding
                        self.fail("%s %s=%r crashed the pack: %r"
                                  % (path.name, leaf, repr(value)[:8], exc))
                    self.assertEqual([], list(_unreadable(pack.to_dict())),
                                     "%s %s" % (path.name, leaf))
        self.assertGreater(tried, 7000)

    def test_no_case_file_carries_an_unreadable_number(self):
        for path in (SYNTH / "RD-0106.json", SYNTH / "RD-0103.json", ORGANISER / "DISP-002.json",
                     SYNTH / "NS-0205.json"):
            record = _record(path)
            for leaf in _numeric_leaves(record):
                with self.subTest(record=path.name, leaf=leaf):
                    try:
                        case, _gates, _summary = _run(_set(record, leaf, HUGE), MockLLMClient())
                    except Exception as exc:  # noqa: BLE001
                        self.fail("%s %s crashed the pipeline: %r" % (path.name, leaf, exc))
                    # The filed record is kept verbatim only in the filing event; every
                    # section that is parsed or computed (intake, pack, claims, resolution)
                    # must be clean.
                    self.assertIn("intake", case)
                    computed = dict(case)
                    computed["events"] = [e for e in case["events"]
                                          if e.get("type") != "dispute.filed"]
                    self.assertEqual([], list(_unreadable(computed)))


# ---------------------------------------------------------------------- docs


class DocsNameTheRoundTwoRule(unittest.TestCase):
    def test_policy_esc2_names_unreadable_inputs(self):
        text = POLICY.read_text(encoding="utf-8")
        section = text.split("### ESC-2", 1)[1].split("\n### ", 1)[0]
        self.assertIn("fare.unreadable_inputs", section)
        self.assertRegex(section, r"(?i)integer\s+too\s+large")

    def test_architecture_esc2_row_names_unreadable_inputs(self):
        text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        section = text.split("## Gates enforced in code", 1)[1].split("\n## ", 1)[0]
        row = [l for l in section.splitlines() if l.startswith("| ") and "ESC-2" in l.split("|")[1]]
        self.assertEqual(1, len(row))
        self.assertIn("fare.unreadable_inputs", row[0])

    def test_architecture_evidence_row_names_huge_integers(self):
        text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        row = [l for l in text.splitlines() if l.startswith("| Evidence layer |")]
        self.assertEqual(1, len(row))
        self.assertRegex(row[0], r"(?i)integer too large")
        self.assertRegex(row[0], r"(?i)overflow")


if __name__ == "__main__":
    unittest.main()
