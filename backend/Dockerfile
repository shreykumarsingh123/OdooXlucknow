FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# mysqlclient compiles against these.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Static files need settings to load, but no real secrets and no database.
RUN DEBUG=true SECRET_KEY=build-only python manage.py collectstatic --noinput

RUN useradd --create-home appuser && mkdir -p /app/sent_emails && chown -R appuser /app
USER appuser

# The free plan has no shell, so setup runs at each start. Both steps change nothing when already done.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_demo --if-empty && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 60"]
