FROM python:3.12-slim
WORKDIR /app

# System deps: ffmpeg for video frame sampling + audio extraction (multimodal analysis)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Runtime deps (mirrors pyproject; kept explicit for a slim image)
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.32" "anthropic>=0.40" \
    "requests>=2.32" "pydantic>=2.9" "pydantic-settings>=2.6" "python-multipart>=0.0.12" \
    "psycopg2-binary>=2.9" "python-docx>=1.1"

COPY allen ./allen

EXPOSE 8090
CMD ["uvicorn", "allen.main:app", "--host", "0.0.0.0", "--port", "8090"]
