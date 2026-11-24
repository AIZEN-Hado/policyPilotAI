import importlib.util
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch,Mock

spec=importlib.util.spec_from_file_location('publisher',Path(__file__).resolve().parents[1]/'publish_images.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


class PublisherTests(unittest.TestCase):
    def test_public_unknown_and_internal_packages_block_upload(self):
        for package in ({},{'visibility':'public'},{'visibility':'internal'}):
            with self.assertRaises(publisher.PublishError):publisher.assert_private(package)
        publisher.assert_private(None)
        publisher.assert_private({'visibility':'private'})

    def test_token_goes_to_stdin_and_failure_does_not_print_it(self):
        result=Mock(returncode=1,stdout='',stderr='private-token')
        with patch.object(publisher.subprocess,'run',return_value=result) as run:
            with self.assertRaises(publisher.PublishError) as caught:
                publisher.docker('login','ghcr.io','--password-stdin',input_text='private-token\n')
        self.assertNotIn('private-token',str(caught.exception))
        self.assertNotIn('private-token',str(run.call_args.args))
        self.assertEqual(run.call_args.kwargs['input'],'private-token\n')

    def test_error_keeps_permission_reason_but_removes_tokens_and_urls(self):
        text='denied: permission_denied: write_package\nhttps://example.invalid/upload?token=private-value\nBearer private-value\nghp_abcdef'
        safe=publisher.safe_docker_detail(text,('private-value',))
        self.assertIn('permission_denied: write_package',safe)
        for secret in ('private-value','ghp_abcdef','https://example.invalid'):
            self.assertNotIn(secret,safe)

    def test_push_failure_reports_diagnostic_without_disclosing_login_token(self):
        process=Mock(stdout=io.StringIO('denied: insufficient_scope secret-token\n'))
        process.wait.return_value=1
        process.poll.return_value=1
        output=io.StringIO()
        with patch.object(publisher.subprocess,'Popen',return_value=process),contextlib.redirect_stdout(output):
            with self.assertRaises(publisher.PublishError) as caught:
                publisher.docker('push','ghcr.io/example/image:v1',secrets=('secret-token',))
        self.assertIn('insufficient_scope',str(caught.exception))
        self.assertNotIn('secret-token',str(caught.exception))
        self.assertIn('insufficient_scope',output.getvalue())
        self.assertNotIn('secret-token',output.getvalue())

    def test_successful_push_streams_progress_and_reuses_completed_layers(self):
        process=Mock(stdout=io.StringIO('abc: Layer already exists\ndef: Pushed\n'))
        process.wait.return_value=0
        process.poll.return_value=0
        output=io.StringIO()
        with patch.object(publisher.subprocess,'Popen',return_value=process),contextlib.redirect_stdout(output):
            publisher.docker('push','ghcr.io/example/image:v1')
        self.assertIn('Layer already exists',output.getvalue())
        self.assertIn('Pushed',output.getvalue())
        process.kill.assert_not_called()

    def test_timeout_stops_docker_client_and_keeps_local_images(self):
        process=Mock(stdout=io.StringIO(''))
        process.poll.return_value=None
        with patch.object(publisher.subprocess,'Popen',return_value=process),\
             patch.object(publisher.time,'monotonic',side_effect=[0,0,2]):
            with self.assertRaises(publisher.PublishError) as caught:
                publisher.docker('push','ghcr.io/example/image:v1',push_timeout=1)
        self.assertIn('reuse completed layers',str(caught.exception))
        process.kill.assert_called_once()

    def test_api_publication_drops_retired_worker_reference(self):
        import json
        import tempfile
        digest='a'*64
        retired={'name':'policypilot-gpu','reference':'ghcr.io/example/policypilot-gpu@sha256:'+'b'*64}
        metadata={'Os':'linux','Architecture':'amd64','Id':'local-id',
                  'RepoDigests':['ghcr.io/example/policypilot-api@sha256:'+digest]}
        def docker(*args,**kwargs):
            if args[:2]==('image','inspect'):return json.dumps([metadata])
            return ''
        def github(path,*args,**kwargs):
            return {'login':'example'} if path=='/user' else {'visibility':'private'}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'artifacts').mkdir()
            path=root/'artifacts/published-images.json'
            path.write_text(json.dumps({'namespace':'example','version':'v1','images':[retired],'compute_started':False}))
            with patch.object(publisher,'ROOT',root),patch.object(publisher,'docker',side_effect=docker) as calls,\
                 patch.object(publisher,'github',side_effect=github),\
                 patch.object(publisher.getpass,'getpass',return_value='secret'),\
                 patch('sys.argv',['publisher','example','--version','v1','--only','api']),\
                 contextlib.redirect_stdout(io.StringIO()):
                publisher.main()
            report=json.loads(path.read_text())
        self.assertEqual(len(report['images']),1)
        self.assertEqual(report['images'][0]['reference'],metadata['RepoDigests'][0])
        self.assertFalse(any('policypilot-gpu' in str(call) for call in calls.call_args_list))
