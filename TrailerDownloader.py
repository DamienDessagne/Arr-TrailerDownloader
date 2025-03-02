import os
import re
import sys
import requests
from urllib.parse import quote
from datetime import datetime
import yt_dlp
import configparser

############################# CONFIG #############################

# Load configuration from external file
config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini'))

# Whether to log everything the script does
LOG_ACTIVITY = config.getboolean('CONFIG', 'LOG_ACTIVITY')

# Your TMDB API key, if not provided, language-dependant features won't be activated
TMDB_API_KEY = config.get('CONFIG', 'TMDB_API_KEY')

# Youtube API key (see https://developers.google.com/youtube/v3/getting-started)
YOUTUBE_API_KEY = config.get('CONFIG', 'YOUTUBE_API_KEY')

# Browser name to get cookies from to download from YouTube. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for details
YT_DLP_COOKIES_BROWSER = config.get('CONFIG', 'yt_dlp_cookies_browser')

# Video codec to re-encode trailers to
REENCODE_VIDEO_CODEC = config.get('CONFIG', 'reencode_video_codec', fallback=None)

# Audio codec to re-encode trailers to
REENCODE_AUDIO_CODEC = config.get('CONFIG', 'reencode_audio_codec', fallback=None)

# Language-dependant parameters to search for trailers on Youtube
YOUTUBE_PARAMS = {"default": {
    "use_original_movie_name": config.getboolean('YOUTUBE_PARAMS.default', 'use_original_movie_name'),
    "search_keywords": config.get('YOUTUBE_PARAMS.default', 'search_keywords')
}}

# Load language-specific parameters
for section in config.sections():
    if section.startswith('YOUTUBE_PARAMS.') and section != 'YOUTUBE_PARAMS.default':
        language_code = section.split('.')[1]  # Extract language code (e.g., 'fr' from 'YOUTUBE_PARAMS.fr')
        YOUTUBE_PARAMS[language_code] = {
            "use_original_movie_name": config.getboolean(section, 'use_original_movie_name'),
            "search_keywords": config.get(section, 'search_keywords')
        }

############################# LOG #############################

# Set current directory to script location
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Create a new log file
LOG_FOLDER_NAME = "Logs"
if LOG_ACTIVITY and not os.path.exists(LOG_FOLDER_NAME):
    os.makedirs(LOG_FOLDER_NAME)

LOG_FILE_NAME = datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
LOG_FILE_PATH = os.path.join(LOG_FOLDER_NAME, LOG_FILE_NAME)

# Echoes the given text and appends the given text to the log file's content
def log(log_text):
    print(log_text)
    if LOG_ACTIVITY:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(log_text + "\n")

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

    # Download trailer using yt-dlp
    log("Downloading video...")
    ydl_opts = {
        "outtmpl": os.path.join(folder_path, f"{title} ({year})-Trailer.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4] / bv*+ba/b",
    }
    if REENCODE_VIDEO_CODEC is not None or REENCODE_AUDIO_CODEC is not None:
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegCopyStream"},
        ]
        ydl_opts["postprocessor_args"] = {
            "copystream": [
                "-c:v", REENCODE_VIDEO_CODEC if REENCODE_VIDEO_CODEC is not None else "copy",
                "-c:a", REENCODE_AUDIO_CODEC if REENCODE_AUDIO_CODEC is not None else "copy"
            ],
        }
        print(f"{ydl_opts}")

    if YT_DLP_COOKIES_BROWSER != "":
        ydl_opts["cookiesfrombrowser"] = (YT_DLP_COOKIES_BROWSER, None, None, None)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(f"https://www.youtube.com/watch?v={yt_video_id}", download=True)
            output_filename = ydl.prepare_filename(info_dict)
        log(f"Trailer successfully downloaded and saved to {os.path.join(folder_path, output_filename)}")
        return 1
    except Exception as e:
        log(f"Failed to download trailer: {e}")
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
            if file_name.lower().endswith("-trailer.mp4") or file_name.lower().endswith("-trailer.mkv"):
                already_has_trailer = True
                break

        if already_has_trailer:
            log(f'Skipping "{dir_name}" as it already has a trailer')
        else:
            log(f'Downloading a trailer for "{dir_name}" ...')

            # Extract title and year from the folder name
            match = re.match(r"(.*)\s\((\d{4})\)", dir_name)
            if match:
                title, year = match.groups()
                tmdb_id = None
                is_movie = False

                # Find the largest file in the directory
                video_files = [f for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))]
                if video_files:
                    is_movie = True
                    video_file = max(video_files, key=lambda f: os.path.getsize(os.path.join(dir_path, f)))
                    video_file_base = os.path.splitext(video_file)[0]

                    # Extract TMDB ID from the filename if available
                    match = re.match(r"(.*)\s\((\d{4})\)(.*tmdb-(\d+).*|.*)", video_file_base)
                    if match:
                        tmdb_id = match[4]

                    # Download the trailer
                    downloaded_trailers_count += get_youtube_trailer(title, year, dir_path, tmdb_id, is_movie)
                else:
                    log(f"No movie file found for {dir_name}, skipping")
            else:
                log(f"Invalid name format: {dir_name}, expecting 'title (year)', skipping")

    log(f"Successfully downloaded {downloaded_trailers_count} new trailers.")



############################# MAIN #############################



def main():
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
        print("Usage: py DownloadTrailer.py library_root_folder")
        sys.exit(0)

    if not os.path.exists(sys.argv[1]):
        log(f"The folder {sys.argv[1]} doesn't exist")
        sys.exit(1)

    download_trailers_for_library(sys.argv[1])

if __name__ == "__main__":
    main()