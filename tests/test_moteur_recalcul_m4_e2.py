"""E2 (CONCEPTION-ROUTAGE-COUT-CERTIFIE, étape E2) : le moteur de recalcul certifié SQLite, privé et NON branché.

Le moteur (`opsys.moteur_recalcul_m4.recalculer`) est dérivé de la couture QA `service_recalcul_m4._executer_qa`. Chaque
garde ajoutée par E2 a ici son test, sur la VRAIE voie certifiée (M4 V3, bus, M5, tarif d'équipe) quand l'état se
construit sans simuler la source, et par injection ciblée de l'ABSENCE de pièce sinon (reçu WCT sans empreinte, preuve
typée d'équipe absente, registre des tarifs illisible). Pour chaque refus, la preuve centrale est la même :
l'empreinte complète de la base (toutes les tables, séquences comprises) est IDENTIQUE avant et après.

Fictif (`fictif: true`, AGENTS.md) : base éphémère par test, aucune donnée réelle.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
import time
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from sqlalchemy import event as sqla_event
from sqlalchemy import insert, select

from opsys import moteur_recalcul_m4 as moteur
from opsys import service_capability as sc
from opsys import service_recalcul_m4, stockage
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.stockage.moteur import _debuter_sqlite
from opsys.stockage.schema import OPSYS_INSTANCE, SERVICE_POLITIQUES

RACINE = Path(__file__).resolve().parent.parent


def _charger_helpers():
    chemin = Path(__file__).with_name("test_cascade_marge_m5_m8_m10.py")
    nom = "e2_helpers_cascade_marge"
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


cm = _charger_helpers()

BASE = dt.datetime(2026, 9, 16, 7, 0, 0, tzinfo=cm.DT_TZ)
LEAD, DEVIS, CHANTIER = "LEAD-E2-fictif", "DEVIS-E2-fictif", "CH-E2-fictif"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    import opsys

    # le `pythonpath` du pyproject de CE worktree doit primer sur tout autre éditable
    assert Path(opsys.__file__).resolve().is_relative_to(RACINE), opsys.__file__
    assert Path(m5_outils.__file__).resolve().is_relative_to(RACINE), m5_outils.__file__
    assert Path(moteur.__file__).resolve().is_relative_to(RACINE), moteur.__file__
    url = f"sqlite:///{tmp_path / 'opsys-e2-moteur.db'}"
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
# Scénario et mesures
# -------------------------------------------------------------------------------------------
def _chantier(*, quantite: float = 40.0, certifie: bool = True) -> tuple[dict, str]:
    """Du lead au chantier terminé par la voie certifiée (équipe, visite, pointages d'équipe V3, tarif d'équipe,
    politique `m4.verifier_v3`), bus drainé. `quantite` > 40 déclenche une revue humaine de M4 qui N'EST PAS faite
    ici : la complétion reste `completed_pending_review`."""
    deps = charger_departements()
    cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), 8.0)
    wct_id, _ = cm._chantier_termine(deps, BASE, LEAD, DEVIS, CHANTIER, quantite, certifie=certifie)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    return deps, wct_id


def _intention(etiquette: str) -> str:
    return hashlib.sha256(f"e2-{etiquette}".encode()).hexdigest()


def _empreinte_base() -> str:
    """Empreinte de TOUTES les tables (contenu ordonné par rowid) : registres, journal, événements, politiques, audits,
    intentions, résultats, attestations, séquences AUTOINCREMENT comprises."""
    h = hashlib.sha256()
    with stockage.transaction() as cnx:
        tables = [r[0] for r in cnx.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all()]
        for table in tables:
            h.update(table.encode())
            for ligne in cnx.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY rowid').all():
                h.update(repr(tuple(ligne)).encode())
    return h.hexdigest()


def _compte(table) -> int:
    with stockage.transaction() as cnx:
        return len(cnx.execute(select(table)).all())


def _recalculer(wct_id, *, intention="a", devis_id=DEVIS, acteur=cm.ADMIN_CERTIFIE, session="defaut"):
    session = cm._session_admin_certifie() if session == "defaut" else session
    with stockage.transaction() as cnx:
        return moteur.recalculer(cnx, session, acteur=acteur, wct_id=wct_id, devis_id=devis_id,
                                 intention_id=_intention(intention))


def _refus(wct_id, code, **kw):
    """Appelle le moteur : refus typé attendu, et RIEN n'a bougé dans la base."""
    avant = _empreinte_base()
    with pytest.raises(moteur.RefusRecalculM4) as exc:
        _recalculer(wct_id, **kw)
    assert exc.value.code == code, (exc.value.code, str(exc.value))
    assert isinstance(exc.value, sc.RefusAutorite)
    assert _empreinte_base() == avant, "un refus ne doit laisser AUCUNE écriture"
    return exc.value


