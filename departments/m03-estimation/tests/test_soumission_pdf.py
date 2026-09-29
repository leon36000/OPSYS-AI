"""Tests de la soumission brouillon en PDF (PLAN T2.3-f, `soumission_pdf.py`).

Le PDF est produit puis RELU (texte extrait par `pypdf`, dépendance de test) : on ne prouve pas que des
octets existent, on prouve ce qu'un lecteur y lit. Les rendus exigent l'extra `soumission` (ReportLab) ; sans
lui ils sont sautés en local, jamais en CI (`test_en_ci_la_brique_et_pypdf_sont_installees`). Données
fictives (AGENTS.md).
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import subprocess
import sys
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable, soumission, soumission_pdf, verdicts  # noqa: E402

FICTIF = True
_RACINE = Path(__file__).resolve().parents[3]
_HORODATAGE = "2026-09-28T14:00:00-04:00"
_ID = "M3-DEVIS-pdf-001"

# Les codes REJ-SOUMISSION-PDF-* exercés ICI ; TROP-VOLUMINEUX l'est dans test_soumission_pdf_outil.py
# (c'est le verdict de l'adaptateur outils.py, pas du module pur).
_CODES_EXERCES_PAR_CE_FICHIER = {
    "REJ-SOUMISSION-PDF-BRIQUE-ABSENTE",
    "REJ-SOUMISSION-PDF-HORODATAGE-INVALIDE",
    "REJ-SOUMISSION-PDF-MONTANT-INVALIDE",
    "REJ-SOUMISSION-PDF-CARACTERE-NON-SUPPORTE",
    "REJ-SOUMISSION-PDF-RENDU-IMPOSSIBLE",
}
_CODE_DE_L_ADAPTATEUR = "REJ-SOUMISSION-PDF-TROP-VOLUMINEUX"


@pytest.fixture
def brique():
    """Saute le rendu quand l'extra `soumission` ou `pypdf` manque (jamais en CI : voir plus bas)."""
    installe, raison = soumission_pdf.pdf_installe()
    if not installe:
        pytest.skip(raison)
    pytest.importorskip("pypdf")


def _lignes(n=2):
    modeles = [
        ("Gouttière alu 5 po", "30", "pi_lin", "10.00"),
        ("Pose, main-d'œuvre", "12.5", "h", "55.10"),
    ]
    return [
        {
            "description": modeles[i % 2][0] + ("" if i < 2 else f" (poste {i})"),
            "quantite": modeles[i % 2][1],
            "unite": modeles[i % 2][2],
            "cout_unitaire": modeles[i % 2][3],
            "reference_besoin_materiau": None,
        }
        for i in range(n)
    ]


def _devis(lignes=None, taux="0.35", horodatage=_HORODATAGE, devis_id=_ID):
    """Un devis réellement produit par devis_durable.creer_devis (Decimal, prix calculés)."""
    devis, verdict = devis_durable.creer_devis(
        devis_id=devis_id,
        lead_id="lead-pdf-1",
        chantier_id=None,
        lignes=lignes if lignes is not None else _lignes(),
        taux_marge=taux,
        horodatage=horodatage,
        registre_cible=[],
    )
    assert verdict is None, verdict
    return devis


def _pdf(devis):
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert verdict is None, verdict
    return octets


def _pages(octets):
    from pypdf import PdfReader

    return [_norm(page.extract_text()) for page in PdfReader(io.BytesIO(octets)).pages]


def _norm(texte):
    """Blancs (espaces insécables compris) ramenés à une espace : on compare ce qui se lit."""
    return " ".join(texte.split())


def _texte(octets):
    return " ".join(_pages(octets))


def _compact(texte):
    """Sans aucun blanc : une colonne étroite peut couper une charge au milieu d'un mot."""
    return "".join(texte.split())


