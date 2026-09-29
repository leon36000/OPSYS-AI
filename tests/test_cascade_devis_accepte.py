"""PLAN T4.10 — « soumission acceptée -> M4 planifie » par le VRAI bus (DEFINITION-PRODUIT §6, flux principal).

Le trajet, sans réseau ni core (le core ne s'exécute pas ici) :

    SMS du client -> `m1_recevoir_message_canal` (vrai M1) -> `m1.lead_qualifie` -> M2 ingère le lead
    -> M2 qualifie (propriétaire, prochaine action) -> M3 crée le devis, un humain le marque accepté (T3)
    -> `m3.devis_accepte` -> `evenements.repartir` sur TOUS les départements :
         M2  `qualifie -> converti` (référence du devis, prochaine action « planifier le chantier », activité)
         M4  une intervention `a_planifier`, service et ville relus à la source du bus (`m1.lead_qualifie`)
         M5, M6, M8  comme avant (le devis reçu, le prévu de matériaux, le fait mesurable)

Vrais départements (`charger_departements`), vrais outils (`Capacites` pour M1, `executer_atomique` pour le reste),
vrai répartiteur, base SQLite migrée. Aucun département n'importe un autre : M4 lit le lead à la source du bus.
Données fictives (`fictif: true` au sens d'AGENTS.md : personnes, numéro, montants et matériaux de test).
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from m1_front_office import outils as m1_outils
from m2_revenue_crm import clients as m2_clients
from m2_revenue_crm import outils as m2_outils
from m2_revenue_crm import statuts as m2_statuts
from sqlalchemy import func, select

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import Departement, charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

DEBUT = dt.datetime(2026, 9, 29, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
NUMERO = "+15145550142"
RECU_LE = "2026-09-29T09:15:00-04:00"
SMS = {
    "canal": "sms", "expediteur": NUMERO, "message_id": "SMfictif0410", "recu_le": RECU_LE,
    "texte": "Bonjour, mes gouttières fuient à Laval, c'est urgent.",
}
ACCEPTE_LE = "2026-09-30T10:00:00-04:00"
MATERIAU_ID = "gouttiere-alu-5po-fictif"
M2, M3, M4 = "m02-revenue-crm", "m03-estimation", "m04-field-ops"
CONSOMMATEURS = ("m02-revenue-crm", "m04-field-ops", "m05-financecore", "m06-material-control", "m08-analytics")


def _departements() -> dict[str, Departement]:
    return charger_departements()


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    # Ces deux modules gardent un état de processus (registre durable ou mémoire) : un test qui les a laissés en
    # mémoire les rendrait muets ici (M1 ne publierait plus `m1.lead_qualifie`). On les remet sur le durable.
    m1_outils.utiliser_stockage_durable()
    m2_outils.utiliser_stockage_durable()
    yield _departements()
    m1_outils.reinitialiser_registre()
    m2_outils.reinitialiser_registre()
    stockage.liberer()


def _outils(deps, dep_id):
    return {o.nom: o for o in deps[dep_id].charger_outils()}


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _tour(deps, instant: dt.datetime) -> dict[str, int]:
    return evenements.repartir(deps, maintenant=instant.isoformat())


def _drainer(deps, depuis: dt.datetime, *, max_tours: int = 12, pas_s: int = 100) -> dict[str, int]:
    """Livre le bus jusqu'à quiescence, sur TOUS les départements (boucle bornée)."""
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        resume = _tour(deps, depuis + dt.timedelta(seconds=pas_s * tour))
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence après {max_tours} tours : {total}")


def _recu(evenement_id: str, consommateur: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == consommateur)
        )).mappings().first()
    assert ligne is not None, f"aucun reçu de {consommateur} pour {evenement_id}"
    return dict(ligne)


def _maillons(dep: str, registre: str = "principal") -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(dep, registre))


def _empreinte_etat() -> dict:
    """Ce qu'un rejeu ne doit JAMAIS changer : maillons de chaque registre, événements publiés et reçus."""
    with stockage.transaction() as cnx:
        return {
            "registres": {
                f"{ligne.departement}/{ligne.registre}": ligne.n
                for ligne in cnx.execute(select(REGISTRES.c.departement, REGISTRES.c.registre,
                                                func.count().label("n"))
                                         .group_by(REGISTRES.c.departement, REGISTRES.c.registre))
            },
            "sortants": cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one(),
            "recus": cnx.execute(select(func.count()).select_from(EVENEMENTS_RECUS)).scalar_one(),
        }


