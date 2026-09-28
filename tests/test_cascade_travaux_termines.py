"""PLAN T1.2-e — test de bout en bout de la cascade « travaux terminés » (DEFINITION-PRODUIT §6,
§9.7 ; ADR-0009 §3) sur les VRAIS départements, jamais des doublures.

Base SQLite temporaire migrée (comme au démarrage de l'instance), manifestes réels
(`opsys.departements.charger_departements` sur `departments/`), bus réel (`evenements.repartir`
sur TOUS les départements jusqu'à quiescence, boucle bornée — `_drainer` ci-dessous), outils
appelés comme en production (`opsys.outils.executer_atomique`) — même patron que
`departments/*/tests/test_evenements*.py`, mais avec la chaîne COMPLÈTE M2→M3→M4→M6 au lieu
d'événements publiés à la main. Données fictives (DEFINITION-PRODUIT §1) : identifiants,
personnes et montants sont marqués « fictif ».

`m3_marquer_devis_accepte` est T3 (frontière humaine, AGENTS.md) : appelé directement par
`executer_atomique`, sans passer par la file d'approbation du socle (`src/opsys/approbations.py`,
hors périmètre de cette tâche — un autre agent y travaille). La décision humaine elle-même
(l'approbateur qui CONSTATE l'acceptation du client) est prouvée ailleurs (tests dédiés de M3) ;
ce test-ci vérifie la CASCADE qui suit cette décision, pas le mécanisme d'approbation.

Assertions sur les reçus par consommateur (`EVENEMENTS_RECUS`, via `_recu`) et sur les registres
propres à chaque département (`opsys.stockage.maillons`), jamais sur les seuls comptes globaux du
répartiteur.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import struct
import zlib
from decimal import Decimal

import m2_revenue_crm.outils as m2_outils
import m5_financecore.facturation as m5_facturation
import m5_financecore.outils as m5_outils
import pytest
from m2_revenue_crm import statuts as m2_statuts
from m4_field_ops import cedule
from m4_field_ops.outbox import CHAMPS_WCT
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

DT_TZ = dt.timezone(dt.timedelta(hours=-4))  # Québec, heure avancée
VILLE = "Repentigny"
MATERIAU_ID = "gouttiere-alu-5po-fictif"
SEL = "sel-t1-2-e-fictif"
FIX_GPS = {"latitude": 45.7392, "longitude": -73.4536}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T1-2-E-FICTIF"}
TECHNICIEN = "TECH-T1-2-E-fictif"


# -------------------------------------------------------------------------------------------
# Fixture : base SQLite temporaire migrée (ADR-0009), comme au démarrage de l'instance.
# M2 et M5 tiennent un registre « singleton » qui bascule mémoire/durable (patron déjà établi
# par departments/m02-revenue-crm/tests/test_evenements.py et
# departments/m05-financecore/tests/test_evenements_m5.py) : on le rebranche explicitement sur
# le stockage durable, sans dépendre de l'ordre de collecte des autres suites de tests. Les
# autres départements touchés ici (M3, M4, M6, M7, M8, M10) relisent `opsys.stockage.maillons`
# à chaque appel, sans bascule à faire.
# -------------------------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-t1-2-e.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        m2_outils.reinitialiser_registre()
        stockage.liberer()


# -------------------------------------------------------------------------------------------
# Petits outils de test
# -------------------------------------------------------------------------------------------
def _iso(base: dt.datetime, offset_s: int) -> str:
    return (base + dt.timedelta(seconds=offset_s)).isoformat()


def _outils(deps, dep_id):
    """Outils d'un département via son VRAI manifeste (`department.yaml` -> `charger_outils`),
    pas un import direct de son module — pour que le test passe aussi par la même résolution
    que `opsys verifier`/le serveur MCP en production."""
    return {o.nom: o for o in deps[dep_id].charger_outils()}


def _contrat(lead_id: str, ville: str = VILLE) -> dict:
    return {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": {
            "nom": "Client Fictif", "telephone": "418-555-0100", "courriel": f"{lead_id}@exemple-fictif.test",
        },
        "type_travaux": "renovation_totale", "ville": ville, "urgence_declaree": False, "canal": "telephone",
    }


def _fenetre(base: dt.datetime) -> dict:
    return {"debut": _iso(base, 0), "fin": _iso(base, 12 * 3600)}


def _drainer(deps, base: dt.datetime, *, max_tours: int = 15, pas_s: int = 90) -> dict:
    """Draine le bus jusqu'à quiescence (répartiteur réel, `evenements.repartir`, sur TOUS les
    départements) — boucle BORNÉE (`max_tours`), jamais infinie (ADR-0009 §3, PLAN T1.2-e)."""
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
        ligne = cnx.execute(
            select(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == evenement_id,
                EVENEMENTS_RECUS.c.consommateur == consommateur,
            )
        ).mappings().first()
    return dict(ligne) if ligne else None


def _charge_publiee(type_evenement: str, evenement_id: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(
                EVENEMENTS_SORTANTS.c.type_evenement == type_evenement,
                EVENEMENTS_SORTANTS.c.evenement_id == evenement_id,
            )
        ).mappings().one()
    return codec.decoder(ligne["charge"])


def _facture_active(devis_id: str):
    with stockage.transaction():
        registre_cible = m5_outils._registre_factures(None)
        return m5_facturation.facture_active_pour_devis(registre_cible, devis_id)


def _m2_registre():
    return m2_outils._obtenir_registre()


# -------------------------------------------------------------------------------------------
# Étapes de la chaîne — chacune un VRAI appel d'outil (`executer_atomique`), comme en production.
# -------------------------------------------------------------------------------------------
def _m2_amener_pret_pour_readiness(m2, lead_id: str, base: dt.datetime) -> dict:
    """M2 : ingère le lead, le qualifie (owner + prochaine action), logue une interaction post-
    qualification, puis émet le VRAI marqueur de readiness (§6 flux principal, M2 -> M3)."""
    r = executer_atomique(m2["m2_ingerer_lead"], {"contrat": _contrat(lead_id), "horodatage": _iso(base, 0)})
    assert r["ok"] and r["resultat"]["accepte"], r

    r = executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": _iso(base, 60),
        "owner": "Alice Vendeuse (fictif)",
        "prochaine_action": {
            "description": "Planifier la visite technique (fictif)", "echeance": _iso(base, 3600),
        },
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


def _marqueur_fictif_sans_m2(lead_id: str, base: dt.datetime) -> dict:
    """Marqueur structurellement valide mais jamais signé par M2 (scénario « consommateur en
    échec » : un lead que M2 ignore totalement). M4 ne le vérifie pas contre le registre réel de
    M2 — patron déjà établi par departments/m04-field-ops/tests/test_evenements_m4.py::_marqueur."""
    return {
        "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
        "horodatage": _iso(base, 180), "empreinte": "fa" * 32,
    }


def _m3_creer_devis(m3, devis_id: str, lead_id: str, chantier_id: str | None, base: dt.datetime) -> None:
    """Devis fictif à deux lignes, choisi pour retomber sur les mêmes montants déjà vérifiés par
    departments/m05-financecore/tests/test_evenements_m5.py (600.00 $ avant taxes -> TPS 30.00 $,
    TVQ 59.85 $, 689.85 $ après taxes) : 40 pi de gouttière (8.00 $/pi, marge 25 % -> 10.00 $/pi)
    + main d'oeuvre forfaitaire (160.00 $, marge 25 % -> 200.00 $)."""
    lignes = [
        {
            "description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi",
            "cout_unitaire": "8.00", "reference_besoin_materiau": MATERIAU_ID,
        },
        {
            "description": "Main d'oeuvre installation (fictif)", "quantite": "1", "unite": "forfait",
            "cout_unitaire": "160.00", "reference_besoin_materiau": None,
        },
    ]
    r = executer_atomique(m3["m3_creer_devis"], {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": chantier_id, "lignes": lignes,
        "taux_marge": "0.25", "horodatage": _iso(base, 200), "prix_total": "600.00",
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _m3_accepter_devis(m3, devis_id: str, base: dt.datetime, offset: int = 600) -> None:
    # T3 (frontière humaine) : appelé directement, la décision humaine elle-même (l'approbateur
    # qui CONSTATE l'acceptation) est prouvée ailleurs — voir le docstring du module.
    r = executer_atomique(m3["m3_marquer_devis_accepte"], {
        "devis_id": devis_id, "approbateur": "Nathan Proprietaire (fictif, T3)", "horodatage": _iso(base, offset),
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _m2_transitionner(m2, lead_id: str, statut_cible: str, base: dt.datetime, offset: int, **kw) -> None:
    r = executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": statut_cible, "horodatage": _iso(base, offset), **kw,
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _m4_planifier_router_pointer(m4, contrat: dict, marqueur: dict, devis_id: str | None, base: dt.datetime) -> str:
    plan = executer_atomique(m4["m4_planifier_intervention"], {
        "contrat": contrat, "marqueur": marqueur, "horodatage": _iso(base, 900), "sel": SEL,
        "techniciens_disponibles": [TECHNICIEN], "fenetres_disponibles": [_fenetre(base)],
        "devis_id": devis_id,
    })
    assert plan["ok"] and plan["resultat"]["accepte"], plan
    intervention_id = plan["resultat"]["intervention_id"]

    # PLAN T4.2 (POLITIQUE-geolocalisation.md §4) : m4_pointer n'enregistre un fix GPS QUE si le
    # consentement est actif — précondition nécessaire avant tout pointage à fix réel ci-dessous.
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
    """Préalable de `_dernier_cout_unitaire_connu` (materiel.py) : une déclaration de matériaux
    utilisés exige un coût unitaire résolu depuis une réception antérieure pour ce chantier."""
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
    """PNG RVB 1x1 réel (T1.4-e2 : « petits fichiers de test réels », pas un simple préfixe
    magique) — signature + IHDR + IDAT (zlib d'une ligne filtrée « aucun ») + IEND, CRC32 correct."""
    def chunk(tag: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + tag + donnees + struct.pack(">I", zlib.crc32(tag + donnees))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff", 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _deposer_photo_test(m4) -> str:
    """Dépose une photo après-chantier RÉELLE (T1.4-e2) et rend sa référence
    `fichier:sha256:<hex>`, utilisable dans `preuves_completion.photos_apres`."""
    contenu = _png_minimal()
    r = executer_atomique(m4["m4_deposer_fichier"], {
        "empreinte_sha256": hashlib.sha256(contenu).hexdigest(),
        "taille_octets": len(contenu), "type_mime": "image/png",
        "index_bloc": 0, "nombre_blocs": 1,
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


def _m6_declarer(m6, wct_pour_m6: dict, chantier_id: str, materiau_id: str, quantite_declaree: float) -> None:
    r = executer_atomique(m6["m6_declarer_materiaux_utilises"], {
        "wct": wct_pour_m6,
        "formulaire": {
            "wct_id": wct_pour_m6["wct_id"], "intervention_id": wct_pour_m6["intervention_id"],
            "chantier_id": chantier_id,
            "lignes_materiaux": [{
                "type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite_declaree,
                "unite": "pi", "quantite_estimee": quantite_declaree,
            }],
        },
    })
    assert r["ok"] and r["resultat"]["accepte"], r


def _wct_sans_statut(wct_charge: dict) -> dict:
    """WctRecu attendu par M6 (m6_material_control.contrats.CHAMPS_WCT, copie épinglée gelée
    des 12 clés de M4 SANS `statut`).

    T1.2-f : le WCT réel porte désormais, EN PLUS de CHAMPS_WCT (M4), les champs optionnels
    réservés à M7/M8 quand ils sont connus (`m4_field_ops.outbox.CHAMPS_WCT_OPTIONNELS`, ex.
    `type_travaux` — quasi toujours connu depuis le contrat gelé). Le contrat WctRecu de M6
    reste, lui, strictement fermé : `validation.valider_wct` y refuse toute clé « en trop »
    (REJ-WCT-CHAMP-INATTENDU) — sans le filtre `k in CHAMPS_WCT` ci-dessous, cet appel casserait
    pour CHAQUE intervention. M10 (`m10_memoire.outils._recevoir_travaux_termines`) filtre déjà
    ainsi son propre bus ; M6 ne le fait pas encore côté outil `m6_declarer_materiaux_utilises`
    — gap hors périmètre de M4 (departments/m06-material-control/ non touché ici), documenté au
    rapport de T1.2-f."""
    return {k: v for k, v in wct_charge.items() if k in CHAMPS_WCT and k != "statut"}


# =============================================================================================
# 1. NOMINAL : lead M2 -> devis M3 créé puis accepté -> prévu M6 (auto, m3.devis_accepte) ->
#    complétion M4 (WCT, preuves) -> cascade -> déclaration de matériaux conforme -> variance
#    `evaluee` sans signal -> M4 `completed_verified`. Aucune quarantaine.
# =============================================================================================
def test_nominal_cascade_complete_sans_quarantaine(base_durable):
    deps = charger_departements()
    m2, m3, m4, m6 = (_outils(deps, d) for d in
                       ("m02-revenue-crm", "m03-estimation", "m04-field-ops", "m06-material-control"))

    base = dt.datetime(2026, 9, 15, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-NOM-1-fictif", "DEVIS-NOM-1-fictif", "CH-NOM-1-fictif"
    contrat = _contrat(lead_id)

    marqueur = _m2_amener_pret_pour_readiness(m2, lead_id, base)
    _m3_creer_devis(m3, devis_id, lead_id, chantier_id, base)
    _m2_transitionner(m2, lead_id, "converti", base, 300, reference_devis_m3=devis_id)
    _m3_accepter_devis(m3, devis_id, base)
    _m2_transitionner(m2, lead_id, "cedule", base, 660)

    intervention_id = _m4_planifier_router_pointer(m4, contrat, marqueur, devis_id, base)
    _m2_transitionner(m2, lead_id, "chantier", base, 840)

    _m6_receptionner(m6, chantier_id, MATERIAU_ID, 200.0, f"PO-{devis_id}", base)
    wct_resultat = _m4_completer(m4, intervention_id, base)
    wct_id = wct_resultat["wct_id"]
    assert wct_resultat["statut"] == "completed_pending_review", (
        "M4 ne peut jamais affirmer completed_verified lui-même (T1.1-b) : toujours en revue "
        "à la complétion, la vérification vient ensuite du code (variance M6)."
    )

    wct_charge = _charge_publiee("m4.travaux_termines", wct_id)
    # T1.2-f : type_travaux (connu depuis le contrat gelé à l'inscription, jamais deviné) est
    # désormais composé par M4 — voir departments/m04-field-ops/tests/test_outbox.py et
    # test_evenements_m4.py pour la preuve dédiée. Les quatre faits CLIENT (Loi 25 :
    # consentement_marketing, client_satisfait, photos, description_factuelle) restent
    # absents ICI car cette complétion n'est PAS un appel d'appareil (m4_completer_intervention
    # les refuse nommément hors d'un tel appel) ; `ville` reste un cas à part, structurellement
    # absent du WCT — M4 ne connaît la ville qu'au travers de sa tokenisation Loi 25
    # (registre immuable, jamais en clair, docs/bmad/03-ARCHITECTURE.md §2 de M4).
    assert wct_charge["type_travaux"] == "renovation_totale"
    for champ in ("consentement_marketing", "client_satisfait", "photos", "description_factuelle", "ville"):
        assert champ not in wct_charge, f"{champ} inattendu dans le WCT réel (hors appel d'appareil)"

    wct_pour_m6 = _wct_sans_statut(wct_charge)
    _m6_declarer(m6, wct_pour_m6, chantier_id, MATERIAU_ID, 40.0)

    total = _drainer(deps, base + dt.timedelta(hours=1))
    assert total["echecs"] == 0, total
    assert total["quarantaines"] == 0, total

    # -- reçus par consommateur (jamais les seuls comptes globaux du répartiteur) -----------
    for consommateur in (
        "m02-revenue-crm", "m03-estimation", "m05-financecore",
        "m06-material-control", "m07-marketing", "m08-analytics", "m10-memoire",
    ):
        recu = _recu(wct_id, consommateur)
        assert recu is not None and recu["statut"] == "traite", (consommateur, recu)

    # -- M4 : SES traces (registre + statut final) ------------------------------------------
    statut = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_verified"

    # -- M6 : SES traces (wct_recus, besoins_prevus auto via m3.devis_accepte, variance) -----
    wct_recus_m6 = list(stockage.maillons("m06-material-control", "wct_recus"))
    assert any(m["wct_id"] == wct_id for m in wct_recus_m6)
    besoins = list(stockage.maillons("m06-material-control", "besoins_prevus"))
    besoin = next(m for m in besoins if m["devis_id"] == devis_id)
    assert besoin["chantier_id"] == chantier_id
    assert besoin["lignes"] == [{"materiau_id": MATERIAU_ID, "quantite_estimee": 40.0, "unite": "pi"}]

    variance = _charge_publiee("m6.variance_chantier", f"m6-variance-{wct_id}-evaluee")
    assert variance["statut_variance"] == "evaluee"
    assert variance["signal_critique"] is False
    assert variance["chantier_id"] == chantier_id
    assert variance["lignes"] == [{
        "materiau": MATERIAU_ID, "unite": "pi",
        "quantite_prevue": "40.0", "quantite_reelle": "40.0", "ecart_pourcentage": "0.0", "critique": False,
    }]

    # -- M5 : SES traces — facture brouillon exacte (lignes, taxes, total = prix du devis) ---
    facture = _facture_active(devis_id)
    assert facture is not None
    assert facture["facture_id"] == f"fac-{devis_id}"
    assert facture["devis_id"] == devis_id
    assert facture["chantier_id"] == chantier_id
    assert facture["statut"] == "BROUILLON"
    assert len(facture["lignes"]) == 2
    assert facture["lignes"][0]["montant"] == Decimal("400.00")
    assert facture["lignes"][1]["montant"] == Decimal("200.00")
    assert facture["montant_avant_taxes"] == Decimal("600.00")
    assert [t["id"] for t in facture["taxes"]] == ["tps_federale", "tvq_quebec"]
    assert facture["taxes"][0]["montant"] == Decimal("30.00")
    assert facture["taxes"][1]["montant"] == Decimal("59.85")
    assert facture["total_taxes"] == Decimal("89.85")
    assert facture["montant_apres_taxes"] == Decimal("689.85")

    # -- M2 : SES traces — activité et prochaine action --------------------------------------
    registre_m2 = _m2_registre()
    assert m2_statuts.statut_courant(registre_m2, lead_id) == "facture"
    interactions_systeme = [
        m for m in registre_m2.lire()
        if m.get("type_entree") == "interaction" and m.get("lead_id") == lead_id and m.get("auteur") == "system:m4"
    ]
    assert len(interactions_systeme) == 1
    transitions_facture = [
        m for m in registre_m2.lire()
        if m.get("type_entree") == "transition_statut" and m.get("lead_id") == lead_id and m.get("statut") == "facture"
    ]
    assert len(transitions_facture) == 1
    # client_satisfait est absent du WCT réel (constat ci-dessus) : la table de règles M2 retombe
    # sur son troisième palier (signal non recueilli), jamais déduit.
    assert "suivi de la facture" in transitions_facture[0]["prochaine_action"]["description"]
    assert transitions_facture[0]["prochaine_action"]["echeance"] == wct_charge["horodatage_completion"]

    # -- M7 : SES traces — brouillon d'avis SEULEMENT avec consentement ----------------------
    # Constat : consentement_marketing n'existe nulle part dans le WCT réel (ci-dessus) ; M7 fail-
    # closed ne crée donc RIEN ici. La preuve positive (avec consentement -> brouillon) est un
    # test dédié : test_m7_brouillon_avis_seulement_avec_consentement_reel.
    assert list(stockage.maillons("m07-marketing", "demandes_avis")) == []

    # -- M8 : SES traces — faits mesurés (sans coût) ------------------------------------------
    snapshots = list(stockage.maillons("m08-analytics", "snapshots"))
    snap = next(
        m for m in snapshots if m.get("module_source") == "m04-field-ops" and m["valeurs"].get("m4_wct_id") == wct_id
    )
    assert snap["valeurs"]["m4_duree_reelle_minutes"] == str(wct_charge["duree_reelle_minutes"])
    # T1.2-f : type_travaux est maintenant composé par M4 (ci-dessus) — M8 le reprend
    # opportunément (m8_analytics.outils._valeurs_travaux_termines, déjà écrit pour ce cas).
    assert snap["valeurs"]["m4_type_travaux"] == "renovation_totale"

    # -- M10 : SES traces — mémoire (WCT et variance) -----------------------------------------
    evenements_m10 = list(stockage.maillons("m10-memoire", "evenements"))
    wct_memorises = [m for m in evenements_m10 if m.get("wct_id") == wct_id and "duree_reelle_minutes" in m]
    variance_memorisees = [m for m in evenements_m10 if m.get("wct_id") == wct_id and "statut_variance" in m]
    assert len(wct_memorises) == 1
    assert len(variance_memorisees) == 1
    assert variance_memorisees[0]["statut_variance"] == "evaluee"

    # -- M3 : SES traces — estimé contre réel (matériaux repris de la variance) --------------
    r = executer_atomique(m3["m3_lire_ecarts_estime_reel"], {"devis_id": devis_id})
    assert r["ok"] and r["resultat"]["accepte"], r
    ecarts = r["resultat"]["resultat"]
    assert len(ecarts) == 1
    entree = ecarts[0]
    assert entree["wct_id"] == wct_id
    # Constat documenté (estime_vs_reel.py) : aucune duree_estimee_minutes nulle part dans le
    # dépôt aujourd'hui -> lacune nommée, jamais une durée inventée.
    assert entree["main_doeuvre"]["verdict"]["code"] == "REJ-ECART-ESTIMATION-ORIGINE-ABSENTE"
    assert entree["materiaux"]["signal_critique"] is False
    assert entree["materiaux"]["lignes"] == variance["lignes"]


# =============================================================================================
# 2. ÉCART DE 40 % : même chaîne, la déclaration dépasse le seuil configuré (30 %, department.yaml
#    de M6) -> reste `completed_pending_review`, `signal_critique` vrai. M5 facture QUAND MÊME en
#    brouillon (le code ne conditionne jamais la facturation à la variance matériaux).
# =============================================================================================
def test_ecart_quarante_pourcent_reste_pending_review_et_facture_quand_meme(base_durable):
    deps = charger_departements()
    m2, m3, m4, m6 = (_outils(deps, d) for d in
                       ("m02-revenue-crm", "m03-estimation", "m04-field-ops", "m06-material-control"))

    base = dt.datetime(2026, 9, 16, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-ECART-1-fictif", "DEVIS-ECART-1-fictif", "CH-ECART-1-fictif"
    contrat = _contrat(lead_id)

    marqueur = _m2_amener_pret_pour_readiness(m2, lead_id, base)
    _m3_creer_devis(m3, devis_id, lead_id, chantier_id, base)
    _m2_transitionner(m2, lead_id, "converti", base, 300, reference_devis_m3=devis_id)
    _m3_accepter_devis(m3, devis_id, base)
    _m2_transitionner(m2, lead_id, "cedule", base, 660)

    intervention_id = _m4_planifier_router_pointer(m4, contrat, marqueur, devis_id, base)
    _m2_transitionner(m2, lead_id, "chantier", base, 840)

    _m6_receptionner(m6, chantier_id, MATERIAU_ID, 200.0, f"PO-{devis_id}", base)
    wct_resultat = _m4_completer(m4, intervention_id, base)
    wct_id = wct_resultat["wct_id"]
    wct_pour_m6 = _wct_sans_statut(_charge_publiee("m4.travaux_termines", wct_id))
    _m6_declarer(m6, wct_pour_m6, chantier_id, MATERIAU_ID, 56.0)  # prévu 40 -> +40 % (seuil 30 %)

    total = _drainer(deps, base + dt.timedelta(hours=1))
    assert total["echecs"] == 0, total
    assert total["quarantaines"] == 0, total

    variance = _charge_publiee("m6.variance_chantier", f"m6-variance-{wct_id}-evaluee")
    assert variance["statut_variance"] == "evaluee"
    assert variance["signal_critique"] is True
    assert variance["lignes"][0]["ecart_pourcentage"] == "0.4"
    assert variance["lignes"][0]["critique"] is True

    # M4 : jamais completed_verified sur un signal critique (SES traces).
    statut = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"
    recu_m4_variance = _recu(f"m6-variance-{wct_id}-evaluee", "m04-field-ops")
    assert recu_m4_variance is not None and recu_m4_variance["statut"] == "traite", (
        "M4 a bien reçu et traité la variance (il l'a lue et a choisi de ne PAS vérifier), "
        "jamais resté en échec à cause de l'écart."
    )

    # M5 : ce que le code fait RÉELLEMENT — la facture brouillon est créée quand même, le prix
    # du devis n'a aucun lien avec la variance matériaux terrain (constat, vérifié sur le code).
    facture = _facture_active(devis_id)
    assert facture is not None
    assert facture["statut"] == "BROUILLON"
    assert facture["montant_avant_taxes"] == Decimal("600.00")
    assert facture["montant_apres_taxes"] == Decimal("689.85")


# =============================================================================================
# 3. RELIVRAISON : republie le même fait (m4.travaux_termines) sous un NOUVEL evenement_id ->
#    aucun doublon nulle part (facture, maillons, mémoire, métriques, avis).
# =============================================================================================
def test_relivraison_meme_fait_nouvel_evenement_id_aucun_doublon(base_durable):
    deps = charger_departements()
    m2, m3, m4, m6 = (_outils(deps, d) for d in
                       ("m02-revenue-crm", "m03-estimation", "m04-field-ops", "m06-material-control"))

    base = dt.datetime(2026, 9, 17, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-REDEL-1-fictif", "DEVIS-REDEL-1-fictif", "CH-REDEL-1-fictif"
    contrat = _contrat(lead_id)

    marqueur = _m2_amener_pret_pour_readiness(m2, lead_id, base)
    _m3_creer_devis(m3, devis_id, lead_id, chantier_id, base)
    _m2_transitionner(m2, lead_id, "converti", base, 300, reference_devis_m3=devis_id)
    _m3_accepter_devis(m3, devis_id, base)
    _m2_transitionner(m2, lead_id, "cedule", base, 660)

    intervention_id = _m4_planifier_router_pointer(m4, contrat, marqueur, devis_id, base)
    _m2_transitionner(m2, lead_id, "chantier", base, 840)

    _m6_receptionner(m6, chantier_id, MATERIAU_ID, 200.0, f"PO-{devis_id}", base)
    wct_resultat = _m4_completer(m4, intervention_id, base)
    wct_id = wct_resultat["wct_id"]
    wct_charge = _charge_publiee("m4.travaux_termines", wct_id)
    wct_pour_m6 = _wct_sans_statut(wct_charge)
    _m6_declarer(m6, wct_pour_m6, chantier_id, MATERIAU_ID, 40.0)

    total1 = _drainer(deps, base + dt.timedelta(hours=1))
    assert total1["echecs"] == 0 and total1["quarantaines"] == 0, total1

    # -- état « avant » ------------------------------------------------------------------
    facture_avant = _facture_active(devis_id)
    assert facture_avant is not None
    wct_recus_m6_avant = len(list(stockage.maillons("m06-material-control", "wct_recus")))
    snapshots_avant = len(list(stockage.maillons("m08-analytics", "snapshots")))
    evenements_m10_avant = len(list(stockage.maillons("m10-memoire", "evenements")))
    demandes_avis_avant = len(list(stockage.maillons("m07-marketing", "demandes_avis")))
    with stockage.transaction() as cnx:
        n_variance_events_avant = len(cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m6.variance_chantier")
        ).all())
    registre_m2 = _m2_registre()
    interactions_avant = len([
        m for m in registre_m2.lire() if m.get("type_entree") == "interaction" and m.get("lead_id") == lead_id
    ])
    statut_m2_avant = m2_statuts.statut_courant(registre_m2, lead_id)

    # -- relivraison : même charge, NOUVEL evenement_id (bug producteur simulé, ou rejeu) ----
    nouvel_id = f"{wct_id}-relivraison-fictive"
    assert nouvel_id != wct_id
    evenements.publier("m4.travaux_termines", "m04-field-ops", wct_charge, evenement_id=nouvel_id)

    total2 = _drainer(deps, base + dt.timedelta(hours=3), max_tours=10)

    # Chaque consommateur reconnaît le même fait par sa propre clé métier (wct_id pour M2, M5,
    # M6, M8, M10…) : la relivraison est traitée sans rien écrire de plus, sans quarantaine.
    assert total2["echecs"] == 0 and total2["quarantaines"] == 0, total2

    for consommateur in (
        "m02-revenue-crm", "m03-estimation", "m05-financecore", "m06-material-control",
        "m07-marketing", "m08-analytics", "m10-memoire",
    ):
        recu = _recu(nouvel_id, consommateur)
        assert recu is not None and recu["statut"] == "traite", (consommateur, recu)

    # -- aucun doublon nulle part ---------------------------------------------------------
    assert _facture_active(devis_id) == facture_avant
    assert len(list(stockage.maillons("m06-material-control", "wct_recus"))) == wct_recus_m6_avant
    assert len(list(stockage.maillons("m08-analytics", "snapshots"))) == snapshots_avant
    assert len(list(stockage.maillons("m07-marketing", "demandes_avis"))) == demandes_avis_avant
    with stockage.transaction() as cnx:
        n_variance_events_apres = len(cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m6.variance_chantier")
        ).all())
    assert n_variance_events_apres == n_variance_events_avant
    # M10 « mémoire » : PREUVE du correctif wct.py (PLAN T1.2-e) — sans lui, ce compte double.
    assert len(list(stockage.maillons("m10-memoire", "evenements"))) == evenements_m10_avant

    # M2 : aucune transition ni interaction supplémentaire pour un fait déjà appliqué.
    registre_m2_apres = _m2_registre()
    interactions_apres = len([
        m for m in registre_m2_apres.lire() if m.get("type_entree") == "interaction" and m.get("lead_id") == lead_id
    ])
    assert interactions_apres == interactions_avant
    assert m2_statuts.statut_courant(registre_m2_apres, lead_id) == statut_m2_avant == "facture"


# =============================================================================================
# 4. CONSOMMATEUR EN ÉCHEC : un lead inconnu de M2 -> M2 en quarantaine après ses réessais,
#    pendant que TOUS les autres consommateurs traitent le même événement normalement.
# =============================================================================================
def test_consommateur_en_echec_m2_quarantaine_sans_bloquer_les_autres(base_durable):
    deps = charger_departements()
    m3, m4, m6 = (_outils(deps, d) for d in ("m03-estimation", "m04-field-ops", "m06-material-control"))

    base = dt.datetime(2026, 9, 18, 7, 0, 0, tzinfo=DT_TZ)
    lead_id = "LEAD-INCONNU-DE-M2-fictif"  # jamais ingéré dans M2
    devis_id, chantier_id = "DEVIS-ECHEC-1-fictif", "CH-ECHEC-1-fictif"
    contrat = _contrat(lead_id)
    marqueur = _marqueur_fictif_sans_m2(lead_id, base)

    _m3_creer_devis(m3, devis_id, lead_id, chantier_id, base)
    _m3_accepter_devis(m3, devis_id, base)
    intervention_id = _m4_planifier_router_pointer(m4, contrat, marqueur, devis_id, base)
    _m6_receptionner(m6, chantier_id, MATERIAU_ID, 200.0, f"PO-{devis_id}", base)
    wct_resultat = _m4_completer(m4, intervention_id, base)
    wct_id = wct_resultat["wct_id"]
    wct_pour_m6 = _wct_sans_statut(_charge_publiee("m4.travaux_termines", wct_id))
    _m6_declarer(m6, wct_pour_m6, chantier_id, MATERIAU_ID, 40.0)

    t = base + dt.timedelta(hours=1)
    resume1 = evenements.repartir(deps, maintenant=_iso(t, 0))
    assert resume1["echecs"] == 1, resume1
    assert resume1["quarantaines"] == 0, resume1

    recu_m2_t1 = _recu(wct_id, "m02-revenue-crm")
    assert recu_m2_t1 is not None and recu_m2_t1["statut"] == "echec"
    assert recu_m2_t1["tentatives"] == 1
    assert "LeadIntrouvable" in recu_m2_t1["derniere_erreur"]

    # Dès ce PREMIER tour, tous les autres consommateurs ont déjà traité le même événement.
    for consommateur in (
        "m03-estimation", "m05-financecore", "m06-material-control",
        "m07-marketing", "m08-analytics", "m10-memoire",
    ):
        recu = _recu(wct_id, consommateur)
        assert recu is not None and recu["statut"] == "traite", (
            f"{consommateur} doit traiter normalement dès le premier tour malgré l'échec de M2 : {recu}"
        )

    # Draine jusqu'à la quarantaine de M2 (5 tentatives, recul 2^n s), sans jamais rien bloquer
    # d'autre (la variance M6 -> M4/M3/M10, publiée pendant ce même drainage, se livre normalement).
    for _ in range(6):
        t += dt.timedelta(seconds=100)
        evenements.repartir(deps, maintenant=_iso(t, 0))

    recu_m2_final = _recu(wct_id, "m02-revenue-crm")
    assert recu_m2_final is not None and recu_m2_final["statut"] == "quarantaine"
    assert recu_m2_final["tentatives"] == 5

    quarantaine = [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == "m02-revenue-crm"]
    assert len(quarantaine) == 1
    assert quarantaine[0]["evenement_id"] == wct_id

    # M2 n'a RIEN écrit (aucune écriture partielle, ADR-0009 §3).
    assert m2_statuts.statut_courant(_m2_registre(), lead_id) is None

    # La quarantaine de M2 ne bloque rien côté M4 : la variance (evaluee, sans signal) a quand
    # même été livrée à M4, qui atteint son état final normalement.
    statut = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_verified"


# =============================================================================================
# 5. ORDRE INVERSÉ : la complétion arrive avant l'acceptation du devis -> tout converge au même
#    état final que le nominal.
# =============================================================================================
def test_ordre_inverse_completion_avant_acceptation_devis_converge_comme_nominal(base_durable):
    deps = charger_departements()
    m2, m3, m4, m6 = (_outils(deps, d) for d in
                       ("m02-revenue-crm", "m03-estimation", "m04-field-ops", "m06-material-control"))

    base = dt.datetime(2026, 9, 19, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-INVERSE-1-fictif", "DEVIS-INVERSE-1-fictif", "CH-INVERSE-1-fictif"
    contrat = _contrat(lead_id)

    marqueur = _m2_amener_pret_pour_readiness(m2, lead_id, base)
    _m3_creer_devis(m3, devis_id, lead_id, chantier_id, base)  # BROUILLON seulement, pas accepté
    _m2_transitionner(m2, lead_id, "converti", base, 300, reference_devis_m3=devis_id)
    _m2_transitionner(m2, lead_id, "cedule", base, 660)

    intervention_id = _m4_planifier_router_pointer(m4, contrat, marqueur, devis_id, base)
    _m2_transitionner(m2, lead_id, "chantier", base, 840)
    _m6_receptionner(m6, chantier_id, MATERIAU_ID, 200.0, f"PO-{devis_id}", base)

    # La complétion (et le WCT publié) arrive AVANT l'acceptation du devis.
    wct_resultat = _m4_completer(m4, intervention_id, base)
    wct_id = wct_resultat["wct_id"]
    wct_pour_m6 = _wct_sans_statut(_charge_publiee("m4.travaux_termines", wct_id))
    _m6_declarer(m6, wct_pour_m6, chantier_id, MATERIAU_ID, 40.0)

    assert _facture_active(devis_id) is None, "le devis n'est pas encore accepté : rien à facturer"

    _m3_accepter_devis(m3, devis_id, base, offset=20_000)  # ACCEPTÉ APRÈS la complétion

    total = _drainer(deps, base + dt.timedelta(hours=6))
    assert total["echecs"] == 0, total
    assert total["quarantaines"] == 0, total

    # -- même état final que le scénario nominal ---------------------------------------------
    statut = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_verified"

    variance = _charge_publiee("m6.variance_chantier", f"m6-variance-{wct_id}-evaluee")
    assert variance["signal_critique"] is False
    assert variance["lignes"][0]["ecart_pourcentage"] == "0.0"

    facture = _facture_active(devis_id)
    assert facture is not None
    assert facture["statut"] == "BROUILLON"
    assert facture["montant_avant_taxes"] == Decimal("600.00")
    assert facture["total_taxes"] == Decimal("89.85")
    assert facture["montant_apres_taxes"] == Decimal("689.85")

    assert m2_statuts.statut_courant(_m2_registre(), lead_id) == "facture"

    evenements_m10 = list(stockage.maillons("m10-memoire", "evenements"))
    assert any(m.get("wct_id") == wct_id and "duree_reelle_minutes" in m for m in evenements_m10)
    assert any(m.get("wct_id") == wct_id and m.get("statut_variance") == "evaluee" for m in evenements_m10)


# =============================================================================================
# Complément ciblé : le gap M7 constaté dans le scénario nominal (M4 réel ne porte jamais
# consentement_marketing/client_satisfait) laisse la moitié « avec consentement » de la règle
# « brouillon SEULEMENT avec consentement » non exercée par la cascade réelle. Ce test appelle
# le VRAI consommateur M7 (chargé depuis le manifeste, comme le répartiteur le ferait) avec une
# charge conforme au catalogue qui PORTE le consentement, pour prouver les DEUX branches.
# =============================================================================================
def test_m7_brouillon_avis_seulement_avec_consentement_reel(base_durable):
    deps = charger_departements()
    consommateur_m7 = deps["m07-marketing"].charger_consommateurs()["m4.travaux_termines"]

    def _charge(wct_id: str, **overrides) -> dict:
        base = {
            "wct_id": wct_id, "intervention_id": f"INT-{wct_id}", "lead_id": f"LEAD-{wct_id}",
            "technicien_id": "TECH-M7-fictif", "horodatage_completion": "2026-09-20T14:00:00-04:00",
            "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5}, "duree_reelle_minutes": 120,
            "ecart_signale": False, "revue_id": None, "hash_maillon": "fi" * 32,
            "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"], "devis_id": f"DEVIS-{wct_id}",
        }
        base.update(overrides)
        return base

    with stockage.transaction():
        resultat = consommateur_m7(_charge(
            "WCT-M7-CONSENT-fictif", consentement_marketing=True, client_satisfait=True,
        ))
    assert resultat["brouillon_cree"] is True
    demandes = list(stockage.maillons("m07-marketing", "demandes_avis"))
    assert any(m["wct_id"] == "WCT-M7-CONSENT-fictif" for m in demandes)

    with stockage.transaction():
        resultat2 = consommateur_m7(_charge(
            "WCT-M7-SANS-CONSENT-fictif", consentement_marketing=False, client_satisfait=True,
        ))
    assert resultat2["brouillon_cree"] is False
    demandes_apres = list(stockage.maillons("m07-marketing", "demandes_avis"))
    assert not any(m["wct_id"] == "WCT-M7-SANS-CONSENT-fictif" for m in demandes_apres)
    assert len(demandes_apres) == 1, "le refus sans consentement n'écrit toujours rien"
