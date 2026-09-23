"""The labelled corpus must stay consistent with the policy document.

NON-APP. These tests do not exercise app behaviour; they check that the authored
artifacts in data/ and docs/policy.md agree with each other and with what the Evidence
Pack actually computes. A ground-truth label that the evidence contradicts is worse than
no label at all, because every accuracy number measured against it would be wrong.

They are the guard on a hand-authored artifact: edit data/ or the policy and these fail
if the two drift apart.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from app.dispute import AGENT_CATEGORIES, CATEGORY_OTHER, load_dispute, normalise_category
from app.evidence import build_evidence_pack
from app.policy import load_policy

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data" / "packs" / "ryde-synth-v1"
DISPUTES = DATA / "disputes"
GROUND_TRUTH = DATA / "ground-truth.json"
POLICY = REPO / "docs" / "policy.md"

# From docs/policy.md's parameters table. Duplicated here on purpose: if someone edits a
# threshold in the policy without updating the corpus, these tests should fail loudly
# rather than silently track the change.
MATERIAL_PCT = 20.0
MATERIAL_KM = 1.0
GROSS_KM = 5.0
DE_MINIMIS_SGD = 1.00
AUTONOMOUS_CAP_SGD = 50.00
MIN_WAIT_MINUTES = 3.0
PROXIMITY_LIMIT_M = 500.0

VALID_OUTCOMES = {"ruled", "escalated", "human_review"}
VALID_ACTIONS = {"refund", "compensation", "no action", None}


def _load_corpus():
    labels = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    by_id = {case["dispute_id"]: case for case in labels["cases"]}
    records = {}
    for path in sorted(DISPUTES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        records[data["dispute_id"]] = (path, data)
    return labels, by_id, records


class CorpusStructureTest(unittest.TestCase):
    """The corpus exists, is complete, and every case is labelled exactly once."""

    @classmethod
    def setUpClass(cls):
        cls.labels, cls.by_id, cls.records = _load_corpus()

    def test_the_corpus_and_its_labels_exist(self):
        self.assertTrue(DISPUTES.is_dir(), "data/disputes/ is missing — run tools/build_corpus.py")
        self.assertTrue(GROUND_TRUTH.is_file(), "data/ground-truth.json is missing")
        self.assertGreaterEqual(len(self.records), 10, "the corpus is too small to measure anything")

    def test_every_dispute_has_exactly_one_label(self):
        self.assertEqual(
            set(self.records), set(self.by_id), "dispute files and ground-truth labels disagree"
        )
        self.assertEqual(
            len(self.labels["cases"]), len(self.by_id), "a dispute id is labelled more than once"
        )

    def test_no_label_leaks_into_a_dispute_record(self):
        """The agents must never see the answer. A label inside the input voids the metric."""
        leak_keys = {"expected_outcome", "expected_action", "expected_amount_sgd", "label",
                     "ground_truth", "decisive_rule_ids", "rationale"}
        for dispute_id, (path, data) in self.records.items():
            blob = json.dumps(data)
            for key in leak_keys:
                self.assertNotIn(
                    '"%s"' % key, blob, "%s leaks the ground-truth key %r" % (path.name, key)
                )

    def test_every_record_parses_and_routes(self):
        for dispute_id, (path, _data) in self.records.items():
            dispute = load_dispute(path)
            self.assertIn(dispute.category, set(AGENT_CATEGORIES) | {CATEGORY_OTHER})

    def test_labels_use_the_declared_vocabulary(self):
        for dispute_id, label in self.by_id.items():
            self.assertIn(label["expected_outcome"], VALID_OUTCOMES, dispute_id)
            self.assertIn(label["expected_action"], VALID_ACTIONS, dispute_id)

    def test_a_ruled_case_names_an_action_and_an_amount(self):
        for dispute_id, label in self.by_id.items():
            if label["expected_outcome"] != "ruled":
                continue
            self.assertIsNotNone(label["expected_action"], "%s: ruled without an action" % dispute_id)
            self.assertIsNotNone(
                label["expected_amount_sgd"], "%s: ruled without an amount" % dispute_id
            )

    def test_a_non_ruled_case_names_no_action(self):
        for dispute_id, label in self.by_id.items():
            if label["expected_outcome"] == "ruled":
                continue
            self.assertIsNone(
                label["expected_action"],
                "%s: %s cases must not pre-commit an action" % (dispute_id, label["expected_outcome"]),
            )

    def test_the_thresholds_here_match_the_policy_document(self):
        """The constants above are duplicated from the policy. Prove the copy is faithful.

        Parses the parameters table's actual row VALUES rather than grepping for a
        substring: a first-draft version of this test looked only for the text "20%"
        anywhere in the document, and a mutation that changed the parameters row still
        passed because the string survived elsewhere. Read the number that governs.
        """
        rows = {}
        for line in POLICY.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 2 or cells[0] in ("Parameter", "---"):
                continue
            rows[cells[0]] = cells[1]

        self.assertTrue(rows, "no parameters table found in docs/policy.md")

        def numbers(parameter):
            self.assertIn(parameter, rows, "docs/policy.md lost the %r row" % parameter)
            return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", rows[parameter])]

        material = numbers("Material route deviation")
        self.assertIn(MATERIAL_PCT, material, "material deviation pct drifted: %s" % rows["Material route deviation"])
        self.assertIn(MATERIAL_KM, material, "material deviation km drifted: %s" % rows["Material route deviation"])
        self.assertIn(GROSS_KM, numbers("Gross route deviation"))
        self.assertIn(DE_MINIMIS_SGD, numbers("De minimis adjustment"))
        self.assertIn(AUTONOMOUS_CAP_SGD, numbers("Autonomous decision cap"))
        self.assertIn(MIN_WAIT_MINUTES, numbers("Minimum driver wait before no-show"))
        self.assertIn(PROXIMITY_LIMIT_M, numbers("Driver proximity limit at pickup"))

    def test_the_autonomous_cap_matches_the_runtime_config(self):
        """The policy's cap and the one the code enforces must be the same number.

        They live in different files by design (policy is the document, config is the
        runtime knob), which is exactly how they drift apart.
        """
        config = json.loads((REPO / "app" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            AUTONOMOUS_CAP_SGD,
            config["autonomous_cap_sgd"],
            "app/config.json enforces a cap the policy document does not state",
        )

    def test_every_label_category_matches_its_record(self):
        """A label's category steers which evidence checks run, so it must not drift.

        Found by mutation testing: flipping a LABEL's category silently disabled every
        evidence-agreement check for that case, and flipping a RECORD's category to
        'other' under a 'ruled' label went unnoticed in both directions.
        """
        for dispute_id, label in self.by_id.items():
            path, data = self.records[dispute_id]
            record_category = normalise_category(data["category"])
            self.assertEqual(
                record_category,
                normalise_category(label["category"]),
                "%s: the label says %r but the record says %r"
                % (dispute_id, label["category"], data["category"]),
            )

    def test_a_no_action_ruling_carries_a_zero_amount(self):
        """'No action' means no money moves, so any other amount is a contradiction."""
        for dispute_id, label in self.by_id.items():
            if label["expected_action"] != "no action":
                continue
            self.assertEqual(
                0.0,
                float(label["expected_amount_sgd"]),
                "%s: a no-action ruling cannot carry a non-zero amount" % dispute_id,
            )

    def test_a_non_ruled_case_pre_commits_no_amount(self):
        """Escalation hands the decision to a human; it must not pre-decide the money."""
        for dispute_id, label in self.by_id.items():
            if label["expected_outcome"] == "ruled":
                continue
            self.assertIsNone(
                label["expected_amount_sgd"],
                "%s: a %s case must not pre-commit an amount — that is the human's call"
                % (dispute_id, label["expected_outcome"]),
            )

    def test_every_case_carries_a_rationale(self):
        for dispute_id, label in self.by_id.items():
            self.assertTrue(
                (label.get("rationale") or "").strip(),
                "%s has no rationale — an unexplained label cannot be reviewed" % dispute_id,
            )


class CorpusPolicyAgreementTest(unittest.TestCase):
    """Every rule a label calls decisive must exist in the policy document."""

    @classmethod
    def setUpClass(cls):
        cls.labels, cls.by_id, cls.records = _load_corpus()
        cls.policy = load_policy(POLICY)

    def test_the_policy_document_loads(self):
        self.assertGreaterEqual(len(self.policy.rule_ids()), 20)

    def test_no_label_cites_a_rule_that_does_not_exist(self):
        for dispute_id, label in self.by_id.items():
            unknown = self.policy.unknown_rule_ids(label["decisive_rule_ids"])
            self.assertEqual(
                [], unknown, "%s cites rule(s) not in docs/policy.md: %s" % (dispute_id, unknown)
            )

    def test_every_label_names_at_least_one_decisive_rule(self):
        for dispute_id, label in self.by_id.items():
            self.assertTrue(
                label["decisive_rule_ids"], "%s decides nothing on any rule" % dispute_id
            )

    def test_the_corpus_exercises_both_handled_categories_and_the_out_of_scope_path(self):
        categories = {
            normalise_category(data["category"]) for _path, data in self.records.values()
        }
        for required in AGENT_CATEGORIES:
            self.assertIn(required, categories, "the corpus never exercises %r" % required)
        self.assertIn(CATEGORY_OTHER, categories, "the corpus never exercises the human-review path")

    def test_the_corpus_exercises_every_outcome(self):
        outcomes = {label["expected_outcome"] for label in self.by_id.values()}
        self.assertEqual(
            VALID_OUTCOMES,
            outcomes,
            "a corpus that never escalates cannot demonstrate the escalation path",
        )

    def test_the_corpus_exercises_both_directions_of_a_ruling(self):
        actions = {
            label["expected_action"]
            for label in self.by_id.values()
            if label["expected_outcome"] == "ruled"
        }
        self.assertIn("refund", actions)
        self.assertIn(
            "no action",
            actions,
            "a corpus where every claim succeeds proves the system cannot say no",
        )


class CorpusEvidenceAgreementTest(unittest.TestCase):
    """The decisive numbers in each label must be what the Evidence Pack actually computes.

    This is the test that matters most: a label asserting a SGD 5.81 refund is only
    ground truth if the pack computes 5.81 from that record. Otherwise the label is
    fiction and every metric built on it is meaningless.
    """

    @classmethod
    def setUpClass(cls):
        cls.labels, cls.by_id, cls.records = _load_corpus()

    def _pack(self, dispute_id):
        path, _data = self.records[dispute_id]
        return build_evidence_pack(load_dispute(path)).to_dict()

    def test_a_refund_amount_matches_a_computed_pack_field(self):
        """Every refund figure must be traceable to a number the pack produced."""
        for dispute_id, label in self.by_id.items():
            if label["expected_action"] != "refund":
                continue
            expected = round(float(label["expected_amount_sgd"]), 2)
            pack = self._pack(dispute_id)
            fare = pack.get("fare") or {}
            cancellation = pack.get("cancellation") or {}
            candidates = {
                "fare.deviation_fare_delta_sgd": fare.get("deviation_fare_delta_sgd"),
                "fare.difference_sgd": fare.get("difference_sgd"),
                "cancellation.cancellation_fee_sgd": cancellation.get("cancellation_fee_sgd"),
                "fare.charged_sgd": fare.get("charged_sgd"),
            }
            matched = [
                ref
                for ref, value in candidates.items()
                if value is not None and abs(round(float(value), 2) - expected) < 0.005
            ]
            self.assertTrue(
                matched,
                "%s: labelled refund of %.2f matches no pack field. Pack offers %s"
                % (dispute_id, expected, {k: v for k, v in candidates.items() if v is not None}),
            )

    def test_route_materiality_agrees_with_the_labelled_outcome(self):
        """RD-1's thresholds, applied mechanically, must not contradict the label."""
        for dispute_id, label in self.by_id.items():
            if label["category"] != "route_deviation":
                continue
            pack = self._pack(dispute_id)
            route = pack.get("route") or {}
            pct, km = route.get("deviation_pct"), route.get("deviation_km")
            if pct is None or km is None:
                # Undeterminable: the label must escalate rather than rule on the merits.
                self.assertEqual(
                    "escalated",
                    label["expected_outcome"],
                    "%s has no measurable deviation but is not labelled escalated" % dispute_id,
                )
                continue
            material = (pct >= MATERIAL_PCT and km >= MATERIAL_KM) or km >= GROSS_KM
            refunds_on_the_deviation = "RD-3" in label["decisive_rule_ids"]
            if not material:
                self.assertFalse(
                    refunds_on_the_deviation,
                    "%s: deviation is immaterial under RD-1 (%.2f%% / %.2f km) but the label "
                    "refunds under RD-3" % (dispute_id, pct, km),
                )
            if material and label["expected_outcome"] == "ruled":
                self.assertIn(
                    "RD-1",
                    label["decisive_rule_ids"],
                    "%s: the deviation is material (%.2f%% / %.2f km) so RD-1 is decisive and "
                    "must be cited, whichever way it rules" % (dispute_id, pct, km),
                )

    def test_an_amount_over_the_cap_is_never_ruled_autonomously(self):
        """ESC-4: above SGD 50 the ruling is a recommendation, not a decision."""
        for dispute_id, label in self.by_id.items():
            amount = label.get("expected_amount_sgd")
            if amount is None:
                continue
            if float(amount) > AUTONOMOUS_CAP_SGD:
                self.assertNotEqual(
                    "ruled",
                    label["expected_outcome"],
                    "%s: %.2f exceeds the autonomous cap but is labelled ruled" % (dispute_id, amount),
                )

    def test_a_ruled_refund_clears_the_de_minimis_floor(self):
        """GEN-4: below SGD 1.00 no money moves."""
        for dispute_id, label in self.by_id.items():
            if label["expected_action"] != "refund":
                continue
            self.assertGreaterEqual(
                float(label["expected_amount_sgd"]),
                DE_MINIMIS_SGD,
                "%s refunds below the de minimis floor" % dispute_id,
            )

    def test_no_show_preconditions_agree_with_the_labelled_outcome(self):
        """NS-2 and NS-3, applied mechanically, must not contradict the label."""
        for dispute_id, label in self.by_id.items():
            if label["category"] != "no_show_charge":
                continue
            pack = self._pack(dispute_id)
            cancellation = pack.get("cancellation") or {}
            wait = cancellation.get("driver_wait_minutes")
            distance = cancellation.get("driver_distance_from_pickup_m")

            # NS-3: a driver beyond the proximity limit never earned the fee.
            if distance is not None and distance > PROXIMITY_LIMIT_M:
                self.assertEqual(
                    "refund",
                    label["expected_action"],
                    "%s: driver was %.0f m from pickup, beyond NS-3's %.0f m limit, so the fee "
                    "cannot stand" % (dispute_id, distance, PROXIMITY_LIMIT_M),
                )

            # NS-2: a wait shorter than the minimum never earned the fee either.
            if wait is not None and wait < MIN_WAIT_MINUTES and distance is not None:
                self.assertEqual(
                    "refund",
                    label["expected_action"],
                    "%s: driver waited only %.1f min, short of NS-2's %.1f min"
                    % (dispute_id, wait, MIN_WAIT_MINUTES),
                )

            # Both preconditions cleanly met: the fee stands and the label must not refund it.
            if (
                wait is not None
                and distance is not None
                and wait > MIN_WAIT_MINUTES
                and distance <= PROXIMITY_LIMIT_M
                and label["expected_outcome"] == "ruled"
            ):
                self.assertEqual(
                    "no action",
                    label["expected_action"],
                    "%s: NS-2 and NS-3 are both satisfied (%.1f min, %.0f m), so the fee was "
                    "earned" % (dispute_id, wait, distance),
                )

    def test_every_route_case_recomputes_its_own_distance_from_gps(self):
        """The corpus must not assert distances; the pack must derive them."""
        for dispute_id, label in self.by_id.items():
            if label["category"] != "route_deviation":
                continue
            pack = self._pack(dispute_id)
            route = pack.get("route") or {}
            self.assertGreaterEqual(
                route.get("point_count", 0),
                2,
                "%s has no GPS trace, so its distance is asserted rather than computed" % dispute_id,
            )
            notes = " ".join(pack.get("notes") or [])
            self.assertNotIn(
                "taken from the record, not recomputed",
                notes,
                "%s: the pack fell back to a stated distance" % dispute_id,
            )


class CorpusRunsEndToEndTest(unittest.TestCase):
    """Every case in the corpus must survive the real pipeline without crashing."""

    @classmethod
    def setUpClass(cls):
        cls.labels, cls.by_id, cls.records = _load_corpus()

    def test_every_case_builds_an_evidence_pack(self):
        for dispute_id, (path, _data) in self.records.items():
            dispute = load_dispute(path)
            if not dispute.is_agent_handled:
                continue
            pack = build_evidence_pack(dispute)
            self.assertTrue(
                pack.field_refs(), "%s produced an empty Evidence Pack" % dispute_id
            )

    def test_the_out_of_scope_case_is_routed_away_from_the_agents(self):
        out_of_scope = [
            dispute_id
            for dispute_id, label in self.by_id.items()
            if label["expected_outcome"] == "human_review"
        ]
        self.assertTrue(out_of_scope, "the corpus has no out-of-scope case")
        for dispute_id in out_of_scope:
            path, _data = self.records[dispute_id]
            self.assertFalse(
                load_dispute(path).is_agent_handled,
                "%s is labelled human_review but routes to the agents" % dispute_id,
            )


if __name__ == "__main__":
    unittest.main()
