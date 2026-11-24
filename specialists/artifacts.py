"""Create and verify specialist artifact inventories and gzip tar bundles."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile


MANIFEST_NAME = "manifest.json"
DEFAULT_MAX_BYTES = 100 * 1024**2
SOURCE_MAX_BYTES = 16 * 1024**2
_MAX_MANIFEST_BYTES = 1024**2
_MAX_FILES = 4096
_BLOCK_SIZE = 1024**2


def _safe_path(name):
    if (
        not isinstance(name, str)
        or len(name) > 4096
        or any(part in ("", ".", "..") for part in name.split("/"))
        or any(c in "\\:" or ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        raise ValueError(f"Unsafe artifact path {name!r}")


def _check_limit(max_bytes):
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("Artifact byte limit must be a positive integer")


def _fingerprint(stream, *, limit=None):
    digest = hashlib.sha256()
    size = 0
    while block := stream.read(_BLOCK_SIZE):
        size += len(block)
        if limit is not None and size > limit:
            raise ValueError("Artifact exceeds its byte limit")
        digest.update(block)
    return {"sha256": digest.hexdigest(), "bytes": size}


def _open_regular(path):
    # The descriptor check also covers replacements between inventory and reading.
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Artifact must be a regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stream = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise ValueError(f"Artifact must be a regular file: {path}")
    return stream


def sha256_file(path):
    """Hash a regular file without following a symbolic link at its path."""
    with _open_regular(Path(path)) as stream:
        return _fingerprint(stream)["sha256"]


def _inventory(directory, max_bytes):
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ValueError(f"Artifact root must be a directory: {directory}")

    entries = []
    remaining = max_bytes
    pending = [directory]
    while pending:
        for path in pending.pop().iterdir():
            name = path.relative_to(directory).as_posix()
            _safe_path(name)
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode) and name != MANIFEST_NAME:
                pending.append(path)
                continue
            if not stat.S_ISREG(mode):
                raise ValueError(f"Artifact contains a link, special file, or invalid manifest: {name}")
            if name == MANIFEST_NAME:
                continue
            if len(entries) >= _MAX_FILES:
                raise ValueError("Artifact contains too many files")
            with _open_regular(path) as stream:
                fingerprint = _fingerprint(stream, limit=remaining)
            remaining -= fingerprint["bytes"]
            entries.append({"path": name, **fingerprint})
    if not entries:
        raise ValueError("Artifact directory has no payload files")
    return sorted(entries, key=lambda entry: entry["path"])


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate artifact manifest key {key!r}")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError(f"Invalid artifact manifest value {value!r}")


def _read_manifest(stream, max_bytes):
    data = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ValueError("Artifact manifest exceeds its byte limit")
    value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "metadata", "files"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["metadata"], dict)
        or not isinstance(value["files"], list)
        or not 1 <= len(value["files"]) <= _MAX_FILES
    ):
        raise ValueError("Invalid artifact manifest")
    names = []
    total_bytes = 0
    for entry in value["files"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "sha256", "bytes"}
            or not isinstance(entry["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            or type(entry["bytes"]) is not int
            or entry["bytes"] < 0
        ):
            raise ValueError("Invalid artifact file entry")
        name = entry["path"]
        _safe_path(name)
        if name == MANIFEST_NAME:
            raise ValueError("Manifest cannot inventory itself")
        names.append(name)
        total_bytes += entry["bytes"]
    if names != sorted(set(names)):
        raise ValueError("Artifact paths must be unique and sorted")
    all_names = {MANIFEST_NAME, *names}
    for name in names:
        if any(parent.as_posix() in all_names for parent in Path(name).parents):
            raise ValueError(f"Artifact file conflicts with a parent directory: {name}")
    if total_bytes > max_bytes:
        raise ValueError("Artifact exceeds its byte limit")
    return value


class _BoundedReader:
    def __init__(self, stream, limit):
        self.stream = stream
        self.remaining = limit

    def read(self, size):
        data = self.stream.read(min(size, self.remaining + 1))
        if len(data) > self.remaining:
            raise ValueError("Expanded tar archive exceeds its byte limit")
        self.remaining -= len(data)
        return data


def write_manifest(directory, *, metadata=None, max_bytes=DEFAULT_MAX_BYTES):
    """Atomically inventory a directory's payload files and caller metadata."""
    _check_limit(max_bytes)
    directory = Path(directory)
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("Artifact metadata must be a dictionary")
    value = {"version": 1, "metadata": metadata, "files": _inventory(directory, max_bytes)}
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ValueError("Artifact manifest exceeds its byte limit")
    target = directory / MANIFEST_NAME
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def verify_manifest(directory, *, max_bytes=DEFAULT_MAX_BYTES):
    """Return the manifest after verifying all tracked files and their hashes."""
    _check_limit(max_bytes)
    directory = Path(directory)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ValueError(f"Artifact root must be a directory: {directory}")
    with _open_regular(directory / MANIFEST_NAME) as stream:
        manifest = _read_manifest(stream, max_bytes)
    if _inventory(directory, max_bytes) != manifest["files"]:
        raise ValueError("Artifact file inventory, size, or hash mismatch")
    return manifest


