"""Quotas locaux (refus AVANT l'envoi, jamais en dormant) et curseurs (opaques, liés à leur source)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from m7_marketing import journal_chaine
from m7_marketing.signaux import curseurs
from m7_marketing.signaux.erreurs import ErreurSignaux
from m7_marketing.signaux.quotas import LimiteurQuota, Quota

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def test_la_minute_est_comptee_et_le_refus_dit_combien_attendre():
    lim = LimiteurQuota(Quota(par_minute=3, par_jour=None, source="test"))
    for i in range(3):
        lim.reserver(T0 + timedelta(seconds=i))
    with pytest.raises(ErreurSignaux) as exc:
        lim.reserver(T0 + timedelta(seconds=10))
    assert exc.value.code == "REJ-SIGNAUX-QUOTA-LOCAL" and exc.value.reprenable
    assert exc.value.reessayer_apres_s == 51  # 60 - 10 s depuis la première requête, arrondi supérieur
    lim.reserver(T0 + timedelta(seconds=60))  # la première est sortie de la fenêtre


def test_un_refus_ne_compte_pas_la_requete():
    lim = LimiteurQuota(Quota(par_minute=1, par_jour=5, source="test"))
    lim.reserver(T0)
    for _ in range(3):
        with pytest.raises(ErreurSignaux):
            lim.reserver(T0 + timedelta(seconds=1))
    assert lim.compte_du_jour == ("2026-11-01", 1)


def test_le_jour_est_compte_puis_remis_a_zero_a_minuit_utc():
    lim = LimiteurQuota(Quota(par_minute=None, par_jour=2, source="test"))
    lim.reserver(T0)
    lim.reserver(T0 + timedelta(hours=1))
    with pytest.raises(ErreurSignaux) as exc:
        lim.reserver(T0 + timedelta(hours=2))
    assert exc.value.reessayer_apres_s == 10 * 3600  # jusqu'à minuit UTC
    lim.reserver(datetime(2026, 11, 2, 0, 0, 1, tzinfo=UTC))
    assert lim.compte_du_jour == ("2026-11-02", 1)


def test_le_compte_du_jour_persiste_survit_a_un_redemarrage_et_le_plus_haut_gagne():
    lim = LimiteurQuota(Quota(par_minute=None, par_jour=3, source="test"))
    lim.restaurer("2026-11-01", 3)
    with pytest.raises(ErreurSignaux):
        lim.reserver(T0)
    autre = LimiteurQuota(Quota(par_minute=None, par_jour=3, source="test"))
    autre.restaurer("2026-11-01", 2)
    autre.restaurer("2026-11-01", 1)  # un compte plus bas ne diminue jamais
    autre.reserver(T0)
    with pytest.raises(ErreurSignaux):
        autre.reserver(T0)


def test_le_compte_d_un_autre_jour_est_ignore_et_les_valeurs_invalides_aussi():
    lim = LimiteurQuota(Quota(par_minute=None, par_jour=1, source="test"))
    lim.reserver(T0)
    lim.restaurer("2026-10-31", 99)
    lim.restaurer(None, 5)
    lim.restaurer("2026-11-01", -4)
    assert lim.compte_du_jour == ("2026-11-01", 1)


def test_une_horloge_sans_fuseau_est_refusee_et_un_quota_invalide_aussi():
    lim = LimiteurQuota(Quota(par_minute=1, par_jour=1, source="test"))
    with pytest.raises(ErreurSignaux):
        lim.reserver(datetime(2026, 11, 1, 12, 0))
    for mauvais in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            Quota(par_minute=mauvais, par_jour=None, source="x")


# -- curseurs
# ---------------------------------------------------------------------------------------------------------------------
def test_aller_retour_d_un_curseur_et_lien_a_la_source():
    c = curseurs.encoder_curseur("search_console", {"s": 2, "r": 500})
    assert c.startswith("sig:v1:search_console:") and curseurs.decoder_curseur("search_console", c) == {
        "s": 2,
        "r": 500,
    }
    with pytest.raises(ErreurSignaux) as exc:
        curseurs.decoder_curseur("bing_webmaster", c)
    assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"


@pytest.mark.parametrize(
    "mauvais",
    [
        None,
        5,
        "",
        "sig",
        "sig:v1:search_console",
        "sig:v2:search_console:e30",
        "autre:v1:search_console:e30",
        "sig:v1:search_console:%%%",
        "sig:v1:search_console:" + base64.urlsafe_b64encode(b"[1,2]").decode(),
        "sig:v1:search_console:" + base64.urlsafe_b64encode(b"\xff\xfe").decode(),
        "x" * 5000,
    ],
)
def test_un_curseur_illisible_ou_d_une_autre_forme_est_refuse(mauvais):
    with pytest.raises(ErreurSignaux) as exc:
        curseurs.decoder_curseur("search_console", mauvais)
    assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"


def test_un_curseur_trop_long_n_est_pas_emis():
    with pytest.raises(ErreurSignaux):
        curseurs.encoder_curseur("search_console", {"jeton": "x" * 3000})


def test_etat_d_ingestion_dernier_maillon_par_cle_et_aller_retour():
    journal: list = []
    cle = curseurs.cle_etat("search_console", "principal", "jour")
    e1 = curseurs.EtatIngestion(
        cle,
        "search_console",
        "principal",
        "jour",
        fenetre="2026-10-01/2026-10-07",
        curseur="sig:x",
        jour_quota="2026-11-01",
        appels_jour=3,
    )
    e2 = curseurs.EtatIngestion(
        cle,
        "search_console",
        "principal",
        "jour",
        fenetre="2026-10-01/2026-10-07",
        termine=True,
        watermark="2026-10-07",
        derniere_lecture_reussie_le="2026-11-01T12:00:00Z",
        donnees_jusqu_au="2026-10-07",
        dernier_echec=(("code", "REJ-SIGNAUX-RESEAU"), ("le", "2026-11-01T11:00:00Z")),
        jour_quota="2026-11-01",
        appels_jour=4,
    )
    curseurs.ecrire_etat(journal, e1, "2026-11-01T12:00:00Z")
    curseurs.ecrire_etat(journal, e2, "2026-11-01T12:05:00Z")
    lu = curseurs.lire_etats(journal)
    assert lu == {cle: e2} and lu[cle].echec() == {"code": "REJ-SIGNAUX-RESEAU", "le": "2026-11-01T11:00:00Z"}
    assert journal_chaine.integre(journal)


def test_un_maillon_etranger_dans_le_registre_des_curseurs_est_une_erreur():
    with pytest.raises(ErreurSignaux) as exc:
        curseurs.lire_etats([{"type": "autre"}])
    assert exc.value.code == "REJ-SIGNAUX-REGISTRE-INVALIDE"
    # le contenu d'un curseur ne dépasse jamais le JSON qu'on y a mis
    assert json.loads(base64.urlsafe_b64decode(curseurs.encoder_curseur("s", {"a": 1}).split(":", 3)[3] + "==")) == {
        "a": 1
    }
