"""PLAN T1.5-d — « travaux terminés » jusqu'à la lecture de M9 (DEFINITION-PRODUIT §6 : « M8 : temps
réel vs prévu, marge prévue vs réelle ; M9 : lecture stratégique via les preuves de M8 »), par le VRAI
bus, sur les VRAIS départements, sans doublure.

M4 termine un chantier (vrais outils : planification, pointage, complétion) → M6 évalue la variance
de matériaux → le bus livre le WCT, le devis accepté (M3) et la variance à M8, qui mesure le chantier
avec ses métriques gouvernées et publie ses alertes → M9 les reçoit, les lit et les cite dans son
briefing et sa lecture stratégique, sans rien décider.

Deux scénarios, chacun sur une base SQLite temporaire migrée :

1. écart de matériaux de 40 % (seuil de M8 configuré à 30 %) : alerte de mesure, lue par M9 ;
2. devis accepté APRÈS la complétion, aucun seuil configuré (l'état de livraison) : M8 remesure à
   l'arrivée du devis, n'alerte pas, dit « seuil à configurer », et M9 en fait un manque.

Ce que M3 ne fournit pas encore reste « non calculable, manque X » : la durée estimée du devis (M3 ne
la publie pas) et la marge réelle (M5 ne la rapporte pas) — jamais une valeur inventée.

Fichier NOUVEAU : le patron des helpers est celui de `test_cascade_travaux_termines.py`, recopié pour
ne pas dépendre d'un fichier que d'autres agents modifient. Identifiants, personnes et montants fictifs.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import struct
import zlib

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
import yaml
from m2_revenue_crm import statuts as m2_statuts
from m4_field_ops import cedule
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

DT_TZ = dt.timezone(dt.timedelta(hours=-4))  # Québec, heure avancée
VILLE = "Repentigny"
MATERIAU_ID = "gouttiere-alu-5po-fictif"
SEL = "sel-t15d-fictif"
FIX_GPS = {"latitude": 45.7392, "longitude": -73.4536}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T15D-FICTIF"}
TECHNICIEN = "TECH-T15D-fictif"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-t15d.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        m2_outils.reinitialiser_registre()
        stockage.liberer()


@pytest.fixture
def seuils_m8(tmp_path, monkeypatch):
    """Pose les seuils de M8 dans un `department.yaml` temporaire (le vrai n'en fixe aucun)."""
    def poser(seuils_alerte):
        manifeste = tmp_path / "department-m8.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": {"seuils_alerte": seuils_alerte}}), encoding="utf-8")
        monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)
    return poser


# -------------------------------------------------------------------------------------------
# Petits outils de test
# -------------------------------------------------------------------------------------------
def _iso(base: dt.datetime, offset_s: int) -> str:
    return (base + dt.timedelta(seconds=offset_s)).isoformat()


def _outils(deps, dep_id):
    return {o.nom: o for o in deps[dep_id].charger_outils()}


def _contrat(lead_id: str) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100", "courriel": f"{lead_id}@exemple-fictif.test"},
        "type_travaux": "renovation_totale", "ville": VILLE, "urgence_declaree": False, "canal": "telephone",
    }


def _fenetre(base: dt.datetime) -> dict:
    return {"debut": _iso(base, 0), "fin": _iso(base, 12 * 3600)}


def _drainer(deps, base: dt.datetime, *, max_tours: int = 15, pas_s: int = 90) -> dict:
    """Draine le bus jusqu'à quiescence (`evenements.repartir` sur TOUS les départements), boucle bornée :
    l'alerte que M8 publie en consommant le WCT n'est livrée à M9 qu'au tour suivant."""
    t = base
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for _ in range(max_tours):
        resume = evenements.repartir(deps, maintenant=_iso(t, 0))
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
        t = t + dt.timedelta(seconds=pas_s)
    raise AssertionError(f"le bus n'a pas atteint la quiescence après {max_tours} tours : {total}")


