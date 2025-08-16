FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage docker layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the service code
COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["/bin/bash", "-c", "uvicorn app.api:app --host 0.0.0.0 --port 8000"]