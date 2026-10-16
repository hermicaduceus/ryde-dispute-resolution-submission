"""Presentation-form and calculation checks, not proof of live billing or model quality."""
import importlib.util
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "tools" / "deployment"
A = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def paragraphs(member):
    with zipfile.ZipFile(DEPLOY / "ryde-dispute-pitch.pptx") as z:
        # Fixed version-controlled Office part only, never uploaded/untrusted XML.
        doc = ET.fromstring(z.read(member))
    return ["".join(t.text or "" for t in p.findall(".//a:t", A)) for p in doc.findall(".//a:p", A)]


class PresentationAlignment(unittest.TestCase):
    def cost(self):
        path = DEPLOY / "cost_model.py"
        self.assertTrue(path.is_file(), "The reproducible planning calculation is missing")
        spec = importlib.util.spec_from_file_location("presentation_cost", path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_source_names_the_serving_roles(self):
        text = (DEPLOY / "slides.md").read_text()
        self.assertIn("Advocates: V4 Flash", text)
        self.assertIn("Judge: V4 Pro", text)
        self.assertNotIn("V4 Pro is the fallback", text)

    def test_diagram_names_the_serving_roles(self):
        text = (DEPLOY / "deploy-architecture.mmd").read_text()
        self.assertIn("Advocates: V4 Flash", text)
        self.assertIn("Judge: V4 Pro", text)
        self.assertNotIn("DeepSeek V4 Flash:<br/>Rider, Driver", text)

    def test_eval_is_dated_and_has_denominator_in_source(self):
        text = (DEPLOY / "slides.md").read_text()
        self.assertIn("17 of 18", text)
        self.assertIn("3 October 2026", text)
        self.assertIn("before the model switch", text)
        self.assertNotIn("17 labelled cases", text)

    def test_eval_is_dated_and_has_denominator_in_deck_and_notes(self):
        for member in ("ppt/slides/slide11.xml", "ppt/notesSlides/notesSlide11.xml"):
            text = " ".join(paragraphs(member))
            self.assertIn("17 of 18", text, member)
            self.assertIn("3 October 2026", text, member)
            self.assertNotIn("17 labelled cases", text)
            self.assertNotIn("V4 Pro is the fallback", text)

    def test_cost_is_a_budget_not_a_measured_bill(self):
        source = (DEPLOY / "slides.md").read_text()
        slide = " ".join(paragraphs("ppt/slides/slide6.xml"))
        for text in (source, slide):
            self.assertIn("S$175", text)
            self.assertIn("budget", text.lower())
            self.assertIn("not measured", text.lower())
        self.assertNotIn("then S$14 a month", source)
        self.assertNotIn("then S$14 a month", slide)

    def test_model_notes_do_not_claim_flash_only(self):
        for n in (5, 6, 8, 11, 13):
            text = " ".join(paragraphs("ppt/notesSlides/notesSlide%d.xml" % n))
            self.assertIn("Flash", text, n)
            self.assertIn("Pro", text, n)
            self.assertNotIn("Pro is the fallback", text)

    def test_legacy_scenario_is_explicitly_superseded(self):
        head = "\n".join((DEPLOY / "demo-video-script.md").read_text().splitlines()[:15])
        self.assertIn("Historical draft", head)
        self.assertIn("cost_model.py", head)
        self.assertIn("superseded", head)

    def test_embedded_forecast(self):
        result = self.cost().forecast()
        self.assertAlmostEqual(397200, result["manual_total_sgd"], places=2)
        self.assertAlmostEqual(249951, result["system_total_sgd"], places=2)
        self.assertAlmostEqual(147249, result["saving_sgd"], places=2)
        self.assertEqual(21, result["payback_month"])

    def test_hosted_forecast(self):
        result = self.cost().forecast(hosted=True)
        self.assertAlmostEqual(267892.6666667, result["system_total_sgd"], places=2)
        self.assertEqual(20, result["payback_month"])

    def test_zero_disputes_does_not_pay_back(self):
        result = self.cost().forecast(dispute_rate=0)
        self.assertEqual(0, result["manual_total_sgd"])
        self.assertEqual(120000, result["system_total_sgd"])
        self.assertIsNone(result["payback_month"])

    def test_budget_covers_documented_token_scenarios_only(self):
        mod = self.cost()
        refs = mod.token_references()
        self.assertAlmostEqual(46.1413333333, refs["all_flash_ga_peak_sgd"], places=4)
        self.assertAlmostEqual(171.912, refs["all_pro_unversioned_sgd"], places=4)
        self.assertGreaterEqual(mod.TOKEN_BUDGET_SGD, refs["max_reference_rates_sgd"])
        self.assertEqual(175, mod.TOKEN_BUDGET_SGD)

    def test_slide8_title_does_not_use_the_overflowing_phrase(self):
        text = paragraphs("ppt/slides/slide8.xml")
        self.assertIn("S$175/month token budget", text)
        self.assertNotIn("Budget S$175 a month for tokens", text)

    def test_slide5_accessible_description_names_both_model_roles(self):
        with zipfile.ZipFile(DEPLOY / "ryde-dispute-pitch.pptx") as deck:
            root = ET.fromstring(deck.read("ppt/slides/slide5.xml"))
        text = " ".join(node.attrib.get("descr", "") for node in root.iter())
        self.assertIn("V4 Flash for the two advocates", text)
        self.assertIn("V4 Pro for the Judge", text)
        self.assertNotIn("ADP running DeepSeek V4 Flash", text)

    def test_eval_slide_names_demo_labels_and_pre_switch(self):
        text = " ".join(paragraphs("ppt/slides/slide11.xml"))
        self.assertIn("demo labels matched", text)
        self.assertIn("Pre-switch result", text)
        self.assertIn("not real-world accuracy", text)

    def test_reference_pro_row_names_its_unversioned_price(self):
        text = paragraphs("ppt/slides/slide8.xml")
        self.assertIn("Unversioned V4 Pro, all tokens", text)
        self.assertNotIn("V4 Pro, all tokens", text)

    def test_slides_agree_on_the_revised_roi(self):
        for member in ("ppt/slides/slide7.xml", "ppt/slides/slide13.xml"):
            text = " ".join(paragraphs(member))
            self.assertIn("S$250k", text)
            self.assertNotIn("S$244k", text)
        text = " ".join(paragraphs("ppt/slides/slide7.xml"))
        self.assertIn("S$147k", text)
        self.assertIn("123%", text)


if __name__ == "__main__":
    unittest.main()
