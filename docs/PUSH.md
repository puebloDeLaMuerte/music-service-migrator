# Push

Push writes **Local Data** (exactly what the TUI shows under "Local Data") to
**one** streaming service per run. Local edits are never tied to a service;
only a push is.

## Menu (per service)

| Entry | What it does |
| --- | --- |
| Push mode: Push-Add / Push-Delete / Wipe-Push | Selects what Push (dry run) and Push Now do |
| Push (dry run) | Reads the service library, matches everything, stores a plan, prints a report. Changes nothing. |
| Inspect Push Plan | Settle items with several possible matches: pick one (`1`-`9`), exclude (`x`), undo (`u`). Greyed out unless the last dry run for this mode still matches Local Data. |
| Push Now | Uses the last plan; re-plans first if anything changed; confirm; apply (resumable) |
| Wipe | Removes all playlists, liked songs, saved albums and followed artists on the service, then likes "Resist" by Wipers |

Backups of Local Data and loading saved libraries back live under
**Services → Local Files** (`backups/local/<date-time>/`; service Backup runs
land in `backups/<provider>/<date-time>/`). Loading replaces the library files
only; `work/meta/` (logins, plans, decisions, removal records) stays.

## Modes

- **Push-Add** — adds; never removes. Existing playlists keep tracks that
  are only on the service, next to the track they follow there.
- **Push-Delete** — Push-Add plus recorded local removals: unliked songs,
  tracks removed from playlists (P2A, dedupe, list views), removed playlists,
  albums and artists. Unliking a song does not remove it from playlists.
- **Wipe-Push** — the service becomes a mirror of Local Data; extras are
  removed piece by piece. No seed track.

Removals are recorded in `work/meta/sync_intent.json` (no provider field) and
only applied when the item is no longer in Local Data at push time and a
confident match exists on the service.

## Matching

Names are what counts; service ids are only a shortcut. For every track,
album and artist, in this order:

1. your decision from Inspect Push Plan (`work/meta/push_decisions.json`)
2. resolution cache from earlier dry runs (`work/meta/resolution_cache.json`)
3. the row's own id, if it came from the target service — kept only if that
   catalog entry still matches the name, otherwise dropped silently
4. an item already in the service library with the same title/artist
5. ISRC (tracks) / UPC (albums)
6. narrow catalog search, then broad search

"Can't be pushed" only when every step finds nothing (or for local files).
Several close candidates with different titles/artists become a decision
item and block Push Now until settled. Rules live in
`work/meta/push_matching.json` (written with defaults on first use):
thresholds, weights, duration tolerance, `ignore_patterns` (e.g. remaster,
feat., deluxe — treated as the same song) and `prompt_patterns` (live, remix,
acoustic, … — never auto-accepted).

Playlists are targeted by **name**: a decision, then the playlist's own id if
that remote playlist has the same name, then the single editable remote
playlist with that name. Several editable playlists with one name become a
decision item. A same-name playlist you can't edit gets an owned copy.
Playlists are never duplicated because of an id mismatch.

## Plans, stale plans, resume

- Plans: `work/meta/push_plans/{provider}_{mode}_latest.json` (items,
  per-playlist summary, warnings, ordered operations).
- A plan stores a fingerprint of Local Data, removal records, decisions and
  matching rules. Push Now re-plans when it differs, then asks to confirm.
- Dry runs are not resumable. Push Now records finished steps in
  `{provider}_{mode}_progress.json`; running it again continues. A playlist
  that changed on the service after the dry run is not overwritten — run the
  dry run again.
- Playlist order: each changed playlist is written in full (replace), so the
  final order is exactly the planned one.

## Code

- `common/push/` — provider-agnostic: `backend.py` (port), `resolver.py`,
  `matching.py`, `ordering.py`, `planner.py`, `executor.py`, `report.py`,
  `sync_intent.py`, `resolution_cache.py`, `fingerprint.py`, `plan_store.py`.
- `spotify/push_backend.py`, `tidal/push_backend.py` — primitives only.
- `tui/views/push_plan_modal.py` — Inspect Push Plan.
- Tests: `tests/test_push.py` (fake backend, no network).

Spotify needs write scopes; sign in again once (Account → Login) after
upgrading. New Spotify playlists are created private.
