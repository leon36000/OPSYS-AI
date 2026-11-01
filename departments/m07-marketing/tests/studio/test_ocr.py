"""Lecteurs de la sortie : le double à pixels lit vraiment les pixels ; l'adaptateur du profil OCR est testé simulé."""

from __future__ import annotations

import dataclasses

import fabriques_studio as f
import pytest
from m7_marketing.studio import brief as b
from m7_marketing.studio import composition, ocr, png, polices, rendus
from m7_marketing.studio import plan as p


@pytest.fixture(scope="module")
def registre(tmp_path_factory):
    return polices.charger_dossier(f.ecrire_polices(tmp_path_factory.mktemp("p")), production=False)


def _compose(registre, donnees):
    brief, refus = b.depuis_dict(donnees)
    assert brief is not None, refus
    return composition.composer_visuel(brief, registre, f.POLICE_ID)


def _lu(lecture):
    par = {}
    for j in lecture.jetons:
        par.setdefault(j.ref, []).append(j.texte)
    return {ref: " ".join(mots) for ref, mots in par.items()}


@pytest.mark.parametrize(
    ("gabarit", "format_"),
    [("carte_affaires", None), ("banniere_social", "1080x1350"), ("banniere_social", "1200x627"), ("couverture", None)],
)
def test_le_double_a_pixels_relit_chaque_ligne_posee(registre, gabarit, format_):
    donnees = f.brief(
        gabarit,
        format_,
        elements_critiques=f.critiques("telephone", "courriel", "adresse", "licence_rbq", "prix")[
            : 3 if gabarit == "couverture" else 5
        ],
        mentions_obligatoires=[] if gabarit == "couverture" else ["Licence RBQ détenue par l'entreprise"],
    )
    comp = _compose(registre, donnees)
    lecture = ocr.LecteurGabaritsPixels(registre).lire(comp.artefacts["png"], "png", comp.plan)
    lu = _lu(lecture)
    for ligne in comp.plan.lignes:
        assert lu.get(f"{ligne.id}#{ligne.n}") == ligne.texte, ligne.id


def test_le_double_lit_toute_la_police_de_test(registre):
    """Chaque caractère de la police, posé en ligne dans un titre, est relu exactement."""
    tout = [c for c in registre.obtenir(f.POLICE_ID).ttf.caracteres() if 0x21 <= ord(c) < 0x250 and c not in "  "]
    lus_au_total = 0
    for i in range(0, len(tout), 28):
        morceau = "".join(tout[i : i + 28])
        donnees = f.brief("banniere_social")
        donnees["textes"] = {"titre": {"fr": morceau}}
        donnees["elements_critiques"] = []
        donnees["mentions_obligatoires"] = []
        brief, refus = b.depuis_dict(donnees)
        if brief is None:  # le garde-fou de texte public refuse certains motifs (ex. « $ », « @ », « % »)
            continue
        comp = composition.composer_visuel(brief, registre, f.POLICE_ID)
        lecture = ocr.LecteurGabaritsPixels(registre).lire(comp.artefacts["png"], "png", comp.plan)
        lu = _lu(lecture)
        for ligne in comp.plan.lignes:
            assert lu.get(f"{ligne.id}#{ligne.n}") == ligne.texte
            lus_au_total += len(ligne.texte)
    assert lus_au_total >= 60  # le garde-fou de texte public peut écarter certains morceaux : la moitié au moins passe


def test_le_double_lit_les_pixels_un_chiffre_change_dans_le_png_est_lu_change(registre):
    comp = _compose(registre, f.brief())
    ligne = next(lg for lg in comp.plan.lignes if lg.id == "critique.telephone.0")
    # Plan truqué : le PNG est rendu avec un autre numéro ; la lecture se fait sur LES PIXELS, pas sur le plan honnête.
    truque = dataclasses.replace(ligne, texte=ligne.texte.replace("0142", "0143"))
    elements = tuple(truque if e is ligne else e for e in comp.plan.elements)
    plan_truque = dataclasses.replace(comp.plan, elements=elements)
    png_truque = rendus.rendre_png(plan_truque, None, registre, comp.marquage)
    lecture = ocr.LecteurGabaritsPixels(registre).lire(png_truque, "png", comp.plan)  # indices du plan HONNÊTE
    assert _lu(lecture)["critique.telephone.0#0"].endswith("0143")


def test_un_pixel_efface_dans_un_glyphe_le_rend_illisible_ou_different(registre):
    comp = _compose(registre, f.brief())
    ligne = next(lg for lg in comp.plan.lignes if lg.id == "critique.licence_rbq.0")
    image = png.decoder(comp.artefacts["png"])
    pixels = bytearray(image.pixels)
    # Remplit en fond un bloc de la zone du numéro : l'encre disparaît partiellement.
    x0, y0, x1, y1 = (int(v) for v in ligne.boite)
    for y in range(y0, y1):
        for x in range(x0 + int(0.6 * (x1 - x0)), x0 + int(0.7 * (x1 - x0))):
            pixels[3 * (y * image.largeur + x) : 3 * (y * image.largeur + x) + 3] = bytes(comp.plan.rects[0].couleur)
    abime = png.encoder(png.ImageRVB(image.largeur, image.hauteur, bytes(pixels)))
    lu = _lu(ocr.LecteurGabaritsPixels(registre).lire(abime, "png", comp.plan))["critique.licence_rbq.0#0"]
    assert lu != ligne.texte


