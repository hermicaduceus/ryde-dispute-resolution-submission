"""Session twenty acceptance target (W22 review fix): a figure the record cannot prove goes to a human.

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/build-briefs/session-twenty-brief.md. Ruled by the operator on 2026-10-01 (night) as ONE class:

1. The evidence layer reads a non-finite number (NaN, Infinity, -Infinity: json.loads
   accepts all three) as MISSING, never as a figure, and never crashes on one.
   - A broken tariff rate, or a broken promo component, voids the recomputed fare: the
     formula with that input dropped would be a plausible wrong number.
   - A broken breakdown component voids the component sum, so breakdown_consistent is
     unknown (None), not False: False reads as evidence of an overcharge (EV-3).
   - A broken case-policy term is left out of the case's stated terms.
   - A broken claimed amount reads as "not stated" (0.0), like any other non-number.
2. The Judge's gates refuse a non-finite figure: NS-6 never calls a broken fee eligible,
   RD-5 holds a ruling whose overcharge figure is present but not finite, and ESC-2 reads
   a non-finite deviation as unmeasured.
3. EV-1: a route case whose fare charged is not a recorded figure (missing, or no fare
   block at all) is held under ESC-2, the same gate as an unmeasured deviation.

Every gate withholds; none rewrites the Judge's candidate.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import tempfile
import unittest
from pathlib import Path

from app.dispute import load_dispute, parse_dispute
from app.events import EventLog
from app.evidence import build_evidence_pack
from app.llm.mock import MockLLMClient
from app.pipeline import run_dispute
from app.policy import load_policy
from app.schemas import OUTCOME_RULED, OUTCOME_WITHHELD, UNDER_REVIEW_MESSAGE, AdvocateCase

from tests.support import ScriptedLLM

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "data" / "packs"
SYNTH = PACKS / "ryde-synth-v1" / "disputes"
ORGANISER = PACKS / "organiser-style-v1" / "disputes"
POLICY = REPO / "docs" / "policy.md"

BROKEN = (float("nan"), float("inf"), float("-inf"))


def _judge_module():
    import app.agents.judge as judge  # lazy, so each test is RED on its own

    return judge


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


def _non_finite(node, path=()):
    """Every path in a plain-data tree holding a float that is not finite."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _non_finite(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _non_finite(value, path + (index,))
    elif isinstance(node, float) and not math.isfinite(node):
        yield path


def _advocate(party: str) -> AdvocateCase:
    return AdvocateCase(
        party=party,
        agent="%s_advocate" % party,
        claim_summary="stand-in",
        argument="stand-in",
        requested_outcome="no action",
        requested_amount_sgd=0.0,
    )


def _ruling(action, amount, confidence=0.9, rules=("RD-3",), refs=("fare.difference_sgd",)):
    return {
        "action": action,
        "recommended_amount_sgd": amount,
        "confidence": confidence,
        "explanation": "stand-in",
        "cited_rule_ids": list(rules),
        "cited_evidence_refs": list(refs),
    }


def _replace(pack, block, **changes):
    return dataclasses.replace(pack, **{block: dataclasses.replace(getattr(pack, block), **changes)})


# ------------------------------------------------------------- evidence layer


