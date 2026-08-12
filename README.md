# Arr-TrailerDownloader
A Python script that downloads trailers from Youtube for a Radarr/Sonarr libraries.

# Choosing how to run it
The script can be used in three different ways. Pick the one matching your setup:

| | How Radarr/Sonarr triggers it | Best if |
|---|---|---|
| **[Custom Script](#mode-1-custom-script)** | Runs the script once per event | Radarr/Sonarr are **not** in Docker, and run on the same machine as the script |
| **[Server](#mode-2-server)** | Sends a Webhook to a script that stays running | Radarr/Sonarr are in Docker (or on another machine), but you don't want to run this script in Docker |
| **[Docker](#mode-3-docker)** | Sends a Webhook to a container that stays running | You want everything in Docker, with no dependency to install by hand |

All three modes share the same `config.ini` and download trailers exactly the same way. Whatever mode you choose, you can also always [add trailers to an existing library](#adding-trailers-to-an-existing-library) manually.

# Requirements
Only needed for the **Custom Script** and **Server** modes. In **Docker** mode everything below is already included in the image.
- [Python](https://www.python.org/downloads/)
- [Deno](https://docs.deno.com/runtime/getting_started/installation/) (see https://github.com/yt-dlp/yt-dlp/wiki/EJS for more info)
- [ffmpeg](https://www.ffmpeg.org/): download and add its `bin` folder to your PATH environment variable.

# Installation
- Download and extract in a directory of your choice.
- For the **Custom Script** and **Server** modes, install the Python dependencies:
```
pip install -r requirements.txt
```
- Open `config.ini` to provide your API keys and configure the script to your liking. At the very least, you need a [Youtube API key](https://developers.google.com/youtube/v3/getting-started).

---

# Mode 1: Custom Script
The script is launched by Radarr/Sonarr each time an event happens. This requires Radarr/Sonarr to be able to run the script directly, so it only works if they are **not** running in Docker and share the same filesystem as the script.

In your Radarr/Sonarr interface, create a new Custom Script connection (`Settings -> Connect -> + -> Custom Script`) that triggers on import and on rename. In `Path`, enter the path to your local copy of `TrailerDownloader.py` (e.g., `C:\Arr-TrailerDownloader\TrailerDownloader.py`). If clicking the Test button works, the script will work.

# Mode 2: Server
The script stays running in the background and waits for Radarr/Sonarr to notify it over HTTP. Radarr/Sonarr only need to be able to reach it over the network, so this works even when they run in Docker or on another machine.

- Configure the `[Server]` section of `config.ini` (listening address, port, and optional credentials).
- Start the server with `run_server.bat` on Windows, or `run_server.sh` on Linux. Leave it running.
- In your Radarr/Sonarr interface, create a new **Webhook** connection (`Settings -> Connect -> + -> Webhook`) that triggers on import and on rename:
  - `URL`: `http://ADDRESS_OF_THE_MACHINE_RUNNING_THE_SCRIPT:8189/` (if Radarr runs in Docker on the same machine, `http://host.docker.internal:8189/` usually works)
  - `Method`: `POST`
  - `Username` / `Password`: only if you set them in the `[Server]` section of `config.ini`
- Click Test: it should succeed, and the server should log `Test successful`.

If Radarr/Sonarr see your libraries under different paths than the script does, fill in the `[PathMappings]` section of `config.ini` (see [Path mappings](#path-mappings)).

To start the server automatically with your machine, create a scheduled task (Windows) or a systemd service (Linux) calling the same script.

# Mode 3: Docker
Same as the Server mode, but Python, Deno and ffmpeg are already installed inside the image, so there is nothing to install on your machine.

- Copy `config.ini` next to `docker-compose.yml` and fill in your API keys.
- Edit the `volumes` section of `docker-compose.yml` to point to your libraries.
- Start it:
```
docker compose up -d
```
- In your Radarr/Sonarr interface, create a **Webhook** connection exactly as described in [Mode 2](#mode-2-server), using:
  - `http://trailerdownloader:8189/` if Radarr/Sonarr run in Docker on the same Docker network
  - `http://ADDRESS_OF_THE_DOCKER_HOST:8189/` otherwise

## Path mappings
This is the most common source of problems in Server and Docker modes: Radarr/Sonarr send the path of the imported item, but that path must also be valid **for this script**.

The simplest solution is to mount your libraries at the same paths in both containers. When that isn't possible, declare the differences in the `[PathMappings]` section of `config.ini`. For instance, if Radarr sees your movies in `/movies` while this script sees them in `D:\Movies`:
```ini
[PathMappings]
mappings =
    /movies -> D:\Movies
    /tv -> D:\TV Shows
```

---

# Adding trailers to an existing library
In a terminal, launch `py .\TrailerDownloader.py PATH_TO_MY_LIBRARY_ROOT_FOLDER`. This works in every mode (in Docker, use `docker compose exec trailerdownloader python TrailerDownloader.py /movies`).

The script expect libraries folders to follow TRaSH-Guides folder naming convention:
- `{Movie Title} ({Release Year})` for movies libraries (see https://trash-guides.info/Radarr/Radarr-recommended-naming-scheme/#movie-folder-format)
- `{Series TitleYear} {tvdb-{TvdbId}}` for TV shows libraries (see https://trash-guides.info/Sonarr/Sonarr-recommended-naming-scheme/#optional-plex with the recommended TVDb instead of IMDb)

If your library is using a different naming convention, you will need to edit the script to match your own convention (only the `download_trailers_for_library` function).

# Automatic dependency updates
Downloading from YouTube requires up-to-date libraries, since YouTube regularly changes its protection algorithm. By default, the script automatically upgrades its dependencies (`yt-dlp`, `yt-dlp-ejs`, `Requests`) before running, at most once every `auto_update_libs_interval_minutes` (default: 60) so it doesn't slow down every single launch. This behavior can be configured (or disabled) in `config.ini`, under the `auto_update_libs` and `auto_update_libs_interval_minutes` settings.

In Server and Docker modes, the script also checks for updates between downloads, and automatically restarts itself when a new version was installed.