def _recu(evenement_id: str, consommateur: str) -> dict | None:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.evenement_id == evenement_id, EVENEMENTS_RECUS.c.consommateur == consommateur,
        )).mappings().first()
    return dict(ligne) if ligne else None


def _alertes_publiees() -> list[dict]:
    """Charges des `m8.alerte_proposee` publiées par M8, dans l'ordre de publication."""
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m8.alerte_proposee")
            .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)
        ).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


# -------------------------------------------------------------------------------------------
# Étapes de la chaîne — chacune un VRAI appel d'outil (`executer_atomique`), comme en production
# -------------------------------------------------------------------------------------------
def _m2_amener_pret_pour_readiness(m2, lead_id: str, base: dt.datetime) -> dict:
    r = executer_atomique(m2["m2_ingerer_lead"], {"contrat": _contrat(lead_id), "horodatage": _iso(base, 0)})
    assert r["ok"] and r["resultat"]["accepte"], r
    r = executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": _iso(base, 60),
        "owner": "Alice Vendeuse (fictif)",
        "prochaine_action": {"description": "Planifier la visite technique (fictif)", "echeance": _iso(base, 3600)},
    })
    assert r["ok"] and r["resultat"]["accepte"], r
    r = executer_atomique(m2["m2_enregistrer_interaction"], {
        "lead_id": lead_id, "auteur": "Alice Vendeuse (fictif)",
        "resume": "Appel de qualification effectué (fictif).", "horodatage": _iso(base, 120),
    })
    assert r["ok"] and r["resultat"]["accepte"], r
    r = executer_atomique(m2["m2_evaluer_readiness"], {"lead_id": lead_id, "horodatage": _iso(base, 180)})
    assert r["ok"] and r["resultat"]["accepte"], r
    return r["resultat"]["resultat"]