class NonFiniteFiguresReadAsMissing(unittest.TestCase):
    """The evidence layer: a non-finite number in a record is not a recorded figure."""

    def setUp(self):
        self.rd = _record(ORGANISER / "RD-0106.json")
        self.ns = _record(SYNTH / "NS-0205.json")

    def test_the_finite_pack_is_unchanged(self):
        # Positive control: the corpus figures these tests corrupt are real on HEAD.
        fare = _pack(self.rd).fare
        # The breakdown sums to the recomputed 15.76, not the 19.16 charged: that IS the
        # overcharge, so the consistency flag is a real False here.
        self.assertEqual((19.16, 15.76, 3.4, False),
                         (fare.charged_sgd, fare.recomputed_sgd, fare.difference_sgd,
                          fare.breakdown_consistent))
        self.assertEqual(6.61, _pack(self.ns).cancellation.cancellation_fee_sgd)

    def test_a_broken_charged_fare_is_missing(self):
        for value in BROKEN:
            with self.subTest(value=value):
                fare = _pack(_set(self.rd, ("trip_data", "fare", "charged_sgd"), value)).fare
                self.assertIsNone(fare.charged_sgd)
                self.assertIsNone(fare.difference_sgd)
                self.assertIsNone(fare.difference_pct)
                # Nothing to compare the breakdown against: unknown, not inconsistent.
                self.assertIsNone(fare.breakdown_consistent)
                # The recomputation does not depend on the charge and survives.
                self.assertEqual(15.76, fare.recomputed_sgd)

    def test_a_broken_estimated_distance_is_missing(self):
        for value in BROKEN:
            with self.subTest(value=value):
                pack = _pack(_set(self.rd, ("trip_data", "estimated_distance_km"), value))
                self.assertIsNone(pack.route.estimated_distance_km)
                self.assertIsNone(pack.route.deviation_km)
                self.assertIsNone(pack.route.deviation_pct)

    def test_a_broken_tariff_rate_voids_the_recomputed_fare(self):
        # Dropping the broken rate and computing from the rest is a plausible wrong
        # number: a missing per-km rate reads as free distance, a missing surge as 1.0.
        for rate in ("base_sgd", "per_km_sgd", "per_min_sgd", "surge_multiplier"):
            for value in BROKEN:
                with self.subTest(rate=rate, value=value):
                    pack = _pack(_set(self.rd, ("trip_data", "fare", "rates", rate), value))
                    fare = pack.fare
                    self.assertIsNone(fare.recomputed_sgd)
                    self.assertIsNone(fare.recomputed_estimated_route_sgd)
                    self.assertIsNone(fare.deviation_fare_delta_sgd)
                    self.assertIsNone(fare.difference_sgd)
                    self.assertNotIn(rate, fare.rates)
                    self.assertEqual(19.16, fare.charged_sgd)
                    named = [n for n in pack.notes if rate in n and "not a finite number" in n]
                    self.assertEqual(1, len(named), pack.notes)
                    # The trip numbers were there; saying otherwise misstates the record.
                    self.assertFalse([n for n in pack.notes if "trip numbers" in n], pack.notes)
                    self.assertFalse([n for n in pack.notes if "no tariff rates" in n], pack.notes)

    def test_every_rate_broken_is_not_reported_as_no_rates(self):
        record = self.rd
        for rate in ("base_sgd", "per_km_sgd", "per_min_sgd", "surge_multiplier"):
            record = _set(record, ("trip_data", "fare", "rates", rate), float("nan"))
        pack = _pack(record)
        self.assertEqual({}, pack.fare.rates)
        self.assertIsNone(pack.fare.recomputed_sgd)
        self.assertFalse([n for n in pack.notes if "no tariff rates" in n], pack.notes)
        named = [n for n in pack.notes if "not a finite number" in n and "tariff rate" in n]
        self.assertEqual(1, len(named), pack.notes)
        for rate in ("base_sgd", "per_km_sgd", "per_min_sgd", "surge_multiplier"):
            self.assertIn(rate, named[0])

    def test_a_broken_breakdown_component_voids_the_sum(self):
        for component in ("base_sgd", "distance_sgd", "time_sgd"):
            for value in BROKEN:
                with self.subTest(component=component, value=value):
                    path = ("trip_data", "fare", "breakdown", component)
                    pack = _pack(_set(self.rd, path, value))
                    fare = pack.fare
                    self.assertIsNone(fare.component_sum_sgd)
                    # Unknown, not False: False is EV-3 evidence of an incorrect charge.
                    self.assertIsNone(fare.breakdown_consistent)
                    self.assertNotIn(component, fare.components_sgd)
                    # A non-promo component is not a fare-formula input.
                    self.assertEqual(15.76, fare.recomputed_sgd)
                    named = [n for n in pack.notes
                             if component in n and "not a finite number" in n]
                    self.assertEqual(1, len(named), pack.notes)

    def test_a_broken_promo_component_also_voids_the_recomputed_fare(self):
        # The promo is subtracted inside the fare formula, so it is an input there too.
        for value in BROKEN:
            with self.subTest(value=value):
                fare = _pack(_set(self.rd, ("trip_data", "fare", "breakdown", "promo_sgd"), value)).fare
                self.assertIsNone(fare.recomputed_sgd)
                self.assertIsNone(fare.difference_sgd)
                self.assertIsNone(fare.component_sum_sgd)
                self.assertIsNone(fare.breakdown_consistent)

    def test_a_missing_rate_block_keeps_its_own_note(self):
        # The broken-rate note must not replace the existing no-rates note.
        pack = _pack(_delete(self.rd, ("trip_data", "fare", "rates")))
        self.assertIn("no tariff rates in the record, so the fare could not be recomputed", pack.notes)
        self.assertFalse([n for n in pack.notes if "not a finite number" in n])

    def test_a_broken_fee_reads_as_missing(self):
        # Missing, exactly: the existing fallback to the fare breakdown's fee applies,
        # and when that is broken too, there is no fee.
        breakdown_fee = ("trip", "fare", "breakdown", "cancellation_sgd")
        self.assertEqual(6.61, self.ns["trip"]["fare"]["breakdown"]["cancellation_sgd"])
        for value in BROKEN:
            with self.subTest(value=value):
                stated = _set(self.ns, ("cancellation", "cancellation_fee_sgd"), value)
                self.assertEqual(6.61, _pack(stated).cancellation.cancellation_fee_sgd)
                missing = _delete(self.ns, ("cancellation", "cancellation_fee_sgd"))
                self.assertEqual(6.61, _pack(missing).cancellation.cancellation_fee_sgd)
                both = _set(stated, breakdown_fee, value)
                self.assertIsNone(_pack(both).cancellation.cancellation_fee_sgd)
                only_breakdown = _set(missing, breakdown_fee, value)
                self.assertIsNone(_pack(only_breakdown).cancellation.cancellation_fee_sgd)

    def test_broken_profile_counts_are_missing_not_a_crash(self):
        # Review MAJOR 2: int(NaN) raised ValueError and int(inf) OverflowError, so one
        # broken count killed the whole evidence pack.
        for key in ("fraud_flags", "disputes_total", "disputes_upheld", "trips_completed",
                    "account_age_days"):
            for value in BROKEN:
                with self.subTest(key=key, value=value):
                    pack = _pack(_set(self.ns, ("profiles", "rider", key), value))
                    self.assertIsNone(getattr(pack.profiles.rider, key))

    def test_a_broken_rating_is_missing(self):
        for value in BROKEN:
            with self.subTest(value=value):
                pack = _pack(_set(self.ns, ("profiles", "rider", "rating"), value))
                self.assertIsNone(pack.profiles.rider.rating)

    def test_a_broken_case_policy_term_is_left_out(self):
        record = _record(ORGANISER / "DISP-002.json")
        terms = record["cancellation_policy"]
        broken_key = sorted(k for k, v in terms.items()
                            if isinstance(v, (int, float)) and not isinstance(v, bool))[0]
        for value in BROKEN:
            with self.subTest(value=value):
                pack = _pack(_set(record, ("cancellation_policy", broken_key), value))
                stated = pack.cancellation.case_policy
                self.assertNotIn(broken_key, stated)
                # The other terms survive.
                self.assertEqual(len(terms) - 1, len(stated))
                named = [n for n in pack.notes if broken_key in n and "not a finite number" in n]
                self.assertEqual(1, len(named), pack.notes)

    def test_a_broken_claimed_amount_reads_as_not_stated(self):
        for value in BROKEN:
            with self.subTest(value=value):
                record = _set(self.ns, ("claim", "amount_sgd"), value)
                self.assertEqual(0.0, parse_dispute(record).claim_amount_sgd)

    def test_no_pack_ever_carries_a_non_finite_figure(self):
        # The class, not the case: every numeric field of every corpus record, broken
        # one at a time three ways, builds a pack holding only finite numbers.
        records = sorted(SYNTH.glob("*.json")) + sorted(ORGANISER.glob("*.json"))
        self.assertEqual(35, len(records))
        tried = 0
        for path in records:
            record = _record(path)
            for leaf in _numeric_leaves(record):
                for value in BROKEN:
                    tried += 1
                    try:
                        pack = _pack(_set(record, leaf, value))
                    except Exception as exc:  # noqa: BLE001 - the crash IS the finding
                        self.fail("%s %s=%r crashed the pack: %r" % (path.name, leaf, value, exc))
                    leaks = list(_non_finite(pack.to_dict()))
                    self.assertEqual([], leaks, "%s %s=%r" % (path.name, leaf, value))
        self.assertGreater(tried, 3000)


