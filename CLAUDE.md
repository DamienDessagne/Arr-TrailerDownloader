# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script (`TrailerDownloader.py`) that downloads movie/TV trailers from YouTube for
Radarr/Sonarr libraries. It runs either as a Radarr/Sonarr Custom Script (triggered via env vars on
import/rename events) or standalone from the command line against a library root folder.

There is no package structure, no build step, and no test suite — it's meant to be run directly with `py`/`python3`.

## Commands

- Run against a library folder: `py .\TrailerDownloader.py PATH_TO_LIBRARY_ROOT_FOLDER`
- Install dependencies: `pip install -r requirements.txt`
- No linter, formatter, or test suite is configured in this repo.
- Dependencies (`yt-dlp`, `yt-dlp-ejs`, `Requests`) are auto-upgraded by the script itself at startup (see
  AUTO UPDATE section below) — there's no separate update script to run manually.
- To sanity-check a change, run the script against a small local test library folder (or a single subfolder)
  and inspect stdout / the generated `Logs/*.txt` file (only created if `log_activity = True` in `config.ini`).

## Architecture

Everything lives in `TrailerDownloader.py`, organized into clearly-delimited `#### SECTION ####` blocks:

1. **CONFIG** — reads `config.ini` at startup into module-level globals (`TMDB_API_KEY`, `YOUTUBE_API_KEY`,
   `YOUTUBE_PARAMS` per language, `REENCODE_RULES`, `ENCODING_PARAMS`). Any new config option must be added to
   both `config.ini` and this parsing block.
2. **LOG** — `log()` prints and optionally appends to a timestamped file in `Logs/`. Old logs are pruned to
   `max_log_files` on startup. Most functions log their steps; keep that pattern when adding new logic.
3. **AUTO UPDATE** — `update_libs_if_needed()` runs unconditionally at import time (module level, before `main()`)
   and upgrades dependencies via `pip install --upgrade -r requirements.txt`, gated by a `.last_lib_update`
   marker file so it only runs once per `auto_update_libs_interval_minutes` (avoids slowing down every single
   Radarr/Sonarr-triggered launch). Controlled by `auto_update_libs` / `auto_update_libs_interval_minutes` in
   `config.ini`. `requests` and `yt_dlp` are deliberately imported *after* this check (not at the top of the
   file) so a freshly-upgraded version is picked up within the same run, without needing to restart the process.
4. **TMDB** — looks up TMDB id/details for a title (used to detect original language/title). No-ops silently
   if no TMDB API key is configured (language-dependent features are optional).
5. **FFMPEG** — `ffprobe`/`ffmpeg` wrappers to inspect and optionally re-encode a downloaded trailer, driven by
   `REENCODE_RULES` (source codec → target codec) and `ENCODING_PARAMS` (target codec → ffmpeg flags) from
   `config.ini`.
6. **YOUTUBE** — `get_youtube_trailer()` is the core per-title workflow: resolve language/title via TMDB,
   search YouTube Data API for a matching trailer, download it with `yt-dlp` into a temp dir, optionally
   re-encode, then move it into the media folder as `{Title} ({Year})-trailer.{ext}`.
7. **LIBRARY PROCESSING** — `download_trailers_for_library()` walks immediate subfolders of a library root,
   skips folders that already have a `*-trailer.*` file, and parses folder names to extract title/year (and
   TVDB id for TV, or TMDB id from an existing video filename for movies) before calling `get_youtube_trailer()`.
8. **MAIN** — dispatches based on how the script was invoked: Radarr env vars (`radarr_eventtype`, ...), Sonarr
   env vars (`sonarr_eventtype`, ...), or a CLI arg (library root path).

### Folder naming conventions this script depends on

Parsing in `download_trailers_for_library()` assumes TRaSH-Guides folder naming:
- Movies: `{Movie Title} ({Release Year})`
- TV shows: `{Series Title} ({Year}) {tvdb-{TvdbId}}`

If this convention changes, only `download_trailers_for_library` needs to be updated (per the README).

### Key external dependencies

- `yt-dlp` (+ `yt-dlp-ejs`) for the actual YouTube download — requires Deno on the system (`YTDLP_JS_ENGINE=deno`
  is set in-script). yt-dlp/yt-dlp-ejs need periodic updates to keep working as YouTube changes its protections
  (handled automatically by the AUTO UPDATE section above).
- `ffmpeg`/`ffprobe` must be on PATH for codec inspection and optional re-encoding.
- TMDB API (optional) and YouTube Data API v3 (required) — keys are read from `config.ini`, never hardcode keys.

## Working efficiently on this repo (token budget notes)

This is a ~400-line single file — there is no reason to spend tokens on broad codebase exploration:
- Just `Read` `TrailerDownloader.py` directly instead of dispatching Explore/general-purpose agents; the whole
  file fits comfortably in context.
- Don't invoke multi-agent Workflows or ultra-review for changes here — the project is too small to benefit,
  and it will burn far more tokens than the change is worth. A normal inline edit + a quick `/code-review` (low
  effort) is enough.
- Since there's no automated test suite, verification means running the script by hand against a sample library
  folder — mention this explicitly rather than claiming tests pass.
- Prefer small, targeted `Edit` calls over rewriting the whole file with `Write`.
