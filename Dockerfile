FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml

COPY allen ./allen

EXPOSE 8090
CMD ["uvicorn", "allen.main:app", "--host", "0.0.0.0", "--port", "8090"]
