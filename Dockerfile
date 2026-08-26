FROM python:3.12-slim

WORKDIR /srv

# libpq is not needed (asyncpg is pure-Python + C extension wheels), but gcc
# is needed to build a couple of transitive wheels on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# sentence-transformers/torch are only needed when ENABLE_SEMANTIC_MATCH=true
# (see app/services/embeddings.py). Skip them in the default image to keep
# it small enough for a free-tier host; rebuild with --build-arg
# INSTALL_SEMANTIC=1 once semantic matching is turned on.
ARG INSTALL_SEMANTIC=0
RUN if [ "$INSTALL_SEMANTIC" = "1" ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        grep -v -E '^(sentence-transformers)' requirements.txt > requirements.min.txt \
        && pip install --no-cache-dir -r requirements.min.txt; \
    fi

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