# -- le PDF, relu ----------------------------------------------------------------------------------
def test_le_pdf_est_un_pdf_d_une_page_qui_porte_les_champs_du_devis(brique):
    devis = _devis()
    octets = _pdf(devis)
    assert octets.startswith(b"%PDF-") and octets.rstrip().endswith(b"%%EOF")
    pages = _pages(octets)
    assert len(pages) == 1
    texte = pages[0]
    assert _ID in texte
    assert "Gouttière alu 5 po" in texte
    assert "Pose, main-d'œuvre" in texte  # « œ » : la raison d'être de ReportLab plutôt que fpdf2
    assert "30 pi_lin" in texte and "12,5 h" in texte
    assert _norm("13,50\u00a0$") in texte and _norm("405,00\u00a0$") in texte
    assert _norm("1\u00a0334,88\u00a0$") in texte  # 405,00 + 12,5 x 74,39 = 929,88
    assert devis["prix_total"] == Decimal("1334.88")
    assert "Prix total" in texte and "Taxes (TPS/TVQ) en sus" in texte
    assert "28 septembre 2026, 14 h 00 (UTC-04:00)" in texte
    assert "Statut : brouillon" in texte


def test_les_metadonnees_viennent_de_la_donnee(brique):
    from pypdf import PdfReader

    meta = PdfReader(io.BytesIO(_pdf(_devis()))).metadata
    assert meta["/Title"] == f"Soumission brouillon {_ID}"
    assert meta["/CreationDate"] == "D:20260928140000-04'00'"
    assert meta["/ModDate"] == meta["/CreationDate"]
    assert meta["/Creator"] == "OPSYS-AI M3 Estimation"


def test_le_pdf_reprend_les_memes_champs_client_que_le_html(brique):
    """Même source : `contenu_client`. Chaque champ du HTML se retrouve, mis en forme, dans le PDF."""
    devis = _devis(_lignes(3))
    contenu, verdict = soumission.contenu_client(devis)
    assert verdict is None
    html, verdict = soumission.generer_brouillon_html(devis)
    assert verdict is None
    texte = _texte(_pdf(devis))
    assert soumission.MENTION_BROUILLON in html and _norm(soumission.MENTION_BROUILLON) in texte
    for champ in (contenu["devis_id"], contenu["lignes"][0]["description"]):
        assert champ in html and champ in texte
    for ligne in contenu["lignes"]:
        assert ligne["description"] in texte
        assert soumission_pdf.formater_quantite(ligne["quantite"]) + " " + ligne["unite"] in texte
        assert _norm(soumission_pdf.formater_montant(ligne["prix_unitaire"])) in texte
        assert _norm(soumission_pdf.formater_montant(ligne["prix_ligne"])) in texte
        assert str(ligne["prix_ligne"]) in html  # le même chiffre, en notation HTML
    assert _norm(soumission_pdf.formater_montant(contenu["prix_total"])) in texte
    assert str(contenu["prix_total"]) in html


def test_les_montants_en_texte_decimal_donnent_les_memes_octets_que_les_decimal(brique):
    devis = _devis()
    en_texte = json.loads(json.dumps(devis, default=str))
    assert isinstance(en_texte["prix_total"], str)
    assert _pdf(en_texte) == _pdf(devis)


# -- aucun coût, aucune marge ----------------------------------------------------------------------
def test_le_pdf_ne_dit_ni_le_cout_ni_la_marge(brique):
    """Valeurs de test choisies pour qu'aucune ne se retrouve par hasard dans les prix : un coût de
    7.77 et un taux de 0.4321 ne peuvent apparaître dans le PDF que par une fuite."""
    devis = _devis(
        [{"description": "Solin", "quantite": "3", "unite": "u", "cout_unitaire": "7.77",
          "reference_besoin_materiau": None}],
        taux="0.4321",
    )
    texte = _texte(_pdf(devis)).lower()
    assert devis["cout_total"] == Decimal("23.31") and devis["taux_marge"] == Decimal("0.4321")
    for interdit in ("7,77", "7.77", "23,31", "23.31", "0,4321", "0.4321", "43,21", "marge", "coût", "cout"):
        assert interdit not in texte, interdit


def test_des_cles_de_cout_en_surplus_sur_le_devis_ou_la_ligne_ne_fuitent_pas(brique):
    devis = _devis()
    devis["cout_secret"] = "5150.99"
    devis["taux_marge"] = Decimal("0.987654")
    for ligne in devis["lignes"]:
        ligne["cout_ligne"] = Decimal("4242.42")
        ligne["marge_ligne"] = "0.31415"
    texte = _texte(_pdf(devis))
    for interdit in ("5150", "5 150", "0,987654", "0,31415", "4242", "4 242"):
        assert interdit not in texte, interdit


