"""PLAN T1.5 — E2E « travaux terminés » par la porte d'appareil (DEFINITION-PRODUIT §6, §9.7).

« Travaux terminés normaux ; écart de 40 % -> `completed_pending_review` et alerte sur le mobile de
l'admin. » Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai
chemin réseau du moteur (`tests/fixtures/harnais_e2e.py`) :

- la vraie application HTTP MCP (`application_http_departements`, avec son jeton) sur un vrai uvicorn, une
  base temporaire migrée, les dix départements réels ;
- chaque geste de l'app est un appel de la porte d'appareil du core, refaite en Python d'après le fork
  (`invokeOpsysDeviceTool`) : nom nu autorisé par le rôle, serveur pris dans `roles.json`, session MCP
  privée à ce serveur, `_meta` posé comme `buildOpsysMcpCallMeta`, enveloppe `{ok, resultat|erreur, rejoue}`
  rendue telle quelle ;
- personnes et appareils créés par les commandes réelles du socle (`opsys personnes creer`,
  `opsys appareils appairer`), jamais par une écriture en base ;
- le bus est livré à la main (répartiteur réel, tous les départements), l'horloge du serveur est celle du
  test : aucun sommeil, aucune dépendance à l'heure réelle.

Ce que ces tests ne prouvent PAS : le core lui-même (poignée de main, jeton d'appareil, `mcp.servers`,
session MCP TypeScript) ; il reste à prouver en CI du core ou contre un core réel (MOBILE.md).

Le lead est un LeadQualifie v1 (contrat gelé, `type_travaux`), comme T1.2-e : il ne dépend pas du profil
d'entreprise de T0.13, réservé au contrat v2.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any

import m2_revenue_crm.outils as m2_outils
import m5_financecore.facturation as m5_facturation
import m5_financecore.outils as m5_outils
import pytest
from harnais_e2e import Moteur, Reponse, iso
from harnais_e2e_chantier import (
    FIX_GPS,
    MATERIAU_ID,
    AppEmploye,
    Chantier,
    debut_de_journee,
    preparer_chantier,
    receptionner_materiel_args,
)
from m2_revenue_crm import statuts as m2_statuts
from m6_material_control import registre as m6_registre
from m6_material_control import stock as m6_stock
from sqlalchemy import select

from opsys import approbations, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import (
    APPROBATIONS,
    EVENEMENTS_RECUS,
    EVENEMENTS_SORTANTS,
    JOURNAL,
)

# Les trois scénarios qui portent la preuve (normal, rejeu, écart de 40 %) tournent aussi sur PostgreSQL quand
# docker répond ; les autres, sur SQLite seulement : un conteneur de plus coûterait plus qu'il ne prouve.
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)

LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT` : au-delà, `Capacites` rend un aperçu, pas la réponse

# Gestes N3 de l'employé et de l'admin : chacun s'exécute « au départ » (T1.4-h) et laisse une trace.
GESTES_N3_ATTENDUS = {
    "m4_definir_consentement_gps", "m4_demarrer_route", "m4_pointer", "m4_completer_intervention",
    "m6_declarer_materiaux_utilises",
}


# -- lectures de l'état durable ---------------------------------------------------------------------------
def _recus(evenement_id: str) -> dict[str, str]:
    """Statut de chaque consommateur pour un événement du bus."""
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_RECUS.c.consommateur, EVENEMENTS_RECUS.c.statut).where(
            EVENEMENTS_RECUS.c.evenement_id == evenement_id)).all()
    return {ligne.consommateur: ligne.statut for ligne in lignes}


def _evenements(type_evenement: str) -> list[dict[str, Any]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement).order_by(EVENEMENTS_SORTANTS.c.cree_le)).all()
    return [{"evenement_id": ligne.evenement_id, **codec.decoder(ligne.charge)} for ligne in lignes]


def _statuts_recus_non_traites() -> list[tuple[str, str, str]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.consommateur,
                                    EVENEMENTS_RECUS.c.statut).where(EVENEMENTS_RECUS.c.statut != "traite")).all()
    return [tuple(ligne) for ligne in lignes]


def _facture_active(devis_id: str) -> dict[str, Any] | None:
    with stockage.transaction():
        return m5_facturation.facture_active_pour_devis(m5_outils._registre_factures(None), devis_id)


def _stock_m6(chantier: Chantier) -> float:
    """Stock théorique du matériau sur le chantier, dérivé des mouvements du registre de M6."""
    registre = m6_registre.Registre(maillons=stockage.maillons("m06-material-control", "principal"))
    return m6_stock.deriver_stock_theorique(chantier.chantier_id, MATERIAU_ID, registre)


def _demandes(statut: str | None = None) -> list[dict[str, Any]]:
    with stockage.transaction() as cnx:
        return approbations.lister(cnx, statut)


def _traces_au_depart() -> list[dict[str, Any]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(APPROBATIONS).where(
            APPROBATIONS.c.motif_decision == approbations.MOTIF_VALIDATION_AU_DEPART)).mappings().all()
    return [dict(ligne) for ligne in lignes]


def _entrees_du_journal(action: str) -> list[dict[str, Any]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(JOURNAL).where(JOURNAL.c.action == action)).mappings().all()
    return [dict(ligne) for ligne in lignes]


def _sans_rejoue(enveloppe: dict[str, Any]) -> dict[str, Any]:
    return {cle: valeur for cle, valeur in enveloppe.items() if cle != "rejoue"}


def _attentes_du_telephone(admin) -> dict[str, Any]:
    """Ce que l'écran des approbations de l'admin lit : `m9_lister_demandes_approbation`."""
    return admin.appeler("m9_lister_demandes_approbation", {}).resultat


def _mesure(nom: str, s: _Scenario) -> dict[str, Any]:
    """Mesures du scénario, imprimées (`pytest -s`) : durée, appels, requêtes, troncatures. `trajet` : la
    journée de l'employé et la livraison du bus (l'amont, préparé la veille, n'y est pas) ; `lectures` : ce
    que l'admin lit ensuite ; `amont_s` : la préparation (lead, devis, cédule), hors porte d'appareil."""
    bilan = {
        "scenario": nom,
        "amont_s": round(s.duree_amont_s, 3),
        "trajet": {"duree_s": round(s.duree_trajet_s, 3), **s.moteur.bilan(s.depuis, s.fin_trajet)},
        "lectures": s.moteur.bilan(s.fin_trajet),
    }
    print("MESURE-E2E " + json.dumps(bilan, ensure_ascii=False, default=str))
    return bilan


class _Scenario:
    """Le décor commun : chantier prêt, matériel reçu par l'admin, bus au repos."""

    def __init__(self, moteur: Moteur, equipe: dict[str, Any], suffixe: str, jour: int) -> None:
        self.moteur = moteur
        self.admin = equipe["admin"]
        self.employe = equipe["employe"]
        t0 = time.perf_counter()
        self.chantier = preparer_chantier(moteur.departements, suffixe=suffixe, technicien="etienne",
                                          debut=debut_de_journee(jour))
        moteur.horloge.maintenant = self.chantier.debut
        # Le devis accepté a été publié la veille : le répartiteur de fond l'a livré depuis longtemps (M6 en
        # tire le prévu de matériaux, sans lequel un employé ne peut pas déclarer, T1.4-k1).
        moteur.drainer_bus(moteur.horloge.maintenant)
        self.duree_amont_s = time.perf_counter() - t0
        self.reception = self.admin.appeler(
            "m6_receptionner_commande", receptionner_materiel_args(self.chantier), cle=f"mut-reception-{suffixe}",
            horodatage_appareil=iso(self.chantier.debut))
        assert self.reception.metier["accepte"] is True, self.reception.metier
        self.app = AppEmploye(moteur, self.employe, self.chantier)
        self.depuis = len(moteur.mesures)  # les mesures du trajet commencent au geste de l'employé
        self.fin_trajet = self.depuis
        self.duree_trajet_s = 0.0

    def terminer_puis_declarer(self, quantite: float) -> tuple[Reponse, Reponse]:
        """« Terminer » ; le bus livre la complétion ; l'employé remplit le formulaire de matériaux ; le bus
        livre la variance. C'est l'ordre réel de l'app (la déclaration suit la complétion, §9.7)."""
        debut = time.perf_counter()
        completion = self.app.journee_jusqu_a_la_completion()
        wct_id = completion.resultat["wct_id"]
        self.moteur.drainer_bus(self.moteur.horloge.maintenant)
        self.app.attendre(minutes=5)
        declaration = self.app.declarer_materiaux(wct_id, quantite)
        self.moteur.drainer_bus(self.moteur.horloge.maintenant)
        self.duree_trajet_s = time.perf_counter() - debut
        self.fin_trajet = len(self.moteur.mesures)
        return completion, declaration