# --------------------------------------------------------------- judge gates


class _JudgeHarness(unittest.TestCase):
    record = ORGANISER / "RD-0106.json"

    def setUp(self):
        self.dispute = load_dispute(self.record)
        self.pack = build_evidence_pack(self.dispute)
        self.policy = load_policy(POLICY)

    def judge(self, ruling, pack=None):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        events = EventLog(tmp / "run", "s20-gate")
        judge = _judge_module().Judge(llm=ScriptedLLM({"judge": ruling}), events=events,
                                      policy=self.policy)
        resolution = judge.run(
            self.dispute,
            pack if pack is not None else self.pack,
            _advocate("rider"),
            _advocate("driver"),
            confidence_threshold=0.65,
            autonomous_cap_sgd=50.0,
        )
        withheld = [e for e in events.events() if e.type == "judge.ruling_withheld"]
        self.assertLessEqual(len(withheld), 1)
        if withheld:
            return resolution, events.read_payload(withheld[0])["gates_failed"], withheld[0].summary
        return resolution, [], None

    def assertRuled(self, resolution, gates, summary):
        self.assertEqual(OUTCOME_RULED, resolution.outcome, gates)
        self.assertEqual([], gates)

    def assertWithheldBy(self, result, expected_gates, candidate_amount):
        resolution, gates, summary = result
        self.assertEqual(OUTCOME_WITHHELD, resolution.outcome)
        self.assertEqual(expected_gates, gates)
        self.assertIsNone(resolution.ruling)
        self.assertEqual(UNDER_REVIEW_MESSAGE, resolution.party_message)
        self.assertTrue(resolution.escalated_for_human_review)
        self.assertEqual(candidate_amount, resolution.withheld_candidate.recommended_amount_sgd)
        # The operator strip names the gate and carries no figure.
        for gate in expected_gates:
            self.assertIn("(%s)" % gate, summary)
        self.assertNotIn("SGD", summary)
        self.assertNotRegex(summary, r"\d\.\d")
        return summary


