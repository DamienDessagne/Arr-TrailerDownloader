@echo off
REM Starts Arr-TrailerDownloader in server mode, waiting for Radarr/Sonarr webhooks.
REM Configure the listening address and port in the [Server] section of config.ini.
cd /d "%~dp0"
py TrailerDownloader.py --serve
pause
