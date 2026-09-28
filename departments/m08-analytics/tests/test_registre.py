import re

from m8_analytics import registre

_CLES_MAILLON = {
    "index",
    "module_source",
    "horodatage",
    "valeurs",
    "hash_precedent",
    "hash_maillon",
}


def _snapshot(module_source="M1-planning", horodatage="2026-01-15T10:30:00Z", valeur=12):
    return {
        "module_source": module_source,
        "horodatage": horodatage,
        "valeurs": {"indicateur": valeur, "details": {"unite": "m2"}},
    }


def test_ajouter_premier_snapshot_utilise_hash_precedent_vide_et_index_zero():
    snapshots = registre.RegistreSnapshots()

    maillon, erreur = snapshots.ajouter(_snapshot())

    assert erreur is None
    assert maillon["index"] == 0
    assert maillon["hash_precedent"] == ""
    assert set(maillon) == _CLES_MAILLON
    assert re.fullmatch(r"[0-9a-f]{64}", maillon["hash_maillon"])


def test_ajouter_accepte_tout_module_source_et_retourne_toujours_maillon_sans_erreur():
    snapshots = registre.RegistreSnapshots()
    mouvement = _snapshot(module_source="MODULE-SANS-ENUMERE", valeur="valeur quelconque")

    maillon, erreur = snapshots.ajouter(mouvement)

    assert erreur is None
    assert maillon["module_source"] == "MODULE-SANS-ENUMERE"
    assert maillon["valeurs"] == mouvement["valeurs"]


def test_ajouter_chaine_les_trois_snapshots_successifs():
    snapshots = registre.RegistreSnapshots()

    premier, erreur_premier = snapshots.ajouter(_snapshot(valeur=1))
    second, erreur_second = snapshots.ajouter(
        _snapshot(horodatage="2026-01-15T10:31:00Z", valeur=2)
    )
    troisieme, erreur_troisieme = snapshots.ajouter(
        _snapshot(horodatage="2026-01-15T10:32:00Z", valeur=3)
    )

    assert erreur_premier is None
    assert erreur_second is None
    assert erreur_troisieme is None
    assert second["hash_precedent"] == premier["hash_maillon"]
    assert troisieme["hash_precedent"] == second["hash_maillon"]


def test_lire_retourne_une_copie_isolee_de_la_liste_et_des_dicts_internes():
    snapshots = registre.RegistreSnapshots()
    snapshots.ajouter(_snapshot(valeur=1))
    snapshots.ajouter(_snapshot(horodatage="2026-01-15T10:31:00Z", valeur=2))
    attendu = snapshots.lire()

    resultat = snapshots.lire()
    resultat[0]["valeurs"]["details"]["unite"] = "tonne"
    resultat.pop()

    assert snapshots.lire() == attendu


def test_hash_tete_est_vide_pour_un_registre_vide():
    snapshots = registre.RegistreSnapshots()

    assert snapshots.hash_tete() == ""


def test_hash_tete_est_le_hash_du_dernier_snapshot_ajoute():
    snapshots = registre.RegistreSnapshots()
    premier, erreur_premier = snapshots.ajouter(_snapshot(valeur=1))
    dernier, erreur_dernier = snapshots.ajouter(
        _snapshot(horodatage="2026-01-15T10:31:00Z", valeur=2)
    )

    assert erreur_premier is None
    assert erreur_dernier is None
    assert snapshots.hash_tete() == dernier["hash_maillon"]
    assert snapshots.hash_tete() != premier["hash_maillon"]


def test_ajouter_copie_les_valeurs_en_interne_immunise_contre_mutation_externe():
    snapshots = registre.RegistreSnapshots()
    mouvement = _snapshot(valeur=1)

    maillon, erreur = snapshots.ajouter(mouvement)
    assert erreur is None

    mouvement["valeurs"]["indicateur"] = 999
    mouvement["valeurs"]["details"]["unite"] = "mutee"

    assert snapshots.lire()[0]["valeurs"] == {
        "indicateur": 1,
        "details": {"unite": "m2"},
    }
    assert snapshots.valider_chaine() == (True, "")


def test_valider_chaine_accepte_une_chaine_saine_de_plusieurs_snapshots():
    snapshots = registre.RegistreSnapshots()
    snapshots.ajouter(_snapshot(valeur=1))
    snapshots.ajouter(_snapshot(horodatage="2026-01-15T10:31:00Z", valeur=2))
    snapshots.ajouter(_snapshot(horodatage="2026-01-15T10:32:00Z", valeur=3))

    assert snapshots.valider_chaine() == (True, "")


def test_valider_chaine_detecte_l_alteration_directe_du_premier_snapshot():
    snapshots = registre.RegistreSnapshots()
    snapshots.ajouter(_snapshot(valeur=1))
    snapshots.ajouter(_snapshot(horodatage="2026-01-15T10:31:00Z", valeur=2))
    snapshots._maillons[0]["valeurs"] = {"indicateur": 999}

    valide, message = snapshots.valider_chaine()

    assert valide is False
    assert "0" in message
