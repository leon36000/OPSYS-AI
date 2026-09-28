"""Câblage des deux registres append-only de M10 sur le stockage durable de l'instance.

ADR-0009 (décisions 1-3, base unique par instance) et ADR-0010 (décision 2 : M10 gouverne,
les registres deviennent des lignes de la base — `registre_forge` renommé `registre_evenements`).

`registre.Registre` reste pur (DA-M10-08) : il ne sait pas si `maillons` est une liste en mémoire
ou `opsys.stockage.maillons(...)`. Ce test prouve que ça ne change rien à la chaîne de preuve
(mêmes hash des deux côtés) et que le « non-oubli » survit à un redémarrage du processus (une
NOUVELLE instance de `Registre`, pointant sur la même base, relit la chaîne intacte) — et qu'une
altération faite directement en base, hors de toute méthode du registre, est détectée.
"""

from __future__ import annotations

import pytest
from m10_memoire import decisions, registre, wct
from sqlalchemy import update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

HORODATAGE = "2026-08-04T12:00:00+00:00"
DEPARTEMENT = "m10-memoire"


def _wct(wct_id, consommateurs=("M6", "M5", "M10")):
    # `consommateurs_cibles` en TUPLE (pas une liste) : round-trip typé par `opsys.stockage.codec`
    # à vérifier — un tuple redevenu liste après relecture durable changerait le hash recalculé
    # (`encodage.py` distingue explicitement tuple et liste), ce que ce test doit exclure.
    return {
        "wct_id": wct_id,
        "intervention_id": "INT-001",
        "lead_id": "LEAD-001",
        "technicien_id": "TECH-001",
        "horodatage_completion": HORODATAGE,
        "fix_gps_completion": {"lat": "45.5", "lon": "-73.6"},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": "REV-001",
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": consommateurs,
        "devis_id": "DEV-001",
    }


def _decision(decision_id, raison):
    return {
        "decision_id": decision_id,
        "raison": raison,
        "statut": "validee",
        "options_ecartees": "Ne rien faire",
    }


_RAISONS = (
    "Raison suffisante et tracée pour la première décision.",
    "Deuxième décision motivée, options écartées documentées.",
    "Troisième décision : raison non vide obligatoire (règle 4 / D-032).",
)


def _peupler(registre_evenements, registre_affaires):
    """Écrit EXACTEMENT le même scénario (3 événements, 3 décisions dont une avec raison
    vérifiée) dans les deux registres reçus — en mémoire ou durables, la fonction ne le sait ni
    ne le décide (DA-M10-08 : ce test, comme `registre.py`, reste indifférent au magasin)."""
    for indice in range(3):
        maillon, code = wct.memoriser_wct(_wct(f"WCT-DUR-{indice}"), registre_evenements)
        assert code is None, code

    for indice, raison in enumerate(_RAISONS):
        maillon, code = decisions.enregistrer_decision(
            _decision(f"DEC-DUR-{indice}", raison), registre_affaires, HORODATAGE
        )
        assert code is None, code


@pytest.fixture
def base_sqlite(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée (ADR-0009), libérée après le test."""
    url = f"sqlite:///{tmp_path / 'm10-durable.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _registres_durables():
    return (
        registre.Registre(maillons=stockage.maillons(DEPARTEMENT, "evenements")),
        registre.Registre(maillons=stockage.maillons(DEPARTEMENT, "affaires")),
    )


def test_meme_scenario_memoire_et_durable_produit_les_memes_hash(base_sqlite):
    evenements_memoire = registre.Registre()
    affaires_memoire = registre.Registre()
    _peupler(evenements_memoire, affaires_memoire)

    with stockage.transaction():
        evenements_durable, affaires_durable = _registres_durables()
        _peupler(evenements_durable, affaires_durable)

    assert len(evenements_memoire.lire()) == 3 and len(evenements_durable.lire()) == 3
    assert len(affaires_memoire.lire()) == 3 and len(affaires_durable.lire()) == 3

    # Mêmes hash des deux côtés : le codec typé (dont le tuple consommateurs_cibles) ne modifie
    # pas la chaîne de preuve, quel que soit le magasin qui porte les maillons.
    assert [m["ligne_id"] for m in evenements_memoire.lire()] == [
        m["ligne_id"] for m in evenements_durable.lire()
    ]
    assert evenements_memoire.tete() == evenements_durable.tete()

    assert [m["ligne_id"] for m in affaires_memoire.lire()] == [
        m["ligne_id"] for m in affaires_durable.lire()
    ]
    assert affaires_memoire.tete() == affaires_durable.tete()

    # La raison motivée d'une décision survit telle quelle (texte français, accents compris) au
    # round-trip JSON typé du stockage durable.
    assert affaires_durable.lire()[-1]["raison"] == _RAISONS[-1]
    assert affaires_durable.lire()[-1]["raison"] == affaires_memoire.lire()[-1]["raison"]

    for reg in (evenements_memoire, affaires_memoire, evenements_durable, affaires_durable):
        assert reg.valider_chaine() == (True, "")


def test_le_non_oubli_survit_a_une_nouvelle_instance_apres_redemarrage(base_sqlite):
    with stockage.transaction():
        evenements, affaires = _registres_durables()
        _peupler(evenements, affaires)
    tete_evenements_avant = evenements.tete()
    tete_affaires_avant = affaires.tete()

    # NOUVELLES instances : aucun cache, aucun état module conservé — simule un redémarrage du
    # processus (les singletons de `outils.py` seraient recréés de la même façon à l'import).
    evenements_relu, affaires_relu = _registres_durables()

    assert len(evenements_relu.lire()) == 3
    assert len(affaires_relu.lire()) == 3
    assert evenements_relu.tete() == tete_evenements_avant
    assert affaires_relu.tete() == tete_affaires_avant
    assert evenements_relu.valider_chaine() == (True, "")
    assert affaires_relu.valider_chaine() == (True, "")
    assert affaires_relu.lire()[0]["raison"] == _RAISONS[0]


def test_une_alteration_en_base_est_detectee_a_la_relecture(base_sqlite):
    with stockage.transaction():
        evenements, affaires = _registres_durables()
        _peupler(evenements, affaires)

    premier_maillon = affaires.lire()[0]
    maillon_falsifie = {**premier_maillon, "raison": "FALSIFIEE"}

    # Altération directe en base, hors de toute méthode de `Registre` ou `MaillonsDurables`
    # (aucune des deux n'expose de mutation — DA-M10-06/CA-M10) : simule une corruption de la
    # ligne SQL elle-même, ce qu'un `UPDATE` malveillant ou un octet renversé sur disque ferait.
    with stockage.transaction() as cnx:
        cnx.execute(
            update(REGISTRES)
            .where(
                (REGISTRES.c.departement == DEPARTEMENT)
                & (REGISTRES.c.registre == "affaires")
                & (REGISTRES.c.rang == 0)
            )
            .values(maillon=codec.encoder(maillon_falsifie))
        )

    _, affaires_relu = _registres_durables()
    valide, detail = affaires_relu.valider_chaine()
    assert valide is False
    assert detail

    # Le registre Événements, lui, n'a pas été touché : sa chaîne reste intacte — l'altération
    # est bien détectée PAR REGISTRE, jamais globalement (CA-M10-06, registres distincts).
    evenements_relu = _registres_durables()[0]
    assert evenements_relu.valider_chaine() == (True, "")
