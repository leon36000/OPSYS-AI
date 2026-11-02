"""Le registre durable de marque accepte le profil v2, refuse une validation qui n'est pas celle du signataire
(M7-MARQUE)."""

from __future__ import annotations

import copy

from m7_marketing.brand import registre

from opsys import stockage

FICTIF = True


def enregistrer(profil, signataire="nathan"):
    with stockage.transaction():
        return registre.enregistrer(profil, signataire, "2026-11-02T09:00:00-05:00")


def test_un_profil_v2_est_enregistre_relu_et_chaine(base_durable, v2):
    assert enregistrer(v2)["revision"] == 1
    with stockage.transaction():
        courant = registre.courant()
        snapshot = registre.lire_snapshot_marque()
    assert courant["statut"] == "configure" and courant["profil"]["mots_interdits"] == ["pas cher", "bas de gamme"]
    assert snapshot["preuve"]["source"] == "brand_profiles" and snapshot["preuve"]["revision"] == 1


def test_une_validation_signee_par_un_autre_que_le_signataire_est_refusee(base_durable, v2):
    v2["validation_champs"]["promesse"] = {"statut": "valide", "par": "quelqu-un-d-autre", "le": "2026-11-02"}
    r = enregistrer(v2)
    assert r["statut"] == "profil_invalide" and "signée par la personne qui configure" in r["motif"]
    with stockage.transaction():
        assert registre.courant()["statut"] == "a_configurer"  # rien n'a été écrit


def test_valider_un_enonce_absent_est_refuse(base_durable, v1):
    v1["validation_champs"] = {"promesse": {"statut": "valide", "par": "nathan", "le": "2026-11-02"}}
    assert enregistrer(v1)["statut"] == "profil_invalide"


def test_un_champ_etendu_hors_forme_n_est_jamais_enregistre(base_durable, v1):
    v1["mots_interdits"] = "pas une liste"
    assert enregistrer(v1)["statut"] == "profil_invalide"
    with stockage.transaction():
        assert registre.courant()["statut"] == "a_configurer"


def test_la_modification_console_des_cinq_champs_conserve_les_champs_v2(base_durable, v2):
    enregistrer(v2)
    v1_modifie = {k: v for k, v in copy.deepcopy(v2).items() if k in ("name", "tagline", "tone", "colors", "langue")}
    v1_modifie["tagline"] = "Une nouvelle accroche fictive"
    with stockage.transaction(), registre.preserver_options_console(1):
        r = registre.enregistrer(v1_modifie, "nathan", "2026-11-03T09:00:00-05:00")
    assert r["statut"] == "configure" and r["revision"] == 2
    assert r["profil"]["tagline"] == "Une nouvelle accroche fictive"
    assert r["profil"]["mots_interdits"] == v2["mots_interdits"] and r["profil"]["validation_champs"]


def test_une_revision_deja_enregistree_avec_un_champ_etendu_hors_forme_reste_lisible_et_le_champ_est_ignore(
    base_durable, v1, monkeypatch
):
    """Un profil écrit avant le contrat v2 sous un nom devenu champ étendu (`voix` en texte libre) ne casse pas le
    registre :
    la lecture retire le champ, le dit, et ne l'applique jamais."""
    from m7_marketing.brand import profil_v2

    v1["voix"] = "chaleureuse et directe"
    v1["valeurs"] = ["Honnêteté"]
    with monkeypatch.context() as m:
        m.setattr(profil_v2, "normaliser", lambda p: p)  # comme avant l'existence du contrat v2
        assert enregistrer(v1)["statut"] == "configure"
    with stockage.transaction():
        snapshot = registre.lire_snapshot_marque()
        courant = registre.courant()
    assert snapshot["statut"] == "configure" and "voix" not in snapshot["profil"]
    assert snapshot["profil"]["valeurs"] == ["Honnêteté"]
    assert any("voix" in a and "ignoré" in a for a in snapshot["avertissements"])
    assert "voix" not in courant["profil"]
    # une nouvelle révision, elle, est validée strictement
    assert enregistrer(v1)["statut"] == "profil_invalide"
