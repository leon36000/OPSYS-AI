"""Registre de polices OFL : manifeste, empreinte, licence, lecture TrueType (carrés, courbes quadratiques,
composites)."""

from __future__ import annotations

import hashlib
import json

import fabriques_studio as f
import police_pixel
import pytest
from m7_marketing.studio import polices


@pytest.fixture
def dossier(tmp_path):
    return f.ecrire_polices(tmp_path / "polices")


def _manifeste(dossier):
    return json.loads((dossier / "polices.json").read_text(encoding="utf-8"))


def _ecrire(dossier, manifeste):
    (dossier / "polices.json").write_text(json.dumps(manifeste), encoding="utf-8")


def test_chargement_hors_production_puis_resume(dossier):
    registre = polices.charger_dossier(dossier, production=False)
    assert registre.ids() == (f.POLICE_ID,)
    police = registre.obtenir(f.POLICE_ID)
    assert police.licence == "OFL-1.1" and police.fictif
    assert (
        registre.resumes()[0]["sha256"] == hashlib.sha256((dossier / "PixelTest-Regular.ttf").read_bytes()).hexdigest()
    )


def test_police_fictive_refusee_en_production(dossier):
    with pytest.raises(polices.PoliceErreur) as erreur:
        polices.charger_dossier(dossier, production=True)
    assert erreur.value.code == polices.REJ_FICTIVE


def test_sans_manifeste_refus_typé(tmp_path):
    with pytest.raises(polices.PoliceErreur) as erreur:
        polices.charger_dossier(tmp_path, production=False)
    assert erreur.value.code == polices.REJ_ABSENTE


@pytest.mark.parametrize("licence", ["Apache-2.0", "CC0-1.0", "UFL-1.0", "OFL-1.1 ", "", None])
def test_seule_la_licence_ofl_passe(dossier, licence):
    manifeste = _manifeste(dossier)
    manifeste["polices"][0]["licence"] = licence
    _ecrire(dossier, manifeste)
    with pytest.raises(polices.PoliceErreur) as erreur:
        polices.charger_dossier(dossier, production=False)
    assert erreur.value.code == polices.REJ_LICENCE


def test_le_fichier_ne_doit_pas_contredire_le_manifeste(tmp_path):
    dossier = f.ecrire_polices(tmp_path / "p", notice_ofl=False)
    with pytest.raises(polices.PoliceErreur) as erreur:
        polices.charger_dossier(dossier, production=False)
    assert erreur.value.code == polices.REJ_LICENCE
    assert "Open Font License" in erreur.value.detail


def test_fichier_remplace_apres_epinglage_refuse(dossier):
    (dossier / "PixelTest-Regular.ttf").write_bytes(police_pixel.ttf_octets(famille="Autre police"))
    with pytest.raises(polices.PoliceErreur) as erreur:
        polices.charger_dossier(dossier, production=False)
    assert erreur.value.code == polices.REJ_EMPREINTE


@pytest.mark.parametrize("sha", ["", "A" * 64, "z" * 64, "ab", None])
def test_empreinte_absente_ou_mal_formee_refusee(dossier, sha):
    manifeste = _manifeste(dossier)
    manifeste["polices"][0]["sha256"] = sha
    _ecrire(dossier, manifeste)
    with pytest.raises(polices.PoliceErreur) as erreur:
        polices.charger_dossier(dossier, production=False)
    assert erreur.value.code == polices.REJ_EMPREINTE


@pytest.mark.parametrize("fichier", ["../x.ttf", "/etc/passwd", "sous/dossier.ttf", "police.otf", "a b.ttf", ""])
def test_chemin_dans_le_nom_de_fichier_refuse(dossier, fichier):
    manifeste = _manifeste(dossier)
    manifeste["polices"][0]["fichier"] = fichier
    _ecrire(dossier, manifeste)
    with pytest.raises(polices.PoliceErreur) as erreur:
        polices.charger_dossier(dossier, production=False)
    assert erreur.value.code == polices.REJ_MANIFESTE


