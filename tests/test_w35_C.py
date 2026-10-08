"""W35 lane C (operator console): one run-folder picker, Recent runs, readable prompt full text.

Written RED-first against HEAD 57758ce. The contract is the W35 lane C brief; in short:

  C2+C3  The loader has ONE input, #run-folder-picker (webkitdirectory). Picking a run folder
         loads <picked>/case_file.json through the case-file path and attaches every file in
         the folder for the event payloads, in one action. Plain errors for a folder without a
         top-level case_file.json (payloads/ picked) and for a folder of run folders (runs/
         picked); invalid JSON keeps the existing messages. #case-picker is gone.
  RUNS   GET /api/review/runs -> {"runs": [...]}: one entry per openable run folder in the
         server's output folder, newest first, at most RECENT_RUNS_LIMIT (100), read-only.
         The console's "Recent runs" panel (before the loader) opens a run through the SAME
         open-by-id path the queue uses, with the five-part lifecycle; Refresh reloads it.
         The static replay records the route, so every listed run opens in the replay.
  C4     The prompt card's "Show full text" <pre> has the dark code-panel look of the event
         payloads (>= 7:1); event payloads look exactly as before.

Fake-DOM tests drive the real ui/app.js in Node; server tests use the real server on the mock
model; browser tests (RealBrowser*) need PUPPETEER_MODULE and BROWSER_EXECUTABLE and run
tests/browser/w35_C.cjs and tests/browser/w35_C_replay.cjs.

Run: env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w35_C -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from tests.w23_b2_support import HARNESS, NODE
from tests.w23_support import Server, body as decision_body, strip_js_comments

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "ui"
BROWSER_DIR = REPO / "tests" / "browser"

LABEL = "Run folder"
HINT = ("Pick one run folder inside runs/, named like 20260921T161731Z-RD-0109. Select the folder "
        "itself, not the files inside it.")
NO_CASE_FILE = ("This folder has no case_file.json. Pick the run folder itself, named like "
                "20260921T161731Z-RD-0109, not a folder inside it such as payloads/.")
SEVERAL_RUNS = ("This folder holds run folders, not one run. Open it and pick one run folder, "
                "named like 20260921T161731Z-RD-0109.")
NOT_JSON = "The selected file is not valid JSON."
NOT_OBJECT = "The selected JSON must contain one case-file object."
RUNS_UNAVAILABLE = ("Recent runs are not available here. Open the console from the running server "
                    "to use them.")
RUNS_EMPTY = "No runs yet."
RUNS_LOADING = "Loading recent runs…"
CASE_FAILED = "The case could not be opened."
NO_PROPOSAL_NOTE = "No AI proposal to approve; use Change."
NOT_ATTACHED = "Payload files are not attached."
RUN_ENTRY_KEYS = {"run_id", "dispute_id", "category", "outcome", "generated_at", "has_human_decision"}
LIMIT = 100

RUN_A = "20261008T110000Z-aaaa0001"
RUN_B = "20261008T100000Z-bbbb0002"
RUN_C = "20261008T090000Z-cccc0003"
PAYLOAD_REF = "payloads/0009-judge-ruling-withheld.json"
PAYLOAD_BODY = {"gates_failed": ["ESC-4"], "w35_marker": "LOCAL-PAYLOAD-7731"}


# ------------------------------------------------------------------ the fake-DOM driver

H = HARNESS
for _old, _new in (
    # Responses may be delayed, rejected or never answered.
    ('let r=responseFor(String(url));if(r.reject)return Promise.reject(new Error("offline"));return Promise.resolve({',
     'let r=responseFor(String(url));if(r.hang)return new Promise(()=>{});return new Promise((resolve,reject)=>'
     'setTimeout(()=>{if(r.reject){reject(new Error("offline"));return}resolve({'),
    ('json:()=>Promise.resolve(r.body)});};', 'json:()=>Promise.resolve(r.body)});},r.delay||0));};'),
    # Focus and scroll requests are recorded.
    ('n.dataset={};', 'n.focus=()=>{n.focused=true};n.scrollIntoView=()=>{n.scrolled=true};n.dataset={};'),
    ('dataset:n.dataset,children:', 'dataset:n.dataset,focused:!!n.focused,scrolled:!!n.scrolled,children:'),
    # Location (deep links), timers, reduced motion.
    ('const scenario=JSON.parse(process.env.SCENARIO), requests=[], counters={};',
     'const scenario=JSON.parse(process.env.SCENARIO), requests=[], counters={}; const checkpoints=[], reads=[];'
     ' const LOC={search:scenario.search||"",pathname:"/",hash:"",href:"http://127.0.0.1:18200/"+(scenario.search||"")};'),
    ('window:{},fetch,Promise,setTimeout,',
     'window:{matchMedia:()=>({matches:true}),location:LOC},location:LOC,URLSearchParams,'
     'fetch,Promise,setTimeout,clearTimeout,'),
    # wait / snapshot / pickdir: a picked folder is a list of files named by their folder path.
    ('for(const a of (scenario.actions||[])){let n;',
     'for(const a of (scenario.actions||[])){if(a.op==="wait"){await new Promise(r=>setTimeout(r,a.ms));continue}'
     'if(a.op==="snapshot"){checkpoints.push({runButtons:byClass("run-open").map(snap),queueButtons:byClass("queue-open").map(snap),'
     'runRows:byClass("run-row").map(snap),status:ids["load-status"].textContent,loaded:ids["loaded-file"].textContent,'
     'payloadStatus:ids["payload-status"].textContent,workspaceHidden:ids["case-workspace"].hidden,'
     'requests:requests.map(r=>r.url)});continue}'
     'if(a.op==="pickdir"){const p=doc.getElementById("run-folder-picker");p.files=a.files.map(f=>({name:f.path.split("/").pop(),'
     'webkitRelativePath:f.path,text:()=>{reads.push(f.path);const t=f.raw!==undefined?f.raw:JSON.stringify(f.body);'
     'return new Promise((res,rej)=>setTimeout(()=>f.reject?rej(new Error("read failed")):res(t),f.delay||0))}}));'
     'p.fire("change");await tick();await tick();await tick();continue}let n;'),
    ('JSON.stringify({ids:', 'JSON.stringify({checkpoints,reads,ids:'),
    ('["queue-row","queue-category",',
     '["run-row","run-open","run-open-status","run-id","run-category","run-outcome","run-generated","run-decided",'
     '"queue-row","queue-category",'),
):
    assert H.count(_old) == 1, _old
    H = H.replace(_old, _new)


def drive(routes, actions=(), search=""):
    scenario = {"routes": routes, "actions": list(actions), "search": search}
    env = dict(os.environ, APP_JS=str(UI / "app.js"), SCENARIO=json.dumps(scenario))
    result = subprocess.run([NODE, "-e", H], env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError("app.js W35 driver failed: " + result.stderr)
    return json.loads(result.stdout)


def ok(payload, **extra):
    out = {"status": 200, "body": payload}
    out.update(extra)
    return out


def wait(ms):
    return {"op": "wait", "ms": ms}


SNAP = {"op": "snapshot"}
REFRESH = {"id": "queue-refresh", "op": "click"}


def run_open(index=0):
    return {"className": "run-open", "op": "click", "index": index}


def queue_open(index=0):
    return {"className": "queue-open", "op": "click", "index": index}


def case_for(run_id, outcome="withheld", events=True):
    return {
        "run_id": run_id, "dispute_id": "PF-" + run_id[-4:], "category": "route_deviation",
        "generated_at": "2026-10-08T11:00:00+00:00", "intake": {},
        "evidence_pack": {"fare": {"charged_sgd": 112.56}}, "claims": {}, "policy": {},
        "resolution": {"outcome": outcome, "party_message": "waiting",
                       "withheld_candidate": {"action": "refund", "recommended_amount_sgd": 55.16,
                                              "confidence": 0.9, "explanation": "x"}},
        "events": [{"seq": 9, "ts": "now", "type": "judge.ruling_withheld", "from": "judge", "to": "system",
                    "summary": "held", "payload_ref": PAYLOAD_REF}] if events else [],
    }


def run_entry(run_id, outcome="withheld", decided=False, category="route_deviation",
              generated_at="2026-10-08T11:00:00+00:00"):
    return {"run_id": run_id, "dispute_id": "PF-" + run_id[-4:], "category": category,
            "outcome": outcome, "generated_at": generated_at, "has_human_decision": decided}


def queue_entry(run_id):
    return {"run_id": run_id, "dispute_id": "PF-" + run_id[-4:], "category": "route_deviation",
            "safety": False, "amount_sgd": 55.16, "amount_source": "proposed", "waiting_seconds": 59,
            "held_by": ["ESC-4"], "proposed": {"action": "refund", "amount_sgd": 55.16}, "can_approve": True}


def routes(runs=None, queue=None, case_delay=None):
    """Queue, overrides and runs; every listed run (and queued run) opens with its own case."""
    runs = [run_entry(RUN_A), run_entry(RUN_B, "ruled"), run_entry(RUN_C, "withheld", True)] \
        if runs is None else runs
    out = {
        "/api/review/queue": [ok({"cases": [] if queue is None else queue})],
        "/api/review/overrides": [ok({"approved_count": 0, "groups": []})],
        "/api/review/runs": [ok({"runs": runs})],
    }
    ids = [r["run_id"] for r in runs if isinstance(r, dict) and isinstance(r.get("run_id"), str)]
    ids += [q["run_id"] for q in (queue or [])]
    for run_id in ids:
        response = ok({"case_file": case_for(run_id), "human_decision": None})
        if case_delay:
            response["delay"] = case_delay
        out["/api/review/%s/case" % run_id] = [response]
        out["/api/review/%s/prompts" % run_id] = [ok({"run_id": run_id, "agents": []})]
    return out


def folder(name, case=None, raw=None, extra=(), delay=0, reject=False):
    """A picked run folder: <name>/case_file.json, events.jsonl and one payload file."""
    files = []
    if case is not None or raw is not None:
        entry = {"path": name + "/case_file.json", "delay": delay}
        if raw is not None:
            entry["raw"] = raw
        else:
            entry["body"] = case
        if reject:
            entry["reject"] = True
        files.append(entry)
    files.append({"path": name + "/events.jsonl", "raw": ""})
    files.append({"path": name + "/" + PAYLOAD_REF, "body": PAYLOAD_BODY})
    files.extend(extra)
    return {"op": "pickdir", "files": files}


def node(out, id_):
    found = out["ids"].get(id_)
    if found is None:
        raise AssertionError("no element #%s in the driver output" % id_)
    return found


def texts(out, cls):
    return [n["text"] for n in out["classes"][cls]]


def current(out):
    """Every button (queue or runs) carrying aria-current, as (class, run id) pairs."""
    found = []
    for row_cls, button_cls in (("queue-row", "queue-open"), ("run-row", "run-open")):
        for row in out["classes"][row_cls]:
            for child in row["children"]:
                # The fake DOM has no removeAttribute, so app.js writes "false" there; a real
                # browser removes it (tests/browser/w35_C.cjs counts the attribute itself).
                if button_cls in child["className"].split() and child["attrs"].get("aria-current") not in (None, "false"):
                    found.append((button_cls, row["dataset"].get("runId"), child["attrs"]["aria-current"]))
    return found


def urls(out):
    return [r["url"] for r in out["requests"]]


def row_status(out, index):
    rows = out["classes"]["run-row"]
    if len(rows) <= index:
        raise AssertionError("no run row %d (%d rows)" % (index, len(rows)))
    row = rows[index]
    notes = [c for c in row["children"] if "run-open-status" in c["className"].split()]
    if len(notes) != 1:
        raise AssertionError("run row %d has %d status lines" % (index, len(notes)))
    return notes[0]


# ================================================================== C2 + C3: the picker page


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self._open = []

    def handle_starttag(self, tag, attrs):
        item = {"tag": tag, "attrs": dict(attrs), "text": "", "index": len(self.elements)}
        self.elements.append(item)
        if tag not in ("input", "meta", "link", "br", "img"):
            self._open.append(item)

    def handle_endtag(self, tag):
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i]["tag"] == tag:
                del self._open[i:]
                return

    def handle_data(self, data):
        for item in self._open:
            item["text"] += data


def page():
    parser = _Page()
    parser.feed((UI / "index.html").read_text(encoding="utf-8"))
    return parser.elements


def by_id(elements, id_):
    found = [e for e in elements if e["attrs"].get("id") == id_]
    if len(found) != 1:
        raise AssertionError("expected one #%s, found %d" % (id_, len(found)))
    return found[0]


class OnePickerPage(unittest.TestCase):
    def test_the_page_has_exactly_one_file_input_the_run_folder_picker(self):
        inputs = [e for e in page() if e["tag"] == "input" and e["attrs"].get("type") == "file"]
        self.assertEqual(["run-folder-picker"], [e["attrs"].get("id") for e in inputs])
        attrs = inputs[0]["attrs"]
        for flag in ("webkitdirectory", "directory", "multiple"):
            self.assertIn(flag, attrs, "the picker picks a folder: %s" % flag)
        self.assertNotIn("accept", attrs, "no separate .json picker survives")
        self.assertEqual("run-folder-hint", attrs.get("aria-describedby"))

    def test_the_case_picker_is_gone_from_page_and_script(self):
        self.assertNotIn("case-picker", (UI / "index.html").read_text(encoding="utf-8"))
        self.assertNotIn("case-picker", strip_js_comments((UI / "app.js").read_text(encoding="utf-8")))

    def test_label_and_hint_are_the_exact_strings(self):
        elements = page()
        labels = [e for e in elements if e["tag"] == "label" and e["attrs"].get("for") == "run-folder-picker"]
        self.assertEqual([LABEL], [" ".join(e["text"].split()) for e in labels])
        self.assertEqual(HINT, " ".join(by_id(elements, "run-folder-hint")["text"].split()))

    def test_recent_runs_panel_sits_after_overrides_and_before_the_loader(self):
        elements = page()
        order = [e["attrs"].get("id") or e["attrs"].get("class") for e in elements if e["tag"] == "section"]
        self.assertEqual(["queue-panel", "overrides-panel", "runs-panel", "loader-panel"], order[:4])
        panel = by_id(elements, "runs-panel")
        self.assertEqual("runs-title", panel["attrs"].get("aria-labelledby"))
        self.assertEqual("Recent runs", by_id(elements, "runs-title")["text"].strip())
        self.assertEqual("h2", by_id(elements, "runs-title")["tag"])
        runs_status = by_id(elements, "runs-status")
        self.assertEqual(("status", "polite"), (runs_status["attrs"].get("role"), runs_status["attrs"].get("aria-live")))
        self.assertEqual(RUNS_LOADING, runs_status["text"].strip())
        self.assertEqual("div", by_id(elements, "runs-content")["tag"])


# ================================================================== C2 + C3: picking a folder


class PickARunFolder(unittest.TestCase):
    def test_a_run_folder_loads_its_case_file_and_attaches_its_files_in_one_action(self):
        out = drive(routes(runs=[]), [folder("20261008T120000Z-dddd0004", case_for("LOCAL-1")), wait(30)])
        self.assertEqual("Loaded 20261008T120000Z-dddd0004/case_file.json.", node(out, "load-status")["text"])
        self.assertEqual("success", node(out, "load-status")["dataset"].get("state"))
        self.assertEqual("20261008T120000Z-dddd0004/case_file.json", node(out, "loaded-file")["text"])
        self.assertFalse(node(out, "case-workspace")["hidden"])
        self.assertEqual("Attached 3 run file(s); event payloads can be opened.", node(out, "payload-status")["text"])
        self.assertEqual("success", node(out, "payload-status")["dataset"].get("state"))
        self.assertEqual(["20261008T120000Z-dddd0004/case_file.json"], out["reads"], "only the case file is read")
        self.assertEqual([], [u for u in urls(out) if u.endswith("/case")], "a local folder never asks the server")
        self.assertTrue(node(out, "decision-section")["hidden"], "a local folder never gets the decision form")

    def test_an_event_payload_opens_from_the_picked_folder(self):
        out = drive(routes(runs=[]), [folder("R1", case_for("LOCAL-1")), wait(30),
                                      {"className": "event-row", "op": "toggle"}, wait(30)])
        self.assertIn("R1/" + PAYLOAD_REF, out["reads"])
        self.assertEqual([json.dumps(PAYLOAD_BODY, indent=2)], texts(out, "payload-json"))
        self.assertEqual([], [u for u in urls(out) if "/payloads/" in u])

    def test_reading_state_before_the_case_file_arrives(self):
        out = drive(routes(runs=[]), [folder("R1", case_for("LOCAL-1"), delay=200), wait(40), SNAP, wait(300), SNAP])
        first, last = out["checkpoints"]
        self.assertEqual("Reading R1/case_file.json…", first["status"])
        self.assertEqual(NOT_ATTACHED, first["payloadStatus"], "files attach only once the case loaded")
        self.assertTrue(first["workspaceHidden"])
        self.assertEqual("Loaded R1/case_file.json.", last["status"])
        self.assertEqual("Attached 3 run file(s); event payloads can be opened.", last["payloadStatus"])

    def test_the_payloads_folder_picked_says_so_and_reads_nothing(self):
        payloads_only = {"op": "pickdir", "files": [
            {"path": "payloads/0001-run-started.json", "body": {}},
            {"path": "payloads/0009-judge-ruling-withheld.json", "body": PAYLOAD_BODY}]}
        out = drive(routes(runs=[]), [payloads_only, wait(30)])
        self.assertEqual(NO_CASE_FILE, node(out, "load-status")["text"])
        self.assertEqual("error", node(out, "load-status")["dataset"].get("state"))
        self.assertTrue(node(out, "case-workspace")["hidden"])
        self.assertEqual(NOT_ATTACHED, node(out, "payload-status")["text"])
        self.assertEqual([], out["reads"])

    def test_a_case_file_that_is_not_at_the_top_of_the_folder_does_not_count(self):
        for name, files in (
            ("too deep", [{"path": "R1/sub/inner/case_file.json", "body": case_for("X")}]),
            ("other name", [{"path": "R1/case_file.json.bak", "body": case_for("X")},
                            {"path": "R1/old_case_file.json", "body": case_for("X")}]),
            ("no folder", [{"path": "case_file.json", "body": case_for("X")}]),
        ):
            with self.subTest(case=name):
                out = drive(routes(runs=[]), [{"op": "pickdir", "files": files}, wait(30)])
                self.assertEqual(NO_CASE_FILE, node(out, "load-status")["text"])
                self.assertEqual([], out["reads"])
                self.assertTrue(node(out, "case-workspace")["hidden"])

    def test_the_runs_folder_picked_says_pick_one_run(self):
        for count in (1, 3):
            with self.subTest(runs=count):
                files = []
                for i in range(count):
                    files += [{"path": "runs/RUN-%d/case_file.json" % i, "body": case_for("RUN-%d" % i)},
                              {"path": "runs/RUN-%d/%s" % (i, PAYLOAD_REF), "body": PAYLOAD_BODY}]
                out = drive(routes(runs=[]), [{"op": "pickdir", "files": files}, wait(30)])
                self.assertEqual(SEVERAL_RUNS, node(out, "load-status")["text"])
                self.assertEqual("error", node(out, "load-status")["dataset"].get("state"))
                self.assertEqual([], out["reads"])
                self.assertEqual(NOT_ATTACHED, node(out, "payload-status")["text"])

    def test_a_top_level_case_file_wins_over_nested_ones(self):
        files = [{"path": "R1/archive/OLD/case_file.json", "body": case_for("OLD")}]
        out = drive(routes(runs=[]), [folder("R1", case_for("LOCAL-1"), extra=files), wait(30)])
        self.assertEqual("Loaded R1/case_file.json.", node(out, "load-status")["text"])
        self.assertEqual(["R1/case_file.json"], out["reads"])

    def test_invalid_json_keeps_the_existing_messages_and_attaches_nothing(self):
        for raw, message in (("{not json", NOT_JSON), ("[1, 2]", NOT_OBJECT), ("null", NOT_OBJECT), ('"x"', NOT_OBJECT)):
            with self.subTest(raw=raw):
                out = drive(routes(runs=[]), [folder("R1", raw=raw), wait(30)])
                self.assertEqual(message, node(out, "load-status")["text"])
                self.assertEqual("error", node(out, "load-status")["dataset"].get("state"))
                self.assertTrue(node(out, "case-workspace")["hidden"])
                self.assertEqual(NOT_ATTACHED, node(out, "payload-status")["text"])

    def test_an_unreadable_case_file_reports_the_read_error(self):
        out = drive(routes(runs=[]), [folder("R1", case_for("X"), reject=True), wait(30)])
        self.assertEqual("read failed", node(out, "load-status")["text"])
        self.assertEqual(NOT_ATTACHED, node(out, "payload-status")["text"])

    def test_an_empty_pick_changes_nothing(self):
        out = drive(routes(runs=[]), [{"op": "pickdir", "files": []}, wait(30)])
        self.assertEqual("", node(out, "load-status")["text"])
        self.assertNotIn("state", node(out, "load-status")["dataset"])
        self.assertTrue(node(out, "case-workspace")["hidden"])
        self.assertEqual([], out["reads"])

    def test_a_slow_folder_never_replaces_a_newer_folder_or_its_files(self):
        slow = folder("SLOW", case_for("SLOW"), delay=200)
        fast = folder("FAST", case_for("FAST"), extra=[{"path": "FAST/payloads/0010-x.json", "body": {}}])
        out = drive(routes(runs=[]), [slow, fast, wait(400)])
        self.assertEqual("FAST/case_file.json", node(out, "loaded-file")["text"])
        self.assertEqual("Loaded FAST/case_file.json.", node(out, "load-status")["text"])
        self.assertEqual("Attached 4 run file(s); event payloads can be opened.", node(out, "payload-status")["text"])

    def test_a_wrong_folder_clears_an_open_server_case_and_its_marker(self):
        bad = {"op": "pickdir", "files": [{"path": "payloads/0001-run-started.json", "body": {}}]}
        out = drive(routes(queue=[queue_entry(RUN_A)]), [wait(20), run_open(0), wait(30), bad, wait(30)])
        self.assertEqual(NO_CASE_FILE, node(out, "load-status")["text"])
        self.assertEqual([], current(out))
        self.assertTrue(node(out, "decision-section")["hidden"])
        self.assertTrue(node(out, "case-workspace")["hidden"])

    def test_a_folder_pick_invalidates_a_pending_runs_open(self):
        out = drive(routes(case_delay=200), [wait(20), run_open(0), wait(20),
                                              folder("R1", case_for("LOCAL-1")), wait(400)])
        self.assertEqual("R1/case_file.json", node(out, "loaded-file")["text"])
        self.assertEqual([], current(out))
        self.assertEqual(["Open case"] * 3, texts(out, "run-open"))
        self.assertEqual([False] * 3, [b["disabled"] for b in out["classes"]["run-open"]])

    def test_a_folder_pick_before_the_deep_link_fires_wins(self):
        r = routes()
        r["/api/review/queue"] = [ok({"cases": []}, delay=300)]
        out = drive(r, [wait(30), folder("R1", case_for("LOCAL-1")), wait(600)], search="?run=" + RUN_A)
        self.assertEqual([], [u for u in urls(out) if u.endswith("/case")])
        self.assertEqual("R1/case_file.json", node(out, "loaded-file")["text"])


# ================================================================== RUNS: the console panel


class RecentRunsPanel(unittest.TestCase):
    def test_startup_asks_for_the_runs_and_renders_one_row_each_in_server_order(self):
        out = drive(routes(), [wait(30)])
        self.assertIn("/api/review/runs", urls(out))
        self.assertEqual("3 runs, newest first.", node(out, "runs-status")["text"])
        self.assertEqual([RUN_A, RUN_B, RUN_C], [r["dataset"].get("runId") for r in out["classes"]["run-row"]])
        self.assertEqual([RUN_A, RUN_B, RUN_C], texts(out, "run-id"))
        self.assertEqual(["Route deviation"] * 3, texts(out, "run-category"))
        self.assertEqual(["Held for a human", "Ruled", "Held for a human"], texts(out, "run-outcome"))
        self.assertEqual(["2026-10-08T11:00:00+00:00"] * 3, texts(out, "run-generated"))
        self.assertEqual(["Human decision recorded"], texts(out, "run-decided"))
        self.assertNotIn("Human decision recorded", out["classes"]["run-row"][0]["text"])
        self.assertIn("Human decision recorded", out["classes"]["run-row"][2]["text"])
        self.assertEqual(["Open case"] * 3, texts(out, "run-open"))
        self.assertEqual(["button"] * 3, [b["type"] for b in out["classes"]["run-open"]])
        self.assertEqual([], current(out))

    def test_every_outcome_and_category_has_its_label(self):
        runs = [run_entry("R-1", "ruled", category="no_show_charge"), run_entry("R-2", "withheld"),
                run_entry("R-3", "human_review", category="other"), run_entry("R-4", "needs_info"),
                run_entry("R-5", "mystery", category="safety_incident"),
                dict(run_entry("R-6"), generated_at=""), dict(run_entry("R-7"), generated_at=None)]
        out = drive(routes(runs=runs), [wait(30)])
        self.assertEqual(["Ruled", "Held for a human", "Passed to support", "Asked for more information",
                          "Outcome: mystery", "Held for a human", "Held for a human"], texts(out, "run-outcome"))
        self.assertEqual(["No-show charge", "Route deviation", "Other", "Route deviation", "Other",
                          "Route deviation", "Route deviation"], texts(out, "run-category"))
        self.assertEqual(["Time not recorded", "Time not recorded"], texts(out, "run-generated")[5:])
        self.assertEqual("7 runs, newest first.", node(out, "runs-status")["text"])

    def test_one_run_and_no_runs(self):
        out = drive(routes(runs=[run_entry(RUN_A)]), [wait(30)])
        self.assertEqual("1 run, newest first.", node(out, "runs-status")["text"])
        out = drive(routes(runs=[]), [wait(30)])
        self.assertEqual(RUNS_EMPTY, node(out, "runs-status")["text"])
        self.assertEqual([], out["classes"]["run-row"])

    def test_a_failed_or_malformed_answer_says_not_available_here(self):
        for name, response in (("offline", {"reject": True}), ("404", {"status": 404, "body": {"error": "x"}}),
                               ("500", {"status": 500, "body": {}}), ("null", ok(None)), ("array", ok([])),
                               ("empty", ok({})), ("runs-object", ok({"runs": {}})),
                               ("runs-string", ok({"runs": "x"})), ("runs-null", ok({"runs": None}))):
            with self.subTest(response=name):
                r = routes()
                r["/api/review/runs"] = [response]
                out = drive(r, [wait(30)])
                self.assertEqual(RUNS_UNAVAILABLE, node(out, "runs-status")["text"])
                self.assertEqual([], out["classes"]["run-row"])

    def test_rows_that_are_not_run_objects_are_skipped(self):
        runs = [[], {}, None, "x", 7, {"run_id": 5}, {"run_id": ""}, {"run_id": "../etc"},
                {"run_id": "a b"}, {"run_id": "x" * 129}, run_entry(RUN_B, "ruled")]
        out = drive(routes(runs=runs), [wait(30)])
        self.assertEqual([RUN_B], [r["dataset"].get("runId") for r in out["classes"]["run-row"]])
        self.assertEqual("1 run, newest first.", node(out, "runs-status")["text"])

    def test_refresh_reloads_the_runs_too(self):
        r = routes()
        r["/api/review/runs"] = [ok({"runs": [run_entry(RUN_A)]}), ok({"runs": [run_entry(RUN_B), run_entry(RUN_A)]})]
        out = drive(r, [wait(30), REFRESH, wait(30)])
        self.assertEqual(2, urls(out).count("/api/review/runs"))
        self.assertEqual([RUN_B, RUN_A], texts(out, "run-id"))


class RecentRunsOpen(unittest.TestCase):
    """The five-part lifecycle, through the queue's own open-by-id path."""

    def test_open_requests_the_case_by_id_and_renders_it(self):
        out = drive(routes(), [wait(20), run_open(1), wait(40)])
        self.assertEqual(["/api/review/%s/case" % RUN_B], [u for u in urls(out) if u.endswith("/case")])
        self.assertIn("/api/review/%s/prompts" % RUN_B, urls(out), "the prompt panel works from the server")
        self.assertEqual(RUN_B, node(out, "loaded-file")["text"])
        self.assertEqual("Loaded %s." % RUN_B, node(out, "load-status")["text"])
        self.assertFalse(node(out, "case-workspace")["hidden"])

    def test_pending_label_and_disabled_on_the_clicked_button_only(self):
        out = drive(routes(case_delay=150), [wait(20), run_open(1), SNAP, wait(250)])
        buttons = out["checkpoints"][0]["runButtons"]
        self.assertEqual(["Open case", "Opening…", "Open case"], [b["text"] for b in buttons])
        self.assertEqual([False, True, False], [b["disabled"] for b in buttons])

    def test_success_focuses_scrolls_and_marks_exactly_one_row(self):
        out = drive(routes(), [wait(20), run_open(1), wait(40)])
        summary = node(out, "case-summary")
        self.assertTrue(summary["focused"])
        self.assertTrue(summary["scrolled"])
        self.assertEqual("-1", summary["attrs"].get("tabindex"))
        self.assertIn("case-open-highlight", summary["className"])
        self.assertEqual([("run-open", RUN_B, "true")], current(out))
        self.assertEqual(["Open case", "Currently open", "Open case"], texts(out, "run-open"))
        self.assertEqual(3, len(out["classes"]["run-open"]))
        self.assertFalse(out["classes"]["run-open"][1]["disabled"])
        self.assertIn("is-open", out["classes"]["run-row"][1]["className"].split())
        self.assertNotIn("is-open", out["classes"]["run-row"][0]["className"].split())

    def test_a_run_shown_in_both_lists_is_marked_only_where_it_was_opened(self):
        out = drive(routes(queue=[queue_entry(RUN_A)]), [wait(20), run_open(0), wait(40)])
        self.assertEqual([("run-open", RUN_A, "true")], current(out))
        self.assertEqual(["Open case"], texts(out, "queue-open"))
        out = drive(routes(queue=[queue_entry(RUN_A)]), [wait(20), queue_open(0), wait(40)])
        self.assertEqual([("queue-open", RUN_A, "true")], current(out))
        self.assertEqual(["Open case"] * 3, texts(out, "run-open"))
        out = drive(routes(queue=[queue_entry(RUN_A)]), [wait(20), queue_open(0), wait(40), run_open(1), wait(40)])
        self.assertEqual([("run-open", RUN_B, "true")], current(out))
        out = drive(routes(queue=[queue_entry(RUN_A)]), [wait(20), run_open(1), wait(40), queue_open(0), wait(40)])
        self.assertEqual([("queue-open", RUN_A, "true")], current(out))

    def test_a_queued_run_opened_from_the_runs_list_gets_the_queue_decision_form(self):
        out = drive(routes(queue=[queue_entry(RUN_A)]), [wait(20), run_open(0), wait(40)])
        self.assertFalse(node(out, "decision-section")["hidden"])
        self.assertFalse(node(out, "decision-approve")["disabled"], "the queue entry's proposal is used")
        self.assertEqual([], texts(out, "decision-note"))

    def test_a_held_run_not_in_the_queue_has_no_proposal_to_approve(self):
        out = drive(routes(), [wait(20), run_open(0), wait(40)])
        self.assertFalse(node(out, "decision-section")["hidden"])
        self.assertTrue(node(out, "decision-approve")["disabled"])
        self.assertEqual([NO_PROPOSAL_NOTE], texts(out, "decision-note"))

    def test_failure_is_row_local_and_retry_works(self):
        r = routes()
        r["/api/review/%s/case" % RUN_B] = [{"status": 500, "body": {}},
                                             ok({"case_file": case_for(RUN_B), "human_decision": None})]
        out = drive(r, [wait(20), run_open(1), wait(40)])
        note = row_status(out, 1)
        self.assertEqual(CASE_FAILED, note["text"])
        self.assertEqual(("status", "polite"), (note["attrs"].get("role"), note["attrs"].get("aria-live")))
        self.assertEqual("", row_status(out, 0)["text"])
        self.assertEqual(["Open case"] * 3, texts(out, "run-open"))
        self.assertFalse(out["classes"]["run-open"][1]["disabled"])
        self.assertEqual([], current(out))
        out = drive(r, [wait(20), run_open(1), wait(40), run_open(1), wait(40)])
        self.assertEqual("", row_status(out, 1)["text"], "a retry that succeeds clears the row's failure")
        self.assertEqual([("run-open", RUN_B, "true")], current(out))
        self.assertEqual(RUN_B, node(out, "loaded-file")["text"])

    def test_a_slow_earlier_success_never_replaces_the_later_open(self):
        r = routes()
        r["/api/review/%s/case" % RUN_A][0]["delay"] = 200
        out = drive(r, [wait(20), run_open(0), wait(20), run_open(1), wait(400)])
        self.assertEqual(RUN_B, node(out, "loaded-file")["text"])
        self.assertEqual([("run-open", RUN_B, "true")], current(out))
        self.assertEqual(["Open case", "Currently open", "Open case"], texts(out, "run-open"))

    def test_a_slow_earlier_failure_never_clears_the_later_open(self):
        r = routes()
        r["/api/review/%s/case" % RUN_A] = [{"reject": True, "delay": 200}]
        out = drive(r, [wait(20), run_open(0), wait(20), run_open(1), wait(400)])
        self.assertEqual(RUN_B, node(out, "loaded-file")["text"])
        self.assertEqual("Loaded %s." % RUN_B, node(out, "load-status")["text"])
        self.assertEqual("", row_status(out, 0)["text"], "a stale failure renders nowhere")
        self.assertEqual([("run-open", RUN_B, "true")], current(out))
        self.assertFalse(node(out, "decision-section")["hidden"])

    def test_a_stale_reply_never_resets_the_newer_pending_button(self):
        # Same row twice: the first open answers late (success or failure) while the second is
        # still pending; the button must keep the second open's pending state.
        for rejected in (False, True):
            with self.subTest(stale_failure=rejected):
                r = routes()
                first = {"reject": True, "delay": 150} if rejected else \
                    ok({"case_file": case_for(RUN_B), "human_decision": None}, delay=150)
                r["/api/review/%s/case" % RUN_B] = [first, ok({"case_file": case_for(RUN_B), "human_decision": None}, delay=500)]
                out = drive(r, [wait(20), run_open(1), wait(20), folder("R1", case_for("LOCAL-1")), wait(20),
                                run_open(1), wait(250), SNAP, wait(500)])
                buttons = out["checkpoints"][0]["runButtons"]
                self.assertEqual(3, len(buttons), "three run rows at the checkpoint")
                pending = buttons[1]
                self.assertEqual("Opening…", pending["text"])
                self.assertTrue(pending["disabled"])
                self.assertEqual([("run-open", RUN_B, "true")], current(out))

    def test_refresh_invalidates_a_pending_open(self):
        out = drive(routes(case_delay=250), [wait(20), run_open(1), wait(30), REFRESH, wait(30), SNAP, wait(400)])
        snap = out["checkpoints"][0]
        self.assertEqual(["Open case"] * 3, [b["text"] for b in snap["runButtons"]])
        self.assertEqual([False] * 3, [b["disabled"] for b in snap["runButtons"]])
        self.assertEqual("", node(out, "loaded-file")["text"], "the invalidated open never renders")
        self.assertTrue(node(out, "case-workspace")["hidden"])
        self.assertEqual([], current(out))

    def test_refresh_invalidates_a_pending_queue_open_too(self):
        out = drive(routes(queue=[queue_entry(RUN_A)], case_delay=250),
                    [wait(20), queue_open(0), wait(30), REFRESH, wait(400)])
        self.assertEqual("", node(out, "loaded-file")["text"])
        self.assertEqual([], current(out))
        self.assertEqual(["Open case"], texts(out, "queue-open"))

    def test_refresh_keeps_a_completed_open_marked(self):
        out = drive(routes(), [wait(20), run_open(1), wait(40), REFRESH, wait(40)])
        self.assertEqual([("run-open", RUN_B, "true")], current(out))
        self.assertEqual(RUN_B, node(out, "loaded-file")["text"])

    def test_refresh_during_a_local_read_does_not_drop_it(self):
        out = drive(routes(), [wait(20), folder("R1", case_for("LOCAL-1"), delay=150), wait(20), REFRESH, wait(300)])
        self.assertEqual("Loaded R1/case_file.json.", node(out, "load-status")["text"])

    def test_a_deep_link_to_a_run_outside_the_queue_marks_its_runs_row(self):
        out = drive(routes(), [wait(80)], search="?run=" + RUN_B)
        self.assertEqual(RUN_B, node(out, "loaded-file")["text"])
        self.assertEqual([("run-open", RUN_B, "true")], current(out))

    def test_a_deep_link_to_a_queued_run_marks_its_queue_row(self):
        out = drive(routes(queue=[queue_entry(RUN_A)]), [wait(80)], search="?run=" + RUN_A)
        self.assertEqual([("queue-open", RUN_A, "true")], current(out))
        self.assertFalse(node(out, "decision-approve")["disabled"])

    def test_a_decision_sent_reloads_the_runs(self):
        r = routes(queue=[queue_entry(RUN_A)])
        r["/api/review/%s/decision" % RUN_A] = [ok({"decision": {}, "party_view": {"message": "done"}})]
        out = drive(r, [wait(20), queue_open(0), wait(40), {"id": "decision-approve", "op": "check"},
                        {"id": "decision-form", "op": "submit"}, {"id": "decision-confirm-send", "op": "click"},
                        wait(40)])
        self.assertIn("/api/review/%s/decision" % RUN_A, urls(out))
        self.assertEqual(2, urls(out).count("/api/review/runs"))


