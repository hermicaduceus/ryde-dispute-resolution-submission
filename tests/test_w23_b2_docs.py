"""W23 B2 acceptance: architecture docs and status colour tokens."""
import re,unittest
from tests.w23_b2_support import REPO

class DocsAndColours(unittest.TestCase):
 def test_human_decision_docs_name_views_confirm_and_two_paths(self):
  text=(REPO/"docs/architecture.md").read_text();section=text.split("## Human decision",1)[1].split("\n## ",1)[0]
  for phrase in ("review queue","decision form","confirm screen","Overrides","/api/review/<run_id>/case","/api/review/<run_id>/payloads/<name>"):self.assertIn(phrase,section)
 def test_new_status_colours_use_existing_tokens(self):
  css=re.sub(r"/\*.*?\*/","",(REPO/"ui/styles.css").read_text(),flags=re.S)
  expected={".queue-safety":"var(--amber)",".confirm-warning":"var(--amber)","#decision-error":"var(--red)",".decision-result":"var(--green)"}
  for selector,token in expected.items():
   m=re.search(re.escape(selector)+r"\s*\{([^}]*)\}",css);self.assertIsNotNone(m,selector);self.assertIn(token,m.group(1))
  # No new colour tokens or hex values are needed for this feature.
  new_tail=css[css.find("#queue-panel"):css.find("@media (max-width: 760px)")]
  self.assertNotRegex(new_tail,r"#[0-9a-fA-F]{3,8}\b")

if __name__=="__main__":unittest.main()
