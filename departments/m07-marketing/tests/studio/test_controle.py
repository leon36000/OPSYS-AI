"""Contrôle qualité : chaque règle a un cas qui l'enfreint, et le rapport est signé par son empreinte."""

from __future__ import annotations

import dataclasses
import datetime as dt

import fabriques_studio as f
import pytest
from m7_marketing.studio import brief as b
from m7_marketing.studio import composition, controle, ocr, png, polices, rendus
from m7_marketing.studio import plan as p

MAINTENANT = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def registre(tmp_path_factory):
    return polices.charger_dossier(f.ecrire_polices(tmp_path_factory.mktemp("p")), production=False)


def _comp(registre, donnees=None, **kw):
    brief, refus = b.depuis_dict(donnees or f.brief())
    assert brief is not None, refus
    return composition.composer_visuel(brief, registre, f.POLICE_ID, **kw)


def _controler(comp, registre, lecteurs=None, **kw):
    return controle.controler(
        comp, registre, lecteurs or ocr.lecteurs_par_defaut(registre), maintenant=MAINTENANT, **kw
    )


def _code(rapport, code):
    return [c for c in rapport.constats if c["code"] == code]


def _echecs(rapport):
    return set(rapport.echecs_critiques())


def _remplacer_ligne(comp, registre, identifiant, **changements):
    """Une composition dont UNE ligne du plan est changée ; les artefacts sont refaits du plan truqué (un gabarit
    défectueux, pas une altération de fichier)."""
    cible = next(ligne for ligne in comp.plan.lignes if ligne.id == identifiant)
    nouvelle = dataclasses.replace(cible, **changements)
    plan = dataclasses.replace(comp.plan, elements=tuple(nouvelle if e is cible else e for e in comp.plan.elements))
    return _recomposer(comp, registre, plan)


def _recomposer(comp, registre, plan):
    marquage = dict(comp.marquage, plan_empreinte=p.empreinte(plan))
    artefacts = {
        "svg": rendus.rendre_svg(plan, comp.fond_png, registre, marquage),
        "png": rendus.rendre_png(plan, comp.fond_png, registre, marquage),
    }
    if plan.impression:
        artefacts["pdf"] = rendus.rendre_pdf(plan, comp.fond_png, registre, marquage)
    return dataclasses.replace(comp, plan=plan, artefacts=artefacts, marquage=marquage)


@pytest.fixture(scope="module")
def carte(registre):
    return _comp(registre, f.brief(elements_critiques=f.critiques("telephone", "courriel", "adresse", "licence_rbq")))


@pytest.fixture(scope="module")
def rapport_carte(carte, registre):
    return _controler(carte, registre)


def test_une_carte_conforme_passe_tous_les_controles_critiques(rapport_carte):
    assert rapport_carte.conforme, [c for c in rapport_carte.constats if not c["ok"]]
    assert {c["code"] for c in rapport_carte.constats} >= {
        "QC-ELEMENTS",
        "QC-OCR",
        "QC-INCONNU-CRITIQUE",
        "QC-CONTRASTE",
        "QC-TAILLE-MIN",
        "QC-ZONE-SECURITE",
        "QC-FOND-PERDU",
        "QC-RESOLUTION",
        "QC-LANGUE-FR",
        "QC-MARQUAGE-IA",
        "QC-LICENCE",
        "QC-POLICES",
        "QC-REPRODUCTIBILITE",
        "QC-FORMAT",
    }


def test_chaque_format_est_lu_par_son_lecteur_et_la_nature_est_consignee(rapport_carte):
    lecteurs = {x["format"]: x for x in rapport_carte.donnees["lecteurs"]}
    assert set(lecteurs) == {"png", "svg", "pdf"}
    assert all(x["nature"] == "double" for x in lecteurs.values())
    assert any("double" in lim for lim in rapport_carte.donnees["limites"])


