from __future__ import annotations


def generate_replay_script(evidence: dict) -> str:
    """Return the contents of a standalone Python replay script."""
    return '''import hashlib
import json
from pathlib import Path
import sys


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    bundle = Path(__file__).resolve().parent
    with (bundle / "evidence.json").open("r", encoding="utf-8") as handle:
        evidence = json.load(handle)

    errors = []
    entries = list(evidence["inputs_manifest"]) + list(evidence["outputs_manifest"])

    for entry in entries:
        relative_path = entry["path"]
        path = (bundle / relative_path).resolve()
        try:
            actual_hash = sha256_file(path)
        except (OSError, IsADirectoryError):
            errors.append("missing or unreadable: " + str(relative_path))
            continue

        if actual_hash != entry["sha256"]:
            errors.append(
                "hash mismatch: "
                + str(relative_path)
                + " (expected "
                + str(entry["sha256"])
                + ", got "
                + actual_hash
                + ")"
            )

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("Replay successful")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''
