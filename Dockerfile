FROM python:3.12-slim

# Runtime never needs root: the API, the UI and the worker are plain Python
# processes. Create an unprivileged account and drop to it, so a compromise in
# a request path does not land on uid 0 inside the container.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Hand /app to the unprivileged user (COPY lands it owned by root).
RUN chown -R app:app /app

USER app
EXPOSE 8000
CMD ["uvicorn","api.main:app","--host","0.0.0.0","--port","8000"]
