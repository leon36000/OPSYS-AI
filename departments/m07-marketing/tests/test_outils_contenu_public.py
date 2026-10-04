"""Tests — outil d'agent `m7_preparer_contenu_public` (adaptateur, PLAN T4.3).

Correctif de relecture (0a7aaef) : ni le consentement ni l'identité de marque ne sont des
arguments de cet outil. Le consentement vient EXCLUSIVEMENT du WCT `m4.travaux_termines` déjà
reçu et enregistré par le consommateur d'événements (registre `wct_recus`) ; l'identité de
marque vient EXCLUSIVEMENT du profil client configuré (`brand.profil_client`). Ces tests le
prouvent : par le schéma d'entrée de l'outil (ni `charge` ni `brand` acceptés), et par un test de
bout en bout sur le VRAI bus du socle (publication -> consommateur M7 -> outil appelé avec le
seul `wct_id`).

Base durable temporaire isolée (même patron que `tests/test_evenements_travaux_termines.py`) :
les registres `wct_recus`/`contenu_public` sont persistés via `opsys.stockage.maillons`, jamais
un dict en mémoire de processus.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m7_marketing import outils
from m7_marketing.moderation.detection import Detection
from m7_marketing.moderation.image import Boite

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]  # .../departments (m07-marketing/tests/..)

BRAND_VALIDE = {
    "name": "Entreprise Test Fictive",
    "tagline": "Tagline de test",
    "tone": "professionnel",
    "colors": ["#111111"],
    "langue": "fr",
}

PREUVE = {
    "consentement_recueilli_par": "etienne",
    "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
    "consentement_version_texte": "consentement-client-fr-CA-v1",
}

_CHARGE = {
    "wct_id": "wct-outil-1",
    "intervention_id": "int-1",
    "lead_id": "lead-1",
    "ville": "Repentigny",
    "type_travaux": "gouttières",
    "consentement_marketing": True,
    **PREUVE,
}

_PHOTO = {
    "reference": "chantier-apres.jpg",
    "image": {"largeur": 2, "hauteur": 2, "pixels": [[255, 0, 0]] * 4},
}

_WCT_BASE_EVENEMENT = {
    "wct_id": "wct-outil-1",
    "intervention_id": "int-1",
    "lead_id": "lead-1",
    "technicien_id": "tech-1",
    "horodatage_completion": "2026-09-28T14:00:00-04:00",
    "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
    "duree_reelle_minutes": 180,
    "ecart_signale": False,
    "revue_id": None,
    "hash_maillon": "deadbeef",
    "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
    "devis_id": "devis-1",
    "statut": "completed_verified",
    "ville": "Repentigny",
    "type_travaux": "gouttières",
    **PREUVE,
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def brand_configure(monkeypatch):
    """Le profil client configuré (jamais un argument de l'outil, jamais le gabarit par
    défaut du dépôt) — monkeypatché comme n'importe quelle dépendance externe d'un outil."""
    monkeypatch.setattr(outils.brand_profil_client, "charger_profil_client", lambda: (dict(BRAND_VALIDE), None))


class _DetecteurFixe:
    def __init__(self, detections=()):
        self._detections = detections

    def detecter(self, image):
        return list(self._detections)


def _seed_wct_recu(**overrides) -> dict:
    """Simule un WCT déjà reçu du bus (registre `wct_recus`), sans repasser par l'événement
    réel — utile pour isoler la logique de l'outil des tests de bout en bout ci-dessous."""
    charge = dict(_CHARGE, **overrides)
    stockage.maillons("m07-marketing", "wct_recus").append(charge)
    return charge


# ---------------------------------------------------------------------------
# wct_id inconnu du registre wct_recus -> refus nommé, jamais un brouillon (exigence de relecture)
# ---------------------------------------------------------------------------
def test_wct_id_inconnu_refuse(base_durable, brand_configure):
    resultat = outils.preparer_contenu_public(
        wct_id="wct-jamais-recu", photos=[_PHOTO], seuil_confiance=0.8
    )
    assert resultat["brouillon"] is None
    assert resultat["statut"] == outils.STATUT_WCT_INCONNU
    assert "wct-jamais-recu" in resultat["motif"]


def test_consentement_faux_dans_le_wct_recu_refuse(base_durable, brand_configure):
    _seed_wct_recu(consentement_marketing=False)
    resultat = outils.preparer_contenu_public(wct_id="wct-outil-1", photos=[_PHOTO], seuil_confiance=0.8)
    assert resultat["brouillon"] is None
    assert resultat["statut"] == "refuse"
    assert "consentement_marketing" in resultat["motif"]


