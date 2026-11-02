"""Lossless compaction of immutable shared snapshots and disposable PDF renders.

Original project files, meeting logs, checkpoints, attachments and models are
never deleted. Identical archive files share an inode; their paths stay valid.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import uuid
from collections import Counter
from functools import lru_cache


def digest(path: Path) -> str:
    stat = path.stat()
    return _digest(str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@lru_cache(maxsize=2048)
def _digest(path: str, device: int, inode: int, size: int, modified: int, changed: int) -> str:
    # Reuse only while identity, length and both modification timestamps match.
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _snapshots(workspace: Path):
    root = workspace / 'meetings'
    if not root.is_dir():
        return
    for session in sorted(root.iterdir()):
        if session.is_symlink() or not session.is_dir():
            continue
        for name in ('shared', 'uploads'):
            folder = session / name
            if folder.is_symlink() or not folder.is_dir():
                continue
            for p in sorted(folder.iterdir()):
                if p.is_file() and not p.is_symlink() and not p.name.startswith('.compact-'):
                    yield p


def clear_pages(session: Path) -> int:
    """PNG page renders can always be regenerated from the preserved PDFs."""
    folder = session / 'pages'
    if folder.is_symlink() or not folder.is_dir():
        return 0
    freed = 0
    for p in folder.iterdir():
        if p.is_file() and not p.is_symlink() and p.suffix.lower() == '.png':
            size = p.stat().st_blocks * 512
            p.unlink()
            freed += size
    return freed


def duplicate_groups(workspace: Path, active: set[str] | None = None):
    by_size = {}
    for p in _snapshots(workspace):
        if p.parent.parent.name in (active or set()):
            continue
        stat = p.stat()
        if stat.st_size:
            by_size.setdefault(stat.st_size, []).append(p)
    for paths in by_size.values():
        if len(paths) < 2:
            continue
        inodes = {(p.stat().st_dev, p.stat().st_ino) for p in paths}
        if len(inodes) == 1:
            continue  # Already sharing storage: no content reads are needed.
        by_hash = {}
        hashes = {}
        for p in paths:
            stat = p.stat()
            key = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            if key not in hashes:
                hashes[key] = digest(p)
            by_hash.setdefault(hashes[key], []).append(p)
        yield from (g for g in by_hash.values() if len(g) > 1)


def compact(workspace: Path, active: set[str] | None = None, dry_run: bool = False) -> dict:
    active = active or set()
    result = {'duplicate_bytes': 0, 'page_bytes': 0, 'linked_files': 0, 'skipped_files': 0}
    for group in duplicate_groups(workspace, active):
        canonical = group[0]
        canonical_inode = (canonical.stat().st_dev, canonical.stat().st_ino)
        counts = Counter((p.stat().st_dev, p.stat().st_ino) for p in group)
        seen = {canonical_inode}
        for target in group[1:]:
            stat = target.stat()
            inode = (stat.st_dev, stat.st_ino)
            if inode == canonical_inode:
                continue
            # Replacing just one path to an already-linked inode does not free its blocks.
            saving = stat.st_blocks * 512 if stat.st_nlink == 1 else 0
            if dry_run:
                if inode not in seen and stat.st_nlink == counts[inode]:
                    result['duplicate_bytes'] += stat.st_blocks * 512
                seen.add(inode)
                result['linked_files'] += 1
                continue
            tmp = target.with_name('.compact-' + uuid.uuid4().hex)
            try:
                if digest(target) != digest(canonical):
                    result['skipped_files'] += 1
                    continue
                os.link(canonical, tmp)
                current = target.stat()
                if (current.st_ino, current.st_size, current.st_mtime_ns) != (stat.st_ino, stat.st_size, stat.st_mtime_ns):
                    result['skipped_files'] += 1
                    continue
                os.replace(tmp, target)
                result['duplicate_bytes'] += saving
                result['linked_files'] += 1
            except OSError:
                result['skipped_files'] += 1
            finally:
                tmp.unlink(missing_ok=True)
    root = workspace / 'meetings'
    for session in root.iterdir() if root.is_dir() else []:
        if session.name in active or session.is_symlink() or not session.is_dir():
            continue
        if dry_run:
            folder = session / 'pages'
            if folder.is_dir() and not folder.is_symlink():
                result['page_bytes'] += sum(p.stat().st_blocks * 512 for p in folder.iterdir()
                    if p.is_file() and not p.is_symlink() and p.suffix.lower() == '.png')
        else:
            result['page_bytes'] += clear_pages(session)
    result['reclaimed_bytes'] = result['duplicate_bytes'] + result['page_bytes']
    return result


def copy_snapshot(source: Path, destination: Path, workspace: Path):
    temporary = destination.with_name('.compact-' + uuid.uuid4().hex + '_' + destination.name.split('_', 1)[-1])
    try:
        _copy_snapshot(source, temporary, workspace)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_snapshot(source: Path, destination: Path, workspace: Path):
    """Reuse identical archive copies, never hard-link a mutable project source."""
    name = destination.name.split('_', 1)[-1]
    size = source.stat().st_size
    source_hash = None
    for candidate in _snapshots(workspace):
        if candidate == destination or candidate.parent.name != 'shared' or not candidate.name.endswith('_' + name):
            continue
        if candidate.stat().st_size != size:
            continue
        source_hash = source_hash or digest(source)
        if digest(candidate) == source_hash:
            try:
                os.link(candidate, destination)
                return
            except OSError:
                break
    shutil.copy2(source, destination)
