"""Score de conformité d'un texte au profil de marque v2 : verdict, sous-scores, raisons ; la porte binaire reste la
loi."""

from __future__ import annotations

import copy

import pytest
from m7_marketing.brand import conformite, profil_v2
from m7_marketing.usine import controle_texte, plateformes

from opsys import garde_fou_texte as socle

FICTIF = True
FB = plateformes.plateforme("facebook")
GOOGLE = plateformes.plateforme("fiche_google")
PRIVE = plateformes.plateforme("demande_temoignage")
BON = (
    "Chantier terminé à Repentigny : gouttières et descentes. Vous avez un projet semblable ? "
    "Écrivez-nous pour demander une soumission, nous vous répondrons avec plaisir."
)


def evaluer(texte, profil, plateforme=FB):
    return conformite.evaluer(texte, profil, plateforme)


def codes(evaluation):
    return [r["code"] for r in evaluation.rapport["raisons"]]


def test_un_texte_conforme_passe_avec_un_score_complet_et_dit_ce_qu_il_n_a_pas_evalue(v2):
    e = evaluer(BON, v2)
    assert e.rapport["verdict"] == "conforme" and e.violations == () and not e.refuse
    assert e.rapport["score_global"] == 100
    assert e.rapport["non_evaluables"] == ["mentions_requises"]  # aucune mention déclarée : pas de note par défaut
    assert e.rapport["sous_scores"]["mentions_requises"] == {
        **e.rapport["sous_scores"]["mentions_requises"],
        "score": None,
        "evalue": False,
    }
    assert e.rapport["raisons"] == [] and e.rapport["violations_porte_binaire"] == []


@pytest.mark.parametrize(
    "texte",
    [
        "Nos prix sont pas cher pour la région.",
        "Des travaux PAS CHER pour tous.",
        "Offre pas chère cette saison.",
        "Du matériel bas de gamme à éviter.",
        "On fait du pàs chér, vraiment.",
        "pas chеr ici",  # lettre cyrillique « е » qui imite le latin
        "pas​ cher dans la région",  # espace de largeur nulle
    ],
)
def test_un_mot_interdit_est_refuse_malgre_la_casse_les_accents_le_pluriel_et_les_lettres_imitees(v2, texte):
    e = evaluer(texte, v2)
    assert e.rapport["verdict"] == "refuse"
    assert conformite.REJ_MOT_INTERDIT in codes(e)
    assert e.rapport["sous_scores"]["mots_interdits"]["score"] == 0
    assert e.rapport["sous_scores"]["mots_interdits"]["bloquante"] is True


def test_un_mot_interdit_est_cherche_comme_mot_entier(v2):
    v2["mots_interdits"] = ["art", "pas cher"]
    assert evaluer("Un artisan soigné de la région. " + BON, v2).rapport["verdict"] == "conforme"
    assert conformite.REJ_MOT_INTERDIT in codes(evaluer("De l'art de rénover. " + BON, v2))


def test_un_message_interdit_est_refuse_et_nomme(v2):
    e = evaluer("Chantier terminé : vous ne trouverez pas mieux ailleurs.", v2)
    assert conformite.REJ_MESSAGE_INTERDIT in codes(e)
    assert e.rapport["sous_scores"]["messages_interdits"]["score"] == 0
    assert any("vous ne trouverez pas mieux" in r for r in e.rapport["sous_scores"]["messages_interdits"]["raisons"])


def test_une_garantie_non_validee_est_refusee_par_la_porte_binaire_ET_par_l_enonce_du_profil(v2):
    e = evaluer("Chantier terminé. Garantie de dix ans sur tout le revêtement. Écrivez-nous.", v2)
    assert e.rapport["verdict"] == "refuse"
    assert socle.FAMILLES[socle.GARANTIE_NON_VALIDEE].regle in codes(e)
    assert conformite.REJ_PROMESSE_NON_VALIDEE in codes(e)
    assert e.rapport["sous_scores"]["promesses_non_validees"]["score"] == 0


