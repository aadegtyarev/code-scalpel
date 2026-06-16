FROM python:3.11-slim

WORKDIR /app

# Layer 1 — только зависимости (кешируется, пока pyproject.toml не меняется)
COPY pyproject.toml ./
COPY app/__init__.py ./app/__init__.py
RUN pip install --no-cache-dir .

# Layer 2 — исходный код
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Принудительная переустановка, чтобы wheel содержал полный код
RUN pip install --no-cache-dir --force-reinstall --no-deps .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
