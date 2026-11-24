"""Diagnose one pilot login; hide credentials and never invoke model compute."""
import argparse
import getpass
import http.cookiejar
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pilot.auth import COOKIE,valid_hash,verify_password


class DiagnosticError(Exception):pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def validate_origin(origin):
    value=urllib.parse.urlsplit(origin)
    if (value.scheme!='https' or not value.hostname or value.username or value.password
            or value.path not in ('','/') or value.query or value.fragment
            or value.hostname.endswith('.invalid')):
        raise DiagnosticError('Use the actual public HTTPS origin, without a path or credentials.')
    return origin.rstrip('/')


def request(opener,origin,path,method='GET',payload=None):
    body=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(origin+path,data=body,method=method,
                              headers={'Origin':origin,'Content-Type':'application/json'})
    try:
        response=opener.open(req,timeout=90)
    except urllib.error.HTTPError as exc:response=exc
    except OSError:
        raise DiagnosticError('Network/TLS request failed; exception details withheld. No automatic retry.') from None
    with response:
        raw=response.read(8193)
        try:data=json.loads(raw) if len(raw)<=8192 else None
        except (ValueError,UnicodeError):data=None
        return response.code,data


def diagnose(origin,username,encoded,password,opener,cookies):
    origin=validate_origin(origin)
    if not username or username!=username.strip():
        raise DiagnosticError('Username is empty or has surrounding whitespace; use the exact PILOT_USER value.')
    if not valid_hash(encoded):
        raise DiagnosticError('The pasted hash has invalid format. Copy only the full PILOT_PASSWORD_HASH value, without quotes or spaces. No login sent.')
    if not verify_password(password,encoded):
        raise DiagnosticError('Password does NOT match the pasted Render hash. No login sent. Resolve this local mismatch before changing the deployment.')
    print('PASS: entered password matches the pasted Render hash. No secrets printed.')
    code,data=request(opener,origin,'/healthz')
    if code!=200 or not isinstance(data,dict) or data.get('status')!='ok':
        raise DiagnosticError(f'Health check failed (HTTP {code}). Check the Render deploy and database first. No login sent.')
    print('PASS: public health check and database connection.')
    print('Sending one login attempt; no automatic retry and no GPU requests.')
    code,data=request(opener,origin,'/api/auth/login','POST',{'username':username,'password':password})
    if code!=200:
        reasons={
            401:'Server rejected the username/password although the local hash check passed. Check the active deploy, exact PILOT_USER, and that the hash was copied from this web service.',
            403:'Server rejected the Origin. Set APP_ORIGIN to this exact public HTTPS origin, then save and deploy.',
            429:'Account is rate limited. Wait 15 minutes; restarting the web service does not clear the database lockout.',
            503:'Login service is unavailable. Check migration completion and database/auth tables in the deployment logs.'}
        raise DiagnosticError(f'Login HTTP {code}: '+reasons.get(code,'Unexpected server response; body withheld.'))
    try:
        if not any(cookie.name==COOKIE and cookie.secure for cookie in cookies):
            raise DiagnosticError('Login succeeded but the expected Secure session cookie was not received. Check deployment URL and cookie configuration.')
        code,data=request(opener,origin,'/api/auth/me')
        if code!=200 or not isinstance(data,dict) or data.get('username')!=username or data.get('auth_mode')!='session':
            raise DiagnosticError('Login succeeded but session identity verification failed. Check cookie handling and which deployment serves the URL.')
        print('PASS: live credentials, Secure cookie and authenticated session. If the browser still fails, manually enter these same credentials in a private window without autofill.')
    finally:
        # Close only the session created by this diagnostic, even if /me failed.
        try:code,_=request(opener,origin,'/api/auth/logout','POST')
        except DiagnosticError:code=None
        if code!=204:
            print('NOTICE: diagnostic-session logout was not confirmed; the session may remain until expiry.')
        else:print('PASS: diagnostic session logged out.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin')
    args=parser.parse_args()
    origin=validate_origin(args.origin)
    if not sys.stdin.isatty():
        raise DiagnosticError('Run in an interactive terminal so credentials stay hidden.')
    username=input('Exact PILOT_USER from this Render web service [reviewer]: ') or 'reviewer'
    print('Copy the CURRENT hash from this web service\'s Render Environment page.')
    encoded=getpass.getpass('PILOT_PASSWORD_HASH (hidden): ')
    password=getpass.getpass('Password you are trying to use (hidden): ')
    cookies=http.cookiejar.CookieJar()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),
                                     urllib.request.HTTPCookieProcessor(cookies))
    diagnose(origin,username,encoded,password,opener,cookies)


if __name__=='__main__':
    try:main()
    except DiagnosticError as exc:raise SystemExit('CHECK: '+str(exc)) from None
    except OSError:raise SystemExit('CHECK: network or terminal operation failed; details withheld. No automatic retry.') from None
    except (ValueError,EOFError,KeyboardInterrupt):raise SystemExit('Diagnostic stopped. No credentials saved or printed.') from None