class ChargedFareIsDecisiveForRouteCases(_JudgeHarness):
    """EV-1: a route ruling needs a recorded fare charged, or ESC-2 holds it."""

    FULL = ("refund", 3.40)  # covers RD-5 on this pack, so only ESC-2 can fire

    def test_positive_control_the_full_refund_is_ruled(self):
        self.assertRuled(*self.judge(_ruling(*self.FULL)))

    def test_a_missing_charged_fare_is_held_by_esc2(self):
        pack = _replace(self.pack, "fare", charged_sgd=None)
        summary = self.assertWithheldBy(self.judge(_ruling(*self.FULL), pack=pack), ["ESC-2"], 3.40)
        self.assertIn("fare charged could not be established", summary)
        self.assertNotIn("deviation", summary)

    def test_a_non_finite_charged_fare_is_held_by_esc2(self):
        for value in BROKEN:
            with self.subTest(value=value):
                pack = _replace(self.pack, "fare", charged_sgd=value)
                self.assertWithheldBy(self.judge(_ruling(*self.FULL), pack=pack), ["ESC-2"], 3.40)

    def test_a_missing_fare_block_is_held_by_esc2(self):
        pack = dataclasses.replace(self.pack, fare=None)
        self.assertWithheldBy(self.judge(_ruling("no action", 0.0)), ["RD-5"], 0.0)
        self.assertWithheldBy(self.judge(_ruling("no action", 0.0), pack=pack), ["ESC-2"], 0.0)

    def test_a_non_finite_deviation_is_unmeasured(self):
        for value in BROKEN:
            with self.subTest(value=value):
                pack = _replace(self.pack, "route", deviation_pct=value)
                summary = self.assertWithheldBy(
                    self.judge(_ruling(*self.FULL), pack=pack), ["ESC-2"], 3.40)
                self.assertIn("the route deviation could not be measured", summary)

    def test_the_unmeasured_deviation_wording_is_unchanged(self):
        pack = _replace(self.pack, "route", deviation_pct=None)
        summary = self.assertWithheldBy(self.judge(_ruling(*self.FULL), pack=pack), ["ESC-2"], 3.40)
        self.assertEqual(
            "Judge withheld the ruling: the route deviation could not be measured (ESC-2)", summary)

    def test_both_missing_is_one_esc2_entry_naming_both(self):
        pack = _replace(_replace(self.pack, "route", deviation_pct=None), "fare", charged_sgd=None)
        resolution, gates, summary = self.judge(_ruling(*self.FULL), pack=pack)
        self.assertEqual(["ESC-2"], gates)
        self.assertEqual(1, summary.count("(ESC-2)"))
        self.assertIn("the route deviation could not be measured", summary)
        self.assertIn("fare charged could not be established", summary)
        esc2_notes = [n for n in resolution.notes if "ESC-2" in n]
        self.assertEqual(1, len(esc2_notes), resolution.notes)
        self.assertIn("route.deviation_pct", esc2_notes[0])
        self.assertIn("fare.charged_sgd", esc2_notes[0])

    def test_the_note_names_the_charged_field_and_ev1(self):
        pack = _replace(self.pack, "fare", charged_sgd=None)
        resolution, _gates, _summary = self.judge(_ruling(*self.FULL), pack=pack)
        esc2_notes = [n for n in resolution.notes if "ESC-2" in n]
        self.assertEqual(1, len(esc2_notes), resolution.notes)
        self.assertIn("fare.charged_sgd", esc2_notes[0])
        self.assertIn("EV-1", esc2_notes[0])
        self.assertNotIn("route.deviation_pct", esc2_notes[0])

    def test_no_show_cases_are_not_gated_on_the_charged_fare(self):
        # A no-show judged against a pack with no recorded charge: the clause is EV-1's,
        # and EV-1 governs fare findings on route cases only.
        self.dispute = load_dispute(SYNTH / "NS-0201.json")
        ns_pack = build_evidence_pack(self.dispute)
        self.assertRuled(*self.judge(_ruling("no action", 0.0, rules=("NS-1",),
                                             refs=("cancellation.driver_wait_minutes",))))
        for pack in (_replace(ns_pack, "fare", charged_sgd=None),
                     _replace(ns_pack, "fare", charged_sgd=float("nan")),
                     _replace(ns_pack, "fare", difference_sgd=float("nan")),
                     dataclasses.replace(ns_pack, fare=None)):
            with self.subTest(pack=pack.fare):
                self.assertRuled(*self.judge(
                    _ruling("no action", 0.0, rules=("NS-1",),
                            refs=("cancellation.driver_wait_minutes",)), pack=pack))

    def test_a_route_pack_judged_as_route_fires_the_graft(self):
        # The scope test above is only meaningful if the same missing-charge pack IS
        # gated under the route category: prove the graft is live.
        self.dispute = load_dispute(SYNTH / "NS-0201.json")
        ns_pack = build_evidence_pack(self.dispute)
        self.dispute = load_dispute(self.record)
        grafted = dataclasses.replace(
            self.pack, fare=dataclasses.replace(ns_pack.fare, charged_sgd=None)
        )
        _resolution, gates, _summary = self.judge(_ruling(*self.FULL), pack=grafted)
        self.assertIn("ESC-2", gates)