def test_le_rapport_est_signe_par_son_empreinte_et_toute_retouche_la_brise(rapport_carte, carte):
    donnees = rapport_carte.donnees
    assert controle.verifier_empreinte_rapport(donnees)
    for retouche in (
        lambda d: d.update(conforme=not d["conforme"]),
        lambda d: d["constats"][0].update(ok=not d["constats"][0]["ok"]),
        lambda d: d["artefacts"]["png"].update(sha256="0" * 64),
        lambda d: d.update(brief_empreinte="1" * 64),
    ):
        copie = __import__("json").loads(__import__("json").dumps(donnees))
        retouche(copie)
        assert not controle.verifier_empreinte_rapport(copie)
    assert not controle.verifier_empreinte_rapport({"constats": []})
    assert rapport_carte.donnees["composition_empreinte"] == carte.empreinte()


def test_le_rapport_est_deterministe(carte, registre, rapport_carte):
    assert _controler(carte, registre).empreinte == rapport_carte.empreinte


# -- exactitude des éléments critiques --------------------------------------------------------------------------
def test_un_chiffre_du_telephone_change_dans_le_rendu_est_pris(carte, registre):
    truquee = _remplacer_ligne(carte, registre, "critique.telephone.0", texte="Tél. : +1 450 555 0143")
    rapport = _controler(truquee, registre)
    assert not rapport.conforme and {"QC-ELEMENTS", "QC-OCR"} <= _echecs(rapport)
    ecarts = _code(rapport, "QC-OCR")[0]["mesure"]["ecarts"]["critique.telephone.0"]
    assert ecarts["attendu"].endswith("0142") and ecarts["lu"].endswith("0143")


def test_une_licence_rbq_alteree_est_prise(carte, registre):
    truquee = _remplacer_ligne(carte, registre, "critique.licence_rbq.0", texte="Licence RBQ : 1234-5678-91")
    assert {"QC-ELEMENTS", "QC-OCR"} <= _echecs(_controler(truquee, registre))


def test_une_adresse_modifiee_est_prise(carte, registre):
    ligne = next(lg for lg in carte.plan.lignes if lg.id == "critique.adresse.0" and lg.n == 0)
    truquee = _remplacer_ligne(carte, registre, "critique.adresse.0", texte=ligne.texte.replace("123", "132"))
    assert "QC-OCR" in _echecs(_controler(truquee, registre))


def test_le_nom_de_la_marque_modifie_est_pris(carte, registre):
    ligne = next(lg for lg in carte.plan.lignes if lg.id == "marque" and lg.n == 0)
    truquee = _remplacer_ligne(carte, registre, "marque", texte=ligne.texte.replace("Horizon", "Horizo"))
    assert {"QC-ELEMENTS", "QC-OCR"} <= _echecs(_controler(truquee, registre))


def test_un_prix_altere_est_pris(registre):
    comp = _comp(registre, f.brief(elements_critiques=f.critiques("prix")))
    truquee = _remplacer_ligne(comp, registre, "critique.prix.0", texte="Prix : 1 520,00 $")
    rapport = _controler(truquee, registre)
    assert {"QC-ELEMENTS", "QC-OCR"} <= _echecs(rapport)


def test_une_mention_obligatoire_retiree_du_plan_est_prise(carte, registre):
    sans = tuple(e for e in carte.plan.elements if not (isinstance(e, p.Ligne) and e.id == "mention.0"))
    truquee = _recomposer(carte, registre, dataclasses.replace(carte.plan, elements=sans))
    rapport = _controler(truquee, registre)
    assert "QC-ELEMENTS" in _echecs(rapport)
    assert "mention.0" in _code(rapport, "QC-ELEMENTS")[0]["mesure"]["manquants"]


def test_un_texte_non_demande_ajoute_au_plan_est_pris(carte, registre):
    modele = next(lg for lg in carte.plan.lignes if lg.id == "titre.fr")
    en_plus = dataclasses.replace(modele, id="critique.telephone.9", texte="+1 450 555 0199", n=0)
    truquee = _recomposer(carte, registre, dataclasses.replace(carte.plan, elements=(*carte.plan.elements, en_plus)))
    rapport = _controler(truquee, registre)
    assert (
        "QC-ELEMENTS" in _echecs(rapport)
        and "critique.telephone.9" in _code(rapport, "QC-ELEMENTS")[0]["mesure"]["en_trop"]
    )


