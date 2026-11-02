"""D0 : le JOUR d'un constat de M5 se date à minuit LOCAL de l'entreprise, jamais à minuit UTC.

Le défaut (base ea631e4bc) : M5 date ses constats d'un jour du calendrier (AAAA-MM-JJ, « aujourd'hui » dans le fuseau de
l'entreprise : le planificateur le calcule avec `Ports.fuseau`), mais M8 en faisait le DÉBUT du jour en UTC. À UTC-5, ce
début tombe à 19 h la veille, heure locale : avec la fenêtre de 24 h du catalogue, toutes les mesures datées par jour
(cash libre et ses composantes, créances, factures émises, dépense comptabilisée, plaintes…) étaient PÉRIMÉES de 19 h à
minuit locales, même quand tous les passages du planificateur réussissaient.

Ici (pur, sans base) : la conversion elle-même, l'heure d'été des deux côtés du changement, un fuseau illisible
(fail-closed), puis toutes les mesures datées par jour à travers la fraîcheur, à l'instant exact de la soirée locale.
Données fictives.
"""

from __future__ import annotations

import copy
import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from m8_analytics import (
    catalogue_mesures,
    fraicheur_mesures,
    jeux_fictifs,
    moteur_mesures,
    synthese,
)

FICTIF = True
CATALOGUE = catalogue_mesures.charger()
LOCAL = ZoneInfo("America/Toronto")
UTC = dt.UTC

# Les mesures de M8 dont l'instant du dernier fait est un JOUR de M5 (ou de M1) : cash libre et ses composantes,
# créances, écritures en attente, dépense comptabilisée et son écart, plaintes (date du constat), factures émises
# (jour d'émission).
MESURES_DATEES_PAR_JOUR_DE_REFERENCE = (
    "m8_cash_libre_cad",
    "m8_solde_tresorerie_cad",
    "m8_comptes_a_payer_cad",
    "m8_taxes_a_remettre_cad",
    "m8_creances_ouvertes_cad",
    "m8_creances_90_jours_plus_cad",
    "m8_ecritures_en_attente",
    "m8_depense_pub_comptabilisee_cad",
    "m8_ecart_depense_pub_comptabilisee_cad",
    "m8_plaintes_periode",
)
MESURES_DATEES_PAR_JOUR_D_EMISSION = ("m8_factures_emises", "m8_facturation_emise_cad")


def _minuit_local(jour: str) -> dt.datetime:
    return dt.datetime.fromisoformat(jour).replace(tzinfo=LOCAL)


def _lues(jour: str = "2026-11-12", **options) -> dict[str, dict]:
    registres = jeux_fictifs.registres_fictifs(jour=jour, avec_operations=True, **options)
    return {m["metric_id"]: m for m in moteur_mesures.lire(registres, CATALOGUE)}


def _fraicheur(lues: dict[str, dict], metric_id: str, maintenant: dt.datetime) -> dict:
    mesures = fraicheur_mesures.lire_mesures_avec_fraicheur([lues[metric_id]], CATALOGUE, maintenant, {})
    return mesures[0]["fraicheur"]


# ================================================================================ la conversion d'un jour en instant
@pytest.mark.parametrize(
    ("jour", "attendu_utc"),
    [
        ("2026-11-12", "2026-11-12T05:00:00+00:00"),  # novembre : heure normale de l'Est, UTC-5
        ("2026-07-14", "2026-07-14T04:00:00+00:00"),  # juillet : heure d'été, UTC-4
        # le retour à l'heure normale a lieu le dimanche 1er novembre 2026, à 2 h : minuit local du 1er est encore en
        # heure d'été, celui du 2 est en heure normale
        ("2026-10-31", "2026-10-31T04:00:00+00:00"),
        ("2026-11-01", "2026-11-01T04:00:00+00:00"),
        ("2026-11-02", "2026-11-02T05:00:00+00:00"),
        # le passage à l'heure d'été a lieu le dimanche 8 mars 2026, à 2 h : minuit du 8 est encore en heure normale
        ("2026-03-07", "2026-03-07T05:00:00+00:00"),
        ("2026-03-08", "2026-03-08T05:00:00+00:00"),
        ("2026-03-09", "2026-03-09T04:00:00+00:00"),
    ],
)
def test_un_jour_de_m5_est_le_minuit_local_de_l_entreprise_des_deux_cotes_du_changement_d_heure(jour, attendu_utc):
    instant = synthese.jour_en_instant(jour, "America/Toronto")
    lu = dt.datetime.fromisoformat(instant)
    assert lu == dt.datetime.fromisoformat(attendu_utc), (jour, instant)
    assert lu.astimezone(LOCAL) == _minuit_local(jour)  # c'est bien minuit, heure locale


