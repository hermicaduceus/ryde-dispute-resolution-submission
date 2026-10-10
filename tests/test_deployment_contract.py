"""The proposed integration contract must be well-formed and must not widen the party view."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "tools" / "deployment" / "openapi.json").read_text(encoding="utf-8"))


def refs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                yield v
            else:
                yield from refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)


def resolve(ref):
    node = SPEC
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


class DeploymentContractTests(unittest.TestCase):
    def test_every_ref_resolves(self):
        found = list(refs(SPEC))
        self.assertTrue(found)
        for ref in found:
            resolve(ref)

    def test_party_view_is_the_five_key_allowlist(self):
        pv = SPEC["components"]["schemas"]["PartyView"]
        self.assertEqual(set(pv["properties"]),
                         {"run_id", "dispute_id", "status", "message", "questions"})
        self.assertIs(pv["additionalProperties"], False)

    def test_party_facing_schemas_carry_no_confidence_or_explanation(self):
        for name in ("PartyView", "StatusEvent"):
            text = json.dumps(SPEC["components"]["schemas"][name]).lower()
            self.assertNotIn("confidence", text)
            self.assertNotIn("explanation", text)

    def test_mutating_calls_require_idempotency_key(self):
        for path, item in SPEC["paths"].items():
            post = item.get("post")
            if post:
                params = [p.get("$ref", "") for p in post.get("parameters", [])]
                self.assertIn("#/components/parameters/IdempotencyKey", params, path)

    def test_human_ceiling_matches_architecture_doc(self):
        amount = SPEC["components"]["schemas"]["HumanDecision"]["properties"]["amount_sgd"]
        self.assertEqual(amount["maximum"], 500)
        self.assertIn("SGD 500", (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