def test_consentement_sans_preuve_dans_le_wct_recu_refuse(base_durable, brand_configure):
    """Vrai sans preuve (qui, quand, quel texte) : le consentement n'est pas documenté, refus nommé."""
    charge = {k: v for k, v in _CHARGE.items() if k != "consentement_recueilli_par"}
    stockage.maillons("m07-marketing", "wct_recus").append(charge)
    resultat = outils.preparer_contenu_public(wct_id="wct-outil-1", photos=[_PHOTO], seuil_confiance=0.8)
    assert resultat["brouillon"] is None
    assert resultat["statut"] == "refuse"
    assert "preuve" in resultat["motif"]


def test_consentement_absent_du_wct_recu_refuse(base_durable, brand_configure):
    charge = {k: v for k, v in _CHARGE.items() if k != "consentement_marketing"}
    stockage.maillons("m07-marketing", "wct_recus").append(charge)
    resultat = outils.preparer_contenu_public(wct_id="wct-outil-1", photos=[_PHOTO], seuil_confiance=0.8)
    assert resultat["brouillon"] is None
    assert resultat["statut"] == "refuse"


# ---------------------------------------------------------------------------
# Profil de marque non configuré (jamais un argument) -> refus nommé
# ---------------------------------------------------------------------------
def test_profil_marque_non_configure_refuse(base_durable):
    """Sans `brand_configure` : le VRAI chargeur fail-closed est utilisé, contre le VRAI
    `profile.yaml` du dépôt — encore le gabarit non configuré."""
    _seed_wct_recu()
    resultat = outils.preparer_contenu_public(wct_id="wct-outil-1", photos=[_PHOTO], seuil_confiance=0.8)
    assert resultat["brouillon"] is None
    assert resultat["statut"] == outils.STATUT_PROFIL_MARQUE_NON_CONFIGURE


# ---------------------------------------------------------------------------
# Comportement RÉEL de ce bac à sable : cv2 absent -> refus nommé, jamais un faux vert
# ---------------------------------------------------------------------------
def test_detecteur_reel_indisponible_dans_ce_bac_a_sable(base_durable, brand_configure):
    _seed_wct_recu()
    resultat = outils.preparer_contenu_public(wct_id="wct-outil-1", photos=[_PHOTO], seuil_confiance=0.8)
    assert resultat["brouillon"] is None
    assert resultat["statut"] == "detecteur_indisponible"
    assert "cv2" in resultat["motif"]


# ---------------------------------------------------------------------------
# Détecteur injecté (monkeypatch de l'usine par défaut) : chemin complet de l'adaptateur
# ---------------------------------------------------------------------------
def test_succes_avec_detecteur_injecte_depose_dans_le_registre(base_durable, brand_configure, monkeypatch):
    _seed_wct_recu()
    monkeypatch.setattr(
        outils.moderation_detection,
        "detecteur_opencv_par_defaut",
        lambda: _DetecteurFixe([Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=0.95)]),
    )
    resultat = outils.preparer_contenu_public(wct_id="wct-outil-1", photos=[_PHOTO], seuil_confiance=0.8)
    assert resultat["statut"] == "propose"
    assert resultat["brouillon"]["approval_status"] == "PROPOSE"
    assert resultat["brouillon"]["wct_id"] == "wct-outil-1"
    assert resultat["brouillon"]["brand_name"] == "Entreprise Test Fictive"

    registre = list(stockage.maillons("m07-marketing", "contenu_public"))
    assert len(registre) == 1
    assert registre[0]["id"] == resultat["brouillon"]["id"]


def test_idempotent_par_wct_id(base_durable, brand_configure, monkeypatch):
    _seed_wct_recu()
    monkeypatch.setattr(outils.moderation_detection, "detecteur_opencv_par_defaut", lambda: _DetecteurFixe([]))

    premier = outils.preparer_contenu_public(wct_id="wct-outil-1", photos=[_PHOTO], seuil_confiance=0.8)
    assert premier["statut"] == "propose"

    second = outils.preparer_contenu_public(wct_id="wct-outil-1", photos=[_PHOTO], seuil_confiance=0.8)
    assert second["statut"] == "deja_prepare"
    assert second["brouillon"]["id"] == premier["brouillon"]["id"]

    registre = list(stockage.maillons("m07-marketing", "contenu_public"))
    assert len(registre) == 1  # jamais un second brouillon pour le même chantier


# ---------------------------------------------------------------------------
# Contrat de l'outil (manifeste, autonomie, schéma d'entrée, exécution via le contrat générique)
# ---------------------------------------------------------------------------
def test_outil_declare_en_t1_jamais_publication_automatique():
    outil = next(o for o in outils.outils() if o.nom == "m7_preparer_contenu_public")
    assert outil.autonomie == Autonomie.T1


