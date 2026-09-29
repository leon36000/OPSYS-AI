"""Mesure d'un chantier terminé par le bus d'événements réel (PLAN T1.5-d) : M8 consomme
`m4.travaux_termines`, `m3.devis_accepte` et `m6.variance_chantier`, mesure à chaque arrivée et
publie `m8.alerte_proposee` pour M9.

Bout en bout, sans doublure : `opsys.evenements.repartir`, les manifestes réels
(`charger_departements`, M8 seul abonné) et une base SQLite temporaire migrée. Les charges sont des
événements synthétiques et fictifs, validés par le catalogue à la publication. Les seuils sont
posés dans un `department.yaml` temporaire (`_MANIFESTE`) : le vrai n'en fixe aucun.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_MAINTENANT = "2026-09-28T18:00:00+00:00"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements():
    """Manifestes réels ; M8 seul reçoit les événements (les autres ont leurs propres tests)."""
    return {"m08-analytics": charger_departements(_RACINE_DEPARTEMENTS)["m08-analytics"]}


@pytest.fixture
def configurer(tmp_path, monkeypatch):
    """Pose `department.yaml/configuration` du test ; sans appel, M8 lit le vrai manifeste (aucun seuil)."""
    def poser(seuils_alerte=None, performance_equipe=None):
        manifeste = tmp_path / "department.yaml"
        configuration = {}
        if seuils_alerte is not None:
            configuration["seuils_alerte"] = seuils_alerte
        if performance_equipe is not None:
            configuration["performance_equipe"] = performance_equipe
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}), encoding="utf-8")
        monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)
    return poser


def _wct(**surcharges):
    base = {
        "wct_id": "wct-m8-1", "intervention_id": "int-1", "lead_id": "lead-1", "technicien_id": "tech-fictif-a",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None, "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"], "devis_id": "devis-m8-1",
        "statut": "completed_verified",
    }
    base.update(surcharges)
    return base


def _devis(**surcharges):
    base = {
        "devis_id": "devis-m8-1", "lead_id": "lead-1", "chantier_id": None,
        "lignes": [{
            "reference_ligne": "devis-m8-1-L0", "description": "Gouttières 5po (fictif)", "quantite": "40",
            "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00", "reference_besoin_materiau": None,
        }],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
        "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
    }
    base.update(surcharges)
    return base


def _variance(wct_id="wct-m8-1", statut="evaluee", **surcharges):
    evalue = statut == "evaluee"
    base = {
        "evenement_id": f"m6-variance-{wct_id}-{statut}", "wct_id": wct_id, "intervention_id": "int-1",
        "chantier_id": "ch-1", "statut_variance": statut, "signal_critique": True if evalue else None,
        "seuil_pourcentage": 0.3, "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "lignes": [
            {"materiau": "gouttiere-fictif", "unite": "pi", "quantite_prevue": "40", "quantite_reelle": "56",
             "ecart_pourcentage": "0.4", "critique": True},
            {"materiau": "crochet-fictif", "unite": "u", "quantite_prevue": "20", "quantite_reelle": "22",
             "ecart_pourcentage": "0.1", "critique": False},
        ] if evalue else None,
    }
    base.update(surcharges)
    return base


def _publier(type_evenement, producteur, charge, evenement_id=None):
    evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)


def _livrer(departements, maintenant=_MAINTENANT):
    return evenements.repartir(departements, maintenant=maintenant)


def _faits():
    return list(stockage.maillons("m08-analytics", "faits_chantier"))


def _alertes():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m8.alerte_proposee")
            .order_by(EVENEMENTS_SORTANTS.c.cree_le)
        ).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


def _mesures(wct_id="wct-m8-1"):
    par_nom = {o.nom: o for o in m8_outils.outils()}
    reponse = executer_atomique(par_nom["m8_lire_mesures_chantier"], {"wct_id": wct_id})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _par_metrique(resultat):
    return {m["metric_id"]: m for m in resultat["mesures"]}


# ---------------------------------------------------------------------------
# Le WCT seul : rien n'est inventé
# ---------------------------------------------------------------------------
def test_le_wct_seul_donne_des_mesures_non_calculables_qui_nomment_ce_qui_manque(base_durable, departements):
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    assert _livrer(departements) == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

    assert [f["type_entree"] for f in _faits()] == ["wct"]
    mesures = _par_metrique(_mesures())
    assert {m["statut"] for m in mesures.values()} == {"non_calculable"}
    assert all(m["valeur"] is None for m in mesures.values())  # jamais un zéro, jamais une moyenne
    assert mesures["m8_ecart_duree_pct"]["manque"][0]["champ"] == "duree_estimee_minutes"
    assert {c["champ"] for c in mesures["m8_marge_prevue_cad"]["manque"]} == {"prix_total", "cout_total"}
    assert _alertes() == []  # rien de calculé, rien d'alerté


def test_le_faits_du_wct_ne_portent_ni_cout_ni_marge_et_le_snapshot_existant_est_inchange(base_durable, departements):
    _publier("m4.travaux_termines", "m04-field-ops", _wct(type_travaux="gouttières"))
    _livrer(departements)

    fait = _faits()[0]
    assert set(fait) == {
        "type_entree", "wct_id", "intervention_id", "devis_id", "technicien_id", "horodatage_completion",
        "duree_reelle_minutes", "statut",
    }
    snapshots = [m for m in stockage.maillons("m08-analytics", "snapshots") if m["module_source"] == "m04-field-ops"]
    assert snapshots[0]["valeurs"] == {
        "m4_wct_id": "wct-m8-1", "m4_intervention_id": "int-1", "m4_duree_reelle_minutes": "120",
        "m4_type_travaux": "gouttières",
    }


# ---------------------------------------------------------------------------
# Ordre de livraison : devis avant ou après le chantier, même mesure
# ---------------------------------------------------------------------------
def test_le_devis_avant_le_wct_donne_le_temps_prevu_et_la_marge_prevue(base_durable, departements):
    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _livrer(departements)

    mesures = _par_metrique(_mesures())
    assert mesures["m8_ecart_duree_minutes"]["valeur"] == "60.00"  # 120 - 60
    assert mesures["m8_ecart_duree_pct"]["valeur"] == "100.00"
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"  # 600 - 480
    assert mesures["m8_marge_reelle_cad"]["statut"] == "non_calculable"  # M5 ne rapporte pas encore
    assert mesures["m8_marge_reelle_cad"]["manque"][0]["source"] == "M5 (rentabilité du chantier)"


def test_le_devis_apres_le_wct_remesure_le_chantier_deja_termine(base_durable, departements):
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _livrer(departements)
    avant = _par_metrique(_mesures())
    assert avant["m8_ecart_duree_pct"]["statut"] == "non_calculable"

    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _livrer(departements, "2026-09-28T18:05:00+00:00")

    apres = _par_metrique(_mesures())
    assert apres["m8_ecart_duree_pct"]["valeur"] == "100.00"
    assert apres["m8_marge_prevue_cad"]["valeur"] == "120.00"


def test_un_devis_sans_duree_estimee_laisse_le_temps_prevu_non_calculable_mais_donne_la_marge(
        base_durable, departements):
    devis = _devis()
    del devis["duree_estimee_minutes"]
    _publier("m3.devis_accepte", "m03-estimation", devis)
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _livrer(departements)

    mesures = _par_metrique(_mesures())
    assert mesures["m8_ecart_duree_pct"]["statut"] == "non_calculable"
    assert mesures["m8_ecart_duree_pct"]["manque"][0]["champ"] == "duree_estimee_minutes"
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"


def test_un_wct_sans_devis_id_n_est_lie_a_aucun_devis(base_durable, departements):
    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _publier("m4.travaux_termines", "m04-field-ops", _wct(devis_id=None))
    _livrer(departements)

    mesure = _par_metrique(_mesures())["m8_ecart_duree_pct"]
    assert mesure["statut"] == "non_calculable"
    assert "aucun devis" in mesure["manque"][0]["raison"]


# ---------------------------------------------------------------------------
# Variance de matériaux (M6) : le verdict de M6, repris
# ---------------------------------------------------------------------------
def test_la_variance_evaluee_de_m6_donne_le_plus_grand_ecart_sans_recalcul(base_durable, departements):
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _publier("m6.variance_chantier", "m06-material-control", _variance())
    _livrer(departements)

    mesure = _par_metrique(_mesures())["m8_ecart_materiaux_max_pct"]
    assert mesure["valeur"] == "40.00"
    assert mesure["entrees"]["materiau"] == "gouttiere-fictif"
    assert mesure["entrees"]["signal_critique_m6"] is True


def test_la_variance_en_attente_puis_evaluee_la_mesure_suit_le_statut(base_durable, departements):
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _publier("m6.variance_chantier", "m06-material-control", _variance(statut="declaration_absente"))
    _livrer(departements)
    en_attente = _par_metrique(_mesures())["m8_ecart_materiaux_max_pct"]
    assert en_attente["statut"] == "non_calculable"
    assert "declaration_absente" in en_attente["manque"][0]["raison"]

    _publier("m6.variance_chantier", "m06-material-control", _variance())
    _livrer(departements, "2026-09-28T18:05:00+00:00")
    assert _par_metrique(_mesures())["m8_ecart_materiaux_max_pct"]["valeur"] == "40.00"
    assert [f["statut_variance"] for f in _faits() if f["type_entree"] == "variance"] == [
        "declaration_absente", "evaluee",
    ]


def test_une_variance_qui_precede_son_wct_est_gardee_puis_reprise_a_l_arrivee_du_wct(base_durable, departements):
    _publier("m6.variance_chantier", "m06-material-control", _variance())
    _livrer(departements)
    assert [f["type_entree"] for f in _faits()] == ["variance"]  # rien n'est perdu ni inventé

    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _livrer(departements, "2026-09-28T18:05:00+00:00")
    assert _par_metrique(_mesures())["m8_ecart_materiaux_max_pct"]["valeur"] == "40.00"


def test_lire_les_mesures_d_un_chantier_inconnu_dit_qu_il_est_inconnu(base_durable):
    par_nom = {o.nom: o for o in m8_outils.outils()}
    reponse = executer_atomique(par_nom["m8_lire_mesures_chantier"], {"wct_id": "wct-inconnu"})
    assert reponse["resultat"] == {
        "wct_id": "wct-inconnu", "trouve": False, "verdict": "REJ-CHANTIER-INCONNU:wct-inconnu",
    }


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------
def test_une_relivraison_n_ajoute_ni_fait_ni_alerte(base_durable, departements, configurer):
    configurer({
        "m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50},
        "m8_ecart_materiaux_max_pct": {"sens": "au_dessus", "valeur": 100},  # 40 % : non franchi
    })
    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _publier("m4.travaux_termines", "m04-field-ops", _wct(), evenement_id="evt-wct-1")
    _livrer(departements)
    faits, alertes = _faits(), _alertes()
    assert len(faits) == 2 and len(alertes) == 1

    # Même fait, autre evenement_id : idempotence du CONSOMMATEUR (celle de l'outbox est déjà acquise).
    _publier("m4.travaux_termines", "m04-field-ops", _wct(), evenement_id="evt-wct-2")
    _publier("m3.devis_accepte", "m03-estimation", _devis(), evenement_id="evt-devis-2")
    _publier("m6.variance_chantier", "m06-material-control", _variance(), evenement_id="evt-var-1")
    _publier("m6.variance_chantier", "m06-material-control", _variance(), evenement_id="evt-var-2")
    resume = _livrer(departements, "2026-09-28T18:05:00+00:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0

    assert len(_faits()) == 3  # + la seule variance, une fois
    assert len(_alertes()) == 1  # le même franchissement de seuil n'est jamais republié
    assert _livrer(departements, "2026-09-28T18:10:00+00:00")["livres"] == 0


# ---------------------------------------------------------------------------
# Seuils : configuré = alerte, absent = pas d'alerte et « seuil à configurer »
# ---------------------------------------------------------------------------
def test_un_seuil_franchi_publie_une_alerte_pour_m9_conforme_au_catalogue(base_durable, departements, configurer):
    configurer({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}})
    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume = _livrer(departements)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0  # la charge a passé le schéma du catalogue

    franchis = [a for a in _alertes() if a["type_alerte"] == "MESURE-SEUIL-FRANCHI"]
    assert len(franchis) == 1
    alerte = franchis[0]
    assert alerte["metric_id"] == "m8_ecart_duree_pct"
    assert alerte["a_qui"] == "m04-field-ops"
    assert alerte["horodatage_reference"] == "2026-09-28T14:00:00-04:00"
    assert alerte["preuve"]["valeur"] == "100.00" and alerte["preuve"]["seuil"] == "50.00"
    assert alerte["preuve"]["wct_id"] == "wct-m8-1" and alerte["preuve"]["sens"] == "au_dessus"
    assert "wct-m8-1" in alerte["action_proposee"]


def test_le_devis_qui_arrive_apres_le_wct_declenche_l_alerte_a_ce_moment(base_durable, departements, configurer):
    configurer({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}})
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _livrer(departements)
    assert [a for a in _alertes() if a["type_alerte"] == "MESURE-SEUIL-FRANCHI"] == []

    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _livrer(departements, "2026-09-28T18:05:00+00:00")
    assert len([a for a in _alertes() if a["type_alerte"] == "MESURE-SEUIL-FRANCHI"]) == 1


def test_un_seuil_non_franchi_ne_publie_aucune_alerte(base_durable, departements, configurer):
    configurer({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 150}})
    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _livrer(departements)

    types = {a["type_alerte"] for a in _alertes()}
    assert "MESURE-SEUIL-FRANCHI" not in types
    assert "m8_ecart_duree_pct" not in {a["metric_id"] for a in _alertes()}  # configuré : pas même un rappel


def test_sans_seuil_configure_pas_d_alerte_de_franchissement_mais_un_rappel_seuil_a_configurer(
        base_durable, departements):
    """Le vrai `department.yaml` de M8 ne fixe aucun seuil : c'est l'état de livraison."""
    assert m8_outils._seuils_alerte() == {}

    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _livrer(departements)

    alertes = _alertes()
    assert {a["type_alerte"] for a in alertes} == {"MESURE-SEUIL-A-CONFIGURER"}
    assert [a["metric_id"] for a in alertes] == ["m8_ecart_duree_pct"]  # la seule mesure surveillée calculée
    assert alertes[0]["preuve"] == {"metric_id": "m8_ecart_duree_pct", "manque": "seuil"}
    assert _mesures()["seuils_a_configurer"] == ["m8_ecart_duree_pct"]


def test_le_rappel_seuil_a_configurer_n_est_emis_qu_une_fois_par_metrique_et_par_jour(base_durable, departements):
    _publier("m3.devis_accepte", "m03-estimation", _devis())
    for numero in (1, 2, 3):
        _publier("m4.travaux_termines", "m04-field-ops", _wct(
            wct_id=f"wct-m8-{numero}", horodatage_completion=f"2026-09-28T1{numero}:00:00-04:00"))
    _livrer(departements)
    assert len(_alertes()) == 1  # trois chantiers le même jour, un seul rappel

    _publier("m4.travaux_termines", "m04-field-ops", _wct(
        wct_id="wct-m8-4", horodatage_completion="2026-09-29T11:00:00-04:00"))
    _livrer(departements, "2026-09-29T18:00:00+00:00")
    assert len(_alertes()) == 2  # le lendemain, le rappel revient


def test_un_seuil_invalide_est_signale_pas_devine(base_durable, departements, configurer):
    configurer({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": "beaucoup"}})
    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _livrer(departements)

    alertes = _alertes()
    assert [a["type_alerte"] for a in alertes] == ["MESURE-SEUIL-A-CONFIGURER"]
    assert alertes[0]["preuve"]["manque"] == "seuil_invalide"


def test_les_trois_metriques_surveillees_alertent_chacune_vers_le_departement_du_processus(
        base_durable, departements, configurer):
    configurer({
        "m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50},
        "m8_ecart_materiaux_max_pct": {"sens": "au_dessus", "valeur": 30},
    })
    _publier("m3.devis_accepte", "m03-estimation", _devis())
    _publier("m4.travaux_termines", "m04-field-ops", _wct())
    _publier("m6.variance_chantier", "m06-material-control", _variance())
    _livrer(departements)

    franchis = {a["metric_id"]: a for a in _alertes() if a["type_alerte"] == "MESURE-SEUIL-FRANCHI"}
    assert set(franchis) == {"m8_ecart_duree_pct", "m8_ecart_materiaux_max_pct"}
    assert franchis["m8_ecart_materiaux_max_pct"]["a_qui"] == "m06-material-control"
    assert franchis["m8_ecart_materiaux_max_pct"]["preuve"]["valeur"] == "40.00"


# ---------------------------------------------------------------------------
# Catalogue : la durée estimée est optionnelle et bien formée
# ---------------------------------------------------------------------------
def test_le_catalogue_accepte_le_devis_avec_ou_sans_duree_estimee_et_refuse_une_duree_mal_formee(base_durable):
    sans = _devis(devis_id="devis-sans")
    del sans["duree_estimee_minutes"]
    _publier("m3.devis_accepte", "m03-estimation", sans)
    _publier("m3.devis_accepte", "m03-estimation", _devis(devis_id="devis-avec", duree_estimee_minutes="487.5"))
    with pytest.raises(evenements.ChargeInvalide):
        _publier("m3.devis_accepte", "m03-estimation", _devis(devis_id="devis-mal", duree_estimee_minutes="-5"))
    with pytest.raises(evenements.ChargeInvalide):
        _publier("m3.devis_accepte", "m03-estimation", _devis(devis_id="devis-texte", duree_estimee_minutes="1h30"))


def test_le_catalogue_refuse_une_alerte_de_mesure_dont_la_preuve_est_incomplete(base_durable):
    charge = {
        "evenement_id": "m8-alerte-test", "metric_id": "m8_ecart_duree_pct", "type_alerte": "MESURE-SEUIL-FRANCHI",
        "quoi": "q", "a_qui": "m04-field-ops", "pourquoi": "p", "source": "s",
        "horodatage_reference": "2026-09-28T14:00:00-04:00",
        "preuve": {"metric_id": "m8_ecart_duree_pct", "valeur": "1.00"},  # ni wct_id, ni seuil, ni sens
    }
    with pytest.raises(evenements.ChargeInvalide):
        _publier("m8.alerte_proposee", "m08-analytics", charge, evenement_id="m8-alerte-test")
