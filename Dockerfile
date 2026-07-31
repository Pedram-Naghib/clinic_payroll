FROM python:3.12-slim

WORKDIR /srv

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY app ./app
COPY webapp ./webapp
COPY alembic.ini .
COPY migrations ./migrations

EXPOSE 8000
CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