@pytest.fixture
def scenario_a(moteur, equipe):
    return _Scenario(moteur, equipe, "A-NORMAL", 15)


@pytest.fixture
def scenario_b(moteur, equipe):
    return _Scenario(moteur, equipe, "B-ECART", 16)


# =============================================================================================
# A. Travaux terminés normaux : écart faible (+5 %), tout se vérifie seul, rien n'attend un humain.
# =============================================================================================
def test_a_travaux_termines_normaux_par_la_porte_d_appareil(moteur, scenario_a):
    s = scenario_a
    ch, app = s.chantier, s.app

    completion, declaration = s.terminer_puis_declarer(42.0)  # prévu 40 : +5 %, sous le seuil de 30 %

    # -- les gestes de l'employé sont tous acceptés, exécutés une fois, sans file d'attente ------------
    assert [a.reponse.statut for a in app.appels] == [200] * len(app.appels)
    for appel in app.appels:
        assert appel.reponse.enveloppe["rejoue"] is False, appel.outil
        assert appel.reponse.metier["accepte"] is True, (appel.outil, appel.reponse.metier)
    assert declaration.metier["accepte"] is True

    # -- l'heure du serveur fait foi (R12 §4) : l'appareil retarde de 5 minutes, le punch date du serveur ---
    arrivee = next(a for a in app.appels if a.outil == "m4_pointer" and a.args["action"] == "arrivee")
    resultat_arrivee = arrivee.reponse.resultat
    assert resultat_arrivee["statut"] == "sur_site" and resultat_arrivee["gps_coherent"] is True
    assert resultat_arrivee["gps_chiffre"] is True  # consentement donné : le fix est gardé, chiffré
    assert resultat_arrivee["horodatage"] == "2026-09-15T12:00:00+00:00"  # 08:00 -04:00, horloge du serveur
    assert resultat_arrivee["horodatage_appareil"] == arrivee.horodatage_appareil != resultat_arrivee["horodatage"]

    # -- aucune approbation en attente pour les gestes de l'employé (T1.4-h) ----------------------------
    assert _demandes("en_attente") == []
    traces = _traces_au_depart()
    assert {t["outil"] for t in traces} == GESTES_N3_ATTENDUS | {"m6_receptionner_commande"}
    assert all(t["statut"] == "executee" and t["niveau"] == "N3" for t in traces)
    assert {t["decide_par"] for t in traces if t["outil"] != "m6_receptionner_commande"} == {"etienne"}
    assert len(_entrees_du_journal("approbation.valider_au_depart")) == len(traces)
    texte_des_traces = "".join(t["arguments"] for t in traces)
    assert str(FIX_GPS["latitude"]) not in texte_des_traces  # la position de l'employé n'entre jamais en clair
    assert str(FIX_GPS["longitude"]) not in texte_des_traces
    assert _attentes_du_telephone(s.admin)["total_en_attente"] == 0  # ce que l'écran de l'admin lit

    # -- le bus : chaque événement est livré et traité, rien en échec ni en quarantaine -------------------
    assert _statuts_recus_non_traites() == []
    wct_id = completion.resultat["wct_id"]
    assert [e["evenement_id"] for e in _evenements("m4.travaux_termines")] == [wct_id]
    consommateurs_wct = {"m02-revenue-crm", "m03-estimation", "m05-financecore", "m06-material-control",
                         "m07-marketing", "m08-analytics", "m10-memoire"}
    assert _recus(wct_id) == dict.fromkeys(consommateurs_wct, "traite")
    variances = _evenements("m6.variance_chantier")
    assert [(v["statut_variance"], v["signal_critique"]) for v in variances] == [
        ("declaration_absente", None), ("evaluee", False)]  # la déclaration suit la complétion (§9.7)
    evaluee = variances[-1]
    assert evaluee["seuil_pourcentage"] == 0.3 and evaluee["chantier_id"] == ch.chantier_id
    assert evaluee["lignes"] == [{
        "materiau": MATERIAU_ID, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": "42.0",
        "ecart_pourcentage": "0.05", "critique": False}]
    assert _recus(evaluee["evenement_id"]) == dict.fromkeys(
        {"m03-estimation", "m04-field-ops", "m05-financecore", "m10-memoire"}, "traite")

    # -- M4 : `completed_verified` (le statut réel du code, calculé par le code, jamais par l'agent) ---
    assert completion.resultat["statut"] == "completed_pending_review"  # l'app le voit d'abord : jamais vérifié seul
    assert app.statut().resultat["statut"] == "completed_verified"

    # -- M6 : les sorties sont écrites, le stock de chantier est ajusté (200 reçus - 42 utilisés) --------
    assert _stock_m6(ch) == 158.0

    # -- M5 : facture brouillon exacte (prix du devis), prête à envoyer, à valider par un humain ---------
    facture = _facture_active(ch.devis_id)
    assert facture is not None and facture["statut"] == "BROUILLON"
    assert facture["facture_id"] == f"fac-{ch.devis_id}" and facture["chantier_id"] == ch.chantier_id
    assert facture["montant_avant_taxes"] == Decimal("600.00")
    assert [t["montant"] for t in facture["taxes"]] == [Decimal("30.00"), Decimal("59.85")]
    assert facture["montant_apres_taxes"] == Decimal("689.85")

    # -- M2 : chantier marqué terminé, activité écrite ; M8, M10, M3 alimentés ---------------------------
    registre_m2 = m2_outils._obtenir_registre()
    assert m2_statuts.statut_courant(registre_m2, ch.lead_id) == "facture"
    assert len([m for m in registre_m2.lire() if m.get("type_entree") == "interaction"
                and m.get("lead_id") == ch.lead_id and m.get("auteur") == "system:m4"]) == 1
    snapshots = list(stockage.maillons("m08-analytics", "snapshots"))
    assert any(m["valeurs"].get("m4_wct_id") == wct_id for m in snapshots)
    memoire = list(stockage.maillons("m10-memoire", "evenements"))
    assert len([m for m in memoire if m.get("wct_id") == wct_id and "duree_reelle_minutes" in m]) == 1
    assert [m["statut_variance"] for m in memoire if m.get("wct_id") == wct_id and "statut_variance" in m
            ] == ["declaration_absente", "evaluee"]
    m3 = {o.nom: o for o in moteur.departements["m03-estimation"].charger_outils()}
    ecarts = executer_atomique(m3["m3_lire_ecarts_estime_reel"], {"devis_id": ch.devis_id})["resultat"]["resultat"]
    assert len(ecarts) == 1 and ecarts[0]["wct_id"] == wct_id and ecarts[0]["materiaux"]["signal_critique"] is False
    # M7 : aucune demande d'avis sans le consentement du client (jamais inventé, Loi 25).
    assert list(stockage.maillons("m07-marketing", "demandes_avis")) == []

    # -- ce que l'admin voit sur son téléphone : la facture à envoyer, aucune alerte d'écart -------------
    telephone = _attentes_du_telephone(s.admin)
    assert [(a["type"], a["id"]) for a in telephone["attentes"]] == [("facture_brouillon", f"fac-{ch.devis_id}")]
    assert "689.85" in telephone["attentes"][0]["resume"]
    assert telephone["attentes_illisibles"] == []
    briefing = s.admin.appeler("m9_produire_briefing_matin", {"maintenant": iso(moteur.horloge.maintenant)})
    decisions = briefing.resultat["sections"]["decisions_en_attente"]["items"]
    assert [i["type"] for i in decisions] == ["facture_brouillon"]
    assert s.admin.appeler("m5_lister_attentes_facturation", {}).resultat == {
        "attentes_devis": [], "attentes_wct_sans_devis_id": []}  # M5 n'attend aucune donnée

    bilan = _mesure("A-normal", s)
    for partie in (bilan["trajet"], bilan["lectures"]):
        assert partie["troncatures"] == [] and partie["octets_max"][0] < LIMITE_TRONCATURE
        # Une session MCP par appel (`opsys-device-mcp-target.ts`) : initialize, initialized, tools/list,
        # tools/call ; six requêtes HTTP (les quatre messages, le flux serveur et la fermeture de session).
        n = partie["appels_app"]
        assert partie["messages_mcp"] == {"initialize": n, "notifications/initialized": n, "tools/list": n,
                                          "tools/call": n}
        assert partie["requetes_http"] == 6 * n
    assert bilan["trajet"]["appels_app"] == len(s.app.appels) + 1  # les gestes, plus l'écran du jour


