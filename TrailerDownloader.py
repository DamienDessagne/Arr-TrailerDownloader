import base64
import hmac
import json
import os
import queue
import re
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote
from datetime import datetime
import configparser
import subprocess
import tempfile

# Set current directory to script location
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Tell yt-dlp to use Deno
os.environ['YTDLP_JS_ENGINE'] = 'deno'

############################# CONFIG #############################

# Load configuration from external file
CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
# By default configparser also accepts ':' as a key/value separator, which breaks EncodingParams entries for
# ffmpeg options that contain a colon themselves, e.g. `video.hevc_nvenc.b:v = 0` (silently parsed as a "b"
# key with value "v = 0"). Restrict it to '=' only so such option names work as expected.
config = configparser.ConfigParser(delimiters=('=',))
if not config.read(CONFIG_FILE_PATH):
    print(f"ERROR: no configuration file found at {CONFIG_FILE_PATH}.")
    print("Copy config.ini from the repository next to the script (or mount it there in Docker) and fill in your API keys.")
    sys.exit(1)

# Whether to log everything the script does
LOG_ACTIVITY = config.getboolean('Config', 'log_activity')

# Max number of log files to keep
MAX_LOG_FILES = config.getint('Config', 'max_log_files', fallback=10)

# Whether to automatically keep dependencies (yt-dlp, yt-dlp-ejs, Requests) up to date
AUTO_UPDATE_LIBS = config.getboolean('Config', 'auto_update_libs', fallback=True)

# Minimum number of minutes between two automatic dependency updates
AUTO_UPDATE_LIBS_INTERVAL_MINUTES = config.getint('Config', 'auto_update_libs_interval_minutes', fallback=60)

# Your TMDB API key, if not provided, language-dependant features won't be activated
TMDB_API_KEY = config.get('Config', 'tmdb_api_key')

# Youtube API key (see https://developers.google.com/youtube/v3/getting-started)
YOUTUBE_API_KEY = config.get('Config', 'youtube_api_key')

# Browser name to get cookies from to download from YouTube. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for details
YT_DLP_COOKIES_BROWSER = config.get('Config', 'yt_dlp_cookies_browser')

# Path to a cookies.txt file to download from YouTube. Unlike reading cookies from a browser, this works in Docker.
YT_DLP_COOKIES_FILE = config.get('Config', 'yt_dlp_cookies_file', fallback='')

# Language-dependant parameters to search for trailers on Youtube
YOUTUBE_PARAMS = {"default": {
    "use_original_movie_name": config.getboolean('YoutubeParams.default', 'use_original_movie_name'),
    "search_keywords": config.get('YoutubeParams.default', 'search_keywords')
}}

# Load language-specific parameters
for section in config.sections():
    if section.startswith('YoutubeParams.') and section != 'YoutubeParams.default':
        language_code = section.split('.')[1]  # Extract language code (e.g., 'fr' from 'YOUTUBE_PARAMS.fr')
        YOUTUBE_PARAMS[language_code] = {
            "use_original_movie_name": config.getboolean(section, 'use_original_movie_name'),
            "search_keywords": config.get(section, 'search_keywords')
        }

# Load re-encoding rules from config
REENCODE_RULES = {}
if config.has_section('ReencodeRules'):
    for key, value in config.items('ReencodeRules'):
        codec_type, source_codec = key.split('.')
        if codec_type not in REENCODE_RULES:
            REENCODE_RULES[codec_type] = {}
        REENCODE_RULES[codec_type][source_codec] = value

# Load encoding parameters from config
ENCODING_PARAMS = {}
if config.has_section('EncodingParams'):
    for key, value in config.items('EncodingParams'):
        parts = key.split('.')
        if len(parts) == 3:  # Format: codec_type.target_codec.param
            codec_type, target_codec, param = parts
            if codec_type not in ENCODING_PARAMS:
                ENCODING_PARAMS[codec_type] = {}
            if target_codec not in ENCODING_PARAMS[codec_type]:
                ENCODING_PARAMS[codec_type][target_codec] = {}
            ENCODING_PARAMS[codec_type][target_codec][param] = value

