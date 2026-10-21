"""Preuve du branchement du registre M3 sur le stockage durable de l'instance (ADR-0009).

``registre.py`` reste pur : il ignore que ses maillons viennent d'une liste Python ou de
``opsys.stockage.MaillonsDurables``. Ce test rejoue le MÊME scénario métier — trois charges
d'estimation ajoutées à la suite — en mémoire et en durable (base SQLite temporaire), et prouve
qu'ils se comportent à l'identique :

- mêmes ``hash_maillon``/``hash_precedent``, dans le même ordre (la chaîne de hash ne connaît
  pas son support) ;
- ``valider_chaine()`` vraie après relecture par une instance NEUVE (redémarrage simulé, rien
  en cache Python — seule la base persiste) ;
- l'adaptateur de production (``m3_estimation.outils.registre_production``) partage la même
  chaîne durable entre deux instances, comme le feraient deux processus de l'installation ;
- une altération faite directement en base — hors du registre, par une requête SQL brute sur
  ``registres_maillons``, comme le ferait un bogue ou une attaque qui contourne le module pur —
  est détectée par ``valider_chaine()`` exactement comme le serait une altération faite en
  mémoire (cf. ``test_registre.py``).

Types métier réels des charges : ``devis_id``/``lead_id``/``empreinte_marqueur_m2``/
``bareme_version`` sont des chaînes, ``niveau_confiance`` un flottant, ``graine_monte_carlo`` un
entier. Aucun champ de la charge n'est un ``Decimal`` dans le contrat actuel de ``registre.py`` —
``cout_reel``, seul candidat, est verrouillé à ``None`` par ``Registre.ajouter()`` et rejeté par
``valider_chaine()`` dès qu'il ne l'est pas (réservé à M5/M6, cf. docstring du module) : aucun
``Decimal`` n'est donc exercé ici, faute d'en avoir un dans le contrat à faire persister. Le codec
de stockage (``opsys.stockage.codec``) le supporte déjà (cf. ``tests/test_stockage.py``) et sera
exercé par ce test le jour où un champ ``Decimal`` rejoindra le contrat.

Import : comme ``test_outils_agent.py``, ce fichier s'appuie d'abord sur le ``pythonpath`` du
``pyproject.toml`` racine pour ``opsys`` ; l'import de ``m3_estimation`` insère explicitement
``src/`` en tête de ``sys.path`` (comme ``test_registre.py``), pour ne pas dépendre de l'ordre de
collecte d'autres fichiers de test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select, update

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation.registre import Registre  # noqa: E402

from opsys import stockage  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import REGISTRES  # noqa: E402

_DEPARTEMENT = "m03-estimation"
_NOM_REGISTRE = "principal"

_NB_MAILLONS_SCENARIO = 3
_RANG_ALTERE = 1


def _charge_valide(**surcharges):
    """Fabrique une charge d'estimation déterministe, types métier réels du contrat du registre."""
    charge = {
        "devis_id": "M3-DEVIS-durable",
        "lead_id": "lead-durable",
        "empreinte_marqueur_m2": "a" * 64,
        "niveau_confiance": 0.9,
        "bareme_version": "2026.1",
        "graine_monte_carlo": 314159,
    }
    charge.update(surcharges)
    return charge


def _ajouter_valide(journal: Registre, charge: dict) -> dict:
    """Ajoute une charge valide et affirme que l'ajout ne produit pas de rejet."""
    maillon, verdict = journal.ajouter(charge)
    assert verdict is None, f"ajout refusé : {verdict}"
    assert maillon is not None
    return maillon


def _jouer_scenario(journal: Registre) -> list[dict]:
    """Ajoute trois charges distinctes et retourne les maillons produits, dans l'ordre d'ajout."""
    return [
        _ajouter_valide(
            journal,
            _charge_valide(devis_id=f"M3-DEVIS-durable-{i:03d}", lead_id=f"lead-durable-{i:03d}"),
        )
        for i in range(_NB_MAILLONS_SCENARIO)
    ]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


