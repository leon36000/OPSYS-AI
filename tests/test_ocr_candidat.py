"""Frontière OCR non fiable : documents, identités et profils entièrement fictifs."""

from __future__ import annotations

import copy
import importlib
import json

import pytest


def _module():
    # L'import différé permet un oracle rouge sur la capacité absente, sans stub produit.
    assert importlib.util.find_spec("opsys.ocr_candidat") is not None, "frontière OCR absente"
    return importlib.import_module("opsys.ocr_candidat")


def _contexte(module):
    return module.ContexteOCR(
        lot_id="12345678-1234-4234-8234-123456789abc", source_sha256="a" * 64,
        revision_source=2, configuration_sha256="b" * 64,
        rasteriseur="pypdfium2-5.13.0", moteur="tesseract-5.5.0", leptonica="leptonica-1.84.1",
        pdfium_sha256="c" * 64, modele_sha256="d" * 64,
    )


def _candidat():
    return {
        "schema_version": 1, "genre": "m5.ocr_scan_candidat", "statut": "CANDIDAT_A_REVOIR",
        "lot_id": "12345678-1234-4234-8234-123456789abc", "source_sha256": "a" * 64,
        "revision_source": 2, "configuration_sha256": "b" * 64,
        "profil": {"rasteriseur": "pypdfium2-5.13.0", "moteur": "tesseract-5.5.0",
                   "leptonica": "leptonica-1.84.1", "pdfium_sha256": "c" * 64,
                   "modele_sha256": "d" * 64, "langue": "fra"},
        "page": {"numero": 1, "largeur_px": 100, "hauteur_px": 100,
                 "tokens": [{"texte": "Pièce-fictive-école", "x0": 10, "y0": 20, "x1": 90,
                             "y1": 30, "confiance_brute": 92.375}]},
    }


def _json(value):
    return json.dumps(value, ensure_ascii=False).encode()


def _refus_json(value):
    module = _module()
    with pytest.raises(module.OCRContratErreur) as erreur:
        module.decoder_candidat(_json(value), contexte=_contexte(module))
    assert erreur.value.code == "OCR_RESULTAT_INVALIDE"
    assert "Pièce-fictive" not in str(erreur.value) and "CANARI" not in str(erreur.value)


def test_candidat_francais_lie_source_et_profil_sans_approbation():
    module = _module()
    brut = _json(_candidat())
    resultat = module.decoder_candidat(brut, contexte=_contexte(module))
    assert resultat == _candidat() and brut == _json(_candidat())
    assert resultat["statut"] == "CANDIDAT_A_REVOIR"
    assert resultat["page"]["tokens"][0]["confiance_brute"] == 92.375


@pytest.mark.parametrize("chemin,valeur", [
    (("schema_version",), True), (("schema_version",), 2), (("statut",), "VALIDE"),
    (("genre",), "m5.facture"), (("lot_id",), "12345678-1234-4234-8234-123456789ABC"),
    (("source_sha256",), "e" * 64), (("revision_source",), True), (("revision_source",), 3),
    (("configuration_sha256",), "e" * 64), (("profil", "langue"), "eng"),
    (("profil", "rasteriseur"), "pypdfium2-5.3.0"), (("profil", "moteur"), "tesseract-5.4.0"),
    (("profil", "leptonica"), "leptonica-1.83.0"), (("profil", "pdfium_sha256"), "e" * 64),
    (("profil", "modele_sha256"), "e" * 64), (("page", "numero"), 2),
    (("page", "largeur_px"), True), (("page", "largeur_px"), 0),
    (("page", "largeur_px"), 4097), (("page", "hauteur_px"), 100.0),
    (("page", "tokens"), []), (("page", "tokens", 0, "x0"), -1),
    (("page", "tokens", 0, "x0"), True), (("page", "tokens", 0, "x1"), 101),
    (("page", "tokens", 0, "x1"), 10), (("page", "tokens", 0, "y1"), 101),
    (("page", "tokens", 0, "y1"), 20), (("page", "tokens", 0, "confiance_brute"), -1),
    (("page", "tokens", 0, "confiance_brute"), 100.01),
    (("page", "tokens", 0, "confiance_brute"), True),
    (("page", "tokens", 0, "confiance_brute"), "92"),
    (("page", "tokens", 0, "confiance_brute"), float("nan")),
    (("page", "tokens", 0, "confiance_brute"), float("inf")),
    (("page", "tokens", 0, "texte"), ""), (("page", "tokens", 0, "texte"), "  "),
    (("page", "tokens", 0, "texte"), "CANARI\x00"),
    (("page", "tokens", 0, "texte"), "CANARI\n"),
    (("page", "tokens", 0, "texte"), "CANARI\x85"),
    (("page", "tokens", 0, "texte"), "CANARI\ufffd"),
    (("page", "tokens", 0, "texte"), "é" * 257),
])
def test_refuse_mismatch_types_geometrie_score_et_texte(chemin, valeur):
    candidat = _candidat()
    parent = candidat
    for cle in chemin[:-1]:
        parent = parent[cle]
    parent[chemin[-1]] = valeur
    _refus_json(candidat)


