"""Private readiness state used by the macOS Dock launcher."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import tempfile


def publish(path: Path, url: str):
    fd, tmp = tempfile.mkstemp(prefix='.launcher-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump({'pid': os.getpid(), 'url': url}, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def remove_own_state(path: Path):
    try:
        if json.loads(path.read_text()).get('pid') == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass


async def serve(server, path: Path, url: str):
    task = asyncio.create_task(server.serve())
    try:
        while not server.started and not task.done():
            await asyncio.sleep(.05)
        if server.started:
            publish(path, url)
        await task
    finally:
        remove_own_state(path)
