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
d'entreprise de T0.13, réservé au contrat v2. Un scénario (`scenario_v2`) refait le trajet avec un lead v2
(`service`), pour prouver que M4 et ses sept consommateurs le prennent comme le v1 (T0.13-b).

PLAN T1.5-d (M6, stock bas) : la cascade « travaux terminés » ne s'arrête pas à la variance. Quand la
déclaration de matériaux sort du stock, M6 évalue chaque article touché contre SON seuil de
réapprovisionnement (`department.yaml/configuration/reapprovisionnement`, remplacé ici par `reappro`) : sous
le seuil, un besoin de commande dans la file de l'admin (C et E) ; sans seuil, un signal « seuil non
configuré » (D). Jamais un bon de commande créé seul. A et B, eux, configurent un seuil que le stock ne
franchit pas : M6 n'a rien à dire, et les assertions d'origine tiennent.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from decimal import Decimal
from typing import Any

import m2_revenue_crm.outils as m2_outils
import m5_financecore.facturation as m5_facturation
import m5_financecore.outils as m5_outils
import m6_material_control.outils as m6_outils
import pytest
import yaml
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
from m4_field_ops import encodage as m4_encodage
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


# Seuil que le stock de A (158) et de B (144) ne franchit pas : M6 n'a rien à signaler.
SEUIL_CONFORTABLE = {MATERIAU_ID: {"seuil_reapprovisionnement": 100, "quantite_cible": 300}}
# Seuil que le stock d'un chantier terminé sans histoire (158) franchit : 200 reçus - 42 utilisés < 160.
SEUIL_FRANCHI_PAR_A = {MATERIAU_ID: {"seuil_reapprovisionnement": 160, "quantite_cible": 300}}
# Seuil que le stock de B (144, écart de 40 %) franchit aussi.
SEUIL_FRANCHI_PAR_B = {MATERIAU_ID: {"seuil_reapprovisionnement": 150, "quantite_cible": 300}}


@pytest.fixture
def reappro(monkeypatch, tmp_path):
    """Le `department.yaml` de M6 dont seul le bloc de réapprovisionnement change (`articles`) : M6 le relit à
    chaque appel, donc un test peut le renseigner en cours de route, comme Nathan le ferait. Le moteur tourne
    dans ce processus : le même module `m6_material_control.outils` sert le test et le serveur."""
    reel = yaml.safe_load(m6_outils._MANIFESTE.read_text(encoding="utf-8"))

    def configurer(articles: dict[str, Any]) -> None:
        manifeste = {**reel, "configuration": {**reel["configuration"], "reapprovisionnement": {"articles": articles}}}
        chemin = tmp_path / "department-m6-e2e.yaml"
        chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8")
        monkeypatch.setattr(m6_outils, "_MANIFESTE", chemin)

    return configurer


def _registre_m6(nom: str) -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons("m06-material-control", nom))


class _Scenario:
    """Le décor commun : chantier prêt, matériel reçu par l'admin, bus au repos."""

    def __init__(self, moteur: Moteur, equipe: dict[str, Any], suffixe: str, jour: int,
                 version_lead: int = 1) -> None:
        self.moteur = moteur
        self.admin = equipe["admin"]
        self.employe = equipe["employe"]
        t0 = time.perf_counter()
        self.chantier = preparer_chantier(moteur.departements, suffixe=suffixe, technicien="etienne",
                                          debut=debut_de_journee(jour), version_lead=version_lead)
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
def scenario_a(moteur, equipe, reappro):
    reappro(SEUIL_CONFORTABLE)
    return _Scenario(moteur, equipe, "A-NORMAL", 15)


@pytest.fixture
def scenario_b(moteur, equipe, reappro):
    reappro(SEUIL_CONFORTABLE)
    return _Scenario(moteur, equipe, "B-ECART", 16)


@pytest.fixture
def scenario_c(moteur, equipe, reappro):
    reappro(SEUIL_FRANCHI_PAR_A)
    return _Scenario(moteur, equipe, "C-STOCK-BAS", 17)