class LecteurScripte:
    """Un lecteur qui rend des jetons prédéterminés (position ou ref) : sert à injecter ce qu'un VRAI OCR pourrait
    lire."""

    nom = "scripte"
    version = "0"
    nature = ocr.NATURE_DOUBLE
    formats = ("png", "svg", "pdf")

    def __init__(self, base, jetons_en_plus=(), retirer=None):
        self._base, self._plus, self._retirer = base, tuple(jetons_en_plus), retirer

    def lire(self, octets, format_, plan):
        lecture = self._base[format_].lire(octets, format_, plan)
        jetons = tuple(j for j in lecture.jetons if not (self._retirer and (j.ref or "").startswith(self._retirer)))
        return dataclasses.replace(lecture, jetons=jetons + self._plus)


def _avec_lecteur_png(registre, lecteur):
    base = ocr.lecteurs_par_defaut(registre)
    return {**base, "png": lecteur}


def test_un_numero_halluciene_dans_le_fond_est_pris_meme_hors_de_toute_zone(carte, registre):
    base = ocr.lecteurs_par_defaut(registre)
    plus = [ocr.Jeton("514 555 9999", 5, 5, 90, 20)]  # lu en haut à gauche : hors de toute ligne du plan
    rapport = _controler(carte, registre, _avec_lecteur_png(registre, LecteurScripte(base, plus)))
    assert {"QC-OCR", "QC-INCONNU-CRITIQUE"} <= _echecs(rapport)
    assert ["telephone", "514 555 9999"] in _code(rapport, "QC-INCONNU-CRITIQUE")[0]["mesure"]["inconnus"] or any(
        "514 555 9999" in str(c["mesure"]) for c in _code(rapport, "QC-INCONNU-CRITIQUE")
    )


@pytest.mark.parametrize(
    ("texte", "type_"),
    [
        ("info@autre.example", "courriel"),
        ("2 999,00 $", "prix"),
        ("9999-8888-77", "licence_rbq"),
        ("1234567890", "neq"),
        ("https://pirate.example", "site_web"),
    ],
)
def test_toute_donnee_critique_lue_hors_du_brief_est_prise(carte, registre, texte, type_):
    base = ocr.lecteurs_par_defaut(registre)
    rapport = _controler(
        carte, registre, _avec_lecteur_png(registre, LecteurScripte(base, [ocr.Jeton(texte, 5, 5, 90, 20)]))
    )
    inconnus = [c for c in rapport.constats if c["code"] == "QC-INCONNU-CRITIQUE" and not c["ok"]]
    assert inconnus and any(type_ == t for t, _v in inconnus[0]["mesure"]["inconnus"])


def test_un_jeton_attribue_a_une_ligne_par_sa_position_remplace_la_lecture_de_cette_ligne(carte, registre):
    """Un OCR réel sans `ref` : ses jetons sont rangés dans la ligne du plan qui les contient."""
    ligne = next(lg for lg in carte.plan.lignes if lg.id == "critique.courriel.0")

    class OcrReel:
        nom, version, nature, formats = "faux-reel", "1", ocr.NATURE_REEL, ("png", "svg", "pdf")

        def lire(self, octets, format_, plan):
            jetons = []
            for lg in plan.lignes:
                mots = lg.texte.split(" ")
                largeur = (lg.boite[2] - lg.boite[0]) / len(mots)
                for i, mot in enumerate(mots):
                    texte = mot.replace("@", "©") if lg is ligne else mot
                    jetons.append(
                        ocr.Jeton(
                            texte,
                            lg.boite[0] + i * largeur,
                            lg.boite[1],
                            lg.boite[0] + (i + 1) * largeur - 1,
                            lg.boite[3],
                        )
                    )
            return ocr.LectureOCR(self.nom, self.version, self.nature, format_, "0" * 64, tuple(jetons))

    rapport = _controler(carte, registre, {"png": OcrReel(), "svg": OcrReel(), "pdf": OcrReel()})
    assert "QC-OCR" in _echecs(rapport)
    assert rapport.donnees["lecteurs"][0]["nature"] == "reel"
    sain = _controler(
        carte, registre, {"png": OcrReel(), "svg": ocr.LecteurTexteVectoriel(), "pdf": ocr.LecteurTexteVectoriel()}
    )
    assert "QC-OCR" in _echecs(sain)  # le png truqué reste pris, indépendamment des autres lecteurs


