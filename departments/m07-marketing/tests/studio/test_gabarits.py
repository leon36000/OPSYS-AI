"""Gabarits : mise en page déterministe, aucun texte tronqué, refus de ce qui ne tient pas, zones de sécurité."""

from __future__ import annotations

import copy

import fabriques_studio as f
import pytest
from m7_marketing.studio import brief as b
from m7_marketing.studio import gabarits, plan, polices


@pytest.fixture(scope="module")
def registre(tmp_path_factory):
    return polices.charger_dossier(f.ecrire_polices(tmp_path_factory.mktemp("p")), production=False)


def _brief(*args, **kwargs):
    brief, refus = b.depuis_dict(f.brief(*args, **kwargs))
    assert brief is not None, refus
    return brief


FOND = {"mode": "uni", "couleur": "#F2C14E"}


def _plan(registre, brief, **kw):
    return gabarits.composer(brief, registre, f.POLICE_ID, fond=FOND, **kw)


@pytest.mark.parametrize(("gabarit", "format_"), [(g, n) for g, fs in b.GABARITS.items() for n in fs])
def test_chaque_gabarit_et_chaque_format_se_compose_et_reste_dans_la_zone_de_securite(registre, gabarit, format_):
    brief = _brief(gabarit, format_, elements_critiques=f.critiques("telephone"), mentions_obligatoires=[])
    pl = _plan(registre, brief)
    assert pl.lignes
    s = pl.surete
    for ligne in pl.lignes:
        x0, y0, x1, y1 = ligne.boite
        assert s[0] - 0.5 <= x0 and x1 <= s[2] + 0.5 and s[1] - 0.5 <= y0 and y1 <= s[3] + 0.5, ligne.id
        assert ligne.taille_px >= pl.taille_min_px - 1e-6
        for zone in pl.zones_reservees:
            assert y1 <= zone[1] or y0 >= zone[3] or x1 <= zone[0] or x0 >= zone[2]


def test_le_plan_est_deterministe(registre):
    brief = _brief()
    assert plan.empreinte(_plan(registre, brief)) == plan.empreinte(_plan(registre, brief))
    autre = _brief(textes={"titre": {"fr": "Un autre titre"}})
    assert plan.empreinte(_plan(registre, brief)) != plan.empreinte(_plan(registre, autre))


def test_la_carte_a_les_dimensions_du_format_fini_et_un_fond_perdu_de_un_huitieme_de_pouce(registre):
    pl = _plan(registre, _brief())
    rogne = pl.rognage
    assert rogne[2] - rogne[0] == 1050 and rogne[3] - rogne[1] == 600  # 3,5 × 2 po à 300 ppp
    assert pl.fond_perdu_px >= 37.5  # 0,125 po
    assert pl.largeur_px == 1050 + 2 * pl.fond_perdu_px
    assert pl.taille_min_px == pytest.approx(7 * 300 / 72)


def test_les_donnees_critiques_sont_posees_telles_quelles_avec_leur_libelle(registre):
    brief = _brief(elements_critiques=f.critiques("telephone", "licence_rbq", "courriel", "prix"))
    pl = _plan(registre, brief)
    textes = {i: " ".join(ligne.texte for ligne in lignes) for i, lignes in pl.elements_logiques().items()}
    assert textes["critique.telephone.0"] == "Tél. : " + f.TELEPHONE
    assert textes["critique.licence_rbq.0"] == "Licence RBQ : " + f.RBQ
    assert textes["critique.courriel.0"] == f.COURRIEL
    assert textes["critique.prix.0"] == "Prix : 1 250,00 $"
    assert all(ligne.critique for ligne in pl.lignes if ligne.id.startswith("critique."))


def test_les_lignes_jointes_par_une_espace_redonnent_exactement_le_texte(registre):
    """Un envoi à la ligne ne modifie, ne perd et ne déplace aucun caractère."""
    ttf = registre.obtenir(f.POLICE_ID).ttf
    textes = [
        f.ADRESSE,
        "Licence RBQ détenue par l'entreprise",
        "Un très très long titre qui doit se répartir",
        "Revêtements Horizon Fictif",
        "a b c d e f g h i j k l m n o p",
    ]
    for texte in textes:
        for largeur in (200, 350, 500, 900):
            for coupures in ((), (", ",)):
                lignes = gabarits.envelopper(texte, ttf, 20.0, largeur, 6, coupures)
                if lignes is not None:
                    assert " ".join(lignes) == texte, (texte, largeur, coupures)
                    assert all(ttf.largeur(ligne, 20.0) <= largeur for ligne in lignes)


def test_l_adresse_se_coupe_d_abord_apres_les_virgules(registre):
    ttf = registre.obtenir(f.POLICE_ID).ttf
    lignes = gabarits.envelopper(f.ADRESSE, ttf, 20.0, ttf.largeur(f.ADRESSE, 20.0) * 0.75, 3, (", ",))
    assert lignes[0].endswith(",") and " ".join(lignes) == f.ADRESSE


def test_un_mot_plus_large_que_la_zone_est_refuse_jamais_coupe(registre):
    ttf = registre.obtenir(f.POLICE_ID).ttf
    assert gabarits.envelopper("Supercalifragilistic", ttf, 20.0, 50.0, 5, ()) is None


