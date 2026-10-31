"""PLAN T1.5-d — la marge réelle de M5 atteint M8 et M10 (DEFINITION-PRODUIT §6 « travaux terminés » : « M5
calcule le coût réel [...] et la rentabilité ; M8 : temps réel vs prévu, marge prévue vs réelle ; M10 : rien
n'est oublié »), par le VRAI bus, sur les VRAIS départements, sans doublure.

Devis accepté (M3, avec la durée estimée de son estimation) → travaux terminés (M4, vrais outils : planification,
journée d'ÉQUIPE certifiée — cédule datée, visite, pointages d'équipe V3 —, complétion) → variance de matériaux (M6)
→ M5 calcule le coût réel et la marge (prix du livre de prix M6, main-d'oeuvre = projection M4 vérifiée × tarif
d'équipe M5) et publie `m5.rentabilite_chantier` → M8 mesure la marge réelle et le temps prévu contre réel →
M10 mémorise l'écart de marge, sans qu'aucun montant ne sorte dans un paquet.

Depuis la PR #861 une durée scalaire de WCT (pointage individuel) ne chiffre plus la main-d'oeuvre : coût partiel,
`REJ-COUT-TEMPS-POINTE-ABSENT` (scénario 2). Le coût complet n'existe que par la voie certifiée (helpers
`_m4_journee_equipe_certifiee`, `_recalculer_cout_certifie`, `_relecture_m5_sur_projection_certifiee`).

Trois scénarios, chacun sur une base SQLite temporaire migrée :

1. coût complet (voie certifiée, prix au livre) : marge réelle, écart de marge, temps prévu, alerte de marge
   (seuil configuré à -20 %), leçon mémorisée par M10 au niveau FINANCIAL ;
2. coût PARTIEL (état de livraison : ni taux, ni prix) : aucune marge ne part de M5, M8 dit « non calculable,
   manque marge_reelle_cad » avec les codes de M5, M10 garde un état sans marge ;
3. le prix arrive après coup : le partiel est remplacé par l'état complet, à tous les étages.

Fichier NOUVEAU : le patron des helpers est celui de `test_cascade_mesure_m8_m9.py`, recopié pour ne pas dépendre
d'un fichier que d'autres agents modifient. Identifiants, personnes et montants fictifs.
"""

from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import json
import struct
import time
import zlib
from decimal import Decimal

import m2_revenue_crm.outils as m2_outils
import m3_estimation.outils as m3_outils
import m5_financecore.outils as m5_outils
import pytest
import yaml
from m3_estimation import trace_calibration_temps
from m4_field_ops import (
    calendrier_civil,
    cedule,
    cedule_tournees,
    ecarts,
    encodage,
    equipes_pointees_v3,
    temps_certifies_v3,
    visites_ecriture,
)
from m4_field_ops import outils as m4_outils
from m4_field_ops.registre import Registre
from m8_analytics import outils as m8_outils
from sqlalchemy import insert, select

from opsys import (
    approbations,
    contexte,
    equipes,
    evenements,
    identite,
    service_lecture_m4,
    service_recalcul_m4,
    stockage,
)
from opsys.capacites import Capacites, outils_executables
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, OPSYS_INSTANCE, SERVICE_POLITIQUES

DT_TZ = dt.timezone(dt.timedelta(hours=-4))  # Québec, heure avancée
VILLE = "Repentigny"
MATERIAU_ID = "gouttiere-alu-5po-fictif"
SEL = "sel-t15d-fictif"
FIX_GPS = {"latitude": 45.7392, "longitude": -73.4536}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T15D-FICTIF"}
TECHNICIEN = "TECH-T15D-fictif"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-t15d-marge.db'}"
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


@pytest.fixture
def taux_m5(tmp_path, monkeypatch):
    """Nathan configure le taux horaire de la main-d'oeuvre (50,00 $/h) : le manifeste livré de M5 n'en porte pas."""
    def poser(taux="50.00"):
        manifeste = tmp_path / "department-m5.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": {"taux_horaire_main_d_oeuvre": taux}}), encoding="utf-8")
        monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
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


def _m3_creer_devis(
    m3, devis_id: str, lead_id: str, chantier_id: str, base: dt.datetime,
    estimation_source_hash: str | None = None,
) -> None:
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
        **({"estimation_source_hash": estimation_source_hash} if estimation_source_hash is not None else {}),
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


# -------------------------------------------------------------------------------------------
# Voie CERTIFIÉE du coût de main-d'oeuvre (PR #861) : pointages d'ÉQUIPE V3 sur une vraie visite, projection M4
# vérifiée (service `m4.verifier_v3`), tarif d'équipe de M5. Une durée scalaire ne chiffre plus rien (scénario 2).
# Même logique que `_journee_equipe_certifiee` de tests/e2e/test_verticale_affaire_durable.py, au niveau
# « départements + bus » : mêmes modules M4/M5, mêmes appels, dans une transaction du stockage.
# -------------------------------------------------------------------------------------------
EQUIPE = "eq-t15d-fictive"
ADMIN_CERTIFIE = "admin-t15d-certifie-fictif"
TARIF_EQUIPE_CAD_H = "50.00"  # $/h-équipe : la même valeur que le taux horaire configuré des anciens tests


def _admin_console():
    """Les trois contextes d'un geste admin de console (identité, département d'origine, jeton)."""
    return (contexte.appele_par_appareil(contexte.IdentiteAppelante(ADMIN_CERTIFIE, "admin", source="console")),
            contexte.appeler_en_tant_que("m04-field-ops", origine="console"))


def _reception(instant: dt.datetime):
    return contexte.receptionne_de(contexte.HorodatageAppareil(f"console:{ADMIN_CERTIFIE}", instant, instant))


def _declarer_equipe_et_tarif_certifies(base: dt.datetime) -> None:
    """Profil d'équipe, compte admin, tarif d'équipe M5 (port de déclaration) et politique `m4.verifier_v3`
    de M5, dans la base éphémère de ce test seulement."""
    equipes.enregistrer_equipes({"liste": [{
        "id": EQUIPE, "membres": ["membre-t15d-fictif"], "competences": [],
        "depot": {"id": "depot-t15d", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
        "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
    }]})
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN_CERTIFIE, "Admin certifié (fictif)",
                                "un-mot-de-passe-certifie-suffisamment-long", ["admin"])
    with (stockage.transaction() as cnx, contexte.appele_par_appareil(
            contexte.IdentiteAppelante(ADMIN_CERTIFIE, "admin", source="console")),
          contexte.appeler_en_tant_que("m05-financecore", origine="console")):
        source = m5_outils._lire_tarifs_equipes()["source"]
        m5_outils._inscrire_tarif_equipe({
            "equipe_id": EQUIPE, "taux": TARIF_EQUIPE_CAD_H, "unite": "heure-equipe", "devise": "CAD",
            "source": "tarif-t15d-fictif", "version": "1",
            "date_effet": base.date().isoformat(), "date_fin": base.date().isoformat(), "remplace_id": None,
        }, mutation_id="tarif-equipe-t15d-fictif", source_attendue=source)
    _poser_politique("m4.verifier_v3")


