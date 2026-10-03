"""W23 B2 acceptance: Overrides rendering."""
import unittest
from tests.w23_b2_support import base_routes,drive

class OverridesView(unittest.TestCase):
 def test_approved_count_groups_entries_and_order(self):
  groups=[{"category":"route_deviation","held_by":["ESC-4"],"decision":"change","action":"refund","count":2,"decisions":[{"run_id":"R1","dispute_id":"D1","reviewer":"Ana","reason":"First reason","action":"refund","amount_sgd":30,"proposed":{"action":"refund","amount_sgd":55.16},"decided_at":"t1"},{"run_id":"R2","dispute_id":"","reviewer":"Bo","reason":"Second reason","action":"refund","amount_sgd":42.25,"proposed":None,"decided_at":"t2"}]},{"category":"other","held_by":[],"decision":"reject","action":"no action","count":1,"decisions":[]}]
  o=drive(base_routes([],groups,3),[])
  self.assertEqual("Approved as proposed: 3",o["classes"]["overrides-approved"][0]["text"])
  texts=[x["text"] for x in o["classes"]["override-group"]]
  self.assertTrue(texts[0].startswith("Route deviation · ESC-4 · change to refund · 2 cases"));self.assertTrue(texts[1].startswith("Other · not recorded · reject to no action · 1 case"))
  entries=[x["text"] for x in o["classes"]["override-entry"]]
  self.assertIn("D1",entries[0]);self.assertIn("Ana",entries[0]);self.assertIn("SGD 30.00",entries[0]);self.assertIn("AI proposed SGD 55.16",entries[0]);self.assertIn("First reason",entries[0])
  self.assertIn("R2",entries[1]);self.assertIn("Bo",entries[1]);self.assertIn("SGD 42.25",entries[1]);self.assertIn("No AI proposal",entries[1]);self.assertIn("Second reason",entries[1])
 def test_model_failure_label_and_empty_state(self):
  g={"category":"no_show_charge","held_by":["model_failure"],"decision":"reject","action":"no action","count":1,"decisions":[]}
  o=drive(base_routes([],[g]),[]);self.assertIn("No-show charge · model failure · reject to no action · 1 case",o["classes"]["override-group"][0]["text"])
  o=drive(base_routes([],[],0),[]);self.assertEqual("No changed or rejected decisions yet.",o["ids"]["overrides-status"]["text"])

if __name__=="__main__":unittest.main()
