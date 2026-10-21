"""Suivi interne fictif : vrai producteur M8/bus/SQL/approbation, aucun effet terrain.

Les événements M3/M4 sont des fixtures de catalogue, pas des actions M3/M4 réelles.
Une ouverture approuvée ne prouve ni l'actualité métier ni l'achèvement de l'action.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from m8_analytics import outils as outils_m8
from m9_strategic_intelligence.encodage import empreinte
from sqlalchemy import select, update

from opsys import approbations, contexte, etat, evenements, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, JOURNAL, META, MUTATIONS_APPLIQUEES, REGISTRES

PREPARER = "m9_preparer_suivi_decision"
OUVRIR = "m9_ouvrir_suivi_decision"
LIRE = "m9_lire_suivi_decision"
DECIDER = "m9_decider_demande_approbation"
PROPRIO = contexte.IdentiteAppelante(personne="proprio-suivi-fictif", role="admin")
RESPONSABLE = "responsable-suivi-fictif"
DEPARTEMENT = "m09-strategic-intelligence"
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'suivi-fictif.db'}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, PROPRIO.personne, "Propriétaire fictif",
                                "mot-de-passe-suivi-fictif", ["admin", "nathan_owner"])
        identite.creer_personne(cnx, RESPONSABLE, "Responsable fictif",
                                "mot-de-passe-responsable-fictif", ["employee"])
    manifeste = tmp_path / "m8-seuil-fictif.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {
        "seuils_alerte": {"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}},
    }}), encoding="utf-8")
    monkeypatch.setattr(outils_m8, "_MANIFESTE", manifeste)
    departements = charger_departements(RACINE)
    actifs = {nom: departements[nom] for nom in ("m08-analytics", DEPARTEMENT)}
    yield actifs
    stockage.liberer()


def _capacites(departements):
    return Capacites(departements, etat.session, memoire=False)


def _recevoir_preuve_m8(departements, suffix=""):
    jeu = {
        "fictif": True,
        "devis": {
            "devis_id": "devis-suivi-fictif" + suffix, "lead_id": "lead-suivi-fictif", "chantier_id": None,
            "lignes": [{"reference_ligne": "ligne-suivi-fictive", "description": "Gouttières fictives",
                        "quantite": "40", "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00",
                        "reference_besoin_materiau": None}],
            "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
            "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
        },
        "wct": {
            "wct_id": "wct-suivi-fictif" + suffix, "intervention_id": "intervention-suivi-fictive",
            "lead_id": "lead-suivi-fictif", "technicien_id": RESPONSABLE,
            "horodatage_completion": "2026-09-27T15:00:00-04:00",
            "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
            "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
            "hash_maillon": "preuve-terrain-fictive", "consommateurs_cibles": ["M8"],
            "devis_id": "devis-suivi-fictif" + suffix, "statut": "completed_verified",
        },
    }
    assert jeu["fictif"] is True
    evenements.publier("m3.devis_accepte", "m03-estimation", jeu["devis"])
    evenements.publier("m4.travaux_termines", "m04-field-ops", jeu["wct"])
    for _ in range(2):
        tour = evenements.repartir(departements, maintenant="2026-09-27T20:00:00+00:00")
        assert tour["echecs"] == tour["quarantaines"] == 0, tour
    with stockage.transaction():
        [alerte] = [a for a in stockage.maillons(DEPARTEMENT, "alertes_m8")
                    if a["preuve"].get("wct_id") == jeu["wct"]["wct_id"]]
    assert alerte["metric_id"] == "m8_ecart_duree_pct"
    assert alerte["type_alerte"] == "MESURE-SEUIL-FRANCHI"
    assert alerte["preuve"]["valeur"] == "100.00"
    assert alerte["preuve"]["wct_id"] == jeu["wct"]["wct_id"]
    return alerte


def _tables():
    with stockage.transaction() as cnx:
        return {nom: sorted(json.dumps(dict(row), sort_keys=True, default=str)
                            for row in cnx.execute(select(table)).mappings())
                for nom, table in META.tables.items()}


def _lire(capacites, nom, arguments):
    avant = _tables()
    with contexte.appele_par_appareil(PROPRIO):
        reponse = capacites.appeler(nom, arguments)
    assert reponse["ok"] is True and "tronque" not in reponse, reponse
    assert _tables() == avant, "Une lecture M9 ne modifie aucune table SQL"
    return reponse["resultat"]


def _metier():
    """Tous les domaines et le bus, hors contrôles N3 et SEUL registre du nouveau suivi."""
    tables = _tables()
    for table in (APPROBATIONS, JOURNAL, MUTATIONS_APPLIQUEES):
        del tables[table.name]
    tables[REGISTRES.name] = [ligne for ligne in tables[REGISTRES.name]
                            if (json.loads(ligne)["departement"], json.loads(ligne)["registre"])
                            != (DEPARTEMENT, "suivi_decisions")]
    return tables


def _decider(capacites, demande_id, cle, decision="approuver"):
    with contexte.appele_par_appareil(PROPRIO):
        return capacites.appeler(DECIDER, {"demande_id": demande_id, "decision": decision},
                                 idempotence.Meta(cle=cle, appareil="tel-suivi-fictif",
                                                  horodatage_appareil="2026-09-28T07:00:00-04:00"))


def _suivis():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, "suivi_decisions"))


def test_ouvrir_un_suivi_avec_preuve_m8_et_approbation_dediee_puis_reprendre(installation):
    alerte = _recevoir_preuve_m8(installation)
    capacites = _capacites(installation)
    assert PREPARER in capacites.index, "Capacité de préparation M9 absente ; preuve M8 reçue vérifiée"
    preparation = _lire(capacites, PREPARER, {"evenement_id": alerte["evenement_id"]})
    source = preparation["source"]
    assert preparation["accepte"] is True
    assert source["alerte"] == alerte and source["empreinte_source"] == empreinte(alerte)
    assert source["nature"] == "historique_recue" and source["couverture"] == "non_evaluee"
    arguments = {"evenement_id": alerte["evenement_id"], "empreinte_source": source["empreinte_source"],
                 "action": "Revoir les causes de durée du chantier fictif avec l'équipe",
                 "responsable_id": RESPONSABLE, "echeance": "2026-10-20T09:00:00-04:00"}
    proposition = capacites.appeler(OUVRIR, arguments)
    assert proposition["statut"] == "en_attente_approbation", proposition
    demande_id = proposition["demande_id"]
    assert _suivis() == [], "Une proposition ne crée aucun suivi métier"
    avant_decision = _metier()
    decision = _decider(capacites, demande_id, "suivi-decision-fictive")
    assert _metier() == avant_decision, "Ouvrir le suivi n'exécute aucune action métier ni événement"
    assert decision["ok"] and not decision["rejoue"], decision
    assert decision["resultat"]["resultat"]["statut"] == "executee", decision
    resultat = _lire(capacites, LIRE, {"suivi_id": demande_id})
    suivi = resultat["suivi"]
    assert resultat["accepte"] is True and suivi["schema"] == 1
    assert suivi["suivi_id"] == demande_id and suivi["statut"] == "planifiee"
    assert suivi["source"] == source
    assert suivi["action"] == arguments["action"] and suivi["responsable_id"] == RESPONSABLE
    assert suivi["echeance"] == arguments["echeance"]
    assert suivi["decision"]["demande_id"] == demande_id
    assert suivi["decision"]["decide_par"] == PROPRIO.personne
    assert suivi["decision"]["decide_role"] == "nathan_owner"
    assert suivi["decision"]["decide_le"] == decision["resultat"]["resultat"]["decide_le"]
    assert _suivis() == [suivi]
    ancien = stockage.moteur()
    stockage.liberer()
    assert stockage.moteur() is not ancien
    capacites = _capacites(installation)
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, PROPRIO.personne)
        assert personne is not None and {"admin", "nathan_owner"} <= personne.roles
    assert _lire(capacites, LIRE, {"suivi_id": demande_id}) == resultat
    avant_rejeu = _tables()
    rejeu = _decider(capacites, demande_id, "suivi-decision-fictive")
    assert rejeu["rejoue"] is True
    assert {k: v for k, v in rejeu.items() if k != "rejoue"} == {
        k: v for k, v in decision.items() if k != "rejoue"}
    assert _tables() == avant_rejeu and _suivis() == [suivi]


def _proposer(installation, **modifications):
    alerte = _recevoir_preuve_m8(installation)
    capacites = _capacites(installation)
    preparation = _lire(capacites, PREPARER, {"evenement_id": alerte["evenement_id"]})
    arguments = {"evenement_id": alerte["evenement_id"],
                 "empreinte_source": preparation["source"]["empreinte_source"],
                 "action": "Analyser la durée du chantier fictif", "responsable_id": RESPONSABLE,
                 "echeance": "2026-10-20T09:00:00-04:00"} | modifications
    proposition = capacites.appeler(OUVRIR, arguments)
    assert proposition["statut"] == "en_attente_approbation", proposition
    return capacites, arguments, proposition["demande_id"], alerte


@pytest.mark.parametrize("cause", ["empreinte", "source_changee", "responsable_inactif",
                                  "responsable_client", "echeance_sans_fuseau", "action_trop_longue"])
def test_refuser_avant_toute_ecriture_de_suivi(installation, cause):
    changements = {"empreinte": {"empreinte_source": "0" * 64},
                   "echeance_sans_fuseau": {"echeance": "2026-10-20T09:00:00"},
                   "action_trop_longue": {"action": "a" * 1001}}.get(cause, {})
    capacites, _, demande_id, alerte = _proposer(installation, **changements)
    with stockage.transaction() as cnx:
        if cause == "responsable_inactif":
            identite.activer(cnx, RESPONSABLE, False)
        elif cause == "responsable_client":
            identite.retirer_role(cnx, RESPONSABLE, "employee")
            identite.ajouter_role(cnx, RESPONSABLE, "client")
        elif cause == "source_changee":
            # Altération contrôlée du SEUL jeu fictif après proposition ; aucune preuve historique modifiée.
            cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == DEPARTEMENT,
                        REGISTRES.c.registre == "alertes_m8").values(
                            maillon=codec.encoder(alerte | {"quoi": "Preuve fictive altérée après proposition"})))
    avant = _metier()
    decision = _decider(capacites, demande_id, "refus-" + cause)
    assert decision["ok"] is True, decision
    execution = decision["resultat"]["resultat"]
    assert execution["statut"] == "echec", execution
    # L'appareil expose une issue bornée, la réponse complète reste dans la demande SQL.
    with stockage.transaction() as cnx:
        refus = approbations.lire(cnx, demande_id)["resultat"]["resultat"]
    assert refus["accepte"] is False and refus["verdict"]["code"].startswith("REJ-SUIVI-"), refus
    assert _suivis() == [] and _metier() == avant
    reprise = _decider(capacites, demande_id, "nouvelle-cle-" + cause)
    assert "executee" not in json.dumps(reprise), reprise
    assert _suivis() == [] and _metier() == avant


def test_proprietaire_revoque_apres_proposition_ne_peut_ouvrir(installation):
    capacites, _, demande_id, _ = _proposer(installation)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, PROPRIO.personne, "nathan_owner")
        assert identite.personne_active(cnx, PROPRIO.personne) is not None
    avant = _metier()
    decision = _decider(capacites, demande_id, "proprietaire-revoque")
    assert "executee" not in json.dumps(decision), decision
    assert _suivis() == [] and _metier() == avant


def test_refus_humain_puis_autre_cle_ne_ressuscite_pas_la_demande(installation):
    capacites, _, demande_id, _ = _proposer(installation)
    avant = _metier()
    refus = _decider(capacites, demande_id, "refus-explicite", decision="refuser")
    assert refus["resultat"]["resultat"]["statut"] == "refusee", refus
    reprise = _decider(capacites, demande_id, "autre-cle-apres-refus")
    assert "executee" not in json.dumps(reprise), reprise
    assert _suivis() == [] and _metier() == avant


def test_appel_direct_et_mandat_ingestion_ne_remplacent_pas_la_demande_dediee(installation):
    capacites, arguments, _, _ = _proposer(installation)
    outil = capacites.index[OUVRIR][1]
    avant = _tables()
    with contexte.appele_par_appareil(PROPRIO):
        direct = executer_atomique(outil, arguments)
    assert direct["resultat"]["verdict"]["code"] == "REJ-SUIVI-APPROBATION", direct
    assert _tables() == avant
    autre = capacites.appeler("m9_etat_consolide", {"snapshot": {
        "module_source": "M8-fictif", "horodatage": "2026-09-28T09:00:00-04:00", "valeurs": {"etat": "fictif"}}})
    autre_id = autre["demande_id"]
    assert _decider(capacites, autre_id, "ingestion-fictive")["resultat"]["resultat"]["statut"] == "executee"
    avant = _tables()
    with contexte.executer_demande_approuvee(autre_id):
        refus = executer_atomique(outil, arguments)
    assert refus["resultat"]["verdict"]["code"] == "REJ-SUIVI-APPROBATION", refus
    assert _tables() == avant and _suivis() == []


@pytest.mark.parametrize("nom,arguments", [(PREPARER, {"evenement_id": "inexistant-fictif"}),
                                          (LIRE, {"suivi_id": "inexistant-fictif"})])
def test_lectures_revalident_admin_sql_et_restent_pures(installation, nom, arguments):
    capacites = _capacites(installation)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, PROPRIO.personne, "admin")
    avant = _tables()
    with contexte.appele_par_appareil(PROPRIO):
        refus = capacites.appeler(nom, arguments)
    assert refus["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in json.dumps(refus), refus
    assert _tables() == avant


def test_arguments_ne_peuvent_usurper_decideur_ni_statut(installation):
    capacites, arguments, _, _ = _proposer(installation)
    for intrusion in ({"decide_par": PROPRIO.personne}, {"demande_id": "faux-mandat"}, {"statut": "terminee"}):
        avant = _tables()
        reponse = capacites.appeler(OUVRIR, arguments | intrusion)
        assert reponse["ok"] is False, reponse
        assert _tables() == avant and _suivis() == []


def test_preuve_historique_authentique_reste_utilisable_apres_autre_alerte(installation):
    capacites, _, demande_id, alerte_a = _proposer(installation)
    alerte_b = _recevoir_preuve_m8(installation, suffix="-b")
    assert alerte_b["evenement_id"] != alerte_a["evenement_id"]
    avant = _metier()
    decision = _decider(capacites, demande_id, "decision-apres-autre-alerte")
    assert decision["resultat"]["resultat"]["statut"] == "executee", decision
    suivi = _lire(capacites, LIRE, {"suivi_id": demande_id})["suivi"]
    assert suivi["source"]["alerte"] == alerte_a
    assert suivi["source"]["nature"] == "historique_recue"
    assert suivi["source"]["couverture"] == "non_evaluee"
    assert _metier() == avant


def test_preuve_trop_volumineuse_refuse_lecture_et_append_sans_troncature(installation):
    alerte = _recevoir_preuve_m8(installation) | {
        "quoi": "Longue preuve fictive " * 160, "pourquoi": "Motif fictif volumineux " * 160}
    capacites = _capacites(installation)
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == DEPARTEMENT,
                    REGISTRES.c.registre == "alertes_m8").values(maillon=codec.encoder(alerte)))
    avant_lecture = _tables()
    with contexte.appele_par_appareil(PROPRIO):
        lecture = capacites.appeler(PREPARER, {"evenement_id": alerte["evenement_id"]})
    assert lecture["ok"] is False and "REJ-SUIVI-BORNE" in json.dumps(lecture), lecture
    assert "tronque" not in lecture and _tables() == avant_lecture
    proposition = capacites.appeler(OUVRIR, {
        "evenement_id": alerte["evenement_id"], "empreinte_source": empreinte(alerte),
        "action": "Revoir la preuve fictive volumineuse", "responsable_id": RESPONSABLE,
        "echeance": "2026-10-20T09:00:00-04:00"})
    avant = _metier()
    decision = _decider(capacites, proposition["demande_id"], "preuve-volume-fictive")
    assert decision["resultat"]["resultat"]["statut"] == "echec", decision
    assert decision["resultat"]["resultat"]["issue"]["verdict"]["code"] == "REJ-SUIVI-BORNE"
    assert _suivis() == [] and _metier() == avant


def test_appel_direct_proprietaire_via_capacites_refuse_le_mandat_implicite(installation):
    capacites, arguments, _, _ = _proposer(installation)
    avant = _metier()
    with contexte.appele_par_appareil(PROPRIO):
        direct = capacites.appeler(OUVRIR, arguments, idempotence.Meta(
            cle="appel-direct-fictif", appareil="tel-suivi-fictif",
            horodatage_appareil="2026-09-28T07:00:00-04:00"))
    assert direct["resultat"]["accepte"] is False, direct
    assert direct["resultat"]["verdict"]["code"] == "REJ-SUIVI-APPROBATION"
    assert _suivis() == [] and _metier() == avant


def test_mandat_autre_outil_encore_en_cours_ne_permet_pas_ouverture(installation):
    capacites, arguments, _, _ = _proposer(installation)
    snapshot = {"module_source": "M8-fictif", "horodatage": "2026-09-28T09:00:00-04:00",
                "valeurs": {"etat": "fictif"}}
    autre = capacites.appeler("m9_etat_consolide", {"snapshot": snapshot})
    index = {nom: outil for nom, (_, outil) in capacites.index.items()}
    ouverture = index[OUVRIR]

    def traverser_autre_outil(snapshot):
        # Injection de test : simule une tentative de réutilisation pendant un AUTRE mandat natif valide.
        cnx = stockage.connexion_courante()
        autorite = approbations.approbateur_en_cours(
            cnx, "m9_etat_consolide", DEPARTEMENT, roles=frozenset({"nathan_owner"}))
        assert autorite is not None and autorite.personne == PROPRIO.personne
        assert approbations.lire(cnx, autre["demande_id"])["statut"] == "en_cours"
        return executer_atomique(ouverture, arguments)["resultat"]

    index["m9_etat_consolide"] = replace(index["m9_etat_consolide"], fonction=traverser_autre_outil)
    avant = _metier()
    with stockage.transaction() as cnx:
        decision = approbations.decider(cnx, autre["demande_id"], True, PROPRIO.personne,
                                       index, installation, role="nathan_owner")
    assert decision["statut"] == "echec", decision
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-SUIVI-APPROBATION"
    assert _suivis() == [] and _metier() == avant