def _positions_fictives(_registre, _lead_id):
    return {"latitude_microdegres": 45740117, "longitude_microdegres": -73454833, "version": 1, "ligne_id": "x"}, None


def _m4_cedule_datee_pour_equipe(intervention_id: str, base: dt.datetime) -> dict:
    """Proposition, application puis datation civile d'un plan qui assigne l'intervention à l'équipe, puis
    prévision de visite ancrée sur cette date. Rend l'ancre de la visite."""
    arguments = {
        "equipes": [{cle: v for cle, v in e.items() if cle != "membres"}
                    for e in equipes.charger_equipes()[0]["liste"]],
        "durees_par_type_travaux": {"renovation_totale": 150},
        "competences_par_type_travaux": {"renovation_totale": []},
        "chantiers": [{"intervention_id": intervention_id,
                       "fenetre": {"jours": [0], "debut_min": 480, "fin_min": 1020}, "creneau_fige": None}],
        "parametres": {"facteur_detour_milliemes": 1300, "vitesse_moyenne_kmh": 50,
                       "marge_par_trajet_secondes": 600, "iterations": 300, "cout_non_cedule_m": 500000},
    }
    with stockage.transaction():
        principal = Registre(stockage.maillons("m04-field-ops", "principal"))
        proposition, verdict = cedule_tournees.proposer(
            principal, arguments, _positions_fictives, _iso(base, 960), moteur="dp")
        assert verdict is None, verdict
        plan_id = proposition["plan_id"]
        application, verdict = cedule_tournees.appliquer(
            principal, plan_id, _positions_fictives, _iso(base, 1020), ADMIN_CERTIFIE)
        assert verdict is None, verdict
        (assignation,) = [a for a in application["assignations"] if a["intervention_id"] == intervention_id]
        assert assignation["technicien_id"] == EQUIPE, "assignation native du solveur, jamais fabriquée par le test"
        datee = calendrier_civil.confirmer(
            principal, plan_id, {"0": base.date().isoformat()}, 0, ADMIN_CERTIFIE, _iso(base, 1080))
        date = next(m for m in principal.lire() if m.get("ligne_id") == datee["ligne_id"])
        return {"intervention_id": intervention_id, "plan_id": plan_id,
                "source_application_id": date["source_application_id"], "source_ligne_id": date["ligne_id"]}


def _m4_evenement_visite(operation: str, visite_id: str, instant: dt.datetime) -> None:
    c1, c2 = _admin_console()
    with stockage.transaction() as cnx, c1, c2, _reception(instant):
        args = {"operation": operation, "visite_id": visite_id,
                "source_attendue": visites_ecriture.empreinte_sources(cnx)}
        mutation = {"appareil": f"console:{ADMIN_CERTIFIE}", "cle": f"{operation}-visite-t15d",
                    "empreinte_arguments": encodage.empreinte(args)}
        visites_ecriture.executer_evenement(cnx, args, {"personne": ADMIN_CERTIFIE, "role": "admin"}, mutation,
                                            instant.isoformat(), m4_outils._autoriser_annotation)


def _m4_pointer_equipe(intervention_id: str, visite_id: str, action: str, instant: dt.datetime, base: dt.datetime):
    """Déclaration d'ÉQUIPE (jamais une présence individuelle) sur la visite ouverte, puis résolution de la
    demande de revue qu'elle ouvre (contrôle admin fictif)."""
    referentiel = {cedule.tokeniser_ville(SEL, VILLE): {
        "latitude": FIX_GPS["latitude"], "longitude": FIX_GPS["longitude"], "rayon_km": 25.0}}
    c1, c2 = _admin_console()
    with stockage.transaction() as cnx, c1, c2, _reception(instant):
        arguments = {
            "intervention_id": intervention_id, "technicien_id": EQUIPE, "action": action,
            "horodatage": instant.isoformat(), "fix_gps": None,
            "attestation": {"fictif": True, "appareil_id": f"console:{ADMIN_CERTIFIE}"},
            "fenetre_travail": _fenetre(base), "referentiel_villes": referentiel, "ville": VILLE, "sel": SEL,
        }
        recu = equipes_pointees_v3.enregistrer(
            cnx, arguments, visite_id, EQUIPE, f"pointage-equipe-t15d-{action}",
            equipes_pointees_v3.empreinte_sources(cnx))
        principal = Registre(stockage.maillons("m04-field-ops", "principal"))
        demandes = [m for m in principal.lire() if m.get("type_entree") == "demande_revue"
                    and m.get("pointage_ligne_id") == recu["pointage_id"]]
        for demande in demandes:
            _, erreur = ecarts.resoudre_demande(demande["demande_id"], "validee", instant.isoformat(), principal)
            assert erreur is None, erreur


def _m4_journee_equipe_certifiee(m4, contrat: dict, marqueur: dict, devis_id: str, base: dt.datetime) -> str:
    """Voie certifiée : l'intervention (inscrite par `m4_planifier_intervention`) est cédulée et datée pour
    l'équipe, une visite est prévue puis ouverte, l'équipe déclare son arrivée (1 h) et son départ (3 h) : 120 min
    de travail certifié, comme l'ancien pointage individuel. Rend `intervention_id`."""
    plan = executer_atomique(m4["m4_planifier_intervention"], {
        "contrat": contrat, "marqueur": marqueur, "horodatage": _iso(base, 900), "sel": SEL,
        "techniciens_disponibles": [TECHNICIEN], "fenetres_disponibles": [_fenetre(base)], "devis_id": devis_id,
    })
    assert plan["ok"] and plan["resultat"]["accepte"], plan
    intervention_id = plan["resultat"]["intervention_id"]
    _declarer_equipe_et_tarif_certifies(base)
    ancre = _m4_cedule_datee_pour_equipe(intervention_id, base)
    c1, c2 = _admin_console()
    instant = base + dt.timedelta(seconds=1140)
    with stockage.transaction() as cnx, c1, c2, _reception(instant):
        args = {"ancre": ancre, "revision_attendue": 0}
        mutation = {"appareil": f"console:{ADMIN_CERTIFIE}", "cle": "visite-prevue-t15d",
                    "empreinte_arguments": encodage.empreinte(args)}
        prevue = visites_ecriture.enregistrer(cnx, args, {"personne": ADMIN_CERTIFIE, "role": "admin"}, mutation,
                                              instant.isoformat(), m4_outils._autoriser_annotation)
    visite_id = prevue["visite_id"]
    _m4_evenement_visite("ouvrir", visite_id, base + dt.timedelta(seconds=1200))
    depart_route = executer_atomique(m4["m4_demarrer_route"], {
        "intervention_id": intervention_id, "technicien_id": EQUIPE, "horodatage": _iso(base, 1800),
    })
    assert depart_route["ok"] and depart_route["resultat"]["accepte"], depart_route
    for action, offset in (("arrivee", 3600), ("depart", 10800)):
        _m4_pointer_equipe(intervention_id, visite_id, action, base + dt.timedelta(seconds=offset), base)
    _m4_evenement_visite("fermer", visite_id, base + dt.timedelta(seconds=10860))
    return intervention_id


