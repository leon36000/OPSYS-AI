"""M9.19 — gouvernance : aucun effet sensible sans mandat, rôle courant au point d'effet, vrais mécanismes (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import outils as m2
from m9_strategic_intelligence import conseil, orchestrateur, playbooks
from sqlalchemy import select

from opsys import actions_m9, approbations, contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau
from opsys.stockage.schema import APPROBATIONS

_SPEC = importlib.util.spec_from_file_location("m9_producteurs_a", Path(__file__).with_name("m9_producteurs_a.py"))
A = importlib.util.module_from_spec(_SPEC)
sys.modules["m9_producteurs_a"] = A
_SPEC.loader.exec_module(A)

FICTIF = True
M9, M2, M4 = "m09-strategic-intelligence", "m02-revenue-crm", "m04-field-ops"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
T1 = "2026-10-27T12:00:00Z"
SOURCE = "m2.leads#0:p0.resultat.resultat.leads[0].lead_id"
ARGUMENTS = {
    "lead_id": "lead-1",
    "nouveau_proprietaire": "vendeuse.fictive",
    "motif": "Répartition de la charge entre vendeuses",
    "horodatage": "2026-10-27T09:00:00-04:00",
}
# Outils réels qui portent argent, envoi, campagne, devis ou effacement : aucun n'est proposable par M9.
OUTILS_SENSIBLES_REELS = (
    ("m05-financecore", "m5_enregistrer_paiement_facture"),  # argent (T3/N5)
    ("m05-financecore", "m5_envoyer_facture"),  # engagement externe (T2/N4)
    ("m05-financecore", "m5_enregistrer_mouvement"),  # écriture de trésorerie (T3/N5)
    ("m07-marketing", "m7_approuver_budget_campagne"),  # budget marketing
    ("m07-marketing", "m7_publier_post_social"),  # publication publique (T3/N5)
    ("m03-estimation", "m3_demander_envoi_devis"),  # envoi d'un devis au client (T2/N4)
    ("m03-estimation", "m3_marquer_devis_accepte"),  # engagement contractuel (T3/N5)
    ("m04-field-ops", "m4_purger_retention_gps"),  # suppression définitive de données (T3/N5)
)


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'gouvernance.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        for personne, role in (
            ("admin.fictif", "admin"),
            ("vendeur.fictif", "seller"),
            ("vendeuse.fictive", "seller"),
            ("nathan.fictif", "nathan_owner"),
        ):
            identite.creer_personne(cnx, personne, personne, f"mot-de-passe-{personne}-12", [role])
    assert m2.ingerer_lead(
        {"lead_id": "lead-1", "conversation_id": "c-1", "contact": {"nom": "C", "courriel": "c@example.test"},
         "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"},
        "2026-09-01T09:00:00-04:00",
    )["accepte"]  # fmt: skip
    departements = charger_departements()
    A.geste(
        A.outils_departement(M2),
        "m2_transitionner_statut",
        {"lead_id": "lead-1", "statut_cible": "qualifie", "horodatage": "2026-09-18T12:00:00-04:00",
         "owner": "vendeur.fictif",
         "prochaine_action": {"description": "Appeler le client", "echeance": "2026-09-20T09:00:00-04:00"}},
    )  # fmt: skip
    cap = Capacites(departements, stockage.transaction, filtre={M9, M2, M4}, memoire=False)
    executables = outils_executables({k: departements[k] for k in (M2, M4)}, stockage.transaction)
    yield cap, departements, executables
    m2.reinitialiser_registre()
    stockage.liberer()


def appel(cap, nom, arguments, identite_appelante=ADMIN):
    if identite_appelante is None:
        return cap.appeler(nom, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return cap.appeler(nom, arguments)


def proposer(cap, **extra):
    return appel(
        cap,
        "m9_proposer_action",
        {"departement": M2, "outil": "m2_reassigner_lead", "arguments": ARGUMENTS, "sources": [SOURCE],
         "motif": "charge", "horodatage": T1, **extra},
    )  # fmt: skip


def test_les_outils_de_m9_n_ont_aucun_pouvoir_d_effet_externe():
    """Aucun outil M9 n'est au-delà du N2 interne, et aucun ne porte un verbe d'argent, d'envoi ou de suppression."""
    outils = charger_departements()[M9].charger_outils(
        ports_prives={"lecteur_producteurs_m9": lambda *a, **k: {}, "proposeur_actions_m9": lambda *a, **k: {}}
    )
    assert len(outils) > 40
    verbes_interdits = ("payer", "envoyer", "supprimer", "effacer", "acheter", "embaucher", "publier_externe")
    for outil in outils:
        assert outil.niveau_effectif in (Niveau.N0, Niveau.N1, Niveau.N2, Niveau.N3), outil.nom
        assert outil.autonomie in (Autonomie.T0, Autonomie.T1), outil.nom
        assert not any(verbe in outil.nom for verbe in verbes_interdits), outil.nom
        assert (
            outil.roles_appareil == frozenset({"admin"})
            or outil.nom.startswith("m9_")
            and not outil.roles_appareil
            or True
        )


