import json
import unittest
from unittest.mock import Mock
from pilot.inference import model_base, openai_generate, parse_chat


def reply(content=None, finish='stop'):
    return {'choices':[{'finish_reason':finish,'message':{'content':json.dumps(content or {'summary':'ok'})}}]}


class InferenceTests(unittest.TestCase):
    def test_endpoint_cannot_inject_url(self):
        for endpoint in ('http://remote.invalid/v1','https://user:secret@host.invalid/v1','https://host.invalid/v1?token=x','https://host.invalid/v1#x',''):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                model_base(endpoint)

    def test_authenticated_model_request_only(self):
        client=Mock();client.post.return_value.json.return_value=reply()
        result=openai_generate('https://model.example.invalid/v1','secret','test-model','system','synthetic',{},client)
        self.assertEqual(result,{'summary':'ok'})
        args=client.post.call_args
        self.assertEqual(args.args[0],'https://model.example.invalid/v1/chat/completions')
        self.assertEqual(args.kwargs['headers'],{'Authorization':'Bearer secret'})
        self.assertNotIn('secret',json.dumps(args.kwargs['json']))
        self.assertFalse(args.kwargs['json']['stream'])

    def test_http_failure_never_retried(self):
        client=Mock();client.post.return_value.raise_for_status.side_effect=RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            openai_generate('https://model.example.invalid/v1','secret','model','system','test',{},client)
        client.post.assert_called_once()

    def test_no_key_no_request(self):
        client=Mock()
        with self.assertRaises(ValueError):
            openai_generate('https://model.example.invalid/v1','','model','system','test',{},client)
        client.post.assert_not_called()

    def test_truncated_or_refused_response_rejected(self):
        for reason in ('length','tool_calls','content_filter',None):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                parse_chat(reply(finish=reason))

    def test_tool_calls_rejected(self):
        response=reply();response['choices'][0]['message']['tool_calls']=[{'name':'fetch'}]
        with self.assertRaises(ValueError):parse_chat(response)

    def test_non_json_and_non_object_rejected(self):
        for content in ('not json','[]','null'):
            response=reply();response['choices'][0]['message']['content']=content
            with self.subTest(content=content),self.assertRaises(ValueError):parse_chat(response)