def _lead_v2(lead_id: str, **surcharges) -> dict:
    lead = {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"sms-{lead_id}",
        "contact": {"telephone": NUMERO}, "service": "gouttieres", "ville": "Laval", "urgence_declaree": True,
        "canal": "texte", "source": "sms",
    }
    lead.update(surcharges)
    return lead


def _publier_lead(lead: dict) -> str:
    identifiant = f"m1-lead-qualifie-{lead['lead_id']}"
    evenements.publier("m1.lead_qualifie", "m01-front-office",
                       {"lead": lead, "horodatage": RECU_LE, "signal_id": f"sms:{lead['lead_id']}"},
                       evenement_id=identifiant)
    return identifiant


def _qualifier(deps, lead_id: str) -> None:
    m2 = _outils(deps, M2)
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": "2026-09-29T11:00:00-04:00",
        "owner": "Alice Vendeuse (fictif)",
        "prochaine_action": {"description": "Préparer la soumission (fictif)", "echeance": "2026-10-02T09:00:00-04:00"},
    }))


def _devis_accepte(deps, lead_id: str, devis_id: str) -> str:
    """M3 crée un devis (40 pi de gouttière + main-d'oeuvre) ; un humain le marque accepté (T3, frontière humaine :
    l'acceptation du client est constatée hors du code). Rend l'identifiant de l'événement publié."""
    m3 = _outils(deps, M3)
    _ok(executer_atomique(m3["m3_creer_devis"], {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [
            {"description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi",
             "cout_unitaire": "8.00", "reference_besoin_materiau": MATERIAU_ID},
            {"description": "Main d'oeuvre installation (fictif)", "quantite": "1", "unite": "forfait",
             "cout_unitaire": "160.00", "reference_besoin_materiau": None},
        ],
        "taux_marge": "0.25", "horodatage": "2026-09-29T15:00:00-04:00", "prix_total": "600.00"}))
    _ok(executer_atomique(m3["m3_marquer_devis_accepte"], {
        "devis_id": devis_id, "approbateur": "Nathan Proprietaire (fictif, T3)", "horodatage": ACCEPTE_LE}))
    return f"m3-devis-accepte-{devis_id}"


def _interventions(deps) -> list[dict]:
    outil = _outils(deps, M4)["m4_lister_interventions"]
    reponse = executer_atomique(outil, {})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