# -- déterminisme ----------------------------------------------------------------------------------
def test_meme_devis_memes_octets(brique):
    devis = _devis()
    assert _pdf(devis) == _pdf(devis)
    assert _pdf(devis) == _pdf(json.loads(json.dumps(devis, default=str)))


_SCRIPT_AUTRE_PROCESSUS = """
import hashlib, json, sys, time
time.time = lambda: 4102444800.0        # 2100-01-01 : lire l'horloge changerait les octets
time.localtime = time.gmtime = lambda *a: time.struct_time((2100, 1, 1, 0, 0, 0, 4, 1, 0))
sys.path[:0] = json.loads(sys.argv[1])
from m3_estimation import soumission_pdf
octets, verdict = soumission_pdf.generer_brouillon_pdf(json.load(sys.stdin))
assert verdict is None, verdict
print(hashlib.sha256(octets).hexdigest())
"""


@pytest.mark.parametrize("graine_de_hachage", ["1", "424242"])
def test_memes_octets_dans_un_autre_processus_avec_une_autre_horloge(brique, graine_de_hachage):
    """Une horloge décalée de 74 ans et une autre graine de hachage : la même empreinte."""
    devis = _devis(_lignes(5))
    attendue = hashlib.sha256(_pdf(devis)).hexdigest()
    env = {**os.environ, "PYTHONHASHSEED": graine_de_hachage, "PYTHONPATH": os.pathsep.join(sys.path)}
    resultat = subprocess.run(
        [sys.executable, "-c", _SCRIPT_AUTRE_PROCESSUS, json.dumps(sys.path)],
        input=json.dumps(devis, default=str), capture_output=True, text=True, timeout=120, env=env, check=False,
    )
    assert resultat.returncode == 0, resultat.stderr
    assert resultat.stdout.strip() == attendue


def test_la_date_de_creation_suit_l_horodatage_du_devis(brique):
    from pypdf import PdfReader

    en_utc = _pdf(_devis(horodatage="2026-10-01T09:05:07Z"))
    autre = _pdf(_devis(horodatage="2026-10-01T09:05:08Z"))
    assert PdfReader(io.BytesIO(en_utc)).metadata["/CreationDate"] == "D:20261001090507+00'00'"
    assert PdfReader(io.BytesIO(autre)).metadata["/CreationDate"] == "D:20261001090508+00'00'"
    assert en_utc != autre
    assert "1er octobre 2026, 9 h 05 (UTC+00:00)" in _texte(en_utc)


# -- BROUILLON -------------------------------------------------------------------------------------
@pytest.mark.parametrize("statut", ["brouillon", "envoye", "accepte"])
def test_la_mention_brouillon_est_sur_toute_page_quel_que_soit_le_statut(brique, statut):
    """Le devis ne modélise aucune approbation : rien ne permet de lever la mention (voir le module)."""
    devis = _devis(_lignes(80))
    devis["statut"] = statut
    pages = _pages(_pdf(devis))
    assert len(pages) >= 2, "80 lignes doivent déborder d'une page pour que la preuve compte"
    for numero, page in enumerate(pages, start=1):
        assert "BROUILLON" in page, numero
        assert f"Page {numero}" in page, numero
        assert "Description" in page and "Prix unitaire" in page, "l'en-tête du tableau se répète"
    assert _norm(soumission.MENTION_BROUILLON) in pages[0]
    assert "Prix total" in pages[-1]


def test_le_libelle_du_statut_est_en_francais(brique):
    devis = _devis()
    devis["statut"] = "envoye"
    assert "Statut : envoyé" in _texte(_pdf(devis))


