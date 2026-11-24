"""Explicit inference transports. No fallback, redirects, tools or prompt logging."""
import json
from urllib.parse import urlsplit


def model_base(value):
    url=urlsplit(value)
    local=url.hostname in {'localhost','127.0.0.1','::1'}
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or (url.scheme!='https' and not (local and url.scheme=='http'))):
        raise ValueError('Model URL must be HTTPS, or loopback HTTP, without credentials or query')
    return value.rstrip('/')


def chat_payload(model, system, prompt, schema):
    return {'model':model, 'stream':False, 'temperature':0, 'max_tokens':1300,
            'messages':[{'role':'system','content':system + '\nJSON schema:\n' + json.dumps(schema)},
                        {'role':'user','content':prompt}]}


def parse_chat(response):
    choices = response.get('choices')
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError('Expected one model response')
    choice = choices[0]
    if choice.get('finish_reason') != 'stop':
        raise ValueError('Model response did not finish normally')
    message = choice.get('message', {})
    if message.get('tool_calls') or message.get('refusal'):
        raise ValueError('Model returned an unsupported response')
    content = message.get('content')
    if not isinstance(content, str) or len(content) > 50000:
        raise ValueError('Invalid model content')
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError('Model JSON must be an object')
    return value


def openai_generate(base, token, model, system, prompt, schema, client=None):
    url = model_base(base) + '/chat/completions'
    if not token:
        raise ValueError('Model inference credential required')
    if client is None:
        import httpx
        with httpx.Client(timeout=httpx.Timeout(300,connect=10),trust_env=False,
                          follow_redirects=False) as transport:
            return openai_generate(base, token, model, system, prompt, schema, transport)
    # Intentionally no retries: a timed-out request may already have incurred work.
    response = client.post(url, headers={'Authorization':'Bearer '+token},
                           json=chat_payload(model,system,prompt,schema))
    response.raise_for_status()
    return parse_chat(response.json())


def generate(system, prompt, schema):
    from . import config
    if config.INFERENCE_BACKEND=='disabled':raise RuntimeError('Model connection is not configured')
    if config.INFERENCE_BACKEND == 'openai':
        return openai_generate(config.MODEL_BASE_URL, config.MODEL_API_KEY,
                               config.MODEL, system, prompt, schema)
    import httpx
    with httpx.Client(timeout=httpx.Timeout(300,connect=10),trust_env=False,
                      follow_redirects=False) as client:
        r=client.post(config.OLLAMA_URL+'/api/generate',json={
            'model':config.MODEL,'stream':False,'format':schema,'system':system,
            'prompt':prompt,'options':{'temperature':0,'num_ctx':8192,'num_predict':1300},
            'keep_alive':'5m'})
        r.raise_for_status()
        response=r.json()
        if response.get('done_reason')=='length':
            raise ValueError('Model output truncated')
        return json.loads(response['response'])


def connection_status():
    """Read configured model metadata only; never start compute or generate."""
    from . import config
    result={'configured':config.INFERENCE_BACKEND!='disabled','state':'disconnected',
            'model':None,'processing_enabled':False,'conversation_enabled':False,
            'detail':'Model connection pending. Your documents remain available.'}
    if not result['configured']:return result
    import httpx
    result.update(model=config.MODEL,state='unavailable',detail='Model service is unavailable. Your documents remain available.')
    try:
        remote=config.INFERENCE_BACKEND=='openai'
        url=model_base(config.MODEL_BASE_URL)+'/models' if remote else config.OLLAMA_URL+'/api/tags'
        headers={'Authorization':'Bearer '+config.MODEL_API_KEY} if remote else {}
        with httpx.Client(timeout=5,trust_env=False,follow_redirects=False) as client:
            response=client.get(url,headers=headers);response.raise_for_status()
            data=response.json()
        names=[row.get('id') for row in data.get('data',[])] if remote else [row.get('name') for row in data.get('models',[])]
        registered=config.MODEL in names or (not remote and config.MODEL+':latest' in names)
        result.update(state='registered' if registered else 'model_missing',
                      processing_enabled=config.PROCESSING_ENABLED and registered,
                      detail='Model is registered. Generation remains unverified.' if registered else 'Configured model was not found.')
    except Exception:pass
    return result