# ================================================================== RUNS: the server route


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, None


def _write_case(out, name, case):
    """HAND-MADE SHAPE: a minimal run folder (a case file only) for listing rules the pipeline
    cannot reach (exact clock positions, a hundred runs, wrong shapes)."""
    run_dir = Path(out) / name
    run_dir.mkdir(parents=True, exist_ok=True)
    data = case if isinstance(case, str) else json.dumps(case)
    (run_dir / "case_file.json").write_text(data, encoding="utf-8")
    return run_dir


def _minimal(name, generated_at="2026-10-08T11:00:00+00:00", outcome="ruled", **extra):
    case = {"run_id": name, "dispute_id": "D-" + name[-4:], "category": "route_deviation",
            "generated_at": generated_at, "resolution": {"outcome": outcome}}
    case.update(extra)
    return case


def _tree(root):
    """Every path under root with its bytes and mtime, plus directory listings."""
    out = {}
    for path in sorted(Path(root).rglob("*")):
        rel = str(path.relative_to(root))
        stat = path.lstat()
        if path.is_symlink():
            out[rel] = ("link", os.readlink(path), stat.st_mtime_ns)
        elif path.is_dir():
            out[rel] = ("dir", tuple(sorted(os.listdir(path))), stat.st_mtime_ns)
        else:
            out[rel] = ("file", path.read_bytes(), stat.st_mtime_ns)
    out["."] = ("dir", tuple(sorted(os.listdir(root))), Path(root).stat().st_mtime_ns)
    return out


class RecentRunsRouteRealRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.rd = cls.server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        cls.ns = cls.server.file(trip_id="T-NS0202", category="no_show_charge", claim=None)
        cls.decided = cls.server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        status, _ = cls.server.decide(cls.decided["run_id"], decision_body("reject"))
        if status != 200:
            raise AssertionError("fixture: the decision was refused")

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def runs(self):
        status, data = _get(self.server.base, "/api/review/runs")
        self.assertEqual(200, status)
        self.assertIsInstance(data, dict)
        self.assertEqual(["runs"], list(data))
        self.assertIsInstance(data["runs"], list)
        return data["runs"]

    def test_one_entry_per_run_with_exactly_the_documented_fields(self):
        runs = self.runs()
        self.assertEqual(sorted([self.rd["run_id"], self.ns["run_id"], self.decided["run_id"]]),
                         sorted(r["run_id"] for r in runs))
        for entry in runs:
            with self.subTest(run=entry["run_id"]):
                self.assertEqual(RUN_ENTRY_KEYS, set(entry))
                case = self.server.case(entry["run_id"])
                self.assertEqual(case["dispute_id"], entry["dispute_id"])
                self.assertEqual(case["category"], entry["category"])
                self.assertEqual(case["resolution"]["outcome"], entry["outcome"])
                self.assertEqual(case["generated_at"], entry["generated_at"])
        by_id = {r["run_id"]: r for r in runs}
        self.assertEqual("withheld", by_id[self.rd["run_id"]]["outcome"])
        self.assertEqual("ruled", by_id[self.ns["run_id"]]["outcome"])
        self.assertIs(False, by_id[self.rd["run_id"]]["has_human_decision"])
        self.assertIs(False, by_id[self.ns["run_id"]]["has_human_decision"])
        self.assertIs(True, by_id[self.decided["run_id"]]["has_human_decision"])

    def test_every_listed_run_opens_through_the_open_by_id_path(self):
        for entry in self.runs():
            with self.subTest(run=entry["run_id"]):
                status, data = _get(self.server.base, "/api/review/%s/case" % entry["run_id"])
                self.assertEqual(200, status)
                self.assertEqual(entry["run_id"], data["case_file"]["run_id"])
                self.assertEqual(200, _get(self.server.base, "/api/review/%s/prompts" % entry["run_id"])[0])

    def test_the_route_never_writes(self):
        before = _tree(self.server.out)
        for _ in range(3):
            self.runs()
        self.assertEqual(before, _tree(self.server.out))

    def test_post_is_not_a_route(self):
        status, _headers, _raw = self.server.raw("POST", "/api/review/runs", body={})
        self.assertEqual(404, status)


