"""PLAN T4.9 : les gabarits FIXES des relances passent le garde-fou de texte partagé, et un gabarit fautif serait
refusé.

Un texte destiné à un client ne porte ni nom, ni identifiant, ni prix, ni date, ni promesse (`opsys.garde_fou_texte`,
PLAN T4.17-c) ; M2 n'écrit pas ses propres motifs. Ce fichier prouve que chaque gabarit livré est propre, que chaque
couple (règle, canal) en a un, que chaque message porte la mention de retrait (STOP) et que le contrôle mord : un
gabarit altéré est refusé avec le code de sa règle. Le contrôle se fait aussi au chargement du département
(`verifier_gabarits`). """

from __future__ import annotations

import re

import pytest
from m2_revenue_crm import consentements, gabarits_relance, relances

from opsys import garde_fou_texte

FICTIF = True

MESSAGES = [
    (regle, canal) for regle in relances.REGLES for canal in consentements.CANAUX_ECRITS
]


def _copie_avec(regle: str, canal: str, **surcharges):
    gabarits = {cle: dict(modele) for cle, modele in gabarits_relance.GABARITS.items()}
    gabarits[(regle, canal)].update(surcharges)
    return gabarits


def test_il_y_a_un_gabarit_par_regle_et_par_canal_ni_un_de_plus_ni_un_de_moins():
    attendus = {(regle, canal) for regle in relances.REGLES for canal in consentements.CANAUX_RELANCE}
    assert set(gabarits_relance.GABARITS) == attendus
    assert len(attendus) == 6


def test_chaque_gabarit_porte_un_identifiant_une_version_et_sa_nature():
    identifiants = set()
    for (regle, canal), modele in gabarits_relance.GABARITS.items():
        assert isinstance(modele["id"], str) and modele["id"], (regle, canal)
        assert isinstance(modele["version"], int) and modele["version"] >= 1, (regle, canal)
        attendue = (
            gabarits_relance.NATURE_POINTS_D_APPEL if canal == consentements.CANAL_APPEL
            else gabarits_relance.NATURE_MESSAGE
        )
        assert modele["nature"] == attendue, (regle, canal)
        identifiants.add(modele["id"])
    assert len(identifiants) == 6, "un identifiant par gabarit : il nomme le texte qu'un audit relit"


def test_le_gabarit_d_un_couple_est_celui_de_ce_couple_et_un_couple_inconnu_n_en_a_pas():
    assert gabarits_relance.gabarit("relance_devis_sans_reponse", "sms")["id"] == "relance_devis_sms"
    assert gabarits_relance.gabarit("relance_lead_dormant", "appel")["id"] == "relance_dormant_appel"
    assert gabarits_relance.gabarit("relance_devis_sans_reponse", "whatsapp") is None
    assert gabarits_relance.gabarit("relance_inconnue", "sms") is None


def test_les_gabarits_livres_n_ont_aucun_defaut():
    assert gabarits_relance.verifier_gabarits(gabarits_relance.GABARITS) == []


@pytest.mark.parametrize(("regle", "canal"), MESSAGES)
def test_un_message_de_client_passe_le_garde_fou_de_texte_partage(regle, canal):
    texte = gabarits_relance.GABARITS[(regle, canal)]["texte"]
    assert garde_fou_texte.controler(texte, gabarits_relance.PROFIL_RELANCE_CLIENT) == ()


@pytest.mark.parametrize(("regle", "canal"), MESSAGES)
def test_un_message_de_client_ne_porte_aucun_chiffre_aucune_adresse_aucun_lien(regle, canal):
    texte = gabarits_relance.GABARITS[(regle, canal)]["texte"]
    assert not re.search(r"\d", texte), "ni prix, ni date, ni identifiant : aucun chiffre"
    assert not re.search(r"https?://|www\.|@", texte)


@pytest.mark.parametrize(("regle", "canal"), MESSAGES)
def test_un_message_de_client_porte_la_mention_de_retrait_que_m1_reconnait(regle, canal):
    texte = gabarits_relance.GABARITS[(regle, canal)]["texte"]
    assert "répondez STOP" in texte


@pytest.mark.parametrize("regle", list(relances.REGLES))
def test_un_sms_tient_dans_deux_segments(regle):
    assert len(gabarits_relance.GABARITS[(regle, "sms")]["texte"]) <= gabarits_relance.SMS_MAX_CARACTERES == 320


def test_les_points_d_appel_sont_une_consigne_interne_hors_du_garde_fou_des_textes_de_client():
    # « ni prix, ni date, ni garantie » est une consigne AU VENDEUR : le garde-fou d'un texte de client la refuserait.
    for regle in relances.REGLES:
        texte = gabarits_relance.GABARITS[(regle, "appel")]["texte"]
        assert "Ne rien promettre" in texte
        assert garde_fou_texte.controler(texte, gabarits_relance.PROFIL_RELANCE_CLIENT) != ()
    assert gabarits_relance.verifier_gabarits(gabarits_relance.GABARITS) == []


def test_le_profil_est_celui_d_un_texte_de_client_dans_l_ordre_du_catalogue():
    noms = [famille.nom for famille in gabarits_relance.PROFIL_RELANCE_CLIENT.familles]
    assert noms == [n for n in garde_fou_texte.FAMILLES if n in noms], "l'ordre est celui du catalogue du socle"
    assert set(noms) == {
        "texte_vide", "lien", "adresse", "coordonnees", "nom_client", "identifiant_interne", "prix_montant",
        "date_execution", "promesse_de_date", "exageration", "engagement", "aveu", "avis_legal",
    }
    assert gabarits_relance.PROFIL_RELANCE_CLIENT.nom == "m2_relance_client"


