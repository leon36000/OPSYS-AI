"""Preuve du branchement du registre M1 sur le stockage durable de l'instance (ADR-0009).

`registre.py` reste pur : il ignore que ses maillons viennent d'une liste Python ou de
`opsys.stockage.MaillonsDurables`. Ce test joue le MÊME scénario sur les deux et prouve
qu'ils se comportent à l'identique : mêmes ligne_id (le hash de chaîne), `valider_chaine()`
vrai après relecture par une instance neuve (redémarrage simulé, rien en cache), et une
altération faite directement en base — hors du registre, par une requête SQL brute sur
`registres_maillons` — détectée par `valider_chaine()` comme le serait une altération faite
en mémoire.

Import : ce fichier n'insère rien dans `sys.path` (contrairement à `test_registre.py`) — il
s'appuie sur `pythonpath` du `pyproject.toml` racine, comme `test_outils_agent.py`. Comme
aucun nom nu (`registre`, ...) n'est jamais importé ici, les deux gardes AST de
`test_module_structure.py` (sys.path visant le paquet, module M1 à plat dans sys.modules)
n'ont rien à voir avec ce fichier : aucune adaptation n'a été nécessaire.
"""

from __future__ import annotations

import pytest
from m1_front_office.registre import Registre
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_DEPARTEMENT = "m01-front-office"
_NOM_REGISTRE = "principal"


def _scenario() -> list[dict]:
    """Trois entrées représentatives des vrais types produits par le pipeline M1
    (voir outils.traiter_demande_entrante et consentement._ecrire_alerte_registre)."""
    return [
        {
            "type_entree": "signal",
            "horodatage": "2026-09-28T09:00:00-04:00",
            "canal": "texte",
            "conversation_id": "conv-1",
            "signal_id": "sig-1",
            "contenu_filtre": "Gouttières à Montréal, urgent.",
            "provenance_saine": True,
        },
        {
            "type_entree": "lead_emis",
            "horodatage": "2026-09-28T09:00:05-04:00",
            "canal": "texte",
            "conversation_id": "conv-1",
            "signal_id": "sig-1",
            "lead": {
                "ville": "Montréal",
                "schema_version": 2,
                "service": "gouttieres",
                "urgence_declaree": True,
            },
        },
        {
            "type_entree": "alerte",
            "horodatage": "2026-09-28T09:05:00-04:00",
            "marqueur": "absence_consentement",
        },
    ]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _remplir(reg: Registre) -> list[str]:
    return [reg.ajouter(entree) for entree in _scenario()]


def test_meme_scenario_meme_ligne_id_en_memoire_et_sur_stockage_durable(base_durable):
    memoire = Registre()
    ids_memoire = _remplir(memoire)

    with stockage.transaction():
        durable = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        ids_durable = _remplir(durable)

    # Trois entrées distinctes → trois ligne_id distincts, et le chaînage (donc le hash)
    # produit exactement la même suite d'identifiants, que le registre soit en mémoire ou
    # adossé au stockage durable : la chaîne de hash ne connaît pas son support.
    assert len(set(ids_memoire)) == 3
    assert ids_durable == ids_memoire
    assert durable.tete() == memoire.tete()

    lignes_memoire = memoire.lire()
    lignes_durables = durable.lire()
    assert type(lignes_durables) is list
    assert lignes_durables == lignes_memoire


def test_valider_chaine_vraie_apres_relecture_par_une_nouvelle_instance(base_durable):
    """Simulation de redémarrage : la deuxième instance ne partage aucun état Python
    avec la première (nouveau Registre, nouveau MaillonsDurables) — seule la base
    persiste, exactement ce qui se passe entre deux démarrages du processus OPSYS."""
    with stockage.transaction():
        ecrivain = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        ids_ecrits = _remplir(ecrivain)

    redemarre = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    assert redemarre.taille() == 3
    assert redemarre.tete() == ids_ecrits[-1]

    ok, verdict = redemarre.valider_chaine()
    assert ok is True
    assert verdict is None


def test_alteration_directe_en_base_detectee_par_valider_chaine(base_durable):
    """Une altération faite hors du registre — ici une requête SQL brute sur
    registres_maillons, comme le ferait un bogue ou une attaque contournant le module
    pur — casse le hash de chaîne et doit être détectée exactement comme une altération
    faite en mémoire (cf. test_registre.py::test_valider_chaine_detecte_alteration)."""
    with stockage.transaction():
        ecrivain = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        _remplir(ecrivain)

    filtre = (
        (REGISTRES.c.departement == _DEPARTEMENT)
        & (REGISTRES.c.registre == _NOM_REGISTRE)
        & (REGISTRES.c.rang == 1)  # le maillon "lead_emis"
    )
    with stockage.transaction() as cnx:
        texte_original = cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one()
        maillon = codec.decoder(texte_original)
        maillon["lead"]["ville"] = "Ailleurs"  # contenu changé, ligne_id NON recalculé
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))

    releve = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    ok, verdict = releve.valider_chaine()
    assert ok is False
    assert verdict["code"] == "REJ-CHAINE-ALTEREE"
