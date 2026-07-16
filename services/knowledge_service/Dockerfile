FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user; uid 1000 matches the host owner of the mounted project volume.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 1000 appuser

COPY . .

ENV HF_HOME=/home/appuser/.cache/huggingface
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
