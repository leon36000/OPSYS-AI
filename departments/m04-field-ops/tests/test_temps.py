"""Tests du brouillon de temps — T1.1-c#3/#4 (pont M4 -> M5, M4.4, M4.23)."""

import m4_field_ops.cedule as cedule_mod
import m4_field_ops.etats as etats_mod
import m4_field_ops.outbox as outbox_mod
import m4_field_ops.pointage as pointage_mod
import m4_field_ops.registre as registre_mod
import m4_field_ops.temps as temps_mod
import pytest

# ------------------------------------------------------------------ helpers
SEL = "sel-de-test"
VILLE = "Montreal"
REFERENTIEL = {
    cedule_mod.tokeniser_ville(SEL, VILLE): {
        "latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0,
    }
}
GPS_PROCHE = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-1"}
FENETRE = {"debut": "2025-06-01T00:00:00+00:00", "fin": "2025-06-10T23:59:59+00:00"}

CONTRAT_VALIDE = {
    "lead_id": "L1",
    "conversation_id": "C1",
    "type_travaux": "renovation_totale",
    "ville": VILLE,
    "canal": "telephone",
    "contact": {"nom": "Dupont", "telephone": "0102030405"},
    "urgence_declaree": True,
}
MARQUEUR_VALIDE = {
    "readiness_ok": True,
    "lead_id": "L1",
    "hash_tete_registre": None,
    "horodatage": "2025-06-01T12:00:00+00:00",
    "empreinte": "ab" * 32,
}


def _completer(reg, lead_id, technicien_id, h_route, h_arr, h_dep, h_completion,
                pauses=(), ecart_detecte=False):
    """Inscrit, cédule, pointe (avec pauses optionnelles) et complète une
    intervention. Retourne intervention_id."""
    contrat = dict(CONTRAT_VALIDE)
    contrat["lead_id"] = lead_id
    marqueur = dict(MARQUEUR_VALIDE)
    marqueur["lead_id"] = lead_id
    acc, ver = etats_mod.inscrire_intervention(contrat, marqueur, reg, h_route, SEL)
    assert acc is not None, f"inscription {lead_id} refusée : {ver}"
    i_id = acc["intervention_id"]
    assign = {"intervention_id": i_id, "technicien_id": technicien_id}
    acc_route, ver_route = etats_mod.transitionner(i_id, "en_route", reg, h_route, assignation=assign)
    assert acc_route is not None, f"transition en_route refusée : {ver_route}"

    sequence = [("arrivee", h_arr)]
    for debut, fin in pauses:
        sequence.append(("pause_debut", debut))
        sequence.append(("pause_fin", fin))
    sequence.append(("depart", h_dep))

    for action, horo in sequence:
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, technicien_id, action, horo, GPS_PROCHE, ATTESTATION,
            assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"{action} refusé pour {lead_id} : {ver_p}"

    acc_comp, ver_comp = outbox_mod.completer_intervention(
        i_id, h_completion, reg, ecart_detecte=ecart_detecte,
    )
    assert acc_comp is not None, f"complétion refusée pour {lead_id} : {ver_comp}"
    return i_id


# ------------------------------------------------------------------ constantes épinglées
def test_constantes_epinglees():
    assert temps_mod.CLES_LIGNE_TEMPS == (
        "technicien_id", "intervention_id", "date",
        "minutes_travail", "minutes_deplacement", "minutes_pause",
    )
    assert "taux" in temps_mod.CLES_PAIE_INTERDITES
    assert "montant" in temps_mod.CLES_PAIE_INTERDITES


# ------------------------------------------------------------------ periode
@pytest.mark.parametrize("periode_bad, code_attendu", [
    ({"debut": "2025-06-01"}, "REJ-CONTRAT-INVALIDE"),
    ({"debut": "2025-06-01", "fin": "2025-06-10", "extra": 1}, "REJ-CONTRAT-INVALIDE"),
    ({"debut": "", "fin": "2025-06-10"}, "REJ-CHAMP-VIDE"),
    ({"debut": "2025-06-01", "fin": "2025-06-10T12:00:00+00:00"}, "REJ-CONTRAT-INVALIDE"),
    ({"debut": "01-06-2025", "fin": "2025-06-10"}, "REJ-CONTRAT-INVALIDE"),
    ({"debut": "2025-06-10", "fin": "2025-06-01"}, "REJ-CONTRAT-INVALIDE"),
    ("2025-06-01", "REJ-CONTRAT-INVALIDE"),
])
def test_periode_invalide_refusee(periode_bad, code_attendu):
    reg = registre_mod.Registre()
    brouillon, verdict = temps_mod.produire_brouillon_temps(reg, periode_bad)
    assert brouillon is None
    assert verdict["code"] == code_attendu


