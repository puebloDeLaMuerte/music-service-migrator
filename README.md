```
        ~ ~ ~ ~ ~         ((( ((( (((
          p M i g r a t o r
        ~ ~ ~ ~ ~         ((( ((( (((
           ~ ~ ~             ((( (((
            ~ ~               ((( (
```

# music-service-migrator

**pMigrator** is a **local-first** toolkit for managing, inspecting, and migrating music libraries across streaming services. It gives you a **terminal UI** (and matching **CLI** commands) so your **OAuth tokens and library exports stay on your machine** — not in someone else’s cloud dashboard.

---

## What it does

- **Pull** your **Spotify** and/or **Tidal** library (playlists, liked tracks, saved albums, followed artists) into **JSON under your workspace** for backup and analysis.
- **Browse** that data in the TUI: saved albums, artists, songs, playlists.
- **Dedupe** — find duplicate tracks within and across playlists.
- **Playlist → Album** — detect when a playlist is really a full album and optionally extract it.
- **Images** — fetch playlist artwork at high resolution.
- **Settings** — tune paths and behaviour without editing code.

Spotify **push** / Tidal **push** and full cross-service **migration** are planned; **pull** and **local data** tools are the focus today.

---

## Why it exists

Moving between Spotify, Tidal, and friends is a good moment to **clean up duplicates and odd playlists** — and to avoid handing **API access** to a third-party “migration as a service” if you’d rather **own the data and the credentials**. This project is built for that workflow: **you** create the developer / API access, **you** authenticate, **you** keep the files.

---

## What you need

### Accounts

- A normal **Spotify** and/or **Tidal** **user account** (the same ones you use in the official apps).
- For **Spotify API** use, Spotify currently expects the **developer app owner** to satisfy their product rules (e.g. **Premium** can matter for some API behaviour — see errors when you first pull).

### Spotify — API app access

1. Create an app in the **[Spotify Developer Dashboard](https://developer.spotify.com/dashboard)**.
2. Note **Client ID** and **Client Secret**.
3. Add a **Redirect URI** that matches what you put in `.env` (default in this project: `http://127.0.0.1:8000/callback`).
4. Copy `.env.example` to `.env` and set:

   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - `SPOTIFY_REDIRECT_URI`

The first time you use Spotify from the app, you’ll complete **OAuth in the browser**; tokens are stored under your workspace (see `spotify/client.py` / `work/meta/`).

More detail: [lib/my-spotify-playlists-downloader/docs/en/SPOTIFY_DEVELOPER_SETUP.md](lib/my-spotify-playlists-downloader/docs/en/SPOTIFY_DEVELOPER_SETUP.md) (vendored reference).

### Tidal — session file (tidalapi)

Tidal uses **[python-tidal](https://github.com/EbbLabs/python-tidal)** ([`tidalapi` on PyPI](https://pypi.org/project/tidalapi/)) with a **device login** flow that writes a **JSON session file** (default: `<work_dir>/meta/tidal_session.json`).

1. Complete a one-time login from a terminal (the TUI **Service** view can guide you; or run the snippet shown in `tidal/client.py` if you prefer the CLI).
2. Optionally set **`TIDAL_SESSION_FILE`** in `.env` to override the path (project-relative or absolute).

You need a **valid Tidal subscription** for catalog access; credentials are **not** sent to this project’s author — they stay in your session file.

### General

- **Python 3.10+** recommended.
- Dependencies: `pip install -r requirements.txt` (use a **virtualenv**, e.g. `.venv`).

Optional:

- **`WORK_DIR`** — where JSON and metadata are stored (default `./work`).
- **`LOG_LEVEL`**, **`TUI_STATUS_FLASH_SECONDS`**, **`P2A_ALWAYS_KEEP_LEFTOVERS`** — see `.env.example` and `common/config.py`.

---

## Quick start

```bash
git clone --recurse-submodules https://github.com/puebloDeLaMuerte/music-service-migrator.git
cd music-service-migrator

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env — at minimum Spotify vars if you use Spotify; configure Tidal session as above if you use Tidal.

python cli.py                 # full TUI (default)
python cli.py spotify pull    # open TUI on Spotify with pull in mind
python cli.py tidal pull
python cli.py data dedupe
python cli.py data playlist2album
python cli.py data playlistimages
```

---

## Project layout (high level)

| Path | Role |
|------|------|
| `cli.py` | Click CLI — launches the TUI or opens a specific screen |
| `common/` | Shared models, config, storage paths, dedupe helpers |
| `spotify/`, `tidal/` | Service adapters (auth + export/pull) |
| `tui/` | Textual UI — navigation, service views, tools |
| `lib/my-spotify-playlists-downloader/` | Vendored docs (Spotify setup); not required at runtime for the current Python path |

---

## Open source

Built with [Textual](https://github.com/Textualize/textual), [Click](https://github.com/pallets/click), [spotipy](https://github.com/spotipy-dev/spotipy), [python-tidal](https://github.com/EbbLabs/python-tidal), [python-dotenv](https://github.com/theskumar/python-dotenv).

---

## License

MIT

---

Philipp Tögel · [github.com/puebloDeLaMuerte/music-service-migrator](https://github.com/puebloDeLaMuerte/music-service-migrator)
