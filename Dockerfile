
# Compilar dashboard React
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY dashboard/package*.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

# Preparar Python
FROM python:3.12-slim-bookworm
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg libopus0 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /build/dist /app/dashboard/dist

RUN mkdir -p /app/data /app/workspaces

ENV PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8080 \
    DB_TYPE=sqlite

EXPOSE 8080
CMD ["python", "-u", "main.py"]
