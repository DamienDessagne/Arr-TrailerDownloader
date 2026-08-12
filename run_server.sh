#!/bin/bash
# Starts Arr-TrailerDownloader in server mode, waiting for Radarr/Sonarr webhooks.
# Configure the listening address and port in the [Server] section of config.ini.
cd "$(dirname "$0")"
python3 TrailerDownloader.py --serve
