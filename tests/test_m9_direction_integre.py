"""M9.5–7 — salle de guerre et revues périodiques par les vrais outils, producteurs M2/M6 réels (fictif)."""

from __future__ import annotations

import json

import pytest
from m2_revenue_crm import outils as m2
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.stockage.schema import META

FICTIF = True
M9 = "m09-strategic-intelligence"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
TOR = "America/Toronto"


@pytest.fixture
def capacites(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'direction.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
    yield Capacites(
        charger_departements(),
        stockage.transaction,
        filtre={M9, "m02-revenue-crm", "m06-material-control"},
        memoire=False,
    )
    m2.reinitialiser_registre()
    stockage.liberer()


def _appel(c, nom, arguments, identite_appelante=ADMIN):
    if identite_appelante is None:
        return c.appeler(nom, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return c.appeler(nom, arguments)


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _refuse(reponse):
    return reponse["ok"] is False or reponse["resultat"].get("accepte") is False


def _capturer(c, lecture, arguments, recu_a):
    return _ok(
        _appel(c, "m9_capturer_producteur", {"lecture_id": lecture, "arguments": arguments, "horodatage": recu_a})
    )


def _lire_tout(c, outil, arguments):
    morceaux, depart = [], 0
    while depart is not None:
        page = _ok(_appel(c, outil, {**arguments, "depart": depart}))
        morceaux.append(page["contenu_json"])
        depart = page["prochain_depart"]
    return json.loads("".join(morceaux))


def _etat_registres():
    with stockage.transaction() as cnx:
        return sorted(map(str, cnx.execute(select(META.tables["registres_maillons"])).fetchall()))


def _lead():
    assert (
        m2.ingerer_lead(
            {
                "lead_id": "lead-1",
                "conversation_id": "c-1",
                "contact": {"nom": "C", "courriel": "c@example.test"},
                "type_travaux": "renovation_totale",
                "ville": "Québec",
                "urgence_declaree": False,
                "canal": "telephone",
            },
            "2026-09-01T09:00:00-04:00",
        )["accepte"]
        is True
    )


def test_salle_de_guerre_montre_couverture_manques_et_refuse_une_vue_perimee(capacites):
    _lead()
    _capturer(capacites, "m2.leads", {"horodatage": "2026-10-21T12:00:00Z"}, "2026-10-21T12:00:01Z")
    salle = _ok(_appel(capacites, "m9_salle_de_guerre", {"reference": "2026-10-21T13:00:00Z"}))
    assert salle["type"] == "SALLE_DE_GUERRE" and salle["couverture"]["complete"] is False
    statuts = {m["lecture_id"]: m["statut"] for m in salle["manques"]}
    assert statuts["m6.disponibilite"] == "ABSENTE" and "m2.leads" not in statuts
    assert salle["decisions_en_attente"]["total"] == 0 and salle["conseils_en_cours_total"] == 0
    assert "aucun effet" in salle["responsabilites"]
    meme = _ok(
        _appel(capacites, "m9_salle_de_guerre", {"reference": "2026-10-21T13:00:00Z", "vue_attendue": salle["vue"]})
    )
    assert meme["vue"] == salle["vue"]
    _capturer(capacites, "m6.disponibilite", {}, "2026-10-21T13:30:00Z")
    refus = _appel(capacites, "m9_salle_de_guerre", {"reference": "2026-10-21T14:00:00Z", "vue_attendue": salle["vue"]})
    assert _refuse(refus) and "REJ-VUE-PERIMEE" in json.dumps(refus)


def test_acces_agent_vendeur_et_role_retire_refuses(capacites):
    for identite_appelante in (None, IdentiteAppelante("vendeur.fictif", "seller", source="console")):
        for nom, args in (
            ("m9_salle_de_guerre", {"reference": "2026-10-21T13:00:00Z"}),
            (
                "m9_apercu_revue",
                {
                    "granularite": "mensuelle",
                    "ancre": "2026-09-10",
                    "fuseau": TOR,
                    "connaissance": "2026-10-02T00:00:00Z",
                },
            ),
            ("m9_lister_revues", {}),
            ("m9_lire_revue", {"index": 0}),
            (
                "m9_publier_revue",
                {
                    "granularite": "mensuelle",
                    "ancre": "2026-09-10",
                    "fuseau": TOR,
                    "horodatage": "2026-10-02T00:00:00Z",
                },
            ),
        ):
            avant = _etat_registres()
            assert _refuse(_appel(capacites, nom, args, identite_appelante)), nom
            assert _etat_registres() == avant
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    assert _refuse(_appel(capacites, "m9_lister_revues", {}))


def test_revue_hebdomadaire_publiee_rejouee_puis_nouvelle_version_apres_arrivee_tardive(capacites):
    _lead()
    _capturer(
        capacites, "m2.leads", {"horodatage": "2026-10-20T15:00:00Z"}, "2026-10-20T15:00:01Z"
    )  # mardi 11 h locale
    periode = {"granularite": "hebdomadaire", "ancre": "2026-10-21", "fuseau": TOR}
    avant_la_fin = _appel(capacites, "m9_publier_revue", periode | {"horodatage": "2026-10-22T00:00:00Z"})
    assert _refuse(avant_la_fin) and "REJ-REVUE-PRECOCE" in json.dumps(avant_la_fin)
    v1 = _ok(_appel(capacites, "m9_publier_revue", periode | {"horodatage": "2026-10-27T10:00:00Z"}))
    assert (v1["version"], v1["rejoue"], v1["synthese"]["captures_recues"]) == (1, False, 1)
    rejeu = _ok(_appel(capacites, "m9_publier_revue", periode | {"horodatage": "2026-10-27T11:00:00Z"}))
    assert rejeu["rejoue"] is True and rejeu["revue_id"] == v1["revue_id"]
    # Une capture reçue après la fin sans étendue métier déclarée ne concerne pas la période : la revue reste la même
    # version.
    _capturer(capacites, "m6.disponibilite", {}, "2026-10-28T09:00:00Z")
    toujours = _ok(_appel(capacites, "m9_publier_revue", periode | {"horodatage": "2026-10-29T00:00:00Z"}))
    assert toujours["rejoue"] is True and toujours["revue_id"] == v1["revue_id"]
    suivante = _ok(
        _appel(
            capacites,
            "m9_publier_revue",
            {"granularite": "hebdomadaire", "ancre": "2026-10-28", "fuseau": TOR, "horodatage": "2026-11-03T10:00:00Z"},
        )
    )
    assert suivante["version"] == 1 and suivante["synthese"]["captures_recues"] == 1
    liste = _ok(_appel(capacites, "m9_lister_revues", {}))
    assert liste["total"] == 2 and [r["version"] for r in liste["revues"]] == [1, 1]
    reprise = _appel(capacites, "m9_lister_revues", {"vue": "0" * 64})
    assert _refuse(reprise) and "REJ-VUE-PERIMEE" in json.dumps(reprise)
    complet = _lire_tout(capacites, "m9_lire_revue", {"index": 0})
    assert complet["revue_id"] == v1["revue_id"] and complet["periode"]["debut_local"] == "2026-10-19"


def test_revue_mensuelle_et_trimestrielle_deux_fuseaux_et_apercu_en_tranches(capacites):
    _lead()
    _capturer(
        capacites, "m2.leads", {"horodatage": "2026-10-01T02:00:00Z"}, "2026-10-01T02:00:01Z"
    )  # 30 sept 22 h à Toronto
    mensuelle_tor = _ok(
        _appel(
            capacites,
            "m9_publier_revue",
            {"granularite": "mensuelle", "ancre": "2026-10-15", "fuseau": TOR, "horodatage": "2026-11-02T00:00:00Z"},
        )
    )
    mensuelle_utc = _ok(
        _appel(
            capacites,
            "m9_publier_revue",
            {"granularite": "mensuelle", "ancre": "2026-10-15", "fuseau": "UTC", "horodatage": "2026-11-02T00:00:00Z"},
        )
    )
    assert mensuelle_tor["synthese"]["captures_recues"] == 0 and mensuelle_utc["synthese"]["captures_recues"] == 1
    trimestre = _ok(
        _appel(
            capacites,
            "m9_publier_revue",
            {
                "granularite": "trimestrielle",
                "ancre": "2026-10-15",
                "fuseau": TOR,
                "horodatage": "2027-01-05T00:00:00Z",
            },
        )
    )
    assert trimestre["periode"]["debut_local"] == "2026-10-01" and trimestre["periode"]["fin_local"] == "2027-01-01"
    apercu = _lire_tout(
        capacites,
        "m9_apercu_revue",
        {"granularite": "mensuelle", "ancre": "2026-10-15", "fuseau": "UTC", "connaissance": "2026-11-02T00:00:00Z"},
    )
    assert apercu["revue_id"] == mensuelle_utc["revue_id"]
    assert _refuse(
        _appel(
            capacites,
            "m9_apercu_revue",
            {
                "granularite": "mensuelle",
                "ancre": "2026-10-15",
                "fuseau": "Mars/X",
                "connaissance": "2026-11-02T00:00:00Z",
            },
        )
    )


def test_registre_des_publications_altere_est_refuse(capacites):
    _lead()
    _capturer(capacites, "m2.leads", {"horodatage": "2026-10-20T15:00:00Z"}, "2026-10-20T15:00:01Z")
    _ok(
        _appel(
            capacites,
            "m9_publier_revue",
            {"granularite": "hebdomadaire", "ancre": "2026-10-21", "fuseau": TOR, "horodatage": "2026-10-27T10:00:00Z"},
        )
    )
    registres = META.tables["registres_maillons"]
    with stockage.transaction() as cnx:
        cnx.execute(registres.update().where(registres.c.registre == "publications_revue").values(maillon="{}"))
    assert _refuse(_appel(capacites, "m9_lister_revues", {}))
    assert _refuse(_appel(capacites, "m9_lire_revue", {"index": 0}))