@pytest.fixture
def scenario_d(moteur, equipe, reappro):
    reappro({})  # l'état réel du manifeste : aucun article n'a de seuil
    return _Scenario(moteur, equipe, "D-SANS-SEUIL", 18)


@pytest.fixture
def scenario_e(moteur, equipe, reappro):
    reappro(SEUIL_FRANCHI_PAR_B)
    return _Scenario(moteur, equipe, "E-ECART-ET-STOCK-BAS", 21)


@pytest.fixture
def scenario_v2(moteur, equipe, declarer_services, reappro):
    """Comme A, mais le lead est un LeadQualifie v2 (`service`, PLAN T0.13-b) : le profil d'entreprise de
    l'instance déclare les services du catalogue de référence."""
    declarer_services()
    reappro(SEUIL_CONFORTABLE)  # comme A : un seuil que le stock ne franchit pas (T1.5-d)
    return _Scenario(moteur, equipe, "V2-SERVICE", 22, version_lead=2)


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

    # -- T1.5-c : « Terminer » est daté comme le punch, par l'heure du serveur, jamais par le téléphone ---
    terminer = next(a for a in app.appels if a.outil == "m4_completer_intervention")
    recu_le = (dt.datetime.fromisoformat(terminer.horodatage_appareil)
               - dt.timedelta(seconds=app.derive_appareil_s)).astimezone(dt.UTC)  # le serveur date en UTC
    assert terminer.args["horodatage"] == terminer.horodatage_appareil != recu_le.isoformat()  # l'app envoie SON heure
    accuse_completion = completion.resultat
    assert accuse_completion["horodatage_appareil"] == terminer.horodatage_appareil  # lue à côté, jamais utilisée
    assert accuse_completion["wct_id"] == m4_encodage.empreinte("wct", ch.intervention_id, recu_le.isoformat())
    # Aucun écart n'était connu de M4 : `ecart_signale` ne vaut plus vrai par précaution ; la complétion reste
    # pourtant à vérifier (les matériaux ne sont pas encore comparés au prévu), par son statut.
    assert accuse_completion["ecart_signale"] is False
    assert accuse_completion["statut"] == "completed_pending_review"

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
    assert [(e["ecart_signale"], e["statut"], e["type_travaux"]) for e in _evenements("m4.travaux_termines")] == [
        (False, "completed_pending_review", "renovation_totale")]  # lead v1 : `type_travaux`, jamais `service`
    assert all("service" not in e for e in _evenements("m4.travaux_termines"))
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
    # Au-dessus du seuil de l'article (100) : M6 n'a rien à signaler (T1.5-d), ni constat ni attente.
    assert _registre_m6("besoins_commande") == []

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