def test_a_rejouer_chaque_appel_avec_la_meme_cle_ne_change_rien(moteur, scenario_a):
    s = scenario_a
    completion, _ = s.terminer_puis_declarer(42.0)
    appels = [*s.app.appels]
    avant = moteur.empreinte_etat()
    stock_avant = _stock_m6(s.chantier)
    moteur.horloge.avancer(hours=6)  # le renvoi arrive bien plus tard : la réponse enregistrée fait foi

    for appel in appels:
        rejeu = s.app.rejouer(appel)
        assert rejeu.statut == 200, appel.outil
        assert rejeu.enveloppe["rejoue"] is True, appel.outil
        assert _sans_rejoue(rejeu.enveloppe) == _sans_rejoue(appel.reponse.enveloppe), appel.outil
    reception = s.admin.appeler(
        "m6_receptionner_commande", receptionner_materiel_args(s.chantier), cle="mut-reception-A-NORMAL",
        horodatage_appareil=iso(s.chantier.debut))
    assert reception.enveloppe["rejoue"] is True

    assert moteur.empreinte_etat() == avant  # registres, événements, reçus, approbations, journal : identiques
    assert _stock_m6(s.chantier) == stock_avant == 200.0 - 42.0  # la déclaration n'est comptée qu'une fois
    assert len(_evenements("m4.travaux_termines")) == 1
    assert _evenements("m4.travaux_termines")[0]["evenement_id"] == completion.resultat["wct_id"]

    # Une même clé pour AUTRE chose n'est pas un rejeu : refus nommé, rien n'est exécuté.
    arrivee = next(a for a in appels if a.outil == "m4_pointer")
    conflit = s.employe.appeler("m4_pointer", {**arrivee.args, "action": "pause_debut"}, cle=arrivee.cle,
                                horodatage_appareil=arrivee.horodatage_appareil)
    assert conflit.statut == 200 and conflit.enveloppe["ok"] is False
    assert conflit.enveloppe["erreur"] == "mutation_conflit"
    assert moteur.empreinte_etat() == avant