def _nouvelle_revision(operation: str, *, active: bool, expire_dans: int = 3600) -> None:
    with stockage.transaction() as cnx:
        instance_id = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        derniere = cnx.execute(select(SERVICE_POLITIQUES.c.revision).where(
            SERVICE_POLITIQUES.c.operation == operation).order_by(SERVICE_POLITIQUES.c.revision.desc())
        ).scalars().first() or 0
        cnx.execute(insert(SERVICE_POLITIQUES).values(
            instance_id=instance_id, consommateur="m05-financecore", operation=operation,
            revision=derniere + 1, active=active, expire_le=int(time.time()) + expire_dans))


def _traces_certifiees() -> int:
    """Traces dont la main-d'oeuvre est certifiée (chiffrée sur une projection M4), pas les partiels de la cascade."""
    from m5_financecore import cout_reel

    with stockage.transaction():
        return sum(1 for t in stockage.maillons("m05-financecore", "rentabilite")
                   if cout_reel._main_d_oeuvre_certifiee(t))


# -------------------------------------------------------------------------------------------
# Le chemin nominal et l'idempotence
# -------------------------------------------------------------------------------------------
def test_publie_puis_second_appel_rien_a_faire_sans_aucune_ecriture(base_durable):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")

    reponse = _recalculer(wct_id, intention="premiere")
    assert reponse["statut"] == "publiee"
    assert reponse["attestation"]["operation"] == "m4.recalculer_v3"
    assert reponse["attestation"]["acteur"] == cm.ADMIN_CERTIFIE
    service_recalcul_m4.valider_reference_v2(reponse["attestation"])
    traces = _traces_certifiees()
    publies = len(cm._publies_m5())

    # même intention : relecture de l'historique, zéro écriture
    avant = _empreinte_base()
    rejeu = _recalculer(wct_id, intention="premiere")
    assert rejeu["statut"] == "deja_executee"
    assert _empreinte_base() == avant

    # AUTRE intention, rien n'a changé : `rien_a_faire`, zéro écriture (ni trace, ni reçu, ni événement, ni audit)
    avant = _empreinte_base()
    second = _recalculer(wct_id, intention="deuxieme")
    assert second == {"statut": "rien_a_faire", "raison": "etat_certifie_a_jour"}
    assert _empreinte_base() == avant, "rien_a_faire = zéro écriture, séquences d'audit comprises"
    assert _traces_certifiees() == traces and len(cm._publies_m5()) == publies
    # la même intention « rien_a_faire » reste rejouable : elle n'a pas été consommée
    assert _recalculer(wct_id, intention="deuxieme")["statut"] == "rien_a_faire"
    assert _empreinte_base() == avant


def _registres_par_nom() -> dict:
    """Empreinte de chaque registre M4/M5/... (departement, registre) : la facture vit dans `factures`."""
    from opsys.stockage.schema import REGISTRES

    sortie: dict = {}
    with stockage.transaction() as cnx:
        for ligne in cnx.execute(select(REGISTRES).order_by(
                REGISTRES.c.departement, REGISTRES.c.registre, REGISTRES.c.rang)).all():
            h = sortie.setdefault((ligne.departement, ligne.registre), hashlib.sha256())
            h.update(repr((ligne.rang, ligne.maillon)).encode())
    return {cle: h.hexdigest() for cle, h in sortie.items()}


