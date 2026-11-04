"""Régressions du parseur d'offset via l'outil public M1, avec uniquement des données fictives."""

import pytest
from m1_front_office.outils import _obtenir_registre, recevoir_message_canal, reinitialiser_registre

from opsys import taxonomie


def _preparer(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval"])
    reinitialiser_registre()


def _recevoir(timestamp, identifiant):
    return recevoir_message_canal(
        canal="sms",
        expediteur="+15145550142",
        message_id=identifiant,
        recu_le=timestamp,
        texte="Demande fictive de gouttières à Laval.",
    )


@pytest.mark.parametrize(
    ("timestamp", "attendu"),
    [
        ("Tue 2026-09-29 09:15:30 UTC+1:59", "2026-09-29T09:15:30+01:59"),
        ("Tue 2026-09-29 09:15:30 UTC-1:59", "2026-09-29T09:15:30-01:59"),
        ("Tue 2026-09-29 09:15:30 UTC+23:59", "2026-09-29T09:15:30+23:59"),
        ("Tue 2026-09-29 09:15:30 UTC-23:59", "2026-09-29T09:15:30-23:59"),
    ],
)
def test_outil_public_accepte_minutes_valides_et_heures_sous_24(
    declarer_services, timestamp, attendu
):
    _preparer(declarer_services)
    try:
        _recevoir(timestamp, "FAKE-OFFSET-VALID")
        assert _obtenir_registre().lire()[0]["horodatage"] == attendu
    finally:
        reinitialiser_registre()


@pytest.mark.parametrize(
    "timestamp",
    [
        "Tue 2026-09-29 09:15:30 UTC+1:60",
        "Tue 2026-09-29 09:15:30 UTC+1:99",
        "Tue 2026-09-29 09:15:30 UTC-1:60",
        "Tue 2026-09-29 09:15:30 UTC-1:99",
        "Tue 2026-09-29 09:15:30 UTC+24",
        "Tue 2026-09-29 09:15:30 UTC-24:00",
    ],
)
def test_outil_public_refuse_offset_hors_plage_sans_ecriture(declarer_services, timestamp):
    _preparer(declarer_services)
    try:
        with pytest.raises(ValueError, match="REJ-HORODATAGE-INVALIDE"):
            _recevoir(timestamp, "FAKE-OFFSET-INVALID")
        assert _obtenir_registre().lire() == []
    finally:
        reinitialiser_registre()


def test_outil_public_accepte_le_timestamp_de_plateforme_utc_sans_decalage(declarer_services):
    _preparer(declarer_services)
    try:
        _recevoir("Tue 2026-09-29 09:15:30 UTC", "FAKE-PLATFORM-UTC")
        assert _obtenir_registre().lire()[0]["horodatage"] == "2026-09-29T09:15:30+00:00"
    finally:
        reinitialiser_registre()
