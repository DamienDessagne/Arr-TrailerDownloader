# Arr-TrailerDownloader
A Python script that downloads trailers from Youtube for a Radarr/Sonarr libraries.

# Requirements
- [Python](https://www.python.org/downloads/)
- [Deno](https://docs.deno.com/runtime/getting_started/installation/) (see https://github.com/yt-dlp/yt-dlp/wiki/EJS for more info)
- [ffmpeg](https://www.ffmpeg.org/): download and add its `bin` folder to your PATH environment variable.

# Installation
- Download and extract in a directory of your choice, visible to your **Radarr/Sonarr** installation.
- Install Python dependencies: 
```
pip install -r requirements.txt
```
- Open `config.ini` to provide your API keys and configure the script to your liking

# Adding trailers to an existing library
In a terminal, launch `py .\TrailerDownloader.py PATH_TO_MY_LIBRARY_ROOT_FOLDER`.

The script expect libraries folders to follow TRaSH-Guides folder naming convention:
- `{Movie Title} ({Release Year})` for movies libraries (see https://trash-guides.info/Radarr/Radarr-recommended-naming-scheme/#movie-folder-format)
- `{Series TitleYear} {tvdb-{TvdbId}}` for TV shows libraries (see https://trash-guides.info/Sonarr/Sonarr-recommended-naming-scheme/#optional-plex with the recommended TVDb instead of IMDb)

If your library is using a different naming convention, you will need to edit the script to match your own convention (only the `download_trailers_for_library` function).

# Have Radarr/Sonarr automatically grab trailers
In your Radarr/Sonarr interface, create a new Custom Script connection (`Settings -> Connect -> + -> Custom Script`) that triggers on import and on rename. In `Path`, enter the path to your local copy of `TrailerDownloader.py` (e.g., `C:\Arr-TrailerDownloader\TrailerDownloader.py`). If clicking the Test button works, the script will work.

# Automatic dependency updates
Downloading from YouTube requires up-to-date libraries, since YouTube regularly changes its protection algorithm. By default, the script automatically upgrades its dependencies (`yt-dlp`, `yt-dlp-ejs`, `Requests`) before running, at most once every `auto_update_libs_interval_minutes` (default: 60) so it doesn't slow down every single launch. This behavior can be configured (or disabled) in `config.ini`, under the `auto_update_libs` and `auto_update_libs_interval_minutes` settings.