from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

import review_store
from website_checker import finish_record


class ReviewerAppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_patch = patch.object(review_store, 'DATABASE', self.root / 'reviews.db')
        self.database_patch.start()

    def tearDown(self):
        self.database_patch.stop()
        self.temporary.cleanup()

    def test_development_review_saves_and_counter_refreshes(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'review_app.py'), default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        app.radio[0].set_value('Development cases').run()
        self.assertEqual(len(app.exception), 0)
        page = app.selectbox[0].value
        app.radio[1].set_value('issue')
        next(button for button in app.button if button.label == 'Save review').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(review_store.benchmark_reviews()[page]['decision'], 'issue')
        self.assertTrue(any('1 of' in caption.value for caption in app.caption))

    def test_website_scan_and_human_override(self):
        image_path = self.root / 'capture.png'
        Image.new('RGB', (60, 60), 'red').save(image_path)
        record = dict(
            scan_id='ui-test', image_key='image_001', page='https://example.org/',
            image_path=str(image_path), src='https://example.org/a.png', alt=None,
            image_html='<img src="a.png">', context_html='<section><img src="a.png"></section>',
            nearby_text='', inside_control=False, capture_status='captured',
        )
        finish_record(record)
        run = dict(
            title='Example page', url='https://example.org/', requested_url='https://example.org/',
            scan_id='ui-test', images_found=1, images=[record], status='captured',
            run_path=str(self.root / 'scan.json'),
        )
        with patch('website_checker.scan_in_worker', return_value=run) as capture:
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'review_app.py'), default_timeout=20).run()
            app.text_input[0].set_value('https://example.org/')
            next(button for button in app.button if button.label == 'Scan webpage').click().run()
            self.assertEqual(len(app.exception), 0)
            capture.assert_called_once_with('https://example.org/', 12, 'browser')
            self.assertEqual(app.metric[0].value, '1')
            self.assertEqual(app.dataframe[0].value.iloc[0]['Assessment'], 'Rule flag')
            app.radio[1].set_value('uncertain')
            next(button for button in app.button if button.label == 'Save review').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(review_store.website_reviews('ui-test')['image_001']['decision'], 'uncertain')
            self.assertEqual(app.dataframe[0].value.iloc[0]['Human decision'], 'uncertain')


if __name__ == '__main__':
    unittest.main()
