# Use an official, lightweight Python runtime
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy only the job requirements first (leverages Docker cache)
COPY jobs/requirements-job.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements-job.txt

# Copy the core database/engine logic and the jobs folder
# (Assuming Docker build context is the project root)
COPY core/ core/
COPY jobs/ jobs/

# Command to run the daily ingestion script
CMD ["python", "jobs/daily_ingestion.py"]