def _tables_par_nom() -> dict:
    sortie = {}
    with stockage.transaction() as cnx:
        for (table,) in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all():
            h = hashlib.sha256()
            for ligne in cnx.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY rowid').all():
                h.update(repr(tuple(ligne)).encode())
            sortie[table] = h.hexdigest()
    return sortie


def test_la_facture_et_les_registres_hors_certifie_ne_bougent_pas_meme_en_cas_de_succes(base_durable):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    registres_avant, tables_avant = _registres_par_nom(), _tables_par_nom()
    assert ("m05-financecore", "factures") in registres_avant

    assert _recalculer(wct_id)["statut"] == "publiee"

    registres_apres, tables_apres = _registres_par_nom(), _tables_par_nom()
    changes = {cle for cle in registres_apres if registres_apres.get(cle) != registres_avant.get(cle)}
    # seuls la trace de rentabilité et le reçu de recalcul v2 de M5 sont écrits dans les registres
    assert changes == {("m05-financecore", "rentabilite"), ("m05-financecore", "rentabilite_recalcul_v2")}, changes
    assert registres_apres[("m05-financecore", "factures")] == registres_avant[("m05-financecore", "factures")]
    ecrites = {t for t in tables_apres if tables_apres[t] != tables_avant.get(t)}
    assert ecrites <= {
        "registres_maillons", "evenements_sortants", "service_audit", "service_recalcul_intentions",
        "service_recalcul_resultats", "service_recalcul_attestations_v2", "sqlite_sequence",
    }, ecrites


# -------------------------------------------------------------------------------------------
# Le verrou d'écriture BEGIN IMMEDIATE est vérifié, pas supposé
# -------------------------------------------------------------------------------------------
def _sans_ecouteur(engine):
    """Retire l'écouteur `begin -> BEGIN IMMEDIATE` de l'engine ; rend de quoi le remettre."""
    assert sqla_event.contains(engine, "begin", _debuter_sqlite)
    sqla_event.remove(engine, "begin", _debuter_sqlite)

    def remettre():
        if not sqla_event.contains(engine, "begin", _debuter_sqlite):
            sqla_event.listen(engine, "begin", _debuter_sqlite)

    return remettre


def test_refus_sans_ecouteur_begin_immediate_a_l_entree_sans_ecriture(base_durable):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    avant = _empreinte_base()
    with stockage.transaction() as cnx:
        remettre = _sans_ecouteur(cnx.engine)
        try:
            with pytest.raises(moteur.RefusRecalculM4) as exc:
                moteur.recalculer(cnx, cm._session_admin_certifie(), acteur=cm.ADMIN_CERTIFIE, wct_id=wct_id,
                                  devis_id=DEVIS, intention_id=_intention("sans-verrou"))
        finally:
            remettre()
    assert exc.value.code == moteur.VERROU_ECRITURE_ABSENT
    assert _empreinte_base() == avant
    # contrôle positif : avec l'écouteur, le même appel publie
    assert _recalculer(wct_id, intention="sans-verrou")["statut"] == "publiee"


def test_refus_si_l_ecouteur_disparait_pendant_la_portee_et_annule_tout(base_durable, monkeypatch):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    avant = _empreinte_base()
    original = sc._faits_m4_verifies
    restaurations = []

    def faits_puis_perte_du_verrou(portee):
        faits = original(portee)
        restaurations.append(_sans_ecouteur(portee.cnx.engine))
        return faits

    monkeypatch.setattr(sc, "_faits_m4_verifies", faits_puis_perte_du_verrou)
    try:
        with pytest.raises(moteur.RefusRecalculM4) as exc:
            _recalculer(wct_id, intention="perte-verrou")
    finally:
        for remettre in restaurations:
            remettre()
    assert exc.value.code == moteur.VERROU_ECRITURE_ABSENT
    assert _empreinte_base() == avant