class TestSoumissionAcceptee:
    def test_de_un_sms_a_m4_a_planifier_avec_m2_converti_et_m5_m6_m8_comme_avant(self, instance):
        deps = instance
        capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
        reponse = capacites.appeler("m1_recevoir_message_canal", SMS)
        assert reponse["ok"] is True and reponse["resultat"]["decision"] == "TRANSMETTRE_M2", reponse
        lead = reponse["resultat"]["lead"]
        lead_id = lead["lead_id"]
        assert _drainer(deps, DEBUT)["quarantaines"] == 0  # M2 ingère le lead que M1 a publié
        _qualifier(deps, lead_id)
        evenement_id = _devis_accepte(deps, lead_id, "DEVIS-T410-1")

        total = _drainer(deps, DEBUT + dt.timedelta(hours=1))
        assert total["echecs"] == 0 and total["quarantaines"] == 0, total
        assert evenements.etat()["quarantaine"] == []
        for consommateur in CONSOMMATEURS:
            assert _recu(evenement_id, consommateur)["statut"] == "traite", consommateur

        # -- M2 : converti, référence du devis, prochaine action citée, activité -----------------------------
        registre_m2 = m2_outils._obtenir_registre()
        assert m2_statuts.statut_courant(registre_m2, lead_id) == "converti"
        (converti,) = [m for m in _maillons(M2) if m["type_entree"] == "transition_statut"
                       and m["lead_id"] == lead_id and m["statut"] == "converti"]
        assert converti["reference_devis_m3"] == "DEVIS-T410-1" and converti["horodatage"] == ACCEPTE_LE
        assert converti["prochaine_action"]["description"].startswith("Planifier le chantier avec M4")
        assert "règle planifier_chantier" in converti["prochaine_action"]["description"]
        assert "Aucune date ni aucun créneau n'est promis au client" in converti["prochaine_action"]["description"]
        assert [m["resume"] for m in _maillons(M2) if m["type_entree"] == "interaction"
                and m["lead_id"] == lead_id and m["auteur"] == "system:m3"] != []
        client_id = m2_clients.client_de_lead(registre_m2, lead_id)
        vue = m2_outils.obtenir_client_360(client_id)["resultat"]
        assert vue["opportunites"][0]["statut"] == "converti"
        assert vue["opportunites"][0]["prochaine_action"] == converti["prochaine_action"]

        # -- M4 : `a_planifier`, service, urgence et ville lus à la source du bus -----------------------------
        (intervention,) = _interventions(deps)
        assert (intervention["statut"], intervention["lead_id"], intervention["devis_id"]) == (
            "a_planifier", lead_id, "DEVIS-T410-1")
        assert intervention["service"] == lead["service"] == "gouttieres"
        assert intervention["technicien_assigne"] is None and intervention["fenetre_planifiee"] is None
        (inscription,) = [m for m in _maillons(M4) if m["type_entree"] == "intervention_inscrite"]
        assert inscription["urgence_declaree"] is lead["urgence_declaree"]
        contenu_m4 = json.dumps(_maillons(M4), ensure_ascii=False)
        for interdit in (NUMERO, "Laval", "600.00", "prix", "contact"):
            assert interdit not in contenu_m4, interdit

        # -- M4 : ce qui manque avant la cédule, jamais « prêt » par défaut ----------------------------------
        capacites_m4 = Capacites(deps, stockage.transaction, filtre={M4}, memoire=False)
        preparation = capacites_m4.appeler(
            "m4_verifier_preparation", {"intervention_id": intervention["intervention_id"]})["resultat"]["resultat"]
        assert preparation["pret"] is False and preparation["statut"] == "bloque"
        assert [f["volet"] for f in preparation["a_fournir"]] == ["adresse", "equipe", "materiel", "meteo"]

        # -- M5, M6, M8 comme avant : chacun a reçu le devis ------------------------------------------------
        assert [m["devis_id"] for m in _maillons("m05-financecore", "devis_recus")] == ["DEVIS-T410-1"]
        assert [m["devis_id"] for m in _maillons("m06-material-control", "besoins_prevus")] == ["DEVIS-T410-1"]
        assert [m["devis_id"] for m in _maillons("m08-analytics", "faits_chantier")] == ["DEVIS-T410-1"]

    def test_un_rejeu_ne_change_rien_nulle_part(self, instance):
        deps = instance
        lead = _lead_v2("LEAD-T410-R")
        _publier_lead(lead)
        _drainer(deps, DEBUT)
        _qualifier(deps, lead["lead_id"])
        evenement_id = _devis_accepte(deps, lead["lead_id"], "DEVIS-T410-R")
        assert _drainer(deps, DEBUT + dt.timedelta(hours=1))["quarantaines"] == 0
        avant = _empreinte_etat()

        # le producteur republie le même événement, puis le même devis sous un autre identifiant
        evenements.publier("m3.devis_accepte", "m03-estimation", _charge_publiee(evenement_id),
                           evenement_id=evenement_id)
        assert _drainer(deps, DEBUT + dt.timedelta(hours=2))["livres"] == 0
        assert _empreinte_etat() == avant

        evenements.publier("m3.devis_accepte", "m03-estimation", _charge_publiee(evenement_id),
                           evenement_id="rejeu-par-un-autre-producteur")
        total = _drainer(deps, DEBUT + dt.timedelta(hours=3))
        assert total["echecs"] == 0 and total["quarantaines"] == 0, total
        apres = _empreinte_etat()
        assert apres["registres"] == avant["registres"], "aucun maillon de plus, dans aucun registre"
        assert len(_interventions(deps)) == 1

    def test_ordre_inverse_le_devis_arrive_avant_le_lead_puis_tout_converge_sans_doublon(self, instance):
        deps = instance
        lead = _lead_v2("LEAD-T410-I")
        evenement_id = _devis_accepte(deps, lead["lead_id"], "DEVIS-T410-I")  # le lead n'existe encore nulle part

        premier = _tour(deps, DEBUT)
        assert premier["quarantaines"] == 0 and premier["echecs"] == 2, premier  # M2 (lead inconnu) et M4 (pas de M1)
        assert _recu(evenement_id, M2)["statut"] == "echec" and _recu(evenement_id, M4)["statut"] == "echec"
        for consommateur in ("m05-financecore", "m06-material-control", "m08-analytics"):
            assert _recu(evenement_id, consommateur)["statut"] == "traite", consommateur
        assert _interventions(deps) == []

        _publier_lead(lead)  # M1 publie enfin le lead
        _tour(deps, DEBUT + dt.timedelta(seconds=10))  # M2 ingère le lead ; M4 le relit et inscrit l'intervention
        assert len(_interventions(deps)) == 1
        _qualifier(deps, lead["lead_id"])  # un humain qualifie le lead
        final = _drainer(deps, DEBUT + dt.timedelta(seconds=100))
        assert final["quarantaines"] == 0, final

        assert m2_statuts.statut_courant(m2_outils._obtenir_registre(), lead["lead_id"]) == "converti"
        (intervention,) = _interventions(deps)
        assert intervention["statut"] == "a_planifier" and intervention["devis_id"] == "DEVIS-T410-I"
        for consommateur in CONSOMMATEURS:
            assert _recu(evenement_id, consommateur)["statut"] == "traite", consommateur
        assert len([m for m in _maillons(M2) if m["type_entree"] == "transition_statut"
                    and m["lead_id"] == lead["lead_id"] and m["statut"] == "converti"]) == 1
        assert len([m for m in _maillons("m05-financecore", "devis_recus")]) == 1
        assert evenements.etat()["quarantaine"] == []

    def test_un_lead_qui_n_est_pas_passe_par_m1_part_en_quarantaine_chez_m4_seulement(self, instance):
        """Un lead saisi directement dans M2 : M4 n'a aucun `m1.lead_qualifie` où lire service et ville. Il ne les
        invente pas ; M2, M5, M6 et M8 traitent le même devis normalement."""
        deps = instance
        m2 = _outils(deps, M2)
        contrat = {
            "lead_id": "LEAD-T410-DIRECT", "conversation_id": "conv-direct", "type_travaux": "renovation_totale",
            "ville": "Laval", "urgence_declaree": False, "canal": "telephone",
            "contact": {"nom": "Client Fictif", "telephone": NUMERO},
        }
        _ok(executer_atomique(m2["m2_ingerer_lead"], {"contrat": contrat, "horodatage": "2026-09-29T10:00:00-04:00"}))
        _qualifier(deps, "LEAD-T410-DIRECT")
        evenement_id = _devis_accepte(deps, "LEAD-T410-DIRECT", "DEVIS-T410-D")

        total = _drainer(deps, DEBUT + dt.timedelta(hours=1), max_tours=14)
        assert total["quarantaines"] == 1, total
        assert _recu(evenement_id, M4)["statut"] == "quarantaine"
        assert "FaitDeLeadManquant" in _recu(evenement_id, M4)["derniere_erreur"]
        for consommateur in ("m02-revenue-crm", "m05-financecore", "m06-material-control", "m08-analytics"):
            assert _recu(evenement_id, consommateur)["statut"] == "traite", consommateur
        assert m2_statuts.statut_courant(m2_outils._obtenir_registre(), "LEAD-T410-DIRECT") == "converti"
        assert _interventions(deps) == []