class ProvenOverchargeRefusesBrokenFigures(_JudgeHarness):
    """RD-5: a difference that is present but not finite cannot prove or disprove anything."""

    def test_a_non_finite_difference_is_held_by_rd5(self):
        for value in BROKEN:
            for ruling in (("refund", 3.40), ("refund", 49.0), ("no action", 0.0)):
                with self.subTest(value=value, ruling=ruling):
                    pack = _replace(self.pack, "fare", difference_sgd=value)
                    summary = self.assertWithheldBy(
                        self.judge(_ruling(*ruling), pack=pack), ["RD-5"], ruling[1])
                    self.assertIn("RD-5", summary)

    def test_a_missing_difference_is_still_not_gated(self):
        # None is "no overcharge figure", which RD-5 does not read (unchanged).
        pack = _replace(self.pack, "fare", difference_sgd=None)
        self.assertRuled(*self.judge(_ruling("no action", 0.0), pack=pack))

    def test_rd5_reason_names_the_field(self):
        pack = _replace(self.pack, "fare", difference_sgd=float("nan"))
        resolution, _gates, _summary = self.judge(_ruling("refund", 3.40), pack=pack)
        rd5 = [n for n in resolution.notes if "RD-5" in n]
        self.assertEqual(1, len(rd5), resolution.notes)
        self.assertIn("fare.difference_sgd", rd5[0])
        self.assertNotIn("nan", rd5[0].lower())


