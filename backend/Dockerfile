# xShot AI backend — production image
#
# Build context is the REPOSITORY ROOT (so the COPY paths below are backend/…):
#   docker build -f backend/Dockerfile -t xshot-backend .
#
# On Render/Railway: Dockerfile Path = backend/Dockerfile, leave Root Directory blank.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy

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

# Install deps with uv instead of pip. pip's backtracking resolver holds many
# candidate wheels in memory at once while resolving torch + ultralytics + opencv
# + matplotlib; on a small CI/build box that peak is what OOM-kills the build.
# uv resolves from a prebuilt graph with a far lower memory ceiling and is much
# faster. uv does not compile .pyc on install (Python compiles lazily on first
# import), which also trims build CPU/memory and layer size.
RUN pip install --no-cache-dir "uv>=0.5,<1.0"

# 1) CPU-only torch/torchvision from the PyTorch CPU index. The default PyPI
#    wheels bundle the full CUDA stack (~6 GB) a CPU box never uses. The +cpu
#    wheels declare no nvidia-* deps, so a normal resolve stays CPU-only.
RUN uv pip install --system --no-cache \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision

# 2) Everything else. torch is already satisfied, so it is not re-resolved.
#    Split from the torch step so each install resolves a smaller graph.
COPY backend/requirements.txt ./requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt

# Application source (model weights best.pt / yolov8n.pt included).
COPY backend/ ./

EXPOSE 8000

# Shell form so ${PORT} from the platform is expanded; falls back to 8000.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
