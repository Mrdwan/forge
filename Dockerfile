FROM python:3.13-slim

# System deps for Aider and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Configure git (Aider needs this)
RUN git config --global user.name "Forge Bot" && \
    git config --global user.email "forge@localhost"

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Forge source
COPY src/ src/
COPY config.yaml .

# Create log directory
RUN mkdir -p /app/logs

# Create non-root user for security
RUN useradd -m forgeuser && chown -R forgeuser:forgeuser /app
USER forgeuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src"]