def test_png_illisible_leve_une_erreur_typee(registre):
    comp = _compose(registre, f.brief())
    with pytest.raises(png.PngInvalide):
        ocr.LecteurGabaritsPixels(registre).lire(b"pas un png", "png", comp.plan)


def test_format_non_lu_par_le_lecteur(registre):
    comp = _compose(registre, f.brief())
    with pytest.raises(ValueError):
        ocr.LecteurGabaritsPixels(registre).lire(b"", "svg", comp.plan)
    with pytest.raises(ValueError):
        ocr.LecteurTexteVectoriel().lire(b"", "png", comp.plan)


def test_le_lecteur_vectoriel_lit_le_svg_et_le_pdf(registre):
    comp = _compose(registre, f.brief())
    lecteur = ocr.LecteurTexteVectoriel()
    for format_ in ("svg", "pdf"):
        lecture = lecteur.lire(comp.artefacts[format_], format_, comp.plan)
        assert lecture.nature == ocr.NATURE_DOUBLE
        assert _lu(lecture) == {f"{ligne.id}#{ligne.n}": ligne.texte for ligne in comp.plan.lignes}


def test_les_doubles_se_declarent_doubles_et_le_profil_se_declare_reel(registre):
    lecteurs = ocr.lecteurs_par_defaut(registre)
    assert {lecteurs[x].nature for x in lecteurs} == {ocr.NATURE_DOUBLE}
    assert ocr.LecteurOCRProfil.nature == ocr.NATURE_REEL


# -- adaptateur du profil OCR existant (simulé : le bundle Tesseract n'existe pas ici) ----------------------------
def _candidat(tokens, largeur=1000, hauteur=500):
    return {"page": {"numero": 1, "largeur_px": largeur, "hauteur_px": hauteur, "tokens": tokens}}


def test_l_adaptateur_du_profil_ocr_convertit_les_jetons_et_remet_a_l_echelle(registre):
    comp = _compose(registre, f.brief())
    appels = []

    def faux(source, **kwargs):
        appels.append((source[:5], kwargs["lot_id"]))
        return _candidat(
            [{"texte": "Tél.", "x0": 10, "y0": 20, "x1": 60, "y1": 40, "confiance_brute": 91.5}],
            largeur=comp.plan.largeur_px // 2,
            hauteur=comp.plan.hauteur_px // 2,
        )

    lecteur = ocr.LecteurOCRProfil(bundle="/non/utilise", extraire=faux)
    lecture = lecteur.lire(comp.artefacts["pdf"], "pdf", comp.plan)
    assert appels == [(b"%PDF-", "studio-controle")]
    assert lecture.nature == ocr.NATURE_REEL and lecture.jetons[0].texte == "Tél."
    assert lecture.jetons[0].x0 == 20.0 and lecture.jetons[0].y1 == 80.0 and lecture.jetons[0].confiance == 91.5


def test_l_adaptateur_emballe_un_png_dans_un_pdf_lisible(registre):
    comp = _compose(registre, f.brief("banniere_social"))
    recus = []
    lecteur = ocr.LecteurOCRProfil(bundle="x", extraire=lambda source, **kw: recus.append(source) or _candidat([]))
    lecteur.lire(comp.artefacts["png"], "png", comp.plan)
    assert recus[0].startswith(b"%PDF-1.4") and rendus.lire_pdf(recus[0])["incorpore_image"]


def test_profil_ocr_indisponible_devient_une_erreur_de_lecture_typee(registre):
    from opsys import ocr_runtime

    comp = _compose(registre, f.brief())

    def echoue(source, **kwargs):
        raise ocr_runtime.OCRRuntimeErreur("OCR_PROFIL_INDISPONIBLE")

    with pytest.raises(ocr.LectureImpossible) as erreur:
        ocr.LecteurOCRProfil(bundle="x", extraire=echoue).lire(comp.artefacts["pdf"], "pdf", comp.plan)
    assert "OCR_PROFIL_INDISPONIBLE" in str(erreur.value)


def test_le_profil_ocr_reel_n_est_pas_disponible_sur_cette_machine(registre, tmp_path):
    """Sans bundle validé, l'appel réel échoue de façon typée : on ne simule jamais une lecture réussie."""
    comp = _compose(registre, f.brief())
    with pytest.raises(ocr.LectureImpossible):
        ocr.LecteurOCRProfil(bundle=tmp_path / "absent").lire(
            comp.artefacts["pdf"], "pdf", p.Plan.__new__(p.Plan) if False else comp.plan
        )