# -- la brique est absente : un verdict, jamais un faux PDF ----------------------------------------
def test_brique_absente_un_verdict_qui_dit_quoi_installer(monkeypatch):
    def introuvable(nom):
        raise soumission_pdf.metadata.PackageNotFoundError(nom)

    monkeypatch.setattr(soumission_pdf.metadata, "version", introuvable)
    assert soumission_pdf.pdf_installe() == (False, "reportlab absent")
    octets, verdict = soumission_pdf.generer_brouillon_pdf(_devis())
    assert octets is None
    assert verdict["code"] == "REJ-SOUMISSION-PDF-BRIQUE-ABSENTE"
    assert "extra soumission" in verdict["detail"]
    assert f"reportlab=={soumission_pdf.VERSION_BRIQUE}" in verdict["detail"]
    assert verdicts.est_verdict(verdict["code"])


def test_brique_d_une_autre_version_est_traitee_comme_absente(monkeypatch):
    monkeypatch.setattr(soumission_pdf.metadata, "version", lambda nom: "4.4.0")
    installe, raison = soumission_pdf.pdf_installe()
    assert installe is False
    assert raison == f"reportlab 4.4.0 trouvé, {soumission_pdf.VERSION_BRIQUE} exigé"
    octets, verdict = soumission_pdf.generer_brouillon_pdf(_devis())
    assert octets is None
    assert verdict["code"] == "REJ-SOUMISSION-PDF-BRIQUE-ABSENTE" and "4.4.0" in verdict["detail"]


def test_brique_installee_mais_non_importable_est_absente(monkeypatch):
    monkeypatch.setattr(soumission_pdf.metadata, "version", lambda nom: soumission_pdf.VERSION_BRIQUE)

    def casse(nom):
        raise ImportError(nom)

    monkeypatch.setattr(soumission_pdf, "import_module", casse)
    assert soumission_pdf.pdf_installe() == (False, "reportlab installé mais non importable")
    octets, verdict = soumission_pdf.generer_brouillon_pdf(_devis())
    assert octets is None and verdict["code"] == "REJ-SOUMISSION-PDF-BRIQUE-ABSENTE"


def test_sans_la_brique_rien_n_est_rendu_meme_pas_du_html(monkeypatch):
    monkeypatch.setattr(soumission_pdf, "pdf_installe", lambda: (False, "reportlab absent"))
    resultat = soumission_pdf.generer_brouillon_pdf(_devis())
    assert resultat[0] is None and isinstance(resultat[1], dict)


# -- champ requis absent ou invalide : un verdict qui dit quoi fournir -----------------------------
@pytest.mark.parametrize("champ", ["devis_id", "lead_id", "statut", "horodatage", "lignes", "prix_total"])
def test_champ_requis_absent_dit_lequel_fournir(brique, champ):
    devis = _devis()
    del devis[champ]
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert champ in verdict["detail"]


@pytest.mark.parametrize("devis_invalide", [{}, "pas-un-dict", None, []])
def test_devis_structurellement_invalide(brique, devis_invalide):
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis_invalide)
    assert octets is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_devis_sans_lignes(brique):
    devis = _devis()
    devis["lignes"] = []
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None and verdict["code"] == "REJ-DEVIS-LIGNES-VIDES"


def test_ligne_sans_les_cles_client_dit_lesquelles(brique):
    devis = _devis()
    del devis["lignes"][1]["prix_ligne"]
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None and verdict["code"] == "REJ-DEVIS-LIGNE-INVALIDE"
    assert "prix_ligne" in verdict["detail"]


@pytest.mark.parametrize("champ", ["description", "unite"])
@pytest.mark.parametrize("valeur", ["", "   ", None, 42])
def test_texte_de_ligne_vide_ou_non_textuel_nomme_la_ligne_et_le_champ(brique, champ, valeur):
    devis = _devis()
    devis["lignes"][1][champ] = valeur
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None and verdict["code"] == "REJ-DEVIS-LIGNE-INVALIDE"
    assert "ligne 1" in verdict["detail"] and champ in verdict["detail"]


@pytest.mark.parametrize("champ", ["devis_id", "statut"])
def test_texte_d_en_tete_vide_est_refuse(brique, champ):
    devis = _devis()
    devis[champ] = ""
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None and verdict["code"] == "REJ-CONTRAT-INVALIDE" and champ in verdict["detail"]