def test_une_garantie_validee_mot_pour_mot_passe(v2):
    e = evaluer("Chantier terminé à Repentigny. Garantie légale de qualité des travaux. Écrivez-nous.", v2)
    assert e.rapport["verdict"] == "conforme", e.rapport["raisons"]


def test_un_enonce_positif_non_valide_ne_peut_pas_etre_cite_mais_le_valide_le_peut(v2):
    cite_non_valide = evaluer("Une équipe locale qui connaît la région vous répond vite.", v2)  # avantages : à valider
    assert conformite.REJ_PROMESSE_NON_VALIDEE in codes(cite_non_valide) and cite_non_valide.refuse
    cite_valide = evaluer("Un chantier propre et bien expliqué du début à la fin, voilà notre approche.", v2)
    assert conformite.REJ_PROMESSE_NON_VALIDEE not in codes(cite_valide)  # promesse validée par le propriétaire
    # retirer la validation rend l'énoncé citable… interdit
    v2["validation_champs"].pop("promesse")
    assert evaluer("Un chantier propre et bien expliqué du début à la fin, voilà notre approche.", v2).refuse


def test_le_nom_et_l_accroche_du_profil_ne_comptent_pas_comme_un_enonce_non_valide(v2):
    v2["promesse"] = v2["tagline"]
    v2["validation_champs"].pop("promesse")
    e = evaluer(f"{v2['tagline']}. Écrivez-nous pour demander une soumission.", v2)
    assert conformite.REJ_PROMESSE_NON_VALIDEE not in codes(e)


@pytest.mark.parametrize(
    ("texte", "regle"),
    [
        ("Installation dès 500 $ seulement.", "REJ-PRIX"),
        ("Une soumission gratuite pour tous.", "REJ-PRIX"),
        ("Livraison de 12 pieds de gouttière.", "REJ-CHIFFRE-NON-SOURCE"),
        ("Travaux terminés dans 3 jours.", "REJ-CHIFFRE-NON-SOURCE"),
        ("Prêt demain matin.", "REJ-PROMESSE-DE-DATE"),
    ],
)
def test_prix_chiffres_et_delais_inventes_sont_refuses_par_la_porte_binaire_et_expliques(v2, texte, regle):
    e = evaluer(texte, v2)
    assert e.rapport["verdict"] == "refuse" and regle in codes(e)
    assert e.rapport["sous_scores"]["prix_et_chiffres"]["score"] == 0
    assert e.rapport["sous_scores"]["prix_et_chiffres"]["bloquante"] is True
    assert regle in [v["regle"] for v in e.rapport["violations_porte_binaire"]]


def test_exageration_est_une_promesse_non_validee(v2):
    e = evaluer("Le meilleur toit de la région, parfait.", v2)
    assert "REJ-EXAGERATION" in codes(e) and e.rapport["sous_scores"]["promesses_non_validees"]["score"] == 0


@pytest.mark.parametrize(
    ("texte", "famille"),
    [
        ("Écrivez à jean@example.test", "coordonnees"),
        ("Chez 123 rue des Érables à Repentigny", "adresse"),
        ("Voir https://exemple.test/x", "lien"),
    ],
)
def test_confidentialite_est_une_dimension_expliquee(v2, texte, famille):
    e = evaluer(texte, v2)
    assert e.rapport["verdict"] == "refuse"
    assert e.rapport["sous_scores"]["confidentialite"]["score"] == 0
    assert any(r["dimension"] == "confidentialite" for r in e.rapport["raisons"])


