"""Exercise the actual Streamlit script without model requests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from altreview import capture, demo, storage


class InterfaceTests(unittest.TestCase):
    def test_demo_inspection_filter_and_review_survive_reruns(self):
        with TemporaryDirectory() as tmp, patch.object(storage, 'RUNS', Path(tmp)):
            run = capture.scan(markup=demo.page(), capture_limit=2)
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
            self.assertFalse(at.exception)
            next(b for b in at.button if b.label == 'Try the built-in demo').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.metric), 4)
            next(r for r in at.radio if r.label == 'Show').set_value('Structural findings').run()
            self.assertFalse(at.exception)
            self.assertTrue(at.dataframe)
            next(r for r in at.radio if r.label == 'Your assessment').set_value('uncertain').run()
            next(b for b in at.button if b.label == 'Save my decision').click().run()
            self.assertFalse(at.exception)
            saved = next(storage.load(path) for path in storage.history() if any("review" in row for row in storage.load(path)["images"]))
            self.assertTrue(any('review' in r for r in saved['images']))


if __name__ == '__main__':
    unittest.main()
