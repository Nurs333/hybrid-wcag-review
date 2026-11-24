from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

import ai_check
import external_benchmarks as bench
from web_evaluation import engine_hashes, fingerprint, read_json, sha256, write_json


class ExternalBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.local_patch = patch.object(bench, "LOCAL", self.folder)
        self.local_patch.start()
        path = self.folder / "image.png"
        Image.new("RGB", (60, 60), "red").save(path)
        self.case = {"case_id": "case1", "page": "source.html", "alt": "Red square", "scan_id": "external-test", "image_path": str(path), "image_sha256": sha256(path.read_bytes())}
        self.data = {"dataset": "assets", "cases": [self.case], "engine_sha256": engine_hashes(), "importer_sha256": sha256(Path(bench.__file__).read_bytes()), "model": ai_check.DEFAULT_MODEL}
        self.data["inputs_sha256"] = fingerprint(self.data)
        write_json(self.folder / "assets" / "inputs.json", self.data)
        refs = {"inputs_sha256": self.data["inputs_sha256"], "references": {"case1": {"decision": "pass"}}, "provenance": {"source": "test"}}
        refs["references_sha256"] = fingerprint(refs)
        write_json(self.folder / "assets" / "references.json", refs)

    def tearDown(self):
        self.local_patch.stop()
        self.temp.cleanup()

    def test_human_mapping_keeps_disagreement_and_midpoint_uncertain(self):
        self.assertEqual(bench.human_reference([1, 2, 4])["decision"], "issue")
        self.assertEqual(bench.human_reference([4, 5, 3])["decision"], "pass")
        self.assertEqual(bench.human_reference([1, 3, 5])["decision"], "uncertain")
        self.assertEqual(bench.human_reference([2, 4])["decision"], "uncertain")
        for scores in ([], [0], [6], ["5"]):
            with self.assertRaises(ValueError):
                bench.human_reference(scores)

    def test_inputs_do_not_contain_reference_or_teacher_outputs(self):
        row = {"page_url": "saved_page.html", "image_url": "https://example.org/a.png", "original_alt_text": "Red square", "html_context": "<p>A square</p>", "user_assessment": "1", "llm_judgment_1": "Failure", "llm_alt_text_1": "Teacher answer"}
        context = bench.assets_context(row)
        self.assertNotIn("user_assessment", context)
        self.assertNotIn("llm_judgment_1", context)
        task = bench.model_task({**self.case, **context, "expected": "issue", "ratings": [1], "rule_id": "secret"})
        self.assertNotIn("expected", task)
        self.assertNotIn("ratings", task)
        self.assertNotIn("rule_id", task)
        self.assertNotIn("Teacher answer", str(task))

    def test_act_titles_and_comments_cannot_reveal_expected_outcomes(self):
        markup = '<html><head><title>Failed Example 1</title></head><body><!-- Reference: failed --><img src="a.png" alt="Red square"></body></html>'
        task = bench.act_context(markup, "https://example.org/hash.html")
        self.assertNotIn("Failed Example", task["context_html"])
        self.assertNotIn("Reference: failed", task["context_html"])
        self.assertEqual(task["src"], "https://example.org/a.png")

    def test_unsupported_act_targets_are_not_silently_passed(self):
        for markup in ('<svg></svg>', '<img src="a"><img src="b">', '<img src="a" style="display:none">', '<img src="a" aria-hidden="true">', '<img src="a"><script>anything()</script>', '<html><head><style>img{display:none}</style></head><body><img src="a"></body></html>'):
            with self.assertRaises(ValueError):
                bench.act_context(markup, "https://example.org/")

    def test_case_grouping_does_not_count_rater_rows_as_images(self):
        rows = [{"page_url": "page", "image_url": "a", "original_alt_text": "x", "user_assessment": str(n)} for n in (1, 3, 5)]
        self.assertEqual(len(bench.assets_groups(rows)), 1)

    def test_no_ai_score_is_invented_before_requests(self):
        result = bench.score("assets")
        self.assertEqual(result["ai_status"], "not_run")
        self.assertIsNone(result["ai"])
        self.assertIsNone(result["hybrid"])
        self.assertEqual(result["rules"]["abstained"], 1)

    def test_prediction_never_opens_the_reference_file(self):
        (self.folder / "assets" / "references.json").write_text("invalid JSON: must not be read")
        with patch("ai_check.check_image", return_value={"decision": "pass"}) as api:
            bench.predict("assets", client=object())
            bench.predict("assets", client=object())
        self.assertEqual(api.call_count, 1)
        self.assertNotIn("image_sha256", api.call_args.args[0])

    def test_missing_or_changed_inputs_and_references_fail_closed(self):
        changed = deepcopy(self.data)
        changed["cases"][0]["alt"] = "Changed"
        with self.assertRaises(ValueError):
            bench.validate_inputs(changed)
        refs = read_json(self.folder / "assets" / "references.json")
        refs["references"]["case1"]["decision"] = "issue"
        write_json(self.folder / "assets" / "references.json", refs)
        with self.assertRaises(ValueError):
            bench.score("assets")

    def test_failed_predictions_are_unresolved_then_retried(self):
        with patch("ai_check.check_image", side_effect=RuntimeError("failed")):
            bench.predict("assets", client=object())
        result = bench.score("assets")
        self.assertEqual(result["api_errors"], 1)
        self.assertEqual(result["ai"]["abstained"], 1)
        with patch("ai_check.check_image", return_value={"decision": "pass"}):
            bench.predict("assets", client=object())
        self.assertEqual(bench.score("assets")["ai_status"], "complete")


if __name__ == "__main__":
    unittest.main()