def test_trop_de_texte_pour_la_carte_est_refuse_sans_troncature(registre):
    brief = _brief(
        elements_critiques=[
            {"type": "telephone", "valeur": f"+1 450 555 01{i:02d}", "source": "fiche fictive"} for i in range(12)
        ]
    )
    with pytest.raises(gabarits.GabaritErreur) as erreur:
        _plan(registre, brief)
    assert erreur.value.code == gabarits.REJ_TEXTE_NE_TIENT_PAS


def test_le_texte_ne_descend_jamais_sous_la_taille_minimale(registre):
    brief = _brief(elements_critiques=f.critiques("telephone", "courriel", "adresse", "licence_rbq", "neq", "site_web"))
    try:
        pl = _plan(registre, brief)
    except gabarits.GabaritErreur as erreur:
        assert erreur.code == gabarits.REJ_TEXTE_NE_TIENT_PAS
    else:
        assert min(ligne.taille_px for ligne in pl.lignes) >= pl.taille_min_px - 1e-6


def test_l_anglais_est_pose_plus_petit_que_le_francais(registre):
    donnees = f.brief(langues=["fr", "en"])
    donnees["textes"] = {"titre": {"fr": "Votre toiture en confiance", "en": "Your roof, with confidence"}}
    pl = _plan(registre, _brief_depuis(donnees))
    fr = [ligne for ligne in pl.lignes if ligne.langue == "fr"]
    en = [ligne for ligne in pl.lignes if ligne.langue == "en"]
    assert fr and en and max(ligne.taille_px for ligne in en) < min(ligne.taille_px for ligne in fr)


def _brief_depuis(donnees):
    brief, refus = b.depuis_dict(donnees)
    assert brief is not None, refus
    return brief


def test_le_blanc_ou_le_noir_atteint_toujours_le_seuil_aa_sur_n_importe_quel_panneau(registre):
    """Le contraste maximal du blanc et du noir sur un gris moyen reste ≥ 4,58:1 : le gabarit n'a donc jamais à refuser
    une palette pour son contraste (le contrôle qualité mesure quand même les pixels livrés)."""
    from m7_marketing.studio.toile import rapport_contraste

    for gris in range(0, 256, 5):
        donnees = f.brief()
        donnees["marque"]["couleurs"] = [f"#{gris:02X}{gris:02X}{gris:02X}"]
        pl = _plan(registre, _brief_depuis(donnees))
        panneau = pl.rects[0].couleur
        assert rapport_contraste(pl.lignes[0].couleur, panneau) >= 4.5


def test_la_couleur_du_texte_est_celle_de_meilleur_contraste(registre):
    sombre = copy.deepcopy(f.brief())
    pl = _plan(registre, _brief_depuis(sombre))
    assert {ligne.couleur for ligne in pl.lignes} == {(255, 255, 255)}  # panneau bleu nuit -> texte blanc
    clair = f.brief()
    clair["marque"]["couleurs"] = ["#F7F2E8", "#0B3C5D"]
    pl = _plan(registre, _brief_depuis(clair))
    assert {ligne.couleur for ligne in pl.lignes} == {(11, 60, 93)} or {ligne.couleur for ligne in pl.lignes} == {
        (0, 0, 0)
    }


def test_caractere_sans_glyphe_refuse_avant_de_composer(registre):
    donnees = f.brief()
    donnees["textes"]["titre"]["fr"] = "Toiture 日本"
    with pytest.raises(gabarits.GabaritErreur) as erreur:
        _plan(registre, _brief_depuis(donnees))
    assert erreur.value.code == gabarits.REJ_POLICE_GLYPHE


def test_police_inconnue_refusee(registre):
    with pytest.raises(polices.PoliceErreur):
        gabarits.composer(_brief(), registre, "police-inexistante", fond=FOND)


def test_le_neuf_seizieme_reserve_ses_bandes_d_interface(registre):
    pl = _plan(registre, _brief("banniere_social", "1080x1920"))
    assert len(pl.zones_reservees) == 2
    haut, bas = pl.zones_reservees
    assert haut[3] == pytest.approx(0.14 * 1920, abs=1) and bas[1] == pytest.approx(1920 - 0.20 * 1920, abs=1)


def test_un_logo_est_pose_et_reserve_sa_place(registre):
    logo = {"id": "logo-fictif-1", "chemins": ["M 0 0 L 10 0 L 10 10 L 0 10 Z"], "vb_w": 10, "vb_h": 10}
    petit = _brief(elements_critiques=f.critiques("telephone"), mentions_obligatoires=[])
    sans = _plan(registre, petit)
    avec = _plan(registre, petit, logo=logo)
    assert avec.logo is not None and avec.logo.couleur == (255, 255, 255)
    assert min(ligne.boite[1] for ligne in avec.lignes) > min(ligne.boite[1] for ligne in sans.lignes)


def test_format_inconnu_refuse():
    with pytest.raises(gabarits.GabaritErreur):
        gabarits.format_de("carte_affaires", "9x9")