class RecentRunsRouteRules(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.addCleanup(self.server.close)
        self.out = self.server.out

    def runs(self):
        """The route's answer, its shape asserted first: 200, exactly {"runs": [...]}."""
        status, data = _get(self.server.base, "/api/review/runs")
        self.assertEqual(200, status)
        self.assertIsInstance(data, dict)
        self.assertEqual(["runs"], list(data))
        self.assertIsInstance(data["runs"], list)
        return data["runs"]

    def listed(self):
        return [r["run_id"] for r in self.runs()]

    def test_the_limit_is_100(self):
        from app import server
        self.assertEqual(LIMIT, getattr(server, "RECENT_RUNS_LIMIT", None))

    def test_newest_first_with_ties_to_the_larger_run_id(self):
        _write_case(self.out, "run-b", _minimal("run-b", "2026-10-08T10:00:00+00:00"))
        _write_case(self.out, "run-a", _minimal("run-a", "2026-10-08T12:00:00+00:00"))
        _write_case(self.out, "run-c", _minimal("run-c", "2026-10-08T10:00:00+00:00"))
        _write_case(self.out, "run-z", _minimal("run-z", "2026-10-08T11:00:00Z"))
        _write_case(self.out, "run-0", _minimal("run-0", "not a time"))
        _write_case(self.out, "run-1", _minimal("run-1", "2026-10-08T13:00:00+08:00"))
        self.assertEqual(["run-a", "run-z", "run-c", "run-b", "run-1", "run-0"], self.listed())

    def test_at_most_100_runs_the_newest_kept(self):
        for count in (LIMIT, LIMIT + 1):
            with self.subTest(runs=count):
                shutil.rmtree(self.out)
                self.out.mkdir()
                names = ["run-%03d" % i for i in range(count)]
                for i, name in enumerate(names):
                    _write_case(self.out, name, _minimal(name, "2026-10-08T%02d:%02d:00+00:00" % (i // 60, i % 60)))
                listed = self.listed()
                self.assertEqual(min(count, LIMIT), len(listed))
                self.assertEqual(list(reversed(names))[:LIMIT], listed, "the oldest run is the one dropped")

    def test_folders_that_cannot_be_opened_by_id_are_skipped(self):
        good = _write_case(self.out, "good-1", _minimal("good-1"))
        (self.out / "plain-file").write_text(json.dumps(_minimal("plain-file")), encoding="utf-8")
        _write_case(self.out, "has space", _minimal("has space"))
        _write_case(self.out, "x" * 129, _minimal("x" * 129))
        _write_case(self.out, "pct%41", _minimal("pct%41"))
        outside = Path(tempfile.mkdtemp(prefix="w35-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        _write_case(outside, "escaped-1", _minimal("escaped-1"))
        os.symlink(outside / "escaped-1", self.out / "escaped-1")
        os.symlink(self.out, self.out / "loop-1")
        (self.out / "case_file.json").write_text(json.dumps(_minimal("loop-1")), encoding="utf-8")
        nested = self.out / "eval-1" / "run-n1"
        _write_case(nested.parent, "run-n1", _minimal("run-n1"))
        self.assertTrue((self.out / "escaped-1" / "case_file.json").is_file(), "fixture: the link resolves")
        self.assertEqual(["good-1"], self.listed())
        self.assertTrue(good.is_dir())

    def test_a_symlink_that_stays_inside_is_listed_under_its_own_name(self):
        store = _write_case(self.out, "store-1", _minimal("link-1"))
        os.symlink(store, self.out / "link-1")
        self.assertEqual(["link-1"], self.listed(), "the folder's own name is the id the case must carry")

    def test_the_whole_family_of_wrong_case_shapes_is_skipped(self):
        def without(name, key):
            case = _minimal(name)
            del case[key]
            return case

        shapes = {
            "s-array": "[]", "s-list": "[1, 2]", "s-empty": "{}", "s-string": '"x"', "s-number": "7",
            "s-null": "null", "s-invalid": "{not json", "s-blank": "",
            "s-no-run-id": without("s-no-run-id", "run_id"),
            "s-run-id-other": _minimal("someone-else"),
            "s-run-id-number": _minimal("x", run_id=5),
            "s-no-dispute": without("s-no-dispute", "dispute_id"),
            "s-dispute-empty": _minimal("s-dispute-empty", dispute_id=""),
            "s-dispute-number": _minimal("s-dispute-number", dispute_id=7),
            "s-no-resolution": without("s-no-resolution", "resolution"),
            "s-resolution-null": _minimal("s-resolution-null", resolution=None),
            "s-resolution-list": _minimal("s-resolution-list", resolution=["ruled"]),
            "s-resolution-empty": _minimal("s-resolution-empty", resolution={}),
            "s-outcome-number": _minimal("s-outcome-number", resolution={"outcome": 3}),
            "s-outcome-empty": _minimal("s-outcome-empty", resolution={"outcome": ""}),
        }
        for name, case in shapes.items():
            _write_case(self.out, name, case)
        (self.out / "s-dir-case" / "case_file.json").mkdir(parents=True)
        _write_case(self.out, "ok-1", _minimal("ok-1"))
        self.assertEqual(["ok-1"], self.listed())

    def test_missing_optional_fields_are_listed_as_empty_strings(self):
        case = _minimal("opt-1")
        case.pop("category")
        case["generated_at"] = 12
        _write_case(self.out, "opt-1", case)
        self.assertEqual([{"run_id": "opt-1", "dispute_id": "D-pt-1", "category": "", "outcome": "ruled",
                           "generated_at": "", "has_human_decision": False}], self.runs())

    def test_an_invalid_decision_file_is_not_a_decision(self):
        run_dir = _write_case(self.out, "dec-1", _minimal("dec-1", outcome="withheld"))
        (run_dir / "human_decision.json").write_text("[]", encoding="utf-8")
        runs = self.runs()
        self.assertEqual(["dec-1"], [r["run_id"] for r in runs])
        self.assertIs(False, runs[0]["has_human_decision"])

    def test_a_missing_output_folder_lists_nothing(self):
        shutil.rmtree(self.out)
        self.assertEqual([], self.listed())


# ================================================================== RUNS: the static replay


class ReplayRecordsTheRuns(unittest.TestCase):
    """The replay exporter records /api/review/runs, and every run it lists opens in the replay."""

    @classmethod
    def setUpClass(cls):
        from tests import w27_replay_support as w27
        cls.w27 = w27
        cls.export = w27.mock_export()

    def test_the_route_is_one_of_the_fixed_recorded_urls(self):
        from tools import export_replay
        self.assertIn("/api/review/runs", export_replay.FIXED_PATHS)

    def test_both_snapshots_record_their_runs_and_each_listed_run_opens(self):
        self.assertEqual(0, self.export["code"], self.export["stderr"][-2000:])
        out, fx = self.export["out"], self.export["fx"]
        for label in self.w27.LABELS:
            with self.subTest(label=label):
                body = self.w27.recorded(out, label, "GET /api/review/runs")
                self.assertIsInstance(body, dict)
                self.assertEqual(["runs"], list(body), "the recorded body is exactly {\"runs\": [...]}")
                self.assertIsInstance(body["runs"], list)
                listed = [r["run_id"] for r in body["runs"]]
                self.assertEqual(sorted(fx["runs"]), sorted(listed))
                keys = self.w27.manifest(out, label)
                for run_id in listed:
                    self.assertIn("GET /api/review/%s/case" % run_id, keys)
                decided = {r["run_id"]: r["has_human_decision"] for r in body["runs"]}
                self.assertEqual(label == "after", decided[fx["rd_run"]])


# ================================================================== C4 + the W35 stylesheet additions


W35_RULES = {
    "#runs-panel": {"margin-top": "28px", "padding": "20px 22px", "background": "var(--panel)",
                    "border": "1px solid var(--line)", "border-left": "4px solid var(--accent)",
                    "border-radius": "16px", "box-shadow": "var(--shadow)"},
    "#runs-panel .section-heading > div": {"min-width": "0"},
    "#runs-status": {"min-height": "20px", "margin": "0 0 12px", "color": "var(--muted)", "font-size": "13px"},
    ".runs-list": {"display": "grid", "gap": "8px", "max-height": "min(26rem, 70vh)", "margin": "0", "padding": "0",
                   "overflow-y": "auto", "list-style": "none"},
    ".runs-list > .run-row": {"display": "flex", "flex-wrap": "wrap", "gap": "12px", "align-items": "center",
                              "padding": "12px", "color": "var(--ink)", "background": "var(--panel)",
                              "border": "1px solid var(--line)"},
    ".run-row > span": {"flex": "1 1 auto", "min-width": "0", "max-width": "100%", "overflow-wrap": "anywhere"},
    ".run-row > .run-category": {"font-weight": "700"},
    ".run-row > .run-id": {"color": "var(--muted)", "font-family": "ui-monospace, sfmono-regular, menlo, consolas, monospace",
                           "font-size": "12px"},
    ".run-row > .run-open": {"flex": "0 0 auto", "min-height": "44px", "max-width": "100%", "padding": "8px 12px",
                             "color": "var(--ink)", "background": "var(--panel)", "border": "1px solid var(--line)",
                             "border-radius": "4px", "font-weight": "600"},
    ".run-row > .run-open:hover": {"background": "var(--canvas)", "border-color": "var(--muted)"},
    ".runs-list > .run-row.is-open": {"background": "var(--canvas)", "border-color": "var(--muted)"},
    ".run-open-status": {"flex": "1 0 100%", "margin": "0", "color": "var(--red)", "font-size": "12px"},
    ".run-open-status:empty": {"display": "none"},
    ".loader-hint": {"margin": "0 0 10px", "color": "var(--muted)", "font-size": "13px"},
    "#prompts-content details > .payload-json": {"margin-top": "10px", "padding": "12px", "background": "#182334",
                                                 "border": "1px solid #2f455f", "color": "#e7eef7"},
}
for _sel in (".run-row > .run-outcome", ".run-row > .run-generated", ".run-row > .run-decided"):
    W35_RULES[_sel] = W35_RULES[".run-row > .run-id"]


def _luminance(hex_colour):
    channels = [int(hex_colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class StylesheetAdditions(unittest.TestCase):
    """The W35 rules are the exception list the W15 console digest skips, so they are pinned exactly."""

    @classmethod
    def setUpClass(cls):
        from tests.test_w15_feedback import rules, stripped
        cls.found = {}
        for context, selectors, decls in rules(stripped((UI / "styles.css").read_text(encoding="utf-8"))):
            for selector in selectors:
                if not context and selector in W35_RULES:
                    cls.found.setdefault(selector, []).append(dict(decls))

    def test_the_w15_exception_list_is_exactly_the_w35_selectors(self):
        import tests.test_w15_feedback as w15
        listed = getattr(w15, "W35_CONSOLE_SELECTORS", None)
        self.assertIsNotNone(listed, "tests/test_w15_feedback.py names the W35 exception list")
        self.assertEqual(set(W35_RULES), set(listed))

    def test_each_w35_rule_appears_once_with_exactly_its_declarations(self):
        self.assertEqual(sorted(W35_RULES), sorted(self.found))
        for selector, expected in W35_RULES.items():
            with self.subTest(selector=selector):
                self.assertEqual([expected], self.found[selector])

    def test_the_prompt_full_text_is_at_least_7_to_1(self):
        self.assertIn("#prompts-content details > .payload-json", self.found)
        decls = self.found["#prompts-content details > .payload-json"][0]
        self.assertGreaterEqual(_contrast(decls["color"], decls["background"]), 7.0)


# ================================================================== real browser


def _browser_env():
    return os.environ.get("PUPPETEER_MODULE") and os.environ.get("BROWSER_EXECUTABLE")


def _run_node(script, args, env_extra, timeout=600):
    env = dict(os.environ)
    env.update(env_extra)
    result = subprocess.run([NODE, str(BROWSER_DIR / script)] + args, env=env, capture_output=True,
                            text=True, timeout=timeout)
    return result


@unittest.skipUnless(_browser_env(), "PUPPETEER_MODULE and BROWSER_EXECUTABLE are not set")
class RealBrowserConsole(unittest.TestCase):
    """tests/browser/w35_C.cjs against the real server with real mock runs."""

    def test_the_console_contract_holds_in_a_real_browser(self):
        server = Server()
        self.addCleanup(server.close)
        rd = server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        ns = server.file(trip_id="T-NS0202", category="no_show_charge", claim=None)
        decided = server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        status, _ = server.decide(decided["run_id"], decision_body("reject"))
        self.assertEqual(200, status, "fixture: decision")
        report = Path(tempfile.mkdtemp(prefix="w35-browser-")) / "report.json"
        self.addCleanup(shutil.rmtree, report.parent, True)
        expect = {"out": str(server.out), "queued": rd["run_id"], "ruled": ns["run_id"],
                  "decided": decided["run_id"], "hint": HINT, "label": LABEL, "noCase": NO_CASE_FILE,
                  "severalRuns": SEVERAL_RUNS, "caseFailed": CASE_FAILED, "runsUnavailable": RUNS_UNAVAILABLE}
        result = _run_node("w35_C.cjs", [server.base, str(report)], {"W35C_EXPECT": json.dumps(expect)})
        data = json.loads(report.read_text()) if report.is_file() else {}
        self.assertEqual(0, result.returncode, (data.get("error") or result.stderr)[-3000:])
        self.assertTrue(data.get("passed"), data.get("error"))


@unittest.skipUnless(_browser_env(), "PUPPETEER_MODULE and BROWSER_EXECUTABLE are not set")
class RealBrowserReplay(unittest.TestCase):
    """tests/browser/w35_C_replay.cjs against an exported replay served statically."""

    def test_every_listed_run_opens_in_the_replay(self):
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        from functools import partial
        from tests import w27_replay_support as w27

        export = w27.mock_export()
        self.assertEqual(0, export["code"], export["stderr"][-2000:])

        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(export["out"])))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        report = Path(tempfile.mkdtemp(prefix="w35-replay-")) / "report.json"
        self.addCleanup(shutil.rmtree, report.parent, True)
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        expect = {"runs": export["fx"]["runs"]}
        result = _run_node("w35_C_replay.cjs", [base, str(report)], {"W35C_REPLAY_EXPECT": json.dumps(expect)})
        data = json.loads(report.read_text()) if report.is_file() else {}
        self.assertEqual(0, result.returncode, (data.get("error") or result.stderr)[-3000:])
        self.assertTrue(data.get("passed"), data.get("error"))


if __name__ == "__main__":
    unittest.main()
