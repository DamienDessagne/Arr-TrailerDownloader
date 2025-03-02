# Arr-TrailerDownloader
A Python script that downloads trailers from Youtube for a Radarr/Sonarr libraries.

# Requirements
- [Python](https://www.python.org/downloads/)
- A library with naming convention starting with `{Title} ({Release Year})`. If your library is using a different naming convention, you will need to edit the script to match your own convention (only the `download_trailers_for_library` function).

# Installation
- Download and extract in a directory of your choice, visible to your **Radarr/Sonarr** installation.
- Install Python dependencies: 
```
pip install -r requirements.txt
```
- Open `config.ini` to provide your API keys and configure the script to your liking
- Highly recommended: download [ffmpeg](https://www.ffmpeg.org/) and add its `bin` folder to your PATH environment variable. Youtube now has separated audio and video for almost all its videos, this will ensure the script can combine them in a single trailer file with video and audio.

# Adding trailers to an existing library
In a terminal, launch `py .\TrailerDownloader.py PATH_TO_MY_LIBRARY_ROOT_FOLDER`

# Have Radarr/Sonarr automatically grab trailers
In your Radarr/Sonarr interface, create a new Custom Script connection (`Settings -> Connect -> + -> Custom Script`) that triggers on import and on rename. In `Path`, enter the path to your local copy of `TrailerDownloader.py` (e.g., `C:\Arr-TrailerDownloader\TrailerDownloader.py`). If clicking the Test button works, the script will work.