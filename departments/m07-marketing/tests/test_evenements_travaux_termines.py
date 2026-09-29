"""Consommateur `m4.travaux_termines` de M7 (ADR-0009 §3, PLAN T1.2-c, partie 2) : bout en bout
sur le bus d'événements réel (`opsys.evenements.repartir`), les manifestes réels du dépôt
(`opsys.departements.charger_departements`, pas les départements de démonstration du socle) et
une base SQLite temporaire migrée — jamais une simulation en mémoire.

M7 prépare une demande d'avis EN BROUILLON (écriture interne au registre du département, jamais
un envoi) seulement si le client a consenti à être contacté pour un avis (`consentement_demande_avis`,
PLAN T1.5-d, distinct de `consentement_marketing`), preuve à l'appui (qui l'a recueilli, quand, quel
texte), et que `client_satisfait` n'est pas faux ; tout champ absent vaut refus, fail-closed
(`reputation/demande_avis.py`, testé isolément dans `tests/reputation/test_demande_avis.py`). Ce
fichier prouve l'intégration réelle : bus, manifeste, registre durable, taxonomie, idempotence.

Les charges publiées ici sont des WCT synthétiques (fictifs, jamais une donnée réelle de client),
même patron que `tests/test_evenements.py::_wct_exemple` du socle.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m7_marketing.reputation import demande_avis

from opsys import evenements, stockage
from opsys.departements import charger_departements

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, isolée de ~/.opsys et de toute autre suite (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements():
    """Manifestes réels de `departments/` (pas une fixture de démonstration) : preuve que
    `department.yaml:evenements.consomme` et `m7_marketing.outils.consommateurs()` s'accordent
    pour de vrai, exactement comme `opsys-metier verifier` et `opsys-metier evenements repartir` en production."""
    # Seul ce département reçoit les événements : les autres consommateurs (M2, M10…) ont
    # leurs propres préconditions et leurs propres tests.
    tous = charger_departements(_RACINE_DEPARTEMENTS)
    return {"m07-marketing": tous["m07-marketing"]}


def _wct_travaux_termines(**overrides):
    base = {
        "wct_id": "wct-m7-nominal",
        "intervention_id": "int-1",
        "lead_id": "lead-1",
        "technicien_id": "tech-1",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 245,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
        "devis_id": "devis-1",
        "statut": "completed_verified",
    }
    base.update(overrides)
    return base


PREUVE_CONSENTEMENT = {
    "consentement_recueilli_par": "etienne",
    "consentement_recueilli_le": "2026-09-28T18:05:00+00:00",
    "consentement_version_texte": "consentement-client-fr-CA-v1",
}


def _wct_consenti(**overrides):
    """Un WCT dont le client a consenti à la demande d'avis, avec la preuve que M4 y pose."""
    return _wct_travaux_termines(consentement_demande_avis=True, **PREUVE_CONSENTEMENT, **overrides)


def _demandes_avis() -> list[dict]:
    return list(stockage.maillons("m07-marketing", "demandes_avis"))


def _wct_recus() -> list[dict]:
    return list(stockage.maillons("m07-marketing", "wct_recus"))