# Server mode parameters (only used when the script is started with --serve)
SERVER_HOST = config.get('Server', 'host', fallback='0.0.0.0')
SERVER_PORT = config.getint('Server', 'port', fallback=8189)
SERVER_USERNAME = config.get('Server', 'username', fallback='')
SERVER_PASSWORD = config.get('Server', 'password', fallback='')

# Path mappings, to translate the paths sent by Radarr/Sonarr into paths this script can actually reach.
# Stored as a list of (path_seen_by_arr, path_seen_by_this_script) tuples.
PATH_MAPPINGS = []
for mapping_line in config.get('PathMappings', 'mappings', fallback='').splitlines():
    mapping_line = mapping_line.strip()
    if '->' in mapping_line:
        arr_path, local_path = mapping_line.split('->', 1)
        PATH_MAPPINGS.append((arr_path.strip(), local_path.strip()))

############################# LOG #############################

# Create a new log file
LOG_FOLDER_NAME = "Logs"
if LOG_ACTIVITY:
    if not os.path.exists(LOG_FOLDER_NAME):
        os.makedirs(LOG_FOLDER_NAME)


    # Clean old logs before creating a new one
    def clean_old_logs():
        files = [os.path.join(LOG_FOLDER_NAME, f) for f in os.listdir(LOG_FOLDER_NAME) if
                 os.path.isfile(os.path.join(LOG_FOLDER_NAME, f))]
        if len(files) >= MAX_LOG_FILES:
            # Sort files by modification time (oldest first)
            files.sort(key=os.path.getmtime)
            # Remove oldest files to respect the limit (keeping room for the new one)
            files_to_delete = files[:len(files) - MAX_LOG_FILES + 1]
            for f in files_to_delete:
                try:
                    os.remove(f)
                except:
                    pass


    clean_old_logs()

LOG_FILE_NAME = datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
LOG_FILE_PATH = os.path.join(LOG_FOLDER_NAME, LOG_FILE_NAME)


# Serializes writes, as server mode logs from several threads at once
LOG_LOCK = threading.Lock()


# Echoes the given text and appends the given text to the log file's content
def log(log_text):
    with LOG_LOCK:
        print(log_text, flush=True)
        if LOG_ACTIVITY:
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
                log_file.write(log_text + "\n")


############################# AUTO UPDATE #############################

# File used to remember when dependencies were last auto-updated
LIB_UPDATE_MARKER_FILE = ".last_lib_update"


