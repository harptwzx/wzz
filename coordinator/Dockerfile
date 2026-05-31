FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y     gcc     libsnappy-dev     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY tests/ ./tests/

ENV PYTHONPATH=/app/src
ENV COORDINATOR_HOST=0.0.0.0
ENV COORDINATOR_PORT=8080
ENV WS_PORT=8765

EXPOSE 8080 8765

CMD ["python", "-m", "src.main"]
