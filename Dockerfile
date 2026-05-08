FROM python:3.10-slim

WORKDIR /usr/src/app

# ---------------- SYSTEM PACKAGES ----------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    pv \
    jq \
    gcc \
    python3-dev \
    mediainfo \
    aria2 \
    libsm6 \
    libxext6 \
    libfontconfig1 \
    libxrender1 \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ---------------- STATIC FFMPEG ----------------
COPY --from=mwader/static-ffmpeg:6.1 /ffmpeg /usr/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:6.1 /ffprobe /usr/bin/ffprobe

# ---------------- COPY PROJECT ----------------
COPY . .

# ---------------- REMOVE OFFICIAL PYROGRAM ----------------
RUN pip uninstall -y pyrogram || true

# ---------------- INSTALL REQUIREMENTS (WITHOUT PYROGRAM) ----------------
RUN pip install --no-cache-dir -r requirements.txt


CMD ["bash", "run.sh"]
