"""PLAN T4.17-e3 — le `utm` du formulaire d'un site : du lien suivi par le visiteur au lead, sans perte silencieuse.

`formulaire` est un canal de `m1_recevoir_message_canal` (l'adresse ou le numéro que le visiteur a écrit, jamais
vérifiée) et le SEUL qui porte un `utm`. Ce fichier prouve, pour ce canal :

- le lead porte le `utm` tel que le formulaire l'a transmis (clés et valeurs d'octet à octet, rien de complété ni de
  normalisé), et le dit (`utm.statut`) ; sans `utm`, le lead n'en porte pas ;
- un `utm` invalide, ou fourni pour un SMS, un courriel ou un appel, est refusé AVANT toute écriture, par un verdict qui
  nomme la règle et dit quoi corriger ;
- un `utm` qu'aucun lead ne porte (demande incomplète, conversation déjà qualifiée, plainte) est dit, jamais perdu en
  silence, et reste sur la ligne de son signal au registre ;
- un message rejoué n'écrit rien de plus, et son `utm` se lit toujours sur le lead que le registre rend ;
- l'identité d'un formulaire est étiquetée « écrite par le client », jamais « vérifiée par le canal ».

Registre en mémoire, sauf le dernier test (base réelle, `Capacites`, bus). Adresses en `.test`, messages fictifs.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from m1_front_office import contrats, reception
from m1_front_office.outils import (
    _obtenir_registre,
    escalader_plainte,
    lire_transfert,
    outils,
    qualifier_signal,
    recevoir_message_canal,
    reinitialiser_registre,
    traiter_demande_entrante,
    utiliser_stockage_durable,
)
from sqlalchemy import func, select

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste
from opsys.outils import executer
from opsys.stockage.schema import EVENEMENTS_SORTANTS

M1 = Path(__file__).resolve().parents[1]
ADRESSE = "visiteur.fictif@exemple.test"
NUMERO = "+15145550142"
DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
DEMANDE = "Bonjour, mes gouttières fuient à Laval, c'est urgent."
# Ce que M7 met dans un lien de paquet (`departments/m07-marketing`, `utm-convention.v1.yaml`) : quatre clés.
UTM = {
    "utm_source": "facebook",
    "utm_medium": "social",
    "utm_campaign": "contenu-gouttieres-2026",
    "utm_content": "facebook-0123456789abcdef",
}
AUTRE_UTM = {"utm_source": "instagram", "utm_medium": "social", "utm_content": "instagram-fedcba9876543210"}


def _a(minutes: float) -> str:
    return (DEBUT + dt.timedelta(minutes=minutes)).isoformat()


@pytest.fixture(autouse=True)
def _instance(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    reinitialiser_registre()
    yield
    reinitialiser_registre()


def _fenetre(minutes: int = 30) -> None:
    taxonomie.enregistrer_fenetre_conversation(minutes)


def _formulaire(texte=DEMANDE, message_id="F-0001", minutes=0.0, expediteur=ADRESSE, **plus):
    return recevoir_message_canal(
        canal="formulaire", expediteur=expediteur, message_id=message_id, recu_le=_a(minutes), texte=texte, **plus)


def _lignes(type_entree: str | None = None) -> list[dict]:
    lignes = _obtenir_registre().lire()
    return lignes if type_entree is None else [ligne for ligne in lignes if ligne["type_entree"] == type_entree]


# =====================================================================================================================
# 1. Le lead porte le `utm` tel que le formulaire l'a transmis
# =====================================================================================================================
def test_un_formulaire_avec_utm_donne_un_lead_v2_qui_porte_l_utm_tel_quel():
    reponse = _formulaire(utm=dict(UTM))

    assert reponse["accepte"] is True and reponse["qualifie"] is True and reponse["decision"] == "TRANSMETTRE_M2"
    lead = reponse["lead"]
    assert lead == {
        "schema_version": 2,
        "lead_id": lead["lead_id"],
        "service": "gouttieres",
        "ville": "Laval",
        "urgence_declaree": True,
        "canal": "formulaire",
        "conversation_id": reception.identifiant_de_conversation("formulaire", ADRESSE),
        "contact": {"courriel": ADRESSE},
        "source": "formulaire",
        "utm": UTM,
    }
    services, _ = taxonomie.charger_services()
    assert contrats.valider_lead(lead, services=services)["code"] == "EVT-CONTRAT-VALIDE"
    assert reponse["utm"] == {"statut": "porte_par_le_lead"}
    assert "cle_session" not in reponse, "un formulaire n'a pas de session par correspondant"


def test_un_utm_partiel_est_porte_sans_etre_complete():
    reponse = _formulaire(utm={"utm_source": "google", "utm_medium": "cpc"})
    assert reponse["lead"]["utm"] == {"utm_source": "google", "utm_medium": "cpc"}
    assert set(reponse["lead"]["utm"]) == {"utm_source", "utm_medium"}, "aucune clé n'est ajoutée, aucune devinée"


def test_les_valeurs_sont_portees_d_octet_a_octet_sans_normalisation():
    """M2 ne revalide pas l'alphabet de M7 : M1 non plus. Majuscules, espaces, accents, ponctuation : tels quels."""
    tel_quel = {
        "utm_source": "Facebook Ads",
        "utm_medium": "CPC ",
        "utm_campaign": "Printemps 2026 — été/automne?",
        "utm_content": "ÉTÉ_x=1&y=2",
    }
    reponse = _formulaire(utm=dict(tel_quel))
    assert reponse["lead"]["utm"] == tel_quel
    assert _lignes("lead_emis")[0]["lead"]["utm"] == tel_quel


