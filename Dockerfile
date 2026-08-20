# Python image for both the Streamlit dashboard and the FastAPI backend.
# docker-compose picks the command per service (streamlit vs uvicorn).
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r api/requirements.txt

COPY . .

# Streamlit (8501) or API (8000) — chosen per service in compose.
EXPOSE 8501 8000

CMD ["streamlit", "run", "app/dashboard.py", \
     "--server.port", "8501", "--server.address", "0.0.0.0", "--server.headless", "true"]