def _m4_revue_humaine_verifiee(deps, intervention_id: str, instant: dt.datetime) -> None:
    """Revue HUMAINE d'une complétion en attente (N4 : l'outil propose, une personne décide) : nécessaire quand la
    variance de matériaux dépasse le seuil de M4 (56 pi pour 40 prévus) ; en dessous, M4 vérifie seule."""
    demande = Capacites({"m04-field-ops": deps["m04-field-ops"]}, stockage.transaction).appeler(
        "m4_resoudre_revue_completion", {
            "intervention_id": intervention_id, "decision": "verifiee", "horodatage": instant.isoformat(),
            "motif": "Revue fictive : 16 pi de plus que prévu, confirmés au chantier.",
        })
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision = approbations.decider(
            cnx, demande["demande_id"], True, ADMIN_CERTIFIE, outils_executables(deps, stockage.transaction), deps)
    assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"], decision


def _session_admin_certifie() -> Session:
    return Session(ADMIN_CERTIFIE, frozenset({"admin"}), "csrf-fictif", int(time.time()) + 3600)


def _poser_politique(operation: str) -> None:
    """Politique de service de M5 (ligne SERVICE_POLITIQUES, base éphémère de ce test), posée une seule fois."""
    with stockage.transaction() as cnx:
        instance_id = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        if cnx.execute(select(SERVICE_POLITIQUES.c.revision).where(
                SERVICE_POLITIQUES.c.operation == operation)).first() is not None:
            return
        cnx.execute(insert(SERVICE_POLITIQUES).values(
            instance_id=instance_id, consommateur="m05-financecore", operation=operation,
            revision=1, active=True, expire_le=int(time.time()) + 3600))


def _recalculer_cout_certifie(wct_id: str, devis_id: str, etiquette: str) -> dict:
    """Recalcul de M5 par la voie certifiée, SUR la projection M4 vérifiée (pointages d'équipe V3, tarif d'équipe).

    Pourquoi ce recalcul : à la livraison du WCT, M4 est toujours `completed_pending_review` (la variance M6 n'arrive
    qu'après), donc la projection n'est pas exploitable ; et les pièces suivantes (variance, facture, prix) ne
    déclenchent qu'un calcul sur la durée scalaire, qui ne chiffre plus la main-d'oeuvre. Seul le candidat interne
    `service_recalcul_m4` (couture QA `_executer_qa`, politique `m4.recalculer_v3`, non routé en production)
    republie le coût sur la projection vérifiée, comme le fait aussi l'e2e `test_verticale_affaire_durable.py`."""
    _poser_politique("m4.recalculer_v3")
    with stockage.transaction() as cnx:
        recalcul = service_recalcul_m4._executer_qa(
            cnx, _session_admin_certifie(), wct_id=wct_id, devis_id=devis_id,
            intention_id=hashlib.sha256(etiquette.encode("utf-8")).hexdigest())
    assert recalcul["statut"] == "publiee"
    assert recalcul["attestation"]["operation"] == "m4.recalculer_v3"
    return recalcul


@contextlib.contextmanager
def _relecture_m5_sur_projection_certifiee(monkeypatch, wct_id: str, devis_id: str):
    """Fait relire à M5 son coût sur la projection M4 vérifiée (couture QA `_ouvrir_qa` de la relecture courante,
    politique `m4.relire_faits_pour_m5_v1`) quand M3 lit la rentabilité : sans elle, la lecture ordinaire de M5
    ne voit que la durée scalaire. Même couture que l'e2e, au niveau départements (session admin de console)."""
    _poser_politique("m4.relire_faits_pour_m5_v1")
    original = m5_outils.lire_rentabilite_chantier

    def lire_sous_portee(*args, **kwargs):
        if kwargs.get("devis_id") != devis_id:
            return original(*args, **kwargs)
        with stockage.transaction() as cnx, service_lecture_m4._ouvrir_qa(
                cnx, _session_admin_certifie(), wct_id=wct_id, devis_id=devis_id):
            return original(*args, **kwargs)

    with monkeypatch.context() as ctx:
        ctx.setattr(m5_outils, "lire_rentabilite_chantier", lire_sous_portee)
        yield


def _projection_certifiee(intervention_id: str, wct_id: str) -> dict:
    """La projection M4 V3 telle que M5 la consomme (lecture seule, sous l'identité admin de console)."""
    c1, c2 = _admin_console()
    with stockage.transaction() as cnx, c1, c2:
        return temps_certifies_v3.projeter(cnx, intervention_id, wct_id)["projection"]


def _prouver_main_d_oeuvre_certifiee(
        intervention_id: str, wct_id: str, *, minutes: int = 120, publications: int = 1) -> None:
    """La DERNIÈRE trace de M5 chiffre la main-d'oeuvre à partir de la projection M4 V3 vérifiée et du tarif
    d'équipe (jamais de la durée scalaire du WCT) : visite, équipe pointée, tarif et empreintes sont ceux de la
    projection relue ici ; 120 min nettes x 50,00 $/h-équipe = 100,00 $."""
    projection = _projection_certifiee(intervention_id, wct_id)
    assert projection["version"] == "opsys.m4.temps_certifies.v3"
    assert projection["totaux"]["travail"] == minutes
    (visite,) = projection["visites"]
    assert visite["equipe_pointee"]["statut"] == "identifiee" and visite["equipe_pointee"]["identifiant"] == EQUIPE
    assert visite["presence_individuelle"] == {"statut": "inconnue"}  # aucune présence individuelle supposée
    with stockage.transaction():
        derniere = list(stockage.maillons("m05-financecore", "rentabilite"))[-1]
        recus_recalcul = list(stockage.maillons("m05-financecore", "rentabilite_recalcul_v2"))
    main_d_oeuvre = derniere["rentabilite"]["cout_reel"]["main_d_oeuvre"]
    assert main_d_oeuvre["statut"] == "complet" and main_d_oeuvre["projection_empreinte"] == projection["empreinte"]
    assert main_d_oeuvre["minutes"] == minutes and main_d_oeuvre["cout"] == Decimal(minutes) * Decimal("50") / 60
    (ligne,) = main_d_oeuvre["lignes"]
    assert (ligne["visite_id"], ligne["equipe_id"], ligne["minutes_nettes"]) == (visite["visite_id"], EQUIPE, minutes)
    assert (ligne["taux"], ligne["unite"], ligne["source"]) == (Decimal(TARIF_EQUIPE_CAD_H), "heure-equipe",
                                                                "tarif-t15d-fictif")
    assert derniere["provenance_service_v1"]["version"] == "opsys.m4.temps_certifies.v3"
    assert derniere["provenance_service_v1"]["empreinte_projection"] == projection["empreinte"]
    assert len(recus_recalcul) == publications  # exactement les publications faites par la voie certifiée
    assert all(r["wct_id"] == wct_id and r["type"] == "publication_recalcul_v2" for r in recus_recalcul)


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


