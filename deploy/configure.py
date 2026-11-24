"""Run interactively on the VPS. Secrets stay off argv and stdout."""
import getpass
import os
from pathlib import Path
import re
import secrets
import subprocess

def main():
    target=Path(__file__).parent/'.env'
    if target.exists(): raise SystemExit('Existing .env preserved. Edit it securely for configuration changes.')
    domain=input('Domain pointed at this VPS (no https://): ').strip().lower()
    if len(domain)>253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',domain):
        raise SystemExit('Supply a valid public DNS hostname')
    user=input('Pilot username [reviewer]: ').strip() or 'reviewer'
    if not re.fullmatch(r'[a-zA-Z0-9_-]{3,40}',user): raise SystemExit('Invalid username')
    password=getpass.getpass('Choose pilot password (16+ characters): ')
    if len(password)<16 or '\n' in password: raise SystemExit('Use at least 16 characters')
    if password!=getpass.getpass('Repeat password: '): raise SystemExit('Passwords differ')
    p=subprocess.run(['docker','run','--rm','-i','caddy:2.10.2-alpine','caddy','hash-password'],input=password+'\n',text=True,stdout=subprocess.PIPE,check=True)
    hashed=p.stdout.strip()
    if not hashed.startswith('$2'): raise SystemExit('Unexpected password hash; no configuration written')
    values={'APP_DOMAIN':domain,'PILOT_USER':user,'PILOT_PASSWORD_HASH':hashed,
            'POSTGRES_PASSWORD':secrets.token_hex(32),'PROXY_TOKEN':secrets.token_hex(32),
            'OLLAMA_MODEL':'qwen2.5:3b','MODEL_MEMORY_LIMIT':'6g'}
    descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as f:
        for key,value in values.items(): f.write(f"{key}='{value}'\n")
    print('Wrote deploy/.env with mode 0600. No secrets printed.')
if __name__=='__main__':main()
