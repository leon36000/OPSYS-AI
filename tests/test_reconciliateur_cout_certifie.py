"""E5 (mode ombre) puis E8 (mode actif) : le réconciliateur du coût certifié, piloté par l'état.

Sur la VRAIE voie (M3 → M4 V3 → bus → M5 → M8/M10) : sans politiques, rien ; en ombre, le moteur tourne et
l'empreinte de TOUTES les tables est identique ; en actif, l'acteur système `opsys-systeme` publie le coût certifié,
le journal le dit, et un second tour n'écrit rien (convergence) ; un état inchangé ne relance rien ; deux exécutions
simultanées n'écrivent qu'une fois ; un défaut du réconciliateur ne touche jamais la facture. Fictif, base éphémère.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
import threading
import time
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from sqlalchemy import select

from opsys import identite, service_politiques, stockage
from opsys import moteur_recalcul_m4 as moteur
from opsys import service_acteur_systeme as systeme
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.evenements import reconciliateur_cout_certifie as rc
from opsys.stockage.schema import COUT_CERTIFIE_RECONCILIATIONS, SERVICE_RECALCUL_INTENTIONS

RACINE = Path(__file__).resolve().parent.parent


def _charger(nom_fichier, nom):
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(nom_fichier))
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


cm = _charger("test_cascade_marge_m5_m8_m10.py", "rc_helpers_cascade_marge")
rg = _charger("test_regression_cascade_cout_certifie.py", "rc_helpers_regression")
BASE = rg.BASE
LEAD, DEVIS, CHANTIER = "LEAD-RC-fictif", "DEVIS-RC-fictif", "CH-RC-fictif"
OPERATEUR = "operateur-rc-fictif"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    import opsys

    assert Path(opsys.__file__).resolve().is_relative_to(RACINE), opsys.__file__
    url = f"sqlite:///{tmp_path / 'opsys-reconciliateur.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv(rc.ENV_MODE, "inactif")  # chaque test choisit son mode
    stockage.migrer(url)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    rc.reinitialiser()
    try:
        yield url
    finally:
        rc.reinitialiser()
        m2_outils.reinitialiser_registre()
        stockage.liberer()


def _session_operateur():
    return Session(OPERATEUR, frozenset({"admin"}), "csrf-fictif", int(time.time()) + 3600)


def _octroyer(*operations):
    """Les politiques sont octroyées par l'OPÉRATEUR Core (D1), sous la session d'un admin actif."""
    with stockage.transaction() as cnx:
        if identite.personne(cnx, OPERATEUR) is None:
            identite.creer_personne(cnx, OPERATEUR, "Opérateur (fictif)", "mot-de-passe-operateur-assez-long",
                                    ["admin"])
        for operation in operations:
            service_politiques.octroyer(cnx, _session_operateur(), operation, motif="Mise en service fictive")


def _empreinte_base() -> str:
    h = hashlib.sha256()
    with stockage.transaction() as cnx:
        for (table,) in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all():
            h.update(table.encode())
            for ligne in cnx.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY rowid').all():
                h.update(repr(tuple(ligne)).encode())
    return h.hexdigest()


def _journal():
    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(COUT_CERTIFIE_RECONCILIATIONS).order_by(
            COUT_CERTIFIE_RECONCILIATIONS.c.id)).mappings()]


def _intentions():
    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(SERVICE_RECALCUL_INTENTIONS)).mappings()]


def _statut(devis_id=DEVIS):
    from m5_financecore import port_service_m4

    with stockage.transaction():
        return port_service_m4.etat_cout_certifie(devis_id)


def _chantier(deps, *, certifie=True, quantite=40.0):
    cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), rg.TARIF_PRIX_LIVRE)
    wct_id, intervention_id = cm._chantier_termine(deps, BASE, LEAD, DEVIS, CHANTIER, quantite, certifie=certifie)
    return wct_id, intervention_id


def _certifiees(devis_id=DEVIS):
    return [t for t in rg._traces_m5(devis_id) if t["projection_empreinte"] is not None and t["mo_statut"] == "complet"
            and t["provenance_service_v1"]]


# -------------------------------------------------------------------------------------------
# Sans politiques : rien
# -------------------------------------------------------------------------------------------
def test_sans_les_deux_politiques_le_reconciliateur_ne_fait_rien(base_durable, monkeypatch):
    deps = charger_departements()
    _chantier(deps)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    with stockage.transaction() as cnx:  # le harnais a posé `m4.verifier_v3` ; pas `m4.recalculer_v3`
        assert service_politiques.statut(service_politiques.derniere(
            cnx, cnx.execute(select(rc.OPSYS_INSTANCE.c.instance_id)).scalar_one(), "m4.recalculer_v3")) == "absente"
    appels = []
    monkeypatch.setattr(moteur, "recalculer", lambda *a, **k: appels.append(1))
    avant = _empreinte_base()
    for mode in ("ombre", "actif"):
        resume = rc.reconcilier(deps, mode_force=mode)
        assert resume["raison"] == "politiques_inactives" and resume["candidats"] == 0, resume
    assert rc.reconcilier(deps, mode_force="inactif")["raison"] == "inactif"
    assert appels == [] and _empreinte_base() == avant


# -------------------------------------------------------------------------------------------
# E5 : mode ombre — le moteur tourne, AUCUNE écriture
# -------------------------------------------------------------------------------------------
def test_mode_ombre_calcule_journalise_et_n_ecrit_rien(base_durable, caplog):
    deps = charger_departements()
    _chantier(deps)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    _octroyer("m4.recalculer_v3")
    assert _statut()["statut"] == "inconnu"
    avant = _empreinte_base()
    with caplog.at_level("INFO", logger="opsys.reconciliateur_cout_certifie"):
        resume = rc.reconcilier(deps, mode_force="ombre")
    assert (resume["candidats"], resume["publiees"], resume["erreurs"]) == (1, 1, 0), resume
    assert _empreinte_base() == avant, "le mode ombre ne doit rien écrire, séquences comprises"
    assert any("aurait publiee" in m and "opsys-systeme" in m for m in caplog.messages), caplog.messages
    assert _statut()["statut"] == "inconnu" and _certifiees() == []
    # état inchangé : pas de second balayage, pas de second calcul
    assert rc.reconcilier(deps, mode_force="ombre")["raison"] == "etat_inchange"
    assert _empreinte_base() == avant


# -------------------------------------------------------------------------------------------
# E8 : mode actif — publication, journal, convergence, idempotence
# -------------------------------------------------------------------------------------------
def test_mode_actif_publie_par_l_acteur_systeme_puis_converge_sans_ecriture(base_durable):
    deps = charger_departements()
    wct_id, intervention_id = _chantier(deps)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    _octroyer("m4.recalculer_v3")
    etat = _statut()
    resume = rc.reconcilier(deps, mode_force="actif")
    assert (resume["publiees"], resume["refus"], resume["erreurs"]) == (1, 0, 0), resume
    cm._prouver_main_d_oeuvre_certifiee(intervention_id, wct_id, publications=1)
    (intention,) = _intentions()
    assert intention["acteur"] == "opsys-systeme" and intention["intention_id"] == rc.intention_pour(etat)
    (ligne,) = _journal()
    assert (ligne["acteur"], ligne["statut"], ligne["wct_id"], ligne["devis_id"]) == (
        "opsys-systeme", "publiee", wct_id, DEVIS)
    assert _statut()["statut"] == "a_jour"
    # Convergence : second tour (même sans mémoire) = zéro écriture, et le moteur n'est même pas appelé.
    apres = _empreinte_base()
    second = rc.reconcilier(deps, mode_force="actif")
    assert second["publiees"] == 0 and second["traites"] == 0, second
    assert _empreinte_base() == apres
    rc.reinitialiser()
    troisieme = rc.reconcilier(deps, mode_force="actif")
    assert (troisieme["candidats"], troisieme["traites"]) == (0, 0), troisieme
    assert _empreinte_base() == apres
    # Même état → même intention → le moteur rend `deja_executee` sans écrire.
    with systeme.contexte_reconciliateur() as acteur, stockage.transaction() as cnx:
        assert moteur.recalculer(cnx, acteur, acteur="opsys-systeme", wct_id=wct_id, devis_id=DEVIS,
                                 intention_id=rc.intention_pour(etat))["statut"] == "deja_executee"
    assert _empreinte_base() == apres


def test_un_refus_est_journalise_une_seule_fois_et_ne_reecrit_rien(base_durable):
    """Journée d'avant le modèle de visites d'équipe (pointage individuel, durée scalaire) : refus
    WCT_ANTERIEUR_MODELE_VISITES, jamais un coût estimé ni une équipe supposée."""
    deps = charger_departements()
    _chantier(deps, certifie=False)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    _octroyer("m4.verifier_v3", "m4.recalculer_v3")
    resume = rc.reconcilier(deps, mode_force="actif")
    assert (resume["publiees"], resume["refus"]) == (0, 1), resume
    (ligne,) = _journal()
    assert (ligne["statut"], ligne["code"], ligne["acteur"]) == (
        "refus", "WCT_ANTERIEUR_MODELE_VISITES", "opsys-systeme")
    assert _intentions() == [] and _certifiees() == []
    avant = _empreinte_base()
    assert rc.reconcilier(deps, mode_force="actif")["raison"] == "etat_inchange"
    rc.reinitialiser()
    rejoue = rc.reconcilier(deps, mode_force="actif")
    assert rejoue["refus"] == 1 and _empreinte_base() == avant  # même refus : pas de seconde ligne


def test_deux_executions_simultanees_n_ecrivent_qu_une_fois(base_durable, monkeypatch):
    """Les deux exécutions ont la MÊME liste de candidats (lue avant que l'une n'écrive : barrière) ; la seconde,
    sérialisée par BEGIN IMMEDIATE, relit l'état sous verrou, le trouve à jour, et n'écrit rien."""
    deps = charger_departements()
    _chantier(deps)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    _octroyer("m4.recalculer_v3")
    barriere, resumes = threading.Barrier(2), []
    traiter, barriere_traitement = rc._traiter, threading.Barrier(2)

    def attendre_puis_traiter(*a, **k):
        barriere_traitement.wait(timeout=30)  # les deux balayages sont faits avant toute écriture
        return traiter(*a, **k)

    monkeypatch.setattr(rc, "_traiter", attendre_puis_traiter)

    def executer():
        barriere.wait(timeout=30)
        resumes.append(rc.reconcilier(deps, mode_force="actif"))

    fils = [threading.Thread(target=executer) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(120)
    assert len(resumes) == 2 and sum(r["erreurs"] for r in resumes) == 0, resumes
    assert sum(r["publiees"] for r in resumes) == 1, resumes
    assert sorted(r["candidats"] for r in resumes) == [1, 1], resumes
    assert sorted((r["publiees"], r["a_jour"]) for r in resumes) == [(0, 1), (1, 0)], resumes
    assert len(_intentions()) == 1 and len(_certifiees()) == 1
    assert [j["statut"] for j in _journal()] == ["publiee"]


def test_un_defaut_du_reconciliateur_ne_touche_ni_la_facture_ni_la_livraison(base_durable, monkeypatch):
    """A3 : le réconciliateur tourne après les livraisons, dans ses propres transactions ; même s'il échoue à
    chaque candidat, le WCT est reçu, la facture brouillon est créée, aucune livraison n'échoue."""
    monkeypatch.setenv(rc.ENV_MODE, "actif")
    _octroyer("m4.recalculer_v3")

    def panne(*a, **k):
        raise RuntimeError("panne fictive du moteur")

    monkeypatch.setattr(moteur, "recalculer", panne)
    deps = charger_departements()
    wct_id, _ = _chantier(deps)
    total = cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    assert total["echecs"] == 0 and total["quarantaines"] == 0
    facture = rg._facture_du_devis(DEVIS)
    assert facture["statut"] == "BROUILLON" and facture["facture_id"] == f"fac-{DEVIS}"
    assert rc.derniere_execution()["erreurs"] >= 1
    assert _journal() == [] and _intentions() == []
    assert cm._recu(wct_id, "m05-financecore")["statut"] == "traite"