def test_le_verrou_d_ecriture_est_reellement_pris_par_la_transaction(base_durable):
    """Contrôle de la garde elle-même : tant que la transaction vit, une autre connexion ne peut pas écrire."""
    import sqlite3

    with stockage.transaction() as cnx:
        chemin = cnx.exec_driver_sql("PRAGMA database_list").all()[0][2]
        autre = sqlite3.connect(chemin, timeout=0.2, isolation_level=None)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                autre.execute("BEGIN IMMEDIATE")
        finally:
            autre.close()


# -------------------------------------------------------------------------------------------
# PostgreSQL : refus explicite
# -------------------------------------------------------------------------------------------
def test_postgresql_refuse_explicitement_sans_aucun_acces_a_la_base():
    from types import SimpleNamespace

    class Connexion(SimpleNamespace):
        def execute(self, *a, **k):  # pragma: no cover - ne doit jamais être appelé
            raise AssertionError("aucun accès base attendu sur un backend non qualifié")

    cnx = Connexion(engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    session = Session("nathan", frozenset({"admin"}), "csrf-fictif", int(time.time()) + 3600)
    with pytest.raises(moteur.RefusRecalculM4) as exc:
        moteur.recalculer(cnx, session, acteur="nathan", wct_id="a" * 64, devis_id="DEVIS", intention_id="b" * 64)
    assert exc.value.code == moteur.BACKEND_NON_SQLITE
    assert "SQLite" in str(exc.value)


# -------------------------------------------------------------------------------------------
# Politiques : absente, révoquée, expirée — pour m4.recalculer_v3 ET m4.verifier_v3
# -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("operation", ["m4.recalculer_v3", "m4.verifier_v3"])
@pytest.mark.parametrize("etat", ["absente", "revoquee", "expiree"])
def test_politique_absente_revoquee_ou_expiree_refuse_sans_ecriture(base_durable, monkeypatch, operation, etat):
    poser = cm._poser_politique
    if etat == "absente":
        monkeypatch.setattr(cm, "_poser_politique", lambda op: None if op == operation else poser(op))
    deps, wct_id = _chantier()
    monkeypatch.setattr(cm, "_poser_politique", poser)
    if operation != "m4.recalculer_v3" or etat != "absente":
        cm._poser_politique("m4.recalculer_v3")
    if etat == "revoquee":
        _nouvelle_revision(operation, active=False)
    elif etat == "expiree":
        _nouvelle_revision(operation, active=True, expire_dans=-30)
    code = {"absente": moteur.POLITIQUE_ABSENTE, "revoquee": moteur.POLITIQUE_REVOQUEE,
            "expiree": moteur.POLITIQUE_EXPIREE}[etat]
    erreur = _refus(wct_id, code)
    assert operation in str(erreur), "le refus nomme l'opération en cause"


# -------------------------------------------------------------------------------------------
# Projection non exploitable : revue en attente, équipe inconnue
# -------------------------------------------------------------------------------------------
def test_revue_en_attente_refuse_puis_la_revue_humaine_debloque(base_durable):
    deps, wct_id = _chantier(quantite=56.0)  # +40 % : M4 attend une revue humaine, qui n'est PAS faite
    cm._poser_politique("m4.recalculer_v3")
    erreur = _refus(wct_id, moteur.REVUE_EN_ATTENTE)
    assert "revue" in str(erreur)
    assert _traces_certifiees() == 0

    intervention_id = cm._charge_publiee("m4.travaux_termines", wct_id)["intervention_id"]
    cm._m4_revue_humaine_verifiee(deps, intervention_id, BASE + dt.timedelta(hours=4, minutes=5))
    assert _recalculer(wct_id, intention="apres-revue")["statut"] == "publiee"
    assert _traces_certifiees() == 1


def test_equipe_inconnue_refuse_sans_attribution_supposee(base_durable, monkeypatch):
    """Sans preuve typée V3 d'équipe, la visite reste « inconnue » : ni égalité avec l'équipe prévue, ni profil
    courant ne la rétroattribue (conception §5.1). On retire la SEULE pièce qui l'établit (la qualification des
    preuves) ; la projection M4 reste, elle, celle du producteur."""
    from m4_field_ops import temps_certifies_v3

    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    with monkeypatch.context() as m:
        m.setattr(temps_certifies_v3, "_qualifier", lambda cnx, projection, captures: [])
        erreur = _refus(wct_id, moteur.EQUIPE_INCONNUE)
    assert "équipe" in str(erreur)
    assert _recalculer(wct_id, intention="avec-preuve")["statut"] == "publiee"


# -------------------------------------------------------------------------------------------
# Historique : WCT d'avant le modèle de visites, WCT sans empreinte_charge
# -------------------------------------------------------------------------------------------
def test_wct_anterieur_au_modele_de_visites_refuse_sans_estimation(base_durable):
    """Une journée au pointage INDIVIDUEL (aucune visite d'équipe) : le producteur M4 refuse de la certifier."""
    deps, wct_id = _chantier(certifie=False)
    from opsys import identite

    with stockage.transaction() as cnx:  # le compte admin existe déjà sur la voie certifiée ; pas ici
        identite.creer_personne(cnx, cm.ADMIN_CERTIFIE, "Admin certifié (fictif)",
                                "un-mot-de-passe-certifie-suffisamment-long", ["admin"])
    cm._poser_politique("m4.verifier_v3")
    cm._poser_politique("m4.recalculer_v3")
    erreur = _refus(wct_id, moteur.WCT_ANTERIEUR_MODELE_VISITES)
    assert erreur.detail == "fait sans ouverture correspondante"
    assert _traces_certifiees() == 0


@pytest.mark.parametrize(("refus_m4", "code"), [
    ("DUREE-INCOHERENTE", moteur.WCT_ANTERIEUR_MODELE_VISITES),
    ("VISITE-AMBIGUE", moteur.WCT_ANTERIEUR_MODELE_VISITES),
    ("WCT-ANTERIEUR-A-VISITE", moteur.WCT_ANTERIEUR_MODELE_VISITES),
    ("ROUTE-AMBIGUE", moteur.WCT_ANTERIEUR_MODELE_VISITES),
    ("REVUE-INCOHERENTE", moteur.SOURCE_M4_REFUSEE),
    ("SOURCE-MODIFIEE", moteur.SOURCE_M4_REFUSEE),
])
def test_refus_du_producteur_m4_sont_types_sans_ecriture(base_durable, monkeypatch, refus_m4, code):
    from m4_field_ops.temps_certifies_v2 import Refus

    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")

    def refuse(portee):
        raise Refus(refus_m4)

    monkeypatch.setattr(sc, "_faits_m4_verifies", refuse)
    assert _refus(wct_id, code).detail == refus_m4


def test_wct_sans_empreinte_charge_refuse_avant_toute_ecriture(base_durable, monkeypatch):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    original = m5_outils._sources_cout_reel

    def sans_empreinte():
        sources = original()
        wct = [{k: v for k, v in r.items() if k != "empreinte_charge"} if r.get("wct_id") == wct_id else r
               for r in sources["wct"]]
        return {**sources, "wct": wct}

    monkeypatch.setattr(m5_outils, "_sources_cout_reel", sans_empreinte)
    erreur = _refus(wct_id, moteur.WCT_SANS_EMPREINTE)
    assert "empreinte" in str(erreur)


# -------------------------------------------------------------------------------------------
# Tarifs : absent, illisible
# -------------------------------------------------------------------------------------------
def test_tarif_absent_annule_la_trace_deja_ecrite_dans_le_savepoint(base_durable, monkeypatch):
    """Aucun tarif d'équipe : M5 écrirait un coût partiel sous provenance certifiée. Le moteur le détecte APRÈS
    l'écriture de la trace (dans le savepoint) et annule tout : l'empreinte de la base est inchangée."""
    inscrire = m5_outils._inscrire_tarif_equipe
    monkeypatch.setattr(m5_outils, "_inscrire_tarif_equipe", lambda *a, **k: None)
    deps, wct_id = _chantier()
    monkeypatch.setattr(m5_outils, "_inscrire_tarif_equipe", inscrire)
    cm._poser_politique("m4.recalculer_v3")
    erreur = _refus(wct_id, moteur.TARIF_ABSENT)
    assert "tarif" in str(erreur)
    assert _traces_certifiees() == 0


def test_tarifs_illisibles_refusent_avant_toute_ecriture(base_durable, monkeypatch):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")

    def illisible():
        raise ValueError("tarifs d'équipe : chaîne invalide")

    monkeypatch.setattr(m5_outils, "_instantane_tarifs_equipes", illisible)
    _refus(wct_id, moteur.TARIFS_ILLISIBLES)


def test_tarifs_corrompus_dans_le_registre_refusent_sans_ecriture(base_durable):
    """Vraie corruption du registre des tarifs d'équipe (sa chaîne ne se vérifie plus), pas une injection."""
    from sqlalchemy import update

    from opsys.stockage.schema import REGISTRES

    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    with stockage.transaction() as cnx:
        try:
            cnx.execute(update(REGISTRES).where(
                REGISTRES.c.departement == "m05-financecore", REGISTRES.c.registre == "tarifs_equipes"
            ).values(maillon="{}"))
        except Exception as exc:  # registre append-only protégé par déclencheur : la corruption n'est pas possible
            pytest.skip(f"registre protégé contre la corruption : {exc}")
    _refus(wct_id, moteur.TARIFS_ILLISIBLES)


# -------------------------------------------------------------------------------------------
# Acteur, intention, identifiants : validation stricte
# -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("acteur", [
    "", " ", " nathan", "nathan ", "x" * 257, None, 7, b"nathan", "nat\nhan", "autre-personne",
])
def test_acteur_invalide_ou_different_de_la_session_refuse(base_durable, acteur):
    avant = _empreinte_base()
    with stockage.transaction() as cnx, pytest.raises(moteur.RefusRecalculM4) as exc:
        moteur.recalculer(cnx, cm._session_admin_certifie(), acteur=acteur, wct_id="a" * 64, devis_id=DEVIS,
                          intention_id="b" * 64)
    assert exc.value.code == moteur.ACTEUR_INVALIDE
    assert _empreinte_base() == avant