def test_sans_utm_le_lead_n_en_porte_pas_et_la_reponse_ne_dit_rien_d_un_utm_qu_on_ne_lui_a_pas_donne():
    reponse = _formulaire()
    assert "utm" not in reponse["lead"] and "utm" not in reponse, "jamais de valeur par défaut inventée"
    reponse_explicite = _formulaire(message_id="F-0002", expediteur="autre.visiteur@exemple.test", utm=None)
    assert "utm" not in reponse_explicite["lead"] and "utm" not in reponse_explicite


def test_le_lead_ne_partage_pas_le_dictionnaire_de_l_appelant():
    fourni = dict(UTM)
    reponse = _formulaire(utm=fourni)
    fourni["utm_content"] = "modifie-apres-coup"
    fourni["utm_id"] = "ajoute-apres-coup"
    assert reponse["lead"]["utm"] == UTM
    assert _lignes("lead_emis")[0]["lead"]["utm"] == UTM and _lignes("signal")[0]["utm"] == UTM


def test_le_utm_reste_au_registre_sur_la_ligne_du_signal_et_sur_celle_du_lead():
    _formulaire(utm=dict(UTM))
    signal, lead = _lignes()
    assert (signal["type_entree"], lead["type_entree"]) == ("signal", "lead_emis")
    assert signal["utm"] == UTM and lead["lead"]["utm"] == UTM
    assert signal["canal"] == "formulaire" and signal["source"] == "formulaire"
    assert signal["signal_id"] == lead["signal_id"] == "formulaire:F-0001"
    assert _obtenir_registre().valider_chaine() == (True, None)


def test_la_ligne_d_un_signal_sans_utm_n_a_pas_de_cle_utm():
    _formulaire()
    assert all("utm" not in ligne for ligne in _lignes("signal"))


def test_le_contact_du_lead_est_l_identite_du_formulaire_seule_meme_si_le_texte_donne_un_autre_courriel():
    reponse = _formulaire(DEMANDE + " Écrivez-moi plutôt à autre.fictif@exemple.test ou au 514-555-9999.", utm=UTM)
    assert reponse["lead"]["contact"] == {"courriel": ADRESSE}


