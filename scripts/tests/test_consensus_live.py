import hashlib
import importlib.util
import json
import subprocess
import sys
import threading
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "consensus_run.py"
_spec = importlib.util.spec_from_file_location("consensus_run", _MODULE_PATH)
consensus_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(consensus_run)

DEFAULT_MODELS = consensus_run.DEFAULT_MODELS
VENDORS_TABLE = consensus_run.VENDORS_TABLE
PROMPT_PREAMBLE = consensus_run.PROMPT_PREAMBLE


def _write_pack(tmp_path, text):
    pack = tmp_path / "pack.md"
    pack.write_text(text, encoding="utf-8")
    return str(pack)


def _expected_sha256(pack_text):
    prompt = PROMPT_PREAMBLE + "\n\nPACK (VERBATIM):\n" + pack_text
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _verdict_dict(verdict="APPROVE", objections=None, **extra):
    if objections is None:
        objections = []
    return {"verdict": verdict, "objections": objections, **extra}


def _transport_from_mapping(mapping, calls=None, lock=None):
    def transport(alias, prompt):
        if lock is not None:
            with lock:
                if calls is not None:
                    calls.append(alias)
        else:
            if calls is not None:
                calls.append(alias)
        resp = mapping.get(alias)
        if isinstance(resp, Exception):
            raise resp
        if resp is None:
            raise RuntimeError(f"transport non prévu pour {alias}")
        return resp

    return transport


