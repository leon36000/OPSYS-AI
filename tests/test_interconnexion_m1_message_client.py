"""M4 -> M1 : la fenêtre d'arrivée préparée par M4 devient un BROUILLON du sas d'envoi de M1, jamais un envoi.

Monde de câblage des connecteurs (base migrée, vrai bus, vrai sas, vrai registre de M1 ; seuls le réseau et les
serveurs de
courrier sont des doubles). Prouve : le brouillon existe et attend la demande N3 d'une personne ; rien n'est envoyé ni
approuvé ; le texte de M4 est repris tel quel ; retrait de consentement, lead inconnu, adresse absente et échéance
sont des
refus rangés ; absence de compte d'envoi = échec avec recul puis reprise unique ; SMS rangé « à reprendre ». Fictif.
"""

from __future__ import annotations

import cablage_qa as cq
import interconnexion_charges as ch
import lea_rosalie_qa as lr
import pytest
from m1_front_office import message_client_m4 as mc

from opsys import evenements, stockage
from opsys.courriel_connecteurs import envoi

FICTIF = True
M1, M4 = "m01-front-office", "m04-field-ops"
CLIENT = "cliente.fictive@example.test"


@pytest.fixture
def w(tmp_path, monkeypatch):
    monde = lr.monter(tmp_path, monkeypatch, (M1, M4))
    yield monde
    cq.demonter()


def _lead(w, expediteur=CLIENT, message_id="msg-1"):
    reponse = w.appeler(
        "m1_recevoir_message_canal",
        canal="courriel",
        expediteur=expediteur,
        message_id=message_id,
        recu_le="2026-10-30T14:00:00-04:00",
        texte="Bonjour, mes gouttières fuient à Laval.",
        objet="Fuite",
    )
    assert reponse["ok"] and reponse["resultat"]["decision"] == "TRANSMETTRE_M2", reponse
    return reponse["resultat"]["lead"]["lead_id"]


def _publier(lead_id, ident, **plus):
    evenements.publier(
        "m4.message_client_brouillon_pret", M4, ch.message_client(lead_id=lead_id, **plus), evenement_id=ident
    )


def _journal(w):
    return w.registre(M1, mc.REGISTRE)


def _envoyes(w):
    return len(w.c.monde.gmail.envoyes)


def test_le_brouillon_est_cree_dans_le_sas_sans_rien_envoyer_ni_approuver(w):
    lead = _lead(w)
    _publier(lead, "m4-1")
    resume = w.repartir()
    assert resume["quarantaines"] == 0
    (ligne,) = _journal(w)
    assert ligne["statut"] == "brouillon" and ligne["lead_id"] == lead
    with stockage.transaction() as cnx:
        brouillon = envoi.lire_brouillon(cnx, ligne["brouillon_id"])
        statut = envoi.statut_brouillon(cnx, ligne["brouillon_id"])
    assert list(brouillon.contenu.a) == [CLIENT] and brouillon.contenu.corps == ch.message_client()["texte"]
    assert brouillon.contenu.objet == mc.OBJET and statut["statut"] == "BROUILLON"
    assert statut["demande_id"] is None and _envoyes(w) == 0  # aucune demande N3, aucun envoi


def test_la_demande_d_envoi_reste_un_geste_n3_d_une_personne(w):
    lead = _lead(w)
    _publier(lead, "m4-1")
    w.repartir()
    brouillon_id = _journal(w)[0]["brouillon_id"]
    reponse = w.appeler("m1_demander_envoi_courriel", brouillon_id=brouillon_id, contexte="Fenêtre d'arrivée estimée")
    assert reponse["ok"] and reponse["resultat"]["resultat"]["statut"] == "en_attente_approbation"
    assert _envoyes(w) == 0  # la demande attend une décision humaine


def test_rejeu_sous_un_autre_evenement_id_un_seul_brouillon_pas_de_quarantaine(w):
    lead = _lead(w)
    _publier(lead, "m4-1")
    w.repartir()
    _publier(lead, "m4-2")
    resume = w.repartir()
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0
    assert len(_journal(w)) == 1


def test_un_message_different_est_un_autre_brouillon(w):
    lead = _lead(w)
    _publier(lead, "m4-1")
    _publier(
        lead,
        "m4-2",
        fenetre_debut="2026-11-04T09:00:00-05:00",
        fenetre_fin="2026-11-04T11:00:00-05:00",
        texte="Bonjour, notre équipe prévoit arriver entre 9 h et 11 h le 4 novembre. Estimation, pas une promesse. "
        "Répondez STOP pour ne plus recevoir ces messages.",
    )
    w.repartir()
    assert len(_journal(w)) == 2