def test_un_numero_e164_ecrit_dans_le_formulaire_est_aussi_une_identite():
    reponse = _formulaire(expediteur=NUMERO, utm=UTM)
    assert reponse["lead"]["contact"] == {"telephone": NUMERO} and reponse["lead"]["utm"] == UTM


# =====================================================================================================================
# 2. Un `utm` invalide est refusé avant toute écriture, et le verdict dit quoi corriger
# =====================================================================================================================
@pytest.mark.parametrize("mauvais, fragment", [
    ({}, "dictionnaire non vide"),
    ("google", "dictionnaire non vide"),
    (["utm_source"], "dictionnaire non vide"),
    (42, "dictionnaire non vide"),
    ({"utm_id": "abc"}, "'utm_id'"),
    ({"utm_source": "google", "utm_term": "gouttières"}, "'utm_term'"),
    ({"UTM_SOURCE": "google"}, "'UTM_SOURCE'"),
    ({"utm_source": ""}, "'utm_source'"),
    ({"utm_source": "google", "utm_content": ""}, "'utm_content'"),
    ({"utm_source": 3}, "'utm_source'"),
    ({"utm_source": None}, "'utm_source'"),
    ({"utm_source": True}, "'utm_source'"),
    ({"utm_source": ["google"]}, "'utm_source'"),
])
def test_un_utm_invalide_est_refuse_sans_rien_ecrire_et_le_verdict_dit_quoi_corriger(mauvais, fragment):
    with pytest.raises(ValueError, match="REJ-UTM-INVALIDE") as exc:
        _formulaire(utm=mauvais)
    message = str(exc.value)
    assert fragment in message, message
    assert "Recopie les paramètres utm_*" in message and "omets `utm`" in message, "il dit quoi faire"
    for cle in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
        assert cle in message, "il liste les clés permises"
    assert "Rien n'est écrit" in message
    assert _lignes() == []


def test_un_utm_invalide_est_refuse_meme_quand_le_message_serait_un_doublon():
    """Le refus vient avant la recherche d'un rejeu : un appel mal formé n'est jamais servi par la réponse d'avant."""
    _formulaire(utm=dict(UTM))
    taille = _obtenir_registre().taille()
    with pytest.raises(ValueError, match="REJ-UTM-INVALIDE"):
        _formulaire(utm={"utm_id": "x"})
    assert _obtenir_registre().taille() == taille


# =====================================================================================================================
# 3. Un canal sans lien ne porte pas de `utm` : refusé, jamais ignoré, jamais déduit du texte
# =====================================================================================================================
@pytest.mark.parametrize("canal, expediteur", [("sms", NUMERO), ("courriel", ADRESSE)])
def test_un_utm_fourni_pour_un_sms_ou_un_courriel_est_refuse_et_le_verdict_le_dit(canal, expediteur):
    with pytest.raises(ValueError, match="REJ-UTM-CANAL-SANS-SENS") as exc:
        recevoir_message_canal(
            canal=canal, expediteur=expediteur, message_id="M-1", recu_le=_a(0), texte=DEMANDE, utm=dict(UTM))
    message = str(exc.value)
    assert repr(canal) in message and "'formulaire'" in message and "Retire `utm`" in message
    assert "jamais déduit du texte" in message and "Rien n'est écrit" in message
    assert _lignes() == []


def test_un_stop_qui_porte_un_utm_est_refuse_sans_inscrire_le_retrait():
    with pytest.raises(ValueError, match="REJ-UTM-CANAL-SANS-SENS"):
        recevoir_message_canal(
            canal="sms", expediteur=NUMERO, message_id="SM-STOP", recu_le=_a(0), texte="STOP", utm=dict(UTM))
    assert _lignes() == [], "ni signal ni alerte : le refus vient avant le retrait"


def test_un_sms_sans_utm_est_inchange_et_ne_dit_rien_d_un_utm():
    reponse = recevoir_message_canal(
        canal="sms", expediteur=NUMERO, message_id="SM-1", recu_le=_a(0), texte=DEMANDE, utm=None)
    assert reponse["decision"] == "TRANSMETTRE_M2" and "utm" not in reponse and "utm" not in reponse["lead"]


