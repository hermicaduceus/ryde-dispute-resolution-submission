"""Publication-cleanup contracts. These check exported bytes and scoped wording,
not original-source authenticity or current model accuracy. Source-hash preservation
and application isolation are additionally checked against the round's backup.
"""
import hashlib
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "evidence/conversation-history"
A = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Historical export fingerprints replaced by the approved 16 October metadata correction.
# These are immutable provenance, not live test or conversation totals.
PREVIOUS_EXPORT_DIGESTS = {'evidence/conversation-history/additions-20261014/manifest.json': {'w47-luna-20261014-061217': {'jsonl': 'c62b7d64cd9dd6835586c656315685362ebb595416db8b6536ea8bda8863e8b6'}},
 'evidence/conversation-history/archive/manifest.json': {'01a0c3eb-56e1-7abc-a2c8-713ccef4a768': {'jsonl': 'b074a5c858198f2025ca868e82bbe73c17cd880d263f75a83ec3f5bb5295b050'},
                                                         '01a0c3f6-f551-7a7f-ba09-b60642e751c8': {'jsonl': '73578bce912d103f210921e18d2211461a2961f7bd7b9cf27ccbe65b0241a682'},
                                                         '01a0c8d2-b44a-71f2-9574-31e427384a28': {'jsonl': '16bf4f3b511421e16c23159eccd7fa746c528dedd8c2ee8d6e0214895f2d572c'},
                                                         '01a0c935-adb8-7e46-a51f-e76d4bacb051': {'jsonl': '8161d7c326635cd550b33694f1a7caf5c53e29c125d556c9e794c2e12f72da8c'},
                                                         '01a0ce44-0226-7fd5-a7fe-3b9f24838445': {'jsonl': '1dc9b999bf4c56381ebd1194dc2a6b6cdead6a19dda23256ebfd942b5771f6fc'},
                                                         '01a0d424-896e-7577-9ea9-e315d0ada69b': {'jsonl': '02c0b00c8c4d3b51c12567e1c04266692f55b3bd74d19b1be2751d55a1f23e92'},
                                                         '01a0d644-dc5c-7534-81f3-f20b41ae6470': {'jsonl': '6111ebbd7d2fbb2989c00fdc96d96c38288b879a149a7a947a8b84ef2003fed7'},
                                                         '01a0d948-4d47-7e60-87e5-71f10ccc5ad8': {'jsonl': '2f92e00b2c8301274d269331e07afd4bf6050f0cb99cd08fe6b9abe1867fa82d'},
                                                         '01a0e075-d3d1-795e-9179-d6a679d9226e': {'jsonl': '007e412d7891c86e4412ae70cc63ce8de74a73b23610d10f0593e916411a6fe0',
                                                                                                  'markdown': 'dc397021f6283a1a412f19fd28f0fa98c5ceeb048e236643587ccce076a6ffd6'},
                                                         '01a0e134-e386-73b8-9bf1-af95691d6200': {'jsonl': 'aed2a9c4d25b6d465e4f61f5b6035cd1798381600da666a25f1de977beee1d1d'},
                                                         '01a0ed36-2d89-70d2-8f56-88cffc3ba068': {'jsonl': '6f9861fdbb195a9ab6ad8eba52640ed6704ffd594bc5d1a5a571f74cbd5c9ab5'},
                                                         '01a0edc2-1b50-77a0-a506-8533fe5d6ef0': {'jsonl': '864c86b781400500eb0337e60c0424b199c951e80d07bee751ce6c483924ed47'},
                                                         '01a0f68d-6f41-76bf-a42e-9345f533fd4f': {'jsonl': '5f1ff401acd82cd75006c659780fc57710bf26312126f82130ad6ef5c4bb455c'},
                                                         '01a0fd87-1c95-7230-b6ab-0bd62e09fdda': {'jsonl': 'd9f9f41f4c84d76c97b3842efe4402e43327ec9eac541a85d3c9e8f2b8d74d73'},
                                                         '01a10200-d46b-76d1-8331-63a8610091de': {'jsonl': '1889e51b92b5611d21cbbdda4ec8a2e9c118697ee2227b6585b7bc5e7b7f73da'},
                                                         '01a10450-619f-74fc-8ce6-db3741870da4': {'jsonl': 'f72d79de359ca657daf484ce8f543645a98d4f9a0e87fe7aaed1cd710cd1b36a'},
                                                         '01a104b4-a32f-7c21-ba9f-419fcfc42055': {'jsonl': '2604499ec3e4eb643a2d3580ccf4a6f84a950e1dc9a4e91ca006bbb81f3c75a2'},
                                                         '01a105bb-dd48-7568-9130-f9a5301603f2': {'jsonl': '8fcef290cdccb97a766ef2a2ed2b40bf1b8fd2a5c536432ffa94861f18bf64f7'},
                                                         '01a107f8-ac03-75f6-9708-64978c3eee95': {'jsonl': '269c808049ae99e77ac479001a37ada5bd47574e49258a4ccc0a24b195439953',
                                                                                                  'markdown': '3a34599d0d793f20806d177add99a65eda765ec9a6d111f540dc95c753023f8e'},
                                                         '01a10c31-9704-785d-8156-d67c9e5d05df': {'jsonl': '4d5670f87211fc674f4466bf98ced26e2679e64b3563af59ca53378de5aaef00'},
                                                         '01a10cb7-0733-7fe6-812b-5c09b63004f1': {'jsonl': 'bb1b9b83706e7f1772ed4a8ca438e5c9759ac6f85acb3cfe83e2891790233775'},
                                                         '01a10e9c-ec95-7344-8030-f1cc9b3780fe': {'jsonl': '076ac8ff52924c0c550869ccdb8749c4790d7cc679e53ba96131578777e308fc'},
                                                         '01a10f71-d931-7c73-92ec-d8ce3200ffdf': {'jsonl': '8032cc458c1d1de0f3b959432f2903691d37032ae1f794cf8e925b0161e7571a'},
                                                         '01a10fae-58a1-731f-9791-1d7b95608ec0': {'jsonl': 'dea53d94a233e2ea80d82200b8dcc6ec9bfaed83c630c84eea29c68dd7fac027'},
                                                         'w20-20261006-1918': {'jsonl': 'b307e7b73efc3ac10afa5b152fc326245c3b71275751134da07f44bca80be6ce'},
                                                         'w24-20261006-2359': {'jsonl': '0ce0ec82c6b7f55809127a83b4d4464fd16a1bec283b80e7bf1449ad41d89f95'}},
 'evidence/conversation-history/manifest.json': {'01a0c3f6-f551-7a7f-ba09-b60642e751c8': {'jsonl': '2f391291fe419e79a90bedc52d5f43e480457220b48e4386e7cd7f186a73f730'},
                                                 '01a0ce44-0226-7fd5-a7fe-3b9f24838445': {'jsonl': '1dc9b999bf4c56381ebd1194dc2a6b6cdead6a19dda23256ebfd942b5771f6fc'},
                                                 '01a0fd87-1c95-7230-b6ab-0bd62e09fdda': {'jsonl': 'd9f9f41f4c84d76c97b3842efe4402e43327ec9eac541a85d3c9e8f2b8d74d73'},
                                                 '01a10200-d46b-76d1-8331-63a8610091de': {'jsonl': '1889e51b92b5611d21cbbdda4ec8a2e9c118697ee2227b6585b7bc5e7b7f73da'},
                                                 '01a10450-619f-74fc-8ce6-db3741870da4': {'jsonl': '079c1e95ae74d61426d8150d7704e7e687065358cbc984d699d681e172ae4690'}}}