# =============================================================================================
# B. Écart de 40 % : `completed_pending_review` et une alerte que l'admin lit sur son téléphone.
# =============================================================================================
def test_b_ecart_de_quarante_pour_cent_reste_en_revue_et_alerte_l_admin(moteur, scenario_b, equipe):
    s = scenario_b
    ch, app = s.chantier, s.app

    completion, declaration = s.terminer_puis_declarer(56.0)  # prévu 40 : +40 %, seuil de 30 %
    wct_id = completion.resultat["wct_id"]

    # -- la déclaration est reçue telle quelle : le fait terrain est enregistré, jamais corrigé --------------
    assert declaration.metier["accepte"] is True
    assert _stock_m6(ch) == 200.0 - 56.0  # le stock suit ce qui a réellement été utilisé

    # -- M6 signale l'écart critique ; M4 ne vérifie pas : la complétion reste en revue -------------------
    assert _statuts_recus_non_traites() == []
    evaluee = _evenements("m6.variance_chantier")[-1]
    assert (evaluee["statut_variance"], evaluee["signal_critique"], evaluee["seuil_pourcentage"]) == (
        "evaluee", True, 0.3)
    assert evaluee["lignes"] == [{
        "materiau": MATERIAU_ID, "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": "56.0",
        "ecart_pourcentage": "0.4", "critique": True}]
    assert _recus(evaluee["evenement_id"])["m04-field-ops"] == "traite"  # M4 l'a lu et a choisi de ne pas vérifier
    assert app.statut().resultat["statut"] == "completed_pending_review"

    # -- M5 facture quand même en brouillon (le prix du devis ne dépend pas de la variance) --------------
    facture = _facture_active(ch.devis_id)
    assert facture is not None and facture["statut"] == "BROUILLON"
    assert facture["montant_apres_taxes"] == Decimal("689.85")

    # -- l'alerte : elle est dans la file du propriétaire, ET l'admin la lit par l'outil de son app -------
    telephone = _attentes_du_telephone(s.admin)
    # Les noms de clés que lit l'app (`mobile/src/approbations/contrat.ts`) : le contrat, épinglé des deux côtés.
    assert set(telephone) == {
        "demandes", "total_en_attente", "affichees", "reste", "proprietaire",
        "attentes", "total_attentes", "attentes_affichees", "attentes_reste", "attentes_illisibles"}
    assert all(set(a) == {"type", "id", "departement", "departement_nom", "resume", "niveau", "depuis",
                          "action_proposee"} for a in telephone["attentes"])
    par_type = {a["type"]: a for a in telephone["attentes"]}
    assert set(par_type) == {"completion_en_revue", "facture_brouillon", "chantier_a_reviser"}
    en_revue = par_type["completion_en_revue"]
    assert en_revue["id"] == ch.intervention_id and en_revue["departement"] == "m04-field-ops"
    assert en_revue["niveau"] == "N4" and "écart matériaux CRITIQUE signalé par M6" in en_revue["resume"]
    assert "m4_resoudre_revue_completion" in en_revue["action_proposee"]
    a_reviser = par_type["chantier_a_reviser"]
    assert a_reviser["id"] == f"variance-{wct_id}" and a_reviser["departement"] == "m05-financecore"
    assert "Écart matériaux critique" in a_reviser["resume"] and ch.chantier_id in a_reviser["resume"]
    assert (telephone["total_attentes"], telephone["attentes_affichees"], telephone["attentes_reste"]) == (3, 3, 0)
    assert telephone["attentes_illisibles"] == [] and telephone["total_en_attente"] == 0
    # Le briefing du matin de M9 (aussi de portée admin) porte les mêmes trois décisions.
    briefing = s.admin.appeler("m9_produire_briefing_matin", {"maintenant": iso(moteur.horloge.maintenant)})
    decisions = briefing.resultat["sections"]["decisions_en_attente"]["items"]
    assert {i["type"] for i in decisions} == set(par_type)
    # M5 : « rien n'attend une donnée » (`m5_lister_attentes_facturation`) ne dit rien de l'écart, et ne doit pas.
    assert s.admin.appeler("m5_lister_attentes_facturation", {}).resultat == {
        "attentes_devis": [], "attentes_wct_sans_devis_id": []}

    # -- les portées : l'employé ne voit ni la file ni le briefing (roles_appareil, ROLES.md) ---------------
    for outil, args in (("m9_lister_demandes_approbation", {}),
                        ("m9_produire_briefing_matin", {"maintenant": iso(moteur.horloge.maintenant)})):
        refus = s.employe.appeler(outil, args)
        assert refus.statut == 403 and refus.corps["error"]["type"] == "tool_call_blocked", outil
        assert "tool_out_of_scope" in refus.corps["error"]["message"]

    bilan = _mesure("B-ecart-40", s)
    for partie in (bilan["trajet"], bilan["lectures"]):
        assert partie["troncatures"] == [] and partie["octets_max"][0] < LIMITE_TRONCATURE


