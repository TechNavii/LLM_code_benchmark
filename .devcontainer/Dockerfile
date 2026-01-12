# Devcontainer for Benchmark Harness
# Provides a reproducible development environment matching CI configuration
#
# Python versions: 3.11 (primary), 3.12 (available via pyenv)
# Uses locked dependencies from requirements*.txt files

FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# Install system dependencies required by the project
RUN apt-get update && apt-get install -y --no-install-recommends \
    # ShellCheck for script linting
    shellcheck \
    # jq for JSON processing (used by scripts)
    jq \
    # Additional development tools
    curl \
    git \
    make \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install actionlint for workflow validation
# hadolint ignore=DL4006
RUN curl -sL https://github.com/rhysd/actionlint/releases/download/v1.7.4/actionlint_1.7.4_linux_amd64.tar.gz | tar xz -C /usr/local/bin

# Set working directory
WORKDIR /workspace

# Copy dependency files first for better layer caching
COPY requirements-dev.txt requirements-dev.in ./
COPY server/requirements.txt server/requirements.in ./server/
COPY harness/requirements.txt harness/requirements.in ./harness/

# Create and activate virtual environment
ENV VIRTUAL_ENV=/workspace/.venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

# Create virtualenv and install dependencies
# Uses --require-hashes for security (matches CI behavior)
# hadolint ignore=DL3013,DL3042
RUN python -m venv ${VIRTUAL_ENV} && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --require-hashes -r requirements-dev.txt && \
    pip install --no-cache-dir --require-hashes -r server/requirements.txt && \
    pip install --no-cache-dir --require-hashes -r harness/requirements.txt

# Install pre-commit hooks (optional but recommended)
# hadolint ignore=DL3013
RUN pip install --no-cache-dir pre-commit

# Install Playwright for GUI tests (optional, can be slow)
# Uncomment if GUI tests are needed in the container
# RUN playwright install chromium && playwright install-deps chromium

# Set Python environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace

# Create non-root user directories
RUN mkdir -p /workspace/runs /workspace/tasks && \
    chown -R vscode:vscode /workspace

# Default command
CMD ["bash"]