@pytest.mark.parametrize("chemin", [(), ("profil",), ("page",), ("page", "tokens", 0)])
def test_champs_inconnus_refuses_sans_extraction_financiere(chemin):
    candidat = _candidat()
    parent = candidat
    for cle in chemin:
        parent = parent[cle]
    parent["montant_CANARI"] = "100.00"
    _refus_json(candidat)


@pytest.mark.parametrize("brut", [b'{}', b'[]', b'null', b'\xff', b'{', b'\xef\xbb\xbf{}',
                                  b'{"schema_version":1,"schema_version":1}', b' ' * 262145])
def test_json_protocole_ferme_borne_avant_decodage(brut):
    module = _module()
    with pytest.raises(module.OCRContratErreur, match="résultat OCR refusé"):
        module.decoder_candidat(brut, contexte=_contexte(module))


def test_doublon_niche_et_substitut_unicode_refuses():
    module = _module()
    brut = _json(_candidat()).replace(b'"langue": "fra"', b'"langue":"fra","langue":"fra"')
    with pytest.raises(module.OCRContratErreur):
        module.decoder_candidat(brut, contexte=_contexte(module))
    brut = _json(_candidat()).replace("Pièce-fictive-école".encode(), b'\\ud800')
    with pytest.raises(module.OCRContratErreur):
        module.decoder_candidat(brut, contexte=_contexte(module))


def test_limites_pixels_tokens_et_octets_inclusives():
    module = _module()
    candidat = _candidat()
    candidat["page"].update(largeur_px=2000, hauteur_px=2000)
    candidat["page"]["tokens"] = [dict(candidat["page"]["tokens"][0], texte="é" * 256)] * 128
    assert sum(len(t["texte"].encode()) for t in candidat["page"]["tokens"]) == 65536
    assert module.decoder_candidat(_json(candidat), contexte=_contexte(module)) == candidat
    trop = copy.deepcopy(candidat)
    trop["page"]["tokens"].append(dict(trop["page"]["tokens"][0], texte="x"))
    _refus_json(trop)
    trop = copy.deepcopy(candidat)
    trop["page"]["hauteur_px"] = 2001
    _refus_json(trop)
    candidat["page"]["tokens"] = [dict(candidat["page"]["tokens"][0], texte="x")] * 2048
    assert len(module.decoder_candidat(_json(candidat), contexte=_contexte(module))["page"]["tokens"]) == 2048
    candidat["page"]["tokens"].append(candidat["page"]["tokens"][0])
    _refus_json(candidat)


def _tsv():
    return (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t\n"
        "2\t1\t1\t0\t0\t0\t10\t20\t80\t10\t-1\t\n"
        "3\t1\t1\t1\t0\t0\t10\t20\t80\t10\t-1\t\n"
        "4\t1\t1\t1\t1\t0\t10\t20\t80\t10\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t80\t10\t92.375\tPièce-fictive-école\n"
    ).encode()


