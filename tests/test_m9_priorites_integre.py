"""M9.11 — m9_prioriser_options par le vrai dispatcher : capacité citée ou déclarée, refus, lecture seule (fictif)."""

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
REF = "2026-10-21T13:00:00Z"


@pytest.fixture
def capacites(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'priorites.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
    yield Capacites(charger_departements(), stockage.transaction, filtre={M9, "m02-revenue-crm"}, memoire=False)
    m2.reinitialiser_registre()
    stockage.liberer()


def _appel(c, nom, arguments, identite_appelante=ADMIN):
    if identite_appelante is None:
        return c.appeler(nom, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return c.appeler(nom, arguments)


def _refuse(reponse):
    return reponse["ok"] is False or reponse["resultat"].get("accepte") is False


def _registres():
    with stockage.transaction() as cnx:
        return sorted(map(str, cnx.execute(select(META.tables["registres_maillons"])).fetchall()))


def piste(id_, impact, urgence, confiance, effort=None, **extra):
    base = {"id": id_, "libelle": f"Piste fictive {id_}", "origine": "DECLAREE_PAR_LA_PERSONNE",
            "impact": impact, "urgence": urgence, "confiance": confiance}  # fmt: skip
    return {**base, **({"effort_jours_personnes": effort} if effort else {}), **extra}


PISTES = [
    piste("relance", 4, 5, 3, "2"),
    piste("campagne", 5, 2, 2, "6", validation="budget_marketing"),
    piste("embauche", 3, 3, 3, "4", validation="embauche"),
]


def test_classement_sans_capacite_ne_propose_aucune_allocation(capacites):
    avant = _registres()
    res = _appel(capacites, "m9_prioriser_options", {"candidats": PISTES, "reference": REF})["resultat"]
    assert res["accepte"] is True and res["allocation"]["statut"] == "CAPACITE_INCONNUE"
    assert [c["id"] for c in res["classement"]] == ["relance", "campagne", "embauche"]  # 25, 23, 18
    assert res["retenus"] == [] and _registres() == avant, "lecture seule : aucun registre écrit"


def test_capacite_declaree_est_nommee_comme_hypothese_et_validation_humaine_conservee(capacites):
    res = _appel(capacites, "m9_prioriser_options", {"candidats": PISTES, "reference": REF, "capacite_declaree": "8"})[
        "resultat"
    ]
    assert res["allocation"]["source_capacite"] == "HYPOTHESE_DECLAREE_PAR_LA_PERSONNE"
    assert res["allocation"]["personnes_affectees"] == [] and res["allocation"]["restante"] == "0"
    assert [r["id"] for r in res["retenus"]] == ["relance", "campagne"]
    assert next(r for r in res["retenus"] if r["id"] == "campagne")["statut"] == "VALIDATION_HUMAINE_REQUISE"
    assert {n["id"]: n["raison"] for n in res["non_retenus"]} == {"embauche": "CAPACITE_INSUFFISANTE"}
    assert len(res["priorisation_id"]) == 64


def test_capacite_citee_depuis_un_fait_du_dossier(capacites):
    # Mécanisme : le fait cité doit exister dans le dossier et être un décimal ; son SENS reste l'affirmation de
    # l'appelant, inscrite telle quelle dans source_capacite (aucun producteur n'expose de capacité d'équipe).
    assert m2.ingerer_lead(
        {"lead_id": "lead-1", "conversation_id": "c-1", "contact": {"nom": "C", "courriel": "c@example.test"},
         "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"},
        "2026-09-01T09:00:00-04:00",
    )["accepte"]  # fmt: skip
    capture = _appel(
        capacites,
        "m9_capturer_producteur",
        {
            "lecture_id": "m2.leads",
            "arguments": {"horodatage": "2026-10-21T12:00:00Z"},
            "horodatage": "2026-10-21T12:00:01Z",
        },
    )["resultat"]
    assert capture["accepte"] is True
    dossier = _appel(
        capacites,
        "m9_apercu_dossier_strategique",
        {"question": "Capacité", "domaines": ["strategie"], "reference": REF},
    )["resultat"]
    faits = dossier["faits"]
    chiffres = {a: t for a, t in faits.items() if t.isdigit()}
    assert chiffres, faits
    adresse = sorted(chiffres)[0]
    res = _appel(
        capacites,
        "m9_prioriser_options",
        {"candidats": [piste("seule", 3, 3, 3, "1")], "reference": REF, "capacite_fait": adresse},
    )["resultat"]
    assert res["accepte"] is True and res["allocation"]["source_capacite"] == adresse
    assert res["allocation"]["capacite"] == chiffres[adresse]
    texte = next((a for a, t in faits.items() if not t.isdigit()), None)
    assert texte is not None
    assert "REJ-PRIORITE-CAPACITE" in json.dumps(
        _appel(capacites, "m9_prioriser_options", {"candidats": PISTES, "reference": REF, "capacite_fait": texte})
    )


@pytest.mark.parametrize(
    "arguments, code",
    [
        ({"capacite_fait": "m9.inexistant#0:p0.x"}, "REJ-PRIORITE-CAPACITE"),
        ({"capacite_fait": "m2.leads#0:p0.x", "capacite_declaree": "3"}, "REJ-PRIORITE-CAPACITE"),
        ({"capacite_declaree": "0"}, "REJ-PRIORITE-INFAISABLE"),
        ({"capacite_declaree": "abc"}, "REJ-PRIORITE-HYPOTHESE"),
        ({"candidats": [{"id": "x"}]}, "REJ-PRIORITE-CANDIDAT"),
        ({"candidats": [piste("a", 9, 1, 1)]}, "REJ-PRIORITE-HYPOTHESE"),
    ],
)
def test_refus_nommes(capacites, arguments, code):
    reponse = _appel(capacites, "m9_prioriser_options", {"candidats": PISTES, "reference": REF, **arguments})
    assert _refuse(reponse) and code in json.dumps(reponse)


def test_seul_l_admin_authentifie_priorise(capacites):
    appel = {"candidats": PISTES, "reference": REF}
    vendeur = IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    assert _refuse(_appel(capacites, "m9_prioriser_options", appel, vendeur))
    assert _refuse(_appel(capacites, "m9_prioriser_options", appel, None)), "voie d'agent refusée"
