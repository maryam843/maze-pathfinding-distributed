# Image for the Celery worker and client. mpi4py has Linux wheels since 4.1.0, but using it
# would also need an MPI library and mpiexec in the image, and the Celery demo does not use MPI,
# so mpi4py is left out to keep the image small.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SDL_VIDEODRIVER=dummy \
    SDL_AUDIODRIVER=dummy \
    PYGAME_HIDE_SUPPORT_PROMPT=1

RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN grep -v -e '^mpi4py' -e '^-e ' requirements.txt > /tmp/req.txt \
    && pip install -r /tmp/req.txt \
    && pip install --no-deps . \
    && rm /tmp/req.txt

USER app
CMD ["celery", "-A", "maze_runner.backends.celery_app", "worker", "-c", "4", "--loglevel=info"]
