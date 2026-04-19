"""Registry of catalog pull adapters (Spotify, Tidal, …).

Each adapter exposes :meth:`fetch_library` returning :class:`~common.models.Library`
with per-entity ``service`` set to the adapter’s :attr:`provider_id`.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from common.models import Library

_registry: dict[str, "CatalogPullAdapter"] | None = None


@runtime_checkable
class CatalogPullAdapter(Protocol):
    """Pull a full library snapshot from a streaming backend."""

    provider_id: str

    def fetch_library(self) -> Library:
        """Block until the remote catalog is fetched; returns in-memory models only."""


class _CallableCatalogPullAdapter:
    __slots__ = ("provider_id", "_fetch")

    def __init__(self, provider_id: str, fetch: Callable[[], Library]) -> None:
        self.provider_id = provider_id
        self._fetch = fetch

    def fetch_library(self) -> Library:
        return self._fetch()


def register_catalog_pull(adapter: CatalogPullAdapter) -> None:
    """Register or replace an adapter for :attr:`CatalogPullAdapter.provider_id`."""
    global _registry
    if _registry is None:
        _registry = {}
    _registry[adapter.provider_id] = adapter


def ensure_catalog_pulls_registered() -> None:
    """Lazily populate the registry (avoids import cycles)."""
    global _registry
    if _registry is not None:
        return
    _registry = {}
    from spotify import export as spotify_export
    from tidal import export as tidal_export

    register_catalog_pull(
        _CallableCatalogPullAdapter("spotify", spotify_export.fetch_library)
    )
    register_catalog_pull(
        _CallableCatalogPullAdapter("tidal", tidal_export.fetch_library)
    )


def get_catalog_pull(provider_id: str) -> CatalogPullAdapter | None:
    """Return the adapter for ``provider_id``, or ``None`` if none registered."""
    ensure_catalog_pulls_registered()
    assert _registry is not None
    return _registry.get(provider_id)
