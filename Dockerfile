FROM python:3.14-slim

WORKDIR /app

# Install uv (one-liner, no pip needed)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Non root user
# RUN useradd --create-home appuser

# Copy ONLY the dependency files
COPY pyproject.toml uv.lock ./

# Install exact versions from lockfile
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY main.py .

# Pre-create the audit log so the named volume mounts a file (not a directory)
RUN touch /app/backend/audit.log

# USER appuser

EXPOSE 5000

CMD ["/app/.venv/bin/python", "main.py"]