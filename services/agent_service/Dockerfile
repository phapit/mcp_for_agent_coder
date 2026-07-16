FROM python:3.11-slim

WORKDIR /app

# Install git client
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user; uid 1000 matches the host owner of the mounted project volume.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 1000 appuser

COPY . .

USER appuser
RUN git config --global --add safe.directory /app/project_data

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