@SQLITE_SEULEMENT
def test_b_avant_la_declaration_l_admin_voit_une_revue_dont_la_variance_n_est_pas_finalisee(moteur, scenario_b):
    """Entre « Terminer » et le formulaire de matériaux, la complétion est déjà en revue (jamais vérifiée seule) :
    l'admin le voit, et la file dit que la variance de M6 n'est pas encore là. Ce n'est PAS l'alerte d'écart."""
    s = scenario_b
    s.app.journee_jusqu_a_la_completion()
    moteur.drainer_bus(moteur.horloge.maintenant)

    telephone = _attentes_du_telephone(s.admin)

    par_type = {a["type"]: a for a in telephone["attentes"]}
    assert set(par_type) == {"completion_en_revue", "facture_brouillon"}  # pas encore de chantier à réviser
    assert "variance M6 non finalisée (declaration_absente)" in par_type["completion_en_revue"]["resume"]
    assert "CRITIQUE" not in par_type["completion_en_revue"]["resume"]
    assert _evenements("m6.variance_chantier")[-1]["statut_variance"] == "declaration_absente"


@SQLITE_SEULEMENT
def test_b_un_admin_qui_n_est_pas_le_proprietaire_voit_l_alerte_sans_pouvoir_decider(
    moteur, scenario_b, monkeypatch
):
    s = scenario_b
    moteur.creer_personne("sophie", "Sophie Gagnon (fictif)", ["admin", "manager"], monkeypatch)
    gestionnaire = moteur.appairer("sophie", "admin")
    s.terminer_puis_declarer(56.0)

    telephone = gestionnaire.appeler("m9_lister_demandes_approbation", {}).resultat

    assert telephone["proprietaire"] is False
    assert {a["type"] for a in telephone["attentes"]} == {
        "completion_en_revue", "facture_brouillon", "chantier_a_reviser"}
    assert all("arguments" not in a and "decidable" not in a for a in telephone["attentes"])