def _m4_completer(m4, intervention_id: str, base: dt.datetime, offset: int = 11400, *, certifie: bool = False) -> dict:
    """Complétion par l'outil propriétaire. Une intervention à visite d'équipe se complète sous l'identité
    admin de la console (la visite et l'équipe sont privées), comme `tests/test_qa_m4_core_m5.py`."""
    c1, c2 = _admin_console() if certifie else (contextlib.nullcontext(), contextlib.nullcontext())
    with c1, c2:
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


# -------------------------------------------------------------------------------------------
# Ce que la chaîne ajoute à ce fichier : M5 (livre de prix, taux), estimation de M3, lecture de M5/M8/M10
# -------------------------------------------------------------------------------------------
DUREE_ESTIMEE = "90"  # minutes, portée par l'estimation du devis puis par m3.devis_accepte
TYPE_M5 = "m5.rentabilite_chantier"
MONTANTS_M5 = ("52.00", "-68.00", "548.00", "120.00")  # marge réelle, écart, coût réel, marge prévue du scénario 1


def _m3_ecrire_estimation(devis_id: str, lead_id: str, duree_estimee_minutes: str) -> str:
    """Écrit une estimation fictive qualifiée et renvoie son hash exact pour l'épingler au devis."""
    bareme = {
        "version": "v1-fictif",
        "unite": "pi",
        "semantique_temps": "duree_ecoulee_intervention",
    }
    trace, verdict = trace_calibration_temps.construire_trace(
        bareme=bareme,
        type_service="gouttieres",
        quantite="40",
        taux_minutes_par_unite=Decimal(duree_estimee_minutes) / Decimal("40"),
        duree_estimee_minutes=duree_estimee_minutes,
    )
    assert verdict is None and trace is not None, verdict
    with stockage.transaction():
        maillon, verdict = m3_outils.registre_production().ajouter({
            "devis_id": devis_id, "lead_id": lead_id, "empreinte_marqueur_m2": "e" * 64, "niveau_confiance": 0.9,
            "bareme_version": "v1-fictif", "graine_monte_carlo": 7,
            "duree_estimee_minutes": duree_estimee_minutes, "trace_calibration_temps": trace,
        })
    assert verdict is None, verdict
    return maillon["hash_maillon"]


def _m6_prix_au_livre(m6, prix: float = 8.0) -> None:
    r = executer_atomique(m6["m6_enregistrer_prix"], {
        "materiau_id": MATERIAU_ID, "fournisseur_id": "gentek-fictif", "prix_unitaire": prix, "devise": "CAD",
        "date_effet": "2026-09-01", "source_document": None, "unite": "pi"})
    assert r["ok"] and r["resultat"]["accepte"], r


def _chantier_termine(deps, base: dt.datetime, lead_id: str, devis_id: str, chantier_id: str,
                      quantite_declaree: float, *, duree_estimee: str | None = DUREE_ESTIMEE,
                      certifie: bool = False) -> tuple[str, str]:
    """Du lead au chantier terminé, avec les vrais outils : rend `(wct_id, intervention_id)`. Le bus n'est pas
    encore livré : chaque test le draine quand il le veut. `certifie` : la journée passe par la voie certifiée
    (équipe, visite, pointages d'équipe V3) au lieu du pointage individuel, qui ne laisse qu'une durée scalaire."""
    m2, m3, m4, m6 = (_outils(deps, d) for d in
                       ("m02-revenue-crm", "m03-estimation", "m04-field-ops", "m06-material-control"))
    marqueur = _m2_amener_pret_pour_readiness(m2, lead_id, base)
    estimation_source_hash = (
        _m3_ecrire_estimation(devis_id, lead_id, duree_estimee) if duree_estimee is not None else None
    )
    _m3_creer_devis(m3, devis_id, lead_id, chantier_id, base, estimation_source_hash)
    _m2_transitionner(m2, lead_id, "converti", base, 300, reference_devis_m3=devis_id)
    _m3_accepter_devis(m3, devis_id, base)
    _m2_transitionner(m2, lead_id, "cedule", base, 660)
    if certifie:
        intervention_id = _m4_journee_equipe_certifiee(m4, _contrat(lead_id), marqueur, devis_id, base)
    else:
        intervention_id = _m4_planifier_router_pointer(m4, _contrat(lead_id), marqueur, devis_id, base)
    _m2_transitionner(m2, lead_id, "chantier", base, 840)
    _m6_receptionner(m6, chantier_id, MATERIAU_ID, 200.0, f"PO-{devis_id}", base)
    wct_id = _m4_completer(m4, intervention_id, base, certifie=certifie)["wct_id"]
    _m6_declarer(m6, wct_id, chantier_id, MATERIAU_ID, quantite_declaree)
    return wct_id, intervention_id


def _publies_m5() -> list[dict]:
    """Les `m5.rentabilite_chantier` publiées, par ordre de trace."""
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge, EVENEMENTS_SORTANTS.c.producteur).where(
            EVENEMENTS_SORTANTS.c.type_evenement == TYPE_M5)).all()
    charges = [codec.decoder(ligne.charge) for ligne in lignes]
    assert {ligne.producteur for ligne in lignes} <= {"m05-financecore"}
    return sorted(charges, key=lambda charge: charge["sequence"])


def _alertes_publiees() -> list[dict]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m8.alerte_proposee")
            .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)
        ).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


def _recu(evenement_id: str, consommateur: str) -> dict | None:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.evenement_id == evenement_id, EVENEMENTS_RECUS.c.consommateur == consommateur,
        )).mappings().first()
    return dict(ligne) if ligne else None


def _m10_rentabilites() -> list[dict]:
    with stockage.transaction():
        return sorted((m for m in stockage.maillons("m10-memoire", "evenements") if "marge_reelle_cad" in m),
                      key=lambda m: m["sequence"])