@SQLITE_SEULEMENT
def test_v2_un_lead_de_service_traverse_la_porte_d_appareil_jusqu_a_completed_verified(moteur, scenario_v2):
    """PLAN T0.13-b : un lead v2 (`service`) est inscrit par M4, planifié, terminé par l'employé ; le WCT porte
    `service` et jamais `type_travaux`, et les sept consommateurs le traitent comme celui d'un lead v1."""
    s = scenario_v2
    ch, app = s.chantier, s.app

    # L'écran « chantiers du jour » de l'employé : la nature des travaux est le `service`, sans `type_travaux`.
    (du_jour,) = app.chantiers_du_jour().resultat
    assert du_jour["intervention_id"] == ch.intervention_id
    assert du_jour["service"] == "gouttieres" and "type_travaux" not in du_jour

    completion, declaration = s.terminer_puis_declarer(42.0)  # prévu 40 : +5 %

    assert declaration.metier["accepte"] is True
    (publie,) = _evenements("m4.travaux_termines")
    assert (publie["service"], publie["statut"], publie["ecart_signale"]) == (
        "gouttieres", "completed_pending_review", False)
    assert "type_travaux" not in publie
    assert _statuts_recus_non_traites() == []
    consommateurs_wct = {"m02-revenue-crm", "m03-estimation", "m05-financecore", "m06-material-control",
                         "m07-marketing", "m08-analytics", "m10-memoire"}
    assert _recus(completion.resultat["wct_id"]) == dict.fromkeys(consommateurs_wct, "traite")
    assert app.statut().resultat["statut"] == "completed_verified"
    facture = _facture_active(ch.devis_id)
    assert facture is not None and facture["statut"] == "BROUILLON"
    assert _stock_m6(ch) == 158.0


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
    assert "m4_resoudre_revue_completion" in en_revue["action_proposee"] and "verifiee" in en_revue["action_proposee"]
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
    """T1.5-c, décision écrite dans `outils.attentes()` : entre « Terminer » et le formulaire de matériaux, la
    complétion est déjà `completed_pending_review` (§6 : le matériel utilisé manque) et l'admin le voit : c'est
    une information juste, pas du bruit. Mais ce n'est ni l'alerte d'écart ni une revue à trancher : la file dit
    qu'on attend le formulaire de l'employé, qu'aucun écart n'est signalé, et n'offre pas de « verifiee »
    (qui court-circuiterait la comparaison de M6)."""
    s = scenario_b
    s.app.journee_jusqu_a_la_completion()
    moteur.drainer_bus(moteur.horloge.maintenant)

    telephone = _attentes_du_telephone(s.admin)

    par_type = {a["type"]: a for a in telephone["attentes"]}
    assert set(par_type) == {"completion_en_revue", "facture_brouillon"}  # pas encore de chantier à réviser
    en_revue = par_type["completion_en_revue"]
    assert "variance M6 non finalisée (declaration_absente)" in en_revue["resume"]
    assert "formulaire des matériaux de l'employé attendu, aucun écart signalé" in en_revue["resume"]
    assert "CRITIQUE" not in en_revue["resume"]
    assert en_revue["action_proposee"].startswith("Rien à décider")
    assert "verifiee" not in en_revue["action_proposee"]
    assert _evenements("m6.variance_chantier")[-1]["statut_variance"] == "declaration_absente"
    assert [e["ecart_signale"] for e in _evenements("m4.travaux_termines")] == [False]


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
# C, D, E. Stock bas à « travaux terminés » (PLAN T1.5-d, DEFINITION-PRODUIT §6, ligne M6).
# =============================================================================================
def _constat_du_besoin(chantier: Chantier, wct_id: str) -> dict[str, Any]:
    (constat,) = _registre_m6("besoins_commande")
    assert constat["evenement_declencheur"] == wct_id and constat["chantier_id"] == chantier.chantier_id
    assert constat["materiau_id"] == MATERIAU_ID and constat["unite"] == "pi"
    return constat


def _rien_de_commande_n_a_ete_cree() -> None:
    """Constater un besoin n'est pas acheter : aucun bon de commande, fournisseur ni prix, aucune demande
    d'approbation (un PO reste un brouillon demandé, puis approuvé, T2.4)."""
    for registre in ("bons_commande", "fournisseurs", "livre_prix"):
        assert _registre_m6(registre) == [], registre
    assert _demandes("en_attente") == []
    assert not {d["outil"] for d in _demandes()} & {"m6_creer_po_brouillon", "m6_approuver_po", "m6_marquer_po_envoye"}