def test_ton_vouvoiement_declare_refuse_le_tutoiement_fort_et_signale_le_faible(v2):
    fort = evaluer("Chantier terminé à Repentigny. Tu peux nous écrire pour une soumission, toi aussi.", v2)
    assert conformite.REJ_TON in codes(fort) and fort.refuse
    assert fort.rapport["sous_scores"]["ton"]["score"] < 100
    faible = evaluer("Chantier terminé à Repentigny. Écrivez-nous pour demander une soumission, c'est ton droit.", v2)
    assert conformite.RES_TON in codes(faible) and not faible.refuse
    assert faible.rapport["verdict"] == "conforme_avec_reserves"
    assert faible.rapport["sous_scores"]["ton"]["score"] < 100


def test_ton_tutoiement_declare_refuse_le_vouvoiement(v2):
    v2["voix"] = {"adresse": "tu"}
    e = evaluer("Chantier terminé. Écris-nous pour une soumission, vous serez bien servis.", v2)
    assert conformite.REJ_TON in codes(e) and e.refuse
    assert not evaluer("Chantier terminé. Écris-nous pour une soumission, tu seras bien servi.", v2).refuse


def test_exclamations_majuscules_et_emojis_sont_des_reserves_pas_des_refus(v2):
    e = evaluer("CHANTIER TERMINÉ À REPENTIGNY ! ÉCRIVEZ-NOUS POUR UNE SOUMISSION ! 😀😀", v2)
    assert not e.refuse and e.rapport["verdict"] == "conforme_avec_reserves"
    messages = " ".join(r["detail"] for r in e.rapport["raisons"] if r["dimension"] == "ton")
    assert "points d'exclamation" in messages and "majuscules" in messages and "émojis" in messages
    assert e.rapport["sous_scores"]["ton"]["score"] == 25  # 1 critère respecté (adresse) sur 4


def test_les_majuscules_ne_comptent_qu_avec_assez_de_lettres(v2):
    assert evaluer("OK", v2).rapport["sous_scores"]["ton"]["score"] == 100


def test_longueur_maximale_declaree_bloque_et_minimale_est_une_reserve(v2):
    v2["style_plateforme"] = {"facebook": {"longueur_min": 120, "longueur_max": 150}}
    court = evaluer("Chantier terminé à Repentigny. Écrivez-nous.", v2)
    assert not court.refuse and conformite.RES_LONGUEUR_COURTE in codes(court)
    assert 0 < court.rapport["sous_scores"]["longueur_plateforme"]["score"] < 100
    long = evaluer("Chantier terminé à Repentigny. " + "Écrivez-nous pour une soumission. " * 6, v2)
    assert long.refuse and conformite.REJ_LONGUEUR in codes(long)
    assert long.rapport["sous_scores"]["longueur_plateforme"]["score"] == 0


def test_le_plafond_de_la_plateforme_reste_la_loi(v2):
    e = evaluer("a " * 1000, v2)
    assert "REJ-LONGUEUR" in codes(e) and e.refuse
    assert e.rapport["sous_scores"]["longueur_plateforme"]["score"] == 0


def test_style_plateforme_mots_clics_et_emojis_sont_des_reserves(v2):
    e = evaluer(BON + " #un #deux #trois #quatre", v2)
    assert not e.refuse and conformite.RES_STYLE in codes(e)
    assert e.rapport["sous_scores"]["style_plateforme"]["score"] == 50  # emojis respectés, mots-clics non
    assert evaluer(BON, v2, GOOGLE).rapport["sous_scores"]["style_plateforme"]["score"] is None


def test_mentions_requises_absentes_bloquent_et_presentes_passent(v2):
    v2["mentions_requises"] = ["Licence RBQ 0000-0000-00 (fictive)"]
    absent = evaluer(BON, v2)
    assert absent.refuse and conformite.REJ_MENTION in codes(absent)
    assert absent.rapport["sous_scores"]["mentions_requises"]["score"] == 0
    present = evaluer(BON + "\n\nLicence RBQ 0000-0000-00 (fictive)", v2)
    assert present.rapport["verdict"] == "conforme", present.rapport["raisons"]
    assert present.rapport["sous_scores"]["mentions_requises"]["score"] == 100