# Upgrades yt-dlp, yt-dlp-ejs and Requests via pip, at most once every AUTO_UPDATE_LIBS_INTERVAL_MINUTES,
# so the script keeps working when YouTube changes its protections without requiring manual maintenance.
# Returns True if a dependency was actually upgraded (which server mode uses to know it should restart).
def update_libs_if_needed():
    if not AUTO_UPDATE_LIBS:
        return False

    if os.path.exists(LIB_UPDATE_MARKER_FILE):
        elapsed_minutes = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(LIB_UPDATE_MARKER_FILE))).total_seconds() / 60
        if elapsed_minutes < AUTO_UPDATE_LIBS_INTERVAL_MINUTES:
            return False

    upgraded = False
    log("Checking for dependency updates...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "-r", "requirements.txt"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        # pip only prints this line when it actually installed a new version
        upgraded = "Successfully installed" in result.stdout.decode(errors='ignore')
        log("Dependencies upgraded." if upgraded else "Dependencies are up to date.")
    except subprocess.CalledProcessError as e:
        log(f"Failed to update dependencies: {e.stderr.decode(errors='ignore')}")

    # Touch the marker file even on failure, so a persistently failing update doesn't slow down every launch
    open(LIB_UPDATE_MARKER_FILE, "a").close()
    os.utime(LIB_UPDATE_MARKER_FILE, None)

    return upgraded


update_libs_if_needed()

# Imported only after the update check above, so a freshly-upgraded version is picked up within the same run
import requests
import yt_dlp

############################# JSON #############################

# Fetches and parses the JSON at the given URL.
def fetch_json(url):
    log(f"Issuing request to {url}")
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


############################# TMDB #############################

# Searches the TMDB ID based on the title and the year. Returns '' if not found.
def get_tmbd_id(title, year, is_movie):
    if TMDB_API_KEY == "YOUR_API_KEY":
        return None

    tmdb_search_url = f"https://api.themoviedb.org/3/search/{"movie" if is_movie else "tv"}?api_key={TMDB_API_KEY}&query={quote(title)}&year={year}"
    log(f"Searching for TMDB {"Movie" if is_movie else "TV Show"} ID...")
    tmdb_search_results = fetch_json(tmdb_search_url)
    if tmdb_search_results["total_results"] >= 1:
        log(f"TMDB ID found: {tmdb_search_results["results"][0]["id"]}")
        return tmdb_search_results["results"][0]["id"]
    return None


# Returns the JSON info on TMDB for the given movie ID. If no info can be found, None is returned
def get_tmdb_info(tmdb_id, is_movie):
    if TMDB_API_KEY == "YOUR_API_KEY" or tmdb_id is None:
        return None

    log(f"Querying TMDB for details of {"Movie" if is_movie else "TV Show"} #{tmdb_id} ...")
    return fetch_json(f"https://api.themoviedb.org/3/{"movie" if is_movie else "tv"}/{tmdb_id}?api_key={TMDB_API_KEY}")


############################# FFMPEG #############################

# Uses ffprobe to extract the video codec from the given file
def get_video_codec_info(file_path):
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name', '-of', 'default=nw=1:nk=1', file_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    video_codec = result.stdout.decode().strip()
    return video_codec

# Uses ffprobe to extract the audio codec from the given file
def get_audio_codec_info(file_path):
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=codec_name', '-of', 'default=nw=1:nk=1', file_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio_codec = result.stdout.decode().strip()
    return audio_codec


# Re-encodes the video using ffmpeg based on the re-encoding rules and encoding parameters.
def reencode_video(input_file, output_file):
    video_codec = get_video_codec_info(input_file)
    audio_codec = get_audio_codec_info(input_file)

    # Determine target codecs based on re-encoding rules
    target_video_codec = REENCODE_RULES.get('video', {}).get(video_codec, 'copy')
    target_audio_codec = REENCODE_RULES.get('audio', {}).get(audio_codec, 'copy')

    # Skip re-encoding if no changes are needed
    if target_video_codec == 'copy' and target_audio_codec == 'copy':
        log("No re-encoding needed.")
        return False

    # Build ffmpeg command
    ffmpeg_cmd = ['ffmpeg', '-i', input_file]

    # Add video encoding parameters
    ffmpeg_cmd.extend(['-c:v', target_video_codec])
    if target_video_codec != 'copy':
        video_params = ENCODING_PARAMS.get('video', {}).get(target_video_codec, {})
        for param, value in video_params.items():
            ffmpeg_cmd.extend([f'-{param}', value])

    # Add audio encoding parameters
    ffmpeg_cmd.extend(['-c:a', target_audio_codec])
    if target_audio_codec != 'copy':
        audio_params = ENCODING_PARAMS.get('audio', {}).get(target_audio_codec, {})
        for param, value in audio_params.items():
            ffmpeg_cmd.extend([f'-{param}', value])

    ffmpeg_cmd.extend(['-y', output_file])  # Overwrite output file if it exists

    log(f"Running ffmpeg command: {' '.join(ffmpeg_cmd)}")
    try:
        subprocess.run(ffmpeg_cmd, check=True)
        log(f"Re-encoding successful: {output_file}")
        return True
    except subprocess.CalledProcessError as e:
        log(f"Failed to re-encode video: {e}")
        return False


############################# YOUTUBE #############################

def get_youtube_trailer(title, year, folder_path, tmdb_id, is_movie):
    # Gather data from TMDB
    if tmdb_id is None:
        tmdb_id = get_tmbd_id(title, year, is_movie)

    keywords = YOUTUBE_PARAMS["default"]["search_keywords"]
    tmdb_info = get_tmdb_info(tmdb_id, is_movie)
    if tmdb_info is not None and tmdb_info["original_language"] in YOUTUBE_PARAMS:
        keywords = YOUTUBE_PARAMS[tmdb_info["original_language"]]["search_keywords"]
        if YOUTUBE_PARAMS[tmdb_info["original_language"]]["use_original_movie_name"]:
            title = tmdb_info[f"{"original_title" if is_movie else "original_name"}"]
            log(f"Using original title: {title}")

    # Remove any special character from title that could cause problems with filenames
    title = re.sub(r'[<>:"/\\|?*]', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip() # remove multiple spaces

    # Search for trailer on YouTube
    yt_query = f"{title} {year} {keywords}"
    yt_query = quote(yt_query)

    yt_search_url = f"https://youtube.googleapis.com/youtube/v3/search?part=snippet&maxResults=1&q={yt_query}&type=video&videoDuration=short&key={YOUTUBE_API_KEY}"
    log("Sending Youtube search request...")
    yt_search_results = fetch_json(yt_search_url)

    if not yt_search_results.get("items"):
        log(f"No search results! Skipping trailer download.")
        return 0

    yt_video_id = yt_search_results["items"][0]["id"]["videoId"]

    # Create a temporary directory for working in
    with tempfile.TemporaryDirectory() as TEMP_DIR:
        log(f"Created temporary directory: {TEMP_DIR}")

        # Download trailer using yt-dlp
        log("Downloading video...")
        ydl_opts = {
            "outtmpl": os.path.join(TEMP_DIR, f"{title} ({year})-trailer.%(ext)s"),
            "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b",
        }

        # Cookies are only needed for age-restricted videos, so each configured source is tried in turn and
        # an anonymous download is always attempted last. This matters in Docker, where no browser is
        # installed and reading cookies from one can never succeed.
        download_attempts = []
        if YT_DLP_COOKIES_FILE != "":
            download_attempts.append((f'cookies file "{YT_DLP_COOKIES_FILE}"', {**ydl_opts, "cookiefile": YT_DLP_COOKIES_FILE}))
        if YT_DLP_COOKIES_BROWSER != "":
            # Optionally read from a specific profile directory instead of the browser's default location,
            # e.g. a Firefox profile folder mounted read-only into a Docker container. Syntax: "firefox:/path".
            browser_name, _, profile_path = YT_DLP_COOKIES_BROWSER.partition(":")
            download_attempts.append((f"cookies from {YT_DLP_COOKIES_BROWSER}", {**ydl_opts, "cookiesfrombrowser": (browser_name, profile_path or None, None, None)}))
        download_attempts.append(("no cookies", ydl_opts))

        temp_filename = None
        for attempt_description, attempt_ydl_opts in download_attempts:
            try:
                with yt_dlp.YoutubeDL(attempt_ydl_opts) as ydl:
                    info_dict = ydl.extract_info(f"https://www.youtube.com/watch?v={yt_video_id}", download=True)
                    temp_filename = ydl.prepare_filename(info_dict)
                break
            except Exception as e:
                log(f"Download using {attempt_description} failed: {e}")

        if temp_filename is None:
            log("Failed to download trailer.")
            return 0

        try:
            output_filename = temp_filename.replace(TEMP_DIR, folder_path)

            # Re-encode the video if necessary
            reencoded_filename = os.path.join(TEMP_DIR, f"{title} ({year})-trailer-reencoded.mp4")
            if reencode_video(temp_filename, reencoded_filename):
                os.remove(temp_filename)
                temp_filename = reencoded_filename  # Use the re-encoded file
            else:
                log("Re-encoding not needed or failed, using original file.")

            # Move the trailer to its destination
            log(f"Moving trailer to its destination ...")
            shutil.move(temp_filename, output_filename)
            log(f"Trailer successfully downloaded and saved to {os.path.join(folder_path, output_filename)}")
            return 1
        except Exception as e:
            log(f"Failed to save trailer: {e}")
            return 0


############################# LIBRARY PROCESSING #############################

def download_trailers_for_library(library_root_path):
    downloaded_trailers_count = 0

    # Iterate over immediate subfolders of library_root_path
    for dir_name in os.listdir(library_root_path):
        dir_path = os.path.join(library_root_path, dir_name)

        if not os.path.isdir(dir_path):
            continue

        # Check if the directory already has a trailer
        already_has_trailer = False
        for file_name in os.listdir(dir_path):
            base_name, ext = os.path.splitext(file_name)
            if base_name.lower().endswith("-trailer"):
                already_has_trailer = True
                break

        if already_has_trailer:
            log(f'Skipping "{dir_name}" as it already has a trailer')
        else:
            log(f'Downloading a trailer for "{dir_name}" ...')

            # Extract title and year from the folder name
            match = re.match(r"(.*)\s\((\d{4})\)(?:\s+)?({tvdb-\d+})?", dir_name)
            if match:
                title, year, tvdb_id = match.groups()
                tmdb_id = None

                if tvdb_id is not None:
                    # Download the TV show trailer
                    downloaded_trailers_count += get_youtube_trailer(title, year, dir_path, tmdb_id, False)
                else:
                    # Find the largest file in the directory
                    video_files = [f for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))]
                    if video_files:
                        video_file = max(video_files, key=lambda f: os.path.getsize(os.path.join(dir_path, f)))
                        video_file_base = os.path.splitext(video_file)[0]

                        # Extract TMDB ID from the filename if available
                        match = re.match(r"(.*)\s\((\d{4})\)(.*tmdb-(\d+).*|.*)", video_file_base)
                        if match:
                            tmdb_id = match[4]

                        # Download the trailer
                        downloaded_trailers_count += get_youtube_trailer(title, year, dir_path, tmdb_id, True)
                    else:
                        log(f"No movie file found for {dir_name}, skipping")
            else:
                log(f"Invalid name format: {dir_name}, expecting 'title (year)', skipping")

    log(f"Successfully downloaded {downloaded_trailers_count} new trailers.")


