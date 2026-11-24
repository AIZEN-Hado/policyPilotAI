"""Direct API regression checks without a network or provider worker."""
import importlib.util
import os
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock,patch

AVAILABLE=all(importlib.util.find_spec(name) for name in ('fastapi','httpx','psycopg'))


@unittest.skipUnless(AVAILABLE,'Requires API dependencies')
class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'DATABASE_URL':'postgresql://unused','PROXY_TOKEN':'t'*64,
            'APP_ORIGIN':'https://pilot.example.invalid'})
        self.env.start();self.addCleanup(self.env.stop)
        from pilot import api
        self.api=api
        self.config=patch.multiple(api.config,INFERENCE_BACKEND='disabled',PROCESSING_ENABLED=False)
        self.config.start();self.addCleanup(self.config.stop)

    def test_removed_control_and_submission_routes_are_absent(self):
        paths={getattr(route,'path',None) for route in self.api.app.routes}
        for path in ('/api/model/start','/api/model/stop','/api/model/status'):
            self.assertNotIn(path,paths)
        routes=[route for route in self.api.app.routes if getattr(route,'path',None)=='/api/cases/{cid}/messages']
        self.assertEqual(len(routes),1);self.assertEqual(routes[0].methods,{'GET'})

    def test_disconnected_status_and_generation_never_make_a_network_request(self):
        from pilot.inference import generate
        with patch('httpx.Client') as network:
            state=self.api.inference_status()
            with self.assertRaises(RuntimeError):generate('system','synthetic',{})
        self.assertFalse(state['configured']);self.assertFalse(state['processing_enabled'])
        network.assert_not_called()

    def test_disabled_assessment_has_no_database_or_provider_effect(self):
        from fastapi import HTTPException
        with patch.object(self.api,'connect') as database:
            with self.assertRaises(HTTPException) as caught:self.api.assess(uuid.uuid4(),None)
        self.assertEqual(caught.exception.status_code,503);database.assert_not_called()

    def test_cleanup_role_still_uses_the_session_identity(self):
        from fastapi import HTTPException
        with patch.object(self.api.config,'AUTH_MODE','session'),patch.dict(os.environ,{'MODEL_OPERATOR':'reviewer'}):
            self.api.require_operator(SimpleNamespace(state=SimpleNamespace(reviewer='reviewer')))
            with self.assertRaises(HTTPException):self.api.require_operator(SimpleNamespace(state=SimpleNamespace(reviewer='other')))

    def test_workspace_has_no_cloud_start_buttons_and_keeps_canvas_and_cleanup(self):
        from pathlib import Path
        source=(Path(self.api.STATIC)/'index.html').read_text()
        for value in ('id="start-model"','id="stop-model"','id="model-cost"','id="model-time"'):
            self.assertNotIn(value,source)
        self.assertIn('id="cleanup-retry"',source);self.assertIn('data-orb=',source)