def test_tsv_tesseract_conserve_texte_boites_score_et_metadonnees_attendues():
    module = _module()
    resultat = module.candidat_depuis_tsv(_tsv(), contexte=_contexte(module), largeur_px=100, hauteur_px=100)
    assert resultat == _candidat()
    assert module.decoder_candidat(_json(resultat), contexte=_contexte(module)) == resultat


@pytest.mark.parametrize("avant,apres", [
    (b'level\t', b'Level\t'), (b'1\t1\t0\t0\t0\t0\t0\t0', b'1\t2\t0\t0\t0\t0\t0\t0'),
    (b'100\t100\t-1', b'101\t100\t-1'), (b'100\t100\t-1', b'100\t100\t0'),
    (b'2\t1\t1\t0\t0\t0', b'2\t1\t1\t1\t0\t0'),
    (b'5\t1\t1\t1\t1\t1', b'5\t1\t1\t1\t2\t1'),
    (b'5\t1\t1\t1\t1\t1', b'6\t1\t1\t1\t1\t1'),
    (b'92.375\t', b'-1\t'), (b'92.375\t', b'NaN\t'),
    (b'92.375\t', b'Infinity\t'), (b'92.375\t', b'1e2\t'),
    (b'92.375\t', b'100.1\t'), (b'92.375\t', b'92.375\tCANARI\t'),
    (b'10\t20\t80\t10\t92', b'10\t20\t91\t10\t92'),
    (b'10\t20\t80\t10\t92', b'+10\t20\t80\t10\t92'),
])
def test_tsv_incoherent_refuse_entierement(avant, apres):
    module = _module()
    with pytest.raises(module.OCRContratErreur) as erreur:
        module.candidat_depuis_tsv(
            _tsv().replace(avant, apres), contexte=_contexte(module), largeur_px=100, hauteur_px=100,
        )
    assert erreur.value.code == "OCR_TSV_INVALIDE" and "CANARI" not in str(erreur.value)


@pytest.mark.parametrize("mode", ["sans_parent", "duplique", "sans_mot", "taille", "utf8", "lignes"])
def test_tsv_bornes_parents_uniques_et_mot_obligatoire(mode):
    module = _module()
    lignes = _tsv().splitlines(keepends=True)
    brut = {
        "sans_parent": b''.join(lignes[:4] + lignes[5:]),
        "duplique": b''.join(lignes + lignes[-1:]),
        "sans_mot": b''.join(lignes[:-1]), "taille": b'x' * 524289,
        "utf8": b'\xff', "lignes": lignes[0] + lignes[1] * 4097,
    }[mode]
    with pytest.raises(module.OCRContratErreur):
        module.candidat_depuis_tsv(brut, contexte=_contexte(module), largeur_px=100, hauteur_px=100)


def test_contexte_attendu_immuable_et_malformed_refuse():
    module = _module()
    contexte = _contexte(module)
    with pytest.raises(AttributeError):
        contexte.revision_source = 9
    donnees = {nom: getattr(contexte, nom) for nom in contexte.__dataclass_fields__}
    for champ, valeur in [("revision_source", True), ("revision_source", 0),
                          ("source_sha256", "A" * 64), ("moteur", "tesseract-CANARI"),
                          ("rasteriseur", "pypdfium2-5.13.0/CANARI")]:
        with pytest.raises(module.OCRContratErreur):
            module.ContexteOCR(**dict(donnees, **{champ: valeur}))


@pytest.mark.parametrize("champ,valeur", [
    ("rasteriseur", "tesseract-5.5.0"), ("moteur", "pypdfium2-5.13.0"),
    ("leptonica", "python-3.11.0"), ("moteur", "tesseract-" + "0" * 51 + ".0.0"),
])
def test_contexte_refuse_famille_incorrecte_et_identite_plus_de_64_caracteres(champ, valeur):
    module = _module()
    contexte = _contexte(module)
    valeurs = {nom: getattr(contexte, nom) for nom in contexte.__dataclass_fields__}
    with pytest.raises(module.OCRContratErreur) as erreur:
        module.ContexteOCR(**dict(valeurs, **{champ: valeur}))
    assert erreur.value.code == "OCR_CONTEXTE_INVALIDE"
