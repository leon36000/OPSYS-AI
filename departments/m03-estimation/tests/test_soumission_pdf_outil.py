"""PLAN T2.3-f : le format `pdf` de `m3_generer_soumission_brouillon`, par l'outil RÉEL.

Même patron que `test_acces_par_proprietaire.py` : base SQLite temporaire migrée, devis créés par
`m3_creer_devis`, appels comme le fait `Capacites.appeler` (`executer_atomique`), vraies personnes. On prouve
que le PDF rendu par l'outil se relit, que les mêmes gardes que le HTML s'appliquent (rôle, propriétaire), que la
sortie ne dépasse jamais ce qu'un outil peut transmettre (un PDF tronqué serait un fichier corrompu) et que
l'extra absent donne un verdict, jamais un HTML renommé. Aucun outil d'envoi n'est ajouté (N4, humain seul).
Données fictives (AGENTS.md).

Peu de tests, chacun sur son propre devis : chaque test qui touche la base migre un SQLite neuf (~0,2 s), et
les outils de mutation de M3 rejouent toute la suite du département à chaque mutant.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import outils as outils_m3  # noqa: E402
from m3_estimation import soumission_pdf, verdicts  # noqa: E402
from m3_estimation.outils import outils  # noqa: E402

from opsys import contexte, evenements, identite, jetons, stockage  # noqa: E402
from opsys.capacites import Capacites  # noqa: E402
from opsys.departements import charger_departements  # noqa: E402
from opsys.outils import Autonomie, executer, executer_atomique  # noqa: E402

FICTIF = True
_RACINE = Path(__file__).resolve().parents[3]
_HORODATAGE = "2026-09-29T14:00:00-04:00"
_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"

VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
ADMIN = contexte.IdentiteAppelante(personne="admin.un", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="employe.un", role="employee")

DEVIS_UN = "M3-DEVIS-pdf-outil-001"
DEVIS_DEUX = "M3-DEVIS-pdf-outil-002"
NOM = "m3_generer_soumission_brouillon"


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(_outil(nom), arguments)


def _lignes(n=2):
    return [
        {
            "description": f"Gouttière aluminium 5 po, poste {i}, main-d'œuvre incluse",
            "quantite": str(10 + i),
            "unite": "pi_lin",
            "cout_unitaire": f"{10 + i * 1.37:.2f}",
            "reference_besoin_materiau": None,
        }
        for i in range(n)
    ]


def _creer_devis(devis_id, lead_id, lignes=None, taux="0.20"):
    reponse = _appeler("m3_creer_devis", {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": lignes if lignes is not None else _lignes(),
        "taux_marge": taux, "horodatage": _HORODATAGE,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _lead_assigne(lead_id, proprietaire):
    with stockage.transaction():
        evenements.publier(
            "m2.lead_assigne", "m02-revenue-crm",
            {"lead_id": lead_id, "proprietaire": proprietaire, "horodatage_assignation": _HORODATAGE},
            evenement_id=f"m2-lead-assigne-{lead_id}",
        )


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys-m3-pdf.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def scenario(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", _MOT_DE_PASSE, roles=["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", _MOT_DE_PASSE, roles=["seller"])
        identite.creer_personne(cnx, "admin.un", "Admin Un", _MOT_DE_PASSE, roles=["admin"])
        identite.creer_personne(cnx, "employe.un", "Employé Un", _MOT_DE_PASSE, roles=["employee"])
    _creer_devis(DEVIS_UN, "lead-un")
    _creer_devis(DEVIS_DEUX, "lead-deux")
    _lead_assigne("lead-un", "vendeur.un")
    _lead_assigne("lead-deux", "vendeur.deux")


@pytest.fixture
def brique():
    installe, raison = soumission_pdf.pdf_installe()
    if not installe:
        pytest.skip(raison)
    pytest.importorskip("pypdf")


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _verdict(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _texte_du_pdf(octets):
    from pypdf import PdfReader

    return " ".join(" ".join(page.extract_text().split()) for page in PdfReader(io.BytesIO(octets)).pages)


def _pdf(arguments_devis_id, appelant=None):
    return _appeler(NOM, {"devis_id": arguments_devis_id, "format": "pdf"}, appelant)


# -- le PDF rendu par l'outil ----------------------------------------------------------------------
def test_l_outil_rend_un_pdf_relisible_stable_sans_cout_ni_marge_et_le_html_reste_le_defaut(brique, scenario):
    reponse = _pdf(DEVIS_UN)
    fichier = _accepte(reponse)
    assert set(fichier) == {"format", "type_mime", "nom_fichier", "taille_octets", "empreinte_sha256",
                            "contenu_base64"}
    assert fichier["format"] == "pdf" and fichier["type_mime"] == "application/pdf"
    assert fichier["nom_fichier"] == "soumission-brouillon-M3-DEVIS-pdf-outil-001.pdf"
    octets = base64.b64decode(fichier["contenu_base64"], validate=True)
    assert octets.startswith(b"%PDF-") and octets.rstrip().endswith(b"%%EOF")
    assert fichier["taille_octets"] == len(octets)
    assert fichier["empreinte_sha256"] == hashlib.sha256(octets).hexdigest()

    texte = _texte_du_pdf(octets)
    assert DEVIS_UN in texte and "BROUILLON" in texte and "main-d'œuvre incluse" in texte
    assert "Prix total" in texte and "Taxes (TPS/TVQ) en sus" in texte
    # coût unitaire 10,00 et 11,37 ; taux de marge 0,20 : le prix (12,00 et 13,64) est le seul chiffre à paraître
    for interdit in ("10,00", "11,37", "0,20", "20 %", "marge", "coût"):
        assert interdit not in texte.lower(), interdit
    assert "12,00" in texte and "13,64" in texte

    assert _accepte(_pdf(DEVIS_UN)) == fichier, "mêmes entrées, mêmes octets, d'un appel à l'autre"
    assert len(json.dumps(reponse, ensure_ascii=False)) <= jetons.LIMITE_SORTIE_DEFAUT

    par_defaut = _accepte(_appeler(NOM, {"devis_id": DEVIS_UN}))
    assert isinstance(par_defaut, str) and par_defaut.startswith("<!doctype html>")
    assert _accepte(_appeler(NOM, {"devis_id": DEVIS_UN, "format": "html"})) == par_defaut


def test_un_format_inconnu_est_refuse_au_schema_puis_par_la_fonction():
    reponse = executer(_outil(NOM), {"devis_id": DEVIS_UN, "format": "docx"})
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    with pytest.raises(ValueError, match="format inconnu"):
        outils_m3.generer_soumission_brouillon(DEVIS_UN, "docx")


def test_aucun_outil_d_envoi_n_est_ajoute_et_la_portee_de_l_outil_est_inchangee():
    noms = [o.nom for o in outils()]
    assert noms.count(NOM) == 1
    assert [nom for nom in noms if "envoy" in nom or "pdf" in nom or "courriel" in nom] == []
    outil = _outil(NOM)
    assert outil.autonomie is Autonomie.T0
    assert outil.roles_appareil == frozenset({"seller", "admin"})
    assert set(outil.parametres["properties"]) == {"devis_id", "format"}
    assert outil.parametres["required"] == ["devis_id"]


# -- mêmes gardes que le HTML ----------------------------------------------------------------------
def test_le_pdf_passe_par_les_memes_gardes_de_role_et_de_proprietaire_que_le_html(brique, scenario):
    for appelant in (VENDEUR_UN, ADMIN, None):
        fichier = _accepte(_pdf(DEVIS_UN, appelant))
        assert base64.b64decode(fichier["contenu_base64"]).startswith(b"%PDF-")

    # le lead d'un autre vendeur, et un devis qui n'existe pas : le même refus, en PDF comme en HTML
    en_pdf = _verdict(_pdf(DEVIS_DEUX, VENDEUR_UN))
    en_html = _verdict(_appeler(NOM, {"devis_id": DEVIS_DEUX, "format": "html"}, VENDEUR_UN))
    assert en_pdf["code"] == "REJ-DEVIS-INTROUVABLE" and en_pdf == en_html
    assert _verdict(_pdf("M3-DEVIS-fantome", VENDEUR_UN))["code"] == "REJ-DEVIS-INTROUVABLE"
    assert _verdict(_pdf("M3-DEVIS-fantome"))["code"] == "REJ-DEVIS-INTROUVABLE"

    # l'employé ne voit jamais un prix
    refus = _verdict(_pdf(DEVIS_UN, EMPLOYE))
    assert refus["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _verdict(_appeler(NOM, {"devis_id": DEVIS_UN, "format": "html"}, EMPLOYE)) == refus


# -- l'extra est absent : un verdict, jamais un HTML renommé ---------------------------------------
def test_sans_la_brique_l_outil_refuse_le_pdf_avec_un_verdict_et_ne_rend_aucun_contenu(monkeypatch, scenario):
    def introuvable(nom):
        raise soumission_pdf.metadata.PackageNotFoundError(nom)

    monkeypatch.setattr(soumission_pdf.metadata, "version", introuvable)
    reponse = _pdf(DEVIS_UN)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert set(reponse["resultat"]) == {"accepte", "verdict"}, "aucun contenu, ni HTML ni PDF"
    verdict = reponse["resultat"]["verdict"]
    assert verdict["code"] == "REJ-SOUMISSION-PDF-BRIQUE-ABSENTE" and "extra soumission" in verdict["detail"]
    assert _accepte(_appeler(NOM, {"devis_id": DEVIS_UN, "format": "html"})).startswith("<!doctype html>")


# -- la limite de sortie d'un outil ----------------------------------------------------------------
def test_un_pdf_trop_gros_est_un_verdict_jamais_un_contenu_tronque(brique, scenario, monkeypatch):
    """80 lignes : le PDF fait plus de 6000 caractères une fois en base64, `Capacites._tronquer` le
    remplacerait par un aperçu, donc un fichier corrompu. L'outil le refuse, et dit pourquoi."""
    _creer_devis("M3-DEVIS-pdf-gros", "lead-un", lignes=_lignes(80))
    reponse = _pdf("M3-DEVIS-pdf-gros")
    verdict = _verdict(reponse)
    assert verdict["code"] == "REJ-SOUMISSION-PDF-TROP-VOLUMINEUX"
    assert str(jetons.LIMITE_SORTIE_DEFAUT) in verdict["detail"] and "octets" in verdict["detail"]
    assert "contenu_base64" not in json.dumps(reponse)
    assert verdicts.est_verdict(verdict["code"])
    # le HTML du même devis n'est pas concerné par cette limite du PDF
    assert "M3-DEVIS-pdf-gros" in _accepte(_appeler(NOM, {"devis_id": "M3-DEVIS-pdf-gros", "format": "html"}))

    # la limite est mesurée comme `Capacites._tronquer` le fait, au caractère près
    mesure = len(json.dumps(_pdf(DEVIS_UN), ensure_ascii=False))
    monkeypatch.setattr(outils_m3.jetons, "LIMITE_SORTIE_DEFAUT", mesure)
    assert _accepte(_pdf(DEVIS_UN))["format"] == "pdf"
    monkeypatch.setattr(outils_m3.jetons, "LIMITE_SORTIE_DEFAUT", mesure - 1)
    assert _verdict(_pdf(DEVIS_UN))["code"] == "REJ-SOUMISSION-PDF-TROP-VOLUMINEUX"


