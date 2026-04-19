# Backend image for Uptime Guardian (FastAPI + Uvicorn).
#
# The SQLite database lives under /data, which docker-compose mounts to the
# named `sqlite_data` volume so monitor history survives container restarts.
# Set DATABASE_URL=sqlite:////data/uptime.db (four slashes => absolute path)
# when running the container so the DB file is written to the volume.
FROM python:3.11-slim

# Avoid .pyc files and ensure logs are flushed straight to the console.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source.
COPY . .

# Directory that backs the SQLite database (mounted as a volume in compose).
RUN mkdir -p /data

EXPOSE 8000

# Serve the FastAPI app. Host 0.0.0.0 so it is reachable outside the container.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
