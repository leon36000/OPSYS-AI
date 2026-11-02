"""Le carnet de preuve du filet anti-perte : douze leads FICTIFS aux défauts variés, semés par les VRAIS outils de M2
(et,
pour les données abîmées, par le registre chaîné lui-même), à partir d'un instant de référence fixe.

Partagé par `test_filet_scenario.py` (départements) et par `tests/test_filet_anti_perte_planifie.py` (planificateur,
bus, M8).
Les délais du propriétaire sont ceux de FICTIF_SLA : des valeurs de preuve, jamais des recommandations.

  L01 sain (récent)              L07 soumission périmée non relancée
  L02 sain (photos liées)        L08 plainte non escaladée (et action échue)
  L03 sain (converti)            L09 tâche en retard
  L04 sain (chaud, contacté)     L10 tâche échue mais faite (sain)
  L05 nouveau, ni propriétaire   L11 donnée abîmée (qualifié sans propriétaire ni action)
      ni prochaine action        L12 client injoignable (sain côté SLA)
  L06 chaud jamais contacté      L13 fantôme : une note et un devis sans lead
"""

from __future__ import annotations

import datetime as dt

from m2_revenue_crm import outils
from m2_revenue_crm.registre import Registre
from ventes_aide import ADMIN, VENDEUR_DEUX, VENDEUR_UN, contact

from opsys import stockage

FICTIF = True
EST = dt.timezone(dt.timedelta(hours=-5))
MAINT_UTC = dt.datetime(2026, 11, 2, 17, 0, tzinfo=dt.UTC)
MAINT = MAINT_UTC.astimezone(EST).isoformat()  # 2026-11-02T12:00:00-05:00
FICTIF_SLA = {
    "heures_premiere_action": 24,
    "heures_lead_chaud": 4,
    "heures_demande_photos": 48,
    "heures_relance_soumission": 24,
    "heures_escalade_plainte": 12,
    "heures_assignation": 24,
    "heures_retard_tolerance": 6,
}
SEGMENTS = {"jours_inactivite_dormant": 30, "jours_soumission_perimee": 14}
RELANCES = {"jours_entre_relances": 7}

# Ce que le moteur doit sortir, exactement (règle, lead), dans l'ordre : par règle, puis par début de violation.
VIOLATIONS_ATTENDUES = [
    ("prochaine_action_obligatoire", "L11"),
    ("prochaine_action_obligatoire", "L05"),
    ("lead_chaud_non_contacte", "L06"),
    ("photos_non_recues", "L11"),
    ("soumission_non_relancee", "L07"),
    ("plainte_non_escaladee", "L08"),
    ("lead_sans_proprietaire", "L11"),
    ("lead_sans_proprietaire", "L05"),
    ("tache_en_retard", "L08"),
    ("tache_en_retard", "L09"),
]
SAINS = ("L01", "L02", "L03", "L04", "L10", "L12")
ANOMALIES_ATTENDUES = [
    ("client_sans_contact", None),  # le client de L12 (identifiant dérivé du contact)
    ("soumission_orpheline", None),
    ("activite_sans_lead", "L13"),
    ("pipeline_incoherent", "L11"),
    ("pipeline_incoherent", "L11"),
]


def il_y_a(heures: float) -> str:
    return (MAINT_UTC - dt.timedelta(hours=heures)).astimezone(EST).isoformat()


def _action(echeance_dans_h: float) -> dict:
    return {"description": "Appeler le client", "echeance": il_y_a(-echeance_dans_h)}


def _ingerer(lead_id, n, ingere_h, *, urgence=False, ville=None, contact_=None) -> None:
    contrat = {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": contact_ if contact_ is not None else contact(f"Client {lead_id}", n),
        "type_travaux": "renovation_totale",
        "ville": ville or f"Ville-{lead_id}",
        "urgence_declaree": urgence,
        "canal": "telephone",
    }
    assert outils.ingerer_lead(contrat, il_y_a(ingere_h))["accepte"] is True


def _qualifier(lead_id, owner, qualifie_h, echeance_dans_h) -> None:
    reponse = outils.transitionner_statut(
        lead_id, "qualifie", il_y_a(qualifie_h), owner=owner, prochaine_action=_action(echeance_dans_h)
    )
    assert reponse["accepte"] is True, reponse


def _note(lead_id, il_y_a_h, auteur="vendeur.un") -> None:
    assert outils.enregistrer_interaction(lead_id, auteur, "Appel fait au client.", il_y_a(il_y_a_h))["accepte"] is True


