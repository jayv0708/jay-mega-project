FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY log_ui ./log_ui
WORKDIR /app/log_ui
EXPOSE 8080
CMD ["python", "app.py"]
