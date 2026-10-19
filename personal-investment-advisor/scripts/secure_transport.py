"""HTTPS-only source reads. Redirects fail closed rather than replaying a request."""
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, build_opener
import ssl


def require_https(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('source requires HTTPS without URL credentials')
    return url


ANONYMOUS_POLICY = 'pia_anonymous_https_v2'
CREDENTIAL_HEADERS = frozenset({'authorization', 'proxy-authorization', 'cookie', 'cookie2',
                                'x-api-key', 'api-key', 'x-auth-token', 'x-access-token'})


def reject_credentials(headers):
    if any(str(key).lower() in CREDENTIAL_HEADERS for key in headers):
        raise ValueError('anonymous source credential header forbidden')


def anonymous_session():
    import requests
    session = requests.Session()
    session.trust_env = False
    return session


def anonymous_policy(session, headers=None):
    session.trust_env = False
    reject_credentials(session.headers)
    reject_credentials(headers or {})
    if session.auth is not None or session.cert is not None or session.proxies or session.cookies:
        raise ValueError('anonymous source session credentials/cookies/proxies forbidden')


def request(session, method, url, **kwargs):
    require_https(url)
    anonymous_policy(session, kwargs.get('headers'))
    if set(kwargs) & {'auth', 'cookies', 'cert', 'proxies', 'verify', 'allow_redirects'}:
        raise ValueError('anonymous source credential/security parameters forbidden')
    if kwargs.get('headers', {}).get('Referer'):
        require_https(kwargs['headers']['Referer'])
    try:
        response = getattr(session, method.lower())(url, allow_redirects=False, verify=True, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise ValueError('source redirect refused (no request to redirect target)')
        return response
    finally:
        session.cookies.clear()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('source redirect refused (no request to redirect target)')


def open_https(req, timeout):
    require_https(req.full_url)
    reject_credentials(dict(req.header_items()))
    referer = req.get_header('Referer')
    if referer:
        require_https(referer)
    return build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()), ProxyHandler({})).open(req, timeout=timeout)
