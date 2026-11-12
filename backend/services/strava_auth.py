"""Connecting z2 to the athlete's Strava account with Strava's OAuth web flow: the browser goes to
Strava's consent page and comes back to the app's callback with a code, which becomes the token.
A one-off state ties each return to the connect that started it, so no other page can sign z2
in to another account."""

import logging
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from urllib.parse import urlsplit

import requests

from backend.errors import Invalid
from zone2.core import Zone2
from zone2.endpoint import STRAVA_SCOPES, StravaNotConnected

logger = logging.getLogger(__name__)

# How long Strava's consent page may stay open before its return is refused
_STATE_TTL_S = 15 * 60


@dataclass(frozen=True)
class _Pending:
    return_to: str
    issued_at: float


@dataclass(frozen=True)
class Outcome:
    """Where the browser goes back to, and why Strava isn't connected, if it isn't."""
    return_to: str
    error: str | None = None


_pending: dict[str, _Pending] = {}
_lock = Lock()


def _app_path(path: str) -> str:
    """`path` when it is one of the app's own, else the app's home: the callback never sends the
    browser to another site."""
    return path if path.startswith("/") and not path.startswith(("//", "/\\")) else "/"


def start(z2: Zone2, origin: str, callback_path: str, return_to: str) -> str:
    """Strava's consent page, coming back to `callback_path` on the browser's `origin` and from
    there to `return_to`, a path of the app. The origin comes from the browser because behind
    the dev proxy or a tunnel the backend doesn't see the address the athlete opened."""
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path not in ("", "/"):
        raise Invalid(f"Not an origin Strava can send you back to: {origin!r}")
    state = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _lock:
        for stale in [s for s, p in _pending.items() if now - p.issued_at > _STATE_TTL_S]:
            del _pending[stale]
        _pending[state] = _Pending(_app_path(return_to), now)
    return z2.strava_endpoint.authorize_url(f"{parts.scheme}://{parts.netloc}{callback_path}", state)


def finish(z2: Zone2, state: str, code: str | None, scope: str, error: str | None) -> Outcome:
    """Connect the account from what Strava's consent page sent back: the state `start` gave it,
    and the code and the scopes granted, or the error when the athlete cancelled."""
    with _lock:
        pending = _pending.pop(state, None)
    if pending is None or time.monotonic() - pending.issued_at > _STATE_TTL_S:
        return Outcome("/", "That Strava sign-in expired or didn't start here: connect again.")
    if error or not code:
        return Outcome(pending.return_to, "Strava wasn't connected: the sign-in was cancelled.")
    if set(STRAVA_SCOPES) - set(scope.split(",")):
        return Outcome(pending.return_to, "z2 needs your private activities and your full profile: "
                                          "connect again and leave both boxes ticked.")
    try:
        athlete = z2.strava_endpoint.connect(code)
    except StravaNotConnected as e:
        return Outcome(pending.return_to, str(e))
    except requests.RequestException as e:
        logger.warning("Strava sign-in failed: %s", e)
        return Outcome(pending.return_to, "Strava can't be reached right now: try again in a minute.")
    z2.strava_user_cache.forget()
    logger.info("Strava connected for athlete %s", athlete.get("id"))
    return Outcome(pending.return_to)
