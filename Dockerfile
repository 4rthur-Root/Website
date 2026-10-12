FROM python:3.12-slim AS builder

WORKDIR /app/

# Non root user
RUN useradd --create-home appuser

COPY requirements.txt .

# Install packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

USER appuser

EXPOSE 5000

CMD ["python3", "app.py"]