# ---------------------------------------------------------------------------
# Autorisation : consentement vrai ET client satisfait -> brouillon déposé, jamais envoyé
# ---------------------------------------------------------------------------
def test_consentement_vrai_et_client_satisfait_depose_un_brouillon(base_durable, departements):
    charge = _wct_consenti(
        wct_id="wct-m7-consentement-ok", ville="Repentigny", type_travaux="gouttières",
        client_satisfait=True,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    # M7 ET M8 sont tous deux abonnés à m4.travaux_termines (T1.2-c) : les deux sont traités.
    assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

    demandes = _demandes_avis()
    assert len(demandes) == 1
    brouillon = demandes[0]
    assert brouillon["wct_id"] == "wct-m7-consentement-ok"
    assert brouillon["approval_status"] == "PROPOSE"  # jamais un envoi
    assert brouillon["ville"] == "Repentigny"
    assert brouillon["type_travaux"] == "gouttières"
    assert brouillon["preuve_consentement"]["recueilli_par"] == "etienne"  # le consentement se relit


# ---------------------------------------------------------------------------
# Fail-closed : consentement absent, consentement faux, client insatisfait -> aucun brouillon
# ---------------------------------------------------------------------------
def test_consentement_absent_ne_depose_aucun_brouillon(base_durable, departements):
    charge = _wct_travaux_termines(wct_id="wct-m7-consentement-absent", client_satisfait=True)
    assert "consentement_demande_avis" not in charge
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert _demandes_avis() == []


def test_consentement_faux_et_client_insatisfait_ne_depose_aucun_brouillon(base_durable, departements):
    charge = _wct_travaux_termines(
        wct_id="wct-m7-refus", consentement_demande_avis=False, client_satisfait=False,
        **PREUVE_CONSENTEMENT,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert _demandes_avis() == []


def test_client_insatisfait_seul_ne_depose_aucun_brouillon(base_durable, departements):
    """Le consentement vrai ne suffit pas : `client_satisfait = false` refuse aussi."""
    charge = _wct_consenti(wct_id="wct-m7-client-insatisfait", client_satisfait=False)
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert _demandes_avis() == []


def test_le_consentement_aux_photos_ne_depose_aucun_brouillon_d_avis(base_durable, departements):
    """Deux consentements distincts (Loi 25) : `consentement_marketing` (photos) n'est pas celui de la demande
    d'avis. Le WCT est quand même enregistré : le contenu public, lui, le lit."""
    charge = _wct_travaux_termines(
        wct_id="wct-m7-photos-seulement", consentement_marketing=True, client_satisfait=True,
        **PREUVE_CONSENTEMENT,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert _demandes_avis() == []
    assert [recu["wct_id"] for recu in _wct_recus()] == ["wct-m7-photos-seulement"]


def test_un_consentement_sans_preuve_ne_depose_aucun_brouillon(base_durable, departements):
    """Un consentement que personne ne peut relire (ni qui, ni quand, ni quel texte) n'est pas documenté."""
    charge = _wct_travaux_termines(wct_id="wct-m7-sans-preuve", consentement_demande_avis=True)
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)

    resume = evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert _demandes_avis() == []


# ---------------------------------------------------------------------------
# Nature des travaux (PLAN T0.13-b) : `type_travaux` d'un lead v1, libellé du service d'un lead v2
# ---------------------------------------------------------------------------
def test_lead_v1_le_brouillon_dit_type_travaux(base_durable, departements):
    charge = _wct_consenti(wct_id="wct-m7-v1", type_travaux="renovation_totale", client_satisfait=True)
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    (brouillon,) = _demandes_avis()
    assert (brouillon["type_travaux"], brouillon["service"]) == ("renovation_totale", None)
    assert "(renovation totale)" in brouillon["texte"]


def test_lead_v2_le_brouillon_dit_le_libelle_du_service_declare(base_durable, departements, declarer_services):
    declarer_services()
    charge = _wct_consenti(wct_id="wct-m7-v2", service="gouttieres")
    assert "type_travaux" not in charge
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    (brouillon,) = _demandes_avis()
    assert (brouillon["service"], brouillon["type_travaux"]) == ("gouttieres", None)
    assert brouillon["nature_travaux"] == "Gouttières et descentes"  # le libellé fr-CA de la taxonomie
    assert "(Gouttières et descentes)" in brouillon["texte"]
    assert "gouttieres" not in brouillon["texte"]
    assert brouillon["avertissements"] == []


def test_lead_v2_avec_un_service_propre_de_l_entreprise_dit_son_libelle(base_durable, departements, declarer_services):
    declarer_services("gouttieres", {"code": "pose_pergola", "libelle": "Pose de pergolas"})
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_consenti(
        wct_id="wct-m7-v2-propre", service="pose_pergola"))
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    (brouillon,) = _demandes_avis()
    assert "(Pose de pergolas)" in brouillon["texte"]


def test_lead_v2_dont_le_service_n_est_plus_declare_ne_perd_pas_la_demande_et_le_dit(
    base_durable, departements, declarer_services,
):
    """L'entreprise a retiré ce service de son profil depuis : la demande d'avis (le client a consenti) n'est
    pas perdue, mais son texte reste générique, le code brut n'y entre pas, et le brouillon consigne pourquoi."""
    declarer_services("revetement")
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_consenti(
        wct_id="wct-m7-v2-non-declare", service="gouttieres"))
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    (brouillon,) = _demandes_avis()
    assert brouillon["service"] == "gouttieres" and brouillon["nature_travaux"] is None
    assert "gouttieres" not in brouillon["texte"] and "None" not in brouillon["texte"]
    (avertissement,) = brouillon["avertissements"]
    assert "gouttieres" in avertissement and "REJ-SERVICE-INCONNU" in avertissement
    assert "entreprise.yaml" not in avertissement  # jamais un chemin du serveur dans un brouillon


def test_lead_v2_sans_profil_d_entreprise_garde_la_demande_sans_nature(base_durable, departements):
    """Aucun service déclaré (instance non configurée) : fail-closed de la taxonomie, sans repli sur le code."""
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_consenti(
        wct_id="wct-m7-v2-sans-profil", service="gouttieres"))
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    (brouillon,) = _demandes_avis()
    assert brouillon["nature_travaux"] is None
    assert "REJ-SERVICE-NON-CONFIGURE" in brouillon["avertissements"][0]


