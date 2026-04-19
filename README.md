```text
        ~ ~ ~ ~ ~         ((( ((( (((
          p M i g r a t o r
        ~ ~ ~ ~ ~         ((( ((( (((
           ~ ~ ~             ((( (((
            ~ ~               ((( (
```

# music-service-migrator

A **toolkit for migrating library data between Spotify and Tidal**, with **extra features to inspect and clean up** the copies you keep on disk.

**pMigrator** is **local-first**: a **terminal UI** plus **CLI** commands so **OAuth tokens and exports stay on your machine**, not in a third-party “migration service.”

---

## What it does

**Across Spotify and Tidal** you can **pull** your library (playlists, liked tracks, saved albums, followed artists) to **JSON under your workspace**, then **browse** that data in the TUI.

- **Dedupe** — find duplicate tracks within and across playlists.
- **Playlist → Album** — flag playlists that are really full albums; **find** those albums **in** playlists **and add them to your saved library as proper albums** (extract / extract+delete flows in the TUI).
- **Images** — fetch playlist artwork at high resolution.
- **Settings** — tune paths and behaviour without editing code.

**Tidal:** **Import (pull) from Tidal** is implemented. **Push** back to Tidal is not the focus yet.

**Spotify:** **Pull** is implemented; **push** is planned.

**Cross-service migration** (moving playlists from one service to the other inside the app) is **planned**; today the emphasis is **pull**, **local JSON**, and **cleanup / analysis** tools.

---

## Why it exists

Switching between Spotify and Tidal is a good moment to **dedupe and fix messy playlists** — and, if you prefer, to **keep API access and files under your control** instead of delegating to another company’s servers.

---

## What you need

### Accounts

- **Spotify** and/or **Tidal** — the same consumer accounts you use in the official apps.
- For **Spotify’s Web API**, their rules apply (e.g. **Premium** can matter for some endpoints — you’ll see clear errors on first pull if something blocks you).

### Spotify — API credentials (`.env`)

1. Create an app in the **[Spotify Developer Dashboard](https://developer.spotify.com/dashboard)**.
2. Note **Client ID** and **Client Secret**.
3. Add a **Redirect URI** matching `.env` (default: `http://127.0.0.1:8000/callback`).
4. Copy `.env.example` to `.env` and set `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`.

First use runs **OAuth in the browser**; tokens are cached under your workspace (see `spotify/client.py` / `work/meta/`).

### Tidal — session file (`tidalapi`)

Uses **[python-tidal](https://github.com/EbbLabs/python-tidal)** ([`tidalapi` on PyPI](https://pypi.org/project/tidalapi/)): **device login** writes a **JSON session** (default `<work_dir>/meta/tidal_session.json`). Override with **`TIDAL_SESSION_FILE`** in `.env` if you want another path.

Complete login once (TUI **Service** view for Tidal, or the snippet in `tidal/client.py`). You need a **valid Tidal subscription** for catalog access.

### General

- **Python 3.10+** recommended.
- `pip install -r requirements.txt` inside a **virtualenv** (e.g. `.venv`).

Optional env: **`WORK_DIR`**, **`LOG_LEVEL`**, **`TUI_STATUS_FLASH_SECONDS`**, **`P2A_ALWAYS_KEEP_LEFTOVERS`** — see `.env.example` and `common/config.py`.

---

## Developer setup (dashboards & first login)

**Spotify** — step-by-step app registration, redirect URI, and dashboard settings:

[lib/my-spotify-playlists-downloader/docs/en/SPOTIFY_DEVELOPER_SETUP.md](lib/my-spotify-playlists-downloader/docs/en/SPOTIFY_DEVELOPER_SETUP.md)

**Tidal** — no Spotify-style “developer app” in the same sense; auth is **session file + device login** via `tidalapi`. Authoritative details (default paths, `TIDAL_SESSION_FILE`, interactive login, and a minimal one-shot login snippet) live in:

[`tidal/client.py`](tidal/client.py)

Use the **Tidal** screen in the TUI for guided login, or run the `python -c "…"` flow described there once so `tidal_session.json` exists before **Pull**.

---

## Quick start

```bash
git clone --recurse-submodules https://github.com/puebloDeLaMuerte/music-service-migrator.git
cd music-service-migrator

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env for Spotify if you use Spotify; complete Tidal session login if you use Tidal.

python cli.py                 # full TUI (default)
python cli.py spotify pull
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
| `spotify/`, `tidal/` | Service adapters (auth + pull/export to disk) |
| `tui/` | Textual UI — navigation, service views, tools |
| `lib/my-spotify-playlists-downloader/` | Vendored **Spotify** setup docs; optional reference |

---

## Open source

Built with [Textual](https://github.com/Textualize/textual), [Click](https://github.com/pallets/click), [spotipy](https://github.com/spotipy-dev/spotipy), [python-tidal](https://github.com/EbbLabs/python-tidal), [python-dotenv](https://github.com/theskumar/python-dotenv).

---

## License

No license is specified in this README; that is a deliberate project-level choice and not set here.

---

Philipp Tögel · [github.com/puebloDeLaMuerte/music-service-migrator](https://github.com/puebloDeLaMuerte/music-service-migrator)
