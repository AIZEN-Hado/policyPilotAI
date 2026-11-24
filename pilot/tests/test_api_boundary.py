"""Runs in the built app image; explicitly skipped when dependencies are unavailable."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

AVAILABLE=all(importlib.util.find_spec(name) for name in ('fastapi','httpx','psycopg'))

@unittest.skipUnless(AVAILABLE,'Requires the built pilot image / API dependencies')
class BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=patch.dict(os.environ,{'DATABASE_URL':'postgresql://unused','PROXY_TOKEN':'t'*64,'APP_ORIGIN':'https://pilot.example.invalid'})
        cls.env.start()
        from pilot.api import app,config
        from fastapi.testclient import TestClient
        cls.config=config
        cls.client=TestClient(app)
    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.env.stop()
    def setUp(self):
        self.headers={'X-Proxy-Token':self.config.PROXY_TOKEN,'Origin':self.config.APP_ORIGIN}
    def test_no_token_denied(self):
        self.assertEqual(self.client.get('/api/cases').status_code,401)
    def test_spoofed_reviewer_denied(self):
        self.assertEqual(self.client.get('/',headers={'X-Reviewer':'admin'}).status_code,401)
    def test_wrong_origin_denied(self):
        headers={**self.headers,'Origin':'https://untrusted.example.invalid'}
        self.assertEqual(self.client.post('/api/cases',json={},headers=headers).status_code,403)
    def test_missing_origin_denied(self):
        self.assertEqual(self.client.post('/api/cases',json={},headers={'X-Proxy-Token':self.config.PROXY_TOKEN}).status_code,403)
    def test_authenticated_static_has_security_headers(self):
        r=self.client.get('/',headers=self.headers)
        self.assertEqual(r.status_code,200)
        self.assertIn("script-src 'self'",r.headers['content-security-policy'])
        self.assertEqual(r.headers['cache-control'],'no-store')
    def test_invalid_case_id(self):
        self.assertEqual(self.client.get('/api/cases/not-a-uuid',headers=self.headers).status_code,422)
    def test_bad_pdf_removed_before_database(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(self.config,'DATA_DIR',Path(folder)):
            headers={**self.headers,'Content-Type':'application/pdf'}
            r=self.client.put('/api/cases/00000000-0000-0000-0000-000000000001/documents?kind=bill&filename=test.pdf',content=b'not a pdf',headers=headers)
            self.assertEqual(r.status_code,415)
            self.assertEqual(list(Path(folder).iterdir()),[])
    def test_oversized_pdf_removed(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(self.config,'DATA_DIR',Path(folder)),patch.object(self.config,'MAX_FILE',20):
            headers={**self.headers,'Content-Type':'application/pdf'}
            r=self.client.put('/api/cases/00000000-0000-0000-0000-000000000001/documents?kind=bill&filename=test.pdf',content=b'%PDF-'+b'0'*30,headers=headers)
            self.assertEqual(r.status_code,413)
            self.assertEqual(list(Path(folder).iterdir()),[])
