"""Mesures du chantier, performance d'équipe et vue exécutive sur le même état de faits reçus.

Par le vrai bus (manifeste M8 réel, catalogue réel, SQLite migrée), un chantier fictif reçoit son devis
(M3), son WCT (M4), une variance terminale (M6) puis la rentabilité M5 : séquence 1 calculée, séquence 2
partielle plus récente, puis une trace ancienne relivrée, une variance non terminale tardive et un rejeu.
Les trois lectures doivent rester d'accord, sans ressusciter une marge, ni zéro, ni écriture : l'instantané
de TOUTES les tables du schéma est comparé avant/après CHAQUE lecture. Le cash libre (CF033) n'est pas
repris ici ; l'évaluateur de qualité (N2, publie) n'est pas une lecture et reste hors de ce fichier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import contexte, evenements, identite, stockage
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import META

FICTIF = True
_DEP = "m08-analytics"
_ADMIN = IdentiteAppelante("admin.fictif", "admin")
_TECH = "tech-vues-fictif"
_CODES_M5 = ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER"]


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
    yield url
    stockage.liberer()


@pytest.fixture
def departements():
    return {_DEP: charger_departements(Path(__file__).resolve().parents[2])[_DEP]}


def _wct():
    return {
        "wct_id": "wct-vues-fictif", "intervention_id": "int-vues-fictif", "lead_id": "lead-vues-fictif",
        "technicien_id": _TECH, "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5}, "duree_reelle_minutes": 120,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "c" * 64, "consommateurs_cibles": ["M8"],
        "devis_id": "devis-vues-fictif", "statut": "completed_verified",
    }


def _devis():
    return {
        "devis_id": "devis-vues-fictif", "lead_id": "lead-vues-fictif", "chantier_id": None,
        "lignes": [{
            "reference_ligne": "devis-vues-fictif-L0", "description": "Gouttières (fictif)", "quantite": "40",
            "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00", "reference_besoin_materiau": None,
        }],
        "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
        "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
    }


def _variance(statut):
    evaluee = statut == "evaluee"
    return {
        "evenement_id": f"m6-variance-vues-fictif-{statut}", "wct_id": "wct-vues-fictif",
        "intervention_id": "int-vues-fictif", "chantier_id": "ch-vues-fictif", "statut_variance": statut,
        "signal_critique": True if evaluee else None, "seuil_pourcentage": 0.3,
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "lignes": [
            {"materiau": "gouttiere-fictif", "unite": "pi", "quantite_prevue": "40", "quantite_reelle": "56",
             "ecart_pourcentage": "0.4", "critique": True},
        ] if evaluee else None,
    }


def _m5(sequence, verdict):
    complete = verdict == "CALCULEE"
    return {
        "evenement_id": f"m5-rentabilite-vues-fictif-{sequence}", "devis_id": "devis-vues-fictif",
        "chantier_id": "ch-vues-fictif", "wct_id": "wct-vues-fictif", "sequence": sequence,
        "version_entrees": f"{sequence:064x}", "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "verdict": verdict, "devise": "CAD", "prix_definitif": True, "cout_reel_complet": complete,
        "cout_reel_cad": "486.00" if complete else None, "cout_connu_cad": "486.00" if complete else "150.00",
        "marge_reelle_cad": "114.00" if complete else None, "marge_prevue_cad": "120.00",
        "ecart_marge_cad": "-6.00" if complete else None, "manque": [] if complete else list(_CODES_M5),
    }


def _publier(type_evenement, producteur, charge, evenement_id):
    evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)


def _livrer(departements, maintenant):
    resume = evenements.repartir(departements, maintenant=maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    return resume


def _instantane_meta():
    """Toutes les tables du schéma de l'instance, ligne à ligne."""
    with stockage.transaction() as cnx:
        return {
            table.name: sorted(repr(tuple(ligne)) for ligne in cnx.execute(select(table)).all())
            for table in META.sorted_tables
        }


