from __future__ import annotations

import sys
import tempfile
from functools import partial
from pathlib import Path

import pytest

from _harness import (
    DEFAULT_PROFILE_PATH,
    assert_brand_contract,
    get_build_server,
    http_get,
    media_type,
    running_server,
)


def _server_factory(profile_path):
    return partial(get_build_server(), profile_path=str(profile_path))


def test_get_brand_contract() -> None:
    with running_server(_server_factory(DEFAULT_PROFILE_PATH)) as base_url:
        assert_brand_contract(base_url)


def test_invalid_yaml_500() -> None:
    build_server = get_build_server()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as file:
        file.write("not: [valid\n")
        tmp_path = file.name
    try:
        with running_server(
            partial(build_server, profile_path=tmp_path)
        ) as base_url:
            code, headers, body = http_get(f"{base_url}/brand")
            assert code == 500, f"YAML invalide attendu 500, obtenu {code}"
            assert media_type(headers) == "application/problem+json", (
                f"YAML invalide Content-Type inattendu: {headers.get('Content-Type')}"
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_server_teardown_repeatable() -> None:
    factory = _server_factory(DEFAULT_PROFILE_PATH)
    for run in range(2):
        with running_server(factory) as base_url:
            code, _, _ = http_get(f"{base_url}/brand")
            assert code == 200, f"run {run}: attendu 200, obtenu {code}"


if __name__ == "__main__":
    try:
        test_get_brand_contract()
        test_invalid_yaml_500()
        test_server_teardown_repeatable()
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("OK")
    raise SystemExit(0)
