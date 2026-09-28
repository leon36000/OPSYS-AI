"""PLAN T1.4-d, partie serveur (R12 §4, docs/architecture/IDEMPOTENCE.md §5) : pendant un appel
d'appareil, `m4_pointer` retient l'heure de RÉCEPTION DU SERVEUR comme heure qui fait foi pour la
paie — jamais l'horloge (potentiellement déréglée) de l'appareil, ni la valeur `horodatage` que
l'appelant a fournie — et garde l'heure de l'appareil lisible À CÔTÉ. `m4_produire_brouillon_temps`
calcule depuis cette heure qui fait foi (aucun changement nécessaire dans `temps.py`/`outbox.py` :
la durée réelle et les minutes de déplacement/pause sont TOUJOURS dérivées du champ `horodatage`
des maillons de pointage, corrigé à la SOURCE par `outils.py`, T1.4-d). Hors appel d'appareil
(aucun `contexte.receptionne_de` actif) : comportement strictement inchangé, comme avant T1.4-b.

Même patron que `test_evenements_m4.py` (`contexte.receptionne_de`, socle T1.4-b) : ces tests
n'exercent pas l'idempotence elle-même (déjà prouvée par `tests/test_idempotence.py`), seulement
ce que M4 en FAIT une fois `contexte.horodatage_reception()` non nul.
"""

from __future__ import annotations

import datetime as dt

import pytest
from m4_field_ops import cedule
from m4_field_ops.outils import outils

from opsys import contexte, stockage
from opsys.outils import executer_atomique

SEL = "sel-t14d"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T14D"}
FENETRE = {"debut": "2025-06-02T00:00:00+00:00", "fin": "2025-06-03T00:00:00+00:00"}
PERIODE = {"debut": "2025-06-02", "fin": "2025-06-02"}
_PREUVES_OK = {
    "checklist_complete": True, "photos_apres": ["photo-apres.jpg"], "notes": "RAS.", "signature": None,
}

# Horloge d'appareil DÉRÉGLÉE (an 2000) : si elle fuite dans un calcul, la durée deviendrait
# négative ou aberrante — le test la détecterait immédiatement plutôt que de rester silencieux.
_HORLOGE_APPAREIL_DEREGLEE = dt.datetime(2000, 1, 1, 0, 0, 0, tzinfo=dt.UTC)


def _horodatage_appareil(recu_le: dt.datetime) -> contexte.HorodatageAppareil:
    return contexte.HorodatageAppareil(
        appareil="tel-technicien-t14d-fictif",
        horodatage_appareil=_HORLOGE_APPAREIL_DEREGLEE,
        recu_le=recu_le,
    )


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _planifier_et_router(par_nom, lead_id):
    contrat = {
        "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
        "ville": VILLE, "canal": "telephone",
        "contact": {"nom": "Client", "telephone": "0102030405"}, "urgence_declaree": False,
    }
    marqueur = {
        "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32,
    }
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": contrat, "marqueur": marqueur,
        "horodatage": "2025-06-02T07:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]

    # PLAN T4.2 (POLITIQUE-geolocalisation.md §4) : m4_pointer n'enregistre un fix GPS QUE si le
    # consentement est actif — précondition nécessaire avant tout pointage à fix réel ci-dessous.
    consentement = executer_atomique(par_nom["m4_definir_consentement_gps"], {
        "technicien_id": "T1", "action": "donne", "horodatage": "2025-06-02T06:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": "consentement-test"},
    })
    assert consentement["ok"] is True and consentement["resultat"]["accepte"] is True, consentement

    depart = executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": "T1", "horodatage": "2025-06-02T07:30:00+00:00",
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart
    return i_id