############################# WEBHOOK SERVER #############################

# Radarr/Sonarr event types that should trigger a trailer download
TRAILER_EVENT_TYPES = ("Download", "Rename")

# Downloads are queued and handled by a single worker thread, so a burst of imports doesn't start
# several yt-dlp downloads in parallel.
JOB_QUEUE = queue.Queue()


# Translates a path as seen by Radarr/Sonarr into a path this script can actually reach, using PATH_MAPPINGS.
# Returns the path unchanged when no mapping matches, which is the common case when both run on the same host.
def map_path(arr_path):
    if arr_path is None:
        return None

    for arr_prefix, local_prefix in PATH_MAPPINGS:
        if arr_path.startswith(arr_prefix):
            # Re-join the remaining parts using the local platform's separator, as Radarr/Sonarr may use the other one
            suffix = arr_path[len(arr_prefix):].replace("\\", "/").strip("/")
            mapped_path = os.path.join(local_prefix, *suffix.split("/")) if suffix else local_prefix
            log(f'Mapped path "{arr_path}" to "{mapped_path}"')
            return mapped_path

    return arr_path


# Turns a Radarr/Sonarr webhook payload into the arguments get_youtube_trailer expects.
# Returns None when the payload describes an event that shouldn't trigger a download.
def build_trailer_job(payload):
    event_type = payload.get("eventType")

    if event_type not in TRAILER_EVENT_TYPES:
        log(f'Ignoring "{event_type}" event')
        return None

    # An upgrade replaces an existing file, so the trailer has already been downloaded
    if event_type == "Download" and payload.get("isUpgrade", False):
        log("Ignoring the upgrade of an already imported item")
        return None

    if "movie" in payload:
        movie = payload["movie"]
        return movie.get("title"), movie.get("year"), map_path(movie.get("folderPath")), movie.get("tmdbId"), True

    if "series" in payload:
        series = payload["series"]
        return series.get("title"), series.get("year"), map_path(series.get("path")), None, False

    log("Payload contains neither a movie nor a series, ignoring")
    return None


