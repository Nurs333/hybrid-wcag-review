from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

import ai_check
from image_rules import apply_rules
import local_model
import local_benchmark
import external_benchmarks
import review_pipeline as pipeline
import review_store


class LocalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.path = self.folder / "image.png"
        Image.new("RGB", (60, 60), "red").save(self.path)
        self.record = dict(page="https://example.org/", image_key="image_001", scan_id="test", image_path=str(self.path), alt=None, image_html='<img src="red.png" title="Red square">', context_html="", nearby_text="", capture_status="captured", visible=True, inside_control=False)
        apply_rules(self.record)
        self.run = dict(scan_id="test", run_path=str(self.folder / "scan.json"), images=[self.record])

    def tearDown(self):
        self.temp.cleanup()

    def local_result(self, decision="pass", **changes):
        return dict(provider="local", model=local_model.MODEL_ID, assessment_key=pipeline.assessment_key(self.record), response_id="local_test", decision=decision, reason="Image naming evidence.", evidence=["A title names the image."], **changes)

    def test_flagged_images_are_eligible_but_hidden_and_failed_images_are_not(self):
        records = [self.record, dict(self.record, image_key="hidden", visible=False), dict(self.record, image_key="failed", capture_status="unavailable")]
        self.assertEqual(pipeline.pending_ai_records({"images": records}), [self.record])

    def test_local_run_never_calls_openai_even_when_a_key_exists(self):
        with patch("local_model.check_image", return_value=self.local_result()) as local, patch("ai_check.check_image", side_effect=AssertionError("No cloud requests")) as cloud, patch.dict("os.environ", {"OPENAI_API_KEY": "unused"}):
            pipeline.run_ai(self.run)
        local.assert_called_once()
        cloud.assert_not_called()
        self.assertEqual(self.record["ai_result"]["decision"], "pass")
        self.assertEqual(self.record["decision"], "uncertain")
        self.assertTrue(self.record["disagreement"])
        self.assertTrue(self.record["needs_human_review"])
        self.assertTrue(self.record["rule_flags"])

    def test_model_agreement_retains_rule_evidence(self):
        with patch("local_model.check_image", return_value=self.local_result("issue")):
            pipeline.run_ai(self.run)
        self.assertEqual(self.record["decision"], "issue")
        self.assertFalse(self.record["disagreement"])
        self.assertTrue(self.record["rule_flags"])

    def test_provider_switch_restores_each_cache_without_cross_reuse(self):
        local_result = self.local_result("issue")
        cloud_result = {**local_result, "provider": "openai", "model": ai_check.DEFAULT_MODEL, "response_id": "cloud_test", "assessment_key": ai_check.assessment_key(self.record)}
        with patch("local_model.check_image", return_value=local_result) as local, patch("ai_check.check_image", return_value=cloud_result) as cloud:
            pipeline.run_ai(self.run)
            pipeline.run_ai(self.run, provider="openai", client=object())
            pipeline.run_ai(self.run)
        self.assertEqual(local.call_count, 1)
        self.assertEqual(cloud.call_count, 1)
        self.assertEqual(len(self.record["model_results"]), 2)
        self.assertEqual(self.record["ai_result"]["provider"], "local")

    def test_parse_errors_never_become_pass(self):
        for raw in ('pass', '{"decision":"pass"}', 'The image does not pass.', '{"decision":"pass","reason":"ok","evidence":[]} trailing'):
            parsed, error = local_model.parse_output(raw)
            self.assertEqual(parsed["decision"], "uncertain")
            self.assertIsNotNone(error)
        parsed, error = local_model.parse_output('```json\n{"decision":"issue","reason":"Wrong scene","evidence":["A dog is visible"],"supporting_text":""}\n```')
        self.assertEqual(parsed["decision"], "issue")
        self.assertIsNone(error)

    def test_local_prompt_allowlist_and_explicit_truncation(self):
        task = dict(self.record, expected_label="pass", teacher_answer="Do not leak", context_html="x" * 30000, alt="x" * 20000)
        context = local_model.local_context(task)
        self.assertNotIn("expected_label", context)
        self.assertNotIn("teacher_answer", context)
        self.assertTrue(context["context_truncated"])
        self.assertLess(len(json.dumps(context)), local_model.CONTEXT_LIMIT + 100)
        self.assertNotEqual(local_model.assessment_key(task), local_model.assessment_key(self.record))

    def test_errors_do_not_fall_back_to_cloud_or_leave_a_stale_pass(self):
        with patch("local_model.check_image", side_effect=RuntimeError("Local load failed")), patch("ai_check.check_image", side_effect=AssertionError("No fallback")) as cloud:
            pipeline.run_ai(self.run)
        cloud.assert_not_called()
        self.assertEqual(self.record["decision"], "needs_review")
        self.assertNotIn("ai_result", self.record)
        self.assertIn("Local load failed", self.record["ai_error"])
        pipeline.select_backend(self.run)
        self.assertIn("Local load failed", self.record["ai_error"])
        self.assertEqual(self.record["source"], "Local error")
        with patch("local_model.check_image", return_value=self.local_result("issue")):
            pipeline.run_ai(self.run)
        self.assertEqual(self.record["decision"], "issue")
        self.assertNotIn("ai_error", self.record)

    def test_review_identity_changes_when_backend_or_conflict_changes(self):
        before = dict(self.record, decision="potential_issue")
        first = pipeline.review_assessment_id(before)
        pipeline.combine(before, self.local_result())
        self.assertNotEqual(first, pipeline.review_assessment_id(before))

    def test_local_benchmark_reads_no_references_during_prediction_and_keeps_cloud_files(self):
        folder = self.folder / "act"
        folder.mkdir()
        case = {**self.record, "case_id": "sample"}
        inputs = {"inputs_sha256": "fixture", "cases": [case]}
        (folder / "inputs.json").write_text(json.dumps(inputs))
        (folder / "predictions.json").write_text("cloud predictions stay intact")
        # No references file exists: prediction must not need one.
        task = external_benchmarks.model_task(case)
        result = {**self.local_result(), "assessment_key": local_model.assessment_key(task), "device": "cpu", "elapsed_seconds": 1}
        with patch.object(external_benchmarks, "LOCAL", self.folder), patch.object(external_benchmarks, "validate_inputs"), patch("local_model.check_image", return_value=result) as check:
            local_benchmark.predict("act")
            local_benchmark.predict("act")
            self.assertEqual(check.call_count, 1)
        self.assertEqual((folder / "predictions.json").read_text(), "cloud predictions stay intact")
        self.assertTrue((folder / "local_predictions.json").exists())

    def test_local_benchmark_reports_rule_conflict_as_abstention_and_rejects_stale_results(self):
        folder = self.folder / "act"
        folder.mkdir()
        case = {**self.record, "case_id": "sample"}
        (folder / "inputs.json").write_text(json.dumps({"inputs_sha256": "fixture", "cases": [case]}))
        refs = {"inputs_sha256": "fixture", "references": {"sample": {"decision": "pass"}}}
        refs["references_sha256"] = local_benchmark.fingerprint(refs)
        (folder / "references.json").write_text(json.dumps(refs))
        task = external_benchmarks.model_task(case)
        result = {**self.local_result(), "assessment_key": local_model.assessment_key(task), "device": "cpu", "elapsed_seconds": 1}
        predictions = {"inputs_sha256": "fixture", "records": {"sample": {"result": result}}}
        (folder / "local_predictions.json").write_text(json.dumps(predictions))
        with patch.object(external_benchmarks, "LOCAL", self.folder), patch.object(external_benchmarks, "validate_inputs"):
            report = local_benchmark.score("act")
            self.assertEqual(report["local_only"]["tn"], 1)
            self.assertEqual(report["raw_model"]["tn"], 1)
            self.assertEqual(report["combined_review_all"]["abstained_pass"], 1)
            self.assertEqual(report["combined_review_all"]["fp"], 0)
            result.update(model_decision="pass", decision="uncertain", validation_issues=["No quoted support"])
            (folder / "local_predictions.json").write_text(json.dumps(predictions))
            guarded = local_benchmark.score("act")
            self.assertEqual(guarded["raw_model"]["tn"], 1)
            self.assertEqual(guarded["local_only"]["abstained_pass"], 1)
            self.assertEqual(guarded["passes_requiring_review"], 1)
            predictions["records"]["sample"]["result"]["assessment_key"] = "stale"
            (folder / "local_predictions.json").write_text(json.dumps(predictions))
            with self.assertRaisesRegex(ValueError, "settings changed"):
                local_benchmark.score("act")

    def test_app_uses_local_by_default_and_displays_disagreement(self):
        run = {**self.run, "title": "Example", "url": "https://example.org/", "images_found": 1, "status": "captured"}
        with patch.object(review_store, "DATABASE", self.folder / "review.db"), patch("website_checker.scan_in_worker", return_value=run), patch("local_model.available", return_value=True), patch("local_model.check_image", return_value=self.local_result()), patch("ai_check.check_image", side_effect=AssertionError("Cloud must stay unused")):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "review_app.py"), default_timeout=20).run()
            app.text_input[0].set_value("https://example.org/")
            next(b for b in app.button if b.label == "Scan webpage").click().run()
            self.assertEqual(len(app.exception), 0)
            engine = next(s for s in app.selectbox if s.label == "Assessment engine")
            self.assertTrue(engine.value.startswith("Local"))
            next(b for b in app.button if b.label == "Run local model on 1 images").click().run()
            self.assertEqual(len(app.exception), 0)
            row = app.dataframe[0].value.iloc[0]
            self.assertEqual(row["Assessment"], "Uncertain")
            self.assertEqual(row["Model decision"], "pass")
            self.assertTrue(row["Disagreement"])
            app.radio[1].set_value("pass")
            next(b for b in app.button if b.label == "Save review").click().run()
            self.assertEqual(review_store.website_reviews("test")["image_001"]["decision"], "pass")


if __name__ == "__main__":
    unittest.main()
