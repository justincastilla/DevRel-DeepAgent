FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code (overridden by volume mount in dev)
COPY . .

# Create directory for generated reports
RUN mkdir -p research_reports

EXPOSE 8000

# Use uvicorn with --reload for live code reloading
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