def _m3_creer_devis(m3, devis_id: str, lead_id: str, chantier_id: str, base: dt.datetime) -> None:
    """Devis fictif : 40 pi de gouttière (8.00 $/pi) + main d'oeuvre forfaitaire (160.00 $), marge 25 % :
    coût total 480.00 $, prix total 600.00 $, donc marge prévue 120.00 $."""
    lignes = [
        {"description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi",
         "cout_unitaire": "8.00", "reference_besoin_materiau": MATERIAU_ID},
        {"description": "Main d'oeuvre installation (fictif)", "quantite": "1", "unite": "forfait",
         "cout_unitaire": "160.00", "reference_besoin_materiau": None},
    ]
    r = executer_atomique(m3["m3_creer_devis"], {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": chantier_id, "lignes": lignes,
        "taux_marge": "0.25", "horodatage": _iso(base, 200), "prix_total": "600.00",
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _m3_accepter_devis(m3, devis_id: str, base: dt.datetime, offset: int = 600) -> None:
    # T3 (frontière humaine) : appelé directement ; la décision humaine est prouvée ailleurs.
    r = executer_atomique(m3["m3_marquer_devis_accepte"], {
        "devis_id": devis_id, "approbateur": "Nathan Proprietaire (fictif, T3)", "horodatage": _iso(base, offset),
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _m2_transitionner(m2, lead_id: str, statut_cible: str, base: dt.datetime, offset: int, **kw) -> None:
    r = executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": statut_cible, "horodatage": _iso(base, offset), **kw,
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _m4_planifier_router_pointer(m4, contrat: dict, marqueur: dict, devis_id: str, base: dt.datetime) -> str:
    plan = executer_atomique(m4["m4_planifier_intervention"], {
        "contrat": contrat, "marqueur": marqueur, "horodatage": _iso(base, 900), "sel": SEL,
        "techniciens_disponibles": [TECHNICIEN], "fenetres_disponibles": [_fenetre(base)], "devis_id": devis_id,
    })
    assert plan["ok"] and plan["resultat"]["accepte"], plan
    intervention_id = plan["resultat"]["intervention_id"]
    consentement = executer_atomique(m4["m4_definir_consentement_gps"], {
        "technicien_id": TECHNICIEN, "action": "donne", "horodatage": _iso(base, 0),
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": "consentement-test"},
    })
    assert consentement["ok"] and consentement["resultat"]["accepte"], consentement
    depart = executer_atomique(m4["m4_demarrer_route"], {
        "intervention_id": intervention_id, "technicien_id": TECHNICIEN, "horodatage": _iso(base, 1800),
    })
    assert depart["ok"] and depart["resultat"]["accepte"], depart
    token = cedule.tokeniser_ville(SEL, VILLE)
    referentiel = {token: {"latitude": FIX_GPS["latitude"], "longitude": FIX_GPS["longitude"], "rayon_km": 25.0}}
    for action, offset in (("arrivee", 3600), ("depart", 10800)):
        r = executer_atomique(m4["m4_pointer"], {
            "intervention_id": intervention_id, "technicien_id": TECHNICIEN, "action": action,
            "horodatage": _iso(base, offset), "fix_gps": FIX_GPS, "attestation": ATTESTATION,
            "fenetre_travail": _fenetre(base), "referentiel_villes": referentiel, "ville": VILLE, "sel": SEL,
        })
        assert r["ok"] and r["resultat"]["accepte"], r
    return intervention_id


def _m6_receptionner(m6, chantier_id: str, materiau_id: str, quantite: float, po_id: str, base: dt.datetime) -> None:
    r = executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {
            "po_id": po_id, "chantier_id": chantier_id,
            "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": quantite}],
            "horodatage": _iso(base, -3600),
        },
        "reception_po": {
            "po_id": po_id, "chantier_id": chantier_id,
            "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}],
            "horodatage": _iso(base, -1800),
        },
        "catalogue_materiaux": {
            "version": "v1-fictif", "unite_monetaire": "CAD",
            "postes": {materiau_id: {"cout_unitaire": 8.0, "libelle": "Gouttière 5po alu (fictif)"}},
        },
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _png_minimal() -> bytes:
    def chunk(tag: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + tag + donnees + struct.pack(">I", zlib.crc32(tag + donnees))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff", 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _deposer_photo_test(m4) -> str:
    contenu = _png_minimal()
    r = executer_atomique(m4["m4_deposer_fichier"], {
        "empreinte_sha256": hashlib.sha256(contenu).hexdigest(), "taille_octets": len(contenu),
        "type_mime": "image/png", "index_bloc": 0, "nombre_blocs": 1,
        "bloc_base64": base64.b64encode(contenu).decode("ascii"),
    })
    assert r["ok"] and r["resultat"]["accepte"] and r["resultat"]["resultat"]["complet"], r
    return r["resultat"]["resultat"]["reference"]


def _m4_completer(m4, intervention_id: str, base: dt.datetime, offset: int = 11400) -> dict:
    preuves = {
        "checklist_complete": True, "photos_apres": [_deposer_photo_test(m4)],
        "notes": "Installation terminée sans incident (fictif).", "signature": None,
    }
    r = executer_atomique(m4["m4_completer_intervention"], {
        "intervention_id": intervention_id, "horodatage": _iso(base, offset), "preuves_completion": preuves,
    })
    assert r["ok"] and r["resultat"]["accepte"], r
    return r["resultat"]["resultat"]


def _m6_declarer(m6, wct_id: str, chantier_id: str, materiau_id: str, quantite_declaree: float) -> None:
    intervention_id = _charge_publiee("m4.travaux_termines", wct_id)["intervention_id"]
    r = executer_atomique(m6["m6_declarer_materiaux_utilises"], {
        "wct_id": wct_id,
        "formulaire": {
            "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": chantier_id,
            "lignes_materiaux": [{
                "type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite_declaree,
                "unite": "pi", "quantite_estimee": quantite_declaree,
            }],
        },
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _charge_publiee(type_evenement: str, evenement_id: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement,
            EVENEMENTS_SORTANTS.c.evenement_id == evenement_id,
        )).mappings().one()
    return codec.decoder(ligne["charge"])


def _mesures_de_m8(deps, wct_id: str) -> dict:
    reponse = executer_atomique(_outils(deps, "m08-analytics")["m8_lire_mesures_chantier"], {"wct_id": wct_id})
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["trouve"] is True
    return reponse["resultat"]


def _m9(deps, nom: str, **arguments) -> dict:
    reponse = executer_atomique(_outils(deps, "m09-strategic-intelligence")[nom], arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


# =============================================================================================
# 1. M4 termine (+40 % de matériaux) -> M8 mesure et alerte (seuil configuré) -> M9 lit et cite
# =============================================================================================
def test_m4_termine_m8_mesure_et_alerte_m9_lit_et_cite_les_preuves_sans_decider(base_durable, seuils_m8):
    seuils_m8({
        "m8_ecart_materiaux_max_pct": {"sens": "au_dessus", "valeur": 30},
        "m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50},
    })
    deps = charger_departements()
    m2, m3, m4, m6 = (_outils(deps, d) for d in
                       ("m02-revenue-crm", "m03-estimation", "m04-field-ops", "m06-material-control"))

    base = dt.datetime(2026, 9, 16, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-T15D-1-fictif", "DEVIS-T15D-1-fictif", "CH-T15D-1-fictif"
    marqueur = _m2_amener_pret_pour_readiness(m2, lead_id, base)
    _m3_creer_devis(m3, devis_id, lead_id, chantier_id, base)
    _m2_transitionner(m2, lead_id, "converti", base, 300, reference_devis_m3=devis_id)
    _m3_accepter_devis(m3, devis_id, base)
    _m2_transitionner(m2, lead_id, "cedule", base, 660)
    intervention_id = _m4_planifier_router_pointer(m4, _contrat(lead_id), marqueur, devis_id, base)
    _m2_transitionner(m2, lead_id, "chantier", base, 840)
    _m6_receptionner(m6, chantier_id, MATERIAU_ID, 200.0, f"PO-{devis_id}", base)
    wct_id = _m4_completer(m4, intervention_id, base)["wct_id"]
    _m6_declarer(m6, wct_id, chantier_id, MATERIAU_ID, 56.0)  # prévu 40 -> +40 %

    total = _drainer(deps, base + dt.timedelta(hours=1))
    assert total["echecs"] == 0 and total["quarantaines"] == 0, total

    # -- M8 : les trois faits reçus, jamais un coût par employé --------------------------------
    faits = list(stockage.maillons("m08-analytics", "faits_chantier"))
    assert sorted(f["type_entree"] for f in faits if f.get("wct_id") == wct_id or f.get("devis_id") == devis_id) == [
        "devis", "variance", "wct",
    ]
    assert next(f for f in faits if f["type_entree"] == "wct")["technicien_id"] == TECHNICIEN  # jamais dans une alerte
    for consommateur_evenement in (wct_id, f"m6-variance-{wct_id}-evaluee", f"m3-devis-accepte-{devis_id}"):
        recu = _recu(consommateur_evenement, "m08-analytics")
        assert recu is not None and recu["statut"] == "traite", (consommateur_evenement, recu)

    # -- M8 : les mesures — calculées par le code, ou « non calculable, manque X » --------------
    resultat = _mesures_de_m8(deps, wct_id)
    mesures = {m["metric_id"]: m for m in resultat["mesures"]}
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"  # 600.00 - 480.00, tels que M3 les a arrêtés
    assert mesures["m8_ecart_materiaux_max_pct"]["valeur"] == "40.00"  # le 0.4 de M6, jamais recalculé
    assert mesures["m8_ecart_materiaux_max_pct"]["entrees"]["signal_critique_m6"] is True
    assert mesures["m8_ecart_duree_pct"]["statut"] == "non_calculable"
    assert mesures["m8_ecart_duree_pct"]["manque"] == ["duree_estimee_minutes"]
    assert mesures["m8_ecart_duree_pct"]["valeur"] is None  # M3 ne publie pas encore la durée : rien d'inventé
    assert mesures["m8_marge_reelle_cad"]["manque"] == ["marge_reelle_cad"]
    sources = {m["champ"]: m["source"] for m in resultat["manques"]}
    assert sources["duree_estimee_minutes"].startswith("M3") and sources["marge_reelle_cad"].startswith("M5")
    assert resultat["seuils_a_configurer"] == []  # les deux seuils utiles sont configurés

    # -- M8 : UNE alerte, le franchissement du seuil de matériaux, avec sa preuve chiffrée -------
    alertes = _alertes_publiees()
    assert [(a["type_alerte"], a["metric_id"]) for a in alertes] == [
        ("MESURE-SEUIL-FRANCHI", "m8_ecart_materiaux_max_pct"),
    ]
    alerte = alertes[0]
    assert alerte["a_qui"] == "m06-material-control"
    assert alerte["preuve"]["wct_id"] == wct_id and alerte["preuve"]["valeur"] == "40.00"
    assert alerte["preuve"]["seuil"] == "30.00" and alerte["preuve"]["sens"] == "au_dessus"
    assert wct_id in alerte["action_proposee"]
    assert alerte["horodatage_reference"] == _charge_publiee("m4.travaux_termines", wct_id)["horodatage_completion"]

    # -- M9 : l'alerte est reçue (traitée) et rangée ---------------------------------------------
    recu_m9 = _recu(alerte["evenement_id"], "m09-strategic-intelligence")
    assert recu_m9 is not None and recu_m9["statut"] == "traite"
    assert [a["evenement_id"] for a in stockage.maillons("m09-strategic-intelligence", "alertes_m8")] == [
        alerte["evenement_id"],
    ]

    # -- M9 : la lecture stratégique cite les preuves de M8 et ne décide pas ---------------------
    lendemain_matin = _iso(base, 24 * 3600)  # chantier fini hier à 10 h, lecture demain à 7 h
    lecture = _m9(deps, "m9_produire_lecture_strategique", maintenant=lendemain_matin)
    assert lecture["preuves_m8"] == ["m8_ecart_materiaux_max_pct"]
    [item] = lecture["lectures"]
    assert item["metric_id"] == "m8_ecart_materiaux_max_pct" and item["chantier"] == wct_id
    assert (item["valeur"], item["seuil"]) == ("40.00", "30.00")
    assert item["evenement_id"] == alerte["evenement_id"]
    assert item["version_definition"] == alerte["preuve"]["version_definition"]
    assert lecture["decision"] == {"prise_par_m9": False, "a_prendre_par": "nathan_owner", "requise": True}
    assert lecture["manques"]["seuils_a_configurer"] == []

    # -- M9 : le briefing du matin montre l'alerte, sourcée, dans sa fenêtre ---------------------
    briefing = _m9(deps, "m9_produire_briefing_matin", maintenant=lendemain_matin)
    assert [a["evenement_id"] for a in briefing["sections"]["alertes_m8"]["items"]] == [alerte["evenement_id"]]
    assert briefing["affichage"]["complet"] is True

    # -- M8 et M9 ne décident rien : M4 garde son statut (jamais completed_verified sur un signal critique) --
    statut = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"


# =============================================================================================
# 2. Devis accepté APRÈS la complétion, aucun seuil configuré : M8 remesure, n'alerte pas, le dit
# =============================================================================================
def test_devis_apres_la_completion_m8_remesure_sans_seuil_pas_d_alerte_et_m9_lit_un_manque(base_durable):
    deps = charger_departements()
    m2, m3, m4, m6 = (_outils(deps, d) for d in
                       ("m02-revenue-crm", "m03-estimation", "m04-field-ops", "m06-material-control"))

    base = dt.datetime(2026, 9, 19, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-T15D-2-fictif", "DEVIS-T15D-2-fictif", "CH-T15D-2-fictif"
    marqueur = _m2_amener_pret_pour_readiness(m2, lead_id, base)
    _m3_creer_devis(m3, devis_id, lead_id, chantier_id, base)  # brouillon seulement, pas encore accepté
    _m2_transitionner(m2, lead_id, "converti", base, 300, reference_devis_m3=devis_id)
    _m2_transitionner(m2, lead_id, "cedule", base, 660)
    intervention_id = _m4_planifier_router_pointer(m4, _contrat(lead_id), marqueur, devis_id, base)
    _m2_transitionner(m2, lead_id, "chantier", base, 840)
    _m6_receptionner(m6, chantier_id, MATERIAU_ID, 200.0, f"PO-{devis_id}", base)
    wct_id = _m4_completer(m4, intervention_id, base)["wct_id"]
    _m6_declarer(m6, wct_id, chantier_id, MATERIAU_ID, 40.0)  # conforme : 0 %

    # Premier tour : le chantier terminé arrive à M8 sans son devis, qui n'est pas accepté.
    premier = evenements.repartir(deps, maintenant=_iso(base, 3600))
    assert premier["echecs"] == 0 and premier["quarantaines"] == 0, premier
    avant = {m["metric_id"]: m for m in _mesures_de_m8(deps, wct_id)["mesures"]}
    assert avant["m8_marge_prevue_cad"]["statut"] == "non_calculable"
    assert any("aucun devis accepté reçu" in m["raison"] for m in _mesures_de_m8(deps, wct_id)["manques"])

    _m3_accepter_devis(m3, devis_id, base, offset=20_000)  # accepté APRÈS la complétion
    total = _drainer(deps, base + dt.timedelta(hours=6))
    assert total["echecs"] == 0 and total["quarantaines"] == 0, total

    # -- M8 a remesuré le chantier à l'arrivée du devis -----------------------------------------
    resultat = _mesures_de_m8(deps, wct_id)
    mesures = {m["metric_id"]: m for m in resultat["mesures"]}
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"
    assert mesures["m8_ecart_materiaux_max_pct"]["valeur"] == "0.00"
    assert mesures["m8_ecart_duree_pct"]["statut"] == "non_calculable"

    # -- Aucun seuil configuré : pas d'alerte de franchissement, un rappel par métrique surveillée ----
    assert m8_outils._seuils_alerte() == {}  # le vrai `department.yaml` de M8, tel que livré
    alertes = _alertes_publiees()
    assert {a["type_alerte"] for a in alertes} == {"MESURE-SEUIL-A-CONFIGURER"}
    assert [a["metric_id"] for a in alertes] == ["m8_ecart_materiaux_max_pct"]  # la seule surveillée qui soit calculée
    assert resultat["seuils_a_configurer"] == ["m8_ecart_materiaux_max_pct"]

    # -- M9 : rien à décider, un manque à signaler -------------------------------------------------
    lendemain_matin = _iso(base, 24 * 3600)
    lecture = _m9(deps, "m9_produire_lecture_strategique", maintenant=lendemain_matin)
    assert lecture["lectures"] == [] and lecture["decision"]["requise"] is False
    assert lecture["manques"]["seuils_a_configurer"] == ["m8_ecart_materiaux_max_pct"]

    briefing = _m9(deps, "m9_produire_briefing_matin", maintenant=lendemain_matin)
    assert briefing["sections"]["alertes_m8"] == {"items": [], "vide": True}
    manques = briefing["sections"]["manques_pour_conclure"]["items"]
    [seuil] = [m for m in manques if "seuil à configurer" in m["constat"]]
    assert "m8_ecart_materiaux_max_pct" in seuil["constat"]

    # -- Le reste de la cascade converge comme d'habitude (M8 et M9 n'y changent rien) ------------
    statut = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_verified"
    assert m2_statuts.statut_courant(m2_outils._obtenir_registre(), lead_id) == "facture"
