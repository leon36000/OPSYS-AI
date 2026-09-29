"""PLAN T4.4 : un verdict de qualification nomme CHAQUE champ manquant, et le cumul de la conversation couvre le
contact et l'urgence comme le service et la ville.

Registre en mémoire (voir `tests/test_canal_conversation.py` pour la base réelle et le bus). Numéros en 555, messages
fictifs.
"""

from __future__ import annotations

import datetime as dt

import pytest
from m1_front_office import contrats, conversation, garde_fou, qualification
from m1_front_office.outils import (
    _obtenir_registre,
    _traiter,
    recevoir_message_canal,
    reinitialiser_registre,
    traiter_demande_entrante,
)

from opsys import taxonomie

NUMERO = "+15145550142"
DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
ZONE = ["Laval", "Québec"]
CANAL = {"telephone": NUMERO}


def _a(minutes: float) -> str:
    return (DEBUT + dt.timedelta(minutes=minutes)).isoformat()


@pytest.fixture(autouse=True)
def _instance(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(ZONE)
    taxonomie.enregistrer_fenetre_conversation(30)
    reinitialiser_registre()
    yield
    reinitialiser_registre()


def _sms(texte: str, message_id: str, minutes: float = 0) -> dict:
    return recevoir_message_canal(
        canal="sms", expediteur=NUMERO, message_id=message_id, recu_le=_a(minutes), texte=texte)


# -- Le verdict de rejet nomme chaque champ manquant -------------------------------------------------------------------


@pytest.mark.parametrize(("contenu", "contact_canal", "manque", "fragments"), [
    ("Bonjour.", None, ["service", "ville", "contact"],
     ["aucun service", "aucune ville de la zone desservie", "aucun téléphone ni courriel"]),
    ("Bonjour.", CANAL, ["service", "ville"], ["aucun service", "aucune ville"]),
    ("Gouttières à Laval.", None, ["contact"], ["aucun téléphone ni courriel"]),
    ("Gouttières à Laval.", CANAL, [], []),
    ("Gouttières.", CANAL, ["ville"], ["aucune ville de la zone desservie"]),
    ("Gouttières à Rimouski.", CANAL, ["ville"], ["aucune ville de la zone desservie"]),
    ("À Laval, 514-555-0142.", None, ["service"], ["aucun service"]),
    ("Gouttières et soffite à Laval.", CANAL, ["service"], ["gouttieres, soffite_fascia", "demander lequel"]),
    ("Gouttières et soffite.", CANAL, ["service", "ville"], ["gouttieres, soffite_fascia", "aucune ville"]),
    ("[CONTENU_NON_FIABLE]", CANAL, ["service", "ville"], ["aucun service", "aucune ville"]),
    ("", None, ["service", "ville", "contact"], ["aucun service"]),
])
def test_le_rejet_nomme_chaque_champ_manquant_et_dit_quoi_demander(contenu, contact_canal, manque, fragments):
    resultat = qualification.qualifier(contenu, "texte", "conv-1", ZONE, contact_canal=contact_canal)
    if not manque:
        assert "verdict" not in resultat and "champs_manquants" not in resultat
        return
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"
    assert resultat["champs_manquants"] == manque
    detail = resultat["verdict"]["detail"]
    assert detail.startswith(f"champs manquants ({', '.join(manque)})")
    for fragment in fragments:
        assert fragment in detail
    for champ in ("service", "ville", "contact"):
        assert (f"{champ} : " in detail) == (champ in manque), f"{champ} nommé si et seulement s'il manque"


def test_un_lead_complet_ne_porte_ni_champ_manquant_ni_champ_de_plus():
    lead = qualification.qualifier("Gouttières à Laval, urgent.", "texte", "conv-1", ZONE, contact_canal=CANAL)
    assert "verdict" not in lead and "champs_manquants" not in lead
    contrats.valider_lead(lead)
    assert lead["contact"] == CANAL and lead["urgence_declaree"] is True


def test_le_diagnostic_dit_d_ou_vient_le_contact_et_ne_prend_le_texte_qu_a_defaut_du_canal():
    zone = ["Laval"]
    assert qualification.diagnostiquer("Gouttières à Laval.", zone)["contact"] is None
    assert qualification.diagnostiquer("Gouttières à Laval, 514-555-0142.", zone)["contact"] == "texte"
    assert qualification.diagnostiquer("Gouttières, jean@exemple.test.", zone)["contact"] == "texte"
    assert qualification.diagnostiquer("Gouttières à Laval.", zone, contact_canal=CANAL)["contact"] == "canal"
    assert qualification.diagnostiquer(
        "Gouttières, mon numéro : 450-555-0000.", zone, contact_canal=CANAL)["contact"] == "canal"


def test_le_contact_d_un_message_de_canal_reste_l_expediteur_meme_si_le_texte_en_donne_un_autre():
    reponse = _sms("Gouttières à Laval, appelez-moi au 450-555-0000.", "SM-1")
    assert reponse["lead"]["contact"] == CANAL, "l'identité vérifiée par la plateforme, seule"


# -- Sans fenêtre : le rejet nomme les champs dans la réponse ---------------------------------------------------------


def test_un_rejet_sans_fenetre_nomme_les_champs_dans_la_reponse_de_l_outil():
    taxonomie.fichier_profil().write_text(
        taxonomie.fichier_profil().read_text(encoding="utf-8").replace("fenetre_conversation_minutes: 30\n", ""),
        encoding="utf-8")
    reponse = traiter_demande_entrante(
        contenu_brut="Gouttières à Laval.", canal="texte", conversation_id="conv-7", signal_id="sig-7",
        horodatage=_a(0), zone_desservie=ZONE)
    assert reponse["decision"] == "DEMANDER_PRECISIONS" and reponse["champs_manquants"] == ["contact"]
    assert "contact : aucun téléphone ni courriel" in reponse["verdict_qualification"]["detail"]

    sans_ville = _sms("Gouttières.", "SM-2")
    assert sans_ville["conversation"]["mode"] == "message_par_message"
    assert sans_ville["champs_manquants"] == ["ville"] and "a_demander" not in sans_ville


# -- Un message sans ville rend « ville » manquante --------------------------------------------------------------------


def test_un_message_sans_ville_rend_la_ville_manquante_partout_dans_la_reponse():
    reponse = _sms("Bonjour, mes gouttières sont bouchées.", "SM-1")
    assert reponse["qualifie"] is False and reponse["decision"] == "DEMANDER_PRECISIONS"
    assert reponse["champs_manquants"] == ["ville"] and reponse["a_demander"] == ["ville"]
    assert reponse["conversation"]["connu"] == {
        "service": "gouttieres", "ville": None, "contact": "canal", "urgence_declaree": False}
    assert "ville : aucune ville de la zone desservie" in reponse["verdict_qualification"]["detail"]
    assert reponse["brouillon_reponse"] == "Bonjour, merci de votre message. Dans quelle ville se trouve la propriété?"


# -- Trois SMS successifs donnent un lead v2 complet ------------------------------------------------------------------


def test_trois_sms_successifs_donnent_un_lead_v2_complet_avec_urgence_et_contact_cumules():
    premier = _sms("Bonjour, j'ai un problème chez moi.", "SM-1", 0)
    assert premier["champs_manquants"] == ["service", "ville"]
    assert premier["conversation"]["connu"]["urgence_declaree"] is False

    second = _sms("Mes gouttières débordent, c'est urgent.", "SM-2", 3)
    assert second["qualifie"] is False and second["champs_manquants"] == ["ville"]
    assert second["conversation"]["connu"] == {
        "service": "gouttieres", "ville": None, "contact": "canal", "urgence_declaree": True}, "l'urgence est retenue"

    troisieme = _sms("Nous sommes à Laval.", "SM-3", 6)
    assert troisieme["qualifie"] is True and troisieme["decision"] == "TRANSMETTRE_M2"
    lead = troisieme["lead"]
    contrats.valider_lead(lead)
    assert lead["schema_version"] == 2
    assert (lead["service"], lead["ville"], lead["urgence_declaree"], lead["canal"], lead["source"]) == (
        "gouttieres", "Laval", True, "texte", "sms")
    assert lead["contact"] == CANAL
    assert troisieme["conversation"]["signaux"] == ["sms:SM-1", "sms:SM-2", "sms:SM-3"]
    assert troisieme["conversation"]["connu"] == {
        "service": "gouttieres", "ville": "Laval", "contact": "canal", "urgence_declaree": True}
    lignes = _obtenir_registre().lire()
    assert [ligne["type_entree"] for ligne in lignes].count("signal") == 3
    assert [ligne["type_entree"] for ligne in lignes].count("lead_emis") == 1
    assert _obtenir_registre().valider_chaine() == (True, None)


# -- Le contact aussi se cumule quand la plateforme ne le fournit pas -------------------------------------------------


def _traiter_sans_canal(texte: str, signal_id: str, minutes: float) -> dict:
    """La chaîne complète pour une demande dont le contact n'est pas celui d'un canal (voix transcrite, saisie)."""
    return _traiter(
        texte, "telephone", "conv-voix", signal_id, _a(minutes), ZONE, None, None, None, None,
        contact_canal=None, fenetre_minutes=30)


def test_le_contact_ecrit_dans_un_message_suivant_complete_le_lead():
    premier = _traiter_sans_canal("Mes gouttières fuient à Laval.", "sig-1", 0)
    assert premier["qualifie"] is False and premier["champs_manquants"] == ["contact"]
    assert premier["a_demander"] == ["contact"]
    assert premier["conversation"]["connu"] == {
        "service": "gouttieres", "ville": "Laval", "contact": None, "urgence_declaree": False}
    assert premier["brouillon_reponse"] == (
        "Bonjour, merci de votre message. À quel numéro de téléphone ou à quelle adresse courriel pouvons-nous "
        "vous joindre?")
    assert garde_fou.verifier_sortie(premier["brouillon_reponse"])["code"] == "OK"
    assert premier["envoye"] is False

    second = _traiter_sans_canal("Vous pouvez me joindre au 514-555-0142.", "sig-2", 2)
    assert second["qualifie"] is True
    lead = second["lead"]
    contrats.valider_lead(lead)
    assert lead["contact"] == {"telephone": "514-555-0142"}
    assert second["conversation"]["connu"]["contact"] == "texte"


def test_le_service_la_ville_et_le_contact_manquent_ensemble_et_le_brouillon_les_demande_tous():
    reponse = _traiter_sans_canal("Bonjour.", "sig-1", 0)
    assert reponse["champs_manquants"] == ["service", "ville", "contact"]
    assert reponse["brouillon_reponse"].startswith("Bonjour, merci de votre message. Quel service vous intéresse (")
    assert reponse["brouillon_reponse"].endswith(
        ", dans quelle ville se trouve la propriété, et à quel numéro de téléphone ou à quelle adresse courriel "
        "pouvons-nous vous joindre?")
    assert garde_fou.verifier_sortie(reponse["brouillon_reponse"])["code"] == "OK"


@pytest.mark.parametrize(("texte", "attendu"), [
    ("Gouttières à Laval.", "Bonjour, merci de votre message. À quel numéro de téléphone ou à quelle adresse "
                            "courriel pouvons-nous vous joindre?"),
    ("Gouttières, 514-555-0142.", "Bonjour, merci de votre message. Dans quelle ville se trouve la propriété?"),
    ("À Laval, 514-555-0142.", None),
])
def test_le_brouillon_ne_demande_que_ce_qui_manque(texte, attendu):
    reponse = _traiter_sans_canal(texte, "sig-1", 0)
    if attendu is None:
        assert reponse["brouillon_reponse"].startswith("Bonjour, merci de votre message. Quel service vous intéresse")
        assert "ville" not in reponse["brouillon_reponse"] and "numéro" not in reponse["brouillon_reponse"]
    else:
        assert reponse["brouillon_reponse"] == attendu


# -- L'urgence se cumule aussi après le lead ---------------------------------------------------------------------------


def test_l_urgence_dite_apres_le_lead_reste_signalee_tant_que_le_lead_ne_la_porte_pas():
    _sms("Mes gouttières fuient à Laval.", "SM-1", 0)
    merci = _sms("Merci beaucoup!", "SM-2", 2)
    assert merci["complement"]["urgence_declaree"] is False
    urgent = _sms("En fait, c'est urgent!", "SM-3", 4)
    assert urgent["complement"]["urgence_declaree"] is True
    encore = _sms("Merci encore.", "SM-4", 6)
    assert encore["complement"]["urgence_declaree"] is True, "l'urgence dite au message d'avant compte toujours"
    assert encore["conversation"]["connu"]["urgence_declaree"] is True
    assert encore["lead"]["urgence_declaree"] is False, "le lead transmis est gelé : il ne la porte pas"


def test_un_lead_deja_urgent_n_a_rien_a_signaler_de_plus():
    lead = _sms("C'est urgent, gouttières à Laval.", "SM-1", 0)["lead"]
    assert lead["urgence_declaree"] is True
    encore = _sms("Vraiment urgent!", "SM-2", 2)
    assert encore["complement"]["urgence_declaree"] is False, "le lead la porte déjà"
    assert encore["conversation"]["connu"]["urgence_declaree"] is True


def test_l_urgence_d_une_conversation_expiree_ne_se_cumule_pas_avec_la_suivante():
    _sms("Urgent, mes gouttières fuient!", "SM-1", 0)
    tard = _sms("À Laval.", "SM-2", 120)
    assert tard["conversation"]["connu"]["urgence_declaree"] is False


def test_la_conversation_rassemblee_est_celle_du_module_pur():
    """`connu` est un résumé du diagnostic : la même fonction pour les trois chemins de la réponse."""
    diagnostic = qualification.diagnostiquer("Gouttières à Laval, urgent.", ZONE, contact_canal=CANAL)
    assert conversation.connu(diagnostic) == {
        "service": "gouttieres", "ville": "Laval", "contact": "canal", "urgence_declaree": True}
    assert conversation.ce_qui_manque(diagnostic) == []
