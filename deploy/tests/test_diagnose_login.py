import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

spec=importlib.util.spec_from_file_location('diagnostic',Path(__file__).resolve().parents[1]/'diagnose_login.py')
diagnostic=importlib.util.module_from_spec(spec);spec.loader.exec_module(diagnostic)
from pilot.auth import password_hash


class LoginDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password='synthetic-diagnostic-password'
        cls.encoded=password_hash(cls.password)

    def run_check(self,answers,password=None,encoded=None,cookies=None):
        output=io.StringIO()
        cookie_values=[SimpleNamespace(name=diagnostic.COOKIE,secure=True)] if cookies is None else cookies
        with patch.object(diagnostic,'request',side_effect=answers) as send,contextlib.redirect_stdout(output):
            try:
                diagnostic.diagnose('https://pilot.example.com','reviewer',
                                    self.encoded if encoded is None else encoded,
                                    self.password if password is None else password,Mock(),cookie_values)
                error=None
            except diagnostic.DiagnosticError as exc:error=str(exc)
        self.assertNotIn(self.password,output.getvalue())
        self.assertNotIn(self.encoded,output.getvalue())
        return send,output.getvalue(),error

    def test_wrong_password_or_malformed_hash_never_sends_request(self):
        for kwargs in ({'password':'wrong'},{'encoded':'bad'}):
            send,_,error=self.run_check([],**kwargs)
            self.assertIsNotNone(error)
            send.assert_not_called()

    def test_origin_cannot_include_credentials_or_redirect_path(self):
        for origin in ('http://pilot.example.com','https://user:secret@pilot.example.com',
                       'https://pilot.example.com/login','https://setup.invalid'):
            with self.assertRaises(diagnostic.DiagnosticError):diagnostic.validate_origin(origin)

    def test_server_rejection_is_reported_once_without_response_body(self):
        for code,reason in ((401,'active deploy'),(403,'Origin'),(429,'rate limited'),(503,'migration')):
            send,output,error=self.run_check([(200,{'status':'ok'}),(code,{'detail':self.password})])
            self.assertEqual(send.call_count,2)
            self.assertIn(reason,error)
            self.assertNotIn(self.password,error)

    def test_healthy_session_is_verified_and_logged_out_without_gpu_calls(self):
        send,output,error=self.run_check([(200,{'status':'ok'}),(200,{}),
                                        (200,{'username':'reviewer','auth_mode':'session'}),(204,None)])
        self.assertIsNone(error)
        self.assertIn('authenticated session',output)
        self.assertIn('logged out',output)
        paths=[call.args[2] for call in send.call_args_list]
        self.assertEqual(paths,['/healthz','/api/auth/login','/api/auth/me','/api/auth/logout'])

    def test_failed_session_check_still_logs_out(self):
        send,_,error=self.run_check([(200,{'status':'ok'}),(200,{}),(401,{}),(204,None)])
        self.assertIn('identity verification failed',error)
        self.assertEqual(send.call_args.args[2],'/api/auth/logout')

    def test_missing_secure_cookie_still_attempts_logout(self):
        send,_,error=self.run_check([(200,{'status':'ok'}),(200,{}),(204,None)],cookies=[])
        self.assertIn('Secure session cookie',error)
        self.assertEqual(send.call_count,3)
