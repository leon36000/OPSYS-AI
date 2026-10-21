"""M8 mesure, M9 lit — par le bus réel (PLAN T1.5-d) : M8 et M9 seuls, événements du catalogue
publiés à la main (WCT de M4, devis de M3), base SQLite migrée, vrais manifestes.

Le trajet complet avec les vrais M2, M3, M4 et M6 est dans `tests/test_cascade_mesure_m8_m9.py` du
socle. Ici, la frontière M8 → M9 : l'alerte de mesure franchie arrive au registre de M9, la lecture
stratégique la cite sans décider, le briefing du matin la montre (fenêtre de jours), et le rappel
« seuil à configurer » devient un manque.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from m8_analytics import outils as m8_outils
from m9_strategic_intelligence.outils import outils as m9_outils

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_MATIN = "2026-09-28T07:00:00-04:00"  # le chantier ci-dessous est fini la veille, à 15 h


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements():
    tous = charger_departements(_RACINE_DEPARTEMENTS)
    return {"m08-analytics": tous["m08-analytics"], "m09-strategic-intelligence": tous["m09-strategic-intelligence"]}


@pytest.fixture
def seuils(tmp_path, monkeypatch):
    def poser(seuils_alerte):
        manifeste = tmp_path / "department-m8.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": {"seuils_alerte": seuils_alerte}}), encoding="utf-8")
        monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)
    return poser


def _wct(**surcharges):
    base = {
        "wct_id": "wct-m8m9-1", "intervention_id": "int-1", "lead_id": "lead-1", "technicien_id": "tech-fictif-a",
        "horodatage_completion": "2026-09-27T15:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None, "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M8"], "devis_id": "devis-m8m9-1", "statut": "completed_verified",
    }
    base.update(surcharges)
    return base


def _devis():
    return {
        "devis_id": "devis-m8m9-1", "lead_id": "lead-1", "chantier_id": None,
        "lignes": [{
            "reference_ligne": "devis-m8m9-1-L0", "description": "Gouttières (fictif)", "quantite": "40",
            "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00", "reference_besoin_materiau": None,
        }],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25", "duree_estimee_minutes": "60",
        "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
    }


def _terminer_le_chantier(departements):
    """M3 accepte le devis, M4 termine le chantier ; le bus livre à M8, qui publie son alerte, que le
    tour suivant livre à M9 (les événements publiés pendant un tour sont livrés au tour d'après)."""
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    tours = [evenements.repartir(departements, maintenant="2026-09-27T20:00:00+00:00") for _ in range(2)]
    assert all(t["echecs"] == 0 and t["quarantaines"] == 0 for t in tours), tours
    return tours


def _par_nom_m9():
    return {o.nom: o for o in m9_outils()}


def _appeler(nom, arguments):
    reponse = executer_atomique(_par_nom_m9()[nom], arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _alertes_m9():
    return list(stockage.maillons("m09-strategic-intelligence", "alertes_m8"))


# ---------------------------------------------------------------------------
# Déclaration des deux nouveaux outils
# ---------------------------------------------------------------------------
def test_les_outils_de_lecture_sont_t0_et_reserves_a_l_admin():
    par_nom = _par_nom_m9()
    for nom in ("m9_lire_suite_briefing", "m9_produire_lecture_strategique"):
        assert par_nom[nom].autonomie == Autonomie.T0  # lecture pure : rien n'est décidé ni écrit
        assert par_nom[nom].roles_appareil == frozenset({"admin"})
        assert par_nom[nom].frontiere_humaine is False


# ---------------------------------------------------------------------------
# M8 mesure, M9 lit
# ---------------------------------------------------------------------------
def test_l_alerte_de_mesure_de_m8_arrive_au_registre_de_m9_avec_ses_preuves(base_durable, departements, seuils):
    seuils({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}})

    _terminer_le_chantier(departements)

    [alerte] = _alertes_m9()
    assert alerte["type_alerte"] == "MESURE-SEUIL-FRANCHI" and alerte["metric_id"] == "m8_ecart_duree_pct"
    assert alerte["preuve"]["valeur"] == "100.00" and alerte["preuve"]["wct_id"] == "wct-m8m9-1"
    assert alerte["a_qui"] == "m04-field-ops"


def test_la_lecture_strategique_cite_les_preuves_de_m8_et_ne_decide_pas(base_durable, departements, seuils):
    seuils({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}})
    _terminer_le_chantier(departements)

    lecture = _appeler("m9_produire_lecture_strategique", {"maintenant": _MATIN})

    assert lecture["preuves_m8"] == ["m8_ecart_duree_pct"]
    [item] = lecture["lectures"]
    assert item["metric_id"] == "m8_ecart_duree_pct" and item["chantier"] == "wct-m8m9-1"
    assert (item["valeur"], item["seuil"], item["sens"]) == ("100.00", "50.00", "au_dessus")
    assert item["evenement_id"].startswith("m8-alerte-m8_ecart_duree_pct-MESURE-SEUIL-FRANCHI-")
    assert item["action_proposee_par_m8"].startswith("Revoir le chantier wct-m8m9-1 avec m04-field-ops")
    assert lecture["decision"] == {"prise_par_m9": False, "a_prendre_par": "nathan_owner", "requise": True}
    assert lecture["manques"]["seuils_a_configurer"] == []