def _lire_pur(outil, arguments, appelante=None):
    avant = _instantane_meta()
    if appelante is None:
        reponse = executer_atomique(outil, arguments)
    else:
        with contexte.appele_par_appareil(appelante):
            reponse = executer_atomique(outil, arguments)
    assert _instantane_meta() == avant, outil.nom
    return reponse


def _trois_vues(par_nom, aujourd_hui="2026-10-01"):
    mesures = _lire_pur(par_nom["m8_lire_mesures_chantier"], {"wct_id": "wct-vues-fictif"})
    equipe_agent = _lire_pur(par_nom["m8_performance_equipe"], {})
    equipe_admin = _lire_pur(par_nom["m8_performance_equipe"], {}, _ADMIN)
    vue = _lire_pur(par_nom["m8_lire_vue_executive"], {"aujourd_hui": aujourd_hui}, _ADMIN)
    for reponse in (mesures, equipe_agent, equipe_admin, vue):
        assert reponse["ok"] is True, reponse
    return {
        "mesures": {m["metric_id"]: m for m in mesures["resultat"]["mesures"]},
        "manques": mesures["resultat"]["manques"],
        "equipe_agent": equipe_agent["resultat"], "equipe_admin": equipe_admin["resultat"],
        "vue": vue["resultat"], "brut_vue": json.dumps(vue, ensure_ascii=False),
    }