def test_une_mention_validee_ne_declenche_pas_la_porte_binaire_mais_une_non_validee_oui(v2):
    mention = "Licence RBQ 514-555-0199 (fictive)"
    v2["mentions_requises"] = [mention]
    texte = f"{BON}\n\n{mention}"
    non_validee = evaluer(texte, v2)
    assert non_validee.refuse  # un numéro non validé ressemble à une coordonnée : la porte binaire parle
    v2["validation_champs"]["mentions_requises"] = {"statut": "valide", "par": "nathan", "le": "2026-11-02"}
    validee = evaluer(texte, v2)
    assert validee.rapport["verdict"] == "conforme", validee.rapport["raisons"]


def test_une_mention_requise_ne_s_applique_pas_a_un_message_prive(v2):
    v2["mentions_requises"] = ["Licence RBQ (fictive)"]
    e = evaluer("Bonjour, merci d'avoir choisi notre équipe. Pourriez-vous nous écrire quelques mots ?", v2, PRIVE)
    assert conformite.REJ_MENTION not in codes(e)
    assert e.rapport["sous_scores"]["mentions_requises"]["score"] is None


def test_un_profil_v1_note_la_porte_binaire_et_dit_les_dimensions_non_evaluables(v1):
    e = evaluer(BON, v1)
    assert e.rapport["verdict"] == "conforme" and e.rapport["profil"]["version"] == "v1"
    assert set(e.rapport["non_evaluables"]) == {
        "mots_interdits",
        "messages_interdits",
        "ton",
        "style_plateforme",
        "mentions_requises",
    }
    assert e.rapport["score_global"] == 100  # moyenne des seules dimensions évaluées
    assert e.rapport["profil"]["a_fournir"]
    assert evaluer("Prix : 500 $", v1).refuse


@pytest.mark.parametrize("profil", [None, {}, {"name": "  "}, {"name": 12}, "texte", []])
def test_profil_absent_ou_invalide_est_fail_closed_sans_score(profil):
    e = conformite.evaluer(BON, profil, FB)
    assert e.rapport["statut"] == "profil_marque_non_configure" and e.rapport["verdict"] == "refuse"
    assert e.rapport["score_global"] is None and e.rapport["sous_scores"] == {}
    assert e.rapport["raisons"][0]["code"] == "REJ-PROFIL-MARQUE-NON-CONFIGURE"
    assert e.violations == ()  # rien à retirer d'un texte : c'est le profil qui manque


def test_texte_vide_est_refuse_et_non_chaine_est_une_erreur_de_programmation(v2):
    assert evaluer("   ", v2).refuse
    with pytest.raises(TypeError):
        evaluer(None, v2)  # type: ignore[arg-type]


def test_les_poids_sont_fixes_totalisent_cent_et_chaque_famille_du_socle_est_expliquee():
    assert sum(conformite.POIDS.values()) == 100 and len(conformite.POIDS) == len(conformite.DIMENSIONS)
    familles = {f.nom for f in controle_texte.PROFIL_TEXTE_PUBLIC.familles}
    assert familles <= set(conformite._FAMILLE_VERS_DIMENSION)  # noqa: SLF001 — aucune famille sans dimension
    assert set(conformite._FAMILLE_VERS_DIMENSION.values()) <= set(conformite.POIDS)  # noqa: SLF001