def _photos(monde, lead_id, qui) -> None:
    """Une photo liée au profil de propriété CONFIRMÉ du client (proposition puis confirmation par la personne)."""
    adresse = {"ligne": f"{lead_id} rue des Lilas", "ville": "Québec", "code_postal": "g1a 1a1"}
    source = {"type": "constate_vendeur", "reference": f"visite-{lead_id}"}
    propose = monde.accepte(
        monde.appeler(
            "m2_proposer_profil_propriete",
            {
                "lead_id": lead_id,
                "revision_attendue": 0,
                "champs": {"adresse": adresse, "photos_liees": ["fichier-001"]},
                "source": source,
                "horodatage": il_y_a(300),
            },
            qui,
        )
    )
    monde.accepte(
        monde.appeler(
            "m2_confirmer_profil_propriete",
            {
                "lead_id": lead_id,
                "propriete_id": propose["propriete_id"],
                "revision_attendue": propose["revision"],
                "decision": "confirmer",
                "horodatage": il_y_a(300),
            },
            qui,
        )
    )


def _devis_envoye(devis_id, lead_id, envoi_h) -> None:
    with stockage.transaction():
        assert (
            outils._recevoir_devis_envoye(
                {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": il_y_a(envoi_h)}
            )["traite"]
            is True
        )


def _terminer(lead_id, wct_id, satisfait, termine_h) -> None:
    with stockage.transaction():
        assert (
            outils._recevoir_travaux_termines(
                {
                    "wct_id": wct_id,
                    "lead_id": lead_id,
                    "horodatage_completion": il_y_a(termine_h),
                    "devis_id": f"devis-{lead_id}",
                    "client_satisfait": satisfait,
                }
            )["traite"]
            is True
        )


def semer(monde) -> None:
    """Le carnet de douze leads (plus un fantôme) dans la base du `monde` ; les délais du propriétaire sont déclarés."""
    monde.configurer(sla=FICTIF_SLA)
    # -- sains --------------------------------------------------------------------------------------------------
    _ingerer("L01", 1, 30)
    _qualifier("L01", "vendeur.un", 20, 48)
    _note("L01", 10)
    _ingerer("L02", 2, 320)
    _qualifier("L02", "vendeur.un", 300, 72)
    _photos(monde, "L02", VENDEUR_UN)
    _note("L02", 5)
    _ingerer("L03", 3, 260)
    _qualifier("L03", "vendeur.deux", 250, 24)
    assert (
        outils.transitionner_statut(
            "L03", "converti", il_y_a(10), reference_devis_m3="devis-L03", prochaine_action=_action(24)
        )["accepte"]
        is True
    )
    _note("L03", 12, "vendeur.deux")
    _ingerer("L04", 4, 8, urgence=True, ville="Lévis")  # même ville et mêmes travaux que L06 : doublon signalé
    _note("L04", 6)
    # -- défauts SLA ---------------------------------------------------------------------------------------------
    _ingerer("L05", 5, 72)
    _ingerer("L06", 6, 10, urgence=True, ville="Lévis")
    _ingerer("L07", 7, 620)
    _qualifier("L07", "vendeur.un", 600, -580)
    _photos(monde, "L07", VENDEUR_UN)
    _note("L07", 192)
    _devis_envoye("devis-L07", "L07", 480)
    _ingerer("L08", 8, 500)
    _qualifier("L08", "vendeur.deux", 480, 24)
    for statut, h in (("converti", 450), ("cedule", 440), ("chantier", 430)):
        extra = {"reference_devis_m3": "devis-L08"} if statut == "converti" else {}
        assert outils.transitionner_statut("L08", statut, il_y_a(h), **extra)["accepte"] is True
    _terminer("L08", "wct-L08", False, 30)
    _ingerer("L09", 9, 120)
    _qualifier("L09", "vendeur.un", 100, -30)
    _photos(monde, "L09", VENDEUR_UN)
    _note("L09", 90)
    _ingerer("L10", 10, 120)
    _qualifier("L10", "vendeur.un", 100, -30)
    _photos(monde, "L10", VENDEUR_UN)
    _note("L10", 5)
    # -- données abîmées --------------------------------------------------------------------------------------------
    _ingerer("L11", 11, 200)
    with stockage.transaction():
        Registre(maillons=stockage.maillons("m02-revenue-crm", "principal")).ajouter(
            {
                "type_entree": "transition_statut",
                "horodatage": il_y_a(190),
                "lead_id": "L11",
                "statut": "qualifie",
                "statut_precedent": "nouveau",
            }
        )
    _ingerer("L12", 12, 15, contact_={"nom": "Client Injoignable"})
    _qualifier("L12", "vendeur.deux", 12, 48)
    _note("L12", 3, "vendeur.deux")
    with stockage.transaction():
        Registre(maillons=stockage.maillons("m02-revenue-crm", "principal")).ajouter(
            {
                "type_entree": "interaction",
                "horodatage": il_y_a(50),
                "lead_id": "L13",
                "auteur": "vendeur.un",
                "resume": "Note d'un lead jamais ingéré.",
            }
        )
        stockage.maillons("m02-revenue-crm", "devis_envoyes_recus").append(
            {"devis_id": "devis-L13", "lead_id": "L13", "chantier_id": None, "horodatage_envoi": il_y_a(60)}
        )


ADMIN_ET_AUTRES = (ADMIN, VENDEUR_UN, VENDEUR_DEUX)
