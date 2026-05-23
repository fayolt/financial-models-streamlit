FROM python:3.12-slim

WORKDIR /app

# System libraries needed by compiled wheels (lxml for python-docx,
# libpq for psycopg2-binary fallback, freetype for matplotlib/reportlab).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libxml2 \
    libxslt1.1 \
    libfreetype6 \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer is cached on code-only changes.
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy the rest of the repo (app code + submodule dirs cloned by DO).
COPY . .

EXPOSE 8501
