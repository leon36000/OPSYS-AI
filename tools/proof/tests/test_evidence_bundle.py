"""Tests des Evidence Bundles autonomes (C01-003).

Contrat exact (task spec `tasks/C01-003.md`) :
- `build_bundle(task_id: str, source_dir: Path, out_dir: Path) -> Path` :
  construit un bundle autonome sous `out_dir`, retourne le chemin du
  bundle.
- `replay_bundle(bundle: Path) -> ReplayResult` : rejoue un bundle DEPUIS
  N'IMPORTE QUEL chemin (jamais de chemin absolu de la machine créatrice
  codé en dur), vérifie chaque hash d'entrée/sortie, retourne un résultat
  structuré (jamais une exception pour un échec DE VÉRIFICATION — seul un
  problème structurel du bundle lève).

Format de `source_dir` (convention de ce module, documentée ici) :
    source_dir/manifest.json   -- déclare task_id, implementer_id, commit,
                                   tree, environment, inputs (liste de
                                   chemins RELATIFS à source_dir), outputs
                                   (idem), commands (liste de dicts avec
                                   receipt_dir pointant vers un dossier
                                   RELATIF contenant receipt.json/
                                   stdout.bin/stderr.bin), tests,
                                   limitations, rollback
    source_dir/<chemins inputs/outputs déclarés>
    source_dir/<receipt_dir déclarés>/{receipt.json,stdout.bin,stderr.bin}

Écrit par l'Orchestrateur AVANT toute implémentation (RED d'abord, TDD) —
le crew implémente `tools/proof/evidence_bundle.py` (+
`tools/proof/replay.py`, un GÉNÉRATEUR — le script autonome réel est
ÉCRIT PAR `build_bundle` DANS chaque bundle, pas un fichier statique
partagé) CONTRE ce fichier.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.proof.evidence_bundle import ReplayResult, build_bundle, replay_bundle

HEX64_A = "a" * 64
HEX64_B = "b" * 64


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_minimal(**overrides) -> dict:
    base = {
        "task_id": "C01-003",
        "implementer_id": "claude-code-orchestrateur",
        "commit": HEX64_A,
        "tree": HEX64_B,
        "environment": {"python": "/usr/bin/python3"},
        "inputs": ["inputs/spec.md"],
        "outputs": ["outputs/module.py"],
        "commands": [],
        "tests": [{"path": "tests/test_x.py", "framework": "pytest", "count": 1}],
        "limitations": [],
        "rollback": {"procedure": "git revert du commit atomique.", "tested": True, "receipt_refs": []},
    }
    base.update(overrides)
    return base


def _source_dir_valide(tmp_path: Path, nom: str = "source") -> Path:
    source = tmp_path / nom
    (source / "inputs").mkdir(parents=True)
    (source / "outputs").mkdir(parents=True)
    (source / "inputs" / "spec.md").write_text("spécification d'entrée", encoding="utf-8")
    (source / "outputs" / "module.py").write_text("def f(): return 1\n", encoding="utf-8")
    (source / "manifest.json").write_text(
        json.dumps(_manifest_minimal(), ensure_ascii=False), encoding="utf-8"
    )
    return source


def test_impl_menter_les_evidence_bundles_autonomes_1(tmp_path):
    """Cas RED obligatoire : rejouer depuis un chemin différent — un
    bundle construit à un endroit, puis COPIÉ ailleurs (répertoire
    entièrement différent, aucun lien avec le chemin de construction),
    doit rejouer IDENTIQUEMENT — aucun chemin absolu de la machine
    créatrice ne doit être codé en dur dans le bundle."""
    source = _source_dir_valide(tmp_path)
    out_dir_1 = tmp_path / "build_ici"
    bundle_1 = build_bundle("C01-003", source, out_dir_1)

    resultat_1 = replay_bundle(bundle_1)
    assert resultat_1.ok, resultat_1.errors

    # Copie le bundle vers un chemin TOTALEMENT différent (simulé : un
    # autre "tmp_path" indépendant, préfixe différent).
    ailleurs = tmp_path.parent / f"ailleurs-{tmp_path.name}" / "bundle-deplace"
    shutil.copytree(bundle_1, ailleurs)

    resultat_2 = replay_bundle(ailleurs)
    assert resultat_2.ok, resultat_2.errors
    assert resultat_2.errors == resultat_1.errors == []


def test_impl_menter_les_evidence_bundles_autonomes_2(tmp_path):
    """Cas RED obligatoire : rejeter un input ou output hash divergent —
    altérer le CONTENU d'un fichier copié dans le bundle (après
    construction) doit faire échouer le rejeu, jamais passer en
    silence."""
    source = _source_dir_valide(tmp_path)
    bundle = build_bundle("C01-003", source, tmp_path / "out")

    resultat_intact = replay_bundle(bundle)
    assert resultat_intact.ok

    # Trouve la copie du fichier de sortie DANS le bundle et le corrompt.
    copie_sortie = bundle / "outputs" / "module.py"
    assert copie_sortie.is_file()
    copie_sortie.write_text("def f(): return 999  # falsifie\n", encoding="utf-8")

    resultat_corrompu = replay_bundle(bundle)
    assert not resultat_corrompu.ok
    assert resultat_corrompu.errors, "un bundle corrompu doit rapporter au moins une erreur nommée"

    # Sous-cas ISOLÉ (mutation-testé séparément) : fichier manifesté
    # ENTIÈREMENT ABSENT du bundle, pas seulement corrompu — un contrôle
    # de hash divergent ne prouve pas, à lui seul, qu'un contrôle
    # DISTINCT « fichier présent » existe aussi.
    source_2 = _source_dir_valide(tmp_path, nom="source2")
    bundle_2 = build_bundle("C01-003", source_2, tmp_path / "out2")
    (bundle_2 / "outputs" / "module.py").unlink()
    resultat_absent = replay_bundle(bundle_2)
    assert not resultat_absent.ok
    assert any("module.py" in erreur for erreur in resultat_absent.errors), resultat_absent.errors


def test_impl_menter_les_evidence_bundles_autonomes_3(tmp_path):
    """Cas RED obligatoire : rejeter les chemins absolus de la machine
    créatrice — un manifest.json déclarant un chemin d'input/output
    ABSOLU (au lieu de relatif à source_dir) doit faire refuser
    build_bundle, jamais être silencieusement accepté et embarqué.

    Piège évité (mesuré) : la première version de ce test pointait le
    chemin absolu vers un fichier qui n'existait PAS réellement à cet
    emplacement — la garde de contrôle « fichier introuvable » (autre
    contrôle, non celui visé) suffisait alors à faire échouer
    build_bundle même avec le contrôle d'absoluité neutralisé,
    rendant la mutation invisible. Corrigé : le chemin absolu pointe
    vers un fichier RÉELLEMENT présent sur la machine (celui-là même
    que source/inputs/spec.md), pour isoler le contrôle d'absoluité
    seul — sans lui, `source_dir / chemin_absolu` (pathlib : le membre
    droit absolu écrase le gauche) résoudrait vers un fichier qui
    EXISTE, prouvant que seul le contrôle explicite protège ici.

    2e piège évité (mesuré) : `outputs=[]` faisait échouer
    `validate_evidence` sur « outputs_manifest non vide » AVANT même
    d'atteindre le contrôle d'absoluité en aval — ValueError levée pour
    la MAUVAISE raison, mutation invisible une seconde fois. Corrigé :
    `outputs` garde une entrée valide non liée à l'attaque testée."""
    source = tmp_path / "source_chemin_absolu"
    (source / "inputs").mkdir(parents=True)
    (source / "outputs").mkdir(parents=True)
    fichier_reel = source / "inputs" / "spec.md"
    fichier_reel.write_text("x", encoding="utf-8")
    (source / "outputs" / "module.py").write_text("def f(): return 1\n", encoding="utf-8")
    chemin_absolu_machine = str(fichier_reel.resolve())
    manifest = _manifest_minimal(inputs=[chemin_absolu_machine], outputs=["outputs/module.py"])
    (source / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError):
        build_bundle("C01-003", source, tmp_path / "out")


