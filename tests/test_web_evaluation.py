from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

import ai_check
import web_evaluation as study


class WebEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.local_patch = patch.object(study, "LOCAL", self.folder)
        self.local_patch.start()
        self.lock = study.freeze(ai_check.DEFAULT_MODEL)
        image = self.folder / "image.png"
        Image.new("RGB", (70, 70), "red").save(image)
        self.case = dict(
            case_id="web_001", page="https://example.org/", scan_id="test",
            image_path=str(image), image_sha256=study.sha256(image.read_bytes()),
            alt="A red square", image_html='<img src="a.png" alt="A red square">',
            context_html="", nearby_text="", capture_mode="browser",
        )
        self.dataset = {"protocol": self.lock, "capture_mode": "browser", "cases": [self.case]}
        self.dataset["dataset_sha256"] = study.dataset_digest(self.dataset)

    def tearDown(self):
        self.local_patch.stop()
        self.temporary.cleanup()

    def labels(self, decision="pass", exposure=False):
        value = dict(
            dataset_sha256=self.dataset["dataset_sha256"], reviewer="external",
            relationship="External reviewer", automated_decisions_seen=exposure,
            sealed_at="2026-01-01T00:00:00+00:00",
            labels={"web_001": {"decision": decision, "note": "Reference evidence"}},
        )
        value["labels_sha256"] = study.fingerprint(value)
        return value

    def predictions(self, decision="pass"):
        return dict(
            dataset_sha256=self.dataset["dataset_sha256"], model=ai_check.DEFAULT_MODEL,
            records={"web_001": {
                "rules": "uncertain", "ai": {"decision": decision, "usage": {"input_tokens": 15, "output_tokens": 5}},
                "hybrid": decision, "elapsed_seconds": 0.2, "attempted_at": "2026-02-01T00:00:00+00:00",
            }},
        )

    def test_abstentions_reduce_recall_and_coverage(self):
        result = study.metrics([("issue", "issue"), ("issue", "uncertain"), ("pass", "uncertain"), ("pass", "pass"), ("uncertain", "issue")])
        self.assertEqual(result["precision"], 1)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["coverage"], 0.5)
        self.assertEqual(result["selective_accuracy"], 1)
        self.assertEqual(result["reference_uncertain"], 1)
        self.assertIsNone(study.metrics([])["precision"])

    def test_collection_logs_exclusions_and_keeps_predictions_out(self):
        tiny = self.folder / "tiny.png"
        Image.new("RGB", (5, 5), "blue").save(tiny)
        records = [
            {**self.case, "image_key": "tiny", "image_path": str(tiny), "capture_status": "captured", "visible": True},
            {**self.case, "image_key": "first", "capture_status": "captured", "visible": True, "ai_result": {"decision": "issue"}, "rule_result": "potential_issue"},
            {**self.case, "image_key": "duplicate", "capture_status": "captured", "visible": True},
        ]
        lock = deepcopy(self.lock)
        lock["sampling"] = {
            "target_images": 5, "images_per_site": 5, "scan_limit": 12,
            "sources": [{"url": "https://example.org/", "category": "test"}, {"url": "https://blocked.example/", "category": "test"}],
        }
        run = {"url": "https://example.org/", "images": records, "created_at": "2026-01-01", "scan_id": "test"}
        with patch.object(study, "ROOT", self.folder), patch.object(study, "freeze", return_value=lock), patch.object(study, "scan_in_worker", side_effect=[run, RuntimeError("blocked")]):
            study.collect("browser")
        dataset = study.read_json(self.folder / "dataset.json")
        self.assertFalse(dataset["target_met"])
        self.assertEqual(dataset["actual_count"], 1)
        self.assertNotIn("ai_result", dataset["cases"][0])
        self.assertNotIn("rule_result", dataset["cases"][0])
        self.assertEqual([x["reason"] for x in dataset["collection_log"][0]["excluded"]], ["small_image", "duplicate_bytes"])
        self.assertEqual(dataset["collection_log"][1]["status"], "capture_failed")

    def test_rule_silence_is_uncertain(self):
        self.assertEqual(study.rules_decision(self.case), "uncertain")
        self.assertEqual(study.rules_decision({**self.case, "alt": None}), "issue")

    def test_frozen_engine_and_dataset_changes_are_rejected(self):
        with patch.object(study, "engine_hashes", return_value={}):
            with self.assertRaisesRegex(ValueError, "frozen"):
                study.validate_dataset(self.dataset)
        altered = deepcopy(self.dataset)
        altered["cases"][0]["alt"] = "Something else"
        with self.assertRaisesRegex(ValueError, "Dataset contents changed"):
            study.validate_dataset(altered)
        Path(self.case["image_path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Captured image changed"):
            study.validate_dataset(self.dataset)

    def test_unsealed_or_changed_references_are_rejected(self):
        labels = self.labels()
        labels["labels"]["web_001"]["decision"] = "issue"
        with self.assertRaisesRegex(ValueError, "changed after sealing"):
            study.score(self.dataset, self.predictions(), labels)
        with self.assertRaisesRegex(ValueError, "seal"):
            study.score(self.dataset, self.predictions(), {"dataset_sha256": self.dataset["dataset_sha256"]})

    def test_missing_cases_and_wrong_capture_are_rejected(self):
        output = self.predictions()
        output["records"] = {}
        with self.assertRaisesRegex(ValueError, "Every dataset case"):
            study.score(self.dataset, output, self.labels())
        output["dataset_sha256"] = "another capture"
        with self.assertRaisesRegex(ValueError, "same capture"):
            study.score(self.dataset, output, self.labels())

    def test_assisted_or_late_reviews_are_not_called_independent(self):
        output = study.score(self.dataset, self.predictions(), self.labels(exposure=True))
        self.assertFalse(output["independent_review_claim_supported"])
        labels = self.labels()
        labels["sealed_at"] = "2026-03-01T00:00:00+00:00"
        labels["labels_sha256"] = study.fingerprint({k: v for k, v in labels.items() if k != "labels_sha256"})
        output = study.score(self.dataset, self.predictions(), labels)
        self.assertFalse(output["references_sealed_before_recorded_predictions"])
        self.assertEqual(output["all_ai_input_tokens"], 15)

    def test_model_failures_remain_unresolved_and_retry(self):
        output_path = self.folder / "predictions.json"
        with patch("ai_check.check_image", side_effect=RuntimeError("temporary")):
            output = study.predict(self.dataset, output_path, ai_check.DEFAULT_MODEL, client=object())
        self.assertIsNone(output["records"]["web_001"]["ai"])
        self.assertEqual(output["records"]["web_001"]["hybrid"], "uncertain")
        with patch("ai_check.check_image", return_value={"decision": "pass"}) as api:
            study.predict(self.dataset, output_path, ai_check.DEFAULT_MODEL, client=object())
            study.predict(self.dataset, output_path, ai_check.DEFAULT_MODEL, client=object())
        self.assertEqual(api.call_count, 1)

    def test_blind_labeler_saves_and_seals_without_reading_predictions(self):
        study.write_json(self.folder / "dataset.json", self.dataset)
        # Invalid model output deliberately exists; the labeler must never load it.
        (self.folder / "predictions.json").write_text("not valid JSON")
        app = AppTest.from_file(str(study.ROOT / "label_web_images.py"), default_timeout=20).run()
        app.text_input[0].set_value("reviewer1").run()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any("AI assessment" in x.value for x in app.markdown))
        app.radio[0].set_value("pass")
        next(b for b in app.button if b.label == "Save reference").click().run()
        self.assertEqual(len(app.exception), 0)
        next(x for x in app.selectbox if x.label == "Reviewer relationship").set_value("External reviewer").run()
        next(x for x in app.selectbox if x.label.startswith("Have you seen")).set_value("No").run()
        next(b for b in app.button if b.label == "Seal references").click().run()
        self.assertEqual(len(app.exception), 0)
        labels = study.read_json(self.folder / "labels" / "reviewer1.json")
        self.assertIn("sealed_at", labels)
        self.assertFalse(labels["automated_decisions_seen"])
        self.assertFalse(any(b.label == "Save reference" for b in app.button))


if __name__ == "__main__":
    unittest.main()