def test_un_format_sans_lecteur_est_un_echec_critique_pas_un_saut(carte, registre):
    for manquant in ("png", "svg", "pdf"):
        lecteurs = dict(ocr.lecteurs_par_defaut(registre))
        del lecteurs[manquant]
        rapport = _controler(carte, registre, lecteurs)
        assert "QC-OCR-ABSENT" in _echecs(rapport) and not rapport.conforme


def test_un_lecteur_qui_ne_sait_pas_lire_le_format_est_un_echec(carte, registre):
    lecteurs = dict(ocr.lecteurs_par_defaut(registre))
    lecteurs["png"] = ocr.LecteurTexteVectoriel()  # ne lit que svg et pdf
    assert "QC-OCR-ABSENT" in _echecs(_controler(carte, registre, lecteurs))


def test_un_lecteur_qui_echoue_est_un_echec_pas_un_succes(carte, registre):
    class Casse:
        nom, version, nature, formats = "casse", "1", ocr.NATURE_REEL, ("png",)

        def lire(self, octets, format_, plan):
            raise ocr.LectureImpossible("profil OCR absent")

    rapport = _controler(carte, registre, {**ocr.lecteurs_par_defaut(registre), "png": Casse()})
    assert "QC-OCR" in _echecs(rapport)


# -- altération des fichiers ---------------------------------------------------------------------------------------
def test_un_png_retouche_apres_composition_est_pris_par_la_reproductibilite_et_la_lecture(carte, registre):
    image = png.decoder(carte.artefacts["png"])
    ligne = next(lg for lg in carte.plan.lignes if lg.id == "critique.telephone.0")
    pixels = bytearray(image.pixels)
    x0, y0, x1, y1 = (int(v) for v in ligne.boite)
    for y in range(y0, y1):
        for x in range(x0 + 120, x0 + 150):
            pixels[3 * (y * image.largeur + x) : 3 * (y * image.largeur + x) + 3] = bytes(carte.plan.rects[0].couleur)
    truque = dataclasses.replace(
        carte,
        artefacts={
            **carte.artefacts,
            "png": png.encoder(
                png.ImageRVB(image.largeur, image.hauteur, bytes(pixels)), png.metadonnees(carte.artefacts["png"])
            ),
        },
    )
    rapport = _controler(truque, registre)
    assert {"QC-REPRODUCTIBILITE", "QC-OCR"} <= _echecs(rapport)


def test_un_svg_ou_un_pdf_retouche_est_pris(carte, registre):
    svg = carte.artefacts["svg"].replace(b"+1 450 555 0142", b"+1 450 555 0149")
    assert svg != carte.artefacts["svg"]
    rapport = _controler(dataclasses.replace(carte, artefacts={**carte.artefacts, "svg": svg}), registre)
    assert {"QC-REPRODUCTIBILITE", "QC-OCR"} <= _echecs(rapport)
    pdf = carte.artefacts["pdf"].replace(b"/Lang (fr-CA)", b"/Lang (en-CA)")
    rapport = _controler(dataclasses.replace(carte, artefacts={**carte.artefacts, "pdf": pdf}), registre)
    assert "QC-REPRODUCTIBILITE" in _echecs(rapport)


