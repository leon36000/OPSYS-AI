"""Preuve du câblage de bout en bout de l'orchestrateur d'estimation (PLAN T2.3) sur le stockage
durable de l'instance (ADR-0009) : `m3_estimer_projet` (registre "principal"),
`m3_detecter_devis_sans_reponse` (registre "devis" + bus d'événements),
`m3_generer_soumission_brouillon` et `m3_verifier_politique_photos`. Même patron que
`test_devis_durable_stockage.py`/`test_registre_durable.py` : base SQLite temporaire migrée, appels
par les outils RÉELS (`executer`/`executer_atomique`), une nouvelle instance = redémarrage simulé.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation.outils import outils, registre_production  # noqa: E402

from opsys import stockage  # noqa: E402
from opsys.outils import executer, executer_atomique  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import EVENEMENTS_SORTANTS  # noqa: E402

_HORODATAGE = "2026-09-28T14:00:00-04:00"

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1",
    "unite": "pi2",
    "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}},
}


def _contrat(**surcharges):
    contrat = {
        "lead_id": "lead-stock-001",
        "conversation_id": "conv-stock-001",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire_web",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }
    contrat.update(surcharges)
    return contrat


def _marqueur(**surcharges):
    marqueur = {
        "readiness_ok": True,
        "lead_id": "lead-stock-001",
        "hash_tete_registre": "f" * 64,
        "horodatage": "2026-09-28T10:00:00-04:00",
        "empreinte": "a" * 64,
    }
    marqueur.update(surcharges)
    return marqueur


def _photo(i=1, reference=None, angle="face"):
    return {
        "photo_id": f"p{i}",
        "resolution_largeur": 3000,
        "resolution_hauteur": 2000,
        "eclairage": 7,
        "angle": angle,
        "reference_echelle": reference,
    }


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def _appeler(nom, arguments):
    return executer_atomique(_outil(nom), arguments)


def _compte_evenements(where=None) -> int:
    requete = select(func.count()).select_from(EVENEMENTS_SORTANTS)
    if where is not None:
        requete = requete.where(where)
    with stockage.transaction() as cnx:
        return cnx.execute(requete).scalar_one()


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _estimer(**surcharges):
    arguments = {
        "contrat": _contrat(),
        "marqueur": _marqueur(),
        "photos": [_photo(reference={"type": "porte", "dimensions_connues": True})],
        "seuils": SEUILS,
        "bareme": BAREME,
        "quantite": 1200,
        "plancher_rentable": 9000,
    }
    arguments.update(surcharges)
    return _appeler("m3_estimer_projet", arguments)


# ------------------------------------------------------------- m3_estimer_projet, registre durable
def test_estimer_projet_ecrit_au_registre_durable_principal(base_durable):
    reponse = _estimer()
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["accepte"] is True
    assert resultat["estimation"]["devis_id"].startswith("M3-DEVIS-")

    assert len(registre_production().lire()) == 1


def test_estimer_projet_relu_par_une_nouvelle_instance_depuis_le_stockage_durable(base_durable):
    premiere = _estimer()
    devis_id = premiere["resultat"]["estimation"]["devis_id"]

    # "Nouvelle instance" : aucun état Python en cache — seule la base a persisté ce qui a été
    # écrit ci-dessus (même preuve que test_registre_durable.py).
    maillons = registre_production().lire()
    assert len(maillons) == 1
    assert maillons[0]["charge"]["devis_id"] == devis_id
    valide, diagnostic = registre_production().valider_chaine()
    assert valide is True, diagnostic


def test_estimer_projet_ne_publie_aucun_evenement(base_durable):
    """m3_estimer_projet écrit au registre "principal" mais ne publie RIEN sur le bus — seul
    m3_marquer_devis_accepte publie m3.devis_accepte (T2.3-a/b, inchangé par cette tranche)."""
    _estimer()
    assert _compte_evenements() == 0


def test_estimer_projet_type_travaux_hors_contrat_rejet_metier_nomme(base_durable):
    """`type_travaux` vit désormais DANS `contrat` (PLAN T2.3) : le validateur de schéma minimal
    de `opsys.outils` (premier niveau seulement) ne peut plus le rejeter à ce stade — c'est
    `validation.valider_entrees`, à l'intérieur de l'orchestrateur, qui le fait, avec un verdict
    nommé (jamais un plantage ni un contrat accepté à tort)."""
    reponse = _estimer(contrat=_contrat(type_travaux="piscine"))
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["etape"] == "validation"
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    assert len(registre_production().lire()) == 0, "une entrée rejetée n'écrit rien au registre"


def test_estimer_projet_schema_refuse_contrat_absent(base_durable):
    """Une entrée absente au premier niveau (contrat, marqueur…) reste rejetée AU SCHÉMA, avant
    tout appel de la fonction — inchangé par la restructuration de type_travaux."""
    outil = _outil("m3_estimer_projet")
    arguments = {
        "marqueur": _marqueur(),
        "photos": [_photo(reference={"type": "porte", "dimensions_connues": True})],
        "seuils": SEUILS,
        "bareme": BAREME,
        "quantite": 1200,
        "plancher_rentable": 9000,
    }
    reponse = executer(outil, arguments)
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"
    assert any("contrat" in detail for detail in reponse["details"])


def test_estimer_projet_photos_insuffisantes_ecrit_quand_meme_un_maillon_avec_devis_id(base_durable):
    reponse = _estimer(photos=[_photo()], seuils={"resolution_minimale": 999999, "eclairage_minimal": 4})
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["estimation"]["prix_bloque"] is True
    assert resultat["estimation"]["devis_id"]
    assert len(registre_production().lire()) == 1


# --------------------------------------------------------- m3_generer_soumission_brouillon (durable)
def _creer_devis_durable(devis_id, **surcharges):
    arguments = {
        "devis_id": devis_id,
        "lead_id": "lead-stock-001",
        "chantier_id": None,
        "lignes": [
            {
                "description": "Gouttière alu 5 po",
                "quantite": "30",
                "unite": "pi_lin",
                "cout_unitaire": "10.00",
                "reference_besoin_materiau": None,
            }
        ],
        "taux_marge": "0.20",
        "horodatage": _HORODATAGE,
    }
    arguments.update(surcharges)
    return _appeler("m3_creer_devis", arguments)


def test_generer_soumission_brouillon_depuis_un_devis_durable_reel(base_durable):
    cree = _creer_devis_durable("M3-DEVIS-soum-stock-001")
    assert cree["ok"] is True, cree

    reponse = executer(_outil("m3_generer_soumission_brouillon"), {"devis_id": "M3-DEVIS-soum-stock-001"})
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is True
    html = reponse["resultat"]["resultat"]
    assert "M3-DEVIS-soum-stock-001" in html
    assert "360.00" in html  # prix_total = 30 * (10.00 * 1.20)
    assert "cout_unitaire" not in html


def test_generer_soumission_brouillon_devis_introuvable(base_durable):
    reponse = executer(_outil("m3_generer_soumission_brouillon"), {"devis_id": "M3-DEVIS-inconnu"})
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-DEVIS-INTROUVABLE"


# ---------------------------------------------------------- m3_detecter_devis_sans_reponse (durable)
def test_detecter_devis_sans_reponse_publie_levenement_pour_un_devis_ancien(base_durable):
    _creer_devis_durable("M3-DEVIS-relance-stock-001", horodatage="2026-09-01T10:00:00-04:00")

    reponse = _appeler(
        "m3_detecter_devis_sans_reponse",
        {"horodatage_reference": "2026-09-28T10:00:00-04:00", "delai_relance_jours": 14},
    )
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["devis_verifies"] == 1
    assert resultat["relances_publiees"] == ["M3-DEVIS-relance-stock-001"]

    assert _compte_evenements() == 1
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_sans_reponse")
        ).mappings().one()
    assert ligne["evenement_id"] == "m3-devis-sans-reponse-M3-DEVIS-relance-stock-001"
    charge = codec.decoder(ligne["charge"])
    assert charge["devis_id"] == "M3-DEVIS-relance-stock-001"
    assert charge["delai_relance_jours"] == 14


def test_detecter_devis_sans_reponse_redelivrance_ne_republie_pas(base_durable):
    _creer_devis_durable("M3-DEVIS-relance-stock-002", horodatage="2026-09-01T10:00:00-04:00")
    args = {"horodatage_reference": "2026-09-28T10:00:00-04:00", "delai_relance_jours": 14}

    premiere = _appeler("m3_detecter_devis_sans_reponse", args)
    assert premiere["ok"] is True
    seconde = _appeler("m3_detecter_devis_sans_reponse", args)
    assert seconde["ok"] is True

    assert _compte_evenements() == 1, "une seconde détection sur le même devis ne publie jamais un second événement"


def test_detecter_devis_sans_reponse_ignore_les_devis_recents_et_acceptes(base_durable):
    _creer_devis_durable("M3-DEVIS-relance-stock-003", horodatage="2026-09-27T10:00:00-04:00")  # trop récent
    _creer_devis_durable("M3-DEVIS-relance-stock-004", horodatage="2026-09-01T10:00:00-04:00")
    _appeler(
        "m3_marquer_devis_accepte",
        {"devis_id": "M3-DEVIS-relance-stock-004", "approbateur": "nathan", "horodatage": _HORODATAGE},
    )

    reponse = _appeler(
        "m3_detecter_devis_sans_reponse",
        {"horodatage_reference": "2026-09-28T10:00:00-04:00", "delai_relance_jours": 14},
    )
    assert reponse["resultat"]["devis_verifies"] == 2
    assert reponse["resultat"]["relances_publiees"] == []
    # m3_marquer_devis_accepte a déjà publié m3.devis_accepte ; aucune relance ne s'y ajoute.
    assert _compte_evenements() == 1


# ------------------------------------------------------------------- m3_verifier_politique_photos
def test_verifier_politique_photos_refuse_tant_que_non_validee(base_durable):
    reponse = executer(_outil("m3_verifier_politique_photos"), {})
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-PHOTO-POLITIQUE-NON-VALIDEE"