# Worker loop consuming the download queue, run in a background thread by run_server()
def process_jobs():
    while True:
        job = JOB_QUEUE.get()
        try:
            get_youtube_trailer(*job)
        except Exception as e:
            log(f'Failed to download a trailer for "{job[0]}": {e}')
        finally:
            JOB_QUEUE.task_done()

        # Take advantage of being idle to refresh dependencies. Since yt_dlp is already imported at this point,
        # the process has to restart for the new version to actually be used.
        if JOB_QUEUE.empty() and update_libs_if_needed():
            log("Restarting to load the newly installed dependencies...")
            os.execv(sys.executable, [sys.executable] + sys.argv)


class WebhookRequestHandler(BaseHTTPRequestHandler):
    # Route the built-in HTTP logging into our own log file
    def log_message(self, format, *args):
        log(f"{self.address_string()} - {format % args}")

    def send_text_response(self, status_code, message):
        body = message.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Checks the credentials configured in the [Server] section, matching the webhook connection's Username/Password
    def is_authorized(self):
        if SERVER_USERNAME == "" and SERVER_PASSWORD == "":
            return True

        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            return False

        try:
            username, _, password = base64.b64decode(auth_header[len("Basic "):]).decode("utf-8").partition(":")
        except Exception:
            return False

        # compare_digest avoids leaking the expected credentials through response timing
        return hmac.compare_digest(username, SERVER_USERNAME) and hmac.compare_digest(password, SERVER_PASSWORD)

    # Health check, also handy to confirm from a browser that the server is reachable
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/health"):
            self.send_text_response(200, "Arr-TrailerDownloader is running")
        else:
            self.send_text_response(404, "Not found")

    def do_POST(self):
        if not self.is_authorized():
            log("Rejected a request with missing or invalid credentials")
            self.send_text_response(401, "Unauthorized")
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            log(f"Received an invalid webhook payload: {e}")
            self.send_text_response(400, "Invalid JSON payload")
            return

        # Radarr/Sonarr's "Test" button
        if payload.get("eventType") == "Test":
            if YOUTUBE_API_KEY == "YOUR_API_KEY":
                log("Please insert your Youtube API key for the script to work")
                self.send_text_response(500, "Missing Youtube API key, see config.ini")
                return
            log("Test successful")
            self.send_text_response(200, "Test successful")
            return

        job = build_trailer_job(payload)
        if job is None:
            self.send_text_response(200, "Nothing to do")
            return

        # Answer right away, as downloading takes far longer than Radarr/Sonarr are willing to wait
        JOB_QUEUE.put(job)
        log(f'Queued a trailer download for "{job[0]}" ({JOB_QUEUE.qsize()} job(s) pending)')
        self.send_text_response(202, "Trailer download queued")