@pytest.mark.parametrize("canal", ["telephone", "texte", "courriel"])
def test_l_ancien_outil_refuse_aussi_un_utm_pour_un_appel_un_sms_ou_un_courriel(canal):
    with pytest.raises(ValueError, match="REJ-UTM-CANAL-SANS-SENS") as exc:
        traiter_demande_entrante(
            contenu_brut="Gouttières à Laval, téléphone 450-555-0000.", canal=canal, conversation_id="conv-1",
            signal_id="sig-1", horodatage=_a(0), zone_desservie=["Laval"], utm=dict(UTM))
    assert repr(canal) in str(exc.value)
    assert _lignes() == [], "refusé avant l'écriture du signal"


def test_l_ancien_outil_porte_le_utm_d_un_formulaire_et_le_dit():
    reponse = traiter_demande_entrante(
        contenu_brut="Gouttières à Laval, téléphone 450-555-0000.", canal="formulaire", conversation_id="conv-2",
        signal_id="sig-2", horodatage=_a(0), zone_desservie=["Laval"], utm=dict(UTM))
    assert reponse["qualifie"] is True and reponse["lead"]["utm"] == UTM
    assert reponse["utm"] == {"statut": "porte_par_le_lead"}
    assert _lignes("signal")[0]["utm"] == UTM


def test_l_ancien_outil_refuse_un_utm_invalide_sans_rien_ecrire():
    with pytest.raises(ValueError, match="REJ-UTM-INVALIDE"):
        traiter_demande_entrante(
            contenu_brut="Gouttières à Laval, téléphone 450-555-0000.", canal="formulaire", conversation_id="conv-3",
            signal_id="sig-3", horodatage=_a(0), zone_desservie=["Laval"], utm={"utm_inconnu": "x"})
    assert _lignes() == []


def test_l_outil_de_qualification_suit_la_meme_regle():
    contenu = "Gouttières à Laval, téléphone 450-555-0000."
    lead = qualifier_signal(contenu, "formulaire", "conv-4", ["Laval"], utm=dict(UTM))
    assert lead["utm"] == UTM and lead["canal"] == "formulaire"
    sans = qualifier_signal(contenu, "formulaire", "conv-4", ["Laval"])
    assert "utm" not in sans
    with pytest.raises(ValueError, match="REJ-UTM-CANAL-SANS-SENS"):
        qualifier_signal(contenu, "texte", "conv-4", ["Laval"], utm=dict(UTM))
    with pytest.raises(ValueError, match="REJ-UTM-INVALIDE"):
        qualifier_signal(contenu, "formulaire", "conv-4", ["Laval"], utm={})


# =====================================================================================================================
# 4. La règle est une seule : `contrats.utm_invalide` sert le contrat, le refus et la réception
# =====================================================================================================================
@pytest.mark.parametrize("utm", [
    UTM, {"utm_source": "google"}, {"utm_content": "x"}, {"utm_source": "a", "utm_medium": "b", "utm_campaign": "c"},
])
def test_utm_conforme(utm):
    assert contrats.utm_invalide(utm) is None
    assert contrats.verifier_utm("formulaire", utm) is None


@pytest.mark.parametrize("utm", [{}, "x", [], {"utm_id": "a"}, {"utm_source": ""}, {"utm_source": 1}, {1: "a"}])
def test_utm_non_conforme(utm):
    assert contrats.utm_invalide(utm) is not None
    verdict = contrats.verifier_utm("formulaire", utm)
    assert verdict["code"] == "REJ-UTM-INVALIDE" and verdict["detail"]
    with pytest.raises(ValueError, match="REJ-UTM-INVALIDE"):
        contrats.exiger_utm("formulaire", utm)