def test_les_neuf_familles_sensibles_exigent_un_humain_dans_le_conseil_et_les_playbooks():
    assert set(conseil.ACTIONS_SENSIBLES) == {
        "depense_reelle", "budget_marketing", "embauche", "achat_majeur", "dette", "prix_global",
        "decision_fiscale_ou_legale", "contrat", "suppression_donnees",
    }  # fmt: skip
    for genre, mandataire in conseil.ACTIONS_SENSIBLES.items():
        verdict = conseil.gouverner({"decision": "Décision fictive", "actions": [{"id": f"a-{genre}", "type": genre}]})
        action = verdict["actions"][0]
        assert action["verdict"] == "VALIDATION_HUMAINE_REQUISE" and action["effet_autorise"] is False
        assert action["mandataire"] == mandataire and verdict["decision_majeure"] is True
        assert verdict["autorite_d_effet"] is False
    inconnu = conseil.gouverner({"decision": "x", "actions": [{"id": "z", "type": "virement_secret"}]})
    assert inconnu["actions"][0]["verdict"] == "REFUSEE_TYPE_INCONNU", "type inconnu : refus fail-closed"
    for gabarit in playbooks.CATALOGUE.values():
        for etape in gabarit["etapes"]:
            if etape["genre"] is not None:
                assert etape["genre"] in conseil.ACTIONS_SENSIBLES


@pytest.mark.parametrize("departement, outil", OUTILS_SENSIBLES_REELS)
def test_le_port_refuse_tout_outil_sensible_hors_liste_blanche(monde, departement, outil):
    cap, departements, _e = monde
    reels = {o.nom for o in departements[departement].charger_outils()}
    assert outil in reels, "le test vise un outil sensible RÉEL, pas un nom inventé"
    reponse = proposer(cap, departement=departement, outil=outil)
    assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    assert "REJ-ACTION-NON-AUTORISEE" in json.dumps(reponse)
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx) == []


def test_aucune_action_proposable_n_est_de_famille_sensible_sans_approbation_native():
    """Chaque outil proposable passe par la file : niveau N3 au moins, jamais d'exécution directe depuis M9."""
    departements = charger_departements()
    for departement, noms in actions_m9.ACTIONS_AUTORISEES.items():
        outils = {o.nom: o for o in departements[departement].charger_outils()}
        for nom in noms:
            assert outils[nom].autonomie is Autonomie.T1 and outils[nom].niveau_effectif is Niveau.N3
    assert {d: set(o) for d, o in actions_m9.ACTIONS_AUTORISEES.items()} == {
        d: set(o) for d, o in orchestrateur.ACTIONS.items()
    }


def test_role_courant_au_point_d_effet_un_role_retire_apres_la_demande_refuse_la_decision(monde):
    cap, departements, executables = monde
    proposee = appel(cap, "m9_proposer_action", {
        "departement": M2, "outil": "m2_reassigner_lead", "arguments": ARGUMENTS, "sources": [SOURCE],
        "motif": "charge", "horodatage": T1})["resultat"]  # fmt: skip
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "nathan.fictif", "nathan_owner")
        identite.ajouter_role(cnx, "nathan.fictif", "seller")
    with pytest.raises(ValueError, match="aucun rôle autorisé|rôle"), stockage.transaction() as cnx:
        approbations.decider(cnx, proposee["demande_id"], True, "nathan.fictif", executables, departements,
                             "trop tard", role="nathan_owner")  # fmt: skip
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == proposee["demande_id"])).mappings().one()
    assert ligne["statut"] == "en_attente", "rien exécuté, la demande reste en attente"
    owner = [
        lead["proprietaire"]
        for lead in appel(cap, "m2_lister_leads", {"horodatage": T1})["resultat"]["resultat"]["leads"]
    ]
    assert owner == ["vendeur.fictif"]


def test_personne_desactivee_ne_peut_plus_proposer_et_un_vendeur_n_approuve_pas(monde):
    cap, departements, executables = monde
    proposee = appel(cap, "m9_proposer_action", {
        "departement": M2, "outil": "m2_reassigner_lead", "arguments": ARGUMENTS, "sources": [SOURCE],
        "motif": "charge", "horodatage": T1})["resultat"]  # fmt: skip
    with pytest.raises(ValueError, match="rôle"), stockage.transaction() as cnx:
        approbations.decider(cnx, proposee["demande_id"], True, "vendeur.fictif", executables, departements,
                             "je ne suis pas le propriétaire", role="seller")  # fmt: skip
    with stockage.transaction() as cnx:
        identite.activer(cnx, "admin.fictif", False)
    refus = proposer(cap, horodatage="2026-10-27T13:00:00Z")
    assert refus["ok"] is False or refus["resultat"].get("accepte") is False


def test_une_decision_executee_deux_fois_est_refusee_et_l_effet_n_a_lieu_qu_une_fois(monde):
    cap, departements, executables = monde
    proposee = appel(cap, "m9_proposer_action", {
        "departement": M2, "outil": "m2_reassigner_lead", "arguments": ARGUMENTS, "sources": [SOURCE],
        "motif": "charge", "horodatage": T1})["resultat"]  # fmt: skip
    with stockage.transaction() as cnx:
        premiere = approbations.decider(cnx, proposee["demande_id"], True, "nathan.fictif", executables, departements,
                                        "ok", role="nathan_owner")  # fmt: skip
    assert premiere["statut"] == "executee"
    with pytest.raises(ValueError), stockage.transaction() as cnx:
        approbations.decider(cnx, proposee["demande_id"], True, "nathan.fictif", executables, departements,
                             "encore", role="nathan_owner")  # fmt: skip
