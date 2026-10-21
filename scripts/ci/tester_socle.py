"""SOCLE: native full collection, stable file partitions and same-run runtime receipts.

The verifier uses only the standard library; pytest is imported only by run/collect.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path, PurePosixPath


class RefusSocle(Exception):
    """Incomplete or inconsistent CI evidence; never a successful empty partition."""


def context(root: Path, env=None) -> dict:
    env = os.environ if env is None else env
    sha = env.get("GITHUB_SHA", "")
    run_id, attempt = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", "")
    if (not re.fullmatch(r"[0-9a-f]{40}", sha)
            or not all(re.fullmatch(r"[1-9][0-9]{0,31}", x) for x in (run_id, attempt))):
        raise RefusSocle("CONTEXTE_INVALIDE")
    actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                            text=True, check=False, timeout=10, env=env)
    if actual.returncode != 0 or actual.stdout.strip() != sha:
        raise RefusSocle("CHECKOUT_DIFFERENT")
    return {"sha": sha, "run_id": run_id, "attempt": attempt}


def signature(root: Path) -> dict:
    files = [p for p in ("pyproject.toml", "pytest.ini", "uv.lock") if (root / p).is_file()]
    if not files:
        raise RefusSocle("CONFIGURATION_ABSENTE")
    return {**{p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files},
            "tester_socle.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def owner(path: str, parts: int = 2) -> int:
    return int.from_bytes(hashlib.sha256(path.encode("utf-8")).digest(), "big") % parts


def _inventory(items, root: Path) -> list[dict]:
    result = []
    for item in items:
        path = item.path.resolve().relative_to(root).as_posix()
        if not path.startswith("tests/") or not item.nodeid.startswith(path + "::"):
            raise RefusSocle("CIBLE_NON_NATIVE")
        result.append({"path": path, "nodeid": item.nodeid})
    return result


def _write(path: Path, data: dict) -> None:
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
    os.replace(temporary, path)


class Partition:
    def __init__(self, root, receipt, manifest):
        self.root, self.receipt, self.manifest = root, receipt, manifest

    def pytest_collection_modifyitems(self, config, items):
        import pytest

        if config.option.keyword or config.option.markexpr or config.option.deselect:
            raise pytest.UsageError("SOCLE_SELECTION_PARTIELLE_INTERDITE")
        inventory = _inventory(items, self.root)
        selected, removed = [], []
        for item in items:
            path = item.path.resolve().relative_to(self.root).as_posix()
            target = selected if owner(path) == self.receipt["part"] else removed
            target.append(item)
        if not inventory or not selected:
            raise pytest.UsageError("SOCLE_PART_VIDE")
        self.receipt["inventory"] = inventory
        self.receipt["selected"] = [item.nodeid for item in selected]
        items[:] = selected
        config.hook.pytest_deselected(items=removed)

    def pytest_collection_finish(self, session):
        if (session.testsfailed or not self.receipt["inventory"]
                or [i.nodeid for i in session.items] != self.receipt["selected"]):
            raise RefusSocle("COLLECTE_INCOMPLETE")
        self.receipt["collection_complete"] = True
        _write(self.manifest, self.receipt)

    def pytest_runtest_logreport(self, report):
        # Preserve occurrences, including duplicate IDs: a start or a green early exit is insufficient.
        if report.when == "teardown":
            self.receipt["completed"].append(report.nodeid)

    def pytest_sessionfinish(self, session, exitstatus):
        self.receipt["ended"] = True


def execute(mode: str, root: Path, part: int, parts: int, manifest: Path) -> int:
    import pytest

    if parts != 2 or type(part) is not int or part not in range(parts):
        raise RefusSocle("PARTITION_INVALIDE")
    root = root.resolve()
    identity, source = context(root), signature(root)
    receipt = {"schema": 1, **identity, "signature": source, "pytest_version": pytest.__version__,
               "mode": mode, "part": part, "parts": parts, "pytest_args": ["-rs"],
               "inventory": [], "selected": [], "completed": [], "collection_complete": False,
               "ended": False, "exit": None}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream)
    pytest.hookimpl(trylast=True)(Partition.pytest_collection_modifyitems)
    plugin = Partition(root, receipt, manifest)
    args = ["-rs", *(["--collect-only"] if mode == "collect" else [])]
    result = 1
    try:
        result = int(pytest.main(args, plugins=[plugin]))
    finally:
        if (not receipt["collection_complete"] or not receipt["ended"]
                or (mode == "run" and Counter(receipt["completed"]) != Counter(receipt["selected"]))):
            result = result or 1
        receipt["exit"] = result
        _write(manifest, receipt)
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RefusSocle("JSON_CLE_DUPLIQUEE")
        result[key] = value
    return result


def _invalid_constant(value):
    raise RefusSocle("JSON_CONSTANTE_INVALIDE")


def _read(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise RefusSocle("MANIFESTE_INVALIDE")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise RefusSocle("JSON_INVALIDE") from exc


def verify(directory: Path, identity: dict, source: dict) -> dict:
    prefix = f"socle-parts-{identity['run_id']}-{identity['attempt']}"
    expected = {f"{prefix}-{part}" for part in (0, 1)}
    if (not directory.is_dir() or directory.is_symlink()
            or {p.name for p in directory.iterdir()} != expected):
        raise RefusSocle("MANIFESTES_MANQUANTS_OU_SUPPLEMENTAIRES")
    full = None
    all_selected = []
    for part in (0, 1):
        artifact = directory / f"{prefix}-{part}"
        name = f"socle-part-{part}.json"
        if (not artifact.is_dir() or artifact.is_symlink()
                or {p.name for p in artifact.iterdir()} != {name}):
            raise RefusSocle("ARTEFACT_INVALIDE")
        data = _read(artifact / name)
        keys = {"schema", "sha", "run_id", "attempt", "signature", "pytest_version", "mode", "part", "parts",
                "pytest_args", "inventory", "selected", "completed", "collection_complete", "ended", "exit"}
        if (type(data) is not dict or set(data) != keys or type(data["schema"]) is not int or data["schema"] != 1
                or any(data[k] != v for k, v in identity.items()) or data["signature"] != source
                or type(data["part"]) is not int or data["part"] != part
                or type(data["parts"]) is not int or data["parts"] != 2
                or data["mode"] != "run" or data["pytest_args"] != ["-rs"]
                or type(data["pytest_version"]) is not str or not data["pytest_version"]
                or data["collection_complete"] is not True or data["ended"] is not True
                or type(data["exit"]) is not int or data["exit"] != 0):
            raise RefusSocle("PREUVE_RUNTIME_INCOMPLETE")
        inventory = data["inventory"]
        if type(inventory) is not list or not inventory:
            raise RefusSocle("INVENTAIRE_VIDE")
        for item in inventory:
            if (type(item) is not dict or set(item) != {"path", "nodeid"}
                    or type(item["path"]) is not str or type(item["nodeid"]) is not str
                    or not item["path"].startswith("tests/") or not item["path"].endswith(".py")
                    or "\\" in item["path"] or "\0" in item["path"]
                    or PurePosixPath(item["path"]).as_posix() != item["path"]
                    or any(piece in {"", ".", ".."} for piece in item["path"].split("/"))
                    or not item["nodeid"].startswith(item["path"] + "::")):
                raise RefusSocle("INVENTAIRE_INVALIDE")
        selected = [item["nodeid"] for item in inventory if owner(item["path"]) == part]
        if (not selected or data["selected"] != selected or type(data["completed"]) is not list
                or any(type(nodeid) is not str for nodeid in data["completed"])
                or Counter(data["completed"]) != Counter(selected)):
            raise RefusSocle("COUVERTURE_INCOMPLETE")
        if full is None:
            full = inventory, data["pytest_version"]
        elif full != (inventory, data["pytest_version"]):
            raise RefusSocle("INVENTAIRES_DIVERGENTS")
        all_selected.extend(selected)
    if full is None or Counter(all_selected) != Counter(i["nodeid"] for i in full[0]):
        raise RefusSocle("UNION_INCOMPLETE")
    return {"ok": True, "parts": 2, "tests": len(all_selected)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["run", "collect", "verify"])
    parser.add_argument("--part", type=int)
    parser.add_argument("--parts", type=int, default=2)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-dir", type=Path)
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    try:
        if args.mode == "verify":
            if args.manifest_dir is None or args.part is not None or args.parts != 2 or args.manifest is not None:
                raise RefusSocle("DOSSIER_REQUIS")
            print(json.dumps(verify(args.manifest_dir, context(root), signature(root))))
            return 0
        if args.manifest is None or args.part is None:
            raise RefusSocle("CONFIGURATION_REQUISE")
        return execute(args.mode, root, args.part, args.parts, args.manifest.resolve())
    except (RefusSocle, OSError, subprocess.SubprocessError):
        print("SOCLE_PREUVE_REFUSEE", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
