FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory structure
RUN mkdir -p /app/data/images /app/data/pending_images /app/data/sqlite

# Copy application code
COPY app.py .
COPY templates/ ./templates/
COPY admin_templates/ ./admin_templates/

# Set up template directories for Flask to find them
RUN mkdir -p /app/templates
RUN ln -sf /app/templates/index.html /app/index.html
RUN ln -sf /app/admin_templates /app/templates/admin_templates

# Copy existing images to data directory if they exist
COPY images/ ./data/images/

# Set environment variables
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Expose port for the app
EXPOSE 5000

# Command to run the application
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
