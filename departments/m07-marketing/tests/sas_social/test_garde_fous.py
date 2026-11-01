"""Les contrôles du sas : texte, médias (décision r2 n°3), divulgation d'IA, annonces payantes, fenêtre, quota, niveau.

Chaque cas négatif nomme la règle violée ; chaque cas positif prouve qu'un contenu propre passe (pas de sur-refus).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, time, timedelta

import pytest
from fabriques_sociales import DEMAIN_10H, MAINTENANT, annonce, media_photo, media_video, publication
from m7_marketing.moderation.detection import Detection
from m7_marketing.moderation.floutage import DetectionTraitee, RapportPhoto
from m7_marketing.moderation.image import Boite
from m7_marketing.sas_social import garde_fous, modele, politique

FICTIF = True


def _pub(donnees):
    chargee, refus = modele.depuis_dict(donnees)
    assert chargee is not None, refus
    return chargee


def _contenu(declarations, donnees, pol=None):
    publication_ = _pub(donnees)
    return [
        (r["code"], r["chemin"])
        for r in garde_fous.controler_contenu(
            publication_, declarations[publication_.reseau], pol or politique.PolitiqueSas()
        )
    ]


def _codes(declarations, donnees, pol=None):
    return [code for code, _ in _contenu(declarations, donnees, pol)]


@pytest.mark.parametrize("reseau", ["gbp", "facebook", "instagram", "linkedin", "youtube", "tiktok"])
def test_une_publication_propre_passe_sur_chaque_reseau(declarations, reseau):
    assert _contenu(declarations, publication(reseau)) == []


# -- texte (garde-fou du socle) ----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("texte", "regle"),
    [
        ("", "REJ-TEXTE-VIDE"),
        ("Visitez https://exemple.example/soumission pour un devis.", "REJ-LIEN"),
        ("Chantier terminé au 12 rue des Érables à Laval.", "REJ-ADRESSE"),
        ("Écrivez-nous à contact@horizon.example pour en savoir plus.", "REJ-COORDONNEES"),
        ("Appelez-nous au 450 555 0142 pour une évaluation.", "REJ-COORDONNEES"),
        ("Merci à Mme Tremblay pour sa confiance.", "REJ-NOM-CLIENT"),
        ("Soumission gratuite et rabais de saison pour tous.", "REJ-PRIX"),
        ("Votre toit sera refait pour 5 000 $ seulement.", "REJ-PRIX"),
        ("Une toiture de 1200 pieds carrés posée en 3 jours.", "REJ-CHIFFRE-NON-SOURCE"),
        ("Tous nos travaux sont couverts par une garantie à vie.", "REJ-GARANTIE-NON-VALIDEE"),
        ("Nous commençons demain et finissons d'ici deux semaines.", "REJ-PROMESSE-DE-DATE"),
        ("Le meilleur couvreur de la région, numéro 1 au Québec.", "REJ-EXAGERATION"),
    ],
)
def test_le_texte_passe_par_le_garde_fou_du_socle_et_le_refus_nomme_la_regle(declarations, texte, regle):
    codes = _codes(declarations, publication("facebook", texte=texte))
    assert regle in codes, codes


def test_le_contexte_du_client_fait_refuser_ses_noms_et_ses_identifiants(declarations):
    from opsys import garde_fou_texte as socle

    pol = politique.PolitiqueSas(
        contexte_texte=socle.Contexte(noms_clients=("Gagnon",), identifiants=("chantier-777",))
    )
    assert "REJ-NOM-CLIENT" in _codes(declarations, publication("facebook", texte="Merci à la famille Gagnon."), pol)
    assert "REJ-IDENTIFIANT-INTERNE" in _codes(
        declarations, publication("facebook", texte="Dossier chantier-777 clos."), pol
    )


def test_un_titre_est_controle_comme_le_texte(declarations):
    assert "REJ-EXAGERATION" in _codes(declarations, publication("youtube", titre="Le meilleur toit au monde"))
    assert "REJ-PRIX" in _codes(declarations, publication("youtube", titre="Toiture à prix cassé : rabais"))


# -- limites de réseau lues sur la classe ------------------------------------------------------------------------------
def test_un_titre_est_exige_sur_youtube_et_interdit_ailleurs(declarations):
    assert "REJ-SOCIAL-TITRE" in _codes(declarations, publication("youtube", titre=None))
    assert "REJ-SOCIAL-TITRE" in _codes(declarations, publication("facebook", titre="Un titre"))
    assert "REJ-SOCIAL-TITRE-LONG" in _codes(declarations, publication("youtube", titre="T" * 101))
    assert _contenu(declarations, publication("youtube", titre="T" * 100)) == []


def test_les_mots_clics_sont_comptes_sur_instagram(declarations):
    trente = " ".join(f"#toit{chr(97 + i % 26)}{chr(97 + i // 26)}" for i in range(30))
    assert _contenu(declarations, publication("instagram", texte="Toiture neuve. " + trente)) == []
    trente_et_un = trente + " #encoreun"
    assert "REJ-SOCIAL-HASHTAGS" in _codes(
        declarations, publication("instagram", texte="Toiture neuve. " + trente_et_un)
    )


@pytest.mark.parametrize(
    ("reseau", "medias", "code"),
    [
        ("instagram", [], "REJ-SOCIAL-MEDIAS-NOMBRE"),
        ("youtube", [], "REJ-SOCIAL-MEDIAS-NOMBRE"),
        ("gbp", [media_photo("p1"), media_photo("p2")], "REJ-SOCIAL-MEDIAS-NOMBRE"),
        ("facebook", [media_photo(f"p{i}") for i in range(11)], "REJ-SOCIAL-MEDIAS-NOMBRE"),
        ("instagram", [media_photo("p1", format_="png")], "REJ-SOCIAL-MEDIA-FORMAT"),
        ("gbp", [media_photo("p1", format_="gif")], "REJ-SOCIAL-MEDIA-FORMAT"),
        ("youtube", [media_video("v1", format_="webm")], "REJ-SOCIAL-MEDIA-FORMAT"),
        ("facebook", [media_photo("p1", octets=10 * 1024 * 1024 + 1)], "REJ-SOCIAL-MEDIA-TAILLE"),
        ("tiktok", [media_video("v1", duree_s=601)], "REJ-SOCIAL-MEDIA-DUREE"),
        ("facebook", [media_photo("p1"), media_video("v1")], "REJ-SOCIAL-MEDIAS-MELANGE"),
    ],
)
def test_les_limites_de_medias_de_la_classe_sont_appliquees(declarations, reseau, medias, code):
    assert code in _codes(declarations, publication(reseau, medias=medias))


def test_instagram_accepte_le_melange_d_images_et_de_video_que_facebook_refuse(declarations):
    medias = [media_photo("p1"), media_video("v1")]
    assert "REJ-SOCIAL-MEDIAS-MELANGE" not in _codes(declarations, publication("instagram", medias=medias))


# -- décision r2 n°3 : aucun texte, logo ou mention produits par un modèle d'image
# -----------------------------------------
def test_un_media_genere_sans_composition_deterministe_est_refuse(declarations):
    generee = media_photo(origine="genere_non_compose", ia_generee=True, realiste=False)
    resultat = _contenu(declarations, publication("facebook", medias=[generee]))
    assert ("REJ-SOCIAL-MEDIA-GENERE-NON-COMPOSE", "$.medias[0].origine") in resultat


def test_une_composition_deterministe_exige_un_controle_ocr_conforme(declarations):
    composee = {"origine": "composition_deterministe", "ia_generee": True}
    assert "REJ-SOCIAL-MEDIA-OCR-NON-CONFORME" in _codes(
        declarations, publication("facebook", medias=[media_photo(controle_ocr="non_fait", **composee)])
    )
    assert "REJ-SOCIAL-MEDIA-OCR-NON-CONFORME" in _codes(
        declarations, publication("facebook", medias=[media_photo(controle_ocr="non_requis", **composee)])
    )
    assert (
        _codes(declarations, publication("facebook", medias=[media_photo(controle_ocr="conforme", **composee)])) == []
    )


def test_une_incoherence_d_origine_et_d_ia_est_refusee(declarations):
    assert "REJ-SOCIAL-MEDIA-IA-INCOHERENTE" in _codes(
        declarations, publication("facebook", medias=[media_photo(ia_generee=True)])
    )
    assert "REJ-SOCIAL-MEDIA-IA-INCOHERENTE" in _codes(
        declarations, publication("facebook", medias=[media_photo(origine="genere_non_compose", ia_generee=False)])
    )


@pytest.mark.parametrize("etat", ["revue_requise", "non_verifiee"])
def test_un_media_non_modere_ne_part_pas(declarations, etat):
    assert "REJ-SOCIAL-MEDIA-MODERATION" in _codes(
        declarations, publication("facebook", medias=[media_photo(moderation=etat)])
    )


def test_la_moderation_vient_du_rapport_de_floutage_et_un_doute_exige_la_revue_humaine():
    boite = Boite(0, 0, 4, 4)
    doute = RapportPhoto("p1", (DetectionTraitee(Detection("visage", boite, 0.4), True, True),), True, "doute")
    sur = RapportPhoto("p2", (DetectionTraitee(Detection("plaque", boite, 0.95), True, False),), False, None)
    assert garde_fous.moderation_depuis_rapport(doute, revue_humaine_faite=False) == "revue_requise"
    assert garde_fous.moderation_depuis_rapport(doute, revue_humaine_faite=True) == "verifiee"
    assert garde_fous.moderation_depuis_rapport(sur, revue_humaine_faite=False) == "verifiee"


# -- divulgation d'IA --------------------------------------------------------------------------------------------------
GENERE_REALISTE = {
    "origine": "composition_deterministe",
    "ia_generee": True,
    "realiste": True,
    "controle_ocr": "conforme",
}
DIVULGATION_OUI = {"texte_ia": True, "media_synthetique_realiste": True, "contenu_commercial": False}


def test_un_media_ia_realiste_impose_la_divulgation_et_elle_doit_etre_declaree(declarations):
    sans = publication("facebook", medias=[media_photo(**GENERE_REALISTE)])
    assert "REJ-SOCIAL-DIVULGATION-INCOHERENTE" in _codes(declarations, sans)
    avec = publication("facebook", medias=[media_photo(**GENERE_REALISTE)], divulgation=DIVULGATION_OUI)
    assert _contenu(declarations, avec) == []


def test_declarer_une_divulgation_que_les_medias_n_imposent_pas_est_aussi_incoherent(declarations):
    assert "REJ-SOCIAL-DIVULGATION-INCOHERENTE" in _codes(
        declarations, publication("facebook", divulgation=DIVULGATION_OUI)
    )


def test_un_reseau_sans_champ_de_divulgation_ne_publie_pas_un_media_ia_realiste(declarations):
    donnees = publication("linkedin", medias=[media_photo(**GENERE_REALISTE)], divulgation=DIVULGATION_OUI)
    assert declarations["linkedin"].LIMITES.etiquette_ia is False
    assert "REJ-SOCIAL-DIVULGATION-IMPOSSIBLE" in _codes(declarations, donnees)
    for reseau in ("facebook", "instagram", "youtube", "tiktok"):
        assert declarations[reseau].LIMITES.etiquette_ia is True


def test_un_media_ia_non_realiste_ne_declenche_pas_la_divulgation_mais_reste_marque(declarations):
    stylise = media_photo(**{**GENERE_REALISTE, "realiste": False})
    donnees = publication("facebook", medias=[stylise])
    assert _contenu(declarations, donnees) == []
    assert _pub(donnees).medias[0].ia_generee is True


# -- annonces payantes
# ---------------------------------------------------------------------------------------------------
def test_une_annonce_valide_passe_et_exige_n4(declarations):
    assert _contenu(declarations, annonce("facebook")) == []
    assert garde_fous.niveau_requis(_pub(annonce("facebook"))) == 4
    assert garde_fous.niveau_requis(_pub(publication("facebook"))) == 3


@pytest.mark.parametrize("reseau", ["gbp", "youtube"])
def test_un_reseau_sans_api_publicitaire_refuse_l_annonce(declarations, reseau):
    assert "REJ-SOCIAL-ANNONCE-NON-SUPPORTEE" in _codes(declarations, annonce(reseau))


def test_les_plafonds_de_budget_sont_durs(declarations):
    base = annonce("facebook")

    def refus_budget(budget):
        publication_ = _pub({**base, "budget": budget})
        return [
            (r["code"], r["chemin"])
            for r in garde_fous.controler_type(publication_, declarations["facebook"].LIMITES, politique.PolitiqueSas())
        ]

    # plafond QUOTIDIEN seul en cause : le total et la cohérence tiennent
    assert refus_budget({"montant_cents": 5001, "plafond_quotidien_cents": 5001, "duree_jours": 1}) == [
        ("REJ-SOCIAL-BUDGET-PLAFOND", "$.budget.plafond_quotidien_cents")
    ]
    assert refus_budget({"montant_cents": 5000, "plafond_quotidien_cents": 5000, "duree_jours": 1}) == []
    # plafond TOTAL seul en cause
    assert refus_budget({"montant_cents": 100_001, "plafond_quotidien_cents": 5000, "duree_jours": 30}) == [
        ("REJ-SOCIAL-BUDGET-PLAFOND", "$.budget.montant_cents")
    ]
    assert refus_budget({"montant_cents": 100_000, "plafond_quotidien_cents": 5000, "duree_jours": 30}) == []
    # incohérence seule en cause : le montant ne tient pas dans plafond x durée
    assert refus_budget({"montant_cents": 3001, "plafond_quotidien_cents": 1000, "duree_jours": 3}) == [
        ("REJ-SOCIAL-BUDGET-PLAFOND", "$.budget.montant_cents")
    ]
    assert refus_budget({"montant_cents": 3000, "plafond_quotidien_cents": 1000, "duree_jours": 3}) == []


def test_les_plafonds_viennent_de_la_politique(declarations):
    serree = politique.PolitiqueSas(plafond_budget_quotidien_cents=500, plafond_budget_total_cents=1000)
    assert "REJ-SOCIAL-BUDGET-PLAFOND" in _codes(declarations, annonce("facebook"), serree)


def test_une_annonce_sans_budget_et_une_publication_organique_avec_budget_sont_incoherentes(declarations):
    assert "REJ-SOCIAL-TYPE-INCOHERENT" in _codes(declarations, {**annonce("facebook"), "budget": None})
    organique_avec_budget = {
        **publication("facebook"),
        "budget": {"montant_cents": 100, "plafond_quotidien_cents": 100, "duree_jours": 1},
    }
    assert "REJ-SOCIAL-TYPE-INCOHERENT" in _codes(declarations, organique_avec_budget)


# -- options propres au réseau
# ------------------------------------------------------------------------------------------
def test_tiktok_exige_des_options_explicites_sans_valeur_par_defaut(declarations):
    sans = publication("tiktok", options={})
    assert _codes(declarations, sans).count("REJ-SOCIAL-OPTIONS-RESEAU") == 4
    inconnue = publication(
        "tiktok",
        options={"confidentialite": "SELF_ONLY", "commentaires": False, "duo": False, "stitch": False, "extra": 1},
    )
    assert "REJ-SOCIAL-OPTIONS-RESEAU" in _codes(declarations, inconnue)
    publique = publication(
        "tiktok",
        options={"confidentialite": "PUBLIC_TO_EVERYONE", "commentaires": False, "duo": False, "stitch": False},
    )
    assert "REJ-SOCIAL-OPTIONS-RESEAU" in _codes(declarations, publique), (
        "application non auditée : SELF_ONLY seulement"
    )
    inconnue_valeur = publication(
        "tiktok", options={"confidentialite": "TOUT_LE_MONDE", "commentaires": False, "duo": False, "stitch": False}
    )
    assert "REJ-SOCIAL-OPTIONS-RESEAU" in _codes(declarations, inconnue_valeur)
    non_booleen = publication(
        "tiktok", options={"confidentialite": "SELF_ONLY", "commentaires": "non", "duo": False, "stitch": False}
    )
    assert "REJ-SOCIAL-OPTIONS-RESEAU" in _codes(declarations, non_booleen)


def test_une_application_tiktok_auditee_permet_la_confidentialite_publique(declarations):
    class Auditee(type(declarations["tiktok"])):
        CLIENT_AUDITE = True

    publique = {"confidentialite": "PUBLIC_TO_EVERYONE", "commentaires": False, "duo": False, "stitch": False}
    assert Auditee().valider_options(publique) == []
    assert declarations["tiktok"].valider_options(publique) != []


def test_les_reseaux_sans_option_requise_refusent_toute_option(declarations):
    assert "REJ-SOCIAL-OPTIONS-RESEAU" in _codes(declarations, publication("facebook", options={"x": 1}))


# -- planification : délai, horizon, fenêtre, quota
# ------------------------------------------------------------------------
def _plan(declarations, donnees, horaires=(), pol=None, maintenant=MAINTENANT):
    chargee = _pub(donnees)
    return [
        (r["code"])
        for r in garde_fous.controler_planification(
            chargee, declarations[chargee.reseau].LIMITES, pol or politique.PolitiqueSas(), maintenant, list(horaires)
        )
    ]


def test_le_delai_minimal_avant_la_publication(declarations):
    pol = politique.PolitiqueSas(delai_minimal_s=300)
    assert _plan(declarations, publication("facebook", planifie_le="2026-01-05T15:04:59Z"), pol=pol) == [
        "REJ-SOCIAL-PLANIFICATION-TROP-PROCHE"
    ]
    assert _plan(declarations, publication("facebook", planifie_le="2026-01-05T15:05:00Z"), pol=pol) == []
    assert _plan(declarations, publication("facebook", planifie_le="2026-01-05T14:00:00Z"), pol=pol) == [
        "REJ-SOCIAL-PLANIFICATION-TROP-PROCHE"
    ]


def test_l_horizon_maximal(declarations):
    limite = (MAINTENANT + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    apres = (MAINTENANT + timedelta(days=60, seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fenetre_large = politique.PolitiqueSas(fenetre=politique.FenetrePublication(debut=time(0, 0), fin=time(23, 59, 59)))
    assert _plan(declarations, publication("facebook", planifie_le=limite), pol=fenetre_large) == []
    assert _plan(declarations, publication("facebook", planifie_le=apres), pol=fenetre_large) == [
        "REJ-SOCIAL-PLANIFICATION-TROP-LOINTAINE"
    ]


@pytest.mark.parametrize(
    ("instant_utc", "dans"),
    [
        ("2026-01-06T11:59:59Z", False),  # 06 h 59 59 à Toronto
        ("2026-01-06T12:00:00Z", True),  # 07 h 00 : début inclus
        ("2026-01-07T01:59:59Z", True),  # 20 h 59 59
        ("2026-01-07T02:00:00Z", False),  # 21 h 00 : fin exclue
        ("2026-01-06T03:00:00Z", False),  # 22 h le soir précédent
    ],
)
def test_la_fenetre_de_publication_est_en_heure_locale(declarations, instant_utc, dans):
    codes = _plan(declarations, publication("facebook", planifie_le=instant_utc))
    assert ("REJ-SOCIAL-HORS-FENETRE" not in codes) is dans, codes


def test_la_fenetre_suit_l_heure_d_ete_de_toronto(declarations):
    # 2026-07-06 : UTC-4. 11 h UTC = 7 h locale (dans la fenêtre) ; 10 h UTC = 6 h locale (hors fenêtre)
    maintenant = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert "REJ-SOCIAL-HORS-FENETRE" not in _plan(
        declarations, publication("facebook", planifie_le="2026-07-06T11:00:00Z"), maintenant=maintenant
    )
    assert "REJ-SOCIAL-HORS-FENETRE" in _plan(
        declarations, publication("facebook", planifie_le="2026-07-06T10:00:00Z"), maintenant=maintenant
    )


def _horaires(n, debut=datetime(2026, 1, 6, 12, 0, tzinfo=UTC), pas=timedelta(minutes=30)):
    return [debut + pas * i for i in range(n)]


def test_le_quota_de_24_heures_glissantes_est_exact_au_bord(declarations):
    quota = declarations["gbp"].LIMITES.quota_24h  # 3
    existants = _horaires(quota)  # 12:00, 12:30, 13:00
    assert "REJ-SOCIAL-QUOTA-24H" in _plan(
        declarations, publication("gbp", planifie_le="2026-01-06T14:00:00Z"), existants
    )
    # exactement 24 h après la première : la fenêtre [12:00, 12:00+24h) ne contient plus la première
    assert "REJ-SOCIAL-QUOTA-24H" not in _plan(
        declarations, publication("gbp", planifie_le="2026-01-07T12:00:00Z"), existants
    )
    # une seconde avant : la première est encore dans la fenêtre
    assert "REJ-SOCIAL-QUOTA-24H" in _plan(
        declarations, publication("gbp", planifie_le="2026-01-07T11:59:59Z"), existants
    )
    assert "REJ-SOCIAL-QUOTA-24H" not in _plan(
        declarations, publication("gbp", planifie_le="2026-01-06T14:00:00Z"), existants[:2]
    )


def test_le_quota_regarde_aussi_les_publications_apres_l_heure_candidate():
    quota = 2
    tot = datetime(2026, 1, 6, 12, 0, tzinfo=UTC)
    existants = [tot + timedelta(hours=10), tot + timedelta(hours=20)]
    assert garde_fous.quota_respecte(existants, tot, quota) is False, (
        "12:00 + 22:00 + 08:00 le lendemain tient dans 24 h"
    )
    assert garde_fous.quota_respecte(existants, tot - timedelta(hours=5), quota) is True


@pytest.mark.parametrize(
    ("n", "quota", "attendu"),
    [
        (0, 1, True),
        (0, 0, False),
        (1, 1, False),
        (1, 2, True),
        (5, 5, False),
        (5, 6, True),
        (23, 23, False),
        (23, 24, True),
        (24, 24, True),  # le candidat tombe pile 24 h après le premier : la fenêtre de 24 h ne les contient pas tous
        (24, 23, False),
    ],
)
def test_le_quota_sur_des_publications_horaires(n, quota, attendu):
    base = datetime(2026, 1, 6, 12, 0, tzinfo=UTC)
    existants = [base + timedelta(hours=i) for i in range(n)]
    assert garde_fous.quota_respecte(existants, base + timedelta(hours=n), quota) is attendu


def test_le_quota_le_plus_strict_s_applique(declarations):
    pol = politique.PolitiqueSas(quota_24h=(("facebook", 1), ("instagram", 10_000)))
    assert garde_fous.quota_applicable(declarations["facebook"].LIMITES, pol) == 1
    assert garde_fous.quota_applicable(declarations["instagram"].LIMITES, pol) == 100, (
        "jamais plus que le plafond du réseau"
    )
    autre = _horaires(1, datetime(2026, 1, 6, 12, 0, tzinfo=UTC))
    assert "REJ-SOCIAL-QUOTA-24H" in _plan(
        declarations, publication("facebook", planifie_le="2026-01-06T13:00:00Z"), autre, pol
    )


# -- niveau d'approbation ---------------------------------------------------------------------------------------------
def test_le_niveau_de_l_outil_doit_etre_exactement_celui_que_la_publication_exige():
    organique, payante = _pub(publication("facebook")), _pub(annonce("facebook"))
    assert garde_fous.verifier_niveau(organique, 3) == []
    assert garde_fous.verifier_niveau(payante, 4) == []
    refus = garde_fous.verifier_niveau(payante, 3)
    assert refus[0]["code"] == "REJ-SOCIAL-NIVEAU-INSUFFISANT" and "m7_demander_annonce_payante" in refus[0]["detail"]
    assert garde_fous.verifier_niveau(organique, 4)[0]["code"] == "REJ-SOCIAL-NIVEAU-INSUFFISANT"
    assert garde_fous.verifier_niveau(organique, 0)[0]["code"] == "REJ-SOCIAL-NIVEAU-INSUFFISANT"


def test_la_fenetre_de_publication_est_une_valeur_de_politique():
    fenetre = politique.FenetrePublication(fuseau="America/Toronto", debut=time(9, 0), fin=time(17, 0))
    assert fenetre.contient(datetime(2026, 1, 6, 14, 0, tzinfo=UTC)) is True
    assert fenetre.contient(datetime(2026, 1, 6, 13, 59, tzinfo=UTC)) is False
    assert dataclasses.is_dataclass(fenetre)


def test_demain_10h_est_bien_dans_la_fenetre_par_defaut(declarations):
    assert _plan(declarations, publication("facebook", planifie_le=DEMAIN_10H)) == []