def test_le_fuseau_est_une_dimension_de_la_conversion_pas_une_constante():
    assert dt.datetime.fromisoformat(synthese.jour_en_instant("2026-11-12", "UTC")) == dt.datetime(
        2026, 11, 12, 0, 0, tzinfo=UTC
    )
    assert dt.datetime.fromisoformat(synthese.jour_en_instant("2026-11-12", "America/Halifax")) == dt.datetime(
        2026, 11, 12, 4, 0, tzinfo=UTC
    )
    assert dt.datetime.fromisoformat(synthese.jour_en_instant("2026-11-12", "America/Toronto")) == dt.datetime(
        2026, 11, 12, 5, 0, tzinfo=UTC
    )


def test_sans_fuseau_donne_c_est_celui_de_l_entreprise_pas_l_utc():
    assert synthese.FUSEAU_DEFAUT == "America/Toronto"
    assert synthese.jour_en_instant("2026-11-12") == synthese.jour_en_instant("2026-11-12", "America/Toronto")


@pytest.mark.parametrize("illisible", [None, "", "2026-13-40", "12 novembre", "2026-11-12T00:00:00+00:00", 20261112])
def test_une_date_illisible_ne_donne_aucun_instant(illisible):
    assert synthese.jour_en_instant(illisible, "America/Toronto") is None


@pytest.mark.parametrize("fuseau", [None, "", "Mars/Olympus", "../etc/passwd", "America/Toronto\n", 5])
def test_un_fuseau_illisible_ne_donne_aucun_instant_jamais_un_utc_devine(fuseau):
    assert synthese.jour_en_instant("2026-11-12", fuseau) is None


# =========================================================== le fuseau déclaré traverse tout le moteur de mesures
def _avec_fuseau(registres: dict, fuseau: str) -> dict:
    copie = copy.deepcopy(registres)
    copie["declarations"] = [*copie.get("declarations", []), {"type_entree": "fuseau_entreprise", "fuseau": fuseau}]
    return copie


def test_une_declaration_de_fuseau_change_l_instant_de_TOUTES_les_mesures_datees_par_jour_et_l_empreinte():
    """Le fuseau déclaré traverse chaque chemin de calcul (synthèse, interdépartements, constats)."""
    registres = jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True)
    halifax = _avec_fuseau(registres, "America/Halifax")
    par_defaut = {m["metric_id"]: m for m in moteur_mesures.lire(registres, CATALOGUE)}
    declare = {m["metric_id"]: m for m in moteur_mesures.lire(halifax, CATALOGUE)}
    for metric_id in MESURES_DATEES_PAR_JOUR_DE_REFERENCE + MESURES_DATEES_PAR_JOUR_D_EMISSION:
        jour = (11 if metric_id in MESURES_DATEES_PAR_JOUR_D_EMISSION else 12)
        assert dt.datetime.fromisoformat(par_defaut[metric_id]["dernier_fait_le"]) == dt.datetime(
            2026, 11, jour, 5, 0, tzinfo=UTC), metric_id  # Toronto : UTC-5
        assert dt.datetime.fromisoformat(declare[metric_id]["dernier_fait_le"]) == dt.datetime(
            2026, 11, jour, 4, 0, tzinfo=UTC), metric_id  # Halifax : UTC-4
    assert moteur_mesures.empreinte_registres(registres) != moteur_mesures.empreinte_registres(halifax)


def test_un_fuseau_declare_illisible_rend_les_mesures_datees_par_jour_de_fraicheur_inconnue_jamais_a_jour():
    registres = _avec_fuseau(jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True), "Mars/Olympus")
    lues = {m["metric_id"]: m for m in moteur_mesures.lire(registres, CATALOGUE)}
    for metric_id in (*MESURES_DATEES_PAR_JOUR_DE_REFERENCE, *MESURES_DATEES_PAR_JOUR_D_EMISSION):
        assert lues[metric_id]["dernier_fait_le"] is None, metric_id
        statut = _fraicheur(lues, metric_id, dt.datetime(2026, 11, 12, 18, 0, tzinfo=UTC))
        assert statut["statut"] == fraicheur_mesures.STATUT_INCONNU and not statut["peut_etre_montree_comme_a_jour"]


