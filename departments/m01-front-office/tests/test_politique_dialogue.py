"""Politique de dialogue d'un appel (M1.2) : règles pures, ordre de préséance, seuils sans valeur par défaut.

Ces tests ne prouvent PAS la voix : ils exercent des décisions sur du texte et une confiance déjà mesurée. Le
vocabulaire
du propriétaire (plainte, danger) est ici un petit vocabulaire FICTIF ; les seuils (0,60 et deux échecs) sont ceux d'un
essai, pas ceux de Nathan.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest
from m1_front_office import garde_fou, plaintes, politique_dialogue
from m1_front_office.politique_dialogue import Action, EtatDialogue, Motif, SeuilsDialogue, decider

SEUILS = SeuilsDialogue(Decimal("0.60"), 2)
SIGNAUX = {
    "insatisfaction": ("déçu", "en colère", "inacceptable"),
    "degat": ("après vos travaux",),
    "garantie": ("sous garantie",),
    "avocat": ("avocat", "mise en demeure"),
    "securite": ("fumée", "danger", "fil électrique"),
}
BONNE = 0.9


def d(texte, confiance=BONNE, etat=None, *, humain=True, signaux=SIGNAUX, verdict=None):
    return decider(texte, confiance, etat or EtatDialogue(), seuils=SEUILS, signaux_profil=signaux,
                   verdict_profil=verdict, humain_disponible=humain)


# ================================================================================================ les seuils
def test_les_bornes_des_seuils_sont_incluses_la_ou_il_faut():
    assert SeuilsDialogue(1, 1).confiance_minimale == Decimal(1)           # tout exiger est permis
    assert SeuilsDialogue(Decimal("0.01"), 10).echecs_max == 10
    assert d("ok", 1.0, etat=None).action is Action.CONTINUER


def test_les_seuils_n_ont_aucune_valeur_par_defaut():
    with pytest.raises(TypeError):
        SeuilsDialogue()
    with pytest.raises(TypeError):
        SeuilsDialogue(Decimal("0.6"))


@pytest.mark.parametrize(("confiance", "echecs"), [
    (0, 2), (-0.1, 2), (1.01, 2), (True, 2), ("0.6", 2), (None, 2), (float("nan"), 2), (float("inf"), 2),
    (0.6, 0), (0.6, 11), (0.6, True), (0.6, 2.0), (0.6, "2"),
])
def test_des_seuils_invalides_sont_refuses(confiance, echecs):
    with pytest.raises(ValueError):
        SeuilsDialogue(confiance, echecs)


def test_la_politique_est_une_proposition_et_dit_qu_elle_ne_prouve_pas_la_voix():
    assert politique_dialogue.STATUT_POLITIQUE == "proposition"
    assert "aucune voix" in politique_dialogue.PORTEE and "FAIT_PROUVE" in politique_dialogue.PORTEE
    assert "NE PROUVE PAS LA VOIX" in politique_dialogue.__doc__


# ================================================================================================ chaque règle
@pytest.mark.parametrize(("texte", "action", "motif", "type_transfert"), [
    ("Il y a de la fumée près de la gouttière.", Action.TRANSFERER, Motif.URGENCE_SECURITE, "urgence"),
    ("Ça fait trois fois, je vais appeler mon avocat.", Action.TRANSFERER, Motif.MENACE_JURIDIQUE, "plainte"),
    ("Je suis très déçu de votre service.", Action.TRANSFERER, Motif.PLAINTE, "plainte"),
    ("C'est mal fait, après vos travaux ça coule.", Action.TRANSFERER, Motif.PLAINTE, "plainte"),
    ("Est-ce que je peux voir le contrat que j'ai signé?", Action.TRANSFERER, Motif.SUJET_LEGAL, "proprietaire"),
    ("Je veux savoir mes droits.", Action.TRANSFERER, Motif.SUJET_LEGAL, "proprietaire"),
    ("J'ai une question sur ma facture.", Action.TRANSFERER, Motif.SUJET_FINANCIER, "finance"),
    ("Je veux un remboursement.", Action.TRANSFERER, Motif.SUJET_FINANCIER, "finance"),
    ("Pouvez-vous me passer quelqu'un? Je veux parler à une personne.", Action.TRANSFERER, Motif.DEMANDE_HUMAIN,
     "ventes"),
    ("Passez-moi le patron, je veux parler au responsable.", Action.TRANSFERER, Motif.DEMANDE_HUMAIN, "ventes"),
])
def test_chaque_sujet_qui_exige_une_personne_ouvre_un_transfert_du_bon_type(texte, action, motif, type_transfert):
    r = d(texte)
    assert (r.action, r.motif, r.type_transfert) == (action, motif, type_transfert), r
    assert r.texte is not None and r.ouvre_une_tache


def test_une_question_de_prix_recoit_une_reponse_sure_et_l_appel_continue():
    r = d("Ça va coûter combien environ?")
    assert (r.action, r.motif, r.type_transfert) == (Action.REPONSE_SURE, Motif.QUESTION_PRIX, None)
    assert r.texte == politique_dialogue.TEXTES["prix"] and not r.ouvre_une_tache


def test_une_question_de_date_recoit_une_reponse_sure_et_l_appel_continue():
    r = d("Quand venez-vous pour la visite?")
    assert (r.action, r.motif) == (Action.REPONSE_SURE, Motif.QUESTION_DATE)
    assert r.texte == politique_dialogue.TEXTES["date"]


def test_un_tour_ordinaire_laisse_parler_le_repondant_et_remet_les_echecs_a_zero():
    r = d("J'aimerais une soumission pour mes gouttières.", etat=EtatDialogue(1))
    assert (r.action, r.motif, r.texte) == (Action.CONTINUER, Motif.ORDINAIRE, None)
    assert r.etat.echecs == 0


# ================================================================================================ la confiance
def test_une_confiance_sous_le_seuil_fait_redemander_au_premier_echec():
    r = d("mes gouttières", 0.59)
    assert (r.action, r.motif, r.etat.echecs) == (Action.REDEMANDER, Motif.FAIBLE_CONFIANCE, 1)
    assert r.texte == politique_dialogue.TEXTES["redemander"]


def test_la_confiance_egale_au_seuil_est_acceptee_et_juste_en_dessous_est_refusee():
    assert d("mes gouttières", 0.6).action is Action.CONTINUER
    assert d("mes gouttières", Decimal("0.5999")).action is Action.REDEMANDER


@pytest.mark.parametrize("confiance", [None, "0.95", True, False, float("nan"), float("inf"), -1, 2, [0.9]])
def test_une_confiance_absente_ou_invalide_est_traitee_comme_faible(confiance):
    r = d("mes gouttières", confiance)
    assert r.action is Action.REDEMANDER and r.motif is Motif.FAIBLE_CONFIANCE


def test_le_deuxieme_echec_consecutif_est_un_repli_vers_une_personne():
    premier = d("...", 0.3)
    deuxieme = d("...", 0.2, premier.etat)
    assert (deuxieme.action, deuxieme.motif, deuxieme.type_transfert) == (
        Action.TRANSFERER, Motif.ECHECS_REPETES, "ventes")


def test_le_repli_depend_du_nombre_d_echecs_autorise():
    seuils = SeuilsDialogue(Decimal("0.6"), 3)
    etat = EtatDialogue()
    for attendu in (Action.REDEMANDER, Action.REDEMANDER, Action.TRANSFERER):
        r = decider("...", 0.1, etat, seuils=seuils, signaux_profil=SIGNAUX, humain_disponible=True)
        assert r.action is attendu
        etat = r.etat


def test_un_tour_compris_entre_deux_echecs_remet_le_compte_a_zero():
    echec = d("...", 0.3)
    compris = d("mes gouttières", BONNE, echec.etat)
    nouveau_echec = d("...", 0.3, compris.etat)
    assert (compris.etat.echecs, nouveau_echec.action, nouveau_echec.etat.echecs) == (0, Action.REDEMANDER, 1)


@pytest.mark.parametrize("texte", [None, "", "   ", "\n"])
def test_le_silence_est_un_echec_de_comprehension_avec_sa_phrase(texte):
    r = d(texte)
    assert (r.action, r.motif, r.texte) == (Action.REDEMANDER, Motif.SILENCE, politique_dialogue.TEXTES["silence"])
    assert d(texte, etat=r.etat).motif is Motif.ECHECS_REPETES


def test_deux_silences_puis_une_personne_disponible_ou_une_messagerie():
    etat = d(None).etat
    assert d(None, etat=etat, humain=True).action is Action.TRANSFERER
    assert d(None, etat=etat, humain=False).action is Action.MESSAGERIE


def test_l_incomprehension_du_repondant_compte_comme_un_echec_a_la_suite_des_autres():
    r = politique_dialogue.echec_de_comprehension(EtatDialogue(1), SEUILS, True, Motif.INCOMPREHENSION)
    assert (r.action, r.motif) == (Action.TRANSFERER, Motif.ECHECS_REPETES)
    premier = politique_dialogue.echec_de_comprehension(EtatDialogue(), SEUILS, True, Motif.INCOMPREHENSION)
    assert (premier.action, premier.motif, premier.etat.echecs) == (Action.REDEMANDER, Motif.INCOMPREHENSION, 1)


# ================================================================================================ la préséance
# (mauvaise dimension)
def test_un_danger_est_reconnu_meme_quand_la_confiance_est_faible_ou_absente():
    for confiance in (0.05, None):
        r = d("fumée", confiance)
        assert (r.action, r.motif, r.type_transfert) == (Action.TRANSFERER, Motif.URGENCE_SECURITE, "urgence")
        assert r.etat.echecs == 0  # ce n'est pas un échec de compréhension


def test_la_colere_n_est_pas_une_faible_confiance_meme_quand_la_transcription_est_peu_sure():
    r = d("je suis en colère", 0.2)
    assert (r.action, r.motif, r.type_transfert) == (Action.TRANSFERER, Motif.PLAINTE, "plainte")
    assert r.etat.echecs == 0


def test_le_danger_prime_sur_la_plainte_la_menace_juridique_et_le_prix():
    r = d("Je suis déçu, mon avocat va appeler, il y a de la fumée, ça coûte combien?")
    assert (r.motif, r.type_transfert, r.categories) == (
        Motif.URGENCE_SECURITE, "urgence", ("insatisfaction", "avocat", "securite"))


def test_la_menace_juridique_prime_sur_la_plainte_et_se_distingue_d_elle():
    r = d("Je suis déçu, je vais envoyer une mise en demeure.")
    assert r.motif is Motif.MENACE_JURIDIQUE and "avocat" in r.categories


def test_une_plainte_prime_sur_un_sujet_financier_et_sur_une_demande_de_personne():
    r = d("Je suis déçu de ma facture, je veux parler à une personne.")
    assert (r.motif, r.type_transfert) == (Motif.PLAINTE, "plainte")


def test_un_sujet_legal_prime_sur_un_sujet_financier_qui_prime_sur_une_demande_de_personne():
    assert d("Mon contrat et ma facture.").motif is Motif.SUJET_LEGAL
    assert d("Ma facture, je veux parler à une personne.").motif is Motif.SUJET_FINANCIER


def test_un_sujet_qui_exige_une_personne_prime_sur_une_question_de_prix():
    assert d("Ça coûte combien? Je veux un remboursement.").motif is Motif.SUJET_FINANCIER
    assert d("Combien? Je veux parler à une personne.").motif is Motif.DEMANDE_HUMAIN


def test_une_question_de_prix_n_est_pas_un_sujet_financier():
    r = d("Combien ça coûte pour un remplacement?")
    assert r.motif is Motif.QUESTION_PRIX and r.type_transfert is None


def test_un_sujet_qui_exige_une_personne_est_reconnu_meme_a_faible_confiance():
    r = d("je veux parler à une personne", 0.1)
    assert (r.action, r.motif) == (Action.TRANSFERER, Motif.DEMANDE_HUMAIN)


def test_le_prix_a_faible_confiance_est_un_echec_pas_une_reponse():
    r = d("combien", 0.1)
    assert (r.action, r.motif) == (Action.REDEMANDER, Motif.FAIBLE_CONFIANCE)


# ================================================================================================ personne indisponible
@pytest.mark.parametrize("texte", [
    "Je suis déçu.", "Mon avocat va vous appeler.", "Ma facture.", "Mon contrat.", "Je veux parler à une personne.",
])
def test_sans_personne_disponible_la_messagerie_garde_le_type_de_la_tache(texte):
    avec, sans = d(texte, humain=True), d(texte, humain=False)
    assert avec.action is Action.TRANSFERER and sans.action is Action.MESSAGERIE
    assert sans.type_transfert == avec.type_transfert and sans.motif == avec.motif
    assert sans.texte == politique_dialogue.TEXTES["messagerie"]


def test_un_danger_n_attend_jamais_un_message_meme_sans_personne_disponible():
    r = d("de la fumée!", humain=False)
    assert (r.action, r.type_transfert, r.texte) == (Action.TRANSFERER, "urgence", politique_dialogue.TEXTES["urgence"])


# ================================================================================================ sans vocabulaire
# (fail-closed)
def test_sans_vocabulaire_du_proprietaire_ni_colere_ni_danger_ne_sont_reconnus_mais_le_reste_tient():
    """Limite assumée, la même que pour les messages écrits : M1 ne devine aucun mot. Le vocabulaire doit être adopté
    avant
    tout appel réel."""
    verdict = {"code": "REJ-SIGNAUX-PLAINTE-NON-CONFIGURES", "detail": "x"}
    assert d("je suis déçu, il y a de la fumée", signaux={}, verdict=verdict).action is Action.CONTINUER
    assert d("je veux parler à une personne", signaux={}).motif is Motif.DEMANDE_HUMAIN
    assert d("ma facture", signaux={}).motif is Motif.SUJET_FINANCIER
    assert d("...", 0.1, signaux={}).action is Action.REDEMANDER


# ================================================================================================ le lexique et les
# textes
@pytest.mark.parametrize(("texte", "sujets"), [
    ("J'ai besoin d'un remboursement pour ma facture", {"financier"}),
    ("Je voudrais voir le contrat", {"legal"}),
    ("Je veux parler à un responsable", {"humain"}),
    ("C'est quoi votre prix?", {"prix"}),
    ("Pouvez-vous venir lundi? Quand venez-vous?", {"date"}),
    ("Bonjour, c'est pour des travaux chez moi.", set()),
    ("", set()),
    (None, set()),
])
def test_le_lexique_generique_reconnait_ses_sujets(texte, sujets):
    assert politique_dialogue.sujets(texte) == frozenset(sujets)


def test_limites_connues_du_lexique_faux_positif_de_prix_et_ironie_non_vue():
    """Le code lit des mots, pas le sens : « combien de temps » sonne comme une question de prix (réponse sûre, sans
    conséquence) ; une phrase ironique sans mot du vocabulaire n'est pas vue."""
    assert politique_dialogue.sujets("Combien de temps ça prend?") == frozenset({"prix"})
    assert d("Bravo, encore un travail parfait... vraiment.").action is Action.CONTINUER


