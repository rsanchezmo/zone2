"""Signing in to Garmin Connect from the app: the email and password go to Garmin once and only
its tokens are kept, and when Garmin asks for the code it sent, a second step finishes the
sign-in. Garmin then syncs as it does with its credentials in .env."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from backend.errors import Conflict, Invalid, UpstreamUnavailable
from zone2.core import Zone2
from zone2.garmin_client import GarminSignInFailed, GarminSignInRefused


@contextmanager
def _as_service_errors() -> Iterator[None]:
    try:
        yield
    except GarminSignInRefused as e:
        raise Invalid(str(e)) from e
    except GarminSignInFailed as e:
        raise UpstreamUnavailable(str(e)) from e


async def sign_in(z2: Zone2, email: str, password: str) -> bool:
    """Sign in; True when Garmin asks for the code it sent before the sign-in is done."""
    if not email.strip() or not password:
        raise Invalid("Enter your Garmin email and password.")
    with _as_service_errors():
        return await asyncio.to_thread(z2.garmin_client.begin_sign_in, email.strip(), password)


async def enter_code(z2: Zone2, code: str) -> None:
    """Finish the sign-in with the code Garmin sent."""
    if not code.strip():
        raise Invalid("Enter the code Garmin sent you.")
    with _as_service_errors():
        await asyncio.to_thread(z2.garmin_client.finish_sign_in, code.strip())


def sign_out(z2: Zone2) -> None:
    if z2.garmin_client.from_env:
        raise Conflict("Garmin's email and password are in .env: remove them there to disconnect.")
    z2.garmin_client.sign_out()
