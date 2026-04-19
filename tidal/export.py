"""Pull the user's TIDAL library into :mod:`common.models`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from tidalapi.media import Track as TidalTrack
from tidalapi.media import Video

from common.log import get_logger
from common.models import (
    Album,
    Artist,
    FollowedArtist,
    Image,
    Library,
    Playlist,
    PlaylistTrack,
    RecordMeta,
    SavedAlbum,
    Track,
    record_meta_for_pull,
)
from tidal.client import get_session

if TYPE_CHECKING:
    import tidalapi.album
    import tidalapi.artist
    import tidalapi.playlist
    from tidalapi.session import Session

log = get_logger(__name__)

SERVICE = "tidal"


def _artist_image_url(session: "Session", picture: str | None, size: int = 320) -> list[Image]:
    if not picture:
        return []
    url = session.config.image_url % (picture.replace("-", "/"), size, size)
    return [Image(url=url, height=size, width=size)]


def tidal_artist_to_common(session: "Session", a: "tidalapi.artist.Artist") -> Artist:
    pid = str(a.id) if a.id is not None else None
    return Artist(
        name=a.name or "",
        genres=[],
        images=_artist_image_url(session, getattr(a, "picture", None)),
        service_id=pid,
        service_url=getattr(a, "share_url", None) or getattr(a, "listen_url", None),
        uri=f"tidal:artist:{pid}" if pid else None,
        service=SERVICE,
    )


def tidal_album_to_common(
    session: "Session",
    a: "tidalapi.album.Album",
    *,
    embed_tracks: bool,
) -> Album:
    rel: str | None = None
    prec: str | None = None
    if a.release_date:
        rel = a.release_date.date().isoformat()
        prec = "day"
    elif a.tidal_release_date:
        rel = a.tidal_release_date.date().isoformat()
        prec = "day"
    upc = str(a.upc) if getattr(a, "upc", None) else None
    arts = [tidal_artist_to_common(session, x) for x in (a.artists or [])]
    if not arts and a.artist:
        arts = [tidal_artist_to_common(session, a.artist)]
    cover_imgs: list[Image] = []
    if getattr(a, "cover", None):
        try:
            u = a.image(320)
            cover_imgs = [Image(url=u, height=320, width=320)]
        except Exception:
            pass
    tracks: list[Track] = []
    if embed_tracks and a.tracks:
        for t in a.tracks:
            if isinstance(t, TidalTrack):
                tracks.append(tidal_track_to_common(session, t, embed_album=False))
    aid = str(a.id) if a.id is not None else None
    return Album(
        name=a.name or "",
        artists=arts,
        album_type=str(a.type) if getattr(a, "type", None) is not None else None,
        release_date=rel,
        release_date_precision=prec,
        total_tracks=a.num_tracks,
        tracks=tracks,
        images=cover_imgs,
        genres=[],
        copyrights=[],
        upc=upc,
        service_id=aid,
        service_url=getattr(a, "share_url", None) or getattr(a, "listen_url", None),
        uri=f"tidal:album:{aid}" if aid else None,
        service=SERVICE,
    )


def tidal_track_to_common(
    session: "Session",
    t: TidalTrack,
    *,
    embed_album: bool,
) -> Track:
    arts = [tidal_artist_to_common(session, x) for x in (t.artists or [])]
    alb: Album | None = None
    if embed_album and t.album:
        alb = tidal_album_to_common(session, t.album, embed_tracks=False)
    tid = str(t.id) if t.id is not None else None
    return Track(
        name=t.name or t.full_name or "",
        artists=arts,
        album=alb,
        track_number=getattr(t, "track_num", None),
        disc_number=getattr(t, "volume_num", None),
        duration_ms=int(t.duration * 1000) if getattr(t, "duration", None) else None,
        explicit=getattr(t, "explicit", None),
        is_local=getattr(t, "upload", None),
        isrc=getattr(t, "isrc", None),
        service_id=tid,
        service_url=getattr(t, "share_url", None) or getattr(t, "listen_url", None),
        uri=f"tidal:track:{tid}" if tid else None,
        service=SERVICE,
    )


def _playlist_track_row(
    session: "Session",
    t: TidalTrack,
    pos: int,
    meta: RecordMeta,
) -> PlaylistTrack:
    added = getattr(t, "date_added", None) or getattr(t, "user_date_added", None)
    return PlaylistTrack(
        track=tidal_track_to_common(session, t, embed_album=True),
        record_meta=meta,
        position=pos,
        added_at=added,
        added_by=None,
    )


def _fetch_playlist_tracks(session: "Session", pl: "tidalapi.playlist.Playlist") -> list[PlaylistTrack]:
    meta = record_meta_for_pull(SERVICE)
    out: list[PlaylistTrack] = []
    pos = 0
    offset = 0
    while True:
        batch = pl.items(limit=100, offset=offset)
        if not batch:
            break
        for item in batch:
            if isinstance(item, Video):
                continue
            if not isinstance(item, TidalTrack):
                continue
            out.append(_playlist_track_row(session, item, pos, meta))
            pos += 1
        offset += len(batch)
        if len(batch) < 100:
            break
    return out


def _tidal_playlist_to_common(session: "Session", pl: "tidalapi.playlist.Playlist") -> Playlist:
    owner: str | None = None
    cr = pl.creator
    if cr is not None:
        owner = getattr(cr, "name", None) or (
            str(cr.id) if getattr(cr, "id", None) not in (None, 0) else None
        )
    images: list[Image] = []
    if pl.square_picture or pl.picture:
        try:
            u = pl.image(480)
            images = [Image(url=u, height=480, width=480)]
        except Exception:
            pass
    tracks = _fetch_playlist_tracks(session, pl)
    etag = getattr(pl, "_etag", None)
    pid = str(pl.id) if pl.id else None
    return Playlist(
        name=pl.name or "(untitled)",
        record_meta=record_meta_for_pull(SERVICE),
        description=pl.description,
        owner=owner,
        collaborative=None,
        public=pl.public,
        snapshot_id=str(etag) if etag else None,
        images=images,
        tracks=tracks,
        service_id=pid,
        service_url=getattr(pl, "listen_url", None) or getattr(pl, "share_url", None),
        uri=f"tidal:playlist:{pid}" if pid else None,
        service=SERVICE,
    )


def _fetch_all_playlists(session: "Session") -> list[Playlist]:
    user = session.user
    out: list[Playlist] = []
    offset = 0
    while True:
        batch = user.playlist_and_favorite_playlists(offset=offset, limit=50)
        if not batch:
            break
        for pl in batch:
            try:
                out.append(_tidal_playlist_to_common(session, pl))
            except Exception as exc:
                log.warning("Skipping playlist %s: %s", getattr(pl, "name", "?"), exc)
        offset += len(batch)
        if len(batch) < 50:
            break
    log.info("Fetched %d TIDAL playlists", len(out))
    return out


def _liked_track_to_row(session: "Session", t: TidalTrack) -> PlaylistTrack:
    meta = record_meta_for_pull(SERVICE)
    added = getattr(t, "date_added", None) or getattr(t, "user_date_added", None)
    return PlaylistTrack(
        track=tidal_track_to_common(session, t, embed_album=True),
        record_meta=meta,
        position=None,
        added_at=added,
        added_by=None,
    )


def _saved_album_row(session: "Session", a: "tidalapi.album.Album") -> SavedAlbum:
    return SavedAlbum(
        album=tidal_album_to_common(session, a, embed_tracks=False),
        record_meta=record_meta_for_pull(SERVICE),
        saved_at=getattr(a, "user_date_added", None),
    )


def _followed_artist_row(session: "Session", a: "tidalapi.artist.Artist") -> FollowedArtist:
    return FollowedArtist(
        artist=tidal_artist_to_common(session, a),
        record_meta=record_meta_for_pull(SERVICE),
        followed_at=getattr(a, "user_date_added", None),
    )


def fetch_library() -> Library:
    """Pull the user's entire TIDAL library (favorites + playlists)."""
    session = get_session()
    user = session.user
    if not hasattr(user, "favorites"):
        raise RuntimeError("TIDAL session has no user favorites (not logged in).")

    log.info("Starting full library export from TIDAL…")
    fav = user.favorites

    liked_songs = [_liked_track_to_row(session, t) for t in fav.tracks_paginated()]
    log.info("Fetched %d favorite tracks", len(liked_songs))

    saved_albums = [_saved_album_row(session, a) for a in fav.albums_paginated()]
    log.info("Fetched %d favorite albums", len(saved_albums))

    followed_artists = [_followed_artist_row(session, a) for a in fav.artists_paginated()]
    log.info("Fetched %d favorite artists", len(followed_artists))

    playlists = _fetch_all_playlists(session)

    return Library(
        last_pull_provider=SERVICE,
        exported_at=datetime.now(timezone.utc),
        playlists=playlists,
        liked_songs=liked_songs,
        saved_albums=saved_albums,
        followed_artists=followed_artists,
    )
