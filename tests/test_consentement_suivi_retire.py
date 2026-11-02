"""Retrait du consentement de suivi chez M4 -> M1 (`m4.consentement_suivi_retire`), sur le VRAI bus.

Défaut fermé (revue adverse rvi, INTERCONNEXION.md §7) : un retrait chez M4 APRÈS
`m4.message_client_brouillon_pret` n'atteignait pas M1, qui pouvait créer un brouillon après le retrait sans que la
page d'approbation le dise. Prouve : le retrait est rangé, refuse tout brouillon visé (livré APRÈS le retrait, ordre
inversé), marque « suivi retiré » ceux qui ne sont pas partis (brouillon, demande, approbation), le dit à la direction,
n'est jamais défait par un événement plus ancien, survit au rejeu, à la panne et à la reprise. Monde de câblage des
connecteurs : base migrée, vrai bus, vrai sas, vrai registre de M1 ; seuls le réseau et les serveurs de courrier sont
des doubles. Fictif.
"""

from __future__ import annotations

import datetime as dt

import cablage_qa as cq
import interconnexion_charges as ch
import lea_rosalie_qa as lr
import pytest
from m1_front_office import message_client_m4 as mc
from sqlalchemy import update

from opsys import approbations, evenements, stockage
from opsys.courriel_connecteurs import envoi
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.evenements import ChargeInvalide
from opsys.evenements import repartiteur as rep
from opsys.stockage.schema import COURRIEL_BROUILLONS

FICTIF = True
M1, M4 = "m01-front-office", "m04-field-ops"
CLIENT = "cliente.fictive@example.test"
RETRAIT = "2026-11-02T09:00:00-05:00"


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


def _brouillon(lead, ident, **plus):
    evenements.publier(
        "m4.message_client_brouillon_pret", M4, ch.message_client(lead_id=lead, **plus), evenement_id=ident
    )


def _retrait(lead, ident, **plus):
    evenements.publier(
        "m4.consentement_suivi_retire", M4, ch.consentement_suivi_retire(lead_id=lead, **plus), evenement_id=ident
    )


def _journal(w):
    return w.registre(M1, mc.REGISTRE)


def _messages(w):
    return [m for m in _journal(w) if m["type_entree"] == mc.TYPE_ENTREE]


def _dernier(w):
    return list(mc._dernier_par_cle(_journal(w)).values())


def _sas(brouillon_id):
    with stockage.transaction() as cnx:
        return envoi.statut_brouillon(cnx, brouillon_id)


def _envoyes(w):
    return len(w.c.monde.gmail.envoyes)


def _ailleurs(w, passes_apres_heures=1):
    """Le répartiteur une heure plus tard (les échecs avec recul sont dus)."""
    return evenements.repartir(
        w.capacites.departements,
        maintenant=(dt.datetime.now(dt.UTC) + dt.timedelta(hours=passes_apres_heures)).isoformat(),
    )


def _attentes(w):
    with stockage.transaction() as cnx:
        return [
            a for a in approbations.file_proprietaire(cnx, w.capacites.departements) if a["type"] == mc.TYPE_ATTENTE
        ]


def _ouvrir_demande(w, brouillon_id):
    reponse = w.appeler("m1_demander_envoi_courriel", brouillon_id=brouillon_id, contexte="Fenêtre d'arrivée estimée")
    assert reponse["ok"] and reponse["resultat"]["resultat"]["statut"] == "en_attente_approbation", reponse
    return reponse["resultat"]["resultat"]["demande_id"]


# ------------------------------------------------------------------------------------------ ordre normal
def test_le_retrait_apres_le_brouillon_le_marque_suivi_retire_sans_rien_envoyer(w):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    (brouillon,) = _messages(w)
    assert brouillon["statut"] == "brouillon"
    _retrait(lead, "r-1")
    resume = w.repartir()
    assert resume["quarantaines"] == 0 and resume["echecs"] == 0
    (etat,) = _dernier(w)
    assert (
        etat["statut"] == mc.STATUT_RETIRE
        and etat["code"] == mc.CODE_RETIRE
        and etat["brouillon_id"] == brouillon["brouillon_id"]
    )
    assert etat["neutralise"] is True and etat["etat_envoi_au_retrait"] == "BROUILLON"
    assert _sas(brouillon["brouillon_id"])["statut"] == "BROUILLON" and _envoyes(w) == 0