@pytest.mark.parametrize("intention", [
    "", "B" * 64, "b" * 63, "b" * 65, "g" * 64, None, 12, b"b" * 64, ("b" * 63) + "\n",
])
def test_intention_invalide_refuse(base_durable, intention):
    with stockage.transaction() as cnx, pytest.raises(moteur.RefusRecalculM4) as exc:
        moteur.recalculer(cnx, cm._session_admin_certifie(), acteur=cm.ADMIN_CERTIFIE, wct_id="a" * 64,
                          devis_id=DEVIS, intention_id=intention)
    assert exc.value.code == moteur.INTENTION_INVALIDE


@pytest.mark.parametrize(("wct_id", "devis_id"), [
    ("A" * 64, "D"), ("a" * 63, "D"), (None, "D"), ("a" * 64, ""), ("a" * 64, "d" * 257), ("a" * 64, None),
])
def test_identifiants_invalides_refusent(base_durable, wct_id, devis_id):
    with stockage.transaction() as cnx, pytest.raises(moteur.RefusRecalculM4) as exc:
        moteur.recalculer(cnx, cm._session_admin_certifie(), acteur=cm.ADMIN_CERTIFIE, wct_id=wct_id,
                          devis_id=devis_id, intention_id="b" * 64)
    assert exc.value.code == moteur.IDENTIFIANT_INVALIDE