def test_periode_bornes_incluses():
    reg = registre_mod.Registre()
    i_id = _completer(
        reg, "L1", "T1",
        "2025-06-02T08:00:00+00:00", "2025-06-02T09:00:00+00:00",
        "2025-06-02T11:30:00+00:00", "2025-06-02T11:35:00+00:00",
    )
    brouillon, verdict = temps_mod.produire_brouillon_temps(reg, {"debut": "2025-06-02", "fin": "2025-06-02"})
    assert verdict is None
    assert [ligne["intervention_id"] for ligne in brouillon["lignes"]] == [i_id]


# ------------------------------------------------------------------ brouillon vide
def test_brouillon_registre_vide():
    reg = registre_mod.Registre()
    brouillon, verdict = temps_mod.produire_brouillon_temps(reg, {"debut": "2025-06-01", "fin": "2025-06-30"})
    assert verdict is None
    assert brouillon == {
        "periode": {"debut": "2025-06-01", "fin": "2025-06-30"},
        "lignes": [],
        "depassements": [],
    }


# ------------------------------------------------------------------ ligne nominale
def test_brouillon_ligne_nominale_avec_pause_et_deplacement():
    reg = registre_mod.Registre()
    i_id = _completer(
        reg, "L1", "T1",
        h_route="2025-06-02T08:00:00+00:00",
        h_arr="2025-06-02T08:20:00+00:00",      # 20 min de trajet
        h_dep="2025-06-02T11:20:00+00:00",       # 180 min bruts sur site
        h_completion="2025-06-02T11:25:00+00:00",
        pauses=[("2025-06-02T09:00:00+00:00", "2025-06-02T09:15:00+00:00")],  # 15 min de pause
    )
    brouillon, verdict = temps_mod.produire_brouillon_temps(reg, {"debut": "2025-06-02", "fin": "2025-06-02"})
    assert verdict is None
    assert len(brouillon["lignes"]) == 1
    ligne = brouillon["lignes"][0]
    assert set(ligne.keys()) == set(temps_mod.CLES_LIGNE_TEMPS)
    assert ligne["technicien_id"] == "T1"
    assert ligne["intervention_id"] == i_id
    assert ligne["date"] == "2025-06-02"
    assert ligne["minutes_travail"] == 165       # 180 - 15 de pause
    assert ligne["minutes_deplacement"] == 20
    assert ligne["minutes_pause"] == 15


def test_brouillon_filtre_hors_periode():
    reg = registre_mod.Registre()
    _completer(
        reg, "L1", "T1",
        "2025-06-02T08:00:00+00:00", "2025-06-02T09:00:00+00:00",
        "2025-06-02T11:30:00+00:00", "2025-06-02T11:35:00+00:00",
    )
    brouillon, verdict = temps_mod.produire_brouillon_temps(reg, {"debut": "2025-06-03", "fin": "2025-06-10"})
    assert verdict is None
    assert brouillon["lignes"] == []


def test_brouillon_plusieurs_lignes_tri_deterministe():
    reg = registre_mod.Registre()
    i_c = _completer(
        reg, "LC", "T2",
        "2025-06-02T08:00:00+00:00", "2025-06-02T09:00:00+00:00",
        "2025-06-02T10:00:00+00:00", "2025-06-02T10:05:00+00:00",
    )
    i_a = _completer(
        reg, "LA", "T1",
        "2025-06-02T11:00:00+00:00", "2025-06-02T12:00:00+00:00",
        "2025-06-02T13:00:00+00:00", "2025-06-02T13:05:00+00:00",
    )
    brouillon, verdict = temps_mod.produire_brouillon_temps(reg, {"debut": "2025-06-02", "fin": "2025-06-02"})
    assert verdict is None
    ids = [ligne["intervention_id"] for ligne in brouillon["lignes"]]
    # Tri par (date, technicien_id, intervention_id) : T1 avant T2, indépendant
    # de l'ordre d'écriture au registre (T2/LC a été complétée en premier).
    assert ids == [i_a, i_c]
    techniciens = [ligne["technicien_id"] for ligne in brouillon["lignes"]]
    assert techniciens == ["T1", "T2"]


def test_brouillon_aucun_taux_ni_montant():
    reg = registre_mod.Registre()
    _completer(
        reg, "L1", "T1",
        "2025-06-02T08:00:00+00:00", "2025-06-02T09:00:00+00:00",
        "2025-06-02T11:30:00+00:00", "2025-06-02T11:35:00+00:00",
    )
    brouillon, verdict = temps_mod.produire_brouillon_temps(
        reg, {"debut": "2025-06-02", "fin": "2025-06-02"}, seuil_minutes=60,
    )
    assert verdict is None
    import json
    serialise = json.dumps(brouillon)
    for cle in temps_mod.CLES_PAIE_INTERDITES:
        assert f'"{cle}"' not in serialise


