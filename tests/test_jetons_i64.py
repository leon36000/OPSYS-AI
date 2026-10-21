from __future__ import annotations

import datetime as dt
import math

import pytest
from sqlalchemy import select

from opsys import jetons
from opsys.stockage.schema import USAGE_TOKENS

MAX_I64 = (1 << 63) - 1
JOUR = dt.date(2026, 9, 30)
DEP = "m09-demo"
MODELE = "modele-i64"


@pytest.mark.parametrize(
    "valeur", [True, False, 1.0, 1.5, -1, MAX_I64 + 1, float("inf"), float("-inf"), float("nan"), "12"]
)
def test_normaliser_refuse_valeurs_presentes_non_entieres_hors_borne_ou_non_finies(valeur):
    with pytest.raises(ValueError, match="entier 64 bits"):
        jetons.normaliser_usage({"input_tokens": valeur})


def test_normaliser_conserve_aliases_entiers_et_borne_i64():
    assert jetons.normaliser_usage({"input_tokens": MAX_I64, "output_tokens": 0}) == {
        "tokens_entree": MAX_I64, "tokens_sortie": 0, "tokens_cache_lus": 0,
    }
    assert jetons.normaliser_usage({"prompt_tokens": 12, "completion_tokens": 7,
                                    "cached_tokens": 4}) == {
        "tokens_entree": 12, "tokens_sortie": 7, "tokens_cache_lus": 4,
    }
    assert jetons.normaliser_usage({"input_tokens": 0, "prompt_tokens": 12})["tokens_entree"] == 12
    with pytest.raises(ValueError, match="entier 64 bits"):
        jetons.normaliser_usage({"input_tokens": 12, "prompt_tokens": math.nan})
    assert jetons.normaliser_usage(None) == {
        "tokens_entree": 0, "tokens_sortie": 0, "tokens_cache_lus": 0,
    }


def _lignes(session):
    with session() as cnx:
        return cnx.execute(select(USAGE_TOKENS).where(
            USAGE_TOKENS.c.departement == DEP,
            USAGE_TOKENS.c.modele == MODELE,
        ).order_by(USAGE_TOKENS.c.jour)).mappings().all()


def test_enregistrer_refuse_valeur_invalide_sans_ecriture(session):
    with session() as cnx, pytest.raises(ValueError, match="entier 64 bits"):
        jetons.enregistrer_usage(cnx, DEP, MODELE,
                                {"input_tokens": 9, "output_tokens": math.inf}, JOUR)
    assert _lignes(session) == []


def test_enregistrer_usage_refuse_depassement_atomique_et_garde_ligne(session):
    with session() as cnx:
        cnx.execute(USAGE_TOKENS.insert().values(
            jour=JOUR.isoformat(), departement=DEP, modele=MODELE, appels=10,
            tokens_entree=MAX_I64 - 1, tokens_sortie=20, tokens_cache_lus=30,
        ))
        with pytest.raises(ValueError, match="dépasse la borne signée 64 bits"):
            jetons.enregistrer_usage(cnx, DEP, MODELE,
                                    {"input_tokens": 2, "output_tokens": 5,
                                     "cache_read_tokens": 7}, JOUR)
    [ligne] = _lignes(session)
    assert (ligne["appels"], ligne["tokens_entree"], ligne["tokens_sortie"], ligne["tokens_cache_lus"]) == (
        10, MAX_I64 - 1, 20, 30)


def test_enregistrer_usage_borne_aussi_le_compteur_appels(session):
    with session() as cnx:
        cnx.execute(USAGE_TOKENS.insert().values(
            jour=JOUR.isoformat(), departement=DEP, modele=MODELE, appels=MAX_I64,
            tokens_entree=1, tokens_sortie=2, tokens_cache_lus=3,
        ))
        with pytest.raises(ValueError, match="dépasse la borne signée 64 bits"):
            jetons.enregistrer_usage(cnx, DEP, MODELE, {"input_tokens": 1}, JOUR)
    [ligne] = _lignes(session)
    assert (ligne["appels"], ligne["tokens_entree"]) == (MAX_I64, 1)


@pytest.mark.parametrize("champ,valeur", [
    ("appels", True), ("appels", 1.0), ("appels", -1), ("appels", MAX_I64 + 1),
    ("tokens_entree", math.inf), ("tokens_sortie", -1), ("tokens_cache_lus", MAX_I64 + 1),
])
def test_fixer_usage_valide_tous_les_compteurs_avant_sql(session, champ, valeur):
    compteurs = {"tokens_entree": 3, "tokens_sortie": 4, "tokens_cache_lus": 5}
    appels = 6
    if champ == "appels":
        appels = valeur
    else:
        compteurs[champ] = valeur
    with session() as cnx, pytest.raises(ValueError, match="entier 64 bits"):
        jetons.fixer_usage(cnx, JOUR, DEP, MODELE, appels, compteurs)
    assert _lignes(session) == []


def test_fixer_usage_accepte_borne_i64_exacte_et_remplace_valeur_absolue(session):
    compteurs = {"tokens_entree": MAX_I64, "tokens_sortie": 0, "tokens_cache_lus": 0}
    with session() as cnx:
        jetons.fixer_usage(cnx, JOUR, DEP, MODELE, MAX_I64, compteurs)
    [ligne] = _lignes(session)
    assert (ligne["appels"], ligne["tokens_entree"]) == (MAX_I64, MAX_I64)


def test_consommation_retourne_exactement_un_agregat_superieur_a_i64_et_budget_epuise(session):
    with session() as cnx:
        cnx.execute(USAGE_TOKENS.insert().values(
            jour=JOUR.isoformat(), departement=DEP, modele=MODELE, appels=1,
            tokens_entree=MAX_I64, tokens_sortie=0, tokens_cache_lus=0,
        ))
        cnx.execute(USAGE_TOKENS.insert().values(
            jour=JOUR.isoformat(), departement=DEP, modele="modele-i64-2", appels=1,
            tokens_entree=1, tokens_sortie=0, tokens_cache_lus=0,
        ))
        assert jetons.consommation(cnx, DEP, JOUR, JOUR) == MAX_I64 + 1
        etat = jetons.etat_budget(cnx, DEP, jetons.Budget(tokens_jour=100, tokens_mois=100), JOUR)
        assert etat["niveau"] == "epuise"
        assert etat["jour"]["utilise"] == MAX_I64 + 1


def test_consommation_retourne_exactement_entree_plus_sortie_superieur_a_i64(session):
    with session() as cnx:
        cnx.execute(USAGE_TOKENS.insert().values(
            jour=JOUR.isoformat(), departement=DEP, modele=MODELE, appels=1,
            tokens_entree=MAX_I64, tokens_sortie=1, tokens_cache_lus=0,
        ))
        assert jetons.consommation(cnx, DEP, JOUR, JOUR) == MAX_I64 + 1


def test_fixer_usage_refuse_cle_absente_nomme_avant_sql(session):
    with session() as cnx, pytest.raises(ValueError, match=r"compteur\(s\) manquant\(s\).*tokens_sortie"):
        jetons.fixer_usage(cnx, JOUR, DEP, MODELE, 1, {"tokens_entree": 1, "tokens_cache_lus": 0})
    assert _lignes(session) == []