def _referentiel():
    token = cedule.tokeniser_ville(SEL, VILLE)
    return {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


def test_pointage_appareil_horloge_dereglee_paie_brouillon_suit_heure_serveur(base_durable):
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_et_router(par_nom, "L-T14D-DEREGLE")

    recu_arrivee = dt.datetime(2025, 6, 2, 9, 0, 0, tzinfo=dt.UTC)
    recu_depart = dt.datetime(2025, 6, 2, 11, 30, 0, tzinfo=dt.UTC)  # 150 minutes après

    with contexte.receptionne_de(_horodatage_appareil(recu_arrivee)):
        r_arrivee = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": "arrivee",
            # `horodatage` fourni délibérément absurde (même valeur que l'horloge d'appareil
            # déréglée) : PROUVE qu'il est bien ignoré au profit du contexte, pas seulement que
            # l'un des deux, par coïncidence, était correct.
            "horodatage": _HORLOGE_APPAREIL_DEREGLEE.isoformat(),
            "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
        })
    assert r_arrivee["ok"] is True and r_arrivee["resultat"]["accepte"] is True, r_arrivee
    assert r_arrivee["resultat"]["resultat"]["horodatage"] == recu_arrivee.isoformat()
    assert r_arrivee["resultat"]["resultat"]["horodatage_appareil"] == _HORLOGE_APPAREIL_DEREGLEE.isoformat()

    with contexte.receptionne_de(_horodatage_appareil(recu_depart)):
        r_depart = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": "depart",
            "horodatage": _HORLOGE_APPAREIL_DEREGLEE.isoformat(),
            "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
        })
    assert r_depart["ok"] is True and r_depart["resultat"]["accepte"] is True, r_depart
    assert r_depart["resultat"]["resultat"]["horodatage"] == recu_depart.isoformat()
    assert r_depart["resultat"]["resultat"]["horodatage_appareil"] == _HORLOGE_APPAREIL_DEREGLEE.isoformat()

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": recu_depart.isoformat(),
        "preuves_completion": _PREUVES_OK,
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion

    brouillon = executer_atomique(par_nom["m4_produire_brouillon_temps"], {"periode": PERIODE})
    assert brouillon["ok"] is True and brouillon["resultat"]["accepte"] is True, brouillon
    [ligne] = [
        entree for entree in brouillon["resultat"]["resultat"]["lignes"]
        if entree["intervention_id"] == i_id
    ]
    # 150 minutes = l'écart entre les deux heures de RÉCEPTION SERVEUR ; si l'horloge d'appareil
    # (identique aux deux pointages, donc 0 minute) avait fuité dans le calcul, ceci échouerait.
    assert ligne["minutes_travail"] == 150