def test_none_est_l_absence_d_utm_pour_l_appelant_mais_pas_un_utm_valide_pour_le_contrat():
    """`utm: null` veut dire « pas d'utm » (le lead n'en porte pas) ; dans un lead, la clé `utm` doit être un objet."""
    assert contrats.verifier_utm("formulaire", None) is None
    assert contrats.utm_invalide(None) is not None


def test_le_contrat_v2_refuse_avec_les_memes_mots_qu_avant():
    """La refonte de `_champ_optionnel_v2_invalide` ne change ni la règle ni le message du contrat gelé."""
    services, _ = taxonomie.charger_services()
    lead = _formulaire(utm=dict(UTM))["lead"]
    assert contrats.valider_lead(lead, services=services)["code"] == "EVT-CONTRAT-VALIDE"
    for mauvais, motif in (({}, "dictionnaire non vide exigé"), ({"utm_x": "a"}, "sous-clé 'utm_x' hors de"),
                           ({"utm_source": ""}, "sous-clé 'utm_source' hors de")):
        with pytest.raises(ValueError, match="REJ-CONTRAT-INVALIDE: champ optionnel 'utm' : " + motif):
            contrats.valider_lead({**lead, "utm": mauvais}, services=services)


def test_un_utm_absent_n_est_jamais_un_verdict_quel_que_soit_le_canal():
    for canal in ("formulaire", "texte", "telephone", "courriel", "sms"):
        assert contrats.verifier_utm(canal, None) is None
    contrats.exiger_utm("texte", None)


def test_les_canaux_qui_portent_un_utm_sont_le_formulaire_seul():
    assert contrats.CANAUX_AVEC_UTM == ("formulaire",)
    for canal in ("texte", "telephone", "courriel", "sms", "fax", ""):
        assert contrats.verifier_utm(canal, dict(UTM))["code"] == "REJ-UTM-CANAL-SANS-SENS", canal


# =====================================================================================================================
# 5. Un `utm` qu'aucun lead ne porte est dit, jamais perdu en silence
# =====================================================================================================================
def test_une_demande_incomplete_ne_porte_pas_le_utm_le_dit_et_le_garde_au_registre():
    reponse = _formulaire("Bonjour, mes gouttières fuient.", utm=dict(UTM))
    assert reponse["qualifie"] is False and reponse["decision"] == "DEMANDER_PRECISIONS" and "lead" not in reponse
    assert reponse["utm"]["statut"] == "non_porte" and reponse["utm"]["raison"] == "aucun_lead_ouvert"
    detail = reponse["utm"]["detail"]
    assert "aucun lead ne porte cet utm" in detail and "Dis-le à une personne" in detail
    (signal,) = _lignes()
    assert signal["type_entree"] == "signal" and signal["utm"] == UTM, "ce que le visiteur a déclaré n'est pas perdu"


def test_le_lead_qui_naitra_plus_tard_porte_l_utm_du_message_qui_le_fait_naitre():
    _fenetre()
    premier = _formulaire("Bonjour, mes gouttières fuient.", "F-1", 0, utm=dict(UTM))
    assert premier["utm"]["raison"] == "aucun_lead_ouvert"
    second = _formulaire("Je suis à Laval.", "F-2", 4, utm=dict(AUTRE_UTM))
    assert second["decision"] == "TRANSMETTRE_M2" and second["conversation"]["messages"] == 2
    assert second["lead"]["utm"] == AUTRE_UTM, "celui de CE message, jamais un mélange des deux ni le premier"
    assert second["utm"] == {"statut": "porte_par_le_lead"}
    assert [ligne.get("utm") for ligne in _lignes("signal")] == [UTM, AUTRE_UTM]


def test_un_message_sans_utm_qui_fait_naitre_le_lead_ne_lui_en_donne_pas():
    """Limite documentée (§13.4) : l'UTM d'un message précédent ne passe pas au lead, il reste sur sa ligne."""
    _fenetre()
    _formulaire("Bonjour, mes gouttières fuient.", "F-1", 0, utm=dict(UTM))
    second = _formulaire("Je suis à Laval.", "F-2", 4)
    assert second["decision"] == "TRANSMETTRE_M2" and "utm" not in second["lead"] and "utm" not in second
    assert _lignes("signal")[0]["utm"] == UTM