def _retenus_attendus(agent) -> int:
    """Ce que M10 retient d'un paquet pour cet agent : chaque élément FINANCIAL (les leçons de marge de M5, et depuis
    T4.18 le prix et le coût du devis accepté), et le client associé (CLIENT_PRIVATE) sauf pour M1 et M2."""
    with stockage.transaction():
        niveaux = [m.get("confidentialite") for m in stockage.maillons("m10-memoire", "evenements")]
    prives_admis = agent in ("m01-front-office", "m02-revenue-crm")
    return niveaux.count("FINANCIAL") + (0 if prives_admis else niveaux.count("CLIENT_PRIVATE"))


def _m10(deps, nom: str, *, origine: str | None = None, **arguments) -> dict:
    with contexte.appeler_en_tant_que(origine):
        reponse = executer_atomique(_outils(deps, "m10-memoire")[nom], arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _compte_des_ecritures() -> tuple[int, int, int]:
    """Événements de M5 publiés, leçons de M10 et faits de M8 : ce qu'un second passage du bus ne doit pas changer."""
    with stockage.transaction():
        faits_m8 = len(list(stockage.maillons("m08-analytics", "faits_chantier")))
    return len(_publies_m5()), len(_m10_rentabilites()), faits_m8


def _drainer_sans_echec(deps, base: dt.datetime) -> dict:
    total = _drainer(deps, base)
    assert total["echecs"] == 0 and total["quarantaines"] == 0, total
    return total


@pytest.mark.parametrize(
    ("quantite_reelle", "facture_finale", "facture_payee", "panne_publication"),
    [(40.0, False, False, False), (56.0, False, False, False),
     (40.0, True, False, False), (40.0, True, True, False), (40.0, True, False, True)],
)
def test_lecture_apprentissage_utilise_la_chaine_reelle_et_exclut_la_facture_brouillon(
    base_durable, monkeypatch, quantite_reelle, facture_finale, facture_payee, panne_publication,
):
    """Le lecteur M3 joint les vrais outils et conserve les gardes de finalité M5/M8. La main-d'oeuvre est chiffrée
    par la voie certifiée (tarif d'équipe M5 sur pointages d'équipe V3), sans taux horaire configuré."""
    deps = charger_departements()
    base = dt.datetime(2026, 9, 16, 7, 0, 0, tzinfo=DT_TZ)
    _m6_prix_au_livre(_outils(deps, "m06-material-control"), 8.0)
    lead_id, devis_id, chantier_id = (
        "LEAD-APPRENTISSAGE-fictif", "DEVIS-APPRENTISSAGE-fictif", "CH-APPRENTISSAGE-fictif",
    )
    wct_id, intervention_id = _chantier_termine(
        deps, base, lead_id, devis_id, chantier_id, quantite_reelle, certifie=True)
    _drainer_sans_echec(deps, base + dt.timedelta(hours=4))
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "admin-apprentissage-fictif", "Admin apprentissage (fictif)",
            "un-mot-de-passe-suffisamment-long", ["admin"],
        )
    if facture_finale:
        # Transition interne fictive via la vraie approbation N4 : aucun transport courriel.
        with stockage.transaction() as cnx:
            identite.creer_personne(
                cnx, "finance-apprentissage-fictif", "Finance (fictif)",
                "un-autre-mot-de-passe-suffisamment-long", ["finance"],
            )
            factures = list(stockage.maillons("m05-financecore", "factures"))
        facture = next(f for f in factures if f.get("devis_id") == devis_id)
        facture_id = facture["facture_id"]
        avant_transition = (_compte_des_ecritures(), factures)
        if panne_publication:
            def _panne(*args):
                raise RuntimeError("panne publication fictive")
            monkeypatch.setattr(m5_outils, "_publier_rentabilite", _panne)
        cap_finance = Capacites({"m05-financecore": deps["m05-financecore"]}, stockage.transaction)
        demande = cap_finance.appeler("m5_envoyer_facture", {
            "facture_id": facture_id, "horodatage": _iso(base, 12000),
        })
        assert demande["statut"] == "en_attente_approbation", demande
        with stockage.transaction() as cnx:
            decision = approbations.decider(
                cnx, demande["demande_id"], True, "finance-apprentissage-fictif",
                outils_executables(deps, stockage.transaction), deps,
            )
        if panne_publication:
            assert decision["statut"] == "echec", decision
            assert decision["reponse"]["ok"] is False
            with stockage.transaction():
                apres_factures = list(stockage.maillons("m05-financecore", "factures"))
            assert (_compte_des_ecritures(), apres_factures) == avant_transition
            return  # La facture reste brouillon; ni trace ni événement partiellement validés.
        assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"], decision
        if facture_payee:
            with stockage.transaction() as cnx:
                identite.creer_personne(
                    cnx, "owner-apprentissage-fictif", "Propriétaire (fictif)",
                    "un-mot-de-passe-owner-suffisamment-long", ["nathan_owner"],
                )
            demande = cap_finance.appeler("m5_enregistrer_paiement_facture", {
                "facture_id": facture_id, "montant_paye": str(facture["montant_apres_taxes"]),
                "approbateur": "Propriétaire (fictif)", "horodatage": _iso(base, 13000),
            })
            assert demande["statut"] == "en_attente_approbation", demande
            with stockage.transaction() as cnx:
                decision = approbations.decider(
                    cnx, demande["demande_id"], True, "owner-apprentissage-fictif",
                    outils_executables(deps, stockage.transaction), deps,
                    attestation={"nom": "CPA (fictif)", "profession": "CPA",
                                 "reference_document": "DEPOT-APPRENTISSAGE-fictif"},
                )
            assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"], decision
        # Rejouer la décision n'exécute ni la transition ni sa publication une seconde fois.
        avant_rejeu = _compte_des_ecritures()
        with stockage.transaction() as cnx, pytest.raises(ValueError, match="déjà traitée"):
            approbations.decider(
                cnx, demande["demande_id"], True,
                "owner-apprentissage-fictif" if facture_payee else "finance-apprentissage-fictif",
                outils_executables(deps, stockage.transaction), deps,
            )
        assert _compte_des_ecritures() == avant_rejeu
        with stockage.transaction():
            assert list(stockage.maillons("m05-financecore", "principal")) == []
        _drainer_sans_echec(deps, base + dt.timedelta(hours=4))

    if quantite_reelle == 40.0:
        # +0 % de matériaux : M4 vérifie seule. M5 republie son coût, APRÈS la facture, sur la projection certifiée
        # (les calculs ordinaires du bus, y compris ceux de la facture, ne voient que la durée scalaire).
        _recalculer_cout_certifie(wct_id, devis_id, f"t15d-apprentissage-{facture_finale}-{facture_payee}")
        _drainer_sans_echec(deps, base + dt.timedelta(hours=5))
    admin = contexte.IdentiteAppelante(
        personne="admin-apprentissage-fictif", role="admin", source="appareil",
    )
    def _instantane_metier():
        noms = (
            ("m03-estimation", "principal"), ("m03-estimation", "devis"),
            ("m03-estimation", "estime_vs_reel"), ("m03-estimation", "calibration_versions"),
            ("m04-field-ops", "principal"), ("m05-financecore", "principal"),
            ("m05-financecore", "rentabilite"), ("m05-financecore", "factures"),
            ("m05-financecore", "devis_recus"), ("m05-financecore", "wct_recus"),
            ("m05-financecore", "variance_recue"), ("m06-material-control", "principal"),
            ("m08-analytics", "faits_chantier"),
        )
        with stockage.transaction() as cnx:
            registres = {f"{dep}/{nom}": list(stockage.maillons(dep, nom)) for dep, nom in noms}
            sorties = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id)).all()
            recus = cnx.execute(select(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.consommateur)).all()
        return registres, sorties, recus

    avant_lecture = _instantane_metier()
    lecture_m5 = (_relecture_m5_sur_projection_certifiee(monkeypatch, wct_id, devis_id)
                  if quantite_reelle == 40.0 else contextlib.nullcontext())
    with lecture_m5:
        capacites_m3 = Capacites(
            {"m03-estimation": deps["m03-estimation"]}, stockage.transaction,
            appelant="m03-estimation", memoire=False,
        )
        with contexte.appele_par_appareil(admin):
            reponse = capacites_m3.appeler("m3_lire_apprentissage_chantier", {
                "wct_id": wct_id, "coupure_utc": "2026-10-05T00:00:00Z",
            })
    apres_lecture = _instantane_metier()

    assert reponse["ok"] is True, reponse
    rapport = reponse["resultat"]
    assert apres_lecture == avant_lecture, "lecture sans mutation des registres métier ou du bus"
    if quantite_reelle == 56.0:
        assert rapport["statut"] == "exclu", rapport
        assert "statut_courant_non_verifie" in rapport["exclusions"]
        assert rapport["cause"] is None
        return
    assert rapport["statut"] == "observee", rapport
    assert rapport["sources"]["wct_id"] == wct_id
    assert rapport["sources"]["devis_id"] == devis_id
    assert len(rapport["sources"]["estimation_hash"]) == 64
    assert len(rapport["sources"]["wct_hash"]) == 64
    assert rapport["sources"]["partition_calibration"] in {"train", "holdout"}
    assert rapport["temps"]["unite"] == "minute"
    assert rapport["temps"]["paie_heures_personnes"] == "non mesurees par ces sources"
    assert rapport["rentabilite"]["verdict_m5"] == "CALCULEE"
    assert rapport["rentabilite"]["cout_reel_complet"] is True
    _prouver_main_d_oeuvre_certifiee(intervention_id, wct_id)  # 40 pi x 8,00 + 100,00 : coût de la voie certifiée
    assert rapport["rentabilite"]["prix_definitif"] is facture_finale
    if facture_finale:
        assert rapport["rentabilite"]["statut"] == "qualifiee", rapport["rentabilite"]
        assert rapport["rentabilite"]["trace_m5_a_jour"] is True
        assert rapport["rentabilite"]["version_entrees_m5"] == rapport["rentabilite"]["version_entrees_m8"]
        assert rapport["rentabilite"]["montant_marge_reelle_cad"] == _publies_m5()[-1]["marge_reelle_cad"]
        assert rapport["rentabilite"]["exclusions"] == []
    else:
        assert rapport["rentabilite"]["statut"] == "exclue"
        assert rapport["rentabilite"]["montant_marge_reelle_cad"] is None
        assert "facture_brouillon_ou_prix_non_definitif" in rapport["rentabilite"]["exclusions"]
    assert rapport["cause"] is None and rapport["variance_materiaux"]["cause"] is None
    assert rapport["coupure_utc"] == "2026-10-05T00:00:00Z"
    assert "snapshot transactionnel commun" in rapport["lecture_intermodules"]
    assert apres_lecture == avant_lecture, "la lecture ne modifie ni les registres métier ni le bus"
    texte = json.dumps(rapport, ensure_ascii=True)
    for interdit in (lead_id, "Client Fictif", TECHNICIEN, "latitude", "longitude"):
        assert interdit not in texte, interdit