# -- même scénario, en mémoire et en durable -----------------------------------------------
def test_meme_scenario_memes_hash_en_memoire_et_en_durable(base_durable):
    memoire = Registre()
    maillons_memoire = _jouer_scenario(memoire)

    with stockage.transaction():
        durable = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        maillons_durables = _jouer_scenario(durable)

    lignes_durables = durable.lire()
    assert type(lignes_durables) is list  # copie profonde -> liste, jamais MaillonsDurables

    hash_memoire = [m["hash_maillon"] for m in maillons_memoire]
    hash_durables = [m["hash_maillon"] for m in maillons_durables]
    # Autant de hash distincts que de maillons : aucune collision sur ce scénario.
    assert len(set(hash_memoire)) == _NB_MAILLONS_SCENARIO
    # La chaîne de hash ne connaît pas son support : mêmes charges, mêmes rangs -> mêmes
    # hash_maillon/hash_precedent, dans le même ordre, que le registre soit une liste Python
    # ou adossé au stockage durable.
    assert hash_durables == hash_memoire
    assert [m["hash_precedent"] for m in maillons_durables] == [m["hash_precedent"] for m in maillons_memoire]
    assert lignes_durables == memoire.lire()
    assert durable.hash_tete() == memoire.hash_tete() == maillons_memoire[-1]["hash_maillon"]
    assert durable.valider_chaine() == (True, "")
    assert memoire.valider_chaine() == (True, "")


# -- redémarrage simulé : nouvelle instance, rien en cache Python ----------------------------
def test_valider_chaine_apres_redemarrage_par_une_nouvelle_instance(base_durable):
    """``relu`` ne partage AUCUN état Python avec ``ecrivain`` — nouveau ``Registre``, nouveau
    ``MaillonsDurables`` — seule la base persiste, exactement ce qui se passe entre deux
    démarrages du processus OPSYS."""
    with stockage.transaction():
        ecrivain = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        maillons_ecrits = _jouer_scenario(ecrivain)
        tete_ecrite = ecrivain.hash_tete()

    relu = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    assert len(relu.lire()) == _NB_MAILLONS_SCENARIO
    assert relu.hash_tete() == tete_ecrite == maillons_ecrits[-1]["hash_maillon"]
    assert relu.valider_chaine() == (True, "")


# -- production : deux instances distinctes partagent la chaîne durable ---------------------
def test_deux_registres_de_production_partagent_la_chaine_durable(base_durable):
    """Deux appels à ``registre_production()`` sans argument simulent deux processus de
    l'instance (serveur MCP, console) : chacun relit la chaîne à chaque usage, voit les
    écritures de l'autre, et la chaîne reste valide."""
    from m3_estimation.outils import registre_production

    with stockage.transaction():
        processus_a = registre_production()
        _ajouter_valide(processus_a, _charge_valide(devis_id="M3-DEVIS-durable-proc-a"))

    processus_b = registre_production()
    assert len(processus_b.lire()) == 1

    with stockage.transaction():
        _ajouter_valide(processus_b, _charge_valide(devis_id="M3-DEVIS-durable-proc-b"))

    assert len(registre_production().lire()) == 2
    assert registre_production().valider_chaine() == (True, "")


# -- altération hors du module pur : détectée -------------------------------------------------
def test_alteration_directe_en_base_detectee_par_valider_chaine(base_durable):
    with stockage.transaction():
        ecrivain = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        _jouer_scenario(ecrivain)

    # Altération hors du registre : une requête SQL brute sur registres_maillons, comme le
    # ferait un bogue ou une attaque qui contourne complètement le module pur registre.py.
    filtre = (
        (REGISTRES.c.departement == _DEPARTEMENT)
        & (REGISTRES.c.registre == _NOM_REGISTRE)
        & (REGISTRES.c.rang == _RANG_ALTERE)
    )
    with stockage.transaction() as cnx:
        texte_original = cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one()
        maillon = codec.decoder(texte_original)
        assert maillon["charge"]["devis_id"] == "M3-DEVIS-durable-001"
        maillon["charge"]["lead_id"] = "lead-durable-altere"  # contenu changé, hash NON recalculé
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))

    releve = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    valide, diagnostic = releve.valider_chaine()
    assert valide is False
    assert f"rang {_RANG_ALTERE}" in diagnostic
