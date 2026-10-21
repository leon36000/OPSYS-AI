"""Les cinq variantes d'un chantier et leurs gabarits fixes (PLAN T4.17) : ce que le code compose sans modèle."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from m7_marketing.usine import gabarits, plateformes
from m7_marketing.usine.controle_texte import ContexteControle, controler_texte
from m7_marketing.usine.gabarits import Matiere

FICTIF = True
CONTRAT_UTM = Path(__file__).resolve().parents[2] / "contracts" / "utm-convention.v1.yaml"

MATIERES = [
    Matiere("Toitures Boréales Fictive Inc.", "Rénovation extérieure, sans surprise", "Gouttières et descentes",
            "Repentigny"),
    Matiere("Toitures Boréales Fictive Inc.", "", "Revêtement extérieur", None),
    Matiere("Aluminium Québec Fictif", "Un travail soigné.", "Soffite et fascia", "Joliette"),
    Matiere("Toitures Boréales Fictive Inc.", "À CONFIGURER", "TPS et TVQ", "Terrebonne"),
]


def test_cinq_variantes_dans_l_ordre():
    assert plateformes.CODES_PLATEFORMES == (
        "facebook", "instagram", "fiche_google", "video_courte", "demande_temoignage",
    )
    assert [p.public for p in plateformes.PLATEFORMES] == [True, True, True, True, False]


def test_les_liens_de_suivi_viennent_de_l_enumere_gele_du_contrat_utm():
    enums = yaml.safe_load(CONTRAT_UTM.read_text(encoding="utf-8"))["enums"]
    for p in plateformes.PLATEFORMES:
        if p.source_utm is None:
            assert p.medium_utm is None and not p.public
            continue
        assert p.source_utm in enums["utm_source"], p.code
        assert p.medium_utm in enums["utm_medium"], p.code


def test_la_demande_de_temoignage_est_privee_et_sans_lien():
    p = plateformes.plateforme("demande_temoignage")
    assert (p.public, p.source_utm, p.media) == (False, None, plateformes.MEDIA_AUCUN)


def test_instagram_exige_un_media():
    assert plateformes.plateforme("instagram").media == plateformes.MEDIA_REQUIS


def test_plateforme_inconnue_est_un_refus_metier():
    with pytest.raises(KeyError, match="plateforme inconnue"):
        plateformes.plateforme("tiktok_live")
    with pytest.raises(KeyError, match="aucun gabarit"):
        gabarits.composer("tiktok_live", MATIERES[0])


@pytest.mark.parametrize("code", plateformes.CODES_PLATEFORMES)
@pytest.mark.parametrize("matiere", MATIERES, ids=lambda m: f"{m.marque[:9]}-{m.ville}")
def test_chaque_gabarit_passe_son_propre_controle(code, matiere):
    """Le code n'a pas de traitement de faveur : ce qu'il compose passe le contrôle que subit un texte de modèle
    (marque en nom de marque, plafond de la plateforme compris)."""
    texte = gabarits.composer(code, matiere)
    contexte = ContexteControle(
        noms_de_marque=(matiere.marque,), longueur_max=plateformes.plateforme(code).longueur_max,
    )
    assert controler_texte(texte, contexte) == (), texte


@pytest.mark.parametrize("code", plateformes.CODES_PLATEFORMES)
def test_le_gabarit_dit_la_marque_et_la_nature_et_jamais_un_lieu_invente(code):
    avec = gabarits.composer(code, MATIERES[0])
    sans = gabarits.composer(code, Matiere(MATIERES[0].marque, "", MATIERES[0].nature, None))
    assert "Toitures Boréales Fictive Inc." in avec
    assert "Repentigny" in avec
    assert "Repentigny" not in sans and " à None" not in sans  # sans ville dans le WCT, aucune ville


def test_l_accroche_du_profil_entre_dans_le_texte_avec_sa_ponctuation():
    texte = gabarits.composer("fiche_google", MATIERES[0])
    assert "sans surprise. Contactez" in texte  # l'accroche sans point final en reçoit un avant la phrase suivante
    sans_accroche = gabarits.composer("fiche_google", MATIERES[1])
    assert "  " not in sans_accroche and "\n\n\n" not in gabarits.composer("facebook", MATIERES[1])


def test_l_elision_devant_une_voyelle():
    assert "L'équipe d'Aluminium Québec Fictif" in gabarits.composer("facebook", MATIERES[2])
    assert "L'équipe de Toitures" in gabarits.composer("facebook", MATIERES[0])


def test_un_sigle_garde_ses_majuscules_dans_la_phrase():
    assert "TPS et TVQ" in gabarits.composer("facebook", MATIERES[3])
    assert "gouttières et descentes" in gabarits.composer("facebook", MATIERES[0])


def test_la_video_ne_donne_aucune_duree_et_la_demande_promet_de_ne_rien_publier_sans_accord():
    video = gabarits.composer("video_courte", MATIERES[0])
    assert "Scène 1" in video and "Scène 3" in video and " s)" not in video
    assert "accord explicite" in gabarits.composer("demande_temoignage", MATIERES[0])


def test_les_gabarits_sont_deterministes():
    for code in plateformes.CODES_PLATEFORMES:
        assert gabarits.composer(code, MATIERES[0]) == gabarits.composer(code, MATIERES[0])