class ContestedNoShowRefusesBrokenFigures(_JudgeHarness):
    """NS-6: a broken fee is never eligible (review MAJOR 1)."""

    record = SYNTH / "NS-0205.json"

    def test_positive_control_eligible(self):
        self.assertTrue(_judge_module().ns6_auto_refund_eligible(self.pack))

    def test_a_non_finite_fee_is_not_eligible(self):
        for value in BROKEN:
            with self.subTest(value=value):
                # Graft the broken fee straight onto the pack: the evidence layer now
                # refuses it, so only a pack built some other way can carry one.
                pack = _replace(self.pack, "cancellation", cancellation_fee_sgd=value)
                self.assertFalse(_judge_module().ns6_auto_refund_eligible(pack))
                self.assertWithheldBy(
                    self.judge(_ruling("refund", 6.61, rules=("NS-6", "GEN-3"),
                                       refs=("cancellation.cancellation_fee_sgd",)), pack=pack),
                    ["NS-6", "NS-8"], 6.61)


# ---------------------------------------------------------------------- docs


class PolicyStatesTheEnforcement(unittest.TestCase):
    """The policy the agents read says what the code enforces (operator-authored text)."""

    def setUp(self):
        self.text = POLICY.read_text(encoding="utf-8")

    def _section(self, heading):
        return self.text.split(heading, 1)[1].split("\n### ", 1)[0]

    def test_esc2_names_the_charged_fare(self):
        section = self._section("### ESC-2")
        self.assertIn("fare.charged_sgd", section)
        self.assertRegex(section, r"(?i)not a finite number")

    def test_ev1_says_a_broken_rate_or_component_is_unknown(self):
        section = self._section("### EV-1")
        self.assertIn("breakdown_consistent", section)
        self.assertRegex(section, r"(?i)tariff rate that is not a finite number")


class DocsNameTheChargedFareClause(unittest.TestCase):
    """The architecture table and the README say what the code now enforces."""

    def _esc2_row(self):
        text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        section = text.split("## Gates enforced in code", 1)[1].split("\n## ", 1)[0]
        rows = [l for l in section.splitlines()
                if l.startswith("| ") and "ESC-2" in l.split("|")[1]]
        self.assertEqual(1, len(rows), "exactly one ESC-2 row")
        return rows[0]

    def test_the_esc2_row_names_both_fields_and_ev1(self):
        row = self._esc2_row()
        for needle in ("`app/agents/judge.py`", "deviation_pct", "fare.charged_sgd", "EV-1"):
            self.assertIn(needle, row, needle)

    def test_the_gate_count_is_unchanged(self):
        # One gate, wider: the clause joins ESC-2, it is not a gate of its own. The count
        # moved to nine on 2026-10-02 for RD-4 (W28) and ten on 2026-10-04 for NS-8,
        # separate gates, not clauses of this one.
        text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        section = text.split("## Gates enforced in code", 1)[1]
        self.assertTrue(section.lstrip().startswith("Ten gates"))

    def test_the_readme_esc2_clause_names_the_charged_fare(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        para = next(p for p in text.split("\n\n") if "Seven gates" in p)  # five until W28, six until W29
        esc2 = para.split("ESC-2", 1)[1].split("NS-6", 1)[0]
        self.assertIn("deviation", esc2)
        self.assertIn("fare charged", esc2)

    def test_the_evidence_layer_rule_is_documented(self):
        text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)not a finite number")


