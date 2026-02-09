# Use Python 3.12 (matches your local env)
FROM python:3.12-slim

# Install system dependencies (OpenMP for XGBoost)
RUN apt-get update && apt-get install -y \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copy the shared 'core' library
COPY core/ core/

# 3. Copy the 'mcp_server' directory (where data_server.py lives)
COPY mcp_server/ mcp_server/
COPY helpers/ helpers/

# 4. Copy .env to root (so both folders can find it easily)
COPY .env . 

# 5. Set PYTHONPATH so 'import core' and 'import mcp_server' work anywhere
ENV PYTHONPATH=/app

# 6. Default Command: Run the script from the mcp_server folder
CMD ["python", "mcp_server/data_server.py"]