@pytest.mark.parametrize(
    "horodatage",
    ["2026-09-28T14:00:00", "2026-09-28", "hier vers 14 h", "", None, 1790000000],
)
def test_horodatage_sans_fuseau_ou_illisible_dit_le_format_attendu(brique, horodatage):
    devis = _devis()
    devis["horodatage"] = horodatage
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None
    assert verdict["code"] == "REJ-SOUMISSION-PDF-HORODATAGE-INVALIDE"
    assert "ISO-8601 avec fuseau" in verdict["detail"]


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("prix_total", 1334.88),  # un nombre JSON : jamais
        ("prix_total", Decimal("NaN")),
        ("prix_total", "beaucoup"),
        ("prix_total", None),
        ("prix_total", Decimal("1E+30")),
    ],
)
def test_montant_du_devis_illisible_est_refuse(brique, champ, valeur):
    devis = _devis()
    devis[champ] = valeur
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None
    assert verdict["code"] == "REJ-SOUMISSION-PDF-MONTANT-INVALIDE" and champ in verdict["detail"]


@pytest.mark.parametrize("champ", ["prix_unitaire", "prix_ligne", "quantite"])
def test_montant_de_ligne_illisible_nomme_la_ligne(brique, champ):
    devis = _devis()
    devis["lignes"][0][champ] = 13.5
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None and verdict["code"] == "REJ-SOUMISSION-PDF-MONTANT-INVALIDE"
    assert "ligne 0" in verdict["detail"] and champ in verdict["detail"]


def test_un_montant_qui_exigerait_un_arrondi_est_refuse_jamais_arrondi(brique):
    devis = _devis()
    devis["prix_total"] = Decimal("1334.885")
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None and verdict["code"] == "REJ-SOUMISSION-PDF-MONTANT-INVALIDE"
    assert "au cent" in verdict["detail"]


# -- texte du client = donnée ----------------------------------------------------------------------
_ACCENTS = "Éléphant à côté, ça coûte 1 500 € — « garçon » ’ œuvre Œuvre naïve ÿ ñ Ç ù î ô â ê è"


def test_accents_guillemets_tirets_et_euro_survivent(brique):
    devis = _devis([{"description": _ACCENTS, "quantite": "1", "unite": "forfait", "cout_unitaire": "9.00",
                     "reference_besoin_materiau": None}])
    assert _norm(_ACCENTS) in _texte(_pdf(devis))


def test_un_identifiant_accentue_passe_dans_le_titre_du_pdf_et_dans_le_texte(brique):
    from pypdf import PdfReader

    identifiant = "M3-DEVIS-Éloïse-œ’«»—€"
    octets = _pdf(_devis(devis_id=identifiant))
    assert PdfReader(io.BytesIO(octets)).metadata["/Title"] == f"Soumission brouillon {identifiant}"
    assert f"Soumission {identifiant}" in _texte(octets)


def test_un_texte_decompose_est_normalise_en_nfc(brique):
    decompose = "Gouttière âgée"
    devis = _devis([{"description": decompose, "quantite": "1", "unite": "u", "cout_unitaire": "9.00",
                     "reference_besoin_materiau": None}])
    assert "Gouttière âgée" in _texte(_pdf(devis))


def test_retours_a_la_ligne_et_tabulations_deviennent_des_espaces(brique):
    devis = _devis([{"description": "ligne un\nligne deux\t fin\r\nfin", "quantite": "1", "unite": "u",
                     "cout_unitaire": "9.00", "reference_besoin_materiau": None}])
    assert "ligne un ligne deux fin fin" in _texte(_pdf(devis))


_CHARGES = [
    "<script>alert(1)</script>",
    "<b>gras</b> et <i>italique</i> <font color='red' size='40'>rouge</font>",
    "Fish &amp; Chips &lt;3 &#233; &nbsp;",
    "<a href=\"http://exemple.invalid/x\">cliquez</a>",
    "<img src=\"/etc/hostname\" width=\"9\" height=\"9\"/>",
    "<para><seq id='x'/> %(nom)s {0} ${HOME} \\n <br/> <unknown",
    "</para><para>",
]