# =============================================================================================
# 1. Coût complet : M5 chiffre la marge -> M8 la mesure (et le temps prévu) -> M10 la mémorise
# =============================================================================================
def test_la_marge_reelle_de_m5_atteint_m8_qui_la_mesure_et_m10_qui_la_memorise_sans_la_montrer(
        base_durable, seuils_m8):
    # Aucun taux horaire configuré : seul le tarif d'ÉQUIPE de M5 (50,00 $/h-équipe) chiffre la main-d'oeuvre.
    seuils_m8({"m8_ecart_marge_pct": {"sens": "au_dessous", "valeur": -20}})
    deps = charger_departements()
    base = dt.datetime(2026, 9, 16, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-T15D-M-1-fictif", "DEVIS-T15D-M-1-fictif", "CH-T15D-M-1-fictif"
    _m6_prix_au_livre(_outils(deps, "m06-material-control"), 8.0)
    wct_id, intervention_id = _chantier_termine(
        deps, base, lead_id, devis_id, chantier_id, 56.0, certifie=True)  # prévu 40 : +40 %

    _drainer_sans_echec(deps, base + dt.timedelta(hours=4))
    # +40 % de matériaux : M4 attend une revue HUMAINE ; puis M5 recalcule sur la projection certifiée.
    _m4_revue_humaine_verifiee(deps, intervention_id, base + dt.timedelta(hours=4, minutes=5))
    _recalculer_cout_certifie(wct_id, devis_id, "t15d-scenario-1")
    _drainer_sans_echec(deps, base + dt.timedelta(hours=5))

    # -- M3 : le devis accepté porte la durée estimée de son estimation ----------------------------------
    devis = _charge_publiee("m3.devis_accepte", f"m3-devis-accepte-{devis_id}")
    assert devis["duree_estimee_minutes"] == DUREE_ESTIMEE
    assert (devis["cout_total"], devis["prix_total"]) == ("480.00", "600.00")
    wct = _charge_publiee("m4.travaux_termines", wct_id)
    assert wct["duree_reelle_minutes"] == 120  # de 1 h à 3 h de pointage sur site

    # -- M5 : le coût réel, calculé à la source, puis publié (une fois par version des entrées) -------------
    publies = _publies_m5()
    assert publies, "M5 publie la rentabilité de chaque nouvelle version du coût réel"
    assert [p["sequence"] for p in publies] == list(range(1, len(publies) + 1))
    final = publies[-1]
    assert (final["devis_id"], final["chantier_id"], final["wct_id"]) == (devis_id, chantier_id, wct_id)
    assert final["verdict"] == "CALCULEE" and final["cout_reel_complet"] is True
    # 56 pi x 8,00 $ + 120 min x 50,00 $/h = 448,00 + 100,00
    assert (final["cout_reel_cad"], final["marge_reelle_cad"]) == ("548.00", "52.00")
    assert (final["marge_prevue_cad"], final["ecart_marge_cad"]) == ("120.00", "-68.00")
    assert final["manque"] == []
    for publie in publies[:-1]:  # les versions intermédiaires (pièces arrivées une à une) ne mentent pas non plus
        assert publie["verdict"] == "PARTIELLE" or publie["marge_reelle_cad"] == final["marge_reelle_cad"]
        if publie["verdict"] == "PARTIELLE":
            assert publie["marge_reelle_cad"] is None and publie["ecart_marge_cad"] is None
            # la durée scalaire du WCT (120 min) n'a chiffré aucune main-d'oeuvre dans les calculs ordinaires du bus
            assert "REJ-COUT-TEMPS-POINTE-ABSENT" in publie["manque"], publie["manque"]
    _prouver_main_d_oeuvre_certifiee(intervention_id, wct_id)
    texte_m5 = json.dumps(final)
    for interdit in (MATERIAU_ID, "gentek-fictif", "prix_unitaire", "taux", lead_id, "Client Fictif"):
        assert interdit not in texte_m5, interdit
    assert list(stockage.maillons("m05-financecore", "principal")) == []  # aucune écriture comptable

    # -- M8 : le prix brouillon exclut les marges; temps et matériaux restent calculables --------------------------
    resultat = _mesures_de_m8(deps, wct_id)
    mesures = {m["metric_id"]: m for m in resultat["mesures"]}
    assert final["prix_definitif"] is False
    for metric_id in ("m8_marge_reelle_cad", "m8_ecart_marge_cad", "m8_ecart_marge_pct"):
        assert mesures[metric_id]["statut"] == "non_calculable"
        assert mesures[metric_id]["valeur"] is None
        assert mesures[metric_id]["manque"] == ["marge_reelle_cad"]
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"
    assert mesures["m8_ecart_duree_minutes"]["valeur"] == "30.00"  # 120 réelles - 90 estimées
    assert mesures["m8_ecart_duree_pct"]["valeur"] == "33.33"
    assert mesures["m8_ecart_materiaux_max_pct"]["valeur"] == "40.00"
    assert {m["statut"] for m in mesures.values()} == {"calculee", "non_calculable"}
    (manque_finalite,) = resultat["manques"]
    assert manque_finalite["raison"] == "facture brouillon ou prix non définitif (prix_definitif=false)"
    (fait,) = [f for f in stockage.maillons("m08-analytics", "faits_chantier")
               if f["type_entree"] == "rentabilite" and f["sequence"] == final["sequence"]]
    assert fait["marge_reelle_cad"] == "52.00"

    # -- M8 : seuil configuré (-20 %) franchi -> alerte proposée avec preuve chiffrée ------------------------
    franchis = [a for a in _alertes_publiees() if a["type_alerte"] == "MESURE-SEUIL-FRANCHI"
                and a["metric_id"] == "m8_ecart_marge_pct"]
    assert franchis == []  # un montant provisoire ne justifie aucune alerte de marge réelle

    # -- M10 : l'écart de marge est mémorisé (FINANCIAL), un maillon par version publiée par M5 --------------
    lecons = _m10_rentabilites()
    assert [m["sequence"] for m in lecons] == [p["sequence"] for p in publies]
    derniere = lecons[-1]
    assert derniere["confidentialite"] == "FINANCIAL" and derniere["type_entree"] == "evenement_memorise"
    assert (derniere["marge_reelle_cad"], derniere["ecart_marge_cad"]) == ("52.00", "-68.00")
    assert derniere["wct_id"] == wct_id and derniere["horodatage"] == wct["horodatage_completion"]

    # -- chaque étage a reçu chaque publication de M5, sans échec ni quarantaine ----------------------------------
    for charge in publies:
        for consommateur in ("m08-analytics", "m10-memoire"):
            recu = _recu(charge["evenement_id"], consommateur)
            assert recu is not None and recu["statut"] == "traite", (charge["evenement_id"], consommateur, recu)

    # -- M10 : la marge ne sort dans AUCUN paquet de contexte, pour aucun agent ---------------------------------
    for agent in (None, "m01-front-office", "m02-revenue-crm", "m05-financecore", "m08-analytics"):
        paquet = _m10(
            deps,
            "m10_paquet_contexte_affaire",
            origine=agent,
            affaire_id=lead_id,
            horodatage=_iso(base, 24 * 3600),
        )
        texte = json.dumps(paquet, ensure_ascii=False)
        # Retenues, seulement comptées.
        assert paquet["confidentialite"]["nb_retenus"] == _retenus_attendus(agent), agent
        assert not [m for m in MONTANTS_M5 if m in texte], (agent, texte)
        assert final["evenement_id"] not in texte

    # -- M10 : la consolidation compte, sans montant ; l'audit prouve que rien n'est oublié -------------------------
    jour = _iso(base, 11400)[:10]
    consolide = _m10(deps, "m10_consolider_affaire", affaire_id=lead_id, jour=jour, horodatage=_iso(base, 25 * 3600))
    assert consolide["ecrit"] is True
    assert f"{len(lecons)} rentabilité(s) de chantier" in consolide["fait"]["resume"]
    assert not [m for m in MONTANTS_M5 if m in json.dumps(consolide, ensure_ascii=False)]
    rapport = _m10(deps, "m10_auditer_non_oubli", identifiants_attendus=[
        {"type_evenement": TYPE_M5, "identifiant": final["evenement_id"]},
        {"type_evenement": "m4.travaux_termines", "identifiant": wct_id},
    ])
    assert rapport["nb_oublis"] == 0 and rapport["chaine_evenements_intacte"] is True

    # -- rien de plus n'est publié ni écrit si le bus est repassé --------------------------------------------------
    avant = _compte_des_ecritures()
    assert _drainer_sans_echec(deps, base + dt.timedelta(hours=8))["livres"] == 0
    assert _compte_des_ecritures() == avant


# =============================================================================================
# 2. Coût PARTIEL (l'état de livraison : ni taux ni prix) : aucune marge ne part, M8 dit ce qui manque
# =============================================================================================
def test_un_cout_partiel_ne_porte_aucune_marge_de_m5_a_m8_et_m10_et_le_dit(base_durable, seuils_m8):
    seuils_m8({"m8_ecart_marge_pct": {"sens": "au_dessous", "valeur": -20}})
    assert m5_outils._taux_horaire_configure() is None  # le vrai manifeste de M5 : aucun taux
    deps = charger_departements()
    base = dt.datetime(2026, 9, 19, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-T15D-M-2-fictif", "DEVIS-T15D-M-2-fictif", "CH-T15D-M-2-fictif"
    wct_id, _ = _chantier_termine(deps, base, lead_id, devis_id, chantier_id, 56.0)  # aucun prix au livre de M6

    _drainer_sans_echec(deps, base + dt.timedelta(hours=4))

    # -- M5 : jamais de marge, seulement ce qui manque ---------------------------------------------------------------
    publies = _publies_m5()
    assert publies
    for charge in publies:
        assert charge["verdict"] == "PARTIELLE" and charge["cout_reel_complet"] is False
        assert charge["marge_reelle_cad"] is None and charge["ecart_marge_cad"] is None
        assert charge["cout_reel_cad"] is None
    final = publies[-1]
    assert final["manque"] == [
        "REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TAUX-HORAIRE-A-CONFIGURER", "REJ-COUT-TEMPS-POINTE-ABSENT",
    ]
    assert final["marge_prevue_cad"] == "120.00"  # la marge prévue de M3 reste dite

    # -- M8 : « non calculable, manque marge_reelle_cad », avec la raison de M5 ; le reste est mesuré -----------------
    resultat = _mesures_de_m8(deps, wct_id)
    mesures = {m["metric_id"]: m for m in resultat["mesures"]}
    for metric_id in ("m8_marge_reelle_cad", "m8_ecart_marge_cad", "m8_ecart_marge_pct"):
        assert mesures[metric_id]["statut"] == "non_calculable" and mesures[metric_id]["valeur"] is None
        assert mesures[metric_id]["manque"] == ["marge_reelle_cad"]
    (manque,) = [m for m in resultat["manques"] if m["champ"] == "marge_reelle_cad"]
    assert manque["source"].startswith("M5")
    assert final["prix_definitif"] is False
    assert manque["raison"] == "facture brouillon ou prix non définitif (prix_definitif=false)"
    assert mesures["m8_marge_prevue_cad"]["valeur"] == "120.00"
    assert mesures["m8_ecart_duree_minutes"]["valeur"] == "30.00"  # le temps prévu, lui, est calculé
    assert mesures["m8_ecart_materiaux_max_pct"]["valeur"] == "40.00"
    assert [a for a in _alertes_publiees() if a["metric_id"] == "m8_ecart_marge_pct"] == []  # rien à alerter

    # -- M10 : l'état partiel est mémorisé tel quel, sans aucune marge -------------------------------------------------
    lecons = _m10_rentabilites()
    assert [m["sequence"] for m in lecons] == [p["sequence"] for p in publies]
    assert all(m["marge_reelle_cad"] is None and m["ecart_marge_cad"] is None for m in lecons)
    assert all(m["confidentialite"] == "FINANCIAL" for m in lecons)
    assert lecons[-1]["manque"] == final["manque"]


# =============================================================================================
# 3. Le prix arrive après coup : le partiel est remplacé par l'état complet, à tous les étages
# =============================================================================================
def test_le_prix_ajoute_apres_coup_remplace_le_partiel_par_la_marge_a_tous_les_etages(base_durable, taux_m5):
    taux_m5("50.00")
    deps = charger_departements()
    base = dt.datetime(2026, 9, 22, 7, 0, 0, tzinfo=DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-T15D-M-3-fictif", "DEVIS-T15D-M-3-fictif", "CH-T15D-M-3-fictif"
    wct_id, intervention_id = _chantier_termine(
        deps, base, lead_id, devis_id, chantier_id, 42.0, duree_estimee=None, certifie=True)  # +5 %
    _drainer_sans_echec(deps, base + dt.timedelta(hours=4))
    # Calculs ordinaires du bus : ni prix, ni main-d'oeuvre (la durée scalaire du WCT ne chiffre plus rien).
    ordinaire = _publies_m5()[-1]
    assert ordinaire["verdict"] == "PARTIELLE"
    assert ordinaire["manque"] == ["REJ-COUT-PRIX-NON-DISPONIBLE", "REJ-COUT-TEMPS-POINTE-ABSENT"]

    # La voie certifiée chiffre la main-d'oeuvre (100,00 $) : il ne manque plus que le prix du livre.
    _recalculer_cout_certifie(wct_id, devis_id, "t15d-scenario-3-sans-prix")
    _drainer_sans_echec(deps, base + dt.timedelta(hours=5))
    partiel = _publies_m5()[-1]
    assert partiel["sequence"] == ordinaire["sequence"] + 1
    assert partiel["verdict"] == "PARTIELLE" and partiel["manque"] == ["REJ-COUT-PRIX-NON-DISPONIBLE"]
    avant = {m["metric_id"]: m for m in _mesures_de_m8(deps, wct_id)["mesures"]}
    assert avant["m8_marge_reelle_cad"]["statut"] == "non_calculable"
    assert avant["m8_ecart_duree_pct"]["manque"] == ["duree_estimee_minutes"]  # sans estimation : rien d'inventé

    # M6 saisit le prix ; la facture de M5 change de statut : M5 recalcule sur la projection certifiée.
    _m6_prix_au_livre(_outils(deps, "m06-material-control"), 8.0)
    _recalculer_cout_certifie(wct_id, devis_id, "t15d-scenario-3-avec-prix")
    _drainer_sans_echec(deps, base + dt.timedelta(hours=6))

    complet = _publies_m5()[-1]
    assert complet["sequence"] == partiel["sequence"] + 1 and complet["verdict"] == "CALCULEE"
    assert (complet["cout_reel_cad"], complet["marge_reelle_cad"]) == ("436.00", "164.00")  # 42 x 8,00 + 100,00
    assert complet["ecart_marge_cad"] == "44.00"  # plus que prévu : moins de main-d'oeuvre que le forfait du devis
    _prouver_main_d_oeuvre_certifiee(intervention_id, wct_id, publications=2)
    apres = {m["metric_id"]: m for m in _mesures_de_m8(deps, wct_id)["mesures"]}
    assert complet["prix_definitif"] is False
    for metric_id in ("m8_marge_reelle_cad", "m8_ecart_marge_cad", "m8_ecart_marge_pct"):
        assert apres[metric_id]["statut"] == "non_calculable"
        assert apres[metric_id]["valeur"] is None
    assert apres["m8_ecart_duree_pct"]["manque"] == ["duree_estimee_minutes"]  # la durée reste non calculable
    lecons = _m10_rentabilites()
    assert [(m["sequence"], m["marge_reelle_cad"]) for m in lecons][-2:] == [
        (partiel["sequence"], None), (complet["sequence"], "164.00")]
    # M5/M10 conservent le montant provisoire; M8 conserve le fait sans le présenter comme marge réelle.
    assert complet["marge_reelle_cad"] == "164.00"
    assert apres["m8_marge_reelle_cad"]["valeur"] is None