def test_postgresql_ne_lance_rien(base_durable, monkeypatch):
    import contextlib
    from types import SimpleNamespace

    deps = charger_departements()
    _octroyer("m4.verifier_v3", "m4.recalculer_v3")

    class Connexion(SimpleNamespace):
        def execute(self, *a, **k):  # pragma: no cover - aucun accès attendu
            raise AssertionError("aucune lecture sur un backend non qualifié")

    @contextlib.contextmanager
    def transaction_pg():
        yield Connexion(engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))

    appels = []
    monkeypatch.setattr(rc, "transaction", transaction_pg)
    monkeypatch.setattr(moteur, "recalculer", lambda *a, **k: appels.append(1))
    resume = rc.reconcilier(deps, mode_force="actif")
    assert resume["raison"] == "backend_non_sqlite" and appels == [], resume


# -------------------------------------------------------------------------------------------
# Parcours de bout en bout, sans aucun geste de recalcul humain
# -------------------------------------------------------------------------------------------
def test_parcours_automatique_wct_variance_verification_facture_puis_changement_de_prix(base_durable, monkeypatch):
    """WCT d'équipe V3 → variance → vérification M4 → facture envoyée → le réconciliateur ACTIF (déclenché par le
    répartiteur) publie le coût certifié → trace CALCULEE + événement → M8 marge calculée, M10 leçon de marge,
    apprentissage non exclu ; puis le prix du livre change → périmé → recalcul automatique → nouveau certifié."""
    monkeypatch.setenv(rc.ENV_MODE, "actif")
    _octroyer("m4.recalculer_v3", "m4.relire_faits_pour_m5_v1")  # `m4.verifier_v3` : posée par le harnais d'équipe
    deps = charger_departements()
    t0 = time.monotonic()
    wct_id, intervention_id = _chantier(deps)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))  # WCT, variance, vérification M4 : tout le bus
    # Déjà certifié automatiquement, prix encore provisoire (facture brouillon).
    assert _statut()["statut"] == "a_jour"
    cm._prouver_main_d_oeuvre_certifiee(intervention_id, wct_id, publications=1)
    rg._envoyer_facture(deps, DEVIS)
    rg._drainer(deps, 10)  # la cascade E1 déclare le certifié périmé, le réconciliateur le recalcule aussitôt
    duree_s = time.monotonic() - t0
    e = rg._evenement_courant_m5(DEVIS)
    assert (e["verdict"], e["cout_reel_complet"], e["prix_definitif"]) == ("CALCULEE", True, True), e
    assert e["marge_reelle_cad"] == rg.MARGE_CERTIFIEE
    assert e["sequence_max"] == e["dernier_insere_sequence"]
    m8 = rg._m8(deps, wct_id)
    assert (m8["m8_marge_reelle_cad"]["statut"], m8["m8_marge_reelle_cad"]["valeur"]) == (
        "calculee", rg.MARGE_CERTIFIEE), m8
    m10 = rg._m10()
    assert m10["marge_reelle_cad"] == rg.MARGE_CERTIFIEE and m10["sequence_max"] == e["sequence_max"]
    # Apprentissage de M3 : sous la relecture qualifiée (politique `m4.relire_faits_pour_m5_v1`), non exclu.
    with cm._relecture_m5_sur_projection_certifiee(monkeypatch, wct_id, DEVIS):
        appr = rg._apprentissage_m3(deps, wct_id)
    assert appr["ok"] and appr["statut_rentabilite"] != "exclue", appr
    assert appr["montant_marge_reelle_cad"] is not None
    assert _statut()["statut"] == "a_jour"
    statuts = [j["statut"] for j in _journal()]
    assert statuts.count("publiee") == 2, statuts  # facture brouillon, puis facture envoyée
    assert {j["acteur"] for j in _journal()} == {"opsys-systeme"}

    # Le prix du livre change : la cascade marque le certifié périmé, le réconciliateur republie un certifié neuf.
    traces_avant = len(rg._traces_m5(DEVIS))
    cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), 9.0)
    rg._republier("m6.variance_chantier", "prix-rc", wct_id=wct_id)
    rg._drainer(deps, 20)
    traces = rg._traces_m5(DEVIS)
    assert len(traces) == traces_avant + 2  # partiel « à recalculer », puis certifié recalculé
    assert traces[-2]["verdict"] == "PARTIELLE" and traces[-1]["verdict"] == "CALCULEE"
    assert traces[-1]["projection_empreinte"] is not None
    e2 = rg._evenement_courant_m5(DEVIS)
    assert e2["verdict"] == "CALCULEE" and e2["sequence_max"] == e["sequence_max"] + 2
    assert e2["marge_reelle_cad"] != e["marge_reelle_cad"]  # le nouveau prix (9 $ au lieu de 8 $) est compté
    assert rg._m8(deps, wct_id)["fait_marge_reelle_cad"] == e2["marge_reelle_cad"]
    assert rg._m10()["marge_reelle_cad"] == e2["marge_reelle_cad"]
    assert _statut()["statut"] == "a_jour"
    # Convergence finale : un tour de bus de plus n'écrit rien.
    apres = _empreinte_base()
    rc.reinitialiser()
    rg._drainer(deps, 30)
    assert _empreinte_base() == apres
    print(f"PARCOURS_BOUT_EN_BOUT_S={duree_s:.2f}")
