"""Map provider ids to their push backend."""

from __future__ import annotations

from common.push.backend import PushBackend
from common.push.errors import PushError, PushErrorCode

PUSH_PROVIDERS = ("spotify", "tidal")


def get_push_backend(provider: str) -> PushBackend:
    if provider == "spotify":
        from spotify.push_backend import SpotifyPushBackend

        return SpotifyPushBackend()
    if provider == "tidal":
        from tidal.push_backend import TidalPushBackend

        return TidalPushBackend()
    raise PushError(
        PushErrorCode.NOT_SUPPORTED, f"Pushing to {provider} is not supported.", recoverable=False
    )
