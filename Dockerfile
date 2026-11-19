FROM python:3.12-slim

# Runtime never needs root: the API, the UI and the worker are plain Python
# processes. Create an unprivileged account and drop to it, so a compromise in
# a request path does not land on uid 0 inside the container.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 app

WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY . .

# OpenBB builds its static package the first time it is imported, into
# site-packages, and records what it built in assets/reference.json. The
# published wheels carry no reference file, so a fresh install rebuilds on
# every import -- and at runtime that import runs as the unprivileged app user,
# in a directory owned by root, so the build cannot create its lock file and
# the import dies with "Permission denied: .../openbb/.build.lock". Build it
# here, as root, while site-packages is still writable, and fail the image
# build if the reference file did not land.
RUN RUFF_CACHE_DIR=/tmp/ruff-cache python -c "import openbb" && \
    test -f "$(python -c 'import openbb, pathlib; print(pathlib.Path(openbb.__file__).parent)')/assets/reference.json"

# OpenBB's platform directory is created under the user's home on import and
# holds its settings and credentials. Create it here, owned by the app user, so
# a service whose rootfs is read only can still be given a writable one by
# mounting over this path.
RUN mkdir -p /home/app/.openbb_platform && chown app:app /home/app/.openbb_platform

# The package is already built and the reference file matches the installed
# extensions, so the runtime has no reason to rebuild it -- and no permission
# to. Turning the automatic build off makes that explicit instead of leaving
# a lock file that only fails once the rootfs is hardened.
ENV OPENBB_AUTO_BUILD=false

# Hand /app to the unprivileged user (COPY lands it owned by root).
RUN chown -R app:app /app

USER app
EXPOSE 8000
CMD ["uvicorn","api.main:app","--host","0.0.0.0","--port","8000"]