def test_impl_menter_les_evidence_bundles_autonomes_4(tmp_path):
    """Cas RED obligatoire : préserver stdout et stderr bruts — les
    octets EXACTS d'un stdout/stderr de commande enregistrée survivent la
    construction du bundle sans troncature, ré-encodage ni normalisation
    des fins de ligne."""
    source = tmp_path / "source_avec_commande"
    (source / "inputs").mkdir(parents=True)
    (source / "outputs").mkdir(parents=True)
    (source / "inputs" / "spec.md").write_text("x", encoding="utf-8")
    (source / "outputs" / "module.py").write_text("x", encoding="utf-8")

    receipt_dir = source / "receipts" / "cmd1"
    receipt_dir.mkdir(parents=True)
    stdout_brut = "ligne1\r\nligne2\x00binaire\xff".encode("latin-1")
    stderr_brut = b""
    (receipt_dir / "stdout.bin").write_bytes(stdout_brut)
    (receipt_dir / "stderr.bin").write_bytes(stderr_brut)
    (receipt_dir / "receipt.json").write_text(
        json.dumps(
            {
                "argv": ["python3", "-c", "pass"],
                "expected_returncode": 0,
                "actual_returncode": 0,
                "stdout_sha256": _sha256_bytes(stdout_brut),
                "stderr_sha256": _sha256_bytes(stderr_brut),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = _manifest_minimal(
        inputs=["inputs/spec.md"],
        outputs=["outputs/module.py"],
        commands=[{"kind": "GREEN_TEST", "receipt_dir": "receipts/cmd1"}],
    )
    (source / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    bundle = build_bundle("C01-003", source, tmp_path / "out")

    copie_stdout = (bundle / "receipts" / "cmd1" / "stdout.bin").read_bytes()
    copie_stderr = (bundle / "receipts" / "cmd1" / "stderr.bin").read_bytes()
    assert copie_stdout == stdout_brut, "stdout altéré pendant la construction du bundle"
    assert copie_stderr == stderr_brut, "stderr altéré pendant la construction du bundle"

    resultat = replay_bundle(bundle)
    assert resultat.ok, resultat.errors


# ---------------------------------------------------------------------------
# Robustesse additionnelle.
# ---------------------------------------------------------------------------


def test_build_bundle_genere_evidence_json_valide_selon_c01_002(tmp_path):
    """Le bundle produit un evidence.json qui passe validate_evidence
    (C01-002) — les deux tâches doivent rester cohérentes, jamais deux
    définitions divergentes de ce qu'est une preuve valide."""
    from tools.proof.schema_validation import validate_evidence

    source = _source_dir_valide(tmp_path)
    bundle = build_bundle("C01-003", source, tmp_path / "out")
    evidence = json.loads((bundle / "evidence.json").read_text(encoding="utf-8"))
    validate_evidence(evidence)  # ne lève pas


def test_build_bundle_genere_replay_py_autonome_sans_import_du_produit(tmp_path):
    """`replay.py` généré dans le bundle est réellement AUTONOME :
    stdlib uniquement, aucun `from tools.proof...` (le bundle peut être
    rejoué sur une machine sans ce dépôt), et rc=0 réel en exécution
    directe (pas seulement via replay_bundle())."""
    source = _source_dir_valide(tmp_path)
    bundle = build_bundle("C01-003", source, tmp_path / "out")

    contenu = (bundle / "replay.py").read_text(encoding="utf-8")
    assert "tools.proof" not in contenu, "replay.py importe le produit — pas autonome"
    assert "import jsonschema" not in contenu

    cp = subprocess.run([sys.executable, str(bundle / "replay.py")], capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_build_bundle_gros_fichier_reference_par_cas_petit_copie_inline(tmp_path):
    """« copier les petits artefacts; référencer les gros par CAS » —
    mesuré, pas supposé : un fichier au-dessus du seuil atterrit sous
    bundle/cas/<sha256>, un petit fichier reste copié à son chemin
    manifesté direct."""
    source = tmp_path / "source_gros_fichier"
    (source / "inputs").mkdir(parents=True)
    (source / "outputs").mkdir(parents=True)
    gros_contenu = b"x" * (2 * 1024 * 1024)  # 2 Mio, au-dessus de tout seuil raisonnable
    (source / "inputs" / "gros.bin").write_bytes(gros_contenu)
    (source / "outputs" / "module.py").write_text("petit", encoding="utf-8")
    manifest = _manifest_minimal(inputs=["inputs/gros.bin"], outputs=["outputs/module.py"])
    (source / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    bundle = build_bundle("C01-003", source, tmp_path / "out")

    assert not (bundle / "inputs" / "gros.bin").exists(), "le gros fichier n'aurait pas dû être copié inline"
    sha_gros = _sha256_bytes(gros_contenu)
    assert (bundle / "cas" / sha_gros).is_file(), "le gros fichier doit être référencé sous cas/<sha256>"
    assert (bundle / "cas" / sha_gros).read_bytes() == gros_contenu

    assert (bundle / "outputs" / "module.py").is_file(), "le petit fichier doit rester copié inline"

    resultat = replay_bundle(bundle)
    assert resultat.ok, resultat.errors
