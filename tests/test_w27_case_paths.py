"""W27 exporter path guards on a case-insensitive disk (planner RED pins, 2026-10-07).

The fix-round confirmation review (glm-5.3) found that `_refuse_unsafe_paths` compares
`Path.resolve()` results, which keep the letters as typed. On macOS's default case-insensitive
APFS, `UI` and `ui` are one folder, so `--out <repo>/UI/x` passed the guard and wrote the replay
site into the real `ui/`; a case-changed spelling of an input folder passed the same way. These
tests pin that the guards compare the folders themselves, not their spelling.

Every test runs only where the disk really is case-insensitive (checked by probing the scratch
folder); on a case-sensitive disk `UI` and `ui` are different folders and nothing is at risk.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from tests import w27_replay_support as w27
from tests.test_w27_fix_round import _Base, _export


def _case_insensitive_disk() -> bool:
    with tempfile.TemporaryDirectory(prefix="w27-case-") as tmp:
        lower = Path(tmp) / "casecheck"
        lower.mkdir()
        return (Path(tmp) / "CASECHECK").exists()


CASE_INSENSITIVE = _case_insensitive_disk()


def _swapcase_name(path: Path) -> Path:
    """The same path with its last component's letters case-swapped."""
    swapped = path.name.swapcase()
    if swapped == path.name:
        raise AssertionError("test premise: %s has no letters to swap" % path)
    return path.parent / swapped


@unittest.skipUnless(CASE_INSENSITIVE, "only a case-insensitive disk folds UI onto ui")
class CaseVariantPaths(_Base):

    def _probe_name(self):
        return "w27-case-probe-%s" % uuid.uuid4().hex[:12]

    def test_out_inside_ui_spelled_in_capitals_is_refused(self):
        fx = w27.fixture()
        name = self._probe_name()
        real = w27.UI_DIR / name
        self.addCleanup(shutil.rmtree, str(real), True)
        ui_before = w27.tree(w27.UI_DIR)
        result = _export(fx, allow_mock=True, out=w27.REPO / "UI" / name / "site")
        result["out"] = real / "site"
        self.assertRefused(result)
        self.assertFalse(real.exists(), "nothing may be created inside ui/")
        self.assertEqual(w27.tree(w27.UI_DIR), ui_before)

    def test_out_inside_tools_replay_spelled_in_capitals_is_refused(self):
        fx = w27.fixture()
        replay = w27.REPO / "tools" / "replay"
        name = self._probe_name()
        real = replay / name
        self.addCleanup(shutil.rmtree, str(real), True)
        replay_before = w27.tree(replay)
        result = _export(fx, allow_mock=True, out=w27.REPO / "Tools" / "REPLAY" / name)
        result["out"] = real
        self.assertRefused(result)
        self.assertFalse(real.exists(), "nothing may be created inside tools/replay/")
        self.assertEqual(w27.tree(replay), replay_before)

    def test_out_inside_a_case_changed_spelling_of_before_is_refused(self):
        fx = w27.copy_fixture()
        trees = self.snapshot_trees(fx)
        out = _swapcase_name(Path(fx["before"])) / "site"
        result = _export(fx, allow_mock=True, out=out)
        result["out"] = Path(fx["before"]) / "site"
        self.assertRefused(result)
        self.assertFalse((Path(fx["before"]) / "site").exists())
        self.assertEqual(self.snapshot_trees(fx), trees)

    def test_out_inside_a_case_changed_spelling_of_after_is_refused(self):
        fx = w27.copy_fixture()
        trees = self.snapshot_trees(fx)
        out = _swapcase_name(Path(fx["after"])) / "nested" / "site"
        result = _export(fx, allow_mock=True, out=out)
        result["out"] = Path(fx["after"]) / "nested" / "site"
        self.assertRefused(result)
        self.assertFalse((Path(fx["after"]) / "nested").exists())
        self.assertEqual(self.snapshot_trees(fx), trees)

    def test_before_and_after_that_differ_only_in_case_are_refused(self):
        fx = w27.copy_fixture()
        trees = self.snapshot_trees(fx)
        result = _export(fx, allow_mock=True, before=fx["before"], after=_swapcase_name(Path(fx["before"])))
        self.assertRefused(result)
        self.assertEqual(self.snapshot_trees(fx), trees)

    def test_a_folder_beside_the_inputs_whose_name_differs_by_more_than_case_still_exports(self):
        # Control: the identity check must not refuse a real sibling.
        fx = w27.copy_fixture()
        trees = self.snapshot_trees(fx)
        out = Path(fx["root"]) / (Path(fx["before"]).name.upper() + "-SITE")
        result = _export(fx, allow_mock=True, out=out)
        self.assertExported(result)
        self.assertEqual(self.snapshot_trees(fx), trees)


if __name__ == "__main__":
    unittest.main()
