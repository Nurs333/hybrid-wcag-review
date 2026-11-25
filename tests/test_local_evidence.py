"""Regression patterns from a reported all-pass run; no live website calls."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from jsonschema import validate, ValidationError

from PIL import Image

import local_evidence as evidence
import local_model
import review_pipeline
from image_rules import apply_rules


class LocalEvidenceTests(unittest.TestCase):
    def task(self, alt="", **updates):
        return dict(alt=alt, image_html='<img src="pastry.jpg" alt="">', context_html='<figure><a href="/cakes"><img src="pastry.jpg" alt=""></a><figcaption>WHOLE CAKES</figcaption></figure>', nearby_text="WHOLE CAKES", inside_control=True, control_type="a", control_text="", control_aria_label=None, control_labelledby_text="", control_other_image_alt="", image_aria_label=None, image_labelledby_text="", **updates)

    def result(self, quote="WHOLE CAKES", decision="pass"):
        return dict(decision=decision, reason="A decorative pastry photograph.", evidence=["A cake is visible."], supporting_text=quote)

    def test_sibling_caption_does_not_name_an_image_only_link(self):
        context = evidence.local_context(self.task())
        self.assertEqual(context["control_names"]["text_inside_control"], "")
        result = evidence.validate_pass(self.result(), context)
        self.assertEqual(result["model_decision"], "pass")
        self.assertEqual(result["decision"], "uncertain")
        self.assertIn("no name evidence", result["reason"])

    def test_text_inside_link_is_retained_as_name_evidence(self):
        task = self.task()
        task.update(control_text="WHOLE CAKES", context_html='<a href="/cakes"><img src="pastry.jpg" alt="">WHOLE CAKES</a>')
        result = evidence.validate_pass(self.result(), evidence.local_context(task))
        self.assertEqual(result["decision"], "pass")

    def test_actual_aria_name_supports_empty_alt_link(self):
        task = self.task()
        task.update(control_aria_label="Browse cakes", nearby_text="")
        result = evidence.validate_pass(self.result("Browse cakes"), evidence.local_context(task))
        self.assertEqual(result["decision"], "pass")

    def test_linked_logo_can_pass_using_its_actual_alt(self):
        task = self.task()
        task.update(alt="Bakery & Café", image_html='<img src="logo.png" alt="Bakery &amp; Café">', context_html='<a href="/"><img src="logo.png" alt="Bakery &amp; Café"></a>', nearby_text="")
        result = evidence.validate_pass(self.result("Bakery & Café"), evidence.local_context(task))
        self.assertEqual(result["decision"], "pass")
        self.assertFalse(result["validation_issues"])

    def test_title_alternative_is_not_mistaken_for_missing_name(self):
        task = dict(alt=None, inside_control=False, image_html='<img src="mountain.jpg" title="Mountain at sunset">', nearby_text="")
        result = evidence.validate_pass(self.result("Mountain at sunset"), evidence.local_context(task))
        self.assertEqual(result["decision"], "pass")

    def test_filename_is_not_a_fabricated_scene_description(self):
        task = dict(alt="IMG_2021.jpg", image_html='<img src="a.jpg" alt="IMG_2021.jpg">', nearby_text="", inside_control=False)
        for quote in ("IMG_2021.jpg", "A drawing of a bakery interior"):
            result = evidence.validate_pass(self.result(quote), evidence.local_context(task))
            self.assertEqual(result["decision"], "uncertain")

    def test_empty_alt_timeline_cannot_pass_from_its_visual_content_alone(self):
        task = dict(alt="", image_html='<img src="timeline.png" alt="">', nearby_text="", inside_control=False)
        result = evidence.validate_pass(self.result("The image has years and street addresses"), evidence.local_context(task))
        self.assertEqual(result["decision"], "uncertain")

    def test_equivalent_real_text_can_support_empty_alt_nonfunctional_image(self):
        task = dict(alt="", nearby_text="Opening dates: 2010, 2015, and 2020.", inside_control=False)
        result = evidence.validate_pass(self.result("Opening dates: 2010, 2015, and 2020."), evidence.local_context(task))
        self.assertEqual(result["decision"], "pass")

    def test_presentation_semantics_allow_reviewed_decorative_pass(self):
        task = dict(alt="", role="presentation", inside_control=False)
        self.assertEqual(evidence.validate_pass(self.result(""), evidence.local_context(task))["decision"], "pass")

    def test_compaction_removes_tracking_and_preserves_trailing_caption(self):
        task = self.task()
        noise = "https://cdn.example/" + "x" * 2000
        task.update(image_html=f'<img src="pastry.jpg" alt="" srcset="{noise}" data-tracking="private">', context_html=f'<figure><a href="/cakes"><img src="pastry.jpg" alt="" srcset="{noise}" style="width:900px"></a><figcaption>WHOLE CAKES</figcaption><svg><style>noise</style><path d="noise"/></svg></figure>')
        context = evidence.local_context(task)
        self.assertIn("WHOLE CAKES</figcaption>", context["context_html"])
        self.assertNotIn("srcset", context["image_html"])
        self.assertNotIn("cdn.example", context["context_html"])
        self.assertNotIn("data-tracking", context["image_html"])
        self.assertFalse(context["context_truncated"])
        self.assertLess(len(json.dumps(context)), 1500)

    def test_other_image_link_title_is_not_used_for_ambiguous_target(self):
        task = dict(alt="", image_html='<img src="target.jpg" alt="">', context_html='<a title="Other"><img src="other.jpg"></a><img src="unrelated.jpg">', inside_control=True, control_type="a")
        context = evidence.local_context(task)
        self.assertEqual(context["control_names"]["title"], "")

    def test_nonpass_is_not_changed_into_issue_or_pass(self):
        for decision in ("issue", "uncertain"):
            result = evidence.validate_pass(self.result("", decision), evidence.local_context(self.task()))
            self.assertEqual(result["decision"], decision)

    def test_guarded_model_pass_still_surfaces_rule_disagreement(self):
        task = apply_rules(self.task())
        result = evidence.validate_pass(self.result(), evidence.local_context(task))
        review_pipeline.combine(task, result)
        self.assertTrue(task["disagreement"])
        self.assertEqual(task["decision"], "uncertain")

    def test_cache_changes_when_control_naming_changes(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "image.png"
            Image.new("RGB", (24, 24), "red").save(path)
            task = self.task()
            task.update(image_path=str(path), scan_id="test")
            previous = local_model.assessment_key(task)
            task["control_aria_label"] = "Browse cakes"
            self.assertNotEqual(previous, local_model.assessment_key(task))

    def test_decoder_cannot_invent_a_supporting_quote(self):
        context = evidence.local_context(dict(alt="Bakery & Café", nearby_text="", inside_control=True, control_type="a"))
        schema = local_model.output_schema(context)
        validate(self.result("Bakery & Café"), schema)
        with self.assertRaises(ValidationError):
            validate(self.result("A line drawing of a bakery"), schema)

    def test_filename_is_not_a_decoder_quote_choice(self):
        context = evidence.local_context(dict(alt="IMG_1234.jpg", nearby_text="", inside_control=False))
        self.assertEqual(evidence.supporting_choices(context), [""])


if __name__ == "__main__":
    unittest.main()
