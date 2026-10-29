# STAGE 1: BUILDER (Compilation & dependency preparation)
# ARG centralizes the base image version. Updating Python across stages requires changing only one line.
ARG PYTHON_IMAGE=python:3.13-slim@sha256:8fb4cfa1a2616d7b8e0c2175cc6ad68f5729c34ea8488c0b360d2934b7be9024

FROM ${PYTHON_IMAGE} AS builder

# Disable pip caching and version check warnings during build to keep logs clean and reduce overhead
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# 1. Create an isolated virtual environment (venv)
# Isolating dependencies into /opt/venv makes them easy to copy cleanly into the final runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 2. Build Cache Optimization: Install external dependencies first
COPY requirements.txt .
RUN pip install -r requirements.txt

# 3. Copy and install the local application source code
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-deps .



# STAGE 2: RUNTIME (Minimal & Secure Image for Production)
FROM ${PYTHON_IMAGE} AS runtime

# Essential runtime environment variables:
# - PYTHONUNBUFFERED=1: Flushes logs directly to stdout/stderr without buffering
# - PYTHONDONTWRITEBYTECODE=1: Prevents cluttering the image with temporary .pyc files
# - PYTHONPATH: Fallback safety net ensuring Python always finds the code in /app/src
# - PATH: Automatically activates the virtual environment copied from the builder stage
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    MODEL_DIR=/app/models \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 1. Security (principle of least privilege):
# Create a dedicated non-root user with an explicit numerical UID (10001).
# Required for container security and orchestrator (Kubernetes / OpenShift) deployment standards.
RUN useradd --create-home --uid 10001 appuser

# 2. Copy only the compiled virtual environment from the 'builder' stage
COPY --from=builder /opt/venv /opt/venv

# 3. Copy application code and set proper ownership
# --chown assigns ownership to 'appuser' during copy to avoid PermissionError at runtime
COPY --chown=appuser:appuser pyproject.toml .
COPY --chown=appuser:appuser src/ src/
RUN mkdir -p /app/models && chown appuser:appuser /app/models

# 4. Switch to the unprivileged user
USER appuser

# 5. Build-time validation under the non-root 'appuser':
# Confirms that imports work under the actual non-privileged runtime permissions.
RUN python -c "import velov; import velov.api.main"

EXPOSE 8000

# 6. Reliable healthcheck:
# - Uses explicit IPv4 loopback (127.0.0.1) to avoid IPv6 (::1) resolution traps on minimal Linux images
# - Uses JSON Exec array syntax ["python", ...] to prevent spawning unnecessary shell wrappers
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready')"]

# 7. Final startup command in JSON Exec array format (ensures OS signals like SIGTERM are handled gracefully)
CMD ["uvicorn", "velov.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# How to use : 
# # To build Docker image
# docker build -t velov-api .

# # Start the container (detached mode -d) with:
# #    - Name : velov-api
# #    - Host port 8000 mapped to container port 8000
# #    - Environment variable API_KEY set at runtime if needed
# #    - Based on the built image velov-api
# docker run -d \
#   --name velov-api \
#   -p 8000:8000 \
#   -e API_KEY="" \
#   velov-api
# -> docker run -d --name velov-api -p 8000:8000 velov-api

# Verify all live images and containers with:
# docker images
# docker ps -a

# # Verify API availability (Liveness / Health)
# curl -i http://localhost:8000/health

# # Verify model readiness (Readiness / Health)
# curl -i http://localhost:8000/ready