def test_lead_inconnu_de_m1_refus_range(w):
    _publier("lead-fantome", "m4-1")
    resume = w.repartir()
    assert resume["quarantaines"] == 0
    assert _journal(w)[0]["statut"] == "refuse" and _journal(w)[0]["code"] == "REJ-M1-MESSAGE-LEAD-INCONNU"


def test_retrait_du_consentement_depuis_la_publication_refuse_le_message(w):
    """Le STOP (SMS) arrive APRÈS la préparation de M4 : M1 le sait, pas M4. Le message est refusé, rien n'est
    déposé."""
    numero = "+15145550142"
    premier = w.appeler(
        "m1_recevoir_message_canal",
        canal="sms",
        expediteur=numero,
        message_id="SMfictif1",
        recu_le="2026-10-30T14:00:00-04:00",
        texte="Bonjour, mes gouttières fuient à Laval.",
    )
    lead = premier["resultat"]["lead"]["lead_id"]
    stop = w.appeler(
        "m1_recevoir_message_canal",
        canal="sms",
        expediteur=numero,
        message_id="SMfictif2",
        recu_le="2026-10-31T09:00:00-04:00",
        texte="STOP",
    )
    assert stop["ok"], stop
    _publier(lead, "m4-1", canal="sms")
    w.repartir()
    assert _journal(w)[0]["statut"] == "refuse" and _journal(w)[0]["code"] == "REJ-M1-MESSAGE-RETRAIT-CONSENTEMENT"
    assert _envoyes(w) == 0


def test_message_echu_est_range_echu(w):
    lead = _lead(w)
    _publier(lead, "m4-1", conserve_jusqu_au="2026-10-01T00:00:00-04:00")
    w.repartir()
    assert _journal(w)[0]["statut"] == "echu"


def test_canal_sms_est_range_a_reprendre_jamais_envoye(w):
    lead = _lead(w)
    _publier(lead, "m4-1", canal="sms")
    w.repartir()
    assert _journal(w)[0]["statut"] == "sms_a_reprendre" and _envoyes(w) == 0


def test_sans_compte_d_envoi_echec_avec_recul_puis_reprise_unique(w, monkeypatch):
    lead = _lead(w)
    reel = mc._compte_d_envoi
    monkeypatch.setattr(mc, "_compte_d_envoi", lambda: None)
    _publier(lead, "m4-1")
    w.repartir(passes=1)
    assert _journal(w) == []
    recus = [r for r in w.registre(M1, "principal") if False]  # le reçu du bus est lu plus bas
    with stockage.transaction() as cnx:
        from sqlalchemy import select

        from opsys.stockage.schema import EVENEMENTS_RECUS

        ligne = (
            cnx.execute(
                select(EVENEMENTS_RECUS).where(
                    (EVENEMENTS_RECUS.c.evenement_id == "m4-1") & (EVENEMENTS_RECUS.c.consommateur == M1)
                )
            )
            .mappings()
            .one()
        )
    assert ligne["statut"] == "echec" and "AUCUN-COMPTE" in ligne["derniere_erreur"] and recus == []
    monkeypatch.setattr(mc, "_compte_d_envoi", reel)
    import datetime as dt

    evenements.repartir(
        w.capacites.departements, maintenant=(dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat()
    )
    assert len(_journal(w)) == 1 and _journal(w)[0]["statut"] == "brouillon"
    evenements.repartir(
        w.capacites.departements, maintenant=(dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)).isoformat()
    )
    assert len(_journal(w)) == 1


def test_adresse_absente_refus_range(w):
    # Un lead par SMS n'a pas d'adresse courriel : le canal courriel de M4 ne peut pas être servi.
    reponse = w.appeler(
        "m1_recevoir_message_canal",
        canal="sms",
        expediteur="+15145550142",
        message_id="SMfictif1",
        recu_le="2026-10-30T14:00:00-04:00",
        texte="Bonjour, mes gouttières fuient à Laval.",
    )
    assert reponse["ok"], reponse
    lead = reponse["resultat"]["lead"]["lead_id"]
    _publier(lead, "m4-1", canal="courriel")
    w.repartir()
    assert _journal(w)[0]["code"] == "REJ-M1-MESSAGE-SANS-COURRIEL"


def test_la_cle_depend_du_contenu_pas_de_l_evenement():
    base = ch.message_client()
    assert mc.cle(base) == mc.cle(dict(base))
    assert mc.cle(base) != mc.cle({**base, "texte": base["texte"] + " "})
    assert mc.cle(base) != mc.cle({**base, "canal": "sms"})