def test_jeu_d_artefacts_incomplet_pris(carte, registre):
    sans_pdf = {k: v for k, v in carte.artefacts.items() if k != "pdf"}
    rapport = _controler(dataclasses.replace(carte, artefacts=sans_pdf), registre)
    assert "QC-FORMAT" in _echecs(rapport)


# -- géométrie, contraste, taille, impression -------------------------------------------------------------------------
def test_contraste_insuffisant_pris_sur_les_pixels_du_png_et_seulement_pour_la_ligne_fautive(carte, registre):
    # Titre en bleu sombre sur un panneau bleu nuit : illisible ; les autres lignes (blanc sur bleu) restent lisibles.
    plan = dataclasses.replace(
        carte.plan,
        elements=tuple(
            dataclasses.replace(e, couleur=(20, 70, 110)) if isinstance(e, p.Ligne) and e.id == "titre.fr" else e
            for e in carte.plan.elements
        ),
    )
    truquee = _recomposer(carte, registre, plan)
    rapport = _controler(truquee, registre)
    assert "QC-CONTRASTE" in _echecs(rapport)
    fautives = [x["ligne"] for x in _code(rapport, "QC-CONTRASTE")[0]["mesure"]["lignes_en_echec"]]
    assert fautives and all(ligne.startswith("titre.fr#") for ligne in fautives), fautives


def test_texte_sous_la_taille_minimale_pris(carte, registre):
    ligne = next(lg for lg in carte.plan.lignes if lg.id == "mention.0")
    truquee = _remplacer_ligne(carte, registre, "mention.0", taille_px=ligne.taille_px * 0.6)
    assert "QC-TAILLE-MIN" in _echecs(_controler(truquee, registre))


def test_texte_hors_de_la_zone_de_securite_pris(carte, registre):
    ligne = next(lg for lg in carte.plan.lignes if lg.id == "titre.fr")
    decale = dataclasses.replace(ligne, x=2.0, boite=(2.0, ligne.boite[1], 2.0 + ligne.largeur_px, ligne.boite[3]))
    plan = dataclasses.replace(carte.plan, elements=tuple(decale if e is ligne else e for e in carte.plan.elements))
    rapport = _controler(_recomposer(carte, registre, plan), registre)
    assert "QC-ZONE-SECURITE" in _echecs(rapport)


def test_texte_dans_une_bande_reservee_du_neuf_seizieme_pris(registre):
    comp = _comp(registre, f.brief("banniere_social", "1080x1920"))
    haut = comp.plan.zones_reservees[0]
    ligne = comp.plan.lignes[0]
    dans_bande = dataclasses.replace(
        ligne, baseline=haut[3] - 10, boite=(ligne.boite[0], haut[3] - 40, ligne.boite[2], haut[3] - 5)
    )
    plan = dataclasses.replace(comp.plan, elements=tuple(dans_bande if e is ligne else e for e in comp.plan.elements))
    assert "QC-ZONE-SECURITE" in _echecs(_controler(_recomposer(comp, registre, plan), registre))


def test_rendu_d_impression_sous_300_ppp_refuse(registre):
    comp = _comp(registre, f.brief(ppp=150))
    rapport = _controler(comp, registre)
    assert "QC-RESOLUTION" in _echecs(rapport) and not rapport.conforme


def test_fond_perdu_insuffisant_pris(carte, registre):
    plan = dataclasses.replace(carte.plan, fond_perdu_px=10)
    rapport = _controler(_recomposer(carte, registre, plan), registre)
    assert "QC-FOND-PERDU" in _echecs(rapport)


def test_boite_trim_fausse_dans_le_pdf_prise(carte, registre):
    pdf = carte.artefacts["pdf"]
    faux = pdf.replace(b"/TrimBox [", b"/TrimBox [1 ")
    assert faux != pdf
    rapport = _controler(dataclasses.replace(carte, artefacts={**carte.artefacts, "pdf": faux}), registre)
    assert not rapport.conforme