@SQLITE_SEULEMENT
def test_b_l_admin_traite_l_alerte_depuis_son_telephone_et_la_completion_est_verifiee(moteur, scenario_b):
    """La boucle jusqu'au bout : alerte lue -> revue de la complétion (N4) -> décision signée du propriétaire
    -> `completed_verified`, et l'alerte quitte la file (T1.3-b)."""
    s = scenario_b
    ch = s.chantier
    s.terminer_puis_declarer(56.0)
    avant = _attentes_du_telephone(s.admin)
    assert "completion_en_revue" in {a["type"] for a in avant["attentes"]}

    demande = s.admin.appeler("m4_resoudre_revue_completion", {
        "intervention_id": ch.intervention_id, "decision": "verifiee", "horodatage": iso(moteur.horloge.maintenant),
        "motif": "Bris de 16 pi constaté sur place et photographié : l'écart est expliqué (fictif)."},
        cle="mut-revue-B", horodatage_appareil=iso(moteur.horloge.maintenant))
    # N4 : jamais exécuté au départ, même par un admin ; la demande attend le propriétaire.
    assert demande.enveloppe["statut"] == "en_attente_approbation"
    assert s.app.statut().resultat["statut"] == "completed_pending_review"
    file = _attentes_du_telephone(s.admin)
    (en_attente,) = file["demandes"]
    assert en_attente["outil"] == "m4_resoudre_revue_completion" and en_attente["decidable"] is True
    assert en_attente["niveau"] == "N4" and en_attente["arguments"]["intervention_id"] == ch.intervention_id

    decision = s.admin.appeler("m9_decider_demande_approbation", {
        "demande_id": en_attente["id"], "decision": "approuver", "motif": "Confirmé (fictif)."},
        cle="mut-decision-B", horodatage_appareil=iso(moteur.horloge.maintenant))

    assert decision.metier["accepte"] is True
    assert (decision.resultat["statut"], decision.resultat["decide_par"], decision.resultat["role"]) == (
        "executee", "nathan", "nathan_owner")
    assert decision.resultat["issue"]["accepte"] is True
    assert s.app.statut().resultat["statut"] == "completed_verified"
    apres = _attentes_du_telephone(s.admin)
    assert "completion_en_revue" not in {a["type"] for a in apres["attentes"]}
    assert apres["total_en_attente"] == 0


