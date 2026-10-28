FROM node:24-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

ENV RETAIL_PROJECT_ROOT=/app
ENV RETAIL_FRONTEND_DIST=/app/frontend_dist

# LightGBM requires OpenMP support.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Install application and runtime dependencies.
COPY pyproject.toml ./
COPY src/ ./src/

RUN python -m pip install --no-cache-dir ".[serving,inference]"

# Include the versioned inference model.
COPY artifacts/models/v1/ ./artifacts/models/v1/
COPY reports/tables/ ./reports/tables/
COPY --from=frontend-build /frontend/dist/ ./frontend_dist/

# Prepare a writable reports directory.
RUN useradd --create-home --uid 10001 appuser && \
    mkdir -p /app/reports/tables && \
    chown -R appuser:appuser /app/reports

USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "retail_analytics.api:app", "--host", "0.0.0.0", "--port", "8000"]