def test_resolution_du_fond_genere_en_impression(registre):
    donnees = f.brief(fond={"mode": "genere", "sujet": "toiture de bardeaux gris sous un ciel de printemps"})
    petit = _comp(registre, donnees, fond_png=f.fond_synthetique(200, 120), provenance=f.PROVENANCE)
    rapport = _controler(petit, registre, verdict_licence=lambda: {"conforme": True, "codes": []})
    assert "QC-RESOLUTION" in _echecs(rapport)  # 200 px pour 3,75 po : 53 ppp
    grand = _comp(registre, donnees, fond_png=f.fond_synthetique(1200, 700), provenance=f.PROVENANCE)
    rapport = _controler(grand, registre, verdict_licence=lambda: {"conforme": True, "codes": []})
    assert "QC-RESOLUTION" not in _echecs(rapport) and rapport.conforme, rapport.echecs_critiques()


def test_ecran_fond_trop_agrandi_pris(registre):
    donnees = f.brief(
        "banniere_social", fond={"mode": "genere", "sujet": "toiture de bardeaux gris sous un ciel de printemps"}
    )
    comp = _comp(registre, donnees, fond_png=f.fond_synthetique(300, 300), provenance=f.PROVENANCE)
    assert "QC-RESOLUTION" in _echecs(
        _controler(comp, registre, verdict_licence=lambda: {"conforme": True, "codes": []})
    )


# -- langue ------------------------------------------------------------------------------------------------------
def _bilingue(en_texte="Your roof, with confidence"):
    donnees = f.brief(
        "banniere_social", langues=["fr", "en"], elements_critiques=f.critiques("telephone"), mentions_obligatoires=[]
    )
    donnees["textes"] = {"titre": {"fr": "Votre toiture en confiance", "en": en_texte}}
    return donnees


def test_bilingue_avec_francais_dominant_passe(registre):
    rapport = _controler(_comp(registre, _bilingue()), registre)
    constat = _code(rapport, "QC-LANGUE-FR")[0]
    assert constat["ok"] and "HEURISTIQUE" in constat["detail"] and constat["mesure"]["ratio"] >= 2.0


def test_anglais_aussi_visible_que_le_francais_pris_et_declare_comme_heuristique(registre):
    comp = _comp(registre, _bilingue())
    egal = tuple(
        dataclasses.replace(e, taille_px=next(x.taille_px for x in comp.plan.lignes if x.langue == "fr"))
        if isinstance(e, p.Ligne) and e.langue == "en"
        else e
        for e in comp.plan.elements
    )
    rapport = _controler(_recomposer(comp, registre, dataclasses.replace(comp.plan, elements=egal)), registre)
    constat = _code(rapport, "QC-LANGUE-FR")[0]
    assert not constat["ok"] and "avocat" in constat["detail"]


def test_seuil_de_francais_parametrable(registre):
    comp = _comp(registre, _bilingue())
    strict = _controler(comp, registre, politique=controle.PolitiqueControle(ratio_francais_min=50.0))
    assert "QC-LANGUE-FR" in _echecs(strict)


# -- marquage IA, licence, prix, mention de licence --------------------------------------------------------------------
GENERE = {"mode": "genere", "sujet": "toiture de bardeaux gris sous un ciel de printemps"}


def _generee(registre, **kw):
    return _comp(registre, f.brief(fond=GENERE, **kw), fond_png=f.fond_synthetique(1200, 700), provenance=f.PROVENANCE)


def test_visuel_genere_conforme_avec_licence_reverifiee(registre):
    comp = _generee(registre)
    rapport = _controler(
        comp, registre, verdict_licence=lambda: {"conforme": True, "codes": [], "fournisseur_id": "image.x"}
    )
    assert rapport.conforme, rapport.echecs_critiques()
    assert rapport.donnees["ia_generee"] is True
    assert _code(rapport, "QC-LICENCE")[0]["mesure"]["fournisseur"] == "image.x"


def test_licence_non_verifiee_est_un_echec_pas_un_oubli(registre):
    rapport = _controler(_generee(registre), registre)  # aucun verdict fourni
    assert "QC-LICENCE" in _echecs(rapport) and "NON vérifiée" in _code(rapport, "QC-LICENCE")[0]["detail"]


