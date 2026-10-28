"""Rattachement figé, prix calculés et documents clients; toutes les données sont fictives."""

import io
import sys
from copy import deepcopy
from decimal import Decimal
from html import escape
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable, modeles_soumission, soumission, soumission_pdf  # noqa: E402
from m3_estimation.registre import _encoder_canonique  # noqa: E402

FIXTURE = {"fictif": True}
HEURE = "2030-06-03T12:00:00+00:00"
CHAMPS_FIGES = ("modele_id", "revision", "source_id", "titre", "description", "clauses")


def _modele(catalogue, revision_attendue=0, **modifications):
    arguments = {"modele_id": "modele-prive-fictif", "titre": "Travaux fictifs <alu>",
                 "description": "\nPremière ligne fictive\nSeconde ligne & détails",
                 "clauses": 'Clause fictive <img src="/fichier-prive">\nSuite fictive.',
                 "revision_attendue": revision_attendue, **modifications}
    reponse = modeles_soumission.enregistrer(
        catalogue, **arguments, auteur={"personne": "admin-prive-fictif", "role": "admin"},
        mutation={"appareil": "console:admin-prive-fictif", "cle": f"intention-fictive-{revision_attendue}",
                  "empreinte_arguments": _encoder_canonique(arguments)}, horodatage=HEURE)
    return {cle: reponse["resultat"][cle] for cle in CHAMPS_FIGES}


def _creer(registre, **options):
    return devis_durable.creer_devis(
        devis_id="devis-fictif", lead_id="lead-prive-fictif", chantier_id="chantier-prive-fictif",
        lignes=[{"description": "Gouttière fictive", "quantite": "3", "unite": "pi_lin",
                 "cout_unitaire": "11.17", "reference_besoin_materiau": "besoin-prive-fictif"}],
        taux_marge="0.25", horodatage=HEURE, registre_cible=registre, **options)


def test_snapshot_independant_catalogue_revise_ancien_accepte_conserve():
    catalogue, registre = [], []
    snapshot = _modele(catalogue)
    original = deepcopy(snapshot)
    devis, verdict = _creer(registre, modele_soumission=snapshot)
    assert verdict is None and devis["statut"] == "brouillon"
    assert devis["prix_total"] == Decimal("41.88") and devis["cout_total"] == Decimal("33.51")
    snapshot["clauses"] = "Mutation externe fictive"
    devis["modele_soumission"]["description"] = "Mutation du retour"
    lu, verdict = devis_durable.lire_devis(registre, "devis-fictif")
    assert verdict is None and lu["modele_soumission"] == original
    accepte, verdict = devis_durable.marquer_devis_accepte("devis-fictif", "humain-fictif", HEURE, registre)
    assert verdict is None and accepte["statut"] == "accepte"
    ancien_html = soumission.generer_brouillon_html(accepte)
    _modele(catalogue, 1, clauses="Nouvelle clause fictive : autre version")
    catalogue.clear()  # Le rendu et le devis n'ont plus aucune dépendance au catalogue.
    relu, verdict = devis_durable.lire_devis(registre, "devis-fictif")
    assert verdict is None and relu["modele_soumission"] == original
    assert soumission.generer_brouillon_html(relu) == ancien_html
    relu["modele_soumission"]["titre"] = "Modification du lecteur"
    accepte["modele_soumission"]["clauses"] = "Modification du retour de transition"
    assert registre[0]["modele_soumission"] == original
    assert len(registre) == 2


def test_idempotence_compare_tout_snapshot_et_ne_rattache_pas_ancien_devis():
    snapshot = _modele([])
    registre = []
    premier, verdict = _creer(registre, modele_soumission=snapshot)
    assert verdict is None
    rejoue, verdict = _creer(registre, modele_soumission=deepcopy(snapshot))
    assert verdict is None and rejoue == premier and len(registre) == 1
    rejoue["modele_soumission"]["titre"] = "Mutation du reçu"
    assert registre[0]["modele_soumission"] == snapshot
    for cle, valeur in [("revision", 2), ("source_id", "0" * 64), ("clauses", "Autres clauses fictives")]:
        refuse, verdict = _creer(registre, modele_soumission={**snapshot, cle: valeur})
        assert refuse is None and verdict["code"] == "REJ-DEVIS-ID-DEJA-UTILISE"
    refuse, verdict = _creer(registre)
    assert refuse is None and verdict["code"] == "REJ-DEVIS-ID-DEJA-UTILISE"
    ancien_registre = []
    ancien, verdict = _creer(ancien_registre)
    assert verdict is None and "modele_soumission" not in ancien
    refuse, verdict = _creer(ancien_registre, modele_soumission=snapshot)
    assert refuse is None and verdict["code"] == "REJ-DEVIS-ID-DEJA-UTILISE"
    assert len(registre) == len(ancien_registre) == 1


