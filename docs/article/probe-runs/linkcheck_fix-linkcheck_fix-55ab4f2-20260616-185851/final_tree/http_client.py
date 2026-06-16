"""HTTP-клиент для проверки доступности ссылок."""

import urllib.parse

import requests

HTTP_TIMEOUT_DEFAULT = 10

# Сессия с переиспользованием соединений
_HTTP_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        _HTTP_SESSION = requests.Session()
        _HTTP_SESSION.headers.update({
            "User-Agent": "link-checker/0.1",
        })
    return _HTTP_SESSION


def check_link(url: str, timeout: int = 10) -> int:
    """Проверить HTTP/HTTPS ссылку и вернуть HTTP-статус.

    Сначала HEAD, при 405/501 — GET. При ошибке возвращает 0.
    """
    session = _get_session()

    parsed = urllib.parse.urlparse(url)
    clean_url = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path,
         parsed.params, parsed.query, '')
    )
    if not clean_url:
        clean_url = url

    try:
        resp = session.head(clean_url, timeout=timeout, allow_redirects=True)
        if resp.status_code in (405, 501):
            resp = session.get(clean_url, timeout=timeout, allow_redirects=True)
        return resp.status_code

    except (requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.SSLError,
            requests.exceptions.TooManyRedirects,
            requests.exceptions.RequestException):
        return 0