def test_licence_devenue_non_conforme_apres_la_generation_est_prise(registre):
    verdict = {"conforme": False, "codes": ["SEUIL_REVENU_DEPASSE"], "fournisseur_id": "image.x"}
    rapport = _controler(_generee(registre), registre, verdict_licence=lambda: verdict)
    assert "QC-LICENCE" in _echecs(rapport)
    assert "SEUIL_REVENU_DEPASSE" in _code(rapport, "QC-LICENCE")[0]["detail"]


def test_marquage_ia_absent_ou_faux_pris(registre):
    comp = _generee(registre)
    ok = lambda: {"conforme": True, "codes": []}  # noqa: E731
    menteur = dataclasses.replace(comp, marquage={**comp.marquage, "ia_generee": False})
    assert "QC-MARQUAGE-IA" in _echecs(_controler(menteur, registre, verdict_licence=ok))
    sans_provenance = dataclasses.replace(comp, marquage={**comp.marquage, "provenance": None})
    assert "QC-MARQUAGE-IA" in _echecs(_controler(sans_provenance, registre, verdict_licence=ok))


def test_metadonnees_png_retirees_ou_modifiees_prises(registre):
    comp = _generee(registre)
    image = png.decoder(comp.artefacts["png"])
    nu = png.encoder(image)  # PNG sans aucune métadonnée de marquage
    truque = dataclasses.replace(comp, artefacts={**comp.artefacts, "png": nu})
    rapport = _controler(truque, registre, verdict_licence=lambda: {"conforme": True, "codes": []})
    assert "QC-MARQUAGE-IA" in _echecs(rapport)


def test_prix_expire_pris(registre):
    donnees = f.brief(elements_critiques=f.critiques("prix"))
    donnees["elements_critiques"][0]["valide_jusqu_au"] = "2026-10-31"
    comp = _comp(registre, donnees)
    rapport = _controler(comp, registre)
    assert "QC-PRIX-VALIDITE" in _echecs(rapport)
    donnees["elements_critiques"][0]["valide_jusqu_au"] = "2026-11-01"  # le jour même : encore valide
    assert "QC-PRIX-VALIDITE" not in _echecs(_controler(_comp(registre, donnees), registre))


def test_mention_exigee_par_la_licence_du_modele_doit_etre_posee(registre):
    comp = _generee(registre)
    ok = lambda: {"conforme": True, "codes": []}  # noqa: E731
    rapport = _controler(comp, registre, verdict_licence=ok, mention_licence_requise="Powered by Duix.com")
    assert "QC-MENTION-LICENCE" in _echecs(rapport)
    avec = _generee(registre, mentions_obligatoires=["Powered by Duix.com"])
    rapport = _controler(avec, registre, verdict_licence=ok, mention_licence_requise="Powered by Duix.com")
    assert "QC-MENTION-LICENCE" not in _echecs(rapport) and rapport.conforme


def test_police_de_licence_non_ofl_prise_par_le_controle(carte, registre):
    class Registre:
        def obtenir(self, identifiant):
            police = registre.obtenir(identifiant)
            return dataclasses.replace(police, licence="Apache-2.0")

    rapport = controle.controler(carte, Registre(), ocr.lecteurs_par_defaut(registre), maintenant=MAINTENANT)
    assert "QC-POLICES" in _echecs(rapport)


def test_une_demande_cmjn_est_dite_non_realisee_sans_bloquer_la_revue(registre):
    comp = _comp(registre, f.brief("banniere_social", couleur="cmjn"))
    rapport = _controler(comp, registre)
    constat = _code(rapport, "QC-COULEUR")[0]
    assert constat["ok"] is False and constat["critique"] is False and "NON réalisé" in constat["detail"]
    assert rapport.conforme, rapport.echecs_critiques()  # un avertissement ne bloque pas
    assert _code(_controler(_comp(registre, f.brief("banniere_social")), registre), "QC-COULEUR")[0]["ok"] is True
