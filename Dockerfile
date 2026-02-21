FROM python:3.13-slim

# System deps for Aider and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Configure git (Aider needs this)
RUN git config --global user.name "Forge Bot" && \
    git config --global user.email "forge@localhost"

WORKDIR /app

# Install Python deps (includes pytest, pytest-cov, pytest-asyncio)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Forge source + tests
COPY src/ src/
COPY forge_init.py .
COPY config.yaml .
COPY pyproject.toml .
COPY tests/ tests/

# Create log directory
RUN mkdir -p /app/logs

# Create non-root user for security
RUN useradd -m forgeuser && chown -R forgeuser:forgeuser /app
USER forgeuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src"]
