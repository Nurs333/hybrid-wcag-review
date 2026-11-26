"""Real Chromium tests of computed names, including CSS and ARIA references."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from altreview import capture, storage
from altreview.demo import page


class BrowserEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.override = patch.object(storage, "RUNS", Path(cls.temp.name))
        cls.override.start()
        cls.scan_result = capture.scan(markup=page(), capture_limit=2)

    @classmethod
    def tearDownClass(cls):
        cls.override.stop()
        cls.temp.cleanup()

    def target(self, identifier):
        return next(row for row in self.scan_result["images"] if f'id="{identifier}"' in row.get("markup", ""))

    def test_missing_name_fails_browser_check(self):
        row = self.target("missing")
        self.assertTrue(row["image_ax"]["available"])
        self.assertEqual(row["checks"][0]["status"], "failed")

    def test_title_names_image_without_alt(self):
        row = self.target("title-name")
        self.assertEqual(row["image_ax"]["name"], "Mountain illustration")
        self.assertFalse(row["findings"])

    def test_sibling_caption_does_not_name_the_link(self):
        row = self.target("unnamed-link")
        self.assertEqual(row["caption"], "Photo gallery")
        self.assertEqual(row["control_ax"]["name"], "")
        self.assertTrue(any(f["check"] == "control_name" for f in row["findings"]))

    def test_text_inside_link_is_its_computed_name(self):
        row = self.target("named-link")
        self.assertEqual(row["control_ax"]["name"], "Open the photo gallery")
        self.assertFalse(row["findings"])

    def test_empty_alt_is_not_automatically_an_issue(self):
        row = self.target("decorative")
        self.assertFalse(row["findings"])
        self.assertEqual(row["content_review"]["status"], "not_reviewed")

    def test_filename_has_name_but_still_needs_content_review(self):
        row = self.target("filename")
        self.assertEqual(row["checks"][0]["status"], "passed")
        self.assertFalse(row["findings"])
        self.assertEqual(row["triage"], "review")

    def test_hidden_copy_never_consumes_the_capture_budget(self):
        self.assertEqual(self.target("hidden")["capture_status"], "hidden")
        self.assertEqual(sum(r["capture_status"] == "captured" for r in self.scan_result["images"]), 2)
        self.assertEqual(len(self.scan_result["images"]), self.scan_result["discovered"])
        self.assertTrue(all("checks" in r for r in self.scan_result["images"]))

    def test_css_generated_and_hidden_reference_names(self):
        markup = '''<style>a::before{content:"Open catalogue"}</style>
        <a href="#x"><img alt="" src="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20'/>"></a>
        <span id="name" hidden>Hidden referenced label</span><div role="img" aria-labelledby="name" style="width:20px;height:20px"></div>'''
        run = capture.scan(markup=markup, capture_limit=0)
        self.assertEqual(run["images"][0]["control_ax"]["name"], "Open catalogue")
        self.assertEqual(run["images"][1]["image_ax"]["name"], "Hidden referenced label")
        self.assertTrue(all(not r["findings"] for r in run["images"]))


if __name__ == "__main__":
    unittest.main()