def test_une_demande_d_envoi_est_refusee_pour_un_suivi_retire_et_lecture_le_dit(w):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    brouillon_id = _messages(w)[0]["brouillon_id"]
    _retrait(lead, "r-1")
    w.repartir()
    refus = w.appeler("m1_demander_envoi_courriel", brouillon_id=brouillon_id, contexte="Fenêtre d'arrivée estimée")
    assert not refus["ok"] or refus["resultat"].get("accepte") is False or "REJ-M1-MESSAGE-SUIVI-RETIRE" in str(refus)
    assert "REJ-M1-MESSAGE-SUIVI-RETIRE" in str(refus)
    assert _sas(brouillon_id)["demande_id"] is None
    lecture = w.appeler("m1_lire_reponse_courriel", brouillon_id=brouillon_id)["resultat"]["resultat"]
    assert lecture["suivi_retire"] is True and "retiré son consentement" in lecture["avertissement"]


def test_une_demande_en_attente_devient_caduque_et_la_direction_est_avertie(w):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    brouillon_id = _messages(w)[0]["brouillon_id"]
    demande_id = _ouvrir_demande(w, brouillon_id)
    assert _sas(brouillon_id)["statut"] == "DEMANDE" and _attentes(w) == []
    _retrait(lead, "r-1")
    w.repartir()
    assert _sas(brouillon_id)["statut"] == "BROUILLON"  # l'approbation de l'ancienne empreinte est caduque
    (attente,) = _attentes(w)
    assert (
        attente["id"] == demande_id and attente["niveau"] == "N3" and attente["action_proposee"] == "refuser la demande"
    )
    assert "retiré son consentement" in attente["resume"] and "PAS être approuvée" in attente["resume"]
    assert "@" not in str(attente) and CLIENT not in str(attente)
    # Même si une personne approuve : la demande échoue, rien ne part.
    decision = w.decider(demande_id, True)
    assert decision["statut"] == "echec", decision
    assert _sas(brouillon_id)["statut"] == "BROUILLON" and _envoyes(w) == 0
    assert _attentes(w) == []  # la demande est décidée : l'attente disparaît


def test_une_demande_refusee_par_la_direction_vide_l_attente(w):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    demande_id = _ouvrir_demande(w, _messages(w)[0]["brouillon_id"])
    _retrait(lead, "r-1")
    w.repartir()
    assert len(_attentes(w)) == 1
    assert w.decider(demande_id, False)["statut"] == "refusee"
    assert _attentes(w) == []