def run_server():
    threading.Thread(target=process_jobs, daemon=True).start()

    server = ThreadingHTTPServer((SERVER_HOST, SERVER_PORT), WebhookRequestHandler)
    log(f"Listening for Radarr/Sonarr webhooks on http://{SERVER_HOST}:{SERVER_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down")
        server.shutdown()


############################# MAIN #############################


def main():
    # Running as a webhook server (Docker, run_server.bat, run_server.sh)
    if "--serve" in sys.argv:
        run_server()
        return

    # Calling script from Radarr
    if "radarr_eventtype" in os.environ:
        log("Script triggered from Radarr")

        if os.environ["radarr_eventtype"] == "Test":
            if YOUTUBE_API_KEY == "YOUR_API_KEY":
                log("Please insert your Youtube API key for the script to work")
                sys.exit(1)
            log("Test successful")

        if (os.environ["radarr_eventtype"] == "Download" and os.environ["radarr_isupgrade"] == "False") or os.environ["radarr_eventtype"] == "Rename":
            get_youtube_trailer(
                os.environ["radarr_movie_title"],
                os.environ["radarr_movie_year"],
                os.environ["radarr_movie_path"],
                os.environ["radarr_movie_tmdbid"],
                True
            )

        sys.exit(0)

    # Calling script from Sonarr
    if "sonarr_eventtype" in os.environ:
        log("Script triggered from Sonarr")

        if os.environ["sonarr_eventtype"] == "Test":
            if YOUTUBE_API_KEY == "YOUR_API_KEY":
                log("Please insert your Youtube API key for the script to work")
                sys.exit(1)
            log("Test successful")

        if (os.environ["sonarr_eventtype"] == "Download" and os.environ["sonarr_isupgrade"] == "False") or os.environ["sonarr_eventtype"] == "Rename":
            get_youtube_trailer(
                os.environ["sonarr_series_title"],
                os.environ["sonarr_series_year"],
                os.environ["sonarr_series_path"],
                None,
                False
            )

        sys.exit(0)

    # Calling script from command line
    if len(sys.argv) == 1:
        print("Usage:")
        print("  py TrailerDownloader.py library_root_folder   Download the missing trailers of an existing library")
        print("  py TrailerDownloader.py --serve               Listen for Radarr/Sonarr webhooks (see [Server] in config.ini)")
        sys.exit(0)

    if not os.path.exists(sys.argv[1]):
        log(f"The folder {sys.argv[1]} doesn't exist")
        sys.exit(1)

    download_trailers_for_library(sys.argv[1])


if __name__ == "__main__":
    main()