def test_12_valid_approve_revele_et_tally_approuve(tmp_path, capsys):
    pack_text = "PACK TEST 12 VALIDES"
    pack_path = _write_pack(tmp_path, pack_text)
    outdir = tmp_path / "out"

    mapping = {alias: json.dumps(_verdict_dict()) for alias in DEFAULT_MODELS}
    calls = []
    transport = _transport_from_mapping(mapping, calls=calls, lock=threading.Lock())

    rc = consensus_run.live(
        DEFAULT_MODELS, transport, str(outdir), "anthropic", pack_path
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert "PREUVE: consensus live -> tally APPROVED" in captured.out
    assert set(calls) == set(DEFAULT_MODELS)

    visible = list(outdir.glob("*.json"))
    assert len(visible) == len(DEFAULT_MODELS)
    assert len(list(outdir.glob(".tmp-*"))) == 0

    expected_sha = _expected_sha256(pack_text)
    for f in visible:
        alias = f.stem
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["reviewer"] == alias
        assert data["vendor"] == VENDORS_TABLE[alias]
        assert data["prompt_sha256"] == expected_sha
        assert data["date_heure"]

    raw_dir = outdir / "raw"
    assert len(list(raw_dir.glob("*.txt"))) == len(DEFAULT_MODELS)


def test_un_invalid_aucun_revele_tmp_conserves(tmp_path):
    pack_text = "PACK TEST 1 INVALIDE"
    pack_path = _write_pack(tmp_path, pack_text)
    outdir = tmp_path / "out"

    invalid_alias = DEFAULT_MODELS[0]
    mapping = {
        alias: json.dumps(_verdict_dict()) for alias in DEFAULT_MODELS if alias != invalid_alias
    }
    mapping[invalid_alias] = "ceci n'est absolument pas du JSON"

    rc = consensus_run.live(
        DEFAULT_MODELS, _transport_from_mapping(mapping), str(outdir), "anthropic", pack_path
    )

    assert rc == 2
    assert len(list(outdir.glob("*.json"))) == 0
    tmp_files = list(outdir.glob(".tmp-*"))
    assert len(tmp_files) == len(DEFAULT_MODELS) - 1
    assert not any(f.name == f".tmp-{invalid_alias}" for f in tmp_files)


def test_relance_ciblee_reutilise_et_revele(tmp_path):
    pack_text = "PACK TEST RELANCE CIBLEE"
    pack_path = _write_pack(tmp_path, pack_text)
    outdir = tmp_path / "out"

    missing_alias = DEFAULT_MODELS[5]
    first_mapping = {
        alias: json.dumps(_verdict_dict())
        for alias in DEFAULT_MODELS
        if alias != missing_alias
    }
    first_mapping[missing_alias] = "pas de json"

    rc1 = consensus_run.live(
        DEFAULT_MODELS,
        _transport_from_mapping(first_mapping),
        str(outdir),
        "anthropic",
        pack_path,
    )
    assert rc1 == 2

    calls = []

    def transport2(alias, prompt):
        calls.append(alias)
        if alias == missing_alias:
            return json.dumps(_verdict_dict())
        raise AssertionError(f"relance a rappelé {alias}")

    rc2 = consensus_run.live(
        DEFAULT_MODELS, transport2, str(outdir), "anthropic", pack_path
    )

    assert rc2 == 0
    assert set(calls) == {missing_alias}

    visible = list(outdir.glob("*.json"))
    assert len(visible) == len(DEFAULT_MODELS)
    assert {f.stem for f in visible} == set(DEFAULT_MODELS)
    assert len(list(outdir.glob(".tmp-*"))) == 0


def test_script_ecrase_champs_falsifies_par_le_modele(tmp_path):
    pack_text = "PACK TEST FAUX CHAMPS"
    pack_path = _write_pack(tmp_path, pack_text)
    outdir = tmp_path / "out"

    liar = DEFAULT_MODELS[3]
    mapping = {}
    for alias in DEFAULT_MODELS:
        if alias == liar:
            mapping[alias] = json.dumps(
                _verdict_dict(
                    reviewer="fake-reviewer",
                    vendor="fake-vendor",
                    date_heure="1970-01-01T00:00:00Z",
                    prompt_sha256="0" * 64,
                )
            )
        else:
            mapping[alias] = json.dumps(_verdict_dict())

    rc = consensus_run.live(
        DEFAULT_MODELS, _transport_from_mapping(mapping), str(outdir), "anthropic", pack_path
    )
    assert rc == 0

    data = json.loads((outdir / f"{liar}.json").read_text(encoding="utf-8"))
    assert data["reviewer"] == liar
    assert data["vendor"] == VENDORS_TABLE[liar]
    assert data["prompt_sha256"] == _expected_sha256(pack_text)
    assert data["date_heure"] != "1970-01-01T00:00:00Z"


def test_fences_json_et_texte_parasite_sont_parses(tmp_path):
    pack_text = "PACK TEST FENCES"
    pack_path = _write_pack(tmp_path, pack_text)
    outdir = tmp_path / "out"

    fenced = DEFAULT_MODELS[4]
    mapping = {}
    for alias in DEFAULT_MODELS:
        if alias == fenced:
            inner = json.dumps(_verdict_dict(), ensure_ascii=False)
            mapping[alias] = f"Voici mon évaluation :\n```json\n{inner}\n```\nMerci."
        else:
            mapping[alias] = json.dumps(_verdict_dict())

    rc = consensus_run.live(
        DEFAULT_MODELS, _transport_from_mapping(mapping), str(outdir), "anthropic", pack_path
    )
    assert rc == 0

    data = json.loads((outdir / f"{fenced}.json").read_text(encoding="utf-8"))
    assert data["verdict"] == "APPROVE"
    assert data["reviewer"] == fenced


def test_reject_avec_critique_propaga_rc3(tmp_path, capsys):
    pack_text = "PACK TEST REJECT CRITIQUE"
    pack_path = _write_pack(tmp_path, pack_text)
    outdir = tmp_path / "out"

    rejecter = DEFAULT_MODELS[7]
    mapping = {}
    for alias in DEFAULT_MODELS:
        if alias == rejecter:
            mapping[alias] = json.dumps(
                _verdict_dict(
                    verdict="REJECT",
                    objections=[
                        {
                            "severite": "critique",
                            "fichier": "pack.md",
                            "description": "objection bloquante de test",
                            "preuve": "test",
                        }
                    ],
                )
            )
        else:
            mapping[alias] = json.dumps(_verdict_dict())

    rc = consensus_run.live(
        DEFAULT_MODELS, _transport_from_mapping(mapping), str(outdir), "anthropic", pack_path
    )
    captured = capsys.readouterr()

    assert rc == 3
    assert "PREUVE: consensus live -> tally REJECTED" in captured.out
    assert len(list(outdir.glob("*.json"))) == len(DEFAULT_MODELS)

    data = json.loads((outdir / f"{rejecter}.json").read_text(encoding="utf-8"))
    assert data["verdict"] == "REJECT"


def test_mock_subprocess_byte_identique():
    mock_dir = _MODULE_PATH.parent.parent / "registries" / "verdicts" / "mock-phaseC"
    files = ["glm-5.2.json", "gemini-3.1-pro.json", "longcat-2.0.json"]

    before = {name: (mock_dir / name).read_bytes() if (mock_dir / name).exists() else None for name in files}

    result = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "--mock"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    expected = {
        "glm-5.2.json": json.dumps(
            {"reviewer": "glm-5.2", "vendor": "zhipu", "verdict": "APPROVE", "objections": []},
            ensure_ascii=False,
        ).encode("utf-8"),
        "gemini-3.1-pro.json": json.dumps(
            {"reviewer": "gemini-3.1-pro", "vendor": "google", "verdict": "APPROVE", "objections": []},
            ensure_ascii=False,
        ).encode("utf-8"),
        "longcat-2.0.json": json.dumps(
            {
                "reviewer": "longcat-2.0",
                "vendor": "meituan",
                "verdict": "APPROVE",
                "objections": [
                    {
                        "severite": "mineure",
                        "fichier": "pack",
                        "description": "exemple",
                        "preuve": "n/a",
                    }
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8"),
    }

    for name in files:
        p = mock_dir / name
        assert p.exists()
        after = p.read_bytes()
        if before[name] is not None:
            assert after == before[name], f"{name} n'est pas byte-identique après --mock"
        else:
            assert after == expected[name], f"{name} ne correspond pas au contenu déterministe attendu"
