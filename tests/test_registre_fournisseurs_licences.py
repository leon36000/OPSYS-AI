"""Registre des fournisseurs : chaque ligne du catalogue porte ses licences, ses seuils, ses territoires et son niveau de
vérification À LA SOURCE ; modifier une licence sans repasser par l'audit fait échouer ce test.

Aucun accès réseau : « lue en recherche » veut dire que la recherche R1-R6 du 2026-10-31 avait lu la source (marque [V) ; rien
n'est revérifié ici. Les lignes que le catalogue appelle `verifiee` sans preuve primaire sont listées (écart non corrigé : changer
`verification` modifierait le comportement d'activation).
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from opsys.fournisseurs import catalogue
from opsys.fournisseurs.modele import Fournisseur, Licence

RACINE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit_fournisseurs", RACINE / "scripts/compliance/audit_fournisseurs.py")
A = importlib.util.module_from_spec(spec)
sys.modules["audit_fournisseurs"] = A
spec.loader.exec_module(A)

DONNEES = RACINE / "docs/compliance/donnees/fournisseurs-verification.json"


@pytest.fixture(scope="module")
def consigne():
    return json.loads(DONNEES.read_text(encoding="utf-8"))


def test_chaque_fournisseur_du_catalogue_est_audite_et_aucun_en_trop(consigne):
    assert sorted(consigne["lignes"]) == sorted(f.identifiant for f in catalogue.CATALOGUE)
    assert len(catalogue.CATALOGUE) == 66


def test_les_donnees_et_le_registre_markdown_sont_ceux_du_catalogue(consigne):
    attendu = json.dumps(A.construire(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    assert DONNEES.read_text(encoding="utf-8") == attendu, "audit périmé : PYTHONPATH=src python scripts/compliance/audit_fournisseurs.py --ecrire"
    assert (RACINE / "docs/compliance/REGISTRE-FOURNISSEURS-LICENCES.md").read_text(encoding="utf-8") == A.registre_markdown(consigne)


def test_chaque_ligne_a_ses_champs_de_licence_hors_lacunes_consignees():
    for f in catalogue.CATALOGUE:
        assert A.lacunes(f) == [], f.identifiant
    # les lacunes connues existent encore (sinon la consigne est périmée)
    for identifiant, attendues in A.LACUNES_CONNUES.items():
        f = catalogue.par_identifiant()[identifiant]
        assert A.problemes(f) == attendues, identifiant


def test_les_modeles_locaux_portent_licence_du_code_et_des_poids():
    for f in catalogue.CATALOGUE:
        if f.mode == "local" and f.capacite in A.CAPACITES_A_POIDS and f.statut_catalogue != "ecarte":
            assert f.licence.poids or f.identifiant in A.POIDS_NON_APPLICABLES, f.identifiant
            assert f.licence.code or f.identifiant in A.LACUNES_CONNUES, f.identifiant


def test_seuil_territoires_et_service_a_des_tiers_sont_declares_la_ou_la_licence_les_impose():
    par_id = catalogue.par_identifiant()
    assert par_id["image.flux3-image-klein.local"].licence.seuil_revenu_usd == 5_000_000
    assert par_id["video.minimax-h3"].licence.territoires_exclus == ("UE", "UK", "KR", "US")
    assert par_id["video.hunyuanvideo-1.5"].licence.territoires_exclus == ("UE", "UK", "KR")
    for f in catalogue.CATALOGUE:
        if f.licence.usage_commercial == "sous_seuil":
            assert f.licence.seuil_revenu_usd, f.identifiant
        assert f.licence.service_tiers in ("autorise", "interdit", "incertain")


def test_la_verification_a_la_source_est_marquee_honnetement(consigne):
    lignes = consigne["lignes"]
    for f in catalogue.CATALOGUE:
        d = lignes[f.identifiant]
        if f.licence.verification == "a_lire" or "hors-recherche" in f.licence.source or "[V" not in f.licence.source:
            assert d["statut_source"] == "non_verifiee_a_la_source", f.identifiant
            assert d["date_source"] is None
        else:
            assert d["statut_source"] == "lue_en_recherche_niveau_V" and d["date_source"] == "2026-10-31"
        assert d["date_reverification_locale"] is None  # aucun accès réseau : personne n'a revérifié
    non = [i for i, d in lignes.items() if d["statut_source"] == "non_verifiee_a_la_source"]
    assert len(non) == 30  # chiffre cité par docs/compliance/INVENTAIRE-LICENCES.md et QUESTIONS-AVOCAT.md
    for i in ("vision.grounding-dino.local", "vision.sam2.local", "ocr.docling.local", "llm.nemotron-3.5-lightning.local",
              "image.flux3-image-klein.local", "avatar.musetalk-1.5.local", "embeddings.bge-m3.local"):
        assert i in non


def test_les_lignes_verifiee_sans_preuve_primaire_sont_listees_sans_etre_corrigees(consigne):
    incoherentes = A.incoherences_catalogue()
    assert len(incoherentes) == 21
    assert "reranker.bge-reranker-v2-m3.local" in incoherentes and "ocr.tesseract-5.5.local" in incoherentes
    # écart documenté dans le registre : la liste n'est pas silencieuse
    assert "non vérifiée à la source" in (RACINE / "docs/compliance/REGISTRE-FOURNISSEURS-LICENCES.md").read_text(encoding="utf-8")


def test_modifier_une_licence_du_catalogue_sans_repasser_par_l_audit_est_detecte(consigne):
    f = catalogue.par_identifiant()["image.flux2-klein-4b.local"]
    assert A.empreinte_licence(f) == consigne["lignes"][f.identifiant]["empreinte_licence"]
    modifiee = dataclasses.replace(f, licence=dataclasses.replace(f.licence, usage_commercial="sous_seuil", seuil_revenu_usd=1))
    assert A.empreinte_licence(modifiee) != consigne["lignes"][f.identifiant]["empreinte_licence"]
    seuil_en_moins = dataclasses.replace(f, licence=dataclasses.replace(f.licence, territoires_exclus=("US",)))
    assert A.empreinte_licence(seuil_en_moins) != consigne["lignes"][f.identifiant]["empreinte_licence"]


def test_une_ligne_sans_poids_ni_justification_est_signalee():
    f = Fournisseur(identifiant="image.test-sans-poids", capacite="image", mode="local", modele="m",
                    licence=Licence(code="MIT", poids=None, usage_commercial="autorise", service_tiers="autorise", source="t"))
    assert "licence des poids absente sans justification" in A.problemes(f)
    sans_code = Fournisseur(identifiant="image.test-sans-code", capacite="image", mode="local", modele="m",
                            licence=Licence(code=None, poids="X", usage_commercial="autorise", service_tiers="autorise", source="t"))
    assert "licence du code absente" in A.problemes(sans_code)
    marquee = dataclasses.replace(f, licence=dataclasses.replace(f.licence, source="recherche [V]"))
    assert A.statut_source(marquee)[0] == "lue_en_recherche_niveau_V"
    a_lire = dataclasses.replace(f, licence=dataclasses.replace(f.licence, source="recherche [V]", verification="a_lire"))
    assert A.statut_source(a_lire)[0] == "non_verifiee_a_la_source"
    inconnue = dataclasses.replace(f, licence=dataclasses.replace(f.licence, source="connaissance antérieure"))
    assert A.statut_source(inconnue)[0] == "non_verifiee_a_la_source"


def test_les_licences_interdites_du_catalogue_restent_ecartees():
    for f in catalogue.CATALOGUE:
        if f.licence.copyleft or f.licence.usage_commercial == "interdit":
            assert f.statut_catalogue == "ecarte", f.identifiant
    assert catalogue.par_identifiant()["ocr.pymupdf"].licence.copyleft


def test_les_questions_a_un_avocat_couvrent_les_quatre_questions_connues():
    texte = (RACINE / "docs/compliance/QUESTIONS-AVOCAT.md").read_text(encoding="utf-8")
    for motif in ("Licences à seuil de revenu en multi-PME", "Protection d'un logo généré", "Compilation réservée aux CPA",
                  "« français nettement prédominant »"):
        assert motif in texte, motif
    assert "ne tranche rien" in texte and "30 sur 66" in texte