def test_session_absente_ou_non_admin_ou_expiree_refuse(base_durable):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    avant = _empreinte_base()
    with stockage.transaction() as cnx, pytest.raises(moteur.RefusRecalculM4) as exc:
        moteur.recalculer(cnx, None, acteur=cm.ADMIN_CERTIFIE, wct_id=wct_id, devis_id=DEVIS,
                          intention_id=_intention("s"))
    assert exc.value.code == moteur.ACTEUR_INVALIDE
    for session in (Session("inconnu-fictif", frozenset({"admin"}), "csrf", int(time.time()) + 3600),
                    Session(cm.ADMIN_CERTIFIE, frozenset({"admin"}), "csrf", int(time.time()) - 5)):
        with stockage.transaction() as cnx, pytest.raises(moteur.RefusRecalculM4) as exc:
            moteur.recalculer(cnx, session, acteur=session.utilisateur, wct_id=wct_id, devis_id=DEVIS,
                              intention_id=_intention("s"))
        assert exc.value.code == moteur.AUTORITE_REFUSEE
    assert _empreinte_base() == avant


def test_la_meme_intention_avec_d_autres_parametres_est_un_conflit(base_durable):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    assert _recalculer(wct_id, intention="x")["statut"] == "publiee"
    _refus(wct_id, moteur.INTENTION_EN_CONFLIT, intention="x", devis_id="DEVIS-AUTRE")


