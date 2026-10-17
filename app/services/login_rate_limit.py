"""Bounded, process-local failed-login tracking for the single-worker pilot."""

from collections import deque
from threading import Lock
from time import monotonic


_WINDOW_SECONDS = 300
_PAIR_LIMIT = 5
_IP_LIMIT = 30
_MAX_KEYS = 5000
_failures = {}
_lock = Lock()


def _prune(now):
    expired = [key for key, attempts in _failures.items()
               if not attempts or attempts[-1] <= now - _WINDOW_SECONDS]
    for key in expired:
        del _failures[key]


def _recent(key, now):
    attempts = _failures.setdefault(key, deque())
    while attempts and attempts[0] <= now - _WINDOW_SECONDS:
        attempts.popleft()
    return attempts


def is_limited(ip, username):
    now = monotonic()
    with _lock:
        return (len(_recent(('ip', ip), now)) >= _IP_LIMIT or
                len(_recent(('pair', ip, username.casefold()), now)) >= _PAIR_LIMIT)


def record_failure(ip, username):
    now = monotonic()
    with _lock:
        if len(_failures) >= _MAX_KEYS:
            _prune(now)
            if len(_failures) >= _MAX_KEYS:
                _failures.pop(next(iter(_failures)))
        for key in (('ip', ip), ('pair', ip, username.casefold())):
            _recent(key, now).append(now)


def clear_pair(ip, username):
    with _lock:
        _failures.pop(('pair', ip, username.casefold()), None)