# ---------------------------------------------------------------------------------------------------------
# Le contrôle mord : un gabarit altéré est refusé avec le code de sa règle
# ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("ajout", "code"), [
    ("Le total est de 4 500 $.", "REJ-INTERDIT-PRIX"),
    ("Nous passerons demain.", "REJ-PROMESSE-DE-DATE"),
    ("Répondez d'ici vendredi.", "REJ-PROMESSE-DE-DATE"),
    ("Garantie de 10 ans.", "REJ-INTERDIT-ENGAGEMENT"),
    ("Nous nous engageons à livrer.", "REJ-INTERDIT-ENGAGEMENT"),
    ("Consultez votre avocat.", "REJ-INTERDIT-AVIS-LEGAL"),
    ("Nous sommes les meilleurs.", "REJ-EXAGERATION"),
    ("Écrivez à ecrire@exemple-fictif.test.", "REJ-COORDONNEES"),
    ("Appelez le 514-555-0142.", "REJ-COORDONNEES"),
    ("Voir https://exemple-fictif.test/soumission.", "REJ-LIEN"),
    ("Passez au 123 rue Principale.", "REJ-ADRESSE"),
])
def test_un_gabarit_de_message_altere_est_refuse_avec_le_code_de_sa_regle(ajout, code):
    for canal in consentements.CANAUX_ECRITS:
        original = gabarits_relance.GABARITS[("relance_devis_sans_reponse", canal)]["texte"]
        gabarits = _copie_avec("relance_devis_sans_reponse", canal, texte=f"{original} {ajout}")
        defauts = gabarits_relance.verifier_gabarits(gabarits)
        assert any(code in defaut and f"relance_devis_sans_reponse/{canal}" in defaut for defaut in defauts), (
            canal, defauts)


def test_un_nom_de_client_dans_un_gabarit_est_refuse():
    original = gabarits_relance.GABARITS[("relance_lead_dormant", "sms")]["texte"]
    avec_nom = original.replace("Bonjour,", "Bonjour Monsieur Tremblay,")
    gabarits = _copie_avec("relance_lead_dormant", "sms", texte=avec_nom)
    assert any("REJ-NOM-CLIENT" in defaut for defaut in gabarits_relance.verifier_gabarits(gabarits))


def test_un_message_sans_mention_de_retrait_est_refuse():
    original = gabarits_relance.GABARITS[("relance_devis_sans_reponse", "sms")]["texte"]
    sans_stop = original.replace(" Pour ne plus recevoir de messages, répondez STOP.", "")
    defauts = gabarits_relance.verifier_gabarits(_copie_avec("relance_devis_sans_reponse", "sms", texte=sans_stop))
    assert defauts == ["relance_devis_sans_reponse/sms : la mention de retrait (STOP) manque"]


def test_un_sms_de_320_caracteres_passe_et_un_de_321_est_refuse_avec_sa_taille():
    original = gabarits_relance.GABARITS[("relance_devis_sans_reponse", "sms")]["texte"]
    exact = original + " " + "a" * (gabarits_relance.SMS_MAX_CARACTERES - len(original) - 1)
    assert len(exact) == 320
    assert gabarits_relance.verifier_gabarits(_copie_avec("relance_devis_sans_reponse", "sms", texte=exact)) == []
    trop = exact + "a"
    defauts = gabarits_relance.verifier_gabarits(_copie_avec("relance_devis_sans_reponse", "sms", texte=trop))
    assert defauts == ["relance_devis_sans_reponse/sms : 321 caractères, 320 au plus"]


def test_la_limite_de_longueur_ne_vaut_que_pour_le_sms():
    original = gabarits_relance.GABARITS[("relance_devis_sans_reponse", "courriel")]["texte"]
    long = original + "\n\nMerci de votre confiance." * 20
    assert len(long) > gabarits_relance.SMS_MAX_CARACTERES
    assert gabarits_relance.verifier_gabarits(_copie_avec("relance_devis_sans_reponse", "courriel", texte=long)) == []


@pytest.mark.parametrize("texte", ["", "   ", None, 5])
def test_un_gabarit_sans_texte_est_refuse(texte):
    for canal in consentements.CANAUX_RELANCE:
        defauts = gabarits_relance.verifier_gabarits(_copie_avec("relance_devis_sans_reponse", canal, texte=texte))
        assert defauts == [f"relance_devis_sans_reponse/{canal} : texte vide"], (canal, defauts)


@pytest.mark.parametrize("surcharge", [{"id": ""}, {"id": None}, {"version": None}, {"version": "1"}])
def test_un_gabarit_sans_identifiant_ou_sans_version_est_refuse(surcharge):
    defauts = gabarits_relance.verifier_gabarits(_copie_avec("relance_lead_dormant", "appel", **surcharge))
    assert defauts == ["relance_lead_dormant/appel : identifiant ou version manquant"]


def test_les_defauts_sont_dits_dans_l_ordre_des_gabarits_avec_leur_cle():
    gabarits = _copie_avec("relance_lead_dormant", "sms", texte="Bonjour 4 500 $. STOP")
    gabarits[("relance_devis_sans_reponse", "sms")]["texte"] = ""
    defauts = gabarits_relance.verifier_gabarits(gabarits)
    assert [d.split(" : ")[0] for d in defauts] == ["relance_devis_sans_reponse/sms", "relance_lead_dormant/sms"]