@pytest.mark.parametrize("charge", _CHARGES)
def test_le_texte_du_client_est_affiche_tel_quel_jamais_interprete(brique, charge):
    devis = _devis([{"description": charge, "quantite": "1", "unite": "u", "cout_unitaire": "9.00",
                     "reference_besoin_materiau": None}])
    octets = _pdf(devis)
    assert _compact(charge) in _compact(_texte(octets))


@pytest.mark.parametrize("charge", _CHARGES)
def test_le_texte_du_client_n_ouvre_aucune_action_dans_le_pdf(brique, charge):
    """Ni lien, ni script, ni fichier joint : les clés d'action du PDF sont absentes des octets."""
    devis = _devis([{"description": charge, "quantite": "1", "unite": "u", "cout_unitaire": "9.00",
                     "reference_besoin_materiau": None}])
    octets = _pdf(devis)
    for cle in (b"/URI", b"/JS", b"/JavaScript", b"/Launch", b"/OpenAction", b"/EmbeddedFile", b"/AA", b"/Annots"):
        assert cle not in octets, cle


def test_la_charge_est_aussi_neutre_dans_l_identifiant_et_l_unite(brique):
    devis = _devis(devis_id="M3-DEVIS-<b>x</b>-&-<img src='/etc/hostname'/>")
    devis["lignes"][0]["unite"] = "<font size='99'>u</font>"
    texte = _texte(_pdf(devis))
    assert "M3-DEVIS-<b>x</b>-&-<img src='/etc/hostname'/>" in texte
    assert _compact("<font size='99'>u</font>") in _compact(texte)


@pytest.mark.parametrize(
    ("texte", "points"),
    [
        ("Gouttière 中文", ["U+4E2D", "U+6587"]),
        ("Toit 😀", ["U+1F600"]),
        ("dimension ≥ 5 po", ["U+2265"]),
        ("caractère nul \x00 caché", ["U+0000"]),
        ("inversion ‮ du sens", ["U+202E"]),
        ("dévié ́́", ["U+0301"]),  # combinant orphelin : aucune forme NFC composée
    ],
)
def test_un_caractere_que_la_police_ne_dessine_pas_est_un_verdict_jamais_un_carre(brique, texte, points):
    devis = _devis()
    devis["lignes"][0]["description"] = texte
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None
    assert verdict["code"] == "REJ-SOUMISSION-PDF-CARACTERE-NON-SUPPORTE"
    assert "ligne 0" in verdict["detail"] and "description" in verdict["detail"]
    for point in points:
        assert point in verdict["detail"]
    assert "Windows-1252" in verdict["detail"]
    assert not any(caractere in verdict["detail"] for caractere in "中文😀≥\x00‮")


# -- mise en forme québécoise ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        (Decimal("0"), "0,00\u00a0$"),
        (Decimal("-0.00"), "0,00\u00a0$"),
        (Decimal("5"), "5,00\u00a0$"),
        (Decimal("13.5"), "13,50\u00a0$"),
        (Decimal("405.00"), "405,00\u00a0$"),
        (Decimal("999.99"), "999,99\u00a0$"),
        (Decimal("1000"), "1\u00a0000,00\u00a0$"),
        (Decimal("1234567.5"), "1\u00a0234\u00a0567,50\u00a0$"),
        (Decimal("-12.30"), "-12,30\u00a0$"),
        (Decimal("1E+2"), "100,00\u00a0$"),
    ],
)
def test_formater_montant(valeur, attendu):
    assert soumission_pdf.formater_montant(valeur) == attendu


@pytest.mark.parametrize("valeur", [Decimal("13.505"), Decimal("0.001"), Decimal("NaN"), Decimal("Infinity"),
                                    Decimal("1E+20"), Decimal("1E-9"), 13.5, "13.50", None])
def test_formater_montant_refuse_ce_qui_exigerait_un_arrondi_ou_n_est_pas_un_decimal(valeur):
    with pytest.raises(ValueError, match="montant"):
        soumission_pdf.formater_montant(valeur)


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        (Decimal("30"), "30"),
        (Decimal("12.5"), "12,5"),
        (Decimal("12.50"), "12,50"),
        (Decimal("0.125"), "0,125"),
        (Decimal("1200"), "1\u00a0200"),
        (Decimal("1E+3"), "1\u00a0000"),
    ],
)
def test_formater_quantite(valeur, attendu):
    assert soumission_pdf.formater_quantite(valeur) == attendu


