"""Palette and markup contracts; these do not establish browser conformance."""
from html.parser import HTMLParser
from pathlib import Path
import re
import base64
import json
import unittest

ROOT = Path(__file__).resolve().parents[2]


def luminance(color):
    if len(color) == 4:
        color = '#' + ''.join(ch * 2 for ch in color[1:])
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    rgb = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * w for v, w in zip(rgb, (.2126, .7152, .0722)))


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = {}
        self.dialogs = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            if attrs['id'] in self.ids:
                raise ValueError('Duplicate id ' + attrs['id'])
            self.ids[attrs['id']] = attrs
        if tag == 'dialog':
            self.dialogs.append(attrs)


class DesignChecks(unittest.TestCase):
    def test_palette_text_contrast(self):
        css = (ROOT / 'pilot/static/theme.css').read_text()
        root = css.split(':root {', 1)[1].split('}', 1)[0]
        tokens = dict(re.findall(r'--([\w-]+):\s*(#[\da-f]{3,6});', root))
        for fg, bg in [('ink', 'paper'), ('onyx', 'white'), ('onyx', 'mint'), ('muted', 'white'), ('teal', 'white')]:
            with self.subTest(fg=fg, bg=bg):
                self.assertGreaterEqual(contrast(tokens[fg], tokens[bg]), 4.5)

    def test_dialog_names_and_form_errors(self):
        dom = Markup((ROOT / 'pilot/static/index.html').read_text())
        for dialog in dom.dialogs:
            self.assertIn(dialog['aria-labelledby'], dom.ids)
        self.assertEqual(dom.ids['create-error']['role'], 'alert')
        self.assertEqual(dom.ids['list-summary']['role'], 'status')
        self.assertIn(dom.ids['file']['aria-describedby'], dom.ids)

    def test_preview_is_offline_and_labeled(self):
        page = (ROOT / 'artifacts/policypilot-ui-preview.html').read_text()
        self.assertIn("connect-src 'none'", page)
        self.assertIn("form-action 'none'", page)
        self.assertIn('Offline preview', page)
        self.assertIn('window.fetch =', page)
        self.assertIn('Find text in case documents', page)
        self.assertIn('policypilot-login-preview.html', page)
        data = json.loads(re.search(r'<script type="application/json" id="sample-packets">(.*?)</script>', page)[1])
        sample = data['SYN-C003']
        admission = sample['result']['review_fields']['fields']['ADMISSION_DATE']
        self.assertEqual(admission['status'], 'conflicting')
        self.assertSetEqual({c['value'] for c in admission['candidates']}, {'2026-10-02', '2026-10-03'})
        for doc in sample['documents']:
            original = ROOT / 'data/synthetic/exemplars/SYN-C003' / doc['filename']
            self.assertEqual(base64.b64decode(sample['originals'][doc['id']]), original.read_bytes())
        for candidate in admission['candidates']:
            doc = next(d for d in sample['documents'] if d['id'] == candidate['document_id'])
            page_text = doc['pages'][candidate['page'] - 1]['text']
            self.assertEqual(page_text[candidate['start_offset']:candidate['end_offset']], candidate['source_text'])
        self.assertNotRegex(page, r'<script[^>]+src=')
        self.assertNotRegex(page, r'<link[^>]+href=')
        self.assertFalse((ROOT / 'pilot/static/ui_preview.js').exists())


if __name__ == '__main__':
    unittest.main()
