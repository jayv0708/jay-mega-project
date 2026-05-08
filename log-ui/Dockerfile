FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY log-ui ./log-ui
COPY db ./db
COPY alembic.ini ./alembic.ini
WORKDIR /app/log-ui
EXPOSE 8080
CMD ["python", "app.py"]
