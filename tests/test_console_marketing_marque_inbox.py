"""La réputation fictive consomme la marque canonique, sans repli après corruption."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml
from m7_marketing.brand import profil_client, registre
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage.schema import REGISTRES

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "marque_console_fictive", ROOT / "tests/test_console_marketing_marque_usine.py",
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client = f.client
FICTIF = True
MARQUE_A = "Ancienne marque FICTIVE A"
MARQUE_B = "Marque canonique FICTIVE B"


@pytest.fixture(autouse=True)
def base_sqlite(monkeypatch):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)


@pytest.fixture
def console(client, tmp_path, monkeypatch):
    fichier = tmp_path / "marque-historique-fictive.yaml"
    fichier.write_text(yaml.safe_dump({
        "name": MARQUE_A, "tagline": "Travaux avec soin", "tone": "professionnel",
        "colors": ["#123456"], "langue": "fr",
    }))
    monkeypatch.setattr(profil_client, "_PROFIL_PAR_DEFAUT", fichier)
    return client, f._login(client), fichier


def _importer(console, cle="avis-canonique-fictif"):
    client, csrf, _fichier = console
    return client.post("/api/marketing/avis", headers={"x-csrf-token": csrf}, json={
        "action": "importer", "mutation_id": cle,
        "plateforme": "google_business_profile", "avis_source_id": cle,
        "date_avis": "2026-09-28", "note": 5,
        "texte": "Excellent travail, équipe ponctuelle et soignée.",
        "source_url": "https://business.google.com/reviews/avis-canonique-fictif",
    })


def _avis():
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", "reputation_avis"))


def _configurer(console, nom=MARQUE_B, revision=0):
    client, csrf, _fichier = console
    f._resultat(f._marque(client, csrf, nom, revision_attendue=revision))
    snap = registre.lire_snapshot_marque()
    assert snap["profil"]["name"] == nom
    assert snap["preuve"]["source"] == "brand_profiles"
    assert snap["preuve"]["revision"] == revision + 1


def test_inbox_suit_b_canonique_et_rejeu_historique_sans_recomposition(console):
    _configurer(console)
    f._resultat(_importer(console))
    avant = _avis()
    assert len(avant) == 1 and avant[0]["importe_par"] == "owner-r44"
    assert MARQUE_B in avant[0]["reponse_texte"]
    assert MARQUE_A not in avant[0]["reponse_texte"]
    _configurer(console, "Nouvelle marque FICTIVE C", revision=1)
    f._resultat(_importer(console))
    assert _avis() == avant  # Un reçu rejoué ne réécrit pas une réponse historique.
    f._resultat(_importer(console, "nouvel-avis-marque-c-fictif"))
    assert len(_avis()) == 2
    assert "Nouvelle marque FICTIVE C" in _avis()[-1]["reponse_texte"]


def test_marque_db_configuree_fonctionne_sans_yaml(console):
    _configurer(console)
    console[2].unlink()  # Seulement le YAML temporaire appartenant au fixture.
    f._resultat(_importer(console))
    assert MARQUE_B in _avis()[0]["reponse_texte"]


def test_marque_db_invalide_refuse_sans_repli_legacy_ni_reparation(console):
    _configurer(console)
    filtre = (REGISTRES.c.departement == "m07-marketing") & (REGISTRES.c.registre == "brand_profiles")
    with stockage.transaction() as cnx:
        assert cnx.execute(update(REGISTRES).where(filtre).values(maillon="{}")).rowcount == 1
    assert registre.lire_snapshot_marque()["statut"] == "refuse"
    response = _importer(console)
    assert response.status_code == 400, response.text
    assert response.json()["ok"] is False
    assert response.json()["erreur"]["code"] == "REJ-PROFIL-MARQUE"
    assert _avis() == []
    with stockage.transaction() as cnx:
        assert cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one() == "{}"


def test_legacy_valide_reste_utilisable_sans_marque_db(console):
    snap = registre.lire_snapshot_marque()
    assert snap["preuve"]["source"] == "yaml_legacy"
    f._resultat(_importer(console))
    assert len(_avis()) == 1 and MARQUE_A in _avis()[0]["reponse_texte"]
    assert registre.courant()["statut"] == "a_configurer"


@pytest.mark.parametrize("absence", ["fichier", "placeholder"])
def test_sans_marque_db_et_sans_legacy_configure_import_refuse(console, absence):
    if absence == "fichier":
        console[2].unlink()
    else:
        profil = yaml.safe_load(console[2].read_text())
        profil["name"] = profil_client.PLACEHOLDER_NOM
        console[2].write_text(yaml.safe_dump(profil))
    response = _importer(console)
    assert response.status_code == 400 and response.json()["ok"] is False
    assert response.json()["erreur"]["code"] == "REJ-PROFIL-MARQUE"
    assert _avis() == []
