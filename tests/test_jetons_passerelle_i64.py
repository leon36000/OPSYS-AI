from __future__ import annotations

import datetime as dt
import math

import pytest
from sqlalchemy import select

from opsys import passerelle
from opsys.stockage.schema import USAGE_TOKENS

DATE_1 = dt.date(2026, 9, 30)
DATE_2 = dt.date(2026, 10, 1)


class FauxActiviteLiteLLM:
    def __init__(self, donnees):
        self.donnees = donnees

    def activite_quotidienne(self, *_args):
        return self.donnees


def _jour(date, metrics):
    return {"date": date.isoformat(), "metrics": metrics}


def _lignes(session):
    with session() as cnx:
        return cnx.execute(select(USAGE_TOKENS).where(
            USAGE_TOKENS.c.departement == "m09-demo",
        )).mappings().all()


@pytest.mark.parametrize("champ,valeur", [
    ("successful_requests", 1.5),
    ("prompt_tokens", True),
    ("completion_tokens", math.nan),
    ("cache_read_input_tokens", (1 << 63)),
])
def test_sync_litellm_refuse_compteurs_bruts_invalides_et_rollback_tous_les_jours(
    champ, valeur, departements_demo, session,
):
    premiere = {"successful_requests": 1, "prompt_tokens": 8, "completion_tokens": 3,
                "cache_read_input_tokens": 1}
    seconde = {"successful_requests": 2, "prompt_tokens": 5, "completion_tokens": 2,
               "cache_read_input_tokens": 0}
    seconde[champ] = valeur
    client = FauxActiviteLiteLLM([_jour(DATE_1, premiere), _jour(DATE_2, seconde)])

    with pytest.raises(ValueError, match="entier 64 bits"), session() as cnx:
        passerelle.synchroniser_usage(
            client, cnx, [departements_demo["m09-demo"]], DATE_1, DATE_2,
        )
    assert _lignes(session) == []


def test_sync_litellm_valeurs_brutes_valides_et_champs_absents_conserves(departements_demo, session):
    client = FauxActiviteLiteLLM([_jour(DATE_1, {
        "successful_requests": 4, "prompt_tokens": 12, "completion_tokens": 6,
        "cache_read_input_tokens": 2,
    }), _jour(DATE_2, {"successful_requests": 1, "prompt_tokens": 7})])
    with session() as cnx:
        assert passerelle.synchroniser_usage(
            client, cnx, [departements_demo["m09-demo"]], DATE_1, DATE_2,
        ) == 2

    lignes = sorted(_lignes(session), key=lambda ligne: ligne["jour"])
    assert [(ligne["appels"], ligne["tokens_entree"], ligne["tokens_sortie"],
             ligne["tokens_cache_lus"]) for ligne in lignes] == [(4, 12, 6, 2), (1, 7, 0, 0)]