def _contrat_main(lead_id: str) -> dict:
    """Le contrat d'un lead planifié à la main (`m4_planifier_intervention`), le flux d'avant T4.10."""
    return {
        "lead_id": lead_id, "conversation_id": f"conv-main-{lead_id}", "type_travaux": "renovation_totale",
        "ville": "Laval", "canal": "telephone", "contact": {"nom": "Client Fictif", "telephone": NUMERO},
        "urgence_declaree": False,
    }


def _planifier_a_la_main(deps, lead_id: str, devis_id: str | None) -> dict:
    return executer_atomique(_outils(deps, M4)["m4_planifier_intervention"], {
        "contrat": _contrat_main(lead_id),
        "marqueur": {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
                     "horodatage": "2026-09-29T12:00:00+00:00", "empreinte": "ab" * 32},
        "horodatage": "2026-10-01T08:00:00+00:00", "sel": "sel-fictif", "techniciens_disponibles": ["marc.fictif"],
        "fenetres_disponibles": [{"debut": "2026-10-05T07:00:00+00:00", "fin": "2026-10-05T19:00:00+00:00"}],
        "devis_id": devis_id})


class TestPasDeDoublonPourM4:
    """PLAN T4.12 : le bus et la planification à la main ne font jamais deux interventions pour le même devis, quel
    que soit l'ordre. Le reste de la cascade (M2, M5, M6, M8) ne change pas."""

    def test_apres_la_cascade_la_main_est_refusee_et_rien_ne_s_ecrit(self, instance):
        deps = instance
        lead = _lead_v2("LEAD-T412-A")
        _publier_lead(lead)
        _drainer(deps, DEBUT)
        _qualifier(deps, lead["lead_id"])
        _devis_accepte(deps, lead["lead_id"], "DEVIS-T412-A")
        assert _drainer(deps, DEBUT + dt.timedelta(hours=1))["quarantaines"] == 0
        (nee,) = _interventions(deps)
        assert nee["statut"] == "a_planifier"
        avant = _empreinte_etat()

        refus = _planifier_a_la_main(deps, lead["lead_id"], "DEVIS-T412-A")
        assert refus["ok"] is True and refus["resultat"]["accepte"] is False, refus
        assert refus["resultat"]["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"
        assert nee["intervention_id"] in refus["resultat"]["verdict"]["detail"]
        assert _empreinte_etat() == avant, "aucun maillon de plus, dans aucun registre"
        assert [i["intervention_id"] for i in _interventions(deps)] == [nee["intervention_id"]]

    def test_la_main_avant_la_cascade_laisse_une_seule_intervention_et_la_cascade_intacte(self, instance):
        deps = instance
        lead = _lead_v2("LEAD-T412-B")
        _publier_lead(lead)
        _drainer(deps, DEBUT)
        _qualifier(deps, lead["lead_id"])
        main = _planifier_a_la_main(deps, lead["lead_id"], "DEVIS-T412-B")  # la main passe avant l'acceptation
        assert main["ok"] is True and main["resultat"]["accepte"] is True, main
        evenement_id = _devis_accepte(deps, lead["lead_id"], "DEVIS-T412-B")
        total = _drainer(deps, DEBUT + dt.timedelta(hours=1))
        assert total["echecs"] == 0 and total["quarantaines"] == 0, total

        (seule,) = _interventions(deps)
        assert seule["intervention_id"] == main["resultat"]["intervention_id"] and seule["statut"] == "planifiee"
        assert seule["devis_id"] == "DEVIS-T412-B"
        for consommateur in CONSOMMATEURS:
            assert _recu(evenement_id, consommateur)["statut"] == "traite", consommateur
        assert m2_statuts.statut_courant(m2_outils._obtenir_registre(), lead["lead_id"]) == "converti"
        assert [m["devis_id"] for m in _maillons("m05-financecore", "devis_recus")] == ["DEVIS-T412-B"]
        assert [m["devis_id"] for m in _maillons("m06-material-control", "besoins_prevus")] == ["DEVIS-T412-B"]
        assert [m["devis_id"] for m in _maillons("m08-analytics", "faits_chantier")] == ["DEVIS-T412-B"]

    def test_sans_devis_id_la_main_ne_contourne_pas_la_garde(self, instance):
        deps = instance
        lead = _lead_v2("LEAD-T412-C")
        _publier_lead(lead)
        _drainer(deps, DEBUT)
        _qualifier(deps, lead["lead_id"])
        _devis_accepte(deps, lead["lead_id"], "DEVIS-T412-C")
        _drainer(deps, DEBUT + dt.timedelta(hours=1))
        refus = _planifier_a_la_main(deps, lead["lead_id"], None)
        assert refus["resultat"]["accepte"] is False
        assert refus["resultat"]["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"
        assert "sans devis_id" in refus["resultat"]["verdict"]["detail"]
        assert len(_interventions(deps)) == 1


def _charge_publiee(evenement_id: str) -> dict:
    with stockage.transaction():
        charge = evenements.charge_publiee("m3.devis_accepte", evenement_id)
    assert charge is not None
    return charge