def test_un_message_dans_une_conversation_deja_qualifiee_ne_change_pas_le_lead_et_le_dit():
    _fenetre()
    _formulaire(utm=dict(UTM))
    suite = _formulaire("Et aussi le soffite à Laval.", "F-2", 5, utm=dict(AUTRE_UTM))
    assert suite["decision"] == "CONVERSATION_DEJA_QUALIFIEE" and suite["nouveau_lead"] is False
    assert suite["lead"]["utm"] == UTM, "le lead est gelé (contrat v2) : il garde celui d'avant"
    assert suite["utm"]["statut"] == "non_porte" and suite["utm"]["raison"] == "lead_deja_emis"
    assert _lignes("signal")[1]["utm"] == AUTRE_UTM
    meme = _formulaire("Merci.", "F-3", 6, utm=dict(UTM))
    assert meme["utm"] == {"statut": "porte_par_le_lead"}, "le même utm que celui du lead : rien à dire de plus"
    assert len(_lignes("lead_emis")) == 1


def test_une_plainte_par_formulaire_n_ouvre_pas_de_lead_et_son_utm_reste_au_registre(declarer_plaintes):
    declarer_plaintes()
    reponse = _formulaire("Je suis très déçu de votre service.", utm=dict(UTM))
    assert reponse["decision"] == "ESCALADE_PLAINTE" and reponse["qualifie"] is False and "lead" not in reponse
    assert reponse["utm"]["statut"] == "non_porte" and reponse["utm"]["raison"] == "transfert_humain"
    (signal,) = _lignes("signal")
    assert signal["utm"] == UTM
    assert _lignes("lead_emis") == []


def test_le_bloc_utm_ne_depend_pas_de_la_fenetre_de_conversation():
    sans_fenetre = _formulaire("Bonjour, mes gouttières fuient.", utm=dict(UTM))
    assert sans_fenetre["utm"]["raison"] == "aucun_lead_ouvert"
    assert sans_fenetre["conversation"]["mode"] == "message_par_message"


# =====================================================================================================================
# 6. Le rejeu : exactement une ligne par signal, et le `utm` se lit sur le lead que le registre rend
# =====================================================================================================================
def test_un_formulaire_rejoue_n_ecrit_rien_de_plus_et_rend_le_meme_lead_avec_son_utm():
    premiere = _formulaire(utm=dict(UTM))
    taille = _obtenir_registre().taille()
    seconde = _formulaire(utm=dict(UTM))
    assert _obtenir_registre().taille() == taille
    assert seconde["doublon"] is True and seconde["decision"] == "TRANSMETTRE_M2"
    assert seconde["lead"] == premiere["lead"] and seconde["lead"]["utm"] == UTM
    assert seconde["utm"] == {"statut": "porte_par_le_lead"}


def test_un_rejeu_qui_porte_un_autre_utm_ne_change_pas_le_lead_et_le_dit():
    _formulaire(utm=dict(UTM))
    taille = _obtenir_registre().taille()
    rejeu = _formulaire(utm=dict(AUTRE_UTM))
    assert _obtenir_registre().taille() == taille, "un rejeu n'écrit jamais"
    assert rejeu["doublon"] is True and rejeu["lead"]["utm"] == UTM
    assert rejeu["utm"]["statut"] == "non_porte" and rejeu["utm"]["raison"] == "lead_deja_emis"


def test_un_rejeu_sans_utm_ne_dit_rien_d_un_utm_qu_on_ne_lui_a_pas_donne():
    _formulaire(utm=dict(UTM))
    rejeu = _formulaire()
    assert rejeu["doublon"] is True and rejeu["lead"]["utm"] == UTM and "utm" not in rejeu