def test_hors_transaction_ou_dans_une_portee_de_livraison_refuse(base_durable):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    with stockage.transaction() as cnx:
        jeton = sc._COURANTE.set(object())
        try:
            with pytest.raises(moteur.RefusRecalculM4) as exc:
                moteur.recalculer(cnx, cm._session_admin_certifie(), acteur=cm.ADMIN_CERTIFIE, wct_id=wct_id,
                                  devis_id=DEVIS, intention_id=_intention("l"))
        finally:
            sc._COURANTE.reset(jeton)
    assert exc.value.code == moteur.CONTEXTE_INVALIDE


# -------------------------------------------------------------------------------------------
# Pannes avant / après commit : jamais d'écriture partielle, la facture n'est jamais touchée
# -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("point", ["publication_evenement", "relecture_finale"])
def test_panne_dans_le_recalcul_n_ecrit_rien_et_ne_bloque_pas_l_appelant(base_durable, monkeypatch, point):
    from opsys.stockage.schema import JOURNAL

    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    registres, tables = _registres_par_nom(), _tables_par_nom()

    def panne(*a, **k):
        raise RuntimeError("panne simulée")

    with monkeypatch.context() as m:
        if point == "publication_evenement":  # après la trace, le reçu v2, l'attestation et les audits
            m.setattr(m5_outils, "_publier_rentabilite", panne)
        else:  # après TOUTES les écritures, y compris l'événement
            m.setattr(service_recalcul_m4, "lire_historique_v2", panne)
        with stockage.transaction() as cnx:
            with pytest.raises(RuntimeError, match="panne simulée"):
                moteur.recalculer(cnx, cm._session_admin_certifie(), acteur=cm.ADMIN_CERTIFIE, wct_id=wct_id,
                                  devis_id=DEVIS, intention_id=_intention("panne"))
            # la transaction de l'appelant n'est pas empoisonnée : une écriture indépendante (la sienne) passe
            assert cnx.get_transaction().is_active
            cnx.execute(insert(JOURNAL).values(quand="2026-09-16T11:00:00Z", par="appelant-fictif",
                                               action="e2.ecriture_independante", cible="facture-fictive"))
    with stockage.transaction() as cnx:
        assert cnx.execute(select(JOURNAL.c.cible).where(JOURNAL.c.action == "e2.ecriture_independante")
                           ).scalars().all() == ["facture-fictive"]
    assert _registres_par_nom() == registres, "aucun registre (facture comprise) n'a bougé"
    apres = _tables_par_nom()
    modifiees = {t for t in apres if apres[t] != tables.get(t)}
    assert modifiees <= {"journal", "sqlite_sequence"}, "seule l'écriture de l'appelant"
    assert _traces_certifiees() == 0
    assert _recalculer(wct_id, intention="panne")["statut"] == "publiee", "la reprise après panne publie"


