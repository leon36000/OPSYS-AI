"""M9.9 — tendance extrapolée sur de vraies captures de M2 (m2.leads) : droite, refus sous 6 points, rôle (fictif).

Les leads sont ingérés par la fonction publique de M2 (`m2.ingerer_lead`), capturés par le vrai dispatcher
(`m9_capturer_producteur`), relus dans le registre durable `captures_strategiques`, puis projetés par l'outil
`m9_projeter_tendance` construit ici (il n'est pas encore câblé dans `outils.py`) sous l'identité de l'admin.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from m2_revenue_crm import outils as m2
from m9_strategic_intelligence import outils_tendances

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements

FICTIF = True
M9, M2 = "m09-strategic-intelligence", "m02-revenue-crm"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
VENDEUR = IdentiteAppelante("vendeur.fictif", "seller", source="appareil")
DEBUT = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.UTC)
JOURS = 8  # jours 0 à 7 : 7 jours d'historique observés, l'horizon 7j reste dans l'historique


def _instant(jour: int, minutes: int = 0) -> str:
    return (DEBUT + dt.timedelta(days=jour, minutes=minutes)).isoformat().replace("+00:00", "Z")


def _ingerer(numero: int, jour: int) -> None:
    reponse = m2.ingerer_lead(
        {
            "lead_id": f"lead-tendance-{numero}",
            "conversation_id": f"conv-tendance-{numero}",
            "contact": {"nom": f"Client Fictif {numero}", "courriel": f"client{numero}@exemple-fictif.test"},
            "type_travaux": "renovation_totale",
            "ville": "Québec",
            "urgence_declaree": False,
            "canal": "telephone",
        },
        _instant(jour, minutes=-30),
    )
    assert reponse["accepte"] is True, reponse


def _appel(cap, nom, arguments, identite_appelante=ADMIN):
    with contexte.appele_par_appareil(identite_appelante):
        return cap.appeler(nom, arguments)


@pytest.fixture
def cap(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'tendances.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
    capacites = Capacites(charger_departements(), stockage.transaction, filtre={M9, M2}, memoire=False)
    # Un lead de plus avant chaque capture quotidienne : total M2 = 1, 2, …, 8 sur les jours 0 à 7.
    for jour in range(JOURS):
        _ingerer(jour + 1, jour)
        recu = _instant(jour)
        reponse = _appel(
            capacites,
            "m9_capturer_producteur",
            {"lecture_id": "m2.leads", "arguments": {"horodatage": recu}, "horodatage": recu},
        )
        assert reponse["ok"] is True and reponse["resultat"]["capture"]["complete"] is True, reponse
        assert reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE"
    yield capacites
    m2.reinitialiser_registre()
    stockage.liberer()


def _projeter(identite_appelante=ADMIN, **arguments):
    (outil,) = outils_tendances.construire_outils(budget_sortie=5900)
    appel = {"lecture_id": "m2.leads", "chemin": "resultat.resultat.total", "horizons": ["7j", "30j"], **arguments}
    with stockage.transaction():
        if identite_appelante is None:
            return outil.fonction(**appel)
        with contexte.appele_par_appareil(identite_appelante):
            return outil.fonction(**appel)


def test_projection_a_7j_suit_la_droite_des_totaux_reels_de_m2(cap):
    res = _projeter(connaissance=_instant(JOURS))
    assert res["accepte"] is True and res["statut"] == "PROJETEE", res
    assert res["origine"] == "tendance_extrapolee" and res["prevision_de_proprietaire"] is False
    assert [p["valeur"] for p in res["points"]] == [str(n) for n in range(1, JOURS + 1)]
    assert [p["x"] for p in res["points"]] == list(range(JOURS)) and res["duree_historique_jours"] == 7
    assert res["points"][0]["adresse"] == "m2.leads#0:p0.resultat.resultat.total"
    assert res["captures_ecartees"] == []
    droite = next(m for m in res["methodes"] if m["methode"] == "droite")
    assert droite["parametres"] == {"pente_par_jour": "1.000000", "ordonnee_origine": "1.000000"}
    assert droite["ecart_type_residuel"] == "0.00"
    sept, trente = droite["projections"]
    # Jour 7 + 7 = 14 : 1 + 14 = 15 leads, intervalle nul (droite parfaite).
    assert (sept["horizon"], sept["valeur"], sept["borne_basse"], sept["borne_haute"]) == ("7j", "15.00", "15.00",
                                                                                           "15.00")  # fmt: skip
    assert trente["statut"] == "HORIZON_AU_DELA_DE_L_HISTORIQUE" and "valeur" not in trente
    assert len(json.dumps(res, ensure_ascii=False)) <= 5900 and len(res["projection_id"]) == 64
    assert _projeter(connaissance=_instant(JOURS))["projection_id"] == res["projection_id"]


def test_trois_points_connus_seulement_historique_insuffisant(cap):
    res = _projeter(connaissance=_instant(2, minutes=1))
    assert res["accepte"] is True and res["statut"] == "HISTORIQUE_INSUFFISANT" and res["n"] == 3
    assert res["methodes"] == [] and res["manque"].startswith("3 point(s) de plus")


def test_refus_du_vendeur_de_l_agent_et_d_une_lecture_inconnue(cap):
    with pytest.raises(ValueError, match="REJ-IDENTITE-APPAREIL-INVALIDE"):
        _projeter(VENDEUR, connaissance=_instant(JOURS))
    with pytest.raises(ValueError, match="REJ-IDENTITE-APPAREIL-INVALIDE"):
        _projeter(None, connaissance=_instant(JOURS))
    with pytest.raises(ValueError, match="REJ-TENDANCE-LECTURE"):
        _projeter(connaissance=_instant(JOURS), lecture_id="m2.inexistante")
