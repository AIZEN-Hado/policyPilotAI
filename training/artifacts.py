"""Stream hashes and verify archives without extracting or following symbolic links."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import tarfile

from .common import digest, read_json, save_json

MANIFEST = 'artifact-manifest.json'


def safe_name(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name or any(ord(c) < 32 for c in name):
        raise ValueError('Unsafe artifact path')
    if any(part.startswith('.') for part in path.parts):
        raise ValueError('Hidden files are not artifact inputs')
    return name


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Artifact must be a regular file, not a link')
    return path


def snapshot(directory, metadata):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Artifact root must be a regular directory')
    paths = []
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Artifact tree contains a symbolic link')
        if path.is_file() and path != directory / MANIFEST:
            safe_name(path.relative_to(directory).as_posix())
            paths.append(path)
    if not paths:
        raise ValueError('Empty artifact directory')
    value = {'kind': 'lora_adapter_requires_pinned_base', 'metadata': metadata,
             'files': {path.relative_to(directory).as_posix(): digest(path) for path in paths}}
    save_json(directory / MANIFEST, value)
    verify(directory)
    return value


def verify(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Artifact root must be a regular directory')
    manifest = read_json(regular(directory / MANIFEST))
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Invalid artifact manifest')
    actual = set()
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise ValueError('Artifact tree contains a symbolic link')
        if path.is_file() and path != directory / MANIFEST:
            actual.add(safe_name(path.relative_to(directory).as_posix()))
    if actual != set(files):
        raise ValueError('Artifact has missing or untracked files')
    for name, expected in files.items():
        safe_name(name)
        if digest(regular(directory / name)) != expected:
            raise ValueError('Artifact hash mismatch')
    return manifest


def pack(files, output):
    output = Path(output)
    if output.exists():
        raise ValueError('Archive already exists; preserve it and choose a new name')
    output.parent.mkdir(parents=True, exist_ok=True)
    hashes = {safe_name(name): digest(regular(path)) for name, path in files.items()}
    with tarfile.open(output, 'w:gz') as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    with tarfile.open(output, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) != len(files) or {m.name for m in members} != set(files):
            raise ValueError('Archive member list mismatch')
        for member in members:
            if not member.isfile():
                raise ValueError('Archive contains a link or special file')
            h = hashlib.sha256()
            with archive.extractfile(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
            if h.hexdigest() != hashes[member.name]:
                raise ValueError('Archived file read-back mismatch')
    receipt = {'archive': output.name, 'sha256': digest(output), 'files': hashes,
               'verified': 'All archived members were read back and hash-matched; no extraction used.'}
    save_json(output.with_name(output.name + '.manifest.json'), receipt)
    return receipt


def verify_archive(path):
    path = regular(path)
    receipt = read_json(regular(path.with_name(path.name + '.manifest.json')))
    if receipt.get('archive') != path.name or receipt.get('sha256') != digest(path):
        raise ValueError('Archive checksum does not match its receipt')
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        files = receipt['files']
        if len(members) != len(files) or {member.name for member in members} != set(files):
            raise ValueError('Archive member list mismatch')
        for member in members:
            safe_name(member.name)
            if not member.isfile():
                raise ValueError('Archive contains a non-regular member')
            h = hashlib.sha256()
            with archive.extractfile(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
            if h.hexdigest() != files[member.name]:
                raise ValueError('Archived member checksum mismatch')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?')
    parser.add_argument('--archive')
    args = parser.parse_args()
    if bool(args.directory) == bool(args.archive):
        parser.error('Supply one adapter directory or --archive FILE')
    value = verify_archive(args.archive) if args.archive else verify(args.directory)
    print('PASS: artifact member list and all hashes match. This does not prove model reload or generation.')
