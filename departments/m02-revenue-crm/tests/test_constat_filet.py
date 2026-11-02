"""M2-C1 : la charge du constat planifié `m2.filet_anti_perte_constate` (module pur `constat_filet.py`) et ce qui est
publié par `m2_constater_filet` : des comptes, jamais un lead, un contact ou un vendeur ; `null` pour ce qui n'est pas
évalué ; un identifiant déterministe par instant de constat, une version des données stable. Données fictives."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from m2_revenue_crm import constat_filet, integrite, sla
from sqlalchemy import select
from ventes_aide import ADMIN, MAINTENANT, VENDEUR_UN, contact

import opsys.evenements as evenements_socle
from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
TYPE = "m2.filet_anti_perte_constate"
SLA_TOUS = {
    "heures_premiere_action": 24,
    "heures_lead_chaud": 4,
    "heures_demande_photos": 48,
    "heures_relance_soumission": 24,
    "heures_escalade_plainte": 12,
    "heures_assignation": 24,
    "heures_retard_tolerance": 6,
}


def _rapport(violations=None, etats=None, anomalies=None, non_evalues=(), leads=12):
    violations = violations or {}
    etats = etats or {}
    regles = [
        {
            "regle": r,
            "etat": etats.get(r, "evaluee"),
            "manque": None,
            "violations": None if etats.get(r) == "non_evaluee" else violations.get(r, 0),
        }
        for r in sla.ORDRE_REGLES
    ]
    anomalies = anomalies or {}
    controles = [
        {
            "controle": c,
            "etat": "non_evalue" if c in non_evalues else "evalue",
            "manque": None,
            "anomalies": None if c in non_evalues else anomalies.get(c, 0),
        }
        for c in integrite.CONTROLES
    ]
    return {
        "sla": {"examines": leads, "regles": regles, "violations": []},
        "integrite": {"leads_examines": leads, "controles": controles, "anomalies": []},
    }


def _charge(rapport=None, date="2026-11-02", instant="2026-11-02T12:00:00-05:00"):
    return constat_filet.charge_filet(rapport or _rapport(), date, instant)


# -- le schéma du catalogue
# -------------------------------------------------------------------------------------------------
def _schema():
    return json.loads(
        (Path(evenements_socle.__file__).parent / "catalogue" / f"{TYPE}.json").read_text(encoding="utf-8")
    )


def test_la_charge_respecte_le_schema_ferme_du_catalogue_dans_tous_les_cas():
    schema = _schema()
    cas = [
        _rapport(),
        _rapport({"lead_chaud_non_contacte": 3, "tache_en_retard": 2}, anomalies={"pipeline_incoherent": 1}),
        _rapport(etats={r: "non_evaluee" for r in sla.ORDRE_REGLES}),
        _rapport(
            etats={"photos_non_recues": "non_evaluee", "lead_sans_proprietaire": "partielle"},
            non_evalues=("soumission_orpheline",),
        ),
    ]
    for rapport in cas:
        jsonschema.validate(_charge(rapport), schema)


def test_une_propriete_de_plus_est_refusee_par_le_schema_aucun_lead_ne_peut_traverser():
    charge = _charge()
    schema = _schema()
    for intrus in ({"lead_id": "lead-1"}, {"contact": {"nom": "Jeanne"}}, {"vendeur": "vendeur.un"}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**charge, **intrus}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**charge, "violations_par_regle": {**charge["violations_par_regle"], "regle_x": 1}}, schema
        )


# -- le contenu --------------------------------------------------------------------------------------------------------
def test_les_comptes_par_regle_et_par_controle_sont_ceux_du_rapport():
    charge = _charge(
        _rapport({"lead_chaud_non_contacte": 3, "tache_en_retard": 2}, anomalies={"client_sans_contact": 1})
    )
    assert charge["violations_par_regle"]["lead_chaud_non_contacte"] == 3
    assert charge["violations_total"] == 5 and charge["anomalies_total"] == 1
    assert charge["leads_examines"] == 12 and charge["date_reference"] == "2026-11-02"
    assert charge["regles_non_evaluees"] == [] and charge["controles_non_evalues"] == []


def test_une_regle_non_evaluee_part_en_null_jamais_en_zero_et_n_entre_pas_dans_le_total():
    charge = _charge(_rapport({"lead_chaud_non_contacte": 3}, etats={"photos_non_recues": "non_evaluee"}))
    assert charge["violations_par_regle"]["photos_non_recues"] is None
    assert charge["regles_non_evaluees"] == ["photos_non_recues"] and charge["violations_total"] == 3


def test_aucune_regle_evaluee_le_total_est_null_pas_zero():
    charge = _charge(_rapport(etats={r: "non_evaluee" for r in sla.ORDRE_REGLES}))
    assert charge["violations_total"] is None and charge["regles_non_evaluees"] == list(sla.ORDRE_REGLES)


def test_les_regles_partielles_comptent_leur_partie_sans_delai_dans_le_total():
    charge = _charge(
        _rapport(
            {"lead_sans_proprietaire": 2},
            etats={**{r: "non_evaluee" for r in sla.ORDRE_REGLES}, "lead_sans_proprietaire": "partielle"},
        )
    )
    assert charge["violations_total"] == 2 and charge["regles_partielles"] == ["lead_sans_proprietaire"]


def test_les_regles_partielles_sont_nommees():
    charge = _charge(
        _rapport(etats={"lead_sans_proprietaire": "partielle", "prochaine_action_obligatoire": "partielle"})
    )
    assert charge["regles_partielles"] == ["prochaine_action_obligatoire", "lead_sans_proprietaire"]


def test_un_controle_non_evalue_part_en_null_et_est_nomme_le_total_des_anomalies_reste_un_entier():
    charge = _charge(_rapport(anomalies={"lead_sans_client": 2}, non_evalues=("soumission_orpheline",)))
    assert charge["anomalies_par_controle"]["soumission_orpheline"] is None
    assert charge["controles_non_evalues"] == ["soumission_orpheline"] and charge["anomalies_total"] == 2


# -- identifiant et version
# -------------------------------------------------------------------------------------------------
def test_la_version_des_donnees_ne_depend_que_des_donnees_et_l_identifiant_aussi_de_l_instant():
    a1 = _charge(instant="2026-11-02T12:00:00-05:00")
    a2 = _charge(instant="2026-11-02T18:00:00-05:00")
    b = _charge(_rapport({"tache_en_retard": 1}), instant="2026-11-02T13:00:00-05:00")
    assert a1["version_donnees"] == a2["version_donnees"] != b["version_donnees"]
    assert len({a1["evenement_id"], a2["evenement_id"], b["evenement_id"]}) == 3
    a3 = _charge(instant="2026-11-02T19:00:00-05:00")
    assert a3["version_donnees"] == a1["version_donnees"] and a3["evenement_id"] not in {
        a1["evenement_id"],
        a2["evenement_id"],
    }
    assert _charge(instant="2026-11-02T12:00:00-05:00") == a1, "le même constat redonne la même charge"
    assert a1["evenement_id"].startswith("m2-filet-2026-11-02-") and len(a1["evenement_id"]) < 128


def test_la_date_de_reference_entre_dans_l_identifiant_pas_dans_la_version():
    veille, jour = _charge(date="2026-11-01"), _charge(date="2026-11-02")
    assert veille["version_donnees"] == jour["version_donnees"] and veille["evenement_id"] != jour["evenement_id"]


# -- ce que l'outil publie
# ---------------------------------------------------------------------------------------------------
def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)
            .order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).all()
    return [(i, codec.decoder(c)) for i, c in lignes]


def _constater(monde, qui=None, horodatage=MAINTENANT):
    return monde.appeler("m2_constater_filet", {"horodatage": horodatage}, qui)


def test_l_outil_publie_les_comptes_valides_par_le_schema_sans_aucun_lead(monde):
    monde.configurer(sla=SLA_TOUS)
    monde.lead("lead-un", None, contact("Cliente Secrete", 1), ingere="2026-10-01T09:00:00-04:00", urgence=True)
    retour = monde.accepte(_constater(monde))
    ((identifiant, charge),) = _publies()
    assert identifiant == retour["evenement_id"] == charge["evenement_id"]
    jsonschema.validate(charge, _schema())
    assert charge["violations_par_regle"]["lead_chaud_non_contacte"] == 1
    assert charge["violations_par_regle"]["lead_sans_proprietaire"] == 1 and charge["leads_examines"] == 1
    texte = json.dumps(charge, ensure_ascii=False)
    for fuite in ("lead-un", "Secrete", "example.test", "418-555", "vendeur", "client-"):
        assert fuite not in texte
    assert set(retour) == {
        "publie",
        "evenement_id",
        "date_reference",
        "version_donnees",
        "leads_examines",
        "violations_total",
        "anomalies_total",
        "regles_non_evaluees",
    }


def test_sans_aucun_delai_declare_le_constat_publie_des_null_pas_des_zeros(monde):
    monde.configurer()
    monde.lead("lead-un", None, contact("Cliente A", 1), ingere="2020-01-01T09:00:00-05:00", urgence=True)
    monde.accepte(_constater(monde))
    ((_, charge),) = _publies()
    assert charge["violations_total"] == 0 and len(charge["regles_non_evaluees"]) == 5
    assert charge["regles_partielles"] == ["prochaine_action_obligatoire", "lead_sans_proprietaire"]
    assert charge["violations_par_regle"]["lead_chaud_non_contacte"] is None
    assert charge["violations_par_regle"]["lead_sans_proprietaire"] == 0, "partie sans délai : aucun lead avancé fautif"


def test_rejouer_le_meme_constat_ne_publie_rien_un_autre_instant_est_un_evenement_de_plus(monde):
    monde.configurer(sla=SLA_TOUS)
    monde.lead("lead-un", "vendeur.un", contact("Cliente A", 1))
    premier = monde.accepte(_constater(monde))
    assert monde.accepte(_constater(monde))["evenement_id"] == premier["evenement_id"] and len(_publies()) == 1
    plus_tard = monde.accepte(_constater(monde, horodatage="2026-10-15T18:00:00-04:00"))
    assert plus_tard["version_donnees"] == premier["version_donnees"]
    assert plus_tard["evenement_id"] != premier["evenement_id"] and len(_publies()) == 2


def test_une_donnee_changee_est_une_version_de_plus_et_un_retour_arriere_reste_distinct(monde):
    monde.configurer(sla=SLA_TOUS)
    monde.lead("lead-un", "vendeur.un", contact("Cliente A", 1))
    a1 = monde.accepte(_constater(monde, horodatage="2026-10-15T10:00:00-04:00"))
    monde.lead("lead-deux", None, contact("Client B", 2), ingere="2026-09-01T09:00:00-04:00")
    b = monde.accepte(_constater(monde, horodatage="2026-10-15T11:00:00-04:00"))
    assert b["version_donnees"] != a1["version_donnees"]
    # un lead de plus, jamais retiré : la version ne redevient pas A ; mais le même état reconstaté plus tard reste
    # distinct
    b2 = monde.accepte(_constater(monde, horodatage="2026-10-15T12:00:00-04:00"))
    assert b2["version_donnees"] == b["version_donnees"] and b2["evenement_id"] != b["evenement_id"]
    assert len(_publies()) == 3


def test_un_vendeur_ou_un_horodatage_illisible_ne_publie_rien(monde):
    assert monde.code(_constater(monde, VENDEUR_UN)) == "REJ-FILET-PERIMETRE-GLOBAL"
    assert monde.code(_constater(monde, horodatage="hier")) == "REJ-HORODATAGE-INVALIDE"
    assert _publies() == []


def test_l_administrateur_peut_constater_comme_l_agent(monde):
    monde.accepte(_constater(monde, ADMIN))
    assert len(_publies()) == 1
