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

# Notification triggers (all modes)
Whichever mode you use, the connection is created from the same place in Radarr and in Sonarr: `Settings -> Connect -> + -> ...`, and the same **Notification Triggers** apply. Only two of them matter:

| Trigger | Tick it? | Why |
|---|---|---|
| **On Import** (called *On Download* in older versions) | **Yes** | The event that actually matters: a movie/episode was just imported, so its folder now needs a trailer. |
| **On Rename** | **Yes** | The trailer is saved as `{Title} ({Year})-trailer.ext` next to your media. Re-running the script after a rename keeps a trailer in the renamed folder. |
| **On Upgrade** | No | Fired when an existing file is replaced by a better version. The folder already has its trailer, so the script deliberately ignores these events. Ticking it only causes runs that do nothing. |
| Any other trigger (On Grab, On Health Issue, On Series Add, ...) | No | Not handled. They are ignored, but they wake the script up for nothing. |

The script also answers Radarr/Sonarr's **Test** button: it succeeds only if you filled in your Youtube API key in `config.ini`, so a successful test means the setup is correct.

**Radarr vs Sonarr**: nothing to configure differently, the same script handles both. The only functional difference is that Radarr provides the TMDB id of the movie directly, while for a TV show the script looks it up on TMDB from the title and year (which only matters if you set a TMDB API key to enable the language-dependant features).

---

# Mode 1: Custom Script
Radarr/Sonarr launch the script themselves, once per event. This requires them to be able to run the script directly, so it only works if they are **not** running in Docker and share the same filesystem as the script.

1. In Radarr: `Settings -> Connect -> + -> Custom Script`.
2. `Name`: whatever you like, e.g. `Trailer Downloader`.
3. Tick **On Import** and **On Rename** (see [Notification triggers](#notification-triggers-all-modes)).
4. `Path`: the full path to your local copy of `TrailerDownloader.py`, e.g. `C:\Arr-TrailerDownloader\TrailerDownloader.py`.
5. Click **Test**. If it succeeds, save.
6. Repeat the exact same steps in Sonarr.

Nothing else to configure: Radarr/Sonarr pass the title, year and folder of the imported item to the script through environment variables, so there are no paths to map.

> On Windows, Radarr runs the `.py` file through the file association created by the Python installer. If the Test button fails with a permission or "not executable" error, the usual fix is to make sure Python is installed for all users and that `.py` files are associated with it.

# Mode 2: Server
The script stays running in the background and waits for Radarr/Sonarr to notify it over HTTP. They only need to be able to reach it over the network, so this works even when they run in Docker or on another machine.

**Start the server:**
1. Configure the `[Server]` section of `config.ini` (listening address, port, and optional credentials).
2. Run `run_server.bat` on Windows, or `run_server.sh` on Linux, and leave it running. It should print `Listening for Radarr/Sonarr webhooks on http://0.0.0.0:8189`.
3. To start it automatically with your machine, create a scheduled task (Windows) or a systemd service (Linux) calling that same script.

**Connect Radarr/Sonarr to it:**
1. In Radarr: `Settings -> Connect -> + -> Webhook`.
2. `Name`: whatever you like, e.g. `Trailer Downloader`.
3. Tick **On Import** and **On Rename**.
4. `URL`: see [Which URL should I use?](#which-url-should-i-use) below.
5. `Method`: `POST`.
6. `Username` / `Password`: leave empty, unless you set them in the `[Server]` section of `config.ini`.
7. Click **Test**: it should succeed, and the server should print `Test successful`.
8. Repeat the exact same steps in Sonarr.

Finally, check [Path mappings](#path-mappings): unlike the Custom Script mode, Radarr/Sonarr now send **paths**, which have to be valid for the script too.

# Mode 3: Docker
Same as the Server mode, but Python, Deno and ffmpeg are already installed inside the image, so there is nothing to install on your machine.

1. Copy `config.ini` next to `docker-compose.yml` and fill in your API keys.
2. Edit the `volumes` section of `docker-compose.yml` so your libraries are visible to the container. **Mount them at the same paths Radarr/Sonarr use**, otherwise you'll need [Path mappings](#path-mappings).
3. Start it:
```
docker compose up -d
```
4. Check that it started with `docker compose logs -f`.
5. Create the **Webhook** connection in Radarr and Sonarr exactly as described in [Mode 2](#mode-2-server).

## Which URL should I use?
The URL to enter in the Webhook connection depends on where Radarr/Sonarr run *relative to the script*. `8189` is the default port from `config.ini`.

| Radarr/Sonarr run... | ...and the script runs... | URL to use |
|---|---|---|
| In Docker | In Docker, same Docker network | `http://trailerdownloader:8189/` (the container name) |
| In Docker | Directly on the same machine | `http://host.docker.internal:8189/` |
| Directly on the machine | In Docker on that same machine | `http://localhost:8189/` |
| Directly on the machine | Directly on that same machine | `http://localhost:8189/` (but [Mode 1](#mode-1-custom-script) is simpler) |
| On another machine | Anywhere | `http://IP_OF_THE_MACHINE_RUNNING_THE_SCRIPT:8189/` |

If Radarr/Sonarr are on another machine, also make sure `host` is set to `0.0.0.0` in `config.ini` (the default) so the server accepts connections from outside, and that your firewall allows the port. Setting a `username`/`password` is recommended in that case.

## Path mappings
This is the most common source of problems in Server and Docker modes: Radarr/Sonarr send the path of the imported item, and that path must also be valid **for this script**. A Radarr in Docker typically reports `/movies/Blade Runner (1982)`, which means nothing to a script running on Windows.

The simplest solution is to mount your libraries at the same paths everywhere. When that isn't possible, declare the differences in the `[PathMappings]` section of `config.ini`. For instance, if Radarr sees your movies in `/movies` while this script sees them in `D:\Movies`:
```ini
[PathMappings]
mappings =
    /movies -> D:\Movies
    /tv -> D:\TV Shows
```
The script logs every path it translates, so if trailers don't appear, look for a `Mapped path ... to ...` line (or the absence of one) in the logs.

## Cookies in Docker
Cookies are only needed to download age-restricted videos; when they can't be read, the download is simply retried anonymously. `yt_dlp_cookies_browser` (reading cookies straight from an installed browser) can never work in Docker, since no browser is installed in the container. Use `yt_dlp_cookies_file` instead: export a `cookies.txt` from your browser (e.g. with the "Get cookies.txt LOCALLY" extension), mount it in the container, and set `yt_dlp_cookies_file` to its path *inside* the container:
```yaml
# docker-compose.yml
volumes:
  - ./cookies.txt:/app/cookies.txt
```
```ini
# config.ini
yt_dlp_cookies_file = /app/cookies.txt
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
