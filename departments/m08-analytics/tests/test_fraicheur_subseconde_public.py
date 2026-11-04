"""Frontières subsecondes par l'outil public M8, avec des registres fictifs."""

from datetime import UTC, datetime, timedelta

import pytest
from m8_analytics import analytique_outils, jeux_fictifs
from m8_analytics import outils as m8_outils
from m8_analytics.registre import RegistreSnapshots

from opsys.outils import executer

FICTIF = True
_METRIQUE = "m8_taux_acceptation_pct"
_MAINTENANT = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _outils_publics():
    registres = jeux_fictifs.registres_fictifs()
    return {
        outil.nom: outil
        for outil in m8_outils.outils(
            registre_cible=RegistreSnapshots(),
            definitions_cible=[],
            faits_cible=registres["chantier"],
            faits_entonnoir_cible=registres["entonnoir"],
            faits_contenus_cible=registres["contenus"],
            faits_cash_libre_cible=registres["cash_libre"],
            historique_sante_cible=[],
            publications_cible=[],
        )
    }


@pytest.mark.parametrize(
    ("age_us", "statut", "age_s", "a_jour"),
    [
        (-1, "inconnu", None, False),
        (0, "a_jour", 0, True),
        (1, "a_jour", 0, True),
        (60_000_000, "a_jour", 60, True),
        (60_000_001, "a_jour", 60, True),
        (61_000_000, "perime", 61, False),
    ],
)
def test_m8_lire_mesures_preserve_le_signe_et_les_frontieres_en_secondes(
    monkeypatch, age_us, statut, age_s, a_jour
):
    dernier_fait = (_MAINTENANT - timedelta(microseconds=age_us)).isoformat()
    lire_original = analytique_outils.moteur_mesures.lire

    def lire_avec_instant_borne(faits, catalogue):
        mesures = lire_original(faits, catalogue)
        mesure = next(m for m in mesures if m["metric_id"] == _METRIQUE)
        assert mesure["statut"] == "calculee"
        mesure["dernier_fait_le"] = dernier_fait
        return mesures

    monkeypatch.setattr(analytique_outils.moteur_mesures, "lire", lire_avec_instant_borne)
    reponse = executer(
        _outils_publics()["m8_lire_mesures"],
        {"maintenant": _MAINTENANT.isoformat(), "fraicheur_max_s": 60, "metric_ids": [_METRIQUE]},
    )

    assert reponse["ok"] is True, reponse
    mesure = reponse["resultat"]["mesures"][0]
    assert mesure["dernier_fait_le"] == dernier_fait
    assert mesure["fraicheur"] == statut
    assert mesure["age_s"] == age_s
    assert mesure["a_jour"] is a_jour