def test_le_lexique_est_generique_aucun_mot_de_metier():
    mots = " ".join(t for termes in politique_dialogue.LEXIQUE_V1.values() for t in termes)
    for interdit in ("gouttière", "soffite", "fascia", "revêtement", "toit", "bardeau", "rénovation"):
        assert interdit not in mots


def test_chaque_texte_fixe_de_la_politique_passe_le_garde_fou_des_interdits():
    for cle, texte in politique_dialogue.TEXTES.items():
        verdict = garde_fou.verifier_sortie(texte)
        assert verdict["code"] == "OK", (cle, verdict)
        assert not any(c.isdigit() for c in texte) and "$" not in texte, cle


def test_les_textes_de_danger_et_de_transfert_ne_promettent_ni_ne_conseillent():
    for cle in ("urgence", "transfert", "messagerie", "sur_repli"):
        texte = politique_dialogue.TEXTES[cle].lower()
        for mot in ("911", "évacu", "éloign", "appelez", "garantis", "promets", "désolé", "excuse", "rappellera",
                    "dans les", "bientôt", "immédiat"):
            assert mot not in texte, (cle, mot)


def test_le_catalogue_de_motifs_et_d_actions_est_ferme():
    assert {a.value for a in Action} == {"continuer", "reponse_sure", "redemander", "transferer", "messagerie"}
    assert len(Motif) == 13


def test_un_nombre_non_fini_n_est_jamais_une_confiance():
    assert politique_dialogue._decimal(math.nan) is None and politique_dialogue._decimal(Decimal("NaN")) is None
    assert politique_dialogue._decimal(0.75) == Decimal("0.75")


def test_les_categories_reconnues_sont_celles_du_module_des_plaintes():
    r = d("Mon avocat, la fumée")
    assert set(r.categories) <= set(plaintes.CATEGORIES)
