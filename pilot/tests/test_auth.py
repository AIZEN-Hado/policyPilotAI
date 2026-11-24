from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import unittest

from pilot import auth


class PasswordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded=auth.password_hash('synthetic-test-password-only')

    def test_password_verified_and_wrong_password_rejected(self):
        self.assertTrue(auth.verify_password('synthetic-test-password-only',self.encoded))
        self.assertFalse(auth.verify_password('different',self.encoded))

    def test_salt_is_random(self):
        self.assertNotEqual(self.encoded,auth.password_hash('synthetic-test-password-only'))

    def test_unsafe_hash_parameters_rejected_without_hashing(self):
        with patch.object(auth.hashlib,'pbkdf2_hmac') as derive:
            for encoded in ('bad',self.encoded.replace('600000','999999999'),self.encoded+'0'):
                self.assertFalse(auth.verify_password('synthetic-test-password-only',encoded))
            self.assertFalse(auth.verify_password('a'*1025,self.encoded))
            derive.assert_not_called()

    def test_short_password_not_accepted_for_configuration(self):
        with self.assertRaises(ValueError): auth.password_hash('short')

    def test_session_identifiers_are_random_and_hashed(self):
        token=auth.secrets.token_urlsafe(32)
        digest=auth.session_hash(token)
        self.assertEqual(len(digest),64)
        self.assertNotEqual(digest,token)
        for malformed in ('', 'x'*42,'x'*44,'/'*43,None):
            self.assertIsNone(auth.session_hash(malformed))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.conn=MagicMock()
        self.conn.execute.return_value.fetchone.return_value={'attempts':0,'expired':False}
        self.committed=False

        @contextmanager
        def connect():
            yield self.conn
            self.committed=True
        self.connect=connect

    def test_failed_attempt_commits_instead_of_rolling_back(self):
        with patch.object(auth,'verify_password',return_value=False):
            token,error=auth.login('reviewer','wrong',self.connect,'reviewer','hash')
        self.assertIsNone(token)
        self.assertEqual(error,'invalid')
        self.assertTrue(self.committed)
        self.assertIn('attempts=attempts+1',self.conn.execute.call_args.args[0])

    def test_throttled_attempt_does_not_hash_or_create_session(self):
        self.conn.execute.return_value.fetchone.return_value={'attempts':5,'expired':False}
        with patch.object(auth,'verify_password') as verify:
            self.assertEqual(auth.login('reviewer','wrong',self.connect,'reviewer','hash'),(None,'throttled'))
            verify.assert_not_called()
        self.assertEqual(self.conn.execute.call_count,1)

    def test_wrong_username_does_not_authenticate_with_valid_password(self):
        with patch.object(auth,'verify_password',return_value=True):
            self.assertEqual(auth.login('attacker','password',self.connect,'reviewer','hash'),(None,'invalid'))

    def test_expired_lockout_can_issue_opaque_session(self):
        self.conn.execute.return_value.fetchone.return_value={'attempts':5,'expired':True}
        with patch.object(auth,'verify_password',return_value=True):
            token,error=auth.login('reviewer','password',self.connect,'reviewer','hash')
        self.assertIsNone(error)
        query,params=self.conn.execute.call_args.args
        self.assertIn('INSERT INTO pilot_sessions',query)
        self.assertEqual(params[0],auth.session_hash(token))
        self.assertNotIn(token,params)
        self.assertTrue(self.committed)

    def test_malformed_cookie_does_not_access_database(self):
        connect=MagicMock()
        self.assertIsNone(auth.current_user('forged',connect,'reviewer','hash'))
        auth.logout('forged',connect)
        connect.assert_not_called()

    def test_lookup_requires_expiry_and_current_credential(self):
        self.conn.execute.return_value.fetchone.return_value=None
        token=auth.secrets.token_urlsafe(32)
        self.assertIsNone(auth.current_user(token,self.connect,'reviewer','hash'))
        query,params=self.conn.execute.call_args.args
        self.assertIn('expires_at>now()',query)
        self.assertIn('credential_hash=%s',query)
        self.assertEqual(params[0],auth.session_hash(token))

    def test_logout_revokes_token(self):
        token=auth.secrets.token_urlsafe(32)
        auth.logout(token,self.connect)
        self.assertEqual(self.conn.execute.call_args.args,
                         ('DELETE FROM pilot_sessions WHERE token_hash=%s',(auth.session_hash(token),)))
        self.assertTrue(self.committed)