class PublishedEvidenceIntegrity(unittest.TestCase):
    def test_every_session_export_digest_matches_published_bytes(self):
        checked = 0
        failures = []
        for manifest in sorted(HISTORY.rglob("manifest.json")):
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for session in data["sessions"]:
                for kind in ("markdown", "jsonl"):
                    target = manifest.parent / session[kind]
                    checked += 1
                    if not target.is_file() or digest(target) != session[kind + "_sha256"]:
                        failures.append(str(target.relative_to(ROOT)))
        self.assertGreater(checked, 0)
        self.assertEqual([], failures, "published export digests do not match")

    def test_native_example_digest_matches_published_bytes(self):
        data = json.loads((HISTORY / "manifest.json").read_text(encoding="utf-8"))
        native = data["native_example"]
        self.assertEqual(native["sha256"], digest(HISTORY / native["file"]))

    def test_hash_refresh_discloses_original_vs_published_hashes(self):
        note = text("evidence/conversation-history/PUBLICATION-SUBSTITUTIONS.md")
        section = note.split("## Export checksums after publication", 1)[-1]
        self.assertIn("## Export checksums after publication", note)
        for token in ("source_sha256", "previously_recorded_export_sha256", "baseline_archive_source_sha256"):
            self.assertIn(token, section)
        self.assertIn("not the current", section)

    def test_previous_export_digests_are_retained_with_meaning(self):
        retained = []
        for manifest in HISTORY.rglob("manifest.json"):
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for session in data["sessions"]:
                for kind, old in session.get("previously_recorded_export_sha256", {}).items():
                    self.assertIn(kind, ("markdown", "jsonl"))
                    self.assertRegex(old, r"^[a-f0-9]{64}$")
                    self.assertNotEqual(old, session[kind + "_sha256"])
                    retained.append(old)
        self.assertGreater(len(retained), 0, "refresh must retain the previous digest values")
        for manifest_path, sessions in PREVIOUS_EXPORT_DIGESTS.items():
            data = json.loads((ROOT / manifest_path).read_text(encoding="utf-8"))
            by_id = {s["session_id"]: s for s in data["sessions"]}
            for session_id, expected in sessions.items():
                self.assertIn(session_id, by_id)
                self.assertEqual(expected, by_id[session_id].get("previously_recorded_export_sha256"),
                                 manifest_path + ":" + session_id)

    def test_october15_review_status_is_complete_and_scoped(self):
        for rel in ("evidence/conversation-history/README.md", "evidence/conversation-history/additions-20261015/README.md"):
            content = text(rel)
            if rel.endswith("conversation-history/README.md"):
                content = content.split("## Re-application round, 15 October", 1)[1].split("## Start here", 1)[0]
            else:
                content = content.split("## Reading index", 1)[0]
            self.assertNotIn("review pending", content.lower())
            self.assertIn("independently reviewed", content.lower())
            self.assertIn("PASS", content)
        data = json.loads((HISTORY / "additions-20261015/manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("PENDING", data["review_status"])
        self.assertEqual("PASS", data["independent_review"]["verdict"])
        self.assertEqual("3a278a81e5f3fb782e985446d553e0efa37d7546", data["independent_review"]["reviewed_revision"])
        for session in data["sessions"]:
            for key in ("content_review", "semantic_review_limit"):
                self.assertNotIn("pending", session[key].lower(), key + ":" + session["session_id"])
            self.assertIn("message bodies independently read", session["content_review"])
            self.assertIn("not exhaustively audited", session["content_review"])
            self.assertEqual("Pending", session.get("content_review_at_export"))
            self.assertNotIn("pending", session["semantic_review_limit"].lower())
            self.assertIn("independently reviewed at 3a278a8", session["semantic_review_limit"])
            self.assertEqual("Independent review pending. Historical tests are not rerun.",
                             session.get("semantic_review_limit_at_export"))


class PublicationDocTruth(unittest.TestCase):
    def test_old_filming_script_labels_itself_at_the_top(self):
        top = "\n".join(text("tools/deployment/demo-video-script.md").splitlines()[:12])
        self.assertIn("Historical draft", top)
        self.assertIn("not current filming instructions", top)
        self.assertIn("mock", top)

    def test_old_script_qa_does_not_claim_a_shipped_kill_switch(self):
        content = text("tools/deployment/demo-video-script.md")
        qa = content.split("Likely judge questions and short answers:", 1)[1]
        self.assertNotIn("a kill switch withholds every ruling", qa)
        self.assertIn("Before go-live", qa)
        self.assertIn("kill switch", qa)

    def test_slide_source_separates_existing_and_future_controls(self):
        content = text("tools/deployment/slides.md")
        section = content.split("## Slide 11", 1)[1].split("## Slide 12", 1)[0]
        self.assertNotIn("Controls from day one", section)
        built = section.split("**Built today:**", 1)[1].split("**Before go-live:**", 1)[0]
        future = section.split("**Before go-live:**", 1)[1].split("**Honest limits:**", 1)[0]
        self.assertIn("SGD 50", built)
        self.assertNotIn("kill switch", built.lower())
        self.assertNotIn("PII redaction", built)
        self.assertIn("kill switch", future)
        self.assertIn("personal data", future)
        self.assertEqual("add a kill switch that pauses every ruling and remove personal data before any AI call.",
                         future.strip().splitlines()[0])

    def test_actual_deck_qualifies_each_unbuilt_control(self):
        # This parses one fixed, version-controlled slide part, not an uploaded XML document.
        with zipfile.ZipFile(ROOT / "tools/deployment/ryde-dispute-pitch.pptx") as deck:
            slide = ET.fromstring(deck.read("ppt/slides/slide11.xml"))
        paragraphs = ["".join(node.text or "" for node in p.findall(".//a:t", A)) for p in slide.findall(".//a:p", A)]
        self.assertNotIn("CONTROLS FROM DAY ONE", paragraphs)
        self.assertIn("BUILT TODAY / BEFORE GO-LIVE", paragraphs)
        for term in ("kill switch", "personal data"):
            matches = [p for p in paragraphs if term in p.lower()]
            self.assertEqual(1, len(matches))
            expected = {"kill switch": "Before go-live: add a kill switch to pause rulings",
                        "personal data": "Before go-live: remove personal data before AI"}
            self.assertEqual(expected[term], matches[0])

    def test_builder_status_is_published_and_frozen(self):
        content = text("CODEBUDDY.md")
        self.assertIn("PUBLISHED, APPLICATION FROZEN", content.split("## What this project is", 1)[0])
        self.assertNotIn("application build freezes on", content)
        self.assertNotIn("BUILT, IN POLISH", content)

    def test_builder_deployment_matches_current_open_hosting(self):
        section = text("CODEBUDDY.md").split("- **Deployment:", 1)[1].split("## Non-negotiable", 1)[0]
        self.assertIn("open-access", section)
        self.assertIn("deploy/edgeone/README.md", section)
        self.assertNotIn("behind one shared judge password", section)

    def test_builder_layout_names_the_new_docs_deploy_and_evidence(self):
        section = text("CODEBUDDY.md").split("## Layout", 1)[1]
        for entry in ("deploy/edgeone/", "live-copy.md", "conversation-history/", "API-call"):
            self.assertIn(entry, section)
        for path in ("deploy/edgeone", "docs/live-copy.md", "evidence/conversation-history"):
            self.assertTrue((ROOT / path).is_dir() or (ROOT / path).is_file())
        instruction = next(line for line in text("CODEBUDDY.md").splitlines() if line.startswith("- **Run from this folder."))
        self.assertNotIn("hermes-workspace", instruction)
        self.assertIn("codebuddy", instruction)

    def test_dataset_verification_uses_a_pointer_not_a_mutable_test_count(self):
        section = text("docs/dataset.md").split("## Verification", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`tests/test_corpus.py`", section)
        self.assertNotRegex(section, r"test_corpus\.py`\s*\(\d+ tests\)")
        self.assertTrue(section.lstrip().startswith("`tests/test_corpus.py` is the guard on this artifact."),
                        "verification must point to the suite without adding a hard-coded count")


if __name__ == "__main__":
    unittest.main()