def test_c_stock_sous_le_seuil_l_admin_voit_le_besoin_de_commande_sans_bon_de_commande(moteur, scenario_c):
    s = scenario_c
    ch = s.chantier

    completion, declaration = s.terminer_puis_declarer(42.0)  # +5 % : chantier normal ; stock 158 < seuil 160
    wct_id = completion.resultat["wct_id"]

    # -- le chantier normal reste normal : le stock bas est un autre signal, il ne bloque rien ----------------
    assert declaration.metier["accepte"] is True and _stock_m6(ch) == 158.0
    assert s.app.statut().resultat["statut"] == "completed_verified"
    assert _statuts_recus_non_traites() == []
    assert "seuil" not in json.dumps(declaration.resultat) and "besoin" not in json.dumps(declaration.resultat)

    # -- le besoin est un fait du registre de M6, calculé par le code : cible 300 - stock 158 -----------------
    constat = _constat_du_besoin(ch, wct_id)
    assert constat["type_entree"] == "besoin_commande" and constat["stock_negatif"] is False
    assert (constat["stock_theorique"], constat["seuil_reapprovisionnement"], constat["quantite_cible"],
            constat["quantite_a_commander"]) == ("158.0", "160", "300", "142.0")
    assert constat["horodatage"] == _evenements("m4.travaux_termines")[0]["horodatage_completion"]
    _rien_de_commande_n_a_ete_cree()

    # -- l'admin le lit là où son app lit déjà ses alertes (section « À voir ») -----------------------------
    telephone = _attentes_du_telephone(s.admin)
    par_type = {a["type"]: a for a in telephone["attentes"]}
    assert set(par_type) == {"facture_brouillon", "besoin_commande"}  # ni écart, ni revue : le chantier est vérifié
    assert all(set(a) == {"type", "id", "departement", "departement_nom", "resume", "niveau", "depuis",
                          "action_proposee"} for a in telephone["attentes"])
    besoin = par_type["besoin_commande"]
    assert besoin["departement"] == "m06-material-control" and besoin["niveau"] == "N2"
    assert besoin["id"] == f"besoin_commande:{MATERIAU_ID}"
    assert besoin["depuis"] == constat["horodatage"]
    assert besoin["resume"] == (
        f"Stock bas : {MATERIAU_ID} — 158.0 pi en main, sous le seuil de 160 pi ; besoin de commande : "
        f"142.0 pi pour atteindre 300 pi (chantier {ch.chantier_id})")
    assert "jamais seul" in besoin["action_proposee"]
    assert (telephone["total_attentes"], telephone["attentes_affichees"], telephone["attentes_reste"]) == (2, 2, 0)
    assert telephone["attentes_illisibles"] == [] and telephone["total_en_attente"] == 0
    briefing = s.admin.appeler("m9_produire_briefing_matin", {"maintenant": iso(moteur.horloge.maintenant)})
    assert {i["type"] for i in briefing.resultat["sections"]["decisions_en_attente"]["items"]} == set(par_type)

    # -- l'employé ne le voit pas (portée du rôle) --------------------------------------------------------
    refus = s.employe.appeler("m9_lister_demandes_approbation", {})
    assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"]

    # -- l'admin réapprovisionne (réception au dépôt) : le stock d'aujourd'hui fait foi, le besoin s'efface ---
    args = receptionner_materiel_args(ch, quantite=200.0)
    for cle in ("bon_demande", "reception_po"):
        args[cle] = {**args[cle], "po_id": f"PO-DEPOT-{ch.devis_id}", "chantier_id": "DEPOT-C-fictif"}
    reception = s.admin.appeler("m6_receptionner_commande", args, cle="mut-reception-depot-C",
                                horodatage_appareil=iso(moteur.horloge.maintenant))
    assert reception.metier["accepte"] is True
    apres = _attentes_du_telephone(s.admin)
    assert [a["type"] for a in apres["attentes"]] == ["facture_brouillon"]
    assert _constat_du_besoin(ch, wct_id) == constat  # le constat, lui, ne s'efface pas (audit)
    assert _registre_m6("bons_commande") == []


