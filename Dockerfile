FROM python:3.13-slim

# Deno is required by yt-dlp-ejs to solve YouTube's JS challenges
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# ffmpeg/ffprobe are required to inspect and optionally re-encode the downloaded trailers
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY TrailerDownloader.py ./

# config.ini is expected to be mounted at runtime, so API keys never end up baked into the image.
# A copy of the defaults is shipped so it can be extracted from the image to bootstrap a new setup.
COPY config.ini ./config.ini.default

EXPOSE 8189

# -u keeps the script's output unbuffered so it shows up in `docker logs` right away
CMD ["python", "-u", "TrailerDownloader.py", "--serve"]
