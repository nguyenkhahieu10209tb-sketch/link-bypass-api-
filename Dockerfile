FROM mcr.microsoft.com/playwright/python:v1.40.0-focal
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 10000
CMD gunicorn app:app --bind 0.0.0.0:10000 --workers 1 --threads 2 --timeout 120
