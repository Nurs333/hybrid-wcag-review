import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from altreview import facts, network, storage, vision
from altreview.report import html_report


class ContractTests(unittest.TestCase):
    def test_unavailable_browser_evidence_never_passes(self):
        check = facts.name_check({"available": False}, "image_name")
        self.assertEqual(check["status"], "unknown")

    def test_unicode_whitespace_name_is_not_a_name(self):
        check = facts.name_check({"available": True, "role": "image", "name": " \t\n"}, "image_name")
        self.assertEqual(check["status"], "failed")

    def test_local_and_reserved_addresses_are_rejected(self):
        for url in ['http://localhost/x', 'http://127.0.0.1', 'http://[::1]', 'http://169.254.169.254', 'https://user:pass@example.com']:
            with self.subTest(url=url), self.assertRaises((ValueError, OSError)):
                network.public_url(url)

    def test_storage_rejects_traversal_identifiers(self):
        for identifier in ['..', '../outside', '/tmp/outside', '', 'invalid']:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                storage.run_directory({'id': identifier})

    def test_report_escapes_website_markup(self):
        run = storage.new_run('<script>alert(1)</script>', 0)
        row = facts.assess({'id': 'image_001', 'layout_visible': True, 'alt': '<script>bad()</script>',
            'markup': '<img onerror="bad()">', 'image_ax': {'available': False}, 'capture_status': 'unavailable'})
        run['images'] = [row]
        report = html_report(run)
        self.assertNotIn('<script>', report)
        self.assertIn('&lt;script&gt;', report)
        self.assertIn('Content quality: not_reviewed', report)

    def test_observer_cache_uses_pixels_and_model_not_alt(self):
        with TemporaryDirectory() as tmp, patch.object(storage, 'RUNS', Path(tmp)):
            path = Path(tmp) / 'capture.png'
            path.write_bytes(b'fake-test-image-bytes')
            result = {'scene': 'A square', 'visible_text': [], 'limitations': ''}
            with patch.object(vision, '_observe_local', return_value=(result, {'device': 'test'})) as model:
                first = vision.observe(path)
                second = vision.observe(path)
                self.assertEqual(model.call_count, 1)
                self.assertFalse(first['cache_hit'])
                self.assertTrue(second['cache_hit'])
                self.assertNotIn('decision', first)
                path.write_bytes(b'different-image')
                vision.observe(path)
                self.assertEqual(model.call_count, 2)

    def test_observer_error_does_not_cache_or_fall_back(self):
        with TemporaryDirectory() as tmp, patch.object(storage, 'RUNS', Path(tmp)):
            path = Path(tmp) / 'image.png'; path.write_bytes(b'picture')
            with patch.object(vision, '_observe_local', side_effect=RuntimeError('failure')), patch.object(vision, '_observe_openai') as paid:
                with self.assertRaises(RuntimeError):
                    vision.observe(path)
                paid.assert_not_called()
                self.assertFalse((Path(tmp)/'observations').exists())


if __name__ == '__main__':
    unittest.main()
