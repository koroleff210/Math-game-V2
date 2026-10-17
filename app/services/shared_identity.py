"""Private loopback bridge to the examination system's student identities."""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from flask import current_app


class IdentityUnavailable(ValueError):
    pass


def enabled():
    return bool(current_app.config.get('SHARED_IDENTITY_URL'))


def call(action, **fields):
    url = current_app.config.get('SHARED_IDENTITY_URL', '')
    token = current_app.config.get('SHARED_IDENTITY_TOKEN', '')
    if not url or not token:
        raise IdentityUnavailable('Shared sign-in is unavailable. Please try again shortly.')
    req = Request(url.rstrip('/') + '/identity',
                  data=json.dumps(dict(action=action, **fields)).encode(),
                  headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=5) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code in (400, 401, 404, 409):
            return {'error': 'Sign-in details changed or were not recognised. Please try again.'}
        raise IdentityUnavailable('Shared sign-in is unavailable. Please try again shortly.') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise IdentityUnavailable('Shared sign-in is unavailable. Please try again shortly.') from None