def _read_archive_members(bundle, max_bytes):
    manifest = None
    actual = {}
    remaining = max_bytes
    for member in bundle:
        name = member.name
        _safe_path(name)
        if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.sparse is not None:
            raise ValueError(f"Archive contains a non-regular file: {name}")
        if name in actual or (name == MANIFEST_NAME and manifest is not None):
            raise ValueError(f"Archive contains a duplicate member: {name}")
        if name == MANIFEST_NAME:
            if not 0 <= member.size <= _MAX_MANIFEST_BYTES:
                raise ValueError("Artifact manifest exceeds its byte limit")
            with bundle.extractfile(member) as payload:
                manifest = _read_manifest(payload, max_bytes)
            continue
        if len(actual) >= _MAX_FILES or not 0 <= member.size <= remaining:
            raise ValueError("Archive exceeds its file count or byte limit")
        with bundle.extractfile(member) as payload:
            actual[name] = {"path": name, **_fingerprint(payload, limit=remaining)}
        remaining -= actual[name]["bytes"]
    if manifest is None or [actual[name] for name in sorted(actual)] != manifest["files"]:
        raise ValueError("Archive manifest missing or member inventory, size, or hash mismatch")
    return manifest


def verify_archive(archive, *, max_bytes=DEFAULT_MAX_BYTES):
    """Verify every gzip tar member by streaming, without extraction."""
    _check_limit(max_bytes)
    archive_limit = max_bytes + 8 * 1024**2
    with _open_regular(Path(archive)) as stream:
        # Account for one manifest plus tar headers, padding, and gzip overhead.
        archive_fingerprint = _fingerprint(stream, limit=archive_limit)
        stream.seek(0)
        with gzip.GzipFile(fileobj=stream) as compressed:
            expanded = _BoundedReader(compressed, archive_limit)
            with tarfile.open(fileobj=expanded, mode="r|") as bundle:
                manifest = _read_archive_members(bundle, max_bytes)
            # Finish the gzip stream so its trailer CRC and size are also checked.
            while expanded.read(_BLOCK_SIZE):
                pass
    return {**archive_fingerprint, "manifest": manifest}


def package_directory(directory, archive, *, max_bytes=DEFAULT_MAX_BYTES):
    """Write a verified gzip tar outside its source directory and return its receipt."""
    directory = Path(directory)
    archive = Path(archive)
    if archive.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Archive output must be outside its source directory")
    if archive.exists() or archive.is_symlink():
        raise FileExistsError(archive)
    manifest = verify_manifest(directory, max_bytes=max_bytes)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=archive.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|") as bundle:
                    sizes = {MANIFEST_NAME: _MAX_MANIFEST_BYTES}
                    sizes.update({entry["path"]: entry["bytes"] for entry in manifest["files"]})
                    for name, size_limit in sizes.items():
                        with _open_regular(directory / name) as payload:
                            member = tarfile.TarInfo(name)
                            member.size = os.fstat(payload.fileno()).st_size
                            if member.size > size_limit:
                                raise ValueError(f"Artifact file grew during packaging: {name}")
                            member.mode = 0o644
                            bundle.addfile(member, fileobj=payload)
            output.close()
            receipt = verify_archive(temporary, max_bytes=max_bytes)
            if receipt["manifest"] != manifest:
                raise ValueError("Artifact manifest changed during packaging")
            os.link(temporary, archive)
        finally:
            temporary.unlink(missing_ok=True)
    return receipt
