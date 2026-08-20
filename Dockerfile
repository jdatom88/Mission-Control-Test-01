FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY mission_control ./mission_control
COPY scripts ./scripts

CMD ["python", "scripts/pilot_calendar_runtime.py"]