def test_pointage_hors_appel_appareil_comportement_inchange(base_durable):
    """Sans `contexte.receptionne_de` actif : `horodatage` fait foi comme avant T1.4-b, et
    aucune clé `horodatage_appareil` n'apparaît nulle part (ni accusé, ni maillon)."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_et_router(par_nom, "L-T14D-SANS-APPAREIL")

    h_arrivee = "2025-06-02T09:00:00+00:00"
    h_depart = "2025-06-02T11:30:00+00:00"  # 150 minutes après

    r_arrivee = executer_atomique(par_nom["m4_pointer"], {
        "intervention_id": i_id, "technicien_id": "T1", "action": "arrivee", "horodatage": h_arrivee,
        "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
        "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
    })
    assert r_arrivee["ok"] is True and r_arrivee["resultat"]["accepte"] is True, r_arrivee
    assert r_arrivee["resultat"]["resultat"]["horodatage"] == h_arrivee
    assert "horodatage_appareil" not in r_arrivee["resultat"]["resultat"]

    r_depart = executer_atomique(par_nom["m4_pointer"], {
        "intervention_id": i_id, "technicien_id": "T1", "action": "depart", "horodatage": h_depart,
        "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
        "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
    })
    assert r_depart["ok"] is True and r_depart["resultat"]["accepte"] is True, r_depart
    assert r_depart["resultat"]["resultat"]["horodatage"] == h_depart
    assert "horodatage_appareil" not in r_depart["resultat"]["resultat"]

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": h_depart, "preuves_completion": _PREUVES_OK,
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion

    brouillon = executer_atomique(par_nom["m4_produire_brouillon_temps"], {"periode": PERIODE})
    assert brouillon["ok"] is True and brouillon["resultat"]["accepte"] is True, brouillon
    [ligne] = [
        entree for entree in brouillon["resultat"]["resultat"]["lignes"]
        if entree["intervention_id"] == i_id
    ]
    assert ligne["minutes_travail"] == 150


# ==================================================================================
# PLAN T4.2 : m4_demarrer_route suit le MÊME patron que m4_pointer ci-dessus (T1.4-d, R12 §4) —
# pendant un appel d'appareil, l'heure de RÉCEPTION DU SERVEUR fait foi pour la transition
# en_route, jamais l'horloge de l'appareil ni la valeur `horodatage` fournie ; l'heure d'appareil
# reste lisible À CÔTÉ, sur l'accusé SEULEMENT (``etats.transitionner`` reste inchangé — le
# maillon de transition, lui, ne porte jamais ``horodatage_appareil``, décision de ``outils.py``
# seul, comme documenté dans ``outils.py::demarrer_route``).
# ==================================================================================
def _planifier_seul(par_nom, lead_id):
    contrat = {
        "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
        "ville": VILLE, "canal": "telephone",
        "contact": {"nom": "Client", "telephone": "0102030405"}, "urgence_declaree": False,
    }
    marqueur = {
        "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32,
    }
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": contrat, "marqueur": marqueur,
        "horodatage": "2025-06-02T07:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
    })
    assert plan["ok"] is True, plan
    return plan["resultat"]["intervention_id"]


def test_demarrer_route_appareil_horloge_dereglee_heure_serveur_fait_foi(base_durable):
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_seul(par_nom, "L-ROUTE-T14D-DEREGLE")

    recu_le = dt.datetime(2025, 6, 2, 7, 30, 0, tzinfo=dt.UTC)
    with contexte.receptionne_de(_horodatage_appareil(recu_le)):
        depart = executer_atomique(par_nom["m4_demarrer_route"], {
            "intervention_id": i_id, "technicien_id": "T1",
            # Volontairement absurde (même valeur que l'horloge d'appareil déréglée) : PROUVE
            # qu'elle est bien ignorée, pas seulement que l'une des deux valeurs, par coïncidence,
            # était correcte — même patron que le test m4_pointer ci-dessus.
            "horodatage": _HORLOGE_APPAREIL_DEREGLEE.isoformat(),
        })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart
    accuse = depart["resultat"]["resultat"]
    assert accuse["horodatage"] == recu_le.isoformat()
    assert accuse["horodatage_appareil"] == _HORLOGE_APPAREIL_DEREGLEE.isoformat()
    assert accuse["statut"] == "en_route"

    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "en_route"

    # Le maillon de transition lui-même (registre durable) porte l'heure de RÉCEPTION DU SERVEUR
    # qui fait foi — jamais l'horloge d'appareil, qui n'apparaît nulle part dans le registre.
    with stockage.transaction():
        from m4_field_ops.registre import Registre
        reg = Registre(stockage.maillons("m04-field-ops", "principal"))
        maillon = next(
            m for m in reg.lire()
            if m.get("intervention_id") == i_id and m.get("statut") == "en_route"
        )
    assert maillon["horodatage"] == recu_le.isoformat()
    assert "horodatage_appareil" not in maillon


def test_demarrer_route_hors_appel_appareil_comportement_inchange(base_durable):
    """Sans `contexte.receptionne_de` actif : `horodatage` fait foi comme avant PLAN T4.2, et
    aucune clé `horodatage_appareil` n'apparaît nulle part (ni accusé, ni maillon)."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_seul(par_nom, "L-ROUTE-T14D-SANS-APPAREIL")

    h_route = "2025-06-02T07:30:00+00:00"
    depart = executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": "T1", "horodatage": h_route,
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart
    accuse = depart["resultat"]["resultat"]
    assert accuse["horodatage"] == h_route
    assert "horodatage_appareil" not in accuse

    with stockage.transaction():
        from m4_field_ops.registre import Registre
        reg = Registre(stockage.maillons("m04-field-ops", "principal"))
        maillon = next(
            m for m in reg.lire()
            if m.get("intervention_id") == i_id and m.get("statut") == "en_route"
        )
    assert maillon["horodatage"] == h_route
    assert "horodatage_appareil" not in maillon