@pytest.mark.parametrize("valeur", [Decimal("1E-9"), Decimal("1E+20"), Decimal("NaN"), 12.5])
def test_formater_quantite_refuse_l_inaffichable(valeur):
    with pytest.raises(ValueError, match="quantité"):
        soumission_pdf.formater_quantite(valeur)


# -- échec de la brique tierce ---------------------------------------------------------------------
def test_une_description_plus_haute_qu_une_page_est_un_verdict_qui_dit_quoi_faire(brique):
    devis = _devis()
    devis["lignes"][0]["description"] = "mot " * 6000
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert octets is None
    assert verdict["code"] == "REJ-SOUMISSION-PDF-RENDU-IMPOSSIBLE"
    assert "raccourcir" in verdict["detail"] and "mot mot" not in verdict["detail"]


def test_une_exception_de_la_brique_devient_un_verdict_sans_son_message(brique, monkeypatch):
    def casse(contenu):
        raise RuntimeError("adresse secrète 123 rue Exemple")

    monkeypatch.setattr(soumission_pdf, "_rendre", casse)
    octets, verdict = soumission_pdf.generer_brouillon_pdf(_devis())
    assert octets is None
    assert verdict["code"] == "REJ-SOUMISSION-PDF-RENDU-IMPOSSIBLE"
    assert "secrète" not in verdict["detail"] and "Exemple" not in verdict["detail"]


# -- catalogue, épinglage, CI ----------------------------------------------------------------------
def test_les_codes_du_module_sont_au_catalogue_et_le_catalogue_n_a_pas_de_code_orphelin():
    assert set(verdicts.CODES_M3_LIST) >= _CODES_EXERCES_PAR_CE_FICHIER | {_CODE_DE_L_ADAPTATEUR}
    du_catalogue = {code for code in verdicts.CODES_M3_LIST if code.startswith("REJ-SOUMISSION-PDF-")}
    assert du_catalogue == _CODES_EXERCES_PAR_CE_FICHIER | {_CODE_DE_L_ADAPTATEUR}


def _pyproject():
    return tomllib.loads((_RACINE / "pyproject.toml").read_text(encoding="utf-8"))


def test_l_extra_soumission_epingle_la_version_verifiee_a_l_execution():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert extras["soumission"] == [f"{soumission_pdf.NOM_BRIQUE}=={soumission_pdf.VERSION_BRIQUE}"]
    assert any(exigence.startswith("pypdf==") for exigence in extras["dev"]), "pypdf relit les PDF des tests"


def test_en_ci_la_brique_et_pypdf_sont_installees():
    """En CI, un test PDF sauté serait un faux vert : la brique et pypdf DOIVENT être là."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        pytest.skip("garde de CI seulement")
    assert soumission_pdf.pdf_installe() == (True, soumission_pdf.VERSION_BRIQUE)
    __import__("pypdf")


def test_la_brique_installee_localement_est_la_version_epinglee(brique):
    assert soumission_pdf.pdf_installe() == (True, soumission_pdf.VERSION_BRIQUE)


def test_le_module_est_pur_ni_opsys_ni_horloge_ni_reseau_ni_alea():
    """Module pur (ADR-0009) : la garde AST du paquet (`conformite.py`) couvre l'horloge et l'aléa ;
    celle-ci ajoute l'absence de tout import du socle et de tout accès réseau ou fichier."""
    arbre = ast.parse((_SRC / "m3_estimation" / "soumission_pdf.py").read_text(encoding="utf-8"))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes |= {alias.name.split(".")[0] for alias in noeud.names}
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
            importes.add(noeud.module.split(".")[0])
    assert importes.isdisjoint({"opsys", "time", "random", "uuid", "secrets", "socket", "urllib", "http", "os",
                                "pathlib", "subprocess"}), importes
    appels = {noeud.func.attr for noeud in ast.walk(arbre) if isinstance(noeud, ast.Call)
              and isinstance(noeud.func, ast.Attribute)}
    assert appels.isdisjoint({"now", "today", "utcnow", "strftime", "open", "read_text", "write_bytes"}), appels