def test_les_trois_vues_suivent_l_etat_courant_m5_sans_resurrection_ni_ecriture(base_durable, departements):
    par_nom = {o.nom: o for o in m8_outils.outils()}  # même instance d'outils pour toutes les lectures
    _publier("m3.devis_accepte", "m03-estimation", _devis(), "evt-devis-vues")
    _publier("m4.travaux_termines", "m04-field-ops", _wct(), "evt-wct-vues")
    _publier("m6.variance_chantier", "m06-material-control", _variance("evaluee"), "evt-var-vues-evaluee")
    _publier("m5.rentabilite_chantier", "m05-financecore", _m5(1, "CALCULEE"), "evt-m5-vues-1")
    _livrer(departements, "2026-09-28T18:00:00+00:00")

    calcule = _trois_vues(par_nom)
    marge = calcule["mesures"]["m8_marge_reelle_cad"]
    assert (marge["statut"], marge["valeur"]) == ("calculee", "114.00")
    assert calcule["mesures"]["m8_marge_prevue_cad"]["valeur"] == "120.00"
    assert calcule["mesures"]["m8_ecart_materiaux_max_pct"]["valeur"] == "40.00"
    (ligne,) = calcule["vue"]["marge_reelle"]["chantiers"]
    assert (ligne["statut"], ligne["marge_reelle_cad"], ligne["prix_definitif"]) == ("calculee", "114.00", True)
    assert '"marge_reelle_cad": "114.00"' in calcule["brut_vue"]  # le texte de M5, jamais un flottant
    assert calcule["equipe_agent"]["detail_nominatif"] == "reserve_admin"
    assert "techniciens" not in calcule["equipe_agent"] and _TECH not in json.dumps(calcule["equipe_agent"])
    assert [t["technicien_id"] for t in calcule["equipe_admin"]["techniciens"]] == [_TECH]

    stockage.liberer()  # réouverture : la séquence 2, partielle et plus récente, devient l'état courant
    _publier("m5.rentabilite_chantier", "m05-financecore", _m5(2, "PARTIELLE"), "evt-m5-vues-2")
    _livrer(departements, "2026-09-28T18:05:00+00:00")
    partiel = _trois_vues(par_nom)
    raison = "M5 n'a pas chiffré la marge réelle : " + ", ".join(_CODES_M5)
    for metric_id in ("m8_marge_reelle_cad", "m8_ecart_marge_cad", "m8_ecart_marge_pct"):
        mesure = partiel["mesures"][metric_id]
        assert (mesure["statut"], mesure["valeur"], mesure["manque"]) == ("non_calculable", None,
                                                                          ["marge_reelle_cad"]), metric_id
    assert [m["raison"] for m in partiel["manques"] if m["champ"] == "marge_reelle_cad"] == [raison]
    assert partiel["mesures"]["m8_marge_prevue_cad"] == calcule["mesures"]["m8_marge_prevue_cad"]
    assert partiel["mesures"]["m8_ecart_materiaux_max_pct"] == calcule["mesures"]["m8_ecart_materiaux_max_pct"]
    (ligne,) = partiel["vue"]["marge_reelle"]["chantiers"]
    assert (ligne["statut"], ligne["marge_reelle_cad"], ligne["raison"]) == ("non_calculable", None, raison)
    assert partiel["vue"]["marge_reelle"]["n_marge_connue"] == 0 and "114.00" not in partiel["brut_vue"]
    # La durée M3/M4 de l'équipe ne dépend pas de M5 : identique avant et après.
    assert (partiel["equipe_agent"], partiel["equipe_admin"]) == (calcule["equipe_agent"], calcule["equipe_admin"])

    stockage.liberer()  # trace M5 ancienne relivrée, variance non terminale tardive, rejeu des mêmes événements
    _publier("m5.rentabilite_chantier", "m05-financecore", _m5(1, "CALCULEE"), "evt-m5-vues-1-reessai")
    _publier("m6.variance_chantier", "m06-material-control", _variance("declaration_absente"), "evt-var-vues-tard")
    _publier("m5.rentabilite_chantier", "m05-financecore", _m5(2, "PARTIELLE"), "evt-m5-vues-2")
    _publier("m4.travaux_termines", "m04-field-ops", _wct(), "evt-wct-vues")
    _livrer(departements, "2026-09-28T18:10:00+00:00")
    assert _livrer(departements, "2026-09-28T18:15:00+00:00")["livres"] == 0
    tardif = _trois_vues(par_nom)
    assert (tardif["mesures"], tardif["manques"]) == (partiel["mesures"], partiel["manques"])
    assert (tardif["equipe_agent"], tardif["equipe_admin"]) == (partiel["equipe_agent"], partiel["equipe_admin"])
    assert tardif["vue"]["marge_reelle"] == partiel["vue"]["marge_reelle"]
    faits = list(stockage.maillons(_DEP, "faits_chantier"))
    assert sorted(repr((f["type_entree"], f.get("sequence"), f.get("statut_variance"))) for f in faits) == sorted(
        repr(fait) for fait in [
            ("devis", None, None), ("wct", None, None), ("variance", None, "evaluee"), ("rentabilite", 1, None),
            ("rentabilite", 2, None), ("variance", None, "declaration_absente"),
        ])  # une fois chacun : ni la trace relivrée ni le rejeu n'ajoutent un fait

    # La date ne change que ce qui en dépend : sans date ou à une autre date, la marge reste celle de M5.
    sans_date = _lire_pur(par_nom["m8_lire_vue_executive"], {}, _ADMIN)
    autre_date = _lire_pur(par_nom["m8_lire_vue_executive"], {"aujourd_hui": "2026-12-31"}, _ADMIN)
    assert sans_date["ok"] is True and autre_date["ok"] is True
    for reponse in (sans_date, autre_date):
        assert reponse["resultat"]["marge_reelle"] == tardif["vue"]["marge_reelle"]
        assert reponse["resultat"]["entonnoir"] == tardif["vue"]["entonnoir"]
    illisible = _lire_pur(par_nom["m8_lire_vue_executive"], {"aujourd_hui": "01/10/2026"}, _ADMIN)
    assert illisible["ok"] is False and illisible["erreur"] == "refus_metier"
    assert illisible["details"].startswith("REJ-VUE-AUJOURD-HUI-INVALIDE") and "resultat" not in illisible