@SQLITE_SEULEMENT
def test_d_sans_seuil_configure_l_admin_voit_un_signal_a_configurer_puis_le_besoin(moteur, scenario_d, reappro):
    s = scenario_d
    ch = s.chantier

    completion, _ = s.terminer_puis_declarer(42.0)  # le manifeste réel : aucun article n'a de seuil
    wct_id = completion.resultat["wct_id"]

    # -- M6 ne devine pas de seuil : un constat « seuil non configuré », aucun nombre de stock bas ---------------
    assert s.app.statut().resultat["statut"] == "completed_verified"  # l'employé n'est jamais bloqué
    constat = _constat_du_besoin(ch, wct_id)
    assert (constat["type_entree"], constat["motif"], constat["code"]) == ("seuil_a_configurer", "seuil_absent", None)
    assert "seuil_reapprovisionnement" not in constat and "quantite_a_commander" not in constat
    _rien_de_commande_n_a_ete_cree()

    telephone = _attentes_du_telephone(s.admin)
    par_type = {a["type"]: a for a in telephone["attentes"]}
    assert set(par_type) == {"facture_brouillon", "seuil_a_configurer"}
    a_configurer = par_type["seuil_a_configurer"]
    assert a_configurer["departement"] == "m06-material-control" and a_configurer["id"] == "seuils-reapprovisionnement"
    assert a_configurer["resume"] == (
        f"Seuil de réapprovisionnement non configuré : {MATERIAU_ID}. Le stock bas de cet article n'est pas évalué.")
    assert "department.yaml" in a_configurer["action_proposee"] and "quantite_cible" in a_configurer["action_proposee"]
    assert telephone["attentes_illisibles"] == []

    # -- Nathan renseigne le seuil : l'attente est recalculée, elle devient le besoin de commande -----------------
    reappro(SEUIL_FRANCHI_PAR_A)
    apres = _attentes_du_telephone(s.admin)
    par_type = {a["type"]: a for a in apres["attentes"]}
    assert set(par_type) == {"facture_brouillon", "besoin_commande"}
    assert "142.0 pi pour atteindre 300 pi" in par_type["besoin_commande"]["resume"]
    assert len(_registre_m6("besoins_commande")) == 1  # lire les attentes n'écrit rien
    _rien_de_commande_n_a_ete_cree()


@SQLITE_SEULEMENT
def test_e_ecart_de_quarante_pour_cent_et_stock_bas_quatre_alertes_dont_le_telephone_compte_ce_qu_il_coupe(
    moteur, scenario_e
):
    """Le cas de §6 : l'écart est important ET le stock est bas. La file du propriétaire (console) et le briefing
    du matin portent les quatre alertes ; la complétion reste en revue (M4) et le besoin n'y change rien.
    Constat de cette mesure : la liste de l'app (`m9_lister_demandes_approbation`) borne les attentes à
    `BUDGET_ATTENTES` (1500 caractères) et n'en pagine aucune ; les trois premières y tiennent, la quatrième est
    COMPTÉE (`attentes_reste`), jamais perdue en silence, mais l'admin ne la lit pas sur cet écran."""
    s = scenario_e
    ch = s.chantier

    completion, _ = s.terminer_puis_declarer(56.0)  # +40 % ; stock 144 < seuil 150
    wct_id = completion.resultat["wct_id"]

    assert s.app.statut().resultat["statut"] == "completed_pending_review"
    assert _constat_du_besoin(ch, wct_id)["quantite_a_commander"] == "156.0"
    _rien_de_commande_n_a_ete_cree()
    tous = {"completion_en_revue", "facture_brouillon", "chantier_a_reviser", "besoin_commande"}

    # -- la file du propriétaire (console) et le briefing du matin de M9 : les quatre ------------------------------
    with stockage.transaction() as cnx:
        file, illisibles = approbations.attentes_departements(cnx, moteur.departements)
    assert illisibles == [] and {a["type"] for a in file} == tous
    (besoin,) = (a for a in file if a["type"] == "besoin_commande")
    assert besoin["departement"] == "m06-material-control" and "156.0 pi pour atteindre 300 pi" in besoin["resume"]
    briefing = s.admin.appeler("m9_produire_briefing_matin", {"maintenant": iso(moteur.horloge.maintenant)})
    assert {i["type"] for i in briefing.resultat["sections"]["decisions_en_attente"]["items"]} == tous

    # -- la liste de l'app : bornée, mais honnête sur ce qu'elle ne montre pas -----------------------------------
    telephone = _attentes_du_telephone(s.admin)
    montrees = {a["type"] for a in telephone["attentes"]}
    assert montrees <= tous and telephone["total_attentes"] == 4
    assert telephone["attentes_affichees"] + telephone["attentes_reste"] == 4
    assert telephone["attentes_illisibles"] == []


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
