"""Push core against an in-memory fake provider (no network)."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from common.models import (
    Album,
    Artist,
    FollowedArtist,
    Library,
    Playlist,
    PlaylistTrack,
    SavedAlbum,
    Track,
    record_meta_for_app,
)
from common.push.errors import PushError, PushErrorCode
from common.push.executor import execute_plan
from common.push.fingerprint import library_fingerprint
from common.push.identity import playlist_key, track_key
from common.push.matching import DEFAULT_MATCHING, Matcher, Scored, decide
from common.push.models import CatalogAlbum, CatalogArtist, CatalogTrack, PushMode, RemoteSnapshot
from common.push.ordering import merge_order
from common.push.planner import build_remote_wipe_plan, dry_run_push, prepare_push
from common.push.report import format_plan_details, format_plan_report
from common.push.resolution_cache import EXCLUDE, set_decision
from common.push.sync_intent import (
    load_sync_intents,
    record_liked_removed,
    record_playlist_removed,
    record_playlist_tracks_removed,
)

META = record_meta_for_app()


def ct(tid: str, title: str, artist: str, album: str | None = None, ms: int | None = 200_000, isrc=None):
    return CatalogTrack(id=tid, title=title, artists=[artist], artist_ids=[f"ar_{artist}"],
                        album=album, duration_ms=ms, isrc=isrc)


def lt(title: str, artist: str, *, sid: str | None = None, service: str | None = None,
       ms: int | None = 200_000, isrc: str | None = None, is_local: bool = False) -> Track:
    return Track(name=title, artists=[Artist(name=artist)], duration_ms=ms, isrc=isrc,
                 service_id=sid, service=service, is_local=is_local)


def pl(name: str, tracks: list[Track], *, sid: str | None = None, service: str | None = None) -> Playlist:
    return Playlist(name=name, record_meta=META, service_id=sid, service=service,
                    tracks=[PlaylistTrack(track=t, record_meta=META) for t in tracks])


CATALOG = [
    ct("t_a", "Alpha", "Band"),
    ct("t_b", "Bravo (2009 Remaster)", "Band"),
    ct("t_c", "Charlie", "Band"),
    ct("t_d", "Delta", "Other"),
    ct("t_e", "Echo", "Band"),
    ct("t_live", "Foxtrot - Live", "Band"),
    ct("t_resist", "Resist", "Wipers", album="Youth of America"),
    ct("t_isrc", "Golf", "Band", isrc="US1234567890"),
]


class FakeBackend:
    provider_id = "spotify"

    def __init__(self, catalog=CATALOG) -> None:
        self.catalog = {c.id: c for c in catalog}
        self.albums = {"al_1": CatalogAlbum(id="al_1", title="Record", artists=["Band"], artist_ids=["ar_Band"])}
        self.artists = {"ar_Band": CatalogArtist(id="ar_Band", name="Band"),
                        "ar_Other": CatalogArtist(id="ar_Other", name="Other")}
        self.artist_discography: dict[str, list[str]] = {}
        self.playlists: dict[str, dict] = {}
        self.liked: list[str] = []
        self.saved_albums: list[str] = []
        self.followed: list[str] = []
        self.calls: list[str] = []
        self.fail_on: str | None = None
        self._n = 0

    # helpers
    def add_remote_playlist(self, name: str, ids: list[str], *, editable=True) -> str:
        self._n += 1
        pid = f"p{self._n}"
        self.playlists[pid] = {"name": name, "ids": list(ids), "editable": editable, "version": 1}
        return pid

    def _track(self, tid: str) -> Track:
        c = self.catalog[tid]
        return Track(name=c.title, artists=[Artist(name=a, service_id=i, service="spotify")
                                            for a, i in zip(c.artists, c.artist_ids)],
                     duration_ms=c.duration_ms, isrc=c.isrc, service_id=c.id, service="spotify")

    def _log(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_on == name:
            self.fail_on = None
            raise RuntimeError("boom")

    # read
    def snapshot(self) -> RemoteSnapshot:
        lib = Library(
            playlists=[
                Playlist(name=p["name"], record_meta=META, service_id=pid, service="spotify",
                         snapshot_id=str(p["version"]),
                         tracks=[PlaylistTrack(track=self._track(i), record_meta=META) for i in p["ids"]])
                for pid, p in self.playlists.items()
            ],
            liked_songs=[PlaylistTrack(track=self._track(i), record_meta=META) for i in self.liked],
            saved_albums=[SavedAlbum(album=Album(name=self.albums[i].title,
                                                 artists=[Artist(name=a) for a in self.albums[i].artists],
                                                 service_id=i, service="spotify"), record_meta=META)
                          for i in self.saved_albums],
            followed_artists=[FollowedArtist(artist=Artist(name=self.artists[i].name, service_id=i,
                                                           service="spotify"), record_meta=META)
                              for i in self.followed],
        )
        return RemoteSnapshot(library=lib, editable_playlist_ids={k for k, p in self.playlists.items() if p["editable"]})

    def lookup_tracks(self, ids):
        self.calls.append("lookup_tracks")
        return {i: self.catalog[i] for i in ids if i in self.catalog}

    def lookup_albums(self, ids):
        return {i: self.albums[i] for i in ids if i in self.albums}

    def lookup_artists(self, ids):
        return {i: self.artists[i] for i in ids if i in self.artists}

    def tracks_by_isrc(self, isrc):
        self.calls.append("isrc")
        return [c for c in self.catalog.values() if c.isrc == isrc]

    def albums_by_upc(self, upc):
        return []

    def search_tracks(self, title, artist, album, *, narrow):
        self.calls.append("search_narrow" if narrow else "search_broad")
        q = title.casefold()
        hits = [c for c in self.catalog.values() if q in c.title.casefold() or c.title.casefold() in q]
        if narrow and artist:
            hits = [c for c in hits if artist.casefold() in (a.casefold() for a in c.artists)]
        return hits

    def search_albums(self, title, artist, *, narrow):
        return [a for a in self.albums.values() if title.casefold() in a.title.casefold()]

    def search_artists(self, name):
        return [a for a in self.artists.values() if name.casefold() in a.name.casefold()]

    def artist_albums(self, artist_id):
        self.calls.append("artist_albums")
        return list(self.artist_discography.get(artist_id, []))

    def playlist_version(self, pid):
        return str(self.playlists[pid]["version"])

    # write
    def find_editable_playlists(self, name):
        return [k for k, p in self.playlists.items()
                if p["name"].casefold() == name.casefold() and p["editable"]]

    def create_playlist(self, name, description):
        self._log("create_playlist")
        return self.add_remote_playlist(name, [])

    def replace_playlist_tracks(self, pid, ids):
        self._log("replace_playlist_tracks")
        self.playlists[pid]["ids"] = list(ids)
        self.playlists[pid]["version"] += 1

    def delete_playlist(self, pid, *, owned):
        self._log("delete_playlist")
        del self.playlists[pid]

    def add_liked(self, ids):
        self._log("add_liked")
        self.liked.extend(i for i in ids if i not in self.liked)

    def remove_liked(self, ids):
        self._log("remove_liked")
        self.liked = [i for i in self.liked if i not in ids]

    def save_albums(self, ids):
        self.saved_albums.extend(i for i in ids if i not in self.saved_albums)

    def unsave_albums(self, ids):
        self.saved_albums = [i for i in self.saved_albums if i not in ids]

    def follow_artists(self, ids):
        self.followed.extend(i for i in ids if i not in self.followed)

    def unfollow_artists(self, ids):
        self.followed = [i for i in self.followed if i not in ids]


class _Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "meta").mkdir()
        self.fake = FakeBackend()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def plan(self, library: Library, mode: PushMode) -> dict:
        return dry_run_push("spotify", mode, backend=self.fake, library=library, workspace_root=self.root)

    def apply(self, plan: dict) -> None:
        execute_plan(self.fake, plan, workspace_root=self.root)

    def item(self, plan: dict, kind: str, label_part: str) -> dict:
        return next(i for i in plan["items"] if i["kind"] == kind and label_part in i["label"])


class MatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.m = Matcher.from_config(copy.deepcopy(DEFAULT_MATCHING))

    def test_remaster_suffix_is_ignored(self) -> None:
        score, conflict = self.m.score_track(lt("Bravo", "Band"), ct("x", "Bravo - 2009 Remaster", "Band"))
        self.assertGreaterEqual(score, self.m.accept)
        self.assertFalse(conflict)

    def test_live_version_is_a_conflict(self) -> None:
        _, conflict = self.m.score_track(lt("Foxtrot", "Band"), ct("x", "Foxtrot - Live", "Band"))
        self.assertTrue(conflict)

    def test_same_recording_on_several_releases_is_not_ambiguous(self) -> None:
        s = [Scored("a", "A", 0.97, False, "song|band"), Scored("b", "B", 0.96, False, "song|band")]
        self.assertEqual(decide(self.m, s).status, "resolved")

    def test_close_different_songs_are_ambiguous(self) -> None:
        s = [Scored("a", "A", 0.95, False, "song|band"), Scored("b", "B", 0.93, False, "song 2|band")]
        self.assertEqual(decide(self.m, s).status, "ambiguous")


class OrderingTests(unittest.TestCase):
    def test_local_order_wins_and_remote_extras_keep_their_neighbour(self) -> None:
        self.assertEqual(merge_order(["a", "c", "b"], ["a", "x", "b", "c"]), ["a", "x", "c", "b"])

    def test_remote_extra_before_any_shared_track_stays_at_head(self) -> None:
        self.assertEqual(merge_order(["a", "b"], ["x", "a"]), ["x", "a", "b"])

    def test_duplicates_are_matched_per_occurrence(self) -> None:
        self.assertEqual(merge_order(["a", "a", "b"], ["a", "b"]), ["a", "a", "b"])

    def test_drop_removes_remote_only_items(self) -> None:
        self.assertEqual(merge_order(["a"], ["a", "x", "y"], drop={"x"}), ["a", "y"])


class ResolverTests(_Workspace):
    def test_ladder_outcomes(self) -> None:
        lib = Library(liked_songs=[PlaylistTrack(track=t, record_meta=META) for t in [
            lt("Alpha", "Band", sid="t_a", service="spotify"),       # own id, valid
            lt("Charlie", "Band", sid="t_d", service="spotify"),     # own id points elsewhere
            lt("Bravo", "Band"),                                     # no id → search
            lt("Golf", "Band", isrc="US1234567890"),                 # ISRC
            lt("Foxtrot", "Band"),                                   # only a live version exists
            lt("Nothing Like This", "Nobody"),                       # not in catalog
            lt("My Demo", "Me", is_local=True),                      # local file
        ]])
        plan = self.plan(lib, PushMode.ADD)
        get = lambda label: self.item(plan, "track", label)  # noqa: E731
        self.assertEqual((get("Alpha")["status"], get("Alpha")["method"]), ("resolved", "own_id"))
        self.assertEqual((get("Charlie")["target_id"], get("Charlie")["method"]), ("t_c", "search"))
        self.assertEqual(get("Bravo")["target_id"], "t_b")
        self.assertEqual((get("Golf")["target_id"], get("Golf")["method"]), ("t_isrc", "isrc"))
        self.assertEqual(get("Foxtrot")["status"], "ambiguous")
        self.assertEqual(get("Nothing Like This")["status"], "unavailable")
        self.assertEqual(get("My Demo")["status"], "unsupported")
        self.assertFalse(plan["summary"]["can_apply"])
        self.assertIn("NEEDS YOUR DECISION", format_plan_report(plan))

    def test_cache_skips_second_search(self) -> None:
        lib = Library(liked_songs=[PlaylistTrack(track=lt("Bravo", "Band"), record_meta=META)])
        self.plan(lib, PushMode.ADD)
        self.fake.calls.clear()
        plan = self.plan(lib, PushMode.ADD)
        self.assertNotIn("search_narrow", self.fake.calls)
        self.assertEqual(self.item(plan, "track", "Bravo")["method"], "cache")

    def test_decisions_pick_and_exclude(self) -> None:
        fox, gone = lt("Foxtrot", "Band"), lt("Nothing Like This", "Nobody")
        lib = Library(liked_songs=[PlaylistTrack(track=t, record_meta=META) for t in (fox, gone)])
        set_decision("spotify", "track", track_key(fox), "t_live", workspace_root=self.root)
        set_decision("spotify", "track", track_key(gone), EXCLUDE, workspace_root=self.root)
        plan = self.plan(lib, PushMode.ADD)
        self.assertEqual(self.item(plan, "track", "Foxtrot")["method"], "your_choice")
        self.assertEqual(self.item(plan, "track", "Nothing")["status"], "excluded")
        self.assertTrue(plan["summary"]["can_apply"])


class PushAddTests(_Workspace):
    def test_create_update_and_like_without_removing_anything(self) -> None:
        existing = self.fake.add_remote_playlist("Mix", ["t_e", "t_a"])
        self.fake.liked = ["t_d"]
        lib = Library(
            playlists=[pl("Mix", [lt("Charlie", "Band"), lt("Alpha", "Band")]), pl("New", [lt("Bravo", "Band")])],
            liked_songs=[PlaylistTrack(track=lt("Alpha", "Band"), record_meta=META)],
        )
        plan = self.plan(lib, PushMode.ADD)
        self.apply(plan)
        self.assertEqual(self.fake.playlists[existing]["ids"], ["t_e", "t_c", "t_a"])
        new = self.fake.find_editable_playlists("New")
        self.assertEqual(self.fake.playlists[new[0]]["ids"], ["t_b"])
        self.assertEqual(sorted(self.fake.liked), ["t_a", "t_d"])

    def test_playlist_name_wins_over_stale_id(self) -> None:
        other = self.fake.add_remote_playlist("Something Else", ["t_d"])
        mix = self.fake.add_remote_playlist("Mix", [])
        lib = Library(playlists=[pl("Mix", [lt("Alpha", "Band")], sid="gone", service="spotify")])
        self.apply(self.plan(lib, PushMode.ADD))
        self.assertEqual(self.fake.playlists[mix]["ids"], ["t_a"])
        self.assertEqual(self.fake.playlists[other]["ids"], ["t_d"])
        self.assertEqual(len(self.fake.playlists), 2)

    def test_same_name_remote_playlists_need_a_decision(self) -> None:
        self.fake.add_remote_playlist("Mix", ["t_a"])
        second = self.fake.add_remote_playlist("Mix", ["t_c"])
        lib = Library(playlists=[pl("Mix", [lt("Echo", "Band")])])
        plan = self.plan(lib, PushMode.ADD)
        self.assertFalse(plan["summary"]["can_apply"])
        self.assertEqual(self.item(plan, "playlist", "Mix")["status"], "ambiguous")
        set_decision("spotify", "playlist", playlist_key("Mix"), second, workspace_root=self.root)
        plan = self.plan(lib, PushMode.ADD)
        self.apply(plan)
        self.assertEqual(self.fake.playlists[second]["ids"], ["t_c", "t_e"])

    def test_followed_only_playlist_gets_an_owned_copy(self) -> None:
        self.fake.add_remote_playlist("Mix", ["t_a"], editable=False)
        plan = self.plan(Library(playlists=[pl("Mix", [lt("Echo", "Band")])]), PushMode.ADD)
        self.assertTrue(any("not yours to edit" in w for w in plan["warnings"]))
        self.apply(plan)
        self.assertEqual(len(self.fake.playlists), 2)


class PushDeleteTests(_Workspace):
    def test_recorded_removals_are_applied(self) -> None:
        mix = self.fake.add_remote_playlist("Mix", ["t_a", "t_c"])
        old = self.fake.add_remote_playlist("Old", ["t_d"])
        self.fake.liked = ["t_a", "t_c"]
        record_liked_removed([lt("Charlie", "Band")], workspace_root=self.root)
        record_playlist_tracks_removed("Mix", [lt("Charlie", "Band")], workspace_root=self.root)
        record_playlist_removed("Old", workspace_root=self.root)
        record_liked_removed([lt("Alpha", "Band")], workspace_root=self.root)  # but still liked locally
        lib = Library(
            playlists=[pl("Mix", [lt("Alpha", "Band")])],
            liked_songs=[PlaylistTrack(track=lt("Alpha", "Band"), record_meta=META)],
        )
        self.apply(self.plan(lib, PushMode.DELETE))
        self.assertEqual(self.fake.playlists[mix]["ids"], ["t_a"])
        self.assertNotIn(old, self.fake.playlists)
        self.assertEqual(self.fake.liked, ["t_a"])

    def test_unliking_does_not_touch_playlists(self) -> None:
        mix = self.fake.add_remote_playlist("Mix", ["t_c"])
        self.fake.liked = ["t_c"]
        record_liked_removed([lt("Charlie", "Band")], workspace_root=self.root)
        lib = Library(playlists=[pl("Mix", [lt("Charlie", "Band")])])
        self.apply(self.plan(lib, PushMode.DELETE))
        self.assertEqual(self.fake.liked, [])
        self.assertEqual(self.fake.playlists[mix]["ids"], ["t_c"])

    def test_add_mode_ignores_removals(self) -> None:
        self.fake.liked = ["t_c"]
        record_liked_removed([lt("Charlie", "Band")], workspace_root=self.root)
        self.apply(self.plan(Library(), PushMode.ADD))
        self.assertEqual(self.fake.liked, ["t_c"])


class WipePushTests(_Workspace):
    def test_remote_becomes_a_mirror(self) -> None:
        mix = self.fake.add_remote_playlist("Mix", ["t_e", "t_a", "t_c"])
        extra = self.fake.add_remote_playlist("Extra", ["t_d"])
        self.fake.liked = ["t_d", "t_a"]
        self.fake.followed = ["ar_Other"]
        lib = Library(
            playlists=[pl("Mix", [lt("Charlie", "Band"), lt("Alpha", "Band")])],
            liked_songs=[PlaylistTrack(track=lt("Alpha", "Band"), record_meta=META)],
            followed_artists=[FollowedArtist(artist=Artist(name="Band"), record_meta=META)],
        )
        self.apply(self.plan(lib, PushMode.WIPE))
        self.assertEqual(self.fake.playlists[mix]["ids"], ["t_c", "t_a"])
        self.assertNotIn(extra, self.fake.playlists)
        self.assertEqual(self.fake.liked, ["t_a"])
        self.assertEqual(self.fake.followed, ["ar_Band"])
        self.assertNotIn("t_resist", self.fake.liked)


class ExecutorTests(_Workspace):
    def test_resume_skips_completed_steps_and_reuses_created_playlist(self) -> None:
        lib = Library(
            playlists=[pl("New", [lt("Alpha", "Band")])],
            liked_songs=[PlaylistTrack(track=lt("Charlie", "Band"), record_meta=META)],
        )
        plan = self.plan(lib, PushMode.ADD)
        self.fake.fail_on = "replace_playlist_tracks"
        with self.assertRaises(PushError):
            self.apply(plan)
        self.apply(plan)
        self.assertEqual(self.fake.calls.count("create_playlist"), 1)
        self.assertEqual(len(self.fake.playlists), 1)
        self.assertEqual(self.fake.liked, ["t_c"])

    def test_playlist_changed_since_dry_run_is_not_overwritten(self) -> None:
        mix = self.fake.add_remote_playlist("Mix", ["t_a"])
        plan = self.plan(Library(playlists=[pl("Mix", [lt("Charlie", "Band")])]), PushMode.ADD)
        self.fake.playlists[mix]["ids"].append("t_d")
        self.fake.playlists[mix]["version"] += 1
        with self.assertRaises(PushError) as ctx:
            self.apply(plan)
        self.assertEqual(ctx.exception.code, PushErrorCode.PLAN_STALE)
        self.assertEqual(self.fake.playlists[mix]["ids"], ["t_a", "t_d"])

    def test_prepare_push_replans_only_when_inputs_change(self) -> None:
        fox = lt("Foxtrot", "Band")
        lib = Library(liked_songs=[PlaylistTrack(track=fox, record_meta=META)])
        _, reason = prepare_push("spotify", PushMode.ADD, backend=self.fake, library=lib, workspace_root=self.root)
        self.assertEqual(reason, "new")
        _, reason = prepare_push("spotify", PushMode.ADD, backend=self.fake, library=lib, workspace_root=self.root)
        self.assertEqual(reason, "")
        set_decision("spotify", "track", track_key(fox), "t_live", workspace_root=self.root)
        plan, reason = prepare_push("spotify", PushMode.ADD, backend=self.fake, library=lib, workspace_root=self.root)
        self.assertEqual(reason, "changed")
        self.assertTrue(plan["summary"]["can_apply"])


class RemoteWipeTests(_Workspace):
    def test_wipe_then_seed_track(self) -> None:
        self.fake.add_remote_playlist("Mix", ["t_a"])
        self.fake.liked = ["t_a", "t_resist"]
        self.fake.saved_albums = ["al_1"]
        self.fake.followed = ["ar_Band"]
        plan = build_remote_wipe_plan(self.fake, workspace_root=self.root)
        self.apply(plan)
        self.assertEqual(self.fake.playlists, {})
        self.assertEqual(self.fake.liked, ["t_resist"])
        self.assertEqual((self.fake.saved_albums, self.fake.followed), ([], []))
        self.assertIn("one liked song", format_plan_report(plan).lower())

    def test_missing_seed_track_only_warns(self) -> None:
        self.fake = FakeBackend([c for c in CATALOG if c.id != "t_resist"])
        self.fake.liked = ["t_a"]
        plan = build_remote_wipe_plan(self.fake, workspace_root=self.root)
        self.apply(plan)
        self.assertEqual(self.fake.liked, [])
        self.assertTrue(plan["warnings"])


class NamesakeArtistTests(_Workspace):
    """Several artists can carry the same name; the user needs facts to choose."""

    def setUp(self) -> None:
        super().setUp()
        self.fake.artists = {
            "ar_g1": CatalogArtist(id="ar_g1", name="Geese", url="https://example.test/g1"),
            "ar_g2": CatalogArtist(id="ar_g2", name="Geese", url="https://example.test/g2"),
        }
        self.fake.artist_discography = {
            "ar_g1": ["3D Country (2023)", "Projector (2021)"],
            "ar_g2": ["BBQ Baby (2021)"],
        }
        self.fake.albums["al_bbq"] = CatalogAlbum(
            id="al_bbq", title="BBQ Baby", artists=["Geese"], artist_ids=["ar_g2"]
        )

    def _followed(self) -> FollowedArtist:
        # No Spotify id: the local row came from another service, so only the name is known.
        return FollowedArtist(
            artist=Artist(name="Geese", service_id="3578350", service="tidal"), record_meta=META
        )

    def test_candidates_carry_releases_and_a_link(self) -> None:
        plan = self.plan(Library(followed_artists=[self._followed()]), PushMode.ADD)
        item = self.item(plan, "artist", "Geese")
        self.assertEqual(item["status"], "ambiguous")
        details = {c["ref"]: c["detail"] for c in item["candidates"]}
        self.assertEqual(details["ar_g1"], "releases: 3D Country (2023) · Projector (2021)")
        self.assertEqual(details["ar_g2"], "releases: BBQ Baby (2021)")
        self.assertEqual(
            {c["url"] for c in item["candidates"]},
            {"https://example.test/g1", "https://example.test/g2"},
        )
        self.assertIn("different acts", item["message"])
        self.assertIn("3D Country (2023)", format_plan_details(plan))

    def test_an_artist_whose_record_you_own_is_listed_first(self) -> None:
        lib = Library(
            followed_artists=[self._followed()],
            saved_albums=[SavedAlbum(
                album=Album(name="BBQ Baby", artists=[Artist(name="Geese")]), record_meta=META
            )],
        )
        item = self.item(self.plan(lib, PushMode.ADD), "artist", "Geese")
        self.assertEqual(item["candidates"][0]["ref"], "ar_g2")
        self.assertIn("you have BBQ Baby by this artist", item["candidates"][0]["detail"])
        self.assertIn("listed first", item["message"])

    def test_near_misses_drop_out_when_the_name_matches_outright(self) -> None:
        self.fake.artists["ar_g4"] = CatalogArtist(id="ar_g4", name="Konkrete Geese")
        self.fake.artists["ar_g5"] = CatalogArtist(id="ar_g5", name="Geese 74")
        item = self.item(
            self.plan(Library(followed_artists=[self._followed()]), PushMode.ADD),
            "artist", "Geese",
        )
        self.assertEqual({c["ref"] for c in item["candidates"]}, {"ar_g1", "ar_g2"})

    def test_releases_are_only_fetched_for_a_real_decision(self) -> None:
        self.fake.artists = {"ar_solo": CatalogArtist(id="ar_solo", name="Geese")}
        self.plan(Library(followed_artists=[self._followed()]), PushMode.ADD)
        self.assertNotIn("artist_albums", self.fake.calls)


class ReportTests(_Workspace):
    def test_overview_leads_the_report_and_counts_deletions(self) -> None:
        from common.push.report import plan_counts, plan_overview

        mix = self.fake.add_remote_playlist("Mix", ["t_a", "t_d"])
        self.fake.liked = ["t_d"]
        self.fake.followed = ["ar_Other"]
        lib = Library(
            playlists=[pl("Mix", [lt("Alpha", "Band"), lt("Charlie", "Band")])],
            liked_songs=[PlaylistTrack(track=lt("Alpha", "Band"), record_meta=META)],
        )
        plan = self.plan(lib, PushMode.WIPE)
        n = plan_counts(plan)
        self.assertEqual((n["tracks_added"], n["tracks_removed"]), (1, 1))
        self.assertEqual((n["liked_added"], n["liked_removed"]), (1, 1))
        self.assertEqual(n["artists_removed"], 1)
        self.assertEqual(n["deletions"], 3)

        overview = plan_overview(plan)
        report = format_plan_report(plan)
        self.assertTrue(report.startswith(overview))
        self.assertIn("Pushes Local Data to Spotify", overview)
        self.assertIn("Write steps", overview)
        self.assertNotIn("Write steps", format_plan_details(plan))
        self.assertIn("Mix", report)
        self.assertEqual(self.fake.playlists[mix]["name"], "Mix")

    def test_overview_flags_open_decisions(self) -> None:
        from common.push.report import plan_counts, plan_overview

        lib = Library(liked_songs=[PlaylistTrack(track=lt("Foxtrot", "Band"), record_meta=META)])
        plan = self.plan(lib, PushMode.ADD)
        self.assertEqual(plan_counts(plan)["decisions"], 1)
        self.assertIn("Need your decision", plan_overview(plan))
        self.assertIn("0 conflicts were able to be resolved by decisions you made in the past", plan_overview(plan))
        self.assertIn("1 conflict still needs your decision", plan_overview(plan))
        self.assertIn("Blocked:", plan_overview(plan))

    def test_overview_names_past_picks(self) -> None:
        from common.push.report import conflict_context, format_plan_details, plan_counts, plan_overview

        fox = lt("Foxtrot", "Band")
        lib = Library(liked_songs=[PlaylistTrack(track=fox, record_meta=META)])
        self.plan(lib, PushMode.ADD)
        set_decision("spotify", "track", track_key(fox), "t_live", workspace_root=self.root)
        plan = self.plan(lib, PushMode.ADD)
        self.assertEqual(plan_counts(plan)["decisions"], 0)
        self.assertEqual(plan_counts(plan)["settled_by_you"], 1)
        overview = plan_overview(plan)
        self.assertIn("1 conflict was able to be resolved by decisions you made in the past", overview)
        self.assertIn("0 conflicts still need your decision", overview)
        self.assertIn("Settled by you", overview)
        self.assertIn("Your pick", format_plan_details(plan))
        self.assertEqual(
            conflict_context(0, 0),
            [],
        )


class PushBlockedGuidanceTests(unittest.TestCase):
    def test_valid_isrc(self) -> None:
        from common.push.isrc import valid_isrc

        self.assertTrue(valid_isrc("USRC17607839"))
        self.assertTrue(valid_isrc("us-rc1-76-07839"))
        self.assertFalse(valid_isrc(""))
        self.assertFalse(valid_isrc("not-an-isrc"))

    def test_guidance_mentions_picks_not_catalog_errors(self) -> None:
        from common.push.decisions import push_blocked_guidance, unsettled_decision_count

        plan = {
            "provider": "tidal",
            "summary": {"counts": {"unavailable": 12, "unsupported": 0}},
            "items": [
                {"status": "ambiguous", "kind": "track", "key": "k1"},
            ],
        }
        self.assertEqual(unsettled_decision_count(plan), 1)
        text = push_blocked_guidance(plan)
        self.assertIn("several possible matches", text)
        self.assertIn("Inspect Push Plan", text)
        self.assertIn("12 item(s) cannot be matched", text)


class LocalStateTests(_Workspace):
    def test_removal_records_are_provider_free_and_deduplicated(self) -> None:
        record_liked_removed([lt("Alpha", "Band")], workspace_root=self.root)
        record_liked_removed([lt("alpha", "band")], workspace_root=self.root)
        rows = load_sync_intents(workspace_root=self.root)["intents"]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("target_provider", rows[0])

    def test_fingerprint_tracks_decisions(self) -> None:
        lib = Library(liked_songs=[PlaylistTrack(track=lt("Alpha", "Band"), record_meta=META)])
        fp1 = library_fingerprint(lib, workspace_root=self.root)
        set_decision("spotify", "track", "x", EXCLUDE, workspace_root=self.root)
        self.assertNotEqual(fp1, library_fingerprint(lib, workspace_root=self.root))


if __name__ == "__main__":
    unittest.main()
