import os
import re
import shutil
import sys
import requests
from urllib.parse import quote
from datetime import datetime
import yt_dlp
import configparser
import subprocess
import tempfile

# Set current directory to script location
os.chdir(os.path.dirname(os.path.abspath(__file__)))

############################# CONFIG #############################

# Load configuration from external file
config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini'))

# Whether to log everything the script does
LOG_ACTIVITY = config.getboolean('Config', 'log_activity')

# Your TMDB API key, if not provided, language-dependant features won't be activated
TMDB_API_KEY = config.get('Config', 'tmdb_api_key')

# Youtube API key (see https://developers.google.com/youtube/v3/getting-started)
YOUTUBE_API_KEY = config.get('Config', 'youtube_api_key')

# Browser name to get cookies from to download from YouTube. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for details
YT_DLP_COOKIES_BROWSER = config.get('Config', 'yt_dlp_cookies_browser')

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


############################# LOG #############################

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

        if YT_DLP_COOKIES_BROWSER != "":
            ydl_opts["cookiesfrombrowser"] = (YT_DLP_COOKIES_BROWSER, None, None, None)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(f"https://www.youtube.com/watch?v={yt_video_id}", download=True)
                temp_filename = ydl.prepare_filename(info_dict)
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
        print("Usage: py TrailerDownloader.py library_root_folder")
        sys.exit(0)

    if not os.path.exists(sys.argv[1]):
        log(f"The folder {sys.argv[1]} doesn't exist")
        sys.exit(1)

    download_trailers_for_library(sys.argv[1])


if __name__ == "__main__":
    main()