def test_le_rejeu_d_une_demande_incomplete_dit_toujours_que_son_utm_n_est_porte_par_aucun_lead():
    _formulaire("Bonjour.", utm=dict(UTM))
    rejeu = _formulaire("Bonjour.", utm=dict(UTM))
    assert rejeu["doublon"] is True and rejeu["utm"]["raison"] == "aucun_lead_ouvert"
    assert len(_lignes("signal")) == 1


# =====================================================================================================================
# 7. L'identité d'un formulaire est écrite par le visiteur : elle s'étiquette ainsi, jamais « vérifiée par le canal »
# =====================================================================================================================
def test_le_contact_d_un_formulaire_est_etiquete_texte_et_celui_d_un_sms_canal():
    _fenetre()
    formulaire = _formulaire("Bonjour, mes gouttières fuient.", utm=dict(UTM))
    assert formulaire["conversation"]["connu"]["contact"] == "texte"
    sms = recevoir_message_canal(
        canal="sms", expediteur=NUMERO, message_id="SM-1", recu_le=_a(0), texte="Bonjour, mes gouttières fuient.")
    assert sms["conversation"]["connu"]["contact"] == "canal"


def test_la_reponse_d_une_conversation_qualifiee_garde_la_meme_etiquette_pour_le_formulaire():
    _fenetre()
    _formulaire(utm=dict(UTM))
    suite = _formulaire("Merci.", "F-2", 3)
    assert suite["decision"] == "CONVERSATION_DEJA_QUALIFIEE"
    assert suite["conversation"]["connu"]["contact"] == "texte"


def test_un_transfert_ouvert_par_les_regles_dit_que_le_contact_du_formulaire_est_ecrit_par_le_client(declarer_plaintes):
    declarer_plaintes()
    reponse = _formulaire("Je suis très déçu de votre service.")
    lu = lire_transfert(reponse["transfert"]["transfert_id"])["resultat"]
    assert lu["contact"] == {"courriel": ADRESSE}
    assert "Contact : écrit par le client dans son message (porté à part)." in lu["resume"]
    assert "vérifié par le canal" not in lu["resume"]


def test_un_transfert_ouvert_par_l_agent_pour_un_formulaire_dit_la_meme_chose(declarer_plaintes):
    declarer_plaintes()
    _formulaire("Bonjour, ça ne va pas du tout avec vos gars.")
    resultat = escalader_plainte("autre", "formulaire", ADRESSE)["resultat"]
    lu = lire_transfert(resultat["transfert"]["transfert_id"])["resultat"]
    assert lu["contact"] == {"courriel": ADRESSE} and lu["canal"] == "formulaire"
    assert "Contact : écrit par le client dans son message (porté à part)." in lu["resume"]


def test_un_transfert_ouvert_pour_un_sms_dit_toujours_que_le_canal_a_verifie_le_contact(declarer_plaintes):
    declarer_plaintes()
    reponse = recevoir_message_canal(
        canal="sms", expediteur=NUMERO, message_id="SM-1", recu_le=_a(0), texte="Je suis très déçu de votre service.")
    lu = lire_transfert(reponse["transfert"]["transfert_id"])["resultat"]
    assert "Contact : celui du correspondant, vérifié par le canal (porté à part)." in lu["resume"]


# =====================================================================================================================
# 8. L'outil : le schéma, l'enveloppe, le niveau
# =====================================================================================================================
def _outil():
    return next(o for o in outils() if o.nom == "m1_recevoir_message_canal")


def test_le_schema_de_l_outil_porte_utm_sans_l_exiger():
    outil = _outil()
    utm = outil.parametres["properties"]["utm"]
    assert utm["type"] == ["object", "null"]
    assert "utm" not in outil.parametres["required"]
    assert "formulaire" in utm["description"] and "refusé" in utm["description"]
    assert set(outil.parametres["required"]) == {"canal", "expediteur", "message_id", "recu_le", "texte"}
    assert outil.parametres["additionalProperties"] is False


