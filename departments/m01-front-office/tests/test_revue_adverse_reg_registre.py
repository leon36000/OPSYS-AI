"""Revue adverse (reg) : tout champ d'un maillon M1 est couvert par la chaîne de hachage.

`_canonical_material` excluait un champ nommé `hash` (vestige) du contenu haché : une valeur portée par ce champ pouvait
être changée sans que `valider_chaine` ne le voie. Données fictives."""

import copy

from m1_front_office import registre


def _entree(**extra):
    return {"type_entree": "signal", "horodatage": "2026-07-15T14:30:00-04:00",
            "payload": {"signal_id": "abc", "canal": "telephone", "contenu_brut": "test"}, **extra}


def _registre_a_deux_maillons(**extra):
    r = registre.Registre()
    r.ajouter(_entree(**extra))
    r.ajouter(_entree(payload={"signal_id": "def", "canal": "texte", "contenu_brut": "suite"}))
    assert r.valider_chaine() == (True, None)
    return r


def test_un_champ_hash_altere_est_detecte():
    r = _registre_a_deux_maillons(hash="empreinte-originale")
    r._entrees[0]["hash"] = "empreinte-falsifiee"
    ok, verdict = r.valider_chaine()
    assert ok is False and verdict["code"] == "REJ-CHAINE-ALTEREE"


def test_un_champ_hash_retire_ou_ajoute_est_detecte():
    r = _registre_a_deux_maillons(hash="x")
    del r._entrees[0]["hash"]
    assert r.valider_chaine()[0] is False
    r2 = _registre_a_deux_maillons()
    r2._entrees[1]["hash"] = "ajout-silencieux"
    assert r2.valider_chaine()[0] is False


def test_cas_negatif_les_champs_de_chaine_restent_recalcules_et_la_chaine_saine_est_valide():
    r = _registre_a_deux_maillons()
    avant = copy.deepcopy(r.lire())
    assert r.valider_chaine() == (True, None) and r.lire() == avant
    # modifier le contenu reste détecté, comme avant
    r._entrees[0]["payload"]["contenu_brut"] = "altéré"
    assert r.valider_chaine()[0] is False