# ---------------------------------------------------------------------------
# Idempotence : une relivraison du même fait (même wct_id) ne dépose jamais un second brouillon
# ---------------------------------------------------------------------------
def test_relivraison_est_idempotente_un_seul_brouillon(base_durable, departements):
    charge = _wct_consenti(wct_id="wct-m7-relivraison", client_satisfait=True)

    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-m7-1")
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    demandes_apres_1 = _demandes_avis()
    assert len(demandes_apres_1) == 1
    id_initial = demandes_apres_1[0]["id"]

    # Relivraison : le même fait (même wct_id), publié une seconde fois sous un NOUVEL
    # evenement_id — un evenement_id identique serait déjà un no-op au niveau de l'outbox
    # elle-même (ADR-0009 §3) ; ceci teste l'idempotence du CONSOMMATEUR, une garantie plus forte
    # (ex. producteur qui rejoue l'émission après une panne réseau sans réutiliser l'id).
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-m7-2")
    resume2 = evenements.repartir(departements, maintenant="2026-09-28T18:05:00+00:00")
    assert resume2 == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

    demandes_apres_2 = _demandes_avis()
    assert len(demandes_apres_2) == 1  # jamais un second brouillon pour le même wct_id
    assert demandes_apres_2[0]["id"] == id_initial

    # `repartir()` lui-même ne rejoue jamais un événement déjà traité pour ce consommateur.
    resume3 = evenements.repartir(departements, maintenant="2026-09-28T18:10:00+00:00")
    assert resume3 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(_demandes_avis()) == 1


# ---------------------------------------------------------------------------
# Aucun contenu public, aucune photo publiée (garde-fou documenté dans demande_avis.py)
# ---------------------------------------------------------------------------
def test_brouillon_ne_porte_jamais_de_photo(base_durable, departements):
    charge = _wct_consenti(
        wct_id="wct-m7-photos", consentement_marketing=True, client_satisfait=True,
        photos=["chantier-avant.jpg", "chantier-apres.jpg"],
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    demandes = _demandes_avis()
    assert len(demandes) == 1
    assert "photos" not in demandes[0]
    assert set(demandes[0]) == {
        "id", "type", "wct_id", "intervention_id", "lead_id", "ville", "type_travaux", "service",
        "nature_travaux", "texte", "preuve_consentement", "avertissements", "approval_status",
    }


# ---------------------------------------------------------------------------
# Registre `wct_recus` (correctif de relecture, 0a7aaef) : source de vérité du consentement pour
# `m7_preparer_contenu_public` — alimenté par le SEUL fait de la réception du bus, jamais par le
# sort de la demande d'avis, jamais par un argument d'outil (AGENTS.md « le LLM orchestre, il ne
# fournit jamais un fait »).
# ---------------------------------------------------------------------------
def test_wct_recu_enregistre_quand_la_demande_avis_est_autorisee(base_durable, departements):
    charge = _wct_travaux_termines(
        wct_id="wct-m7-recu-ok", consentement_marketing=True, client_satisfait=True,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    recus = _wct_recus()
    assert len(recus) == 1
    assert recus[0]["wct_id"] == "wct-m7-recu-ok"
    assert recus[0]["consentement_marketing"] is True


def test_wct_recu_enregistre_meme_si_la_demande_avis_est_refusee(base_durable, departements):
    """Le point central du correctif : un refus de demande d'avis (ici, consentement absent)
    n'empêche JAMAIS d'enregistrer le fait reçu — c'est justement ce fait, tel quel, que
    `m7_preparer_contenu_public` doit pouvoir consulter plus tard par wct_id."""
    charge = _wct_travaux_termines(wct_id="wct-m7-recu-refuse", client_satisfait=True)
    assert "consentement_marketing" not in charge
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    assert _demandes_avis() == []  # la demande d'avis, elle, reste bien refusée (inchangé)

    recus = _wct_recus()
    assert len(recus) == 1
    assert recus[0]["wct_id"] == "wct-m7-recu-refuse"
    assert "consentement_marketing" not in recus[0]  # le fait reçu, tel quel, rien d'ajouté


def test_wct_recu_consentement_faux_est_enregistre_tel_quel(base_durable, departements):
    charge = _wct_travaux_termines(
        wct_id="wct-m7-recu-faux", consentement_marketing=False, client_satisfait=False,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")

    recus = _wct_recus()
    assert len(recus) == 1
    assert recus[0]["consentement_marketing"] is False


def test_wct_recu_idempotent_sur_relivraison(base_durable, departements):
    charge = _wct_travaux_termines(
        wct_id="wct-m7-recu-relivraison", consentement_marketing=True, client_satisfait=True,
    )
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-wct-1")
    evenements.repartir(departements, maintenant="2026-09-28T18:00:00+00:00")
    assert len(_wct_recus()) == 1

    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="evt-wct-2")
    evenements.repartir(departements, maintenant="2026-09-28T18:05:00+00:00")
    recus = _wct_recus()
    assert len(recus) == 1  # jamais un second enregistrement pour le même wct_id


def test_module_pur_demande_avis_naimporte_jamais_opsys():
    """Modules purs (AGENTS.md/T1.2-c) : `reputation/demande_avis.py` ne connaît pas `opsys` —
    seul l'adaptateur `outils.py` sait où persister le brouillon."""
    source = Path(demande_avis.__file__).read_text(encoding="utf-8")
    assert "import opsys" not in source
    assert "from opsys" not in source
