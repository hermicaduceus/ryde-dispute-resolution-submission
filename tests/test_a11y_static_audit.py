"""The static accessibility audit must catch defects and pass the shipped pages."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("a11y", ROOT / "tools" / "a11y_static_audit.py")
a11y = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a11y)

GOOD = ('<!doctype html><html lang="en"><head><title>T</title>'
        '<meta name="viewport" content="width=device-width"></head><body><main><h1>x</h1>'
        '<label for="a">A</label><input id="a"><button>Go</button></main></body></html>')


def run(html):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "p.html"
        p.write_text(html, encoding="utf-8")
        return [f["message"] for f in a11y.audit(p) if f["level"] == "error"]


class A11yAuditTests(unittest.TestCase):
    def test_good_page_has_no_errors(self):
        self.assertEqual(run(GOOD), [])

    def test_missing_lang_title_viewport(self):
        errs = run("<html><body><main><h1>x</h1></main></body></html>")
        self.assertEqual(len(errs), 3)

    def test_unlabelled_input_and_missing_alt(self):
        errs = run(GOOD.replace('<label for="a">A</label>', "").replace(
            "<button", '<img src="x.png"><button'))
        self.assertTrue(any("no accessible name" in e for e in errs))
        self.assertTrue(any("no alt" in e for e in errs))

    def test_duplicate_ids(self):
        errs = run(GOOD.replace("<button>", '<button id="a">'))
        self.assertTrue(any("duplicate ids" in e for e in errs))

    def test_shipped_ui_has_no_errors(self):
        self.assertEqual(a11y.main(["--ui", str(ROOT / "ui")]), 0)


if __name__ == "__main__":
    unittest.main()
