"""W27 x W24 integration: the replay records each run's prompt summary.

EXPECTED SIBLING RED for BOTH lanes until lane B (W24, GET /api/review/<run_id>/prompts)
merges: at the prepared baseline the server answers 404 for /prompts, the exporter omits the
optional URL, and the manifest has no prompts entry. Neither lane repairs this file; it turns
green on the first tree that carries both lanes. Contract: docs/w27-replay-export-brief.md.
"""

from __future__ import annotations

import unittest

from tests import w27_replay_support as w27

AGENTS = ["rider_advocate", "driver_advocate", "judge"]


class ReplayRecordsPrompts(unittest.TestCase):

    def test_every_run_has_a_recorded_prompt_summary_for_three_agents(self):
        export = w27.mock_export()
        self.assertEqual(export["code"], 0, export["stderr"][-2000:])
        fx = export["fx"]
        for label in w27.LABELS:
            keys = w27.manifest(export["out"], label)
            for run in fx["runs"]:
                with self.subTest(label=label, run=run):
                    key = "GET /api/review/%s/prompts" % run
                    self.assertTrue(key in keys, "%s is not in the %s manifest" % (key, label))
                    body = w27.recorded(export["out"], label, key)
                    self.assertEqual(body.get("run_id"), run)
                    self.assertEqual([entry.get("agent") for entry in body.get("agents", [])], AGENTS)


if __name__ == "__main__":
    unittest.main()