# ============================================================ toutes les mesures datées par jour, à minuit LOCAL
@pytest.mark.parametrize("metric_id", MESURES_DATEES_PAR_JOUR_DE_REFERENCE)
def test_le_dernier_fait_d_une_mesure_datee_par_jour_de_reference_est_minuit_local(metric_id):
    lues = _lues("2026-11-12")
    assert lues[metric_id]["statut"] == "calculee", metric_id
    instant = dt.datetime.fromisoformat(lues[metric_id]["dernier_fait_le"])
    assert instant == _minuit_local("2026-11-12"), (metric_id, lues[metric_id]["dernier_fait_le"])


@pytest.mark.parametrize("metric_id", MESURES_DATEES_PAR_JOUR_D_EMISSION)
def test_le_dernier_fait_d_une_mesure_datee_par_jour_d_emission_est_minuit_local_de_ce_jour(metric_id):
    lues = _lues("2026-11-12")  # les factures fictives sont émises la veille du jour de référence
    instant = dt.datetime.fromisoformat(lues[metric_id]["dernier_fait_le"])
    assert instant == _minuit_local("2026-11-11"), (metric_id, lues[metric_id]["dernier_fait_le"])


@pytest.mark.parametrize(
    "metric_id", (*MESURES_DATEES_PAR_JOUR_DE_REFERENCE, *MESURES_DATEES_PAR_JOUR_D_EMISSION)
)
def test_une_mesure_datee_par_jour_reste_a_jour_toute_la_soiree_locale_et_perime_24_h_apres_minuit_local(metric_id):
    """Le scénario du défaut : le constat du 12 novembre. 21 h locale = 02 h UTC le 13 : l'ancienne règle (début du jour
    UTC) donnait 26 h d'âge, donc périmé. La fenêtre déclarée (24 h) ne change pas : elle court depuis minuit LOCAL."""
    jour = "2026-11-12" if metric_id not in MESURES_DATEES_PAR_JOUR_D_EMISSION else "2026-11-11"
    minuit = _minuit_local(jour)
    lues = _lues("2026-11-12")
    assert lues[metric_id]["fraicheur_declaree"]["fenetre_s"] == 86400
    for heures, attendu in (
        (3, "a_jour"),  # 03 h locale
        (19.5, "a_jour"),  # 19 h 30 locale : 00 h 30 UTC le lendemain, l'ancienne règle disait « périmé » ici déjà
        (21, "a_jour"),  # 21 h locale : le cas du brief
        (23.99, "a_jour"),  # presque minuit local
        (24, "a_jour"),  # exactement la fenêtre : « au plus 24 h » (borne incluse, règle inchangée)
        (24.01, "perime"),  # la fenêtre est échue
    ):
        maintenant = (minuit + dt.timedelta(hours=heures)).astimezone(UTC)
        statut = _fraicheur(lues, metric_id, maintenant)
        assert statut["statut"] == attendu, (metric_id, heures, statut)
        assert statut["fenetre_s"] == 86400 and statut["origine_fenetre"] == "catalogue"


def test_la_composante_finance_du_score_reste_determinee_a_21_h_locale():
    """Le score de santé lit la fraîcheur du cash libre : périmé, la composante finance était indéterminée."""
    from m8_analytics import sante

    registres = jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True)
    lues = moteur_mesures.lire(registres, CATALOGUE)
    definition = sante.charger(CATALOGUE)
    configuration = sante.lire_configuration({"bornes": jeux_fictifs.BORNES_SANTE_FICTIVES}, definition)
    soir = (_minuit_local("2026-11-12") + dt.timedelta(hours=21)).astimezone(UTC)
    avec = fraicheur_mesures.lire_mesures_avec_fraicheur(lues, CATALOGUE, soir, {})
    finance = next(c for c in sante.evaluer(definition, avec, configuration)["composantes"] if c["id"] == "finance")
    cash = next(i for i in finance["indicateurs"] if i["metric_id"] == "m8_cash_libre_cad")
    assert cash["fraicheur"] == "a_jour", cash
