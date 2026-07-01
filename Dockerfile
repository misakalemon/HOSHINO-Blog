FROM python:3.12-slim AS base

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    curl libcurl4-openssl-dev libssl-dev \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p static/uploads && chmod 777 static/uploads

EXPOSE 5000

CMD ["waitress-serve", "--port=5000", "--host=0.0.0.0", "app:create_app"]
