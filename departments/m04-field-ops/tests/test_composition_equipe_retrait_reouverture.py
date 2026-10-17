"""R1, composition (hypothèse, pas un bug affirmé) : l'autorité d'équipe COURANTE décide d'un départ neuf, même
quand le membre retiré avait préparé son intention avant le retrait et que le stockage et `Capacites` ont été rouverts.

Vrais `Capacites.appeler` (mode `ombre` du manifeste, idempotence d'appareil), vrai profil (`entreprise.yaml`) modifié
par l'API canonique signée, vraie base SQLite migrée. Contexte DEVICE injecté : aucun jeton Gateway prouvé. Le refus
peut laisser une trace d'audit légitime (approbation `echec`, réclamation d'idempotence, journal du profil) ; seules
les tables d'affaires (registres, événements sortants) servent d'oracle « rien n'a changé ». Fictif : personnes,
équipes, interventions, appareils.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from m4_field_ops import etats
from m4_field_ops import registre as registre_m4
from sqlalchemy import select

from opsys import contexte, idempotence, identite, stockage
from opsys import equipes as equipes_entreprise
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, JOURNAL, MUTATIONS_APPLIQUEES, REGISTRES

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
M4 = "m04-field-ops"
HORO = "2030-01-01T08:00:00+00:00"
HEURE_APPAREIL = "2030-01-02T09:00:00+00:00"
LUC = contexte.IdentiteAppelante(personne="luc.fictif", role="employee")    # A : sera retiré de eq-a
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")  # B : reste membre de eq-a
NADIA = contexte.IdentiteAppelante(personne="nadia.fictif", role="employee")  # témoin : eq-b
PROFIL = {
    "liste": [
        {"id": "eq-a", "membres": ["luc.fictif", "marc.fictif"], "competences": ["gouttieres"],
         "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
         "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}]},
        {"id": "eq-b", "membres": ["nadia.fictif"], "competences": ["gouttieres"],
         "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
         "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}]},
    ],
}


def _cap():
    departements = charger_departements(RACINE_DEPARTEMENTS)
    assert departements[M4].mode == "ombre"
    return Capacites(departements, stockage.transaction, filtre={M4}, memoire=False)


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    with stockage.transaction() as cnx:
        for identifiant, roles in (("admin.fictif", ["admin"]), ("luc.fictif", ["employee"]),
                                   ("marc.fictif", ["employee"]), ("nadia.fictif", ["employee"])):
            identite.creer_personne(cnx, identifiant, identifiant.title(), "mot-de-passe-fictif-1234", roles)
    equipes_entreprise.enregistrer_equipes(PROFIL, par="admin.fictif")
    yield tmp_path
    stockage.liberer()


def _registre():
    return registre_m4.Registre(stockage.maillons(M4, "principal"))


def _lead(lead_id):
    return {"schema_version": 2, "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
            "contact": {"nom": "Client Fictif"}, "service": "gouttieres", "ville": "Repentigny",
            "urgence_declaree": False, "canal": "texte"}


def _planifiees(chantiers):
    """Même préparation que test_acces_par_equipe : interventions `planifiee`, assignées (équipe ou personne)."""
    ids = {}
    with stockage.transaction():
        reg = _registre()
        for nom, technicien in chantiers:
            accuse, verdict = etats.inscrire_depuis_devis(reg, f"DEVIS-R1-{nom}", _lead(f"LEAD-R1-{nom}"), "sel", HORO)
            assert verdict is None, verdict
            iid = accuse["intervention_id"]
            volets = {n: {"statut": "ok", "manque": None, "detail": None}
                      for n in ("soumission", "adresse", "equipe", "materiel", "meteo")}
            pret = {"intervention_id": iid, "statut_intervention": "a_planifier", "statut": "pret", "pret": True,
                    "volets": volets, "a_fournir": []}
            pret["empreinte"] = etats.empreinte_preparation(pret)
            assert etats.transitionner(iid, "planifiee", reg, HORO, preparation=pret)[1] is None
            assert etats.assigner_technicien(iid, technicien, reg, HORO)[1] is None
            ids[nom] = iid
    return ids


def _appeler(cap, nom, arguments, appelante, cle, appareil):
    with contexte.appele_par_appareil(appelante):
        return cap.appeler(nom, arguments, idempotence.Meta(cle=cle, appareil=appareil,
                                                            horodatage_appareil=HEURE_APPAREIL))


def _depart(iid, technicien):
    return {"intervention_id": iid, "technicien_id": technicien, "horodatage": HORO}


def _visibles(cap, appelante):
    with contexte.appele_par_appareil(appelante):
        reponse = cap.appeler("m4_lister_interventions", {})
    assert reponse["ok"] is True, reponse
    return {ligne["intervention_id"] for ligne in reponse["resultat"]}


def _etat(iid):
    with stockage.transaction():
        reg = _registre()
        return etats.statut_courant(reg, iid), etats.technicien_assigne(reg, iid)


def _tables(*tables):
    with stockage.transaction() as cnx:
        return {t.name: [dict(r) for r in cnx.execute(select(t).order_by(*t.primary_key.columns)).mappings()]
                for t in tables}


def _affaires():
    """Tables d'affaires seulement : registres métier et événements publiés."""
    return _tables(REGISTRES, EVENEMENTS_SORTANTS)


def _audit():
    return _tables(APPROBATIONS, MUTATIONS_APPLIQUEES, JOURNAL)