def test_lien_symbolique_refuse(tmp_path):
    dossier = f.ecrire_polices(tmp_path / "p")
    reel = dossier / "PixelTest-Regular.ttf"
    cible = tmp_path / "ailleurs.ttf"
    cible.write_bytes(reel.read_bytes())
    reel.unlink()
    reel.symlink_to(cible)
    with pytest.raises(polices.PoliceErreur) as erreur:
        polices.charger_dossier(dossier, production=False)
    assert erreur.value.code == polices.REJ_FICHIER


def test_manifeste_hostile(dossier):
    for corps in (
        "[]",
        "{",
        json.dumps({"schema": "x", "polices": []}),
        json.dumps({"schema": polices.SCHEMA_MANIFESTE, "polices": [], "extra": 1}),
        json.dumps({"schema": polices.SCHEMA_MANIFESTE, "polices": [1]}),
    ):
        (dossier / "polices.json").write_text(corps, encoding="utf-8")
        with pytest.raises(polices.PoliceErreur):
            polices.charger_dossier(dossier, production=False)


def test_url_source_obligatoire_https(dossier):
    manifeste = _manifeste(dossier)
    manifeste["polices"][0]["source_url"] = "http://exemple.test/police"
    _ecrire(dossier, manifeste)
    with pytest.raises(polices.PoliceErreur):
        polices.charger_dossier(dossier, production=False)


def test_identifiant_en_double_refuse(dossier):
    manifeste = _manifeste(dossier)
    manifeste["polices"].append(dict(manifeste["polices"][0]))
    _ecrire(dossier, manifeste)
    with pytest.raises(polices.PoliceErreur):
        polices.charger_dossier(dossier, production=False)


@pytest.mark.parametrize(
    "options", [{}, {"loca_courte": True}, {"cmap12": True}, {"loca_courte": True, "cmap12": True}]
)
def test_lecteur_ttf_variantes_de_tables(tmp_path, options):
    ttf = polices.TTF(police_pixel.ttf_octets(**options))
    assert ttf.unites_par_em == 1000
    assert ttf.largeur("A", 1000) == 600
    assert ttf.largeur("AB", 10) == pytest.approx(12.0)
    assert ttf.couvre("Allô, é!") == set()
    assert ttf.couvre("日本") == {"日", "本"}


def test_caractere_sans_glyphe_jamais_remplace(dossier):
    police = polices.charger_dossier(dossier, production=False).obtenir(f.POLICE_ID)
    with pytest.raises(polices.PoliceErreur) as erreur:
        police.ttf.contours("日")
    assert erreur.value.code == polices.REJ_GLYPHE


def test_contours_d_un_carre_de_pixels():
    ttf = polices.TTF(police_pixel.ttf_octets())
    contours = ttf.contours("I")
    assert contours and all(len(c[1]) == 4 for c in contours)
    xs = {p for c in contours for p in (c[0][0],)}
    assert xs <= {0.0, 100.0, 200.0, 300.0, 400.0}


def test_glyphes_a_courbes_et_composites_decodes():
    ttf = polices.TTF(police_pixel.ttf_octets())
    cercle = ttf.contours(chr(police_pixel.CERCLE))
    assert len(cercle) == 1 and all(s[0] == "Q" for s in cercle[0][1])
    deux = ttf.contours(chr(police_pixel.DEUX_CERCLES))
    assert len(deux) == 2
    reduit = ttf.contours(chr(police_pixel.CERCLE_REDUIT))
    assert len(reduit) == 1
    sommets = [(s[-2], s[-1]) for s in reduit[0][1]]
    assert max(x for x, _ in sommets) == pytest.approx(400.0)  # (800 × 0,5)


@pytest.mark.parametrize("coupe", [20, 60, 200])
def test_ttf_tronque_refuse_sans_exception_brute(coupe):
    with pytest.raises(polices.PoliceErreur):
        polices.TTF(police_pixel.ttf_octets()[:coupe])


def test_police_cff_refusee():
    with pytest.raises(polices.PoliceErreur):
        polices.TTF(b"OTTO" + b"\x00" * 64)
