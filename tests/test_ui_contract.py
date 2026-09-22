"""Behavioral pins for the case-file browser surface.

These tests execute the real UI script in Node with a deliberately small DOM.  The
fixtures are produced by the pipeline (or copied from a local run artifact when one
is available), then mutated in memory to reproduce malformed or audience-sensitive
case files.  They exist because the Python suite cannot see a JavaScript rendering
regression by itself.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI_SOURCE = REPO / "ui" / "app.js"
CORPUS = REPO / "data" / "disputes"

_NODE_HARNESS = r'''
"use strict";

const fs = require("fs");
const vm = require("vm");

class FakeNode {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.className = "";
    this.dataset = {};
    this.hidden = false;
    this.id = "";
    this.href = "";
    this.title = "";
    this.open = false;
    this.files = [];
    this.listeners = {};
    let ownText = "";
    Object.defineProperty(this, "textContent", {
      get: () => ownText + this.children.map((child) => child.textContent).join(""),
      set: (value) => {
        ownText = value === null || value === undefined ? "" : String(value);
        this.children = [];
      },
    });
    this.classList = {
      add: (...names) => {
        names.forEach((name) => {
          if (!this.className.split(/\s+/).includes(name)) {
            this.className = (this.className ? this.className + " " : "") + name;
          }
        });
      },
    };
  }

  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index !== -1) {
      this.children.splice(index, 1);
      child.parentNode = null;
    }
    return child;
  }

  get firstChild() {
    return this.children.length > 0 ? this.children[0] : null;
  }

  addEventListener(name, handler) {
    if (!this.listeners[name]) {
      this.listeners[name] = [];
    }
    this.listeners[name].push(handler);
  }

  dispatch(name) {
    (this.listeners[name] || []).forEach((handler) => handler({ target: this }));
  }
}

function walk(node) {
  const result = [node];
  node.children.forEach((child) => result.push(...walk(child)));
  return result;
}

function classes(node) {
  return node.className.split(/\s+/).filter(Boolean);
}

(async function () {
  const ids = [
    "case-picker",
    "run-folder-picker",
    "load-status",
    "payload-status",
    "case-workspace",
    "loaded-file",
    "metadata-list",
    "grievance-content",
    "evidence-content",
    "claims-content",
    "policy-content",
    "resolution-content",
    "events-content",
  ];
  const roots = {};
  ids.forEach((id) => {
    roots[id] = new FakeNode("div");
    roots[id].id = id;
  });
  roots["case-workspace"].hidden = true;
  const document = {
    getElementById: (id) => roots[id],
    createElement: (tagName) => new FakeNode(tagName),
  };
  const source = fs.readFileSync(process.env.RYDE_UI_SOURCE, "utf8");
  vm.runInNewContext(source, { document }, { filename: "ui/app.js" });

  const caseFile = JSON.parse(fs.readFileSync(process.env.RYDE_CASE_FILE, "utf8"));
  if (process.env.RYDE_UI_SCENARIO === "f3") {
    caseFile.resolution.notes = ["INTERNAL: candidate refund SGD 55.16 at confidence 0.86"];
  } else if (process.env.RYDE_UI_SCENARIO === "f4") {
    caseFile.resolution.ruling = null;
  } else if (process.env.RYDE_UI_SCENARIO === "f4-shape") {
    caseFile.resolution.ruling = JSON.parse(process.env.RYDE_UI_RULING);
  } else if (process.env.RYDE_UI_SCENARIO === "f2-flag") {
    caseFile.resolution.delivered_to_parties = false;
  } else if (process.env.RYDE_UI_SCENARIO === "f5") {
    caseFile.events[2] = null;
  }

  roots["case-picker"].files = [{
    name: "case_file.json",
    text: () => Promise.resolve(JSON.stringify(caseFile)),
  }];
  roots["case-picker"].dispatch("change");
  await new Promise((resolve) => setTimeout(resolve, 0));

  const resolutionNodes = walk(roots["resolution-content"]);
  const partyNodes = resolutionNodes.filter((node) => node.dataset.audience === "parties");
  const humanNodes = resolutionNodes.filter((node) => node.dataset.audience === "human-review-only");
  const eventRows = walk(roots["events-content"]).filter((node) => classes(node).includes("event-row"));
  const malformedRows = eventRows.filter((node) => classes(node).includes("event-malformed"));
  const validRows = eventRows.filter((node) => !classes(node).includes("event-malformed"));

  process.stdout.write(JSON.stringify({
    workspaceHidden: roots["case-workspace"].hidden,
    status: roots["load-status"].textContent,
    partyText: partyNodes.map((node) => node.textContent).join("\n"),
    humanText: humanNodes.map((node) => node.textContent).join("\n"),
    evidenceText: roots["evidence-content"].textContent,
    resolutionText: roots["resolution-content"].textContent,
    eventRows: eventRows.length,
    validEventRows: validRows.length,
    malformedEventRows: malformedRows.length,
    malformedText: malformedRows.map((node) => node.textContent).join("\n"),
  }));
})().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
'''


class UIRenderContractTest(unittest.TestCase):
    """The browser must preserve audience boundaries and degrade malformed rows."""

    def _case_file_path(self, dispute_id: str, temporary: Path) -> Path:
        run_files = sorted((REPO / "runs").glob("*-%s/case_file.json" % dispute_id))
        if run_files:
            data = json.loads(run_files[-1].read_text(encoding="utf-8"))
        else:
            from app.events import EventLog
            from app.llm.mock import MockLLMClient
            from app.pipeline import run_dispute
            from app.policy import load_policy
            from app.dispute import load_dispute

            with tempfile.TemporaryDirectory() as event_tmp:
                case = run_dispute(
                    dispute=load_dispute(CORPUS / (dispute_id + ".json")),
                    llm=MockLLMClient(),
                    policy=load_policy(REPO / "docs" / "policy.md"),
                    events=EventLog(Path(event_tmp) / "run", "ui-test"),
                    confidence_threshold=0.65,
                )
                data = case.to_dict()
        path = temporary / (dispute_id + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def _render(self, scenario: str, dispute_id: str, ruling_literal: str = None) -> dict:
        node = shutil.which("node")
        if not node:
            self.fail("Node is required for the UI behavioral pin")
        with tempfile.TemporaryDirectory() as tmp:
            case_path = self._case_file_path(dispute_id, Path(tmp))
            env = os.environ.copy()
            env.update(
                {
                    "RYDE_UI_SOURCE": str(UI_SOURCE),
                    "RYDE_CASE_FILE": str(case_path),
                    "RYDE_UI_SCENARIO": scenario,
                }
            )
            if ruling_literal is not None:
                env["RYDE_UI_RULING"] = ruling_literal
            result = subprocess.run(
                [node, "-e", _NODE_HARNESS],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
        self.assertEqual(
            0,
            result.returncode,
            "Node UI harness failed:\n%s\n%s" % (result.stdout, result.stderr),
        )
        return json.loads(result.stdout)

    def test_human_review_notes_never_enter_party_or_evidence_surfaces(self):
        """The old human-review renderer put operator notes in the parties card.

        A real OS-0301 case has no evidence pack, so the same notes were also copied
        into an unmarked evidence empty state.  Both copies must stay out of those
        surfaces while a reviewer can still inspect one human-only copy.
        """
        rendered = self._render("f3", "OS-0301")
        self.assertNotIn("55.16", rendered["partyText"])
        self.assertNotIn("0.86", rendered["partyText"])
        self.assertNotIn("55.16", rendered["evidenceText"])
        self.assertNotIn("0.86", rendered["evidenceText"])
        self.assertIn("55.16", rendered["humanText"])
        self.assertIn("0.86", rendered["humanText"])

    def test_ruled_without_ruling_is_marked_malformed_not_delivered(self):
        """A ruled label with no ruling object cannot support a delivery claim."""
        rendered = self._render("f4", "RD-0101")
        self.assertFalse(rendered["workspaceHidden"])
        self.assertNotIn("delivered this decision", rendered["resolutionText"])
        self.assertIn("MALFORMED CASE FILE", rendered["resolutionText"])
        self.assertNotIn("55.16", rendered["resolutionText"])

    def test_a_ruling_that_is_not_a_ruling_object_is_marked_malformed(self):
        """`typeof [] === "object"` let arrays and empty objects through the F4 guard.

        Only null, false, 0 and strings reached the malformed card, so a case file
        whose ruling was [] or {} still claimed "The Judge delivered this decision to
        the parties" over a grid of "Not present in file".
        """
        for literal in ("[]", "{}", "[1,2]", '"refund"', "0"):
            with self.subTest(ruling=literal):
                rendered = self._render("f4-shape", "RD-0101", ruling_literal=literal)
                self.assertFalse(rendered["workspaceHidden"])
                self.assertNotIn("delivered this decision", rendered["resolutionText"])
                self.assertIn("MALFORMED CASE FILE", rendered["resolutionText"])
                self.assertNotIn("Recommended amount", rendered["resolutionText"])

    def test_a_ruled_case_that_was_not_delivered_does_not_claim_delivery(self):
        """The ruled header hardcoded the claim and never read the delivery flag.

        resolution.delivered_to_parties is present on every outcome and the withheld
        card displays it; the ruled card asserted delivery regardless and showed the
        flag nowhere.
        """
        undelivered = self._render("f2-flag", "RD-0101")
        self.assertFalse(undelivered["workspaceHidden"])
        self.assertNotIn("delivered this decision", undelivered["resolutionText"])
        self.assertIn("Delivered to parties", undelivered["resolutionText"])
        self.assertIn("does not say the parties received it", undelivered["resolutionText"])

        delivered = self._render("none", "RD-0101")
        self.assertIn("The Judge delivered this decision to the parties.", delivered["resolutionText"])
        self.assertIn("Delivered to parties", delivered["resolutionText"])

    def test_null_event_degrades_one_row_and_preserves_the_case_file(self):
        """One malformed event must not make the whole workspace disappear."""
        rendered = self._render("f5", "RD-0101")
        self.assertFalse(rendered["workspaceHidden"])
        self.assertEqual(11, rendered["eventRows"])
        self.assertEqual(10, rendered["validEventRows"])
        self.assertEqual(1, rendered["malformedEventRows"])
        self.assertIn("Event row 3", rendered["malformedText"])
        self.assertNotIn("Cannot read properties of null", rendered["status"])


if __name__ == "__main__":
    unittest.main()