# ---------------------------------------------------------------- end to end


class EndToEnd(unittest.TestCase):
    """The review's own repros, through the real pipeline on the mock."""

    def _run(self, record):
        with tempfile.TemporaryDirectory() as tmp:
            events = EventLog(Path(tmp) / "run", "s20-e2e")
            case = run_dispute(
                dispute=parse_dispute(record),
                llm=MockLLMClient(),
                policy=load_policy(POLICY),
                events=events,
                confidence_threshold=0.65,
                autonomous_cap_sgd=50.0,
            ).to_dict()
            withheld = [e for e in events.events() if e.type == "judge.ruling_withheld"]
            gates = events.read_payload(withheld[0])["gates_failed"] if withheld else []
            return case, gates

    def test_rd0106_with_a_broken_or_missing_charge_is_held_by_esc2(self):
        # Review MAJOR 1 (NaN) and the planning lane's extension (missing): both ruled 0.66.
        for path in (SYNTH / "RD-0106.json", ORGANISER / "RD-0106.json"):
            record = _record(path)
            fare_path = (("trip_data",) if "trip_data" in record else ("trip",)) + ("fare",)
            variants = [("missing", _delete(record, fare_path + ("charged_sgd",)))]
            variants += [(repr(v), _set(record, fare_path + ("charged_sgd",), v)) for v in BROKEN]
            for label, variant in variants:
                with self.subTest(pack=path.parent.parent.name, charged=label):
                    case, gates = self._run(variant)
                    resolution = case["resolution"]
                    self.assertEqual("withheld", resolution["outcome"])
                    self.assertIsNone(resolution["ruling"])
                    self.assertEqual(["ESC-2"], gates)
                    self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])

    def test_nan_from_json_text_is_held(self):
        # json.loads accepts the bare token NaN: the realistic route in.
        text = (ORGANISER / "RD-0106.json").read_text(encoding="utf-8")
        self.assertIn('"charged_sgd": 19.16', text)
        record = json.loads(text.replace('"charged_sgd": 19.16', '"charged_sgd": NaN'))
        case, gates = self._run(record)
        self.assertEqual("withheld", case["resolution"]["outcome"])
        self.assertEqual(["ESC-2"], gates)

    def test_ns0205_with_broken_fraud_flags_is_held_not_crashed(self):
        # Review MAJOR 2: NaN fraud_flags crashed the pack. Unknown is not clean, so NS-6
        # withholds the mock's full refund.
        for path in (SYNTH / "NS-0205.json", ORGANISER / "NS-0205.json"):
            record = _record(path)
            flag_path = (("rider_profile",) if "rider_profile" in record
                         else ("profiles", "rider")) + ("fraud_flags",)
            for value in BROKEN:
                with self.subTest(pack=path.parent.parent.name, value=value):
                    case, gates = self._run(_set(record, flag_path, value))
                    self.assertEqual("withheld", case["resolution"]["outcome"])
                    self.assertEqual(["NS-6"], gates)

    def test_no_case_file_carries_a_non_finite_figure(self):
        # Every numeric field of three representative records, broken one at a time:
        # the case file (pack, prompts' inputs, ruling, events) holds only finite numbers.
        for path in (ORGANISER / "RD-0106.json", ORGANISER / "DISP-002.json",
                     SYNTH / "NS-0205.json"):
            record = _record(path)
            for leaf in _numeric_leaves(record):
                with self.subTest(record=path.name, leaf=leaf):
                    case, _gates = self._run(_set(record, leaf, float("nan")))
                    self.assertEqual([], list(_non_finite(case)))
                    self.assertNotIn("NaN", json.dumps(case, default=str))


if __name__ == "__main__":
    unittest.main()
