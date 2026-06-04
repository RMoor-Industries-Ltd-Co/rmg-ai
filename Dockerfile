FROM python:3.12-slim
WORKDIR /app

# Runtime deps (mirrors pyproject; kept explicit for a slim image)
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.32" "anthropic>=0.40" \
    "requests>=2.32" "pydantic>=2.9" "pydantic-settings>=2.6" "python-multipart>=0.0.12"

COPY allen ./allen

EXPOSE 8090
CMD ["uvicorn", "allen.main:app", "--host", "0.0.0.0", "--port", "8090"]