def test_le_briefing_du_matin_montre_l_alerte_du_chantier_fini_la_veille(base_durable, departements, seuils):
    """L'alerte porte l'instant du chantier (hier 15 h) : sans la fenêtre de jours du briefing, elle
    n'aurait jamais paru le lendemain à 7 h."""
    seuils({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}})
    _terminer_le_chantier(departements)

    briefing = _appeler("m9_produire_briefing_matin", {"maintenant": _MATIN})

    [alerte] = briefing["sections"]["alertes_m8"]["items"]
    assert alerte["metric_id"] == "m8_ecart_duree_pct"
    assert alerte["horodatage_reference"] == "2026-09-27T15:00:00-04:00"
    assert briefing["sections"]["alertes_m8"]["vide"] is False


def test_sans_seuil_configure_m9_lit_un_manque_pas_une_alerte(base_durable, departements):
    """Le vrai `department.yaml` de M8 ne fixe aucun seuil : M8 n'alerte pas, il rappelle qu'il en faut un."""
    _terminer_le_chantier(departements)

    lecture = _appeler("m9_produire_lecture_strategique", {"maintenant": _MATIN})
    assert lecture["lectures"] == [] and lecture["preuves_m8"] == []
    assert lecture["decision"]["requise"] is False
    assert lecture["manques"]["seuils_a_configurer"] == ["m8_ecart_duree_pct"]

    briefing = _appeler("m9_produire_briefing_matin", {"maintenant": _MATIN})
    assert briefing["sections"]["alertes_m8"] == {"items": [], "vide": True}
    manques = briefing["sections"]["manques_pour_conclure"]["items"]
    [seuil] = [m for m in manques if "seuil à configurer" in m["constat"]]
    assert "m8_ecart_duree_pct" in seuil["constat"]


def test_un_seuil_non_franchi_ne_donne_rien_a_lire(base_durable, departements, seuils):
    seuils({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 150}})
    _terminer_le_chantier(departements)

    lecture = _appeler("m9_produire_lecture_strategique", {"maintenant": _MATIN})
    assert lecture["lectures"] == [] and lecture["manques"]["seuils_a_configurer"] == []
    assert _alertes_m9() == []


def test_la_lecture_reste_bornee_et_se_lit_par_pages_avec_beaucoup_de_chantiers(base_durable, departements, seuils):
    seuils({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}})
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis())
    for numero in range(40):
        evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(wct_id=f"wct-m8m9-{numero}"))
    for _ in range(2):
        evenements.repartir(departements, maintenant="2026-09-27T20:00:00+00:00", limite=500)
    assert len(_alertes_m9()) == 40

    vus, depart, pages = [], 0, 0
    while depart is not None:
        page = _appeler("m9_produire_lecture_strategique", {"maintenant": _MATIN, "depart": depart})
        vus.extend(i["chantier"] for i in page["lectures"])
        depart = page["affichage"]["prochain_depart"]
        pages += 1
        assert pages < 50
    assert sorted(vus) == sorted(f"wct-m8m9-{n}" for n in range(40))  # les 40 chantiers, une fois chacun
    assert pages > 1
