"""Contrats fermés du journal privé des médias M7."""

from __future__ import annotations

from m7_marketing.usine import registre

_SNAPSHOT = "a" * 64
_SOURCE = "fichier:sha256:" + "b" * 64
_PREPARE = "fichier:sha256:" + "c" * 64


def _preparation(**changements):
    evenement = {
        "type_maillon": "media_prepare",
        "contenu_id": "contenu-fictif-1",
        "revision": 1,
        "source_ref": _SOURCE,
        "source_sha256": "b" * 64,
        "prepared_ref": _PREPARE,
        "prepared_sha256": "c" * 64,
        "prepared_mime": "image/png",
        "prepared_taille": 8,
        "snapshot_sha256": _SNAPSHOT,
        "attestation_humaine": "Préparé humainement pour ce test fictif.",
        "prepare_par": "nathan",
        "horodatage": "2026-10-01T12:00:00+00:00",
    }
    evenement.update(changements)
    return evenement


def _revue(prefixe, decision="approuver"):
    return {
        "type_maillon": "media_revue",
        "contenu_id": "contenu-fictif-1",
        "revision": len(prefixe) + 1,
        "revision_cible": len(prefixe),
        "empreinte_cible": registre._empreinte_dossier(prefixe),
        "snapshot_sha256": _SNAPSHOT,
        "decision": decision,
        "par": "nathan",
        "role": "nathan_owner",
        "source": "approbation",
        "attestation_humaine": "Vérification visuelle fictive, aucune détection automatisée.",
        "horodatage": "2026-10-01T12:01:00+00:00",
    }


def _remise(prefixe, prepared_refs):
    return {
        "type_maillon": "media_remise",
        "contenu_id": "contenu-fictif-1",
        "revision": len(prefixe) + 1,
        "revision_cible": len(prefixe),
        "empreinte_cible": registre._empreinte_dossier(prefixe),
        "snapshot_sha256": _SNAPSHOT,
        "prepared_refs": prepared_refs,
        "media_export_id": "media-export-fictif",
        "export_id": "export-fictif",
        "creneau_id": "creneau-fictif",
        "wct_id": "wct-fictif",
        "empreinte_texte": "f" * 64,
        "remis_par": "nathan",
        "horodatage": "2026-10-01T12:02:00+00:00",
    }


def test_pliage_refuse_les_types_non_hashables_sans_exception():
    for evenement in (
        _preparation(type_maillon=[]),
        _preparation(prepared_mime=[]),
        _preparation(revision=True),
        _preparation(attribut_inconnu=float("nan")),
        _preparation(attribut_inconnu="\ud800"),
    ):
        etat = registre.etat_dossier_medias([evenement], "contenu-fictif-1")
        assert etat["valide"] is False
        assert etat["statut"] == "DOSSIER_INCOHERENT"


def test_pliage_refuse_une_preparation_alteree_apres_revue():
    preparation = _preparation()
    revue = _revue([preparation])
    preparation_alteree = {**preparation, "prepared_ref": "fichier:sha256:" + "d" * 64}

    etat = registre.etat_dossier_medias(
        [preparation_alteree, revue], "contenu-fictif-1",
    )

    assert etat["valide"] is False
    assert etat["statut"] == "REVUE_PERIMEE"


def test_double_revue_courante_conserve_la_derniere_decision():
    preparation = _preparation()
    premiere = _revue([preparation])
    deuxieme = _revue([preparation, premiere], "rejeter")

    etat = registre.etat_dossier_medias(
        [preparation, premiere, deuxieme], "contenu-fictif-1",
    )

    assert etat["valide"] is True
    assert etat["statut"] == "REJETE"


def test_reprise_ouvre_une_epoch_sans_effacer_les_evenements_anterieurs():
    preparation = _preparation()
    revue = _revue([preparation])
    ancien_prefixe = [preparation, revue]
    reprise = {
        "type_maillon": "media_reprise",
        "contenu_id": "contenu-fictif-1",
        "revision": 3,
        "revision_cible": 2,
        "empreinte_cible": registre._empreinte_dossier(ancien_prefixe),
        "snapshot_sha256": "d" * 64,
        "prepare_par": "nathan",
        "horodatage": "2026-10-01T12:02:00+00:00",
    }
    preparation_courante = _preparation(
        revision=4, snapshot_sha256="d" * 64,
        prepared_ref="fichier:sha256:" + "e" * 64, prepared_sha256="e" * 64,
    )

    etat = registre.etat_dossier_medias(
        [preparation, revue, reprise, preparation_courante], "contenu-fictif-1",
    )

    assert etat["valide"] is True
    assert etat["statut"] == "EN_ATTENTE_REVUE"
    assert etat["revision"] == 4
    assert [e["type_maillon"] for e in etat["evenements"]] == ["media_reprise", "media_prepare"]
    assert etat["medias"][0]["prepared_sha256"] == "e" * 64


def test_remise_liee_a_la_revue_fige_les_evenements_suivants():
    preparation = _preparation()
    revue = _revue([preparation])
    remise = {
        "type_maillon": "media_remise",
        "contenu_id": "contenu-fictif-1",
        "revision": 3,
        "revision_cible": 2,
        "empreinte_cible": registre._empreinte_dossier([preparation, revue]),
        "snapshot_sha256": _SNAPSHOT,
        "prepared_refs": [_PREPARE],
        "media_export_id": "media-export-fictif",
        "export_id": "export-fictif",
        "creneau_id": "creneau-fictif",
        "wct_id": "wct-fictif",
        "empreinte_texte": "f" * 64,
        "remis_par": "nathan",
        "horodatage": "2026-10-01T12:02:00+00:00",
    }
    tentative_apres_remise = _preparation(revision=4)

    etat = registre.etat_dossier_medias(
        [preparation, revue, remise, tentative_apres_remise], "contenu-fictif-1",
    )

    assert etat["valide"] is False
    assert etat["statut"] == "DOSSIER_FIGE"


def test_pliage_refuse_reference_remise_absente_des_preparations_courantes():
    preparation = _preparation()
    revue = _revue([preparation])
    remise = _remise([preparation, revue], ["fichier:sha256:" + "d" * 64])

    etat = registre.etat_dossier_medias([preparation, revue, remise], "contenu-fictif-1")

    assert etat["valide"] is False
    assert etat["statut"] == "DOSSIER_INCOHERENT"


def test_pliage_accepte_deux_sources_qui_partagent_une_variante_preparee():
    premiere = _preparation()
    seconde = _preparation(
        revision=2,
        source_ref="fichier:sha256:" + "d" * 64,
        source_sha256="d" * 64,
    )
    prefixe_preparation = [premiere, seconde]
    revue = _revue(prefixe_preparation)
    prefixe_revue = [*prefixe_preparation, revue]
    remise = _remise(prefixe_revue, [_PREPARE])

    etat = registre.etat_dossier_medias([*prefixe_revue, remise], "contenu-fictif-1")

    assert etat["valide"] is True
    assert etat["statut"] == "REMIS"
    assert {media["source_ref"] for media in etat["medias"]} == {_SOURCE, seconde["source_ref"]}