def test_schema_exige_wct_id_naccepte_plus_charge_ni_brand():
    """Preuve directe du correctif de relecture : le schéma d'entrée de l'outil ne porte plus
    `charge` ni `brand` — seul `wct_id` (une référence, jamais un fait) est accepté."""
    outil = next(o for o in outils.outils() if o.nom == "m7_preparer_contenu_public")
    proprietes = outil.parametres["properties"]
    assert "charge" not in proprietes
    assert "brand" not in proprietes
    assert set(proprietes) == {"wct_id", "photos", "seuil_confiance"}
    assert set(outil.parametres["required"]) == {"wct_id", "photos", "seuil_confiance"}
    assert outil.parametres["additionalProperties"] is False


def test_executer_refuse_lancien_schema_charge_et_brand(base_durable):
    """L'ancien appel (charge + brand) est maintenant rejeté par la VALIDATION DU SCHÉMA elle-
    même, avant même d'atteindre la fonction — jamais exécuté avec un consentement ou une
    identité fournis par l'appelant."""
    outil = next(o for o in outils.outils() if o.nom == "m7_preparer_contenu_public")
    reponse = executer(
        outil,
        {
            "charge": dict(_CHARGE),
            "photos": [_PHOTO],
            "brand": BRAND_VALIDE,
            "seuil_confiance": 0.8,
        },
    )
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


def test_outil_executable_via_le_contrat_generique(base_durable, brand_configure, monkeypatch):
    _seed_wct_recu(wct_id="wct-outil-executer")
    monkeypatch.setattr(outils.moderation_detection, "detecteur_opencv_par_defaut", lambda: _DetecteurFixe([]))
    outil = next(o for o in outils.outils() if o.nom == "m7_preparer_contenu_public")
    reponse = executer(
        outil,
        {"wct_id": "wct-outil-executer", "photos": [_PHOTO], "seuil_confiance": 0.8},
    )
    assert reponse["ok"] is True
    assert reponse["resultat"]["statut"] == "propose"


# ---------------------------------------------------------------------------
# Bout en bout, bus RÉEL du socle : publication m4.travaux_termines -> consommateur M7
# (registre wct_recus) -> outil appelé avec le SEUL wct_id (jamais un consentement fourni)
# ---------------------------------------------------------------------------
@pytest.fixture
def departements():
    tous = charger_departements(_RACINE_DEPARTEMENTS)
    return {"m07-marketing": tous["m07-marketing"]}


def test_e2e_bus_reel_jusqua_loutil_avec_le_seul_wct_id(base_durable, departements, brand_configure, monkeypatch):
    monkeypatch.setattr(
        outils.moderation_detection,
        "detecteur_opencv_par_defaut",
        lambda: _DetecteurFixe([Detection(type="visage", boite=Boite(0, 0, 1, 1), confiance=0.95)]),
    )

    charge = dict(_WCT_BASE_EVENEMENT, consentement_marketing=True, client_satisfait=True)
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert resume["traites"] == 1

    # L'agent n'a accès qu'au wct_id (jamais au consentement, jamais à l'identité de marque) :
    # c'est tout ce que ce test lui fournit, exactement le contrat de l'outil.
    resultat = outils.preparer_contenu_public(
        wct_id=charge["wct_id"], photos=[_PHOTO], seuil_confiance=0.8
    )
    assert resultat["statut"] == "propose"
    assert resultat["brouillon"]["wct_id"] == "wct-outil-1"
    assert resultat["brouillon"]["preuve_consentement"]["consentement_marketing"] is True


def test_e2e_bus_reel_consentement_faux_refuse_via_loutil(base_durable, departements, brand_configure):
    charge = dict(
        _WCT_BASE_EVENEMENT, wct_id="wct-e2e-refus", consentement_marketing=False, client_satisfait=False
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    resultat = outils.preparer_contenu_public(wct_id="wct-e2e-refus", photos=[_PHOTO], seuil_confiance=0.8)
    assert resultat["brouillon"] is None
    assert resultat["statut"] == "refuse"


def test_e2e_wct_recu_enregistre_meme_si_demande_avis_refusee(base_durable, departements):
    """Le registre `wct_recus` est alimenté par le SEUL fait de la réception du bus, jamais par
    le sort de la demande d'avis : ici le client a consenti à l'usage des photos, mais pas à être
    contacté pour un avis. Le contenu public reste refusé pour cause d'insatisfaction, règle distincte
    de l'éligibilité aux demandes d'avis, et le WCT reste lisible par l'outil."""
    charge = dict(
        _WCT_BASE_EVENEMENT, wct_id="wct-e2e-insatisfait", consentement_marketing=True, client_satisfait=False
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    recus = list(stockage.maillons("m07-marketing", "wct_recus"))
    assert any(r.get("wct_id") == "wct-e2e-insatisfait" for r in recus)

    demandes = list(stockage.maillons("m07-marketing", "demandes_avis"))
    assert not any(d.get("wct_id") == "wct-e2e-insatisfait" for d in demandes)  # consentement avis absent