def test_un_brouillon_deja_approuve_retombe_en_brouillon_et_ne_peut_plus_partir(w):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    brouillon_id = _messages(w)[0]["brouillon_id"]
    demande_id = _ouvrir_demande(w, brouillon_id)
    assert w.decider(demande_id, True)["statut"] == "executee"
    assert _sas(brouillon_id)["statut"] == "APPROUVE"
    _retrait(lead, "r-1")
    w.repartir()
    assert _sas(brouillon_id)["statut"] == "BROUILLON"
    with pytest.raises(ErreurCourriel) as exc:
        envoi.ServiceEnvoi(stockage.transaction).envoyer(None, brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-NON-APPROUVEE" and _envoyes(w) == 0


@pytest.mark.parametrize("statut_sas", ["ENVOI_RESERVE", "ENVOYE", "INCERTAIN"])
def test_un_message_deja_dans_l_envoi_ne_se_rappelle_pas_et_la_ligne_le_dit_sans_mentir(w, statut_sas):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    brouillon_id = _messages(w)[0]["brouillon_id"]
    assert w.decider(_ouvrir_demande(w, brouillon_id), True)["statut"] == "executee"
    with stockage.transaction() as cnx:  # l'envoi a pris le brouillon approuvé (état posé tel que le sas le poserait)
        cnx.execute(
            update(COURRIEL_BROUILLONS)
            .where(COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id)
            .values(statut=statut_sas)
        )
    _retrait(lead, "r-1")
    w.repartir()
    (etat,) = _dernier(w)
    assert (
        etat["statut"] == mc.STATUT_RETIRE
        and etat["neutralise"] is False
        and etat["etat_envoi_au_retrait"] == statut_sas
    )
    assert _sas(brouillon_id)["statut"] == statut_sas  # M1 ne touche pas à ce qui est parti


def test_un_message_sms_a_reprendre_est_aussi_marque_retire(w):
    lead = _lead(w)
    _brouillon(lead, "b-1", canal="sms")
    w.repartir()
    assert _dernier(w)[0]["statut"] == "sms_a_reprendre"
    _retrait(lead, "r-1", canal="sms")
    w.repartir()
    assert _dernier(w)[0]["statut"] == mc.STATUT_RETIRE


# ------------------------------------------------------------------------------------------ ordre inversé
def test_ordre_inverse_le_brouillon_livre_apres_le_retrait_est_refuse_sans_rien_creer(w, monkeypatch):
    """Le brouillon est publié AVANT le retrait mais arrive APRÈS (panne transitoire) : jamais de brouillon."""
    lead = _lead(w)
    reel = mc._compte_d_envoi
    monkeypatch.setattr(mc, "_compte_d_envoi", lambda: None)  # le brouillon échoue la première fois
    _brouillon(lead, "b-1")
    w.repartir(passes=1)
    assert _messages(w) == []
    _retrait(lead, "r-1")
    w.repartir(passes=1)  # le retrait est livré ; le brouillon attend son recul
    assert [m["type_entree"] for m in _journal(w)] == [mc.TYPE_RETRAIT]
    monkeypatch.setattr(mc, "_compte_d_envoi", reel)
    resume = _ailleurs(w)
    assert resume["quarantaines"] == 0
    (etat,) = _dernier(w)
    assert etat["statut"] == mc.STATUT_RETIRE and etat["code"] == mc.CODE_RETIRE and "brouillon_id" not in etat
    with stockage.transaction() as cnx:
        assert cnx.execute(COURRIEL_BROUILLONS.select()).fetchall() == []  # aucun brouillon n'a été créé
    assert _envoyes(w) == 0


def test_le_retrait_livre_avant_le_brouillon_meme_instant_de_bus_visant_le_meme_consentement(w):
    """Course à la publication : le brouillon, préparé avant le retrait, est publié juste après lui. Le même maillon de
    consentement suffit à le reconnaître, sans horloge."""
    lead = _lead(w)
    _retrait(lead, "r-1", consentement_ligne_id="consent-X")
    w.repartir()
    _brouillon(
        lead, "b-1", consentement_ligne_id="consent-X"
    )  # publié APRÈS le retrait, mais fondé sur le consentement retiré
    w.repartir()
    (etat,) = _dernier(w)
    assert etat["statut"] == mc.STATUT_RETIRE


def test_un_nouveau_consentement_apres_le_retrait_donne_un_brouillon_que_le_retrait_ne_vise_pas(w):
    lead = _lead(w)
    _retrait(lead, "r-1", consentement_ligne_id="consent-X")
    w.repartir()
    _brouillon(lead, "b-2", consentement_ligne_id="consent-Y")  # recueilli et publié après le retrait
    w.repartir()
    (etat,) = _dernier(w)
    assert etat["statut"] == "brouillon" and etat["consentement_ligne_id"] == "consent-Y"


def test_un_retrait_plus_recent_vise_le_brouillon_du_nouveau_consentement_aussi(w):
    lead = _lead(w)
    _retrait(lead, "r-1", consentement_ligne_id="consent-X")
    w.repartir()
    _brouillon(lead, "b-2", consentement_ligne_id="consent-Y")
    w.repartir()
    _retrait(lead, "r-2", consentement_ligne_id="consent-Y", retire_le="2026-11-03T09:00:00-05:00")
    w.repartir()
    assert _dernier(w)[0]["statut"] == mc.STATUT_RETIRE


# ------------------------------------------------------------------------------------------ jamais défait
def test_un_evenement_plus_ancien_ne_defait_jamais_un_retrait(w):
    lead = _lead(w)
    _retrait(lead, "r-1", retire_le="2026-11-03T09:00:00-05:00", consentement_ligne_id="consent-X")
    w.repartir()
    # Un retrait plus ancien livré après le plus récent : sans effet sur l'état.
    _retrait(lead, "r-0", retire_le="2026-11-01T09:00:00-05:00", consentement_ligne_id=None)
    w.repartir()
    # Un brouillon plus ancien, rejoué sous un autre identifiant : toujours refusé.
    _brouillon(lead, "b-1", consentement_ligne_id="consent-X")
    _brouillon(lead, "b-1bis", consentement_ligne_id="consent-X")
    w.repartir()
    assert [m["statut"] for m in _messages(w)] == [mc.STATUT_RETIRE]
    assert len([m for m in _journal(w) if m["type_entree"] == mc.TYPE_RETRAIT]) == 2
    with stockage.transaction() as cnx:
        assert cnx.execute(COURRIEL_BROUILLONS.select()).fetchall() == []


def test_un_message_retire_ne_revient_jamais_a_brouillon_meme_rejoue(w):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    _retrait(lead, "r-1")
    w.repartir()
    _brouillon(lead, "b-1-rejeu")  # même contenu, autre identifiant
    w.repartir()
    assert [m["statut"] for m in _dernier(w)] == [mc.STATUT_RETIRE]


# ------------------------------------------------------------------------------------------ rejeu
def test_le_rejeu_du_meme_retrait_sous_un_autre_identifiant_n_ajoute_rien(w):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    _retrait(lead, "r-1")
    w.repartir()
    avant = len(_journal(w))
    _retrait(lead, "r-1-bis")
    resume = w.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    assert len(_journal(w)) == avant
    w.repartir()
    assert len(_journal(w)) == avant


# ------------------------------------------------------------------------------------------ panne et reprise
def test_panne_du_sas_au_retrait_rien_n_est_a_moitie_range_puis_reprise_unique(w, monkeypatch):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    brouillon_id = _messages(w)[0]["brouillon_id"]
    _ouvrir_demande(w, brouillon_id)
    reel = envoi.modifier_brouillon

    def panne(*args, **kwargs):
        raise ErreurCourriel("REJ-COURRIEL-COFFRE-INDISPONIBLE", "coffre indisponible", 503)

    monkeypatch.setattr(envoi, "modifier_brouillon", panne)
    _retrait(lead, "r-1")
    w.repartir(passes=1)
    assert [m["type_entree"] for m in _journal(w)] == [mc.TYPE_ENTREE]  # ni retrait ni marque : tout a été annulé
    assert _sas(brouillon_id)["statut"] == "DEMANDE"
    with stockage.transaction() as cnx:
        from sqlalchemy import select

        from opsys.stockage.schema import EVENEMENTS_RECUS

        recu = cnx.execute(select(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.evenement_id == "r-1")).mappings().one()
    assert recu["statut"] == "echec" and recu["prochaine_tentative"] and "COFFRE" in recu["derniere_erreur"]
    monkeypatch.setattr(envoi, "modifier_brouillon", reel)
    resume = _ailleurs(w)
    assert resume["quarantaines"] == 0
    assert _sas(brouillon_id)["statut"] == "BROUILLON" and _dernier(w)[0]["statut"] == mc.STATUT_RETIRE
    avant = len(_journal(w))
    _ailleurs(w, 3)
    assert len(_journal(w)) == avant  # une seule fois


# ------------------------------------------------------------------------------------------ portée
def test_le_retrait_ne_vise_que_son_chantier_et_son_canal(w):
    lead = _lead(w)
    _brouillon(lead, "b-1", canal="courriel")
    _brouillon(lead, "b-2", canal="sms", intervention_id="interv-fictive-2")
    _brouillon(
        lead,
        "b-3",
        intervention_id="interv-fictive-3",
        fenetre_debut="2026-11-04T09:00:00-05:00",
        fenetre_fin="2026-11-04T11:00:00-05:00",
        texte="Bonjour, notre équipe prévoit arriver entre 9 h et 11 h le 4 novembre. Estimation, pas une promesse. "
        "Répondez STOP pour ne plus recevoir ces messages.",
    )
    w.repartir()
    _retrait(lead, "r-1", intervention_id="interv-fictive-1", canal="courriel")
    w.repartir()
    par_intervention = {m["intervention_id"]: m["statut"] for m in _dernier(w)}
    assert par_intervention == {
        "interv-fictive-1": mc.STATUT_RETIRE,
        "interv-fictive-2": "sms_a_reprendre",
        "interv-fictive-3": "brouillon",
    }


def test_un_ancien_message_sans_instant_de_publication_est_vise_par_prudence(w):
    lead = _lead(w)
    _brouillon(lead, "b-1")
    w.repartir()
    ancien = _messages(w)[0]
    # Une ligne écrite avant ce chantier n'a ni `publie_le` ni `consentement_ligne_id` : fail-closed.
    assert mc.vise(None, None, {"consentement_ligne_id": "x", "publie_le": "2026-11-02T10:00:00+00:00"}) is True
    assert (
        mc.vise(
            ancien["consentement_ligne_id"], ancien["publie_le"], {"consentement_ligne_id": None, "publie_le": None}
        )
        is True
    )


@pytest.mark.parametrize(
    ("ligne_message", "publie_message", "ligne_retrait", "publie_retrait", "attendu"),
    [
        (
            "A",
            "2026-11-02T10:00:00+00:00",
            "A",
            "2026-11-02T09:00:00+00:00",
            True,
        ),  # même consentement, même publié après
        (
            "A",
            "2026-11-02T10:00:00+00:00",
            "B",
            "2026-11-02T09:00:00+00:00",
            False,
        ),  # nouveau consentement, publié après
        ("A", "2026-11-02T08:00:00+00:00", "B", "2026-11-02T09:00:00+00:00", True),  # publié avant le retrait
        ("A", "2026-11-02T09:00:00+00:00", "B", "2026-11-02T09:00:00+00:00", True),  # même instant : prudence
        ("A", "2026-11-02T10:00:00+00:00", None, "2026-11-02T09:00:00+00:00", False),  # retrait sans maillon visé
        (None, "2026-11-02T10:00:00+00:00", None, "2026-11-02T09:00:00+00:00", False),  # ni l'un ni l'autre maillon
        ("A", None, "B", "2026-11-02T09:00:00+00:00", True),  # instant du message absent
        ("A", "2026-11-02T10:00:00+00:00", "B", None, True),  # instant du retrait absent
        ("A", "illisible", "B", "2026-11-02T09:00:00+00:00", True),
        ("A", "2026-11-02T10:00:00", "B", "2026-11-02T09:00:00+00:00", True),  # sans fuseau : illisible
    ],
)
def test_qui_est_vise_par_un_retrait(ligne_message, publie_message, ligne_retrait, publie_retrait, attendu):
    retrait = {"consentement_ligne_id": ligne_retrait, "publie_le": publie_retrait}
    assert mc.vise(ligne_message, publie_message, retrait) is attendu


# ------------------------------------------------------------------------------------------ catalogue
def test_charge_hors_catalogue_refusee_et_rien_de_personnel_dans_le_schema():
    base = ch.consentement_suivi_retire()
    for plus in (
        {"courriel": CLIENT},
        {"telephone": "+15145550142"},
        {"nom": "Cliente Fictive"},
        {"source": "client_stop"},
    ):
        with pytest.raises(ChargeInvalide):
            evenements.publier("m4.consentement_suivi_retire", M4, {**base, **plus}, evenement_id="x")
    for manquant in base:
        incomplet = {k: v for k, v in base.items() if k != manquant}
        with pytest.raises(ChargeInvalide):
            evenements.publier("m4.consentement_suivi_retire", M4, incomplet, evenement_id="y")
    for hostile in ({"canal": "telegramme"}, {"retire_le": "hier"}, {"retire_le": "2026-11-02T09:00:00"}):
        with pytest.raises(ChargeInvalide):
            evenements.publier("m4.consentement_suivi_retire", M4, {**base, **hostile}, evenement_id="z")


def test_hors_livraison_l_instant_de_publication_est_absent():
    assert rep.instant_publication_livre() is None


# ------------------------------------------------------------------------------------------ instants de publication
def _livrer(fonction, charge, publie_le):
    """Livre `charge` comme le répartiteur le ferait, avec l'instant de PUBLICATION voulu (le bus le donne au
    consommateur ; ici on le choisit pour fabriquer l'ordre exact que l'on veut prouver)."""
    jeton = rep._EVENEMENT_LIVRE.set(publie_le)
    try:
        with stockage.transaction():
            return fonction(charge)
    finally:
        rep._EVENEMENT_LIVRE.reset(jeton)


def test_un_retrait_plus_ancien_livre_apres_un_brouillon_plus_recent_ne_le_vise_pas(w):
    """Le retrait R0 (publié à 09:00, consentement X) est livré APRÈS le brouillon D (publié à 10:00, nouveau
    consentement Y) : il ne peut pas viser ce qui a été publié après lui. Un retrait publié ensuite (11:00) le vise."""
    lead = _lead(w)
    _livrer(
        mc.recevoir_message_client_brouillon,
        ch.message_client(lead_id=lead, consentement_ligne_id="Y"),
        "2026-11-02T10:00:00+00:00",
    )
    (message,) = _dernier(w)
    assert message["statut"] == "brouillon" and message["publie_le"] == "2026-11-02T10:00:00+00:00"
    ancien = ch.consentement_suivi_retire(
        lead_id=lead, consentement_ligne_id="X", retire_le="2026-11-02T04:00:00-05:00"
    )
    resume = _livrer(mc.recevoir_consentement_suivi_retire, ancien, "2026-11-02T09:00:00+00:00")
    assert resume["messages_retires"] == 0 and _dernier(w)[0]["statut"] == "brouillon"
    recent = ch.consentement_suivi_retire(
        lead_id=lead, consentement_ligne_id="Y", retire_le="2026-11-02T06:00:00-05:00"
    )
    assert _livrer(mc.recevoir_consentement_suivi_retire, recent, "2026-11-02T11:00:00+00:00")["messages_retires"] == 1
    assert _dernier(w)[0]["statut"] == mc.STATUT_RETIRE


def test_un_brouillon_publie_apres_un_retrait_plus_ancien_et_livre_avant_lui_n_est_pas_retire(w):
    lead = _lead(w)
    ancien = ch.consentement_suivi_retire(lead_id=lead, consentement_ligne_id="X")
    _livrer(mc.recevoir_consentement_suivi_retire, ancien, "2026-11-02T09:00:00+00:00")
    nouveau = ch.message_client(lead_id=lead, consentement_ligne_id="Y")
    assert _livrer(mc.recevoir_message_client_brouillon, nouveau, "2026-11-02T10:00:00+00:00")["statut"] == "brouillon"
    ancien_message = ch.message_client(
        lead_id=lead,
        consentement_ligne_id="X",
        texte=nouveau["texte"] + " ",
        fenetre_debut="2026-11-04T09:00:00-05:00",
        fenetre_fin="2026-11-04T11:00:00-05:00",
    )
    refus = _livrer(mc.recevoir_message_client_brouillon, ancien_message, "2026-11-02T08:00:00+00:00")
    assert refus["statut"] == mc.STATUT_RETIRE  # publié AVANT le retrait : visé, même livré en dernier