CORPUS = [
    BON,
    "Chantier terminé à Repentigny. Écrivez-nous pour demander une soumission.",
    "Pas cher, pas cher, pas cher !",
    "Prix spécial dès 99 $ !",
    "Garantie à vie sur tout.",
    "Garantie de dix ans sur tout le revêtement, demandez votre soumission.",
    "Le meilleur de la région !",
    "Tu veux une soumission ? Écris-nous.",
    "Appelez le 514-555-0100 ou écrivez à nous@example.test",
    "Au 123 rue des Érables à Repentigny.",
    "Voir https://exemple.test/promo",
    "Travaux livrés demain, 100 % garantis.",
    "Merci à toute l'équipe pour ce beau chantier.",
    "bonjour " * 100,
    "",
    "OK",
    "CHANTIER TERMINÉ !!! ÉCRIVEZ-NOUS !!! 😀😀😀",
    "Un chantier propre et bien expliqué du début à la fin.",
    "Une équipe locale qui connaît la région.",
    "Nos clients nous recommandent à leurs voisins.",
    "vous ne trouverez pas mieux ailleurs",
    "Garantie légale de qualité des travaux. Écrivez-nous.",
    "Revêtement installé à Terrebonne. Vous souhaitez une soumission ? Écrivez-nous.",
    "Gouttières posées, nettoyage complet du terrain. Contactez l'équipe pour une soumission.",
    "Notre équipe termine un projet de toiture. Vous avez un projet semblable ? Écrivez-nous. #toiture #qc #pme #x",
    "A" * 40,
    "ÉCRIVEZ-NOUS POUR UNE SOUMISSION MAINTENANT",
    "On adore ton projet, t'inquiète pas.",
    "Merci de votre confiance, à bientôt.",
    "Comparez avec nos concurrents : moins cher ailleurs ? Non.",
]


@pytest.mark.parametrize("texte", CORPUS)
def test_invariants_sur_le_corpus(v2, texte):
    e = evaluer(texte, v2)
    e2 = evaluer(texte, copy.deepcopy(v2))
    assert e.rapport == e2.rapport and e.violations == e2.violations  # déterministe et rejouable
    rapport = e.rapport
    binaire = controle_texte.controler_texte(texte, conformite.contexte_pour_profil(v2, FB.longueur_max))
    if binaire:  # la porte binaire est la loi : si elle refuse, le verdict refuse
        assert rapport["verdict"] == "refuse" and e.refuse
    assert (rapport["verdict"] == "refuse") == e.refuse == bool(e.violations)
    assert all(
        isinstance(s["score"], int) and 0 <= s["score"] <= 100
        for s in rapport["sous_scores"].values()
        if s["score"] is not None
    )
    for nom, sous in rapport["sous_scores"].items():
        if sous["score"] is not None and sous["score"] < 100:  # jamais un score opaque
            assert sous["raisons"], f"{nom} < 100 sans raison"
        assert (sous["score"] is None) == (nom in rapport["non_evaluables"])
        assert sous["bloquante"] == any(r["bloquante"] and r["dimension"] == nom for r in rapport["raisons"])
    assert all(r["dimension"] in conformite.POIDS for r in rapport["raisons"])
    evalues = [(n, s["score"]) for n, s in rapport["sous_scores"].items() if s["score"] is not None]
    total = sum(conformite.POIDS[n] for n, _ in evalues)
    attendu = (2 * sum(conformite.POIDS[n] * s for n, s in evalues) + total) // (2 * total)
    assert rapport["score_global"] == attendu  # recalculable à la main
    if rapport["verdict"] == "conforme":
        assert rapport["raisons"] == []
    if rapport["verdict"] == "refuse":
        assert any(r["bloquante"] for r in rapport["raisons"])


def test_aucun_texte_de_la_porte_binaire_n_est_accepte_par_le_score(v2):
    """Quel que soit le profil, un texte refusé par la porte binaire ne passe jamais : essai sur des profils
    dépouillés."""
    for profil in (
        copy.deepcopy(v2),
        {**v2, "voix": {"adresse": "tu"}},
        {k: v for k, v in v2.items() if k in ("name", "tagline", "tone", "colors", "langue")},
    ):
        profil = profil_v2.normaliser(profil)
        for texte in CORPUS:
            if controle_texte.controler_texte(texte, conformite.contexte_pour_profil(profil, FB.longueur_max)):
                assert evaluer(texte, profil).refuse


