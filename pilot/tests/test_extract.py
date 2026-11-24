import unittest
from unittest.mock import patch
from pathlib import Path
from pilot.extract import extract_pdf,ExtractionError,run
import subprocess

class ExtractionTests(unittest.TestCase):
    @patch('pilot.extract.run')
    def test_reject_over_limit_before_render(self,mock):
        mock.return_value='Pages: 21\n'
        with self.assertRaises(ExtractionError):extract_pdf(Path('/tmp/example.pdf'))
        self.assertEqual(mock.call_count,1)
    @patch('pilot.extract.run')
    def test_native_page_does_not_call_ocr(self,mock):
        mock.side_effect=['Pages: 1\n','Policy schedule '+('verified text '*10)]
        pages=extract_pdf(Path('/tmp/example.pdf'))
        self.assertEqual(pages[0]['method'],'native_text')
        self.assertEqual(mock.call_count,2)
    @patch('pilot.extract.run')
    def test_scan_calls_renderer_then_ocr(self,mock):
        mock.side_effect=['Pages: 1\n','','','Recognized claim evidence']
        pages=extract_pdf(Path('/tmp/example.pdf'))
        self.assertEqual(pages[0]['method'],'ocr')
        self.assertTrue(pages[0]['needs_verification'])
        self.assertEqual(mock.call_args_list[2].args[0][0],'pdftoppm')
        self.assertEqual(mock.call_args_list[3].args[0][0],'tesseract')
    @patch('pilot.extract.run')
    def test_excessive_page_text_fails(self,mock):
        mock.side_effect=['Pages: 1\n','x'*18001]
        with self.assertRaises(ExtractionError):extract_pdf(Path('/tmp/example.pdf'))
    @patch('pilot.extract.subprocess.run')
    def test_timeout_becomes_safe_error(self,mock):
        mock.side_effect=subprocess.TimeoutExpired(['tool','sensitive-filename'],5)
        with self.assertRaises(ExtractionError) as error:run(['tool'])
        self.assertNotIn('sensitive',str(error.exception))

class ExtractionQualityTests(unittest.TestCase):
    @patch('pilot.extract.run')
    def test_zero_pages_rejected(self, mock):
        mock.return_value = 'Pages: 0\n'
        with self.assertRaises(ExtractionError):
            extract_pdf(Path('/tmp/example.pdf'))
        self.assertEqual(mock.call_count, 1)

    @patch('pilot.extract.run')
    def test_unicode_hindi_native_signal(self, mock):
        native = 'बीमा पॉलिसी दस्तावेज और दावा विवरण ' * 8
        mock.side_effect = ['Pages: 1\n', native]
        page = extract_pdf(Path('/tmp/example.pdf'))[0]
        self.assertEqual(page['method'], 'native_text')
        self.assertFalse(page['needs_verification'])
        self.assertEqual(page['quality_reasons'], [])
        self.assertEqual(page['parser_version'], 'poppler-tesseract-v2')
        self.assertEqual(page['parser']['quality_assessment'], 'heuristic')
        self.assertNotIn('native_text', page)
        self.assertEqual(mock.call_count, 2)

    @patch('pilot.extract.run')
    def test_corrupt_native_routes_to_separate_ocr(self, mock):
        import json
        cases = [
            ('Policy schedule ' * 10 + '\ufffd', 'native_replacement_characters'),
            ('Policy schedule ' * 10 + '\x00', 'native_control_characters'),
            ('(cid:123)' * 20, 'native_garbled_text'),
            ('\ue000' * 100, 'native_garbled_text'),
        ]
        for native, reason in cases:
            with self.subTest(reason=reason, native=native[:10]):
                mock.reset_mock()
                mock.side_effect = ['Pages: 1\n', native, '', 'Recognized claim evidence ' * 5]
                page = extract_pdf(Path('/tmp/example.pdf'))[0]
                self.assertEqual(page['method'], 'ocr')
                self.assertEqual(page['native_text'], native)
                self.assertEqual(page['text'], ('Recognized claim evidence ' * 5).strip())
                self.assertNotIn(native, page['text'])
                self.assertIn(reason, page['quality_reasons'])
                self.assertIn('ocr_used', page['quality_reasons'])
                self.assertTrue(page['needs_verification'])
                json.dumps(page)

    @patch('pilot.extract.run')
    def test_non_alphanumeric_characters_cannot_avoid_ocr(self, mock):
        mock.side_effect = ['Pages: 1\n', '_' * 100, '', 'x' * 49 + ' ' * 100]
        page = extract_pdf(Path('/tmp/example.pdf'))[0]
        self.assertIn('native_insufficient_alphanumeric', page['quality_reasons'])
        self.assertIn('ocr_insufficient_alphanumeric', page['quality_reasons'])
        self.assertTrue(page['needs_verification'])

    @patch('pilot.extract.run')
    def test_weak_ocr_has_explicit_quality_flags(self, mock):
        mock.side_effect = ['Pages: 1\n', '', '', '\ufffd\x01']
        page = extract_pdf(Path('/tmp/example.pdf'))[0]
        self.assertIn('ocr_insufficient_alphanumeric', page['quality_reasons'])
        self.assertIn('ocr_replacement_characters', page['quality_reasons'])
        self.assertIn('ocr_control_characters', page['quality_reasons'])
        self.assertEqual(page['native_text'], '')

    @patch('pilot.extract.run')
    def test_oversized_native_rejected_before_ocr_even_when_sparse(self, mock):
        mock.side_effect = ['Pages: 1\n', ' ' * 18001]
        with self.assertRaises(ExtractionError):
            extract_pdf(Path('/tmp/example.pdf'))
        self.assertEqual(mock.call_count, 2)

    @patch('pilot.extract.run')
    def test_oversized_ocr_rejected(self, mock):
        mock.side_effect = ['Pages: 1\n', '', '', 'x' * 18001]
        with self.assertRaises(ExtractionError):
            extract_pdf(Path('/tmp/example.pdf'))
        self.assertEqual(mock.call_count, 4)

    @patch('pilot.extract.run')
    def test_ocr_failure_propagates_safe_error_without_native_fallback(self, mock):
        mock.side_effect = ['Pages: 1\n', '', '', ExtractionError('Document parsing failed or exceeded processing limits')]
        with self.assertRaisesRegex(ExtractionError, 'Document parsing failed'):
            extract_pdf(Path('/tmp/example.pdf'))

    @patch('pilot.extract.run')
    def test_layout_whitespace_and_repeated_natural_text_are_not_corruption(self, mock):
        native = '\tPolicy schedule\n' + ('verified text ' * 10) + '\f'
        mock.side_effect = ['Pages: 1\n', native]
        page = extract_pdf(Path('/tmp/example.pdf'))[0]
        self.assertEqual(page['method'], 'native_text')
        self.assertEqual(page['quality_reasons'], [])

if __name__=='__main__':unittest.main()