@pytest.mark.parametrize("modifications", [
    {"modele_id": "."}, {"modele_id": ".."}, {"modele_id": "modèle"}, {"revision": True},
    {"revision": 0}, {"revision": 1001}, {"revision": 1.0}, {"source_id": "A" * 64},
    {"source_id": "0" * 63}, {"titre": ""}, {"description": ""}, {"clauses": "\x00"},
    {"clauses": "\ud800"}, {"auteur": "intrus"}, {"description": "x" * 4001}, {"clauses": "x" * 12001},
])
def test_snapshot_invalide_refuse_a_creation_et_rendu(modifications):
    snapshot = {**_modele([]), **modifications}
    assert modeles_soumission.valider_modele_fige(snapshot) is False
    registre = []
    devis, verdict = _creer(registre, modele_soumission=snapshot)
    assert devis is None and verdict["code"] == "REJ-CONTRAT-INVALIDE" and registre == []
    ancien, _ = _creer([])
    ancien["modele_soumission"] = snapshot
    for lecteur in (soumission.contenu_client, soumission.generer_brouillon_html, soumission_pdf._preparer):
        rendu, verdict = lecteur(ancien)
        assert rendu is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_snapshot_ferme_et_valeur_absente_distincte_d_un_document_corrompu():
    snapshot = _modele([])
    assert modeles_soumission.valider_modele_fige(snapshot) is True
    for valeur in [None, [], {}, {k: v for k, v in snapshot.items() if k != "clauses"}]:
        assert modeles_soumission.valider_modele_fige(valeur) is False
    devis, verdict = _creer([], modele_soumission=None)
    assert verdict is None and "modele_soumission" not in devis
    devis["modele_soumission"] = None
    assert soumission.contenu_client(devis)[1]["code"] == "REJ-CONTRAT-INVALIDE"


def test_projection_html_texte_seulement_echappe_et_multiligne():
    snapshot = _modele([])
    devis, verdict = _creer([], modele_soumission=snapshot)
    assert verdict is None
    client, verdict = soumission.contenu_client(devis)
    assert verdict is None
    assert client["modele_soumission"] == {k: snapshot[k] for k in ("titre", "description", "clauses")}
    html, verdict = soumission.generer_brouillon_html(devis)
    assert verdict is None
    assert ('<div style="white-space: pre-wrap">\nPremière ligne fictive\n'
            'Seconde ligne &amp; détails</div>') in html
    assert escape(snapshot["titre"]) in html and escape(snapshot["clauses"]) in html
    assert '<img src=' not in html and '<alu>' not in html
    for interdit in [snapshot["modele_id"], snapshot["source_id"], "admin-prive-fictif", "lead-prive-fictif",
                     "chantier-prive-fictif", "besoin-prive-fictif", "cout_total", "taux_marge", "33.51"]:
        assert interdit not in html
    assert "41.88" in html and "BROUILLON" in html


def test_ancien_html_sans_modele_reste_exact():
    devis, verdict = _creer([])
    assert verdict is None
    attendu = (
        '<!doctype html><html lang="fr-CA"><head><meta charset="utf-8">'
        '<title>Soumission brouillon devis-fictif</title></head><body>'
        '<p><strong>BROUILLON — non envoyé, sujet à approbation. '
        'Ceci n\'est pas un engagement contractuel.</strong></p>'
        '<h1>Soumission — devis-fictif</h1><p>Statut : brouillon — daté du 2030-06-03T12:00:00+00:00</p>'
        '<table border="1" cellspacing="0" cellpadding="4"><thead><tr><th>Description</th><th>Quantité</th>'
        '<th>Prix unitaire</th><th>Prix</th></tr></thead><tbody><tr><td>Gouttière fictive</td><td>3 pi_lin</td>'
        '<td>13.96 $ CAD</td><td>41.88 $ CAD</td></tr></tbody></table><p><strong>Prix total : 41.88 $ CAD, '
        'taxes (TPS/TVQ) en sus.</strong></p></body></html>'
    )
    assert soumission.generer_brouillon_html(devis) == (attendu, None)
    explicite, verdict = _creer([], modele_soumission=None)
    assert verdict is None and explicite == devis


@pytest.fixture
def brique_pdf():
    installe, raison = soumission_pdf.pdf_installe()
    if not installe:
        pytest.skip(raison)
    return pytest.importorskip("pypdf")


def _pdf(devis):
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    assert verdict is None, verdict
    assert octets.startswith(b"%PDF-")
    return octets


def test_pdf_reel_texte_literal_multiligne_sans_sources_couts(brique_pdf):
    catalogue = []
    snapshot = _modele(catalogue)
    devis, _ = _creer([], modele_soumission=snapshot)
    prepare, verdict = soumission_pdf._preparer(devis)
    assert verdict is None and prepare["modele_soumission"]["description"] == snapshot["description"]
    avant = _pdf(devis)
    _modele(catalogue, 1, titre="Nouveau titre catalogue FICTIF")
    assert _pdf(devis) == avant
    pages = brique_pdf.PdfReader(io.BytesIO(avant)).pages
    texte = "\n".join(page.extract_text() for page in pages)
    assert "Travaux fictifs <alu>" in texte
    assert 'Clause fictive <img src="/fichier-prive">' in texte
    lignes = texte.splitlines()
    assert "Première ligne fictive" in lignes and "Seconde ligne & détails" in lignes
    assert "Suite fictive." in lignes and "41,88" in texte
    for interdit in [snapshot["modele_id"], snapshot["source_id"], "admin-prive-fictif", "33,51", "taux_marge"]:
        assert interdit not in texte


def test_pdf_sans_modele_octets_identiques_et_clauses_vides(brique_pdf):
    ancien, _ = _creer([])
    explicite, _ = _creer([], modele_soumission=None)
    assert _pdf(ancien) == _pdf(explicite)
    snapshot = _modele([], clauses="")
    devis, _ = _creer([], modele_soumission=snapshot)
    assert _pdf(devis).startswith(b"%PDF-")


def test_pdf_modele_hors_police_refuse_sans_texte_prive():
    snapshot = _modele([], clauses="Texte confidentiel fictif 😀")
    devis, verdict = _creer([], modele_soumission=snapshot)
    assert verdict is None
    contenu, verdict = soumission_pdf._preparer(devis)
    assert contenu is None and verdict["code"] == "REJ-SOUMISSION-PDF-CARACTERE-NON-SUPPORTE"
    assert "Texte confidentiel" not in str(verdict)