def test_membre_retire_puis_reouverture_ne_part_pas_le_membre_restant_part_et_l_accuse_historique_reste(instance):
    ids = _planifiees((("x", "eq-a"), ("h", "eq-a"), ("w", "eq-b")))
    cap = _cap()  # préchargée AVANT le retrait : aucun état d'équipe ne doit y survivre
    assert {ids["x"], ids["h"]} <= _visibles(cap, LUC) and {ids["x"], ids["h"]} <= _visibles(cap, MARC)

    # Contrôle historique : A part sur H pendant qu'il est encore membre (H devient la sienne).
    accuse_h = _appeler(cap, "m4_demarrer_route", _depart(ids["h"], LUC.personne), LUC, "r1-luc-h", "tel-luc-r1")
    assert accuse_h["ok"] and accuse_h["resultat"]["accepte"] is True and accuse_h["rejoue"] is False, accuse_h
    assert _etat(ids["h"]) == ("en_route", LUC.personne)

    # A prépare son intention neuve sur X (clé et corps fixés), puis le profil le retire de eq-a.
    intention_a = (_depart(ids["x"], LUC.personne), "r1-luc-x-neuve")
    retire = copy.deepcopy(PROFIL)
    retire["liste"][0]["membres"] = ["marc.fictif"]
    equipes_entreprise.enregistrer_equipes(retire, par="admin.fictif")
    assert equipes_entreprise.equipes_de(equipes_entreprise.lire_equipes(), LUC.personne) == ()

    # Réouverture : moteur SQL libéré, Capacites neuve ; la façade préchargée est aussi rejouée.
    moteur_avant = stockage.moteur()
    stockage.liberer()
    cap_neuve = _cap()
    assert stockage.moteur() is not moteur_avant
    with stockage.transaction() as cnx:
        a = identite.personne_active(cnx, LUC.personne)
    assert a is not None and "employee" in a.roles, "A reste une personne active : seul son rattachement change"

    w_avant = _etat(ids["w"])
    for facade, suffixe in ((cap, "prechargee"), (cap_neuve, "neuve")):
        affaires_avant, audit_avant = _affaires(), _audit()
        arguments, cle = intention_a
        refus = _appeler(facade, "m4_demarrer_route", arguments, LUC, f"{cle}-{suffixe}", "tel-luc-r1")
        assert refus["ok"] is True and refus["rejoue"] is False, refus
        assert refus["resultat"]["accepte"] is False
        assert refus["resultat"]["verdict"]["code"] == "REJ-INTERVENTION-NON-ASSIGNEE", refus
        assert _affaires() == affaires_avant, "ni transition, ni assignation, ni WCT, ni événement"
        assert _etat(ids["x"]) == ("planifiee", "eq-a")
        audit_apres = _audit()
        # Audit légitime du refus, décrit : une trace `echec` signée par A et la réclamation de SA clé.
        nouvelles = [t for t in audit_apres["approbations"] if t not in audit_avant["approbations"]]
        assert [(t["outil"], t["statut"], t["decide_par"]) for t in nouvelles] == [
            ("m4_demarrer_route", "echec", LUC.personne)]
        reclamees = [m for m in audit_apres["mutations_appliquees"] if m not in audit_avant["mutations_appliquees"]]
        assert [(m["appareil"], m["cle_idempotence"], m["outil"]) for m in reclamees] == [
            ("tel-luc-r1", f"{cle}-{suffixe}", "m4_demarrer_route")]
        journal = [j for j in audit_apres["journal"] if j not in audit_avant["journal"]]
        assert [(j["action"], j["par"]) for j in journal] == [("approbation.valider_au_depart", LUC.personne)]
    assert ids["x"] not in _visibles(cap_neuve, LUC)
    with contexte.appele_par_appareil(LUC):
        statut_x = cap_neuve.appeler("m4_statut_intervention", {"intervention_id": ids["x"]})
    assert statut_x["ok"] is True and statut_x["resultat"]["statut"] is None, "indiscernable d'une inconnue"

    # L'accusé historique de A (départ committé avant le changement) reste exact, sans nouvel effet.
    affaires_avant, audit_avant = _affaires(), _audit()
    rejeu_h = _appeler(cap_neuve, "m4_demarrer_route", _depart(ids["h"], LUC.personne), LUC, "r1-luc-h", "tel-luc-r1")
    assert rejeu_h == {**accuse_h, "rejoue": True}
    assert _affaires() == affaires_avant and _audit() == audit_avant

    # Positif : B, membre courant, part ; X devient la sienne seule ; le témoin W n'a pas bougé.
    depart_b = _appeler(cap_neuve, "m4_demarrer_route", _depart(ids["x"], MARC.personne), MARC, "r1-marc-x",
                        "tel-marc-r1")
    assert depart_b["ok"] and depart_b["resultat"]["accepte"] is True and depart_b["rejoue"] is False, depart_b
    assert _etat(ids["x"]) == ("en_route", MARC.personne)
    assert ids["x"] in _visibles(cap_neuve, MARC) and ids["x"] not in _visibles(cap_neuve, LUC)
    assert ids["x"] not in _visibles(cap_neuve, NADIA)
    assert _etat(ids["w"]) == w_avant == ("planifiee", "eq-b")
    assert _etat(ids["h"]) == ("en_route", LUC.personne)
