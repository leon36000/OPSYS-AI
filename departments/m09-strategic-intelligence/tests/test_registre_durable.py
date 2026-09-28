"""Branchement du registre de snapshots M9 sur le stockage durable de l'instance (ADR-0009).

Même scénario (trois snapshots réels) rejoué en mémoire et en durable SQLite (base temporaire) :
mêmes maillons, mêmes hash, chaîne valide après relecture par une NOUVELLE instance Python
(aucun cache — la preuve qu'un redémarrage du processus ne perd rien), et une altération directe
d'un maillon en base est détectée par `valider_chaine()`.

Aucune garde AST du département (`conformite.verifier_conformite`,
`verifier_aucun_import_domaine`, `verifier_aucune_cause_signalee`) ne porte sur ce fichier :
toutes scannent `src/m9_strategic_intelligence`, jamais `tests/` (voir leurs appels dans
test_conformite.py) — aucune adaptation n'a donc été nécessaire (mandat, règle 4).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m9_strategic_intelligence import registre
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_SRC = Path(__file__).resolve().parents[1] / "src"

DEPARTEMENT = "m09-strategic-intelligence"
REGISTRE_NOM = "snapshots"


def _snapshot(module_source, horodatage, valeurs):
    return {"module_source": module_source, "horodatage": horodatage, "valeurs": valeurs}


_SNAPSHOTS = [
    _snapshot("M-durable", "2026-01-04T00:00:00Z", {"prevision": "100"}),
    _snapshot("M-durable", "2026-01-05T00:00:00Z", {"prevision": "110"}),
    _snapshot("M-durable", "2026-01-06T00:00:00Z", {"prevision": "120"}),
]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire, isolée de ~/.opsys et de toute autre suite (OPSYS_BASE_URL)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _rejouer(cible: registre.RegistreSnapshots) -> list[dict]:
    maillons = []
    for snapshot in _SNAPSHOTS:
        maillon, erreur = cible.ajouter(snapshot)
        assert erreur is None
        maillons.append(maillon)
    return maillons


def test_meme_scenario_en_memoire_et_en_durable_produit_les_memes_hash(base_durable):
    memoire = registre.RegistreSnapshots()
    _rejouer(memoire)

    with stockage.transaction():
        durable = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
        _rejouer(durable)

    # Relecture par une instance neuve (aucun cache Python) : même contenu, mêmes hash, que le
    # registre vive en mémoire ou dans la base durable.
    durable_relu = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
    assert durable_relu.lire() == memoire.lire()
    assert [m["hash_maillon"] for m in durable_relu.lire()] == [m["hash_maillon"] for m in memoire.lire()]
    assert durable_relu.hash_tete() == memoire.hash_tete() != registre.HASH_PREDECESSEUR_INITIAL
    assert memoire.valider_chaine() == (True, "")
    assert durable_relu.valider_chaine() == (True, "")


def test_valider_chaine_vrai_apres_relecture_par_une_nouvelle_instance(base_durable):
    with stockage.transaction():
        premiere = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
        _rejouer(premiere)
        tete_attendue = premiere.hash_tete()

    # Nouvelle instance, comme après un redémarrage du processus MCP : reconstruit son état
    # entièrement depuis la base, sans rien connaître de `premiere`.
    relue = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
    assert len(relue.lire()) == 3
    assert relue.hash_tete() == tete_attendue
    assert relue.valider_chaine() == (True, "")


def test_alteration_directe_d_un_maillon_en_base_est_detectee(base_durable):
    with stockage.transaction():
        cible = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
        _rejouer(cible)

    filtre = (
        (REGISTRES.c.departement == DEPARTEMENT)
        & (REGISTRES.c.registre == REGISTRE_NOM)
        & (REGISTRES.c.rang == 0)
    )
    with stockage.transaction() as cnx:
        # Altération SQL directe du premier maillon, hash_maillon laissé tel quel (comme une
        # écriture hors application) : valeurs et empreinte stockée divergent désormais.
        texte = cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one()
        maillon = codec.decoder(texte)
        assert maillon["valeurs"] == {"prevision": "100"}
        maillon["valeurs"] = {"prevision": "ALTERE-EN-BASE"}
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))

    relue = registre.RegistreSnapshots(maillons=stockage.maillons(DEPARTEMENT, REGISTRE_NOM))
    valide, message = relue.valider_chaine()
    assert valide is False
    assert "0" in message


def test_adaptateur_branche_le_registre_de_production_sur_stockage_maillons():
    """Preuve statique de la règle 2 (mission de branchement) : `outils()` sans argument —
    utilisé par `charger_outils()` en production — adosse le registre à
    `stockage.maillons("m09-strategic-intelligence", "snapshots")`."""
    texte = (_SRC / "m9_strategic_intelligence" / "outils.py").read_text(encoding="utf-8")
    assert 'stockage.maillons("m09-strategic-intelligence", "snapshots")' in texte
