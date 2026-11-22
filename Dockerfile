FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home /app bot

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY study_bot ./study_bot
RUN mkdir -p /app/data && chown bot /app/data

USER bot
ENV PYTHONUNBUFFERED=1 DATABASE_PATH=/app/data/study.db
CMD ["python", "-m", "study_bot"]
