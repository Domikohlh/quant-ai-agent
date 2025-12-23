# Use a lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set entrypoint
# The port is handled by Cloud Run environment variable $PORT
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
