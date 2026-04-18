# music-service-migrator

Toolkit for managing, analysing, and migrating playlists across music streaming services.

## Features (current & planned)

- **Spotify export** – fetch all playlists & liked songs to JSON (delegates to [my-spotify-playlists-downloader](https://github.com/novama/my-spotify-playlists-downloader))
- **Duplicate detection** – find repeated tracks within and across playlists
- **Album detection** – flag playlists that are really just full albums
- **Tidal support** – (planned) import, export, and manage Tidal playlists
- **Migration** – (planned) migrate playlists from Spotify to Tidal with fuzzy track matching

## Project structure

```
.
├── cli.py                 # unified CLI entry point
├── common/                # service-agnostic models, config, logging
├── spotify/               # Spotify adapter & analysis tools
├── tidal/                 # (future) Tidal adapter
├── migrator/              # cross-service migration logic
└── lib/                   # vendored / submoduled third-party repos
    └── my-spotify-playlists-downloader/
```

## Quick start

```bash
# clone with submodules
git clone --recurse-submodules git@github.com:puebloDeLaMuerte/music-service-migrator.git
cd music-service-migrator

# create a local virtual environment
python3 -m venv .venv
source .venv/bin/activate

# install dependencies
pip install -r requirements.txt

# configure credentials
cp .env.example .env
# edit .env with your Spotify Client ID & Secret

# run
python cli.py spotify export --split --liked-songs
python cli.py spotify dedupe
python cli.py spotify detect-albums
```

## Spotify developer setup

See [lib/my-spotify-playlists-downloader/docs/en/SPOTIFY_DEVELOPER_SETUP.md](lib/my-spotify-playlists-downloader/docs/en/SPOTIFY_DEVELOPER_SETUP.md) for a step-by-step guide.

## License

MIT
