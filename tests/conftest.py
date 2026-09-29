"""Shared test setup. Everything runs headless: pygame gets SDL's dummy video/audio drivers."""

from __future__ import annotations

import multiprocessing as mp
import os
import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

ROOT = Path(__file__).resolve().parents[1]

# T7: MAZE_MP_START_METHOD=spawn runs the whole suite the way Windows would.
if os.environ.get("MAZE_MP_START_METHOD"):
    mp.set_start_method(os.environ["MAZE_MP_START_METHOD"], force=True)


def mpiexec_path() -> str | None:
    return shutil.which(os.environ.get("MPIEXEC", "mpiexec"))


def broker_reachable() -> bool:
    url = urlparse(os.environ.get("CELERY_BROKER_URL", "pyamqp://guest@localhost//"))
    try:
        with socket.create_connection((url.hostname or "localhost", url.port or 5672), 1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture
def need_mpi():
    if sys.platform == "win32":
        pytest.skip("MPI integration tests run on Linux CI only (MS-MPI is not installed there)")
    if mpiexec_path() is None:
        pytest.skip("mpiexec not found on PATH")


@pytest.fixture
def need_broker():
    if sys.platform == "win32":
        pytest.skip("Celery integration needs the RabbitMQ service container (Linux CI only)")
    if not broker_reachable():
        pytest.skip("no RabbitMQ broker reachable at CELERY_BROKER_URL")
