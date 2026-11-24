"""HTTP session boundaries; require the API dependencies, no live providers."""
import importlib.util
import os
import unittest
from unittest.mock import patch

AVAILABLE=all(importlib.util.find_spec(name) for name in ('fastapi','httpx','psycopg'))


@unittest.skipUnless(AVAILABLE,'Requires API dependencies')
class SessionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'DATABASE_URL':'postgresql://unused','PROXY_TOKEN':'t'*64,
                                     'APP_ORIGIN':'https://pilot.example.invalid'})
        self.env.start()
        self.addCleanup(self.env.stop)
        from pilot.api import app,config
        from fastapi.testclient import TestClient
        self.settings=patch.multiple(config,AUTH_MODE='session',PILOT_USER='reviewer',
                                    PILOT_PASSWORD_HASH='test-hash')
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.client=TestClient(app,base_url=config.APP_ORIGIN,follow_redirects=False)
        self.addCleanup(self.client.close)
        self.headers={'Origin':config.APP_ORIGIN}

    def test_home_redirects_and_download_requires_login(self):
        self.assertEqual(self.client.get('/').status_code,303)
        self.assertEqual(self.client.get('/api/cases/a/documents/b').status_code,401)
        self.assertEqual(self.client.get('/api/cases').status_code,401)

    def test_proxy_headers_cannot_bypass_session_mode(self):
        response=self.client.get('/api/cases',headers={'X-Proxy-Token':'t'*64,'X-Reviewer':'admin'})
        self.assertEqual(response.status_code,401)
        self.assertEqual(response.headers['cache-control'],'no-store')

    def test_login_page_is_public_but_workspace_html_is_protected(self):
        self.assertEqual(self.client.get('/login').status_code,200)
        self.assertEqual(self.client.get('/index.html').status_code,401)
        self.assertEqual(self.client.get('/login.html').status_code,401)

    def test_health_identifies_pdf_review_release_after_database_check(self):
        with patch('pilot.api.connect') as database:
            response = self.client.get('/healthz')
        database.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT 1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'deployment_mode': 'pdf-field-review'})

    def test_evidence_search_assets_require_workspace_authentication(self):
        for path, mime in (('/evidence-search.js', 'javascript'), ('/evidence-search.css', 'text/css')):
            self.assertEqual(self.client.get(path).status_code, 401)
            with patch('pilot.api.auth.current_user', return_value='reviewer'):
                response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(mime, response.headers['content-type'])
            self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_cross_origin_login_rejected(self):
        for headers in ({},{'Origin':'https://attacker.invalid'}):
            self.assertEqual(self.client.post('/api/auth/login',headers=headers,json={}).status_code,403)

    def test_successful_login_sets_host_only_secure_cookie(self):
        with patch('pilot.api.auth.login',return_value=('a'*43,None)):
            response=self.client.post('/api/auth/login',headers=self.headers,
                                      json={'username':'reviewer','password':'synthetic-password'})
        self.assertEqual(response.status_code,200)
        cookie=response.headers['set-cookie']
        for required in ('__Host-policypilot-session','HttpOnly','Secure','SameSite=strict','Path=/','Max-Age=28800'):
            self.assertIn(required,cookie)
        self.assertNotIn('Domain=',cookie)

    def test_login_body_limits_and_types(self):
        self.assertEqual(self.client.post('/api/auth/login',headers=self.headers,json={'username':1,'password':2}).status_code,422)
        self.assertEqual(self.client.post('/api/auth/login',headers=self.headers,json={'password':'x'*9000}).status_code,413)

    def test_logout_revokes_and_clears_cookie(self):
        self.client.cookies.set('__Host-policypilot-session','a'*43)
        with patch('pilot.api.auth.current_user',return_value='reviewer'),patch('pilot.api.auth.logout') as revoke:
            response=self.client.post('/api/auth/logout',headers=self.headers)
        self.assertEqual(response.status_code,204)
        revoke.assert_called_once()
        self.assertIn('Max-Age=0',response.headers['set-cookie'])
        self.assertEqual(response.content,b'')

    def test_review_identity_comes_from_session(self):
        with patch('pilot.api.auth.current_user',return_value='reviewer'):
            response=self.client.get('/api/auth/me',headers={'X-Reviewer':'forged-admin'})
        self.assertEqual(response.json()['username'],'reviewer')

    def test_cleanup_requires_operator(self):
        with patch('pilot.api.auth.current_user',return_value='reviewer'),patch.dict(os.environ,{'MODEL_OPERATOR':'different-user'}):
            self.assertEqual(self.client.post('/api/storage/cleanup',headers=self.headers).status_code,403)

    def test_retired_compute_routes_are_unavailable_after_authentication(self):
        with patch('pilot.api.auth.current_user',return_value='reviewer'):
            for path in ('/api/model/start','/api/model/stop'):
                self.assertIn(self.client.post(path,headers=self.headers).status_code,(404,405))
            self.assertEqual(self.client.get('/api/model/status').status_code,404)

    def test_forged_proxy_identity_cannot_control_model(self):
        response=self.client.post('/api/model/start',headers={**self.headers,'X-Reviewer':'reviewer','X-Proxy-Token':'t'*64})
        self.assertEqual(response.status_code,401)

    def test_model_controls_keep_origin_protection(self):
        self.assertEqual(self.client.post('/api/model/stop').status_code,403)

    def test_disconnected_model_status_has_no_network_side_effects(self):
        from pilot.api import config
        with patch('pilot.api.auth.current_user',return_value='reviewer'),patch.object(config,'INFERENCE_BACKEND','disabled'),patch('httpx.Client') as provider:
            result=self.client.get('/api/inference')
            self.assertEqual(result.status_code,200)
            self.assertFalse(result.json()['configured'])
            provider.assert_not_called()

    def test_disconnected_processing_does_not_queue_or_touch_the_database(self):
        from pilot.api import config
        with patch('pilot.api.auth.current_user',return_value='reviewer'),patch.object(config,'PROCESSING_ENABLED',False),patch('pilot.api.connect') as database:
            response=self.client.post('/api/cases/00000000-0000-0000-0000-000000000001/assess',headers=self.headers)
        self.assertEqual(response.status_code,503)
        database.assert_not_called()
