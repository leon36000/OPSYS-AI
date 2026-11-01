"""Banc de qualification en conteneur (install/qualification) : ses parties pures, sans Docker.

Ce qu'on prouve ici : le masque de secrets (aucune valeur ne passe dans une preuve), la lecture du verrou et de ses
marqueurs, la copie hors réseau des dépendances (jamais substituées : une absence est dite), l'empreinte de
contenu d'une base (stable, sensible à un octet, indifférente aux lignes `instance.*` du journal). Le parcours
réel, lui, est joué par `banc.py` (preuves dans docs/qualification/preuves/).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "install" / "qualification"


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(f"qualif_{nom}", DOSSIER / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[spec.name] = module  # type: ignore[union-attr]  # les dataclasses relisent leur module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


banc = _charger("banc")
interne = _charger("interne")
preparer = _charger("preparer_contexte")


def test_le_masque_remplace_les_secrets_et_detecte_les_fuites():
    m = banc.Masque()
    secret = m.ajouter("jeton-fictif-0123456789abcdef")
    m.ajouter("court")  # trop court : ignoré (un mot courant ne doit pas être masqué)
    assert m.masquer(f"Authorization: Bearer {secret}!") == "Authorization: Bearer ***!"
    assert m.fuites("rien ici") == [] and m.fuites(f"x{secret}") != []
    assert m.masquer("court") == "court"


def test_une_preuve_qui_contiendrait_un_secret_n_est_jamais_ecrite(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    b = banc.Banc(tmp_path / "preuves", "img", tmp_path, garder_image=True)
    with b.etape("T1-essai", "essai", "attendu") as e:
        e.constat("fuite", True, f"valeur {b.cle_fournisseur}")
        e.note(f"jeton {b.jetons['OPSYS_MCP_JETON']}")
    contenu = "".join(p.read_text() for p in b.dossier.iterdir())
    assert b.cle_fournisseur not in contenu and b.jetons["OPSYS_MCP_JETON"] not in contenu and "***" in contenu
    assert sorted(p.suffix for p in b.dossier.iterdir()) == [".json", ".md"]
    json.loads(next(b.dossier.glob("*.json")).read_text())  # JSON valide, horodaté
    b.nettoyer()


def test_un_constat_en_echec_fait_echouer_l_etape_et_une_exception_est_un_echec_consigne(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    b = banc.Banc(tmp_path / "preuves", "img", tmp_path, garder_image=True)
    with b.etape("T2-echec", "t", "a") as e:
        e.constat("faux", False, "détail")
    with b.etape("T3-panne", "t", "a"):
        raise RuntimeError("boum")
    assert [x.verdict for x in b.etapes] == ["ECHEC", "ECHEC"]
    assert "boum" in json.dumps(b.etapes[1].constats)
    b.nettoyer()


def test_lecture_du_verrou_et_marqueurs(tmp_path):
    verrou = tmp_path / "v.txt"
    verrou.write_text(
        "# commentaire\nalembic==1.20.0 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n    # via opsys-ai\n"
        "colorama==0.4.6 ; sys_platform == 'win32' \\\n    --hash=sha256:cc\n"
        "numpy==2.3.5 ; python_full_version < '3.14' \\\n    --hash=sha256:dd\n"
        "numpy==2.5.3 ; python_full_version >= '3.14' \\\n    --hash=sha256:ee\n")
    entrees = preparer.lire_verrou(verrou)
    assert [(n, v) for n, v, _ in entrees] == [
        ("alembic", "1.20.0"), ("colorama", "0.4.6"), ("numpy", "2.3.5"), ("numpy", "2.5.3")]
    vrai = [n + v for n, v, m in entrees if preparer.marqueur_vrai(m, "3.12.15")]
    assert vrai == ["alembic1.20.0", "numpy2.3.5"]


def test_la_copie_hors_reseau_dit_ce_qui_manque_et_ne_substitue_rien(tmp_path):
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    dist = site / "paquet_a-1.0.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text("Name: paquet-a\nVersion: 1.0\n")
    (site / "paquet_a").mkdir()
    (site / "paquet_a" / "__init__.py").write_text("X = 1\n")
    (site / "paquet_a" / "__pycache__").mkdir()
    (site / "paquet_a" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    (dist / "RECORD").write_text("paquet_a/__init__.py,,\npaquet_a/__pycache__/x.pyc,,\n../../../bin/x,,\n")
    verrou = tmp_path / "v.txt"
    verrou.write_text("paquet-a==1.0 \\\n    --hash=sha256:aa\npaquet-b==2.0 \\\n    --hash=sha256:bb\n"
                      "paquet-c==3.0 \\\n    --hash=sha256:cc\n")
    (site / "paquet_c-9.9.dist-info").mkdir()
    (site / "paquet_c-9.9.dist-info" / "METADATA").write_text("Name: paquet-c\nVersion: 9.9\n")
    (site / "paquet_c-9.9.dist-info" / "RECORD").write_text("")
    rapport = preparer.preparer(tmp_path / "venv", tmp_path / "sortie", verrou, "3.12.15")
    assert rapport["absentes_du_venv"] == ["paquet-b==2.0"]
    assert rapport["versions_differentes"] == [{"nom": "paquet-c", "verrou": "3.0", "installee": "9.9"}]
    assert rapport["empreintes_verrou_verifiees"] is False
    assert (tmp_path / "sortie/site-packages/paquet_a/__init__.py").read_text() == "X = 1\n"
    assert not list((tmp_path / "sortie").rglob("*.pyc")), "aucun .pyc copié"


def _base(chemin: Path, lignes: list[tuple]) -> Path:
    cnx = sqlite3.connect(chemin)
    cnx.execute("CREATE TABLE alembic_version (version_num TEXT)")
    cnx.execute("INSERT INTO alembic_version VALUES ('0040')")
    cnx.execute("CREATE TABLE personnes (id TEXT, nom TEXT)")
    cnx.execute("CREATE TABLE journal (id INTEGER, action TEXT)")
    cnx.executemany("INSERT INTO personnes VALUES (?, ?)", [(a, b) for a, b, _ in lignes])
    cnx.executemany("INSERT INTO journal VALUES (?, ?)", [(i, c) for i, (_, _, c) in enumerate(lignes)])
    cnx.commit()
    cnx.close()
    return chemin


def test_empreinte_stable_sensible_et_indifferente_aux_lignes_instance(tmp_path):
    a = interne.empreinte_base(_base(tmp_path / "a.db", [("1", "Alice (fictif)", "x.crée")]))
    b = interne.empreinte_base(_base(tmp_path / "b.db", [("1", "Alice (fictif)", "x.crée")]))
    assert a["sha256_global"] == b["sha256_global"] and a["integrity_check"] and a["revision"] == "0040"
    c = interne.empreinte_base(_base(tmp_path / "c.db", [("1", "Alice (fictive)", "x.crée")]))
    assert c["sha256_global"] != a["sha256_global"] and c["details"]["personnes"] != a["details"]["personnes"]
    # une ligne d'audit « instance.* » (export, restauration) ne change pas l'empreinte ; une autre, oui
    cnx = sqlite3.connect(tmp_path / "b.db")
    cnx.execute("INSERT INTO journal VALUES (99, 'instance.export')")
    cnx.commit()
    assert interne.empreinte_base(tmp_path / "b.db")["sha256_global"] == a["sha256_global"]
    cnx.execute("INSERT INTO journal VALUES (100, 'approbation.approuver')")
    cnx.commit()
    cnx.close()
    assert interne.empreinte_base(tmp_path / "b.db")["sha256_global"] != a["sha256_global"]


def test_la_taille_memoire_se_lit_en_octets():
    assert banc.en_octets("512m") == 512 * 1024**2 and banc.en_octets("4g") == 4 * 1024**3
    with pytest.raises(AttributeError):
        banc.en_octets("beaucoup")


def test_le_dockerfile_de_qualification_garde_la_production_non_root_et_les_memes_points_d_entree():
    texte = (DOSSIER / "Dockerfile").read_text()
    assert "USER opsys" in texte and 'ENTRYPOINT ["/opt/opsys/deploy/entrypoint.sh"]' in texte
    assert "EXPOSE 8765 8700" in texte and "--require-hashes" not in texte.split("# Tout le reste")[1]
    assert (DOSSIER / "Dockerfile.dockerignore").read_text() == (RACINE / "deploy/Dockerfile.dockerignore").read_text()