# ------------------------------------------------------------------ depassement_detecte (T1.1-c#4)
def test_depassement_detecte_vrai():
    assert temps_mod.depassement_detecte(500, 480) is True


def test_depassement_detecte_faux():
    assert temps_mod.depassement_detecte(400, 480) is False


def test_depassement_detecte_egalite_non_depassement():
    assert temps_mod.depassement_detecte(480, 480) is False


@pytest.mark.parametrize("minutes_totales, seuil_minutes", [
    (-1, 480), (480, -1), (1.5, 480), (480, 1.5), (True, 480), (480, True), ("500", 480),
])
def test_depassement_detecte_types_invalides_leve_valueerror(minutes_totales, seuil_minutes):
    with pytest.raises(ValueError):
        temps_mod.depassement_detecte(minutes_totales, seuil_minutes)


def test_brouillon_sans_seuil_minutes_aucun_depassement_signale():
    reg = registre_mod.Registre()
    _completer(
        reg, "L1", "T1",
        "2025-06-02T08:00:00+00:00", "2025-06-02T09:00:00+00:00",
        "2025-06-02T20:00:00+00:00", "2025-06-02T20:05:00+00:00",  # 660 minutes
    )
    brouillon, verdict = temps_mod.produire_brouillon_temps(reg, {"debut": "2025-06-02", "fin": "2025-06-02"})
    assert verdict is None
    assert brouillon["depassements"] == []


def test_brouillon_seuil_minutes_fourni_depassement_signale_par_technicien():
    reg = registre_mod.Registre()
    # T1 : deux interventions le même jour, total 480 + 60 = 540 minutes -> dépasse 480
    _completer(
        reg, "L1", "T1",
        "2025-06-02T07:00:00+00:00", "2025-06-02T08:00:00+00:00",
        "2025-06-02T16:00:00+00:00", "2025-06-02T16:05:00+00:00",  # 480 min
    )
    _completer(
        reg, "L2", "T1",
        "2025-06-02T16:30:00+00:00", "2025-06-02T17:00:00+00:00",
        "2025-06-02T18:00:00+00:00", "2025-06-02T18:05:00+00:00",  # 60 min
    )
    # T2 : une seule intervention de 90 minutes -> ne dépasse pas 480
    _completer(
        reg, "L3", "T2",
        "2025-06-02T08:00:00+00:00", "2025-06-02T09:00:00+00:00",
        "2025-06-02T10:30:00+00:00", "2025-06-02T10:35:00+00:00",  # 90 min
    )
    brouillon, verdict = temps_mod.produire_brouillon_temps(
        reg, {"debut": "2025-06-02", "fin": "2025-06-02"}, seuil_minutes=480,
    )
    assert verdict is None
    par_technicien = {d["technicien_id"]: d for d in brouillon["depassements"]}
    assert par_technicien["T1"]["minutes_totales"] == 540
    assert par_technicien["T1"]["depassement_detecte"] is True
    assert par_technicien["T2"]["minutes_totales"] == 90
    assert par_technicien["T2"]["depassement_detecte"] is False


@pytest.mark.parametrize("seuil_bad", [-1, 1.5, True, "480"])
def test_brouillon_seuil_minutes_invalide_refuse(seuil_bad):
    reg = registre_mod.Registre()
    brouillon, verdict = temps_mod.produire_brouillon_temps(
        reg, {"debut": "2025-06-01", "fin": "2025-06-30"}, seuil_minutes=seuil_bad,
    )
    assert brouillon is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


# ------------------------------------------------------------------ non-régression : chemin réel toujours accepté
def test_brouillon_chemin_reel_jamais_rejete():
    """Un registre construit par le chemin réel (déjà couvert par
    outbox.calculer_minutes_pause/calculer_minutes_deplacement) ne produit
    jamais de verdict de rejet ici."""
    reg = registre_mod.Registre()
    _completer(
        reg, "L1", "T1",
        "2025-06-02T08:00:00+00:00", "2025-06-02T09:00:00+00:00",
        "2025-06-02T11:30:00+00:00", "2025-06-02T11:35:00+00:00",
    )
    brouillon, verdict = temps_mod.produire_brouillon_temps(reg, {"debut": "2025-06-02", "fin": "2025-06-02"})
    assert verdict is None
    assert brouillon is not None
