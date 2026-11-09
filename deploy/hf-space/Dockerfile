# Hugging Face Space image for the Filipino pronunciation scorer.
# Layout inside the image mirrors the repo, because the scorer finds its G2P and
# calibration by path: /app/gop/basaquest_gop, /app/g2p/filipino_g2p,
# /app/gop/calibration.json, /app/models/final-model-v2. prepare.ps1 assembles it.
FROM python:3.11-slim

# ffmpeg decodes whatever the browser recorded (webm/opus) to 16 kHz mono.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Spaces run as user 1000.
RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
# CPU-only torch: inference only, no GPU, ~200 MB instead of ~2.5 GB.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .
USER user

ENV PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