def test_l_enveloppe_rend_le_refus_d_un_utm_comme_un_refus_metier_qui_dit_quoi_corriger():
    base = {"canal": "formulaire", "expediteur": ADRESSE, "message_id": "F-1", "recu_le": _a(0), "texte": DEMANDE}
    invalide = executer(_outil(), {**base, "utm": {"utm_id": "x"}})
    assert invalide["ok"] is False and invalide["erreur"] == "refus_metier"
    assert invalide["details"].startswith("REJ-UTM-INVALIDE: ") and "'utm_id'" in invalide["details"]
    sms = executer(_outil(), {**base, "canal": "sms", "expediteur": NUMERO, "utm": dict(UTM)})
    assert sms["ok"] is False and sms["erreur"] == "refus_metier"
    assert sms["details"].startswith("REJ-UTM-CANAL-SANS-SENS: ")
    accepte = executer(_outil(), {**base, "utm": dict(UTM)})
    assert accepte["ok"] is True and accepte["resultat"]["lead"]["utm"] == UTM
    assert accepte["resultat"]["utm"] == {"statut": "porte_par_le_lead"}


def test_un_utm_qui_n_est_ni_objet_ni_null_est_refuse_par_le_schema():
    reponse = executer(_outil(), {
        "canal": "formulaire", "expediteur": ADRESSE, "message_id": "F-1", "recu_le": _a(0), "texte": DEMANDE,
        "utm": "utm_source=google"})
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _lignes() == []


# =====================================================================================================================
# 9. Le bus : le lead publié porte le `utm`, un refus ne publie rien, un rejeu ne publie pas deux fois
# =====================================================================================================================
@pytest.fixture
def capacites(tmp_path, monkeypatch):
    """Base migrée, registre de production de M1, et le vrai manifeste de M1 par `Capacites` (comme le serveur MCP)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    utiliser_stockage_durable()
    departement = lire_manifeste(M1)
    yield Capacites({departement.id: departement}, stockage.transaction, memoire=False)
    reinitialiser_registre()
    stockage.liberer()


def _evenements_de_lead() -> int:
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")).scalar_one()


def test_le_lead_publie_au_bus_porte_le_utm_un_refus_ne_publie_rien_et_un_rejeu_non_plus(capacites):
    message = {"canal": "formulaire", "expediteur": ADRESSE, "message_id": "F-1", "recu_le": _a(0), "texte": DEMANDE}

    refuse = capacites.appeler("m1_recevoir_message_canal", {**message, "utm": {"utm_id": "x"}})
    assert refuse["ok"] is False and refuse["erreur"] == "refus_metier" and "REJ-UTM-INVALIDE" in refuse["details"]
    sms = capacites.appeler("m1_recevoir_message_canal", {
        **message, "canal": "sms", "expediteur": NUMERO, "utm": dict(UTM)})
    assert sms["ok"] is False and "REJ-UTM-CANAL-SANS-SENS" in sms["details"]
    with stockage.transaction():
        assert _obtenir_registre().lire() == []
    assert _evenements_de_lead() == 0

    accepte = capacites.appeler("m1_recevoir_message_canal", {**message, "utm": dict(UTM)})
    assert accepte["ok"] is True and "statut" not in accepte, accepte
    lead = accepte["resultat"]["lead"]
    assert lead["utm"] == UTM and accepte["resultat"]["utm"] == {"statut": "porte_par_le_lead"}
    with stockage.transaction():
        charge = evenements.charge_publiee("m1.lead_qualifie", f"m1-lead-qualifie-{lead['lead_id']}")
    assert charge == {"lead": lead, "horodatage": _a(0), "signal_id": "formulaire:F-1"}
    assert charge["lead"]["utm"] == UTM and charge["lead"]["canal"] == "formulaire"

    rejeu = capacites.appeler("m1_recevoir_message_canal", {**message, "utm": dict(UTM)})
    assert rejeu["ok"] is True and rejeu["resultat"]["doublon"] is True
    assert _evenements_de_lead() == 1