def test_panne_avant_commit_de_l_appelant_annule_tout_puis_la_reprise_publie(base_durable):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    avant = _empreinte_base()
    with pytest.raises(RuntimeError, match="coupure"), stockage.transaction() as cnx:
        assert moteur.recalculer(cnx, cm._session_admin_certifie(), acteur=cm.ADMIN_CERTIFIE, wct_id=wct_id,
                                 devis_id=DEVIS, intention_id=_intention("coupure"))["statut"] == "publiee"
        raise RuntimeError("coupure avant le commit de l'appelant")
    assert _empreinte_base() == avant, "le commit n'a pas eu lieu : rien n'a été écrit"
    assert _recalculer(wct_id, intention="coupure")["statut"] == "publiee"


def test_panne_apres_commit_la_reprise_ne_republie_rien(base_durable):
    deps, wct_id = _chantier()
    cm._poser_politique("m4.recalculer_v3")
    premiere = _recalculer(wct_id, intention="apres")  # commit effectué ; la réponse « se perd »
    assert premiere["statut"] == "publiee"
    apres_commit = _empreinte_base()
    reprise = _recalculer(wct_id, intention="apres")
    assert reprise["statut"] == "deja_executee"
    assert reprise["historique"]["attestation"] == premiere["attestation"]
    assert _empreinte_base() == apres_commit
    assert _recalculer(wct_id, intention="encore-une-autre")["statut"] == "rien_a_faire"
    assert _empreinte_base() == apres_commit


# -------------------------------------------------------------------------------------------
# `ouvrir` reste fermé ; le moteur n'est branché nulle part
# -------------------------------------------------------------------------------------------
def test_ouvrir_reste_ferme_dans_les_deux_services(base_durable):
    from opsys import service_lecture_m4

    with stockage.transaction() as cnx:
        with pytest.raises(sc.RefusAutorite, match="RECALCUL_M4_NON_QUALIFIE"):
            service_recalcul_m4.ouvrir(cnx, cm._session_admin_certifie(), wct_id="a" * 64, devis_id=DEVIS,
                                       intention_id="b" * 64)
        with (pytest.raises(sc.RefusAutorite, match="LECTURE_M4_NON_QUALIFIEE"),
              service_lecture_m4.ouvrir(cnx, cm._session_admin_certifie(), wct_id="a" * 64, devis_id=DEVIS)):
            pytest.fail("la lecture ne doit pas s'ouvrir")  # pragma: no cover


def test_aucune_route_outil_ou_role_n_appelle_le_moteur():
    """Le nouveau module n'est référencé par aucun autre code de production, et importer le serveur MCP, la CLI, la
    console et les capacités ne le charge pas."""
    import subprocess
    import sys as _sys

    reference = []
    for racine in [RACINE / "src", *RACINE.glob("departments/*/src"), RACINE / "core" / "src"]:
        if not racine.exists():
            continue
        for chemin in racine.rglob("*"):
            if (chemin.suffix in {".py", ".ts", ".yaml", ".yml", ".json"} and chemin.is_file()
                    and "moteur_recalcul_m4" in chemin.read_text(encoding="utf-8", errors="ignore")):
                reference.append(chemin.relative_to(RACINE).as_posix())
    assert reference == [], reference
    assert (RACINE / "src" / "opsys" / "moteur_recalcul_m4.py").is_file()
    code = (
        "import sys, opsys.serveur_mcp, opsys.cli, opsys.capacites, opsys.console.application\n"
        "print('opsys.moteur_recalcul_m4' in sys.modules)"
    )
    sortie = subprocess.run([_sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120,
                            env={"PYTHONPATH": ":".join(p for p in _sys.path if p), "PATH": "/usr/bin"},
                            check=False)
    assert sortie.stdout.strip().endswith("False"), (sortie.stdout, sortie.stderr[-500:])