def test_par_capacites_le_pdf_arrive_entier_et_le_trop_gros_ne_devient_jamais_un_apercu(brique, scenario):
    """Le vrai point de passage (`Capacites.appeler`, qui tronque au-delà de la limite) : le PDF d'un devis
    ordinaire arrive sans `tronque` et se relit ; celui d'un devis trop gros est un verdict, pas un aperçu."""
    _creer_devis("M3-DEVIS-pdf-quinze", "lead-un", lignes=_lignes(15))
    _creer_devis("M3-DEVIS-pdf-gros", "lead-un", lignes=_lignes(80))
    capacites = Capacites(charger_departements(_RACINE / "departments"), stockage.transaction,
                          filtre={"m03-estimation"}, memoire=False)

    for devis_id, dernier_poste in ((DEVIS_UN, None), ("M3-DEVIS-pdf-quinze", "poste 14")):
        ordinaire = capacites.appeler(NOM, {"devis_id": devis_id, "format": "pdf"})
        assert "tronque" not in ordinaire and ordinaire["ok"] is True, ordinaire
        fichier = ordinaire["resultat"]["resultat"]
        octets = base64.b64decode(fichier["contenu_base64"], validate=True)
        assert hashlib.sha256(octets).hexdigest() == fichier["empreinte_sha256"]
        assert devis_id in _texte_du_pdf(octets)
        if dernier_poste is not None:
            assert dernier_poste in _texte_du_pdf(octets)

    gros = capacites.appeler(NOM, {"devis_id": "M3-DEVIS-pdf-gros", "format": "pdf"})
    assert "tronque" not in gros and gros["ok"] is True, gros
    assert gros["resultat"]["verdict"]["code"] == "REJ-SOUMISSION-PDF-TROP-VOLUMINEUX"