def test_les_bornes_declarees_sont_inclusives_exactement_la_limite_passe(v2):
    """Une limite « au plus N » accepte N ; une limite « au moins N » accepte N (comparaisons non inversées)."""
    base = (
        "Chantier terminé à Repentigny. Écrivez-nous pour demander une soumission, nous vous répondrons avec plaisir."
    )
    assert len(base) >= 60
    un_point = evaluer(base + " Merci !", v2)
    assert un_point.rapport["verdict"] == "conforme", un_point.rapport["raisons"]  # 1 point d'exclamation, 1 au plus
    un_emoji = evaluer(base + " \U0001f600", v2)
    assert un_emoji.rapport["verdict"] == "conforme", un_emoji.rapport["raisons"]  # 1 émoji, 1 au plus
    trois = evaluer(base + " #un #deux #trois", v2)
    assert trois.rapport["sous_scores"]["style_plateforme"]["score"] == 100  # 3 mots-clics, 3 au plus
    v2["style_plateforme"] = {"facebook": {"longueur_min": len(base), "longueur_max": len(base)}}
    exact = evaluer(base, v2)
    assert (
        exact.rapport["verdict"] == "conforme" and exact.rapport["sous_scores"]["longueur_plateforme"]["score"] == 100
    )
    v2["voix"] = {"adresse": "vous", "majuscules_max_pct": 10}
    lettres = [c for c in "ABCDEFGHIJ" + "abcdefghijklmnopqrstuvwxyz" * 3 + "abcdefghijkl"]
    texte = "".join(lettres)  # 10 majuscules sur 100 lettres : 10 %, 10 % au plus
    assert sum(c.isalpha() for c in texte) == 100 and sum(c.isupper() for c in texte) == 10
    v2["style_plateforme"] = {}
    assert evaluer(texte, v2).rapport["sous_scores"]["ton"]["score"] == 100


def test_les_mots_interdits_sont_independants_des_messages_interdits(v2):
    v2["messages_interdits"] = []
    e = evaluer("Du travail pas cher. " + BON, v2)
    assert e.rapport["sous_scores"]["messages_interdits"]["score"] is None
    assert e.rapport["sous_scores"]["mots_interdits"]["score"] == 0
    v2["mots_interdits"] = []
    assert evaluer("Du travail pas cher. " + BON, v2).rapport["sous_scores"]["mots_interdits"]["score"] is None


def test_le_score_global_est_la_moyenne_ponderee_des_seules_dimensions_evaluees(v2):
    e = evaluer("Tu peux écrire. " + BON, v2)  # tutoiement fort : 1 critère de voix sur 4 manqué, le reste à 100
    evalues = {n: s["score"] for n, s in e.rapport["sous_scores"].items() if s["score"] is not None}
    assert evalues["ton"] == 75 and "mentions_requises" not in evalues
    assert sum(conformite.POIDS[n] for n in evalues) == 90
    assert e.rapport["score_global"] == 97  # (90 x 100 - 10 x 25) / 90 = 97,2


def test_le_score_global_arrondit_au_demi_superieur(v2):
    e = evaluer(BON, v2)
    assert e.rapport["score_global"] == 100
    # 0,5 arrondit vers le haut : poids 5 de longueur à 90 %, le reste à 100 -> 99,5 -> 100
    sous = {n: 100 for n in conformite.POIDS}
    sous["longueur_plateforme"] = 90
    total = sum(conformite.POIDS.values())
    assert (2 * sum(conformite.POIDS[n] * s for n, s in sous.items()) + total) // (2 * total) == 100


def test_le_verdict_refuse_vient_des_violations_et_pas_seulement_des_reserves(v2):
    assert evaluer("Tu veux ton devis ? " + BON, v2).refuse  # tutoiement fort : une violation
    pure = evaluer(BON + " #un #deux #trois #quatre", v2)
    assert pure.rapport["verdict"] == "conforme_avec_reserves" and not pure.refuse and pure.violations == ()
