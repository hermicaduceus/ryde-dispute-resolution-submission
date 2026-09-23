"""Regression pins for the producer's policy path in case files.

The UI displays this value verbatim.  The old pipeline serialized the resolved
absolute path, putting the builder's home directory into every demo artifact.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.dispute import load_dispute
from app.events import EventLog
from app.llm.mock import MockLLMClient
from app.pipeline import run_dispute
from app.policy import load_policy

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "packs" / "ryde-synth-v1" / "disputes"


class PolicySourcePathTest(unittest.TestCase):
    def _run(self, dispute_id: str, policy_path: Path, tmp: Path):
        return run_dispute(
            dispute=load_dispute(CORPUS / (dispute_id + ".json")),
            llm=MockLLMClient(),
            policy=load_policy(policy_path),
            events=EventLog(tmp / "run", "policy-path-test"),
            confidence_threshold=0.65,
        )

    def test_repo_policy_is_emitted_relative_to_repo_root_everywhere(self):
        """The browser should show docs/policy.md, not the builder's home directory."""
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            case = self._run("RD-0101", REPO / "docs" / "policy.md", tmp)
            data = case.to_dict()
            self.assertEqual("docs/policy.md", data["policy"]["source_path"])
            self.assertEqual("docs/policy.md", case.policy_path)

            started = next(event for event in data["events"] if event["type"] == "run.started")
            payload = json.loads((tmp / "run" / started["payload_ref"]).read_text(encoding="utf-8"))
            self.assertEqual("docs/policy.md", payload["policy_path"])

    def test_human_review_case_uses_the_same_relative_policy_path(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            case = self._run("OS-0301", REPO / "docs" / "policy.md", tmp)
            self.assertEqual("docs/policy.md", case.to_dict()["policy"]["source_path"])

    def test_a_relative_policy_path_does_not_depend_on_the_working_directory(self):
        """The same input must serialise the same way wherever the CLI was invoked.

        Path.resolve() anchors a relative path to the process working directory, so
        'docs/policy.md' produced 'docs/policy.md' from the repo and 'policy.md' from
        anywhere else.
        """
        from app.pipeline import _policy_source_path
        from app.policy import PolicySet

        policy = PolicySet(source_path=Path("docs/policy.md"), text="", rules=[])
        from_repo = _policy_source_path(policy)

        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                from_elsewhere = _policy_source_path(policy)
            finally:
                os.chdir(previous)

        self.assertEqual("docs/policy.md", from_repo)
        self.assertEqual(from_repo, from_elsewhere)

    def test_external_policy_does_not_emit_an_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            external_policy = tmp / "policy.md"
            external_policy.write_text(
                (REPO / "docs" / "policy.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            case = self._run("OS-0301", external_policy, tmp)
            source_path = case.to_dict()["policy"]["source_path"]
            self.assertEqual("policy.md", source_path)
            self.assertFalse(Path(source_path).is_absolute())


if __name__ == "__main__":
    unittest.main()
