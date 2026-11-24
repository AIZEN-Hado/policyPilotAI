import os
from pathlib import Path
from urllib.parse import urlparse
DATABASE_URL = os.environ['DATABASE_URL']
AUTH_MODE = os.environ.get('AUTH_MODE', 'proxy')
if AUTH_MODE not in {'proxy', 'session'}:
    raise RuntimeError('Unsupported authentication mode')
PROXY_TOKEN = os.environ.get('PROXY_TOKEN', '')
PILOT_USER = os.environ.get('PILOT_USER', 'reviewer')
PILOT_PASSWORD_HASH = os.environ.get('PILOT_PASSWORD_HASH', '')
if AUTH_MODE == 'proxy' and len(PROXY_TOKEN) < 32:
    raise RuntimeError('PROXY_TOKEN must have at least 32 characters')
if AUTH_MODE == 'session':
    from .auth import valid_hash
    if not 1 <= len(PILOT_USER) <= 80 or not valid_hash(PILOT_PASSWORD_HASH):
        raise RuntimeError('Session authentication requires a pilot user and generated password hash')
APP_ORIGIN = os.environ['APP_ORIGIN'].rstrip('/')
origin = urlparse(APP_ORIGIN)
if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
        or origin.path or origin.query or origin.fragment):
    raise RuntimeError('Public origin must be an exact HTTPS origin')
DATA_DIR = Path(os.environ.get('DATA_DIR','/data/documents'))
OLLAMA_URL = os.environ.get('OLLAMA_BASE_URL','http://ollama:11434')
if urlparse(OLLAMA_URL).hostname not in {'ollama','127.0.0.1','localhost'}:
    raise RuntimeError('Pilot only permits local/private Ollama service')
MODEL = os.environ.get('OLLAMA_MODEL','qwen2.5:3b')
INFERENCE_BACKEND = os.environ.get('INFERENCE_BACKEND', 'disabled')
# Old or unknown deployment values disable inference during migration instead
# of keeping a retired provider active or taking document access offline.
if INFERENCE_BACKEND not in {'disabled','ollama','openai'}:
    INFERENCE_BACKEND = 'disabled'
PROCESSING_ENABLED = os.environ.get('PROCESSING_ENABLED')=='1' and INFERENCE_BACKEND!='disabled'
MODEL_BASE_URL = os.environ.get('MODEL_BASE_URL','')
MODEL_API_KEY = os.environ.get('MODEL_API_KEY','')
if INFERENCE_BACKEND=='openai':
    from .inference import model_base
    model_base(MODEL_BASE_URL)
    MODEL=os.environ.get('MODEL_NAME','')
    if not MODEL or not MODEL_API_KEY:raise RuntimeError('Configure a model name and inference credential')
if 'cloud' in MODEL.lower(): raise RuntimeError('Cloud models are disabled')
MAX_FILE = 10 * 1024 * 1024
MAX_DOCS = 12
MAX_PAGES = 20
