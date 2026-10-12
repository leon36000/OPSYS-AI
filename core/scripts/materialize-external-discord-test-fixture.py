"""Materialize one pinned public test artifact, never install or execute a package."""

import argparse
import base64
import hashlib
import io
import json
import os
import stat
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

URL = "https://registry.npmjs.org/@openclaw/discord/-/discord-2026.9.6.tgz"
SHA256 = "f43f8129d011d248463fe452a75d1c2f8ad2eb7c81a4a00f8e6315dfb2d50948"
SRI = "EjlDGt3+bFDi1y62kPZpXuvITH7VOTXlEBhqpGDSqVfF7JgitYcfrH1X7fZMJ1VFURAljlhWDKBMt3VALlYPBQ=="
ROWS_SHA256 = "d71332d1e058a6884fd31a1d1478d33272e1ad63043fba103dea46a10833dcfa"
ARCHIVE_BYTES, COUNT, UNPACKED_BYTES = 16467605, 6013, 51064599


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirected test artifact refused")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fail_walk(error):
    raise error


def physical_inventory(root):
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail_walk):
        for name in dirs + names:
            path = Path(directory) / name
            info = path.lstat()
            require(not stat.S_ISLNK(info.st_mode), "Fixture link refused")
            if stat.S_ISDIR(info.st_mode):
                continue
            require(stat.S_ISREG(info.st_mode), "Fixture special entry refused")
            files[path.relative_to(root).as_posix()] = {
                "sha256": digest(path.read_bytes()),
                "size": info.st_size,
                "mode": stat.S_IMODE(info.st_mode),
            }
    require(len(files) == COUNT, "Physical file count differs")
    return files


def rows_hash(files):
    rows = [[name, row["sha256"], row["size"], row["mode"]] for name, row in sorted(files.items())]
    return digest(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-file", type=Path)  # Explicit local pinned input for verification.
    args = parser.parse_args()
    repo, out = args.repo_root, args.output
    require(repo.is_absolute() and repo.resolve(strict=True) == repo, "Nonphysical checkout")
    require(out.is_absolute() and out.parent.resolve(strict=True) == out.parent, "Nonphysical output parent")
    require(
        not out.is_relative_to(repo) and "node_modules" not in out.parts,
        "Test fixture must be outside Source and node_modules",
    )
    require(not out.exists() and not out.is_symlink(), "Existing output/cache refused")
    if args.archive_file is not None:
        require(stat.S_ISREG(args.archive_file.lstat().st_mode), "Archive input is not regular")
        data = args.archive_file.read_bytes()
    else:
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
        with opener.open(URL, timeout=30) as response:
            require(response.status == 200 and response.geturl() == URL, "Foreign HTTP archive")
            data = response.read(ARCHIVE_BYTES + 1)
    require(len(data) == ARCHIVE_BYTES and digest(data) == SHA256, "Archive bytes differ")
    require(base64.b64encode(hashlib.sha512(data).digest()).decode() == SRI, "SRI differs")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        require(len(members) == COUNT, "Archive count differs")
        paths = {}
        for member in members:
            parts = member.name.split("/")
            require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE), "Nonregular tar entry")
            require(
                member.name.isascii()
                and "\\" not in member.name
                and len(parts) > 1
                and parts[0] == "package"
                and all(p not in ("", ".", "..") for p in parts),
                "Unsafe tar path",
            )
            name = PurePosixPath(*parts[1:]).as_posix()
            require(name not in paths and member.mode in (0o644, 0o755), "Duplicate/path mode")
            paths[name] = member
        require(sum(member.size for member in members) == UNPACKED_BYTES, "Archive sizes differ")
        for name in paths:
            require(
                all(
                    parent.as_posix() not in paths for parent in PurePosixPath(name).parents if parent.as_posix() != "."
                ),
                "File/ancestor collision",
            )
        out.mkdir(mode=0o700)
        root = out / "discord-2026.9.6"
        root.mkdir(mode=0o700)
        (out / "archive.tgz").write_bytes(data)  # Exclusive private directory; no cache reuse.
        expected = {}
        for name, member in paths.items():
            target = root / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with archive.extractfile(member) as stream:
                content = stream.read(member.size + 1)
            require(len(content) == member.size, "Truncated archive entry")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, member.mode)
            with os.fdopen(fd, "wb") as output:
                output.write(content)
                os.fchmod(output.fileno(), member.mode)  # Exact pinned generated-file mode, not Source.
            expected[name] = {"sha256": digest(content), "size": member.size, "mode": member.mode}
        require(rows_hash(expected) == ROWS_SHA256, "Portable pinned archive rows differ")
        actual = physical_inventory(root)
        require(actual == expected, "Materialized bytes/size/modes differ")
        inventory = {"root": str(root), "files": actual, "count": COUNT}
        with (out / "inventory.json").open("x") as output:
            json.dump(inventory, output, sort_keys=True)
            output.write("\n")
        receipt = {
            "materialization_only": True,
            "archive_SHA256": SHA256,
            "SRI_verified": True,
            "rows_SHA256": ROWS_SHA256,
            "files": COUNT,
            "bytes": UNPACKED_BYTES,
            "root": str(root),
            "inventory": str(out / "inventory.json"),
            "package_executed": False,
            "dependencies_installed": False,
        }
        with (out / "receipt.json").open("x") as output:
            json.dump(receipt, output, sort_keys=True)
            output.write("\n")
        print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()  # Every HTTP/IO/quota/parse/integrity failure is nonzero; no cleanup or retry.