# =============================================================================================
# Refus de la porte : rien n'atteint le moteur hors de la portée du rôle.
# =============================================================================================
@SQLITE_SEULEMENT
def test_la_porte_refuse_ce_que_le_role_ne_permet_pas_avant_d_atteindre_le_moteur(moteur, equipe):
    avant = moteur.empreinte_etat()
    mesures_avant = len(moteur.mesures)

    interdits = (
        ("employe", "m6_receptionner_commande", {}),  # outil de l'admin
        ("employe", "m4_lire_outbox", {}),  # WCT de tous les techniciens : fermé à tous les appareils
        ("admin", "m4_lire_outbox", {}),
        ("employe", "opsys_lire_artefact", {"id": "x"}),  # outil commun : jamais pour un appareil
        ("admin", "m5_marquer_facture_payee", {}),  # inconnu de la portée
    )
    for qui, outil, args in interdits:
        reponse = equipe[qui].appeler(outil, args, cle="mut-refus")
        assert reponse.statut == 403 and reponse.ok is False, (qui, outil)
        assert reponse.mesure.requetes_http == 0  # aucun appel au moteur : refusé par la portée du rôle

    inconnu = moteur.invoquer("f" * 64, "m4_pointer", {}, "mut-refus", None)  # appareil jamais appairé
    assert inconnu.statut == 403 and "device_unknown" in inconnu.corps["error"]["message"]
    assert moteur.empreinte_etat() == avant
    assert all(m.requetes_http == 0 for m in moteur.mesures[mesures_avant:])
