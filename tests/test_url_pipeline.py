import base64
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

import ai_check
from ai_check import AccessibilityResult, assessment_key, check_image
from image_rules import apply_rules
import review_store
import website_checker as scanner


class FakeResponses:
    def __init__(self, fail_first=False):
        self.calls = []
        self.fail_first = fail_first

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError('Simulated API interruption')
        return SimpleNamespace(
            output_parsed=AccessibilityResult(decision='pass', reason='Equivalent text exists.', evidence=['Text names the image.']),
            model=kwargs['model'], response_id='unused',
            id=f'response-{len(self.calls)}', usage=None,
        )


class URLPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.png = self.root / 'image.png'
        Image.new('RGBA', (30, 30), (200, 20, 30, 100)).save(self.png)
        self.patches = [
            patch.object(scanner, 'PROJECT', self.root),
            patch.object(ai_check, 'PROJECT', self.root),
            patch.object(review_store, 'DATABASE', self.root / 'reviews.db'),
        ]
        for item in self.patches:
            item.start()
        self.record = dict(
            page='https://example.org/', image_key='image_001', scan_id='test',
            image_path='image.png', alt='Red square.', image_html='<img alt="Red square.">',
            context_html='<figure>Red square.</figure>', control_type=None,
            control_text='', control_aria_label=None, inside_control=False,
            capture_status='captured', src='https://example.org/image.png',
        )
        apply_rules(self.record)
        scanner.finish_record(self.record)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def test_empty_and_missing_alt_stay_distinct(self):
        _, records, total = scanner.extract_html_records('<img src="a.png"><img src="b.png" alt="">', 'https://example.org/path/', 5)
        self.assertEqual(total, 2)
        self.assertIsNone(records[0]['alt'])
        self.assertEqual(records[1]['alt'], '')
        self.assertEqual(records[0]['src'], 'https://example.org/path/a.png')

    def test_base_and_lazy_source_resolution_and_limit(self):
        markup = '<base href="/assets/"><img src="tiny.png" data-src="full.jpg"><img src="second.png">'
        _, records, total = scanner.extract_html_records(markup, 'https://example.org/blog/', 1)
        self.assertEqual(total, 2)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['src'], 'https://example.org/assets/full.jpg')

    def test_labelledby_outside_the_image_container(self):
        markup = '<span id="name">Book a room</span><section><button aria-labelledby="name"><img src="a.png" alt=""></button></section>'
        _, records, _ = scanner.extract_html_records(markup, 'https://example.org/', 5)
        self.assertEqual(records[0]['control_labelledby_text'], 'Book a room')
        self.assertEqual(apply_rules(records[0])['rule_result'], 'needs_review')

    def test_other_image_can_name_a_control(self):
        markup = '<a href="/home"><img src="a.png" alt=""><img src="b.png" alt="Home"></a>'
        _, records, _ = scanner.extract_html_records(markup, 'https://example.org/', 5)
        self.assertEqual(apply_rules(records[0])['rule_result'], 'needs_review')

    def test_unnamed_image_control_is_flagged(self):
        record = dict(self.record, alt='', inside_control=True)
        self.assertEqual(apply_rules(record)['rule_result'], 'potential_issue')

    def test_hidden_image_needs_contextual_judgment(self):
        record = dict(self.record, alt=None, aria_hidden=True)
        self.assertEqual(apply_rules(record)['rule_result'], 'needs_review')

    def test_image_labels_avoid_missing_alt_false_alarm(self):
        record = dict(self.record, alt=None, image_aria_label='A red square')
        self.assertEqual(apply_rules(record)['rule_result'], 'needs_review')

    def test_context_truncation_is_explicit(self):
        _, records, _ = scanner.extract_html_records('<section><img src="a.png">' + 'x' * 25000 + '</section>', 'https://example.org/', 1)
        self.assertTrue(records[0]['context_truncated'])
        self.assertEqual(len(records[0]['context_html']), scanner.CONTEXT_LIMIT)

    def test_capture_preserves_transparency(self):
        data = base64.b64encode(self.png.read_bytes()).decode()
        target = self.root / 'capture.png'
        scanner.capture_source_image({'src': 'data:image/png;base64,' + data}, target)
        with Image.open(target) as image:
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.getpixel((0, 0))[3], 100)

    def test_url_inputs(self):
        self.assertEqual(scanner.validate_url('example.org'), 'https://example.org')
        for url in ['file:///etc/passwd', 'javascript:alert(1)', 'https://a:b@example.org', 'http://127.0.0.1', 'http://localhost', 'http://[::1]']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                scanner.validate_url(url)

    def test_cache_changes_with_image_context_model_and_prompt(self):
        initial = assessment_key(self.record)
        self.assertNotEqual(initial, assessment_key(dict(self.record, alt='Blue square.')))
        self.assertNotEqual(initial, assessment_key(self.record, model='another-model'))
        with patch.object(ai_check, 'INSTRUCTIONS', 'A revised prompt'):
            self.assertNotEqual(initial, assessment_key(self.record))
        Image.new('RGB', (30, 30), 'blue').save(self.png)
        self.assertNotEqual(initial, assessment_key(self.record))

    def test_actual_image_bytes_are_sent_without_reference_labels(self):
        responses = FakeResponses()
        result = check_image(dict(self.record, expected_label='issue', rationale='Do not leak'), client=SimpleNamespace(responses=responses))
        request = responses.calls[0]
        user_content = request['input'][1]['content']
        self.assertTrue(user_content[1]['image_url'].startswith('data:image/png;base64,'))
        self.assertNotIn('expected_label', user_content[0]['text'])
        self.assertNotIn('rationale', user_content[0]['text'])
        self.assertEqual(result['decision'], 'pass')

    def test_partial_api_failure_retries_only_failed_record(self):
        second = dict(self.record, image_key='image_002')
        run = dict(scan_id='test', run_path=str(self.root / 'scan.json'), images=[dict(self.record), second])
        responses = FakeResponses(fail_first=True)
        client = SimpleNamespace(responses=responses)
        scanner.run_ai(run, client=client)
        self.assertEqual(run['images'][0]['decision'], 'needs_review')
        self.assertEqual(run['images'][1]['decision'], 'pass')
        scanner.run_ai(run, client=client)
        self.assertEqual(len(responses.calls), 3)
        scanner.run_ai(run, client=client)
        self.assertEqual(len(responses.calls), 3)
        checkpoint = json.loads((self.root / 'scan.json').read_text())
        self.assertEqual(checkpoint['images'][0]['decision'], 'pass')

    def test_missing_capture_does_not_block_later_images(self):
        missing = dict(self.record, image_path='missing.png')
        run = dict(run_path=str(self.root / 'scan.json'), images=[missing, dict(self.record)])
        responses = FakeResponses()
        scanner.run_ai(run, client=SimpleNamespace(responses=responses))
        self.assertEqual(missing['decision'], 'needs_review')
        self.assertEqual(run['images'][1]['decision'], 'pass')

    def test_reviews_are_separate_per_scan_and_can_be_updated(self):
        review_store.initialize()
        review_store.save_website_review('first', 'image_001', 'issue', '', 'r1')
        review_store.save_website_review('second', 'image_001', 'pass', '', 'r2')
        review_store.save_website_review('first', 'image_001', 'uncertain', 'Need context', 'r3')
        self.assertEqual(review_store.website_reviews('first')['image_001']['decision'], 'uncertain')
        self.assertEqual(review_store.website_reviews('second')['image_001']['decision'], 'pass')


if __name__ == '__main__':
    unittest.main()
