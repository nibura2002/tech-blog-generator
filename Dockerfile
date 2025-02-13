FROM python:3.12-slim

# Install system dependencies required for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential && rm -rf /var/lib/apt/lists/*

# Install Poetry (Python dependency manager)
RUN curl -sSL https://install.python-poetry.org | python -
ENV PATH="/root/.local/bin:$PATH"

# Set the working directory
WORKDIR /app

# Copy dependency definition files first for caching purposes
COPY pyproject.toml poetry.lock* /app/

# Configure Poetry to install production dependencies (excluding dev dependencies) without creating a virtual environment
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --no-interaction --no-ansi

# Remove build dependencies to reduce the final image size
RUN apt-get purge -y --auto-remove build-essential && rm -rf /var/lib/apt/lists/*

# Copy the application source code
COPY . /app

# Create a non-root user for security and change ownership of the app directory
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser:appuser /app
USER appuser

# Expose the port used by the Flask application (5001 as defined in app.py)
EXPOSE 8080

# Use Gunicorn to run the application (assumes the Flask app object is defined in app:app)
CMD ["gunicorn", "-w", "1", "--timeout", "3600", "-b", "0.0.0.0:8080", "app:app"]