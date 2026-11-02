"""M2-C5 (quick wins) : trois segments débloqués par des données DÉJÀ reçues, et une relance préparée jamais notée qui
ne
retarde plus la suivante.

Vrais outils, vraie base SQLite migrée, vrais consommateurs (`_recevoir_travaux_termines`, `_recevoir_devis_envoye`).
Ce que ces tests décrivent, avant le correctif :
- `client_satisfait` (reçu de M4 dans `m4.travaux_termines`) servait à écrire un texte puis était jeté :
`complaint_risk`
  et `referral_candidate` restaient « non calculables » ;
- `quote_sent` restait « non calculable » alors que M2 consomme `m3.devis_envoye` ;
- « la dernière relance » était la dernière relance PRÉPARÉE : une relance préparée que personne n'a notée au dossier
  (donc jamais faite, aussi loin que M2 le sache) retardait de `jours_entre_relances` jours la relance suivante du
  même client.
Données fictives (`fictif: true`).
"""

from __future__ import annotations

import pytest
from m2_revenue_crm import outils
from ventes_aide import ADMIN, VENDEUR_UN, contact

from opsys import stockage

FICTIF = True
MAINTENANT = "2026-10-15T12:00:00-04:00"
ENVOI = "2026-09-10T09:00:00-04:00"  # le seuil de 14 jours est atteint le 24 septembre


def _amener_au_chantier(monde, lead_id, contact_, owner="vendeur.un"):
    monde.lead(lead_id, owner, contact_)
    for statut, h in (
        ("converti", "2026-09-02T09:00:00-04:00"),
        ("cedule", "2026-09-02T10:00:00-04:00"),
        ("chantier", "2026-09-02T11:00:00-04:00"),
    ):
        extra = {"reference_devis_m3": f"devis-{lead_id}"} if statut == "converti" else {}
        assert outils.transitionner_statut(lead_id, statut, h, **extra)["accepte"] is True


def _terminer(lead_id, wct_id, satisfait, instant="2026-09-20T14:00:00-04:00"):
    charge = {"wct_id": wct_id, "lead_id": lead_id, "horodatage_completion": instant, "devis_id": f"devis-{lead_id}"}
    if satisfait is not None:
        charge["client_satisfait"] = satisfait
    with stockage.transaction():
        return outils._recevoir_travaux_termines(charge)


def _envoyer_devis(devis_id, lead_id, instant=ENVOI):
    with stockage.transaction():
        resultat = outils._recevoir_devis_envoye(
            {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": instant}
        )
    assert resultat["traite"] is True


def _segment(monde, segment, *, qui=ADMIN):
    page = monde.accepte(monde.appeler("m2_lister_leads", {"horodatage": MAINTENANT, "segment": segment}, qui))
    return sorted(item["lead_id"] for item in page["leads"])


# -- la satisfaction du client est gardée -------------------------------------------------------------------------
def test_la_satisfaction_recue_de_m4_est_gardee_et_debloque_deux_segments(monde):
    _amener_au_chantier(monde, "sat-oui", contact("Cliente Contente", 1))
    _amener_au_chantier(monde, "sat-non", contact("Client Mecontent", 2))
    _amener_au_chantier(monde, "sat-nsp", contact("Client Muet", 3))
    for lead_id, satisfait in (("sat-oui", True), ("sat-non", False), ("sat-nsp", None)):
        assert _terminer(lead_id, f"wct-{lead_id}", satisfait)["traite"] is True
    assert _segment(monde, "referral_candidate") == ["sat-oui"]
    assert _segment(monde, "complaint_risk") == ["sat-non"]
    # un fait absent n'est jamais deviné : le lead muet n'est ni candidat ni à risque
    gardes = monde.registre("satisfactions_recues")
    assert sorted((m["lead_id"], m["client_satisfait"]) for m in gardes) == [("sat-non", False), ("sat-oui", True)]


def test_ce_qui_est_garde_ne_porte_aucun_contact_et_un_rejeu_n_ajoute_rien(monde):
    _amener_au_chantier(monde, "sat-fuite", contact("Cliente Secrete", 4))
    _terminer("sat-fuite", "wct-fuite", False)
    assert _terminer("sat-fuite", "wct-fuite", False)["deja_applique"] is True
    gardes = monde.registre("satisfactions_recues")
    assert len(gardes) == 1
    texte = str(gardes)
    for fuite in ("Secrete", "example.test", "418-555"):
        assert fuite not in texte


def test_un_vendeur_ne_voit_la_satisfaction_que_de_ses_leads(monde):
    _amener_au_chantier(monde, "sat-mien", contact("Cliente M", 5), owner="vendeur.un")
    _amener_au_chantier(monde, "sat-autre", contact("Client A", 6), owner="vendeur.deux")
    _terminer("sat-mien", "wct-mien", False)
    _terminer("sat-autre", "wct-autre", False)
    assert _segment(monde, "complaint_risk", qui=VENDEUR_UN) == ["sat-mien"]
    assert _segment(monde, "complaint_risk") == ["sat-autre", "sat-mien"]


# -- quote_sent ---------------------------------------------------------------------------------------------------
def test_un_devis_envoye_rend_le_segment_quote_sent_calculable_et_cite_le_devis(monde):
    monde.lead("devis-oui", "vendeur.un", contact("Cliente D", 8))
    monde.lead("devis-non", "vendeur.un", contact("Client N", 9))
    _envoyer_devis("devis-1", "devis-oui")
    assert _segment(monde, "quote_sent") == ["devis-oui"]
    page = monde.accepte(monde.appeler("m2_lister_leads", {"horodatage": MAINTENANT, "segment": "quote_sent"}, ADMIN))
    donnee = page["leads"][0]["segments"][0]
    assert donnee["segment"] == "quote_sent" and donnee["donnee"]["devis_id"] == "devis-1"
    assert "quote_sent" not in {n["segment"] for n in page["segments_non_calculables"]}


# -- la relance préparée mais jamais notée ne retarde pas la suivante ----------------------------------------------
def _deux_leads_du_meme_client(monde):
    partage = contact("Cliente Partagee", 20)
    monde.lead("rel-devis", "vendeur.un", partage, ingere="2026-09-01T09:00:00-04:00")
    monde.lead(
        "rel-dormant", "vendeur.un", partage, ingere="2026-08-01T09:00:00-04:00", qualifie="2026-08-01T10:00:00-04:00"
    )
    _envoyer_devis("devis-rel", "rel-devis")
    # une note humaine récente sur le lead du devis : seul `rel-dormant` est dormant
    monde.interaction("rel-devis", "Devis envoyé, en attente de réponse.", "2026-09-12T09:00:00-04:00")


def _preparer(monde, lead_id, regle, instant=MAINTENANT, canal="appel"):
    return monde.appeler(
        "m2_preparer_relance", {"lead_id": lead_id, "regle": regle, "canal": canal, "horodatage": instant}, VENDEUR_UN
    )


def test_une_relance_preparee_jamais_notee_ne_retarde_pas_la_relance_suivante_du_client(monde):
    _deux_leads_du_meme_client(monde)
    premiere = monde.accepte(_preparer(monde, "rel-devis", "relance_devis_sans_reponse"))
    assert premiere["envoye"] is False
    # le lendemain, personne n'a noté la relance au dossier : elle n'a pas (à la connaissance de M2) été faite
    lendemain = "2026-10-16T12:00:00-04:00"
    suite = monde.appeler(
        "m2_preparer_relance",
        {"lead_id": "rel-dormant", "regle": "relance_lead_dormant", "canal": "appel", "horodatage": lendemain},
        VENDEUR_UN,
    )
    assert monde.accepte(suite)["regle"] == "relance_lead_dormant"


def test_une_relance_deja_preparee_et_non_notee_n_est_pas_preparee_deux_fois(monde):
    _deux_leads_du_meme_client(monde)
    monde.accepte(_preparer(monde, "rel-devis", "relance_devis_sans_reponse"))
    doublon = _preparer(monde, "rel-devis", "relance_devis_sans_reponse", instant="2026-10-16T12:00:00-04:00")
    assert monde.code(doublon) == "REJ-RELANCE-DEJA-PREPAREE"
    assert len(monde.registre("relances_preparees")) == 1


def test_une_relance_notee_au_dossier_date_la_frequence_a_l_instant_de_la_note(monde):
    _deux_leads_du_meme_client(monde)
    monde.accepte(_preparer(monde, "rel-devis", "relance_devis_sans_reponse"))
    monde.interaction("rel-devis", "Appelé le client, message laissé.", "2026-10-16T09:00:00-04:00")
    trop_tot = monde.appeler(
        "m2_preparer_relance",
        {
            "lead_id": "rel-dormant",
            "regle": "relance_lead_dormant",
            "canal": "appel",
            "horodatage": "2026-10-22T12:00:00-04:00",
        },
        VENDEUR_UN,
    )
    verdict = monde.verdict(trop_tot)
    assert verdict["code"] == "REJ-RELANCE-TROP-PROCHE"
    assert "2026-10-23T13:00:00+00:00" in verdict["detail"], (
        "sept jours après la note (16 oct. 09:00 -04:00), pas la préparation"
    )
    permis = monde.appeler(
        "m2_preparer_relance",
        {
            "lead_id": "rel-dormant",
            "regle": "relance_lead_dormant",
            "canal": "appel",
            "horodatage": "2026-10-23T09:00:00-04:00",
        },
        VENDEUR_UN,
    )
    assert monde.accepte(permis)["regle"] == "relance_lead_dormant"


def test_une_note_anterieure_a_la_preparation_ou_du_systeme_ne_confirme_rien(monde):
    _deux_leads_du_meme_client(monde)
    monde.accepte(_preparer(monde, "rel-devis", "relance_devis_sans_reponse"))
    monde.interaction("rel-devis", "Note du système.", "2026-10-16T09:00:00-04:00", auteur="system:m3")
    monde.interaction("rel-devis", "Ancienne note.", "2026-10-15T09:00:00-04:00")
    liste = monde.accepte(monde.appeler("m2_lister_relances", {"horodatage": "2026-10-16T12:00:00-04:00"}, ADMIN))
    devis = next(r for r in liste["relances"] if r["regle"] == "relance_devis_sans_reponse")
    assert devis["derniere_relance"] is None and devis["preparee_en_attente"]["canal"] == "appel"


@pytest.mark.parametrize("canal", ["appel"])
def test_la_liste_dit_qu_une_relance_est_preparee_en_attente_d_etre_notee(monde, canal):
    _deux_leads_du_meme_client(monde)
    monde.accepte(_preparer(monde, "rel-devis", "relance_devis_sans_reponse", canal=canal))
    liste = monde.accepte(monde.appeler("m2_lister_relances", {"horodatage": MAINTENANT}, ADMIN))
    devis = next(r for r in liste["relances"] if r["regle"] == "relance_devis_sans_reponse")
    assert devis["preparee_en_attente"] == {"le": MAINTENANT, "canal": canal, "canaux": [canal]}
    assert devis["permise_maintenant"] is True


def test_sans_aucune_note_la_frequence_d_une_relance_notee_reste_celle_de_la_personne(monde):
    # non-régression : la relance NOTÉE bloque toujours une relance du même client, et d'aucun autre
    _deux_leads_du_meme_client(monde)
    monde.lead(
        "autre-client",
        "vendeur.un",
        contact("Autre Client", 21),
        ingere="2026-08-01T09:00:00-04:00",
        qualifie="2026-08-01T10:00:00-04:00",
    )
    monde.accepte(_preparer(monde, "rel-devis", "relance_devis_sans_reponse"))
    monde.interaction("rel-devis", "Appelé.", "2026-10-15T13:00:00-04:00")
    memes = monde.appeler(
        "m2_preparer_relance",
        {
            "lead_id": "rel-dormant",
            "regle": "relance_lead_dormant",
            "canal": "appel",
            "horodatage": "2026-10-16T12:00:00-04:00",
        },
        VENDEUR_UN,
    )
    assert monde.code(memes) == "REJ-RELANCE-TROP-PROCHE"
    autre = monde.appeler(
        "m2_preparer_relance",
        {
            "lead_id": "autre-client",
            "regle": "relance_lead_dormant",
            "canal": "appel",
            "horodatage": "2026-10-16T12:00:00-04:00",
        },
        VENDEUR_UN,
    )
    assert monde.accepte(autre)["regle"] == "relance_lead_dormant"
