"""Un SELECT financier stable pendant des commits M5 concurrents, sur PostgreSQL réel."""
from __future__ import annotations

import importlib
import threading
from pathlib import Path

import pytest
from doubles import postgres_ephemere, raison_sans_docker

from opsys import stockage

HORODATAGE = "2026-08-03T12:00:00+00:00"
LIGNES = [
    {"description": "travail fictif", "quantite": "40", "unite": "pi", "prix_unitaire": "8.50",
     "reference_ligne_devis": "L1"},
    {"description": "main d'oeuvre fictive", "quantite": "1", "unite": "forfait",
     "prix_unitaire": "260.00", "reference_ligne_devis": "L2"},
]
MONTANT = "689.85"
ATTESTATION = {"nom": "CPA fictif", "profession": "CPA", "reference_document": "DEPOT-FICTIF-001"}
CONFIG = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12,
               "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {},
    "prevision": {"horizon_semaines": 1, "delai_encaissement_clients_jours": 30,
                  "delai_paiement_fournisseurs_jours": 30},
}


@pytest.fixture
def postgres_m5_snapshot(monkeypatch):
    with postgres_ephemere() as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        yield url
        stockage.liberer(url)


@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
def test_prevision_publique_postgresql_lit_un_seul_etat_maillons(postgres_m5_snapshot, monkeypatch):
    url = postgres_m5_snapshot
    from opsys import approbations, contexte, identite
    from opsys.capacites import Capacites, outils_executables
    from opsys.departements import lire_manifeste
    from opsys.outils import executer_atomique
    moteur_module = importlib.import_module("opsys.stockage.moteur")
    import m5_financecore.outils as m5
    from m5_financecore import facturation

    stockage.migrer(url)
    m5.utiliser_stockage_durable()
    monkeypatch.setattr(m5, "_configuration_manifeste", lambda: CONFIG)
    monkeypatch.setattr(m5, "_stockage_durable_actif", True)
    with stockage.transaction(url) as cnx:
        identite.creer_personne(cnx, "owner.fictif", "Propriétaire fictif", "password-fictif-12345",
                                ["nathan_owner"])
        identite.creer_personne(cnx, "employee.fictif", "Employé fictif", "password-employee-12345",
                                ["employee"])
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    deps = {"m05-financecore": dep}
    outils = {o.nom: o for o in m5.outils()}
    disponibles = outils_executables(deps, stockage.transaction)
    capacites = Capacites(deps, stockage.transaction)

    def approuver(nom, arguments, attestation=None):
        demande = capacites.appeler(nom, arguments)
        assert demande["statut"] == "en_attente_approbation", demande
        with stockage.transaction(url) as cnx:
            decision = approbations.decider(
                cnx, demande["demande_id"], True, "owner.fictif", disponibles, deps,
                attestation=attestation,
            )
        assert decision["statut"] == "executee", decision
        assert decision["reponse"]["resultat"]["accepte"] is True, decision
        return decision

    # Setup de pièce fictive valide, selon les mêmes builders M5 que les tests permanents.
    with stockage.transaction(url):
        cree = executer_atomique(outils["m5_creer_facture_brouillon"], {
            "facture_id": "FACT-PG-FICTIVE", "chantier_id": "CHANTIER-FICTIF",
            "devis_id": "DEVIS-PG-FICTIF", "client_id": "CLIENT-FICTIF", "lignes": LIGNES,
            "horodatage": HORODATAGE,
        })
    assert cree["ok"] and cree["resultat"]["accepte"] is True, cree
    approuver("m5_envoyer_facture", {"facture_id": "FACT-PG-FICTIVE", "horodatage": HORODATAGE})
    assert facturation._etat_facture(m5._registre_factures(None), "FACT-PG-FICTIVE")["statut"] == "ENVOYEE"
    # Solde d'ouverture déjà constaté par le même outil financier (données uniquement fictives).
    approuver("m5_enregistrer_mouvement", {
        "montant": "10000.00", "type_mouvement": "ENCAISSEMENT", "horodatage": HORODATAGE,
        "classe_retention": "STANDARD", "source": "solde d'ouverture fictif",
    }, ATTESTATION)

    reached = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    stale_result: dict = {}
    blocked = False
    original_snapshot = stockage.lire_instantane_maillons

    def synchronized_snapshot(departement, registres):
        nonlocal blocked
        result = original_snapshot(departement, registres)
        if departement == "m05-financecore" and not blocked:
            blocked = True
            reached.set()
            if not release.wait(30):
                raise TimeoutError("approved writers did not finish")
        return result

    def reader():
        try:
            with stockage.transaction(url) as cnx:
                token = moteur_module._CONNEXION.set(cnx)
                try:
                    stale_result.update(executer_atomique(outils["m5_prevoir_tresorerie"], {
                        "aujourd_hui": "2026-08-03", "horizon_semaines": 1,
                        "role": "admin", "autorise_couts": True,
                    }))
                finally:
                    moteur_module._CONNEXION.reset(token)
        except BaseException as exc:
            errors.append(exc)

    def writer():
        try:
            if not reached.wait(30):
                raise TimeoutError("forecast did not read movements")
            # Écriture d'encaissement via T3/N5 et véritable décision nathan_owner + attestation.
            approuver("m5_enregistrer_mouvement", {
                "montant": MONTANT, "type_mouvement": "ENCAISSEMENT", "horodatage": HORODATAGE,
                "classe_retention": "STANDARD", "source": "dépôt fictif lié à la facture",
            }, ATTESTATION)
            # Transition de paiement de facture via T3/N5, avec le même contrôle d'approbation.
            approuver("m5_enregistrer_paiement_facture", {
                "facture_id": "FACT-PG-FICTIVE", "montant_paye": MONTANT,
                "approbateur": "owner.fictif", "horodatage": HORODATAGE,
            }, ATTESTATION)
        except BaseException as exc:
            errors.append(exc)
        finally:
            release.set()

    monkeypatch.setattr(stockage, "lire_instantane_maillons", synchronized_snapshot)
    t_reader = threading.Thread(target=reader, daemon=True)
    t_writer = threading.Thread(target=writer, daemon=True)
    t_reader.start()
    t_writer.start()
    t_reader.join(60)
    t_writer.join(60)
    assert not t_reader.is_alive() and not t_writer.is_alive(), "thread timeout"
    assert not errors, errors

    # Même outil public après commit, sans interleaving : référence de l'état final.
    with stockage.transaction(url):
        final_result = executer_atomique(outils["m5_prevoir_tresorerie"], {
            "aujourd_hui": "2026-08-03", "horizon_semaines": 1,
            "role": "admin", "autorise_couts": True,
        })
        statut_final = facturation._etat_facture(m5._registre_factures(None), "FACT-PG-FICTIVE")["statut"]
        mouvement_final = m5._registre_mouvements(None).lire()
    assert stale_result["ok"] and stale_result["resultat"]["accepte"] is True, stale_result
    assert final_result["ok"] and final_result["resultat"]["accepte"] is True, final_result
    stale_page = stale_result["resultat"]["resultat"]
    final_page = final_result["resultat"]["resultat"]
    stale_solde = stale_page["solde_initial"]["montant"]
    final_solde = final_page["solde_initial"]["montant"]
    assert stale_solde == "10000.00", stale_page
    assert final_solde == "10689.85", final_page
    assert statut_final == "PAYEE" and len(mouvement_final) == 2
    assert stale_page["au_dela_de_l_horizon"]["entrees"]["total"] == "689.85", stale_page
    assert final_page["au_dela_de_l_horizon"]["entrees"]["total"] == "0.00", final_page

    # Chaque source effectivement lue par la prévision courte est fail-closed si sa chaîne est altérée.
    from datetime import date

    from m5_financecore import comptes_a_payer, constat_tresorerie_prevue
    from sqlalchemy import func, select, update

    from opsys.stockage import codec
    from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

    charge = {
        "evenement_id": "evt-ap-fictif", "po_id": "PO-AP-FICTIF", "fournisseur_id": "gentek",
        "chantier_id": "CHANTIER-FICTIF", "horodatage_reception": HORODATAGE,
        "verdict_reception": "RECEPTION_INFERIEURE", "statut_po": "partially_received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": None,
        "lignes": [{"materiau_id": "materiau-fictif", "quantite_demandee": "1", "quantite_recue": "1",
                    "prix_unitaire_prevu": None, "devise_prevue": None, "verdict_prix_po": "PRIX_ABSENT",
                    "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE",
                    "ecart_prix_critique": None}],
    }
    with stockage.transaction(url):
        entree, refus = comptes_a_payer.construire_reception(charge)
        assert refus is None and entree is not None, refus
        _, refus = comptes_a_payer.enregistrer_reception(entree, m5._registre_comptes_a_payer())
        assert refus is None, refus

    for nom_registre in ("principal", "factures", "comptes_a_payer"):
        with stockage.transaction(url) as cnx:
            row = cnx.execute(
                select(REGISTRES.c.maillon).where(
                    REGISTRES.c.departement == "m05-financecore",
                    REGISTRES.c.registre == nom_registre,
                    REGISTRES.c.rang == 0,
                )
            ).one()
            original = row.maillon
            modifie = codec.decoder(original)
            modifie["ligne_id"] = "falsifie-fictif"
            cnx.execute(
                update(REGISTRES).where(
                    REGISTRES.c.departement == "m05-financecore",
                    REGISTRES.c.registre == nom_registre,
                    REGISTRES.c.rang == 0,
                ).values(maillon=codec.encoder(modifie))
            )
            token = moteur_module._CONNEXION.set(cnx)
            try:
                refuse = executer_atomique(outils["m5_prevoir_tresorerie"], {
                    "aujourd_hui": "2026-08-03", "horizon_semaines": 1,
                    "role": "admin", "autorise_couts": True,
                })
                evenements_avant = cnx.execute(
                    select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
                        EVENEMENTS_SORTANTS.c.type_evenement
                        == constat_tresorerie_prevue.TYPE_EVENEMENT_TRESORERIE_PREVUE
                    )
                ).scalar_one()
                constat = m5._constater_tresorerie_prevue(
                    m5._registre_mouvements(None), date(2026, 8, 3), HORODATAGE
                )
                etat_refus = executer_atomique(outils["m5_etat_tresorerie"], {
                    "role": "admin", "autorise_couts": True,
                })
                evenements_apres = cnx.execute(
                    select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
                        EVENEMENTS_SORTANTS.c.type_evenement
                        == constat_tresorerie_prevue.TYPE_EVENEMENT_TRESORERIE_PREVUE
                    )
                ).scalar_one()
            finally:
                moteur_module._CONNEXION.reset(token)
            cnx.execute(
                update(REGISTRES).where(
                    REGISTRES.c.departement == "m05-financecore",
                    REGISTRES.c.registre == nom_registre,
                    REGISTRES.c.rang == 0,
                ).values(maillon=original)
            )
        assert refuse["ok"] and refuse["resultat"]["accepte"] is False, (nom_registre, refuse)
        assert refuse["resultat"]["verdict"]["code"] == "REJ-CFO-CHAINE-INVALIDE", (nom_registre, refuse)
        assert constat["refus"]["code"] == "REJ-CFO-CHAINE-INVALIDE", (nom_registre, constat)
        assert etat_refus["ok"] and etat_refus["resultat"]["accepte"] is False, (nom_registre, etat_refus)
        assert etat_refus["resultat"]["verdict"]["code"] == "REJ-CFO-CHAINE-INVALIDE", (nom_registre, etat_refus)
        assert set(etat_refus["resultat"]) == {"accepte", "verdict"}, (nom_registre, etat_refus)
        assert evenements_apres == evenements_avant, nom_registre

    # Les voies refusées ou explicitement sans coûts n'ouvrent pas la lecture groupée.
    appels_snapshot = []
    original_snapshot_sans_couts = stockage.lire_instantane_maillons

    def compter_snapshot(departement, registres):
        appels_snapshot.append((departement, tuple(registres)))
        return original_snapshot_sans_couts(departement, registres)

    monkeypatch.setattr(stockage, "lire_instantane_maillons", compter_snapshot)
    with stockage.transaction(url):
        sans_couts = executer_atomique(outils["m5_etat_tresorerie"], {
            "role": "admin", "autorise_couts": False,
        })
    assert sans_couts["ok"] and sans_couts["resultat"]["solde"] is None, sans_couts
    assert sans_couts["resultat"]["cash_libre"] is None, sans_couts
    assert appels_snapshot == []

    with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne="employee.fictif", role="employee")):
        refuse_appareil = executer_atomique(outils["m5_etat_tresorerie"], {})
    assert refuse_appareil["ok"] and refuse_appareil["resultat"]["accepte"] is False, refuse_appareil
    assert refuse_appareil["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE", refuse_appareil
    assert appels_snapshot == []

    # `m5_etat_tresorerie` currently reads its ledger state before `_cash_libre` opens a second snapshot.
    state_reached = threading.Event()
    state_release = threading.Event()
    state_errors: list[BaseException] = []
    state_result: dict = {}
    original_state_snapshot = stockage.lire_instantane_maillons

    def synchronized_state_snapshot(departement, registres):
        if departement == "m05-financecore":
            state_reached.set()
            if not state_release.wait(30):
                raise TimeoutError("state writer approval did not finish")
        return original_state_snapshot(departement, registres)

    def state_reader():
        try:
            with stockage.transaction(url) as cnx:
                token = moteur_module._CONNEXION.set(cnx)
                try:
                    state_result.update(executer_atomique(outils["m5_etat_tresorerie"], {
                        "role": "admin", "autorise_couts": True,
                    }))
                finally:
                    moteur_module._CONNEXION.reset(token)
        except BaseException as exc:
            state_errors.append(exc)

    def state_writer():
        try:
            if not state_reached.wait(30):
                raise TimeoutError("state calculation did not reach cash libre")
            approuver("m5_enregistrer_mouvement", {
                "montant": "100.00", "type_mouvement": "ENCAISSEMENT", "horodatage": HORODATAGE,
                "classe_retention": "STANDARD", "source": "mouvement concurrent fictif pour instantane",
            }, ATTESTATION)
        except BaseException as exc:
            state_errors.append(exc)
        finally:
            state_release.set()

    monkeypatch.setattr(stockage, "lire_instantane_maillons", synchronized_state_snapshot)
    state_reader_thread = threading.Thread(target=state_reader, daemon=True)
    state_writer_thread = threading.Thread(target=state_writer, daemon=True)
    state_reader_thread.start()
    state_writer_thread.start()
    state_reader_thread.join(60)
    state_writer_thread.join(60)
    assert not state_reader_thread.is_alive() and not state_writer_thread.is_alive(), "state thread timeout"
    assert not state_errors, state_errors
    assert state_result["ok"], state_result
    state = state_result["resultat"]
    assert state["solde"] == "10789.85"
    assert state["cash_libre"]["solde"]["montant"] == "10789.85"

    with stockage.transaction(url):
        settled_state = executer_atomique(outils["m5_etat_tresorerie"], {"role": "admin", "autorise_couts": True})
    settled = settled_state["resultat"]
    assert settled["solde"] == settled["cash_libre"]["solde"]["montant"] == "10789.85"
