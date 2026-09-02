# xShot AI backend — production image
#
# Build context is the REPOSITORY ROOT (so the COPY paths below are backend/…):
#   docker build -f backend/Dockerfile -t xshot-backend .
#
# On Render: Dockerfile Path = backend/Dockerfile, leave Root Directory blank.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System libraries: ffmpeg + OpenCV runtime deps + libpq for the Postgres client.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsm6 \
        libxext6 \
        libgl1 \
        libglib2.0-0 \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the CPU-only build of torch/torchvision first. The default PyPI wheels
# bundle the full CUDA stack (~6 GB) that a CPU cloud box never uses; the cpu
# index keeps the image around ~2 GB. Pinning here also stops the -r install
# below from resolving the CUDA variant.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision

# Dependencies first, so the pip layer is cached until requirements.txt changes.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application source (model weights best.pt / yolov8n.pt included).
COPY backend/ ./

EXPOSE 8000

# Shell form so ${PORT} from the platform is expanded; falls back to 8000.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
