"""Raccord CFO mandaté aux déclarations durables fictives, sans activation cash."""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from m5_financecore import outils
from sqlalchemy import select, update

from opsys import agent_cfo_grants, contexte, idempotence, identite, intentions_obligations_m5, stockage
from opsys.stockage.schema import META

FICTIF = True
ROOT = Path(__file__).resolve().parents[1]

def _helpers(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

GRANTS = _helpers("cfo_obligations_grants", ROOT / "tests/test_agent_cfo_grants.py")
CFO = _helpers("cfo_obligations_fixture", ROOT / "departments/m05-financecore/tests/test_dossier_decision_cfo.py")
ADMIN = contexte.IdentiteAppelante("admin.obligations.cfo.fictif", "admin")
DATE = "2026-10-01"
HORA = "2026-10-01T12:00:00+00:00"
ARGS = {"aujourd_hui": DATE, "question_posee": "Préparer les obligations fictives?"}

@pytest.fixture
def dossier(session, monkeypatch, tmp_path):
    profile = GRANTS.finance_profile.__wrapped__(session, monkeypatch)
    with GRANTS._as_owner(), session() as cnx:
        agent_cfo_grants.accorder(
            cnx, profile["id"], par=GRANTS.OWNER, instance_id=profile["instance_id"],
            revision_attendue=profile["revision"], version_attendue=0,
            date_debut_rapport="2026-10-01", date_fin_rapport="2026-10-31", rapports_par_jour=20,
        )
    with session() as cnx:
        identite.creer_personne(cnx, ADMIN.personne, "Admin fictif", "mot-de-passe-fictif-1234", ["admin"])
    outils.utiliser_stockage_durable()
    CFO._declarer_configuration(tmp_path, monkeypatch)
    CFO._peupler_snapshot_connu()
    yield profile
    outils.reinitialiser_stockage_mouvements()


def _declarer(
    montant="1000.00", *, revision=None, operation="declarer", cle="obligations-cfo-1",
    categorie="paies", **declaration,
):
    args = {
        "categorie": categorie, "operation": operation, "revision_attendue": revision, "motif": "FICTIF",
        "declaration": None if operation == "retirer" else {
            "montant": montant, "source": "déclaration fictive", "au": DATE,
            "echeance": "2026-10-09", "calendrier": None,
        },
    }
    if args["declaration"] is not None:
        args["declaration"].update(declaration)
    meta = idempotence.Meta(cle, "device-cfo-fictif", HORA)
    hora = contexte.HorodatageAppareil(meta.appareil, dt.datetime.fromisoformat(HORA), dt.datetime.fromisoformat(HORA))
    with (stockage.transaction(), contexte.appele_par_appareil(ADMIN), contexte.receptionne_de(hora),
          contexte.sortie_bornee(5400), intentions_obligations_m5.contexte_intention(meta, args)):
        result = outils.enregistrer_obligation_preparee_appareil(**args)
    assert result["accepte"] is True, result
    return result["resultat"]["reference"]


def _reference(cells):
    index, ligne_id, precedent = cells
    return {"registre": "obligations_preparees", "index": index,
            "ligne_id": ligne_id, "precedent_ligne_id": precedent}


def _tables_metier():
    with stockage.transaction() as cnx:
        return {name: [dict(row) for row in cnx.execute(select(table)).mappings()]
                for name, table in META.tables.items() if name != "agents_tickets_cfo"}


def _rapport(profile, session, *, volet=None, question_posee=ARGS["question_posee"]):
    args = {**ARGS, "question_posee": question_posee, **({"volet": volet} if volet is not None else {})}
    issued = GRANTS._issue(session, profile, "m5_preparer_dossier_decision_cfo", args)
    before = _tables_metier()
    with contexte.appele_avec_ticket_agent_cfo(issued["ticket"], args):
        result = outils.preparer_dossier_decision_cfo(**args)
    assert _tables_metier() == before
    assert result["accepte"] is True, result
    return result["resultat"]


def test_agent_mandate_lit_declaration_durable_sans_la_promouvoir_dans_cash(dossier, session):
    avant = _rapport(dossier, session)
    assert "obligations_preparees" not in avant
    cash_avant = avant["rubriques"][1]["contenu"]["cash_libre_cad"]
    assert cash_avant is not None
    ref = _declarer()
    rapport = _rapport(dossier, session)
    assert rapport["rubriques"][1]["contenu"]["cash_libre_cad"] == cash_avant
    contexte_ob = rapport["obligations_preparees"]
    assert contexte_ob["statut"] == "PREPARATOIRE_NON_ATTESTE"
    assert contexte_ob["utilisee_pour_cash"] is False
    paie = contexte_ob["lecture"]["obligations"][0]
    assert paie["categorie"] == "paies"
    assert paie["declaration"]["montant"] == "1000.00"
    assert _reference(paie["reference"]) == ref
    assert len(rapport["rubriques"]) == 25


def test_correction_retrait_et_restart_changent_source_hash_pas_cash(dossier, session):
    cash_avant = _cash()
    configuration_avant = outils._configuration_manifeste()
    ref1 = _declarer()
    first = _rapport(dossier, session, volet="obligations_preparees")
    full = _rapport(dossier, session)
    assert first["reference"] == full["reference"]
    ref2 = _declarer("1200.00", revision=ref1, cle="obligations-cfo-2")
    stockage.liberer()
    second = _rapport(dossier, session, volet="obligations_preparees")
    _refus_budget(dossier, session)
    row = second["obligations_preparees"]["lecture"]["obligations"][0]
    assert row["declaration"]["montant"] == "1200.00"
    assert _reference(row["reference"]) == ref2 and _reference(row["revision_precedente"]) == ref1
    assert first["reference"]["snapshot_id"] != second["reference"]["snapshot_id"]
    ref3 = _declarer(operation="retirer", revision=ref2, cle="obligations-cfo-3")
    stockage.liberer()
    third = _rapport(dossier, session, volet="obligations_preparees")
    retired = third["obligations_preparees"]["lecture"]["obligations"][0]
    assert retired["etat_declaration"] == "RETIREE" and retired["declaration"] is None
    assert _reference(retired["reference"]) == ref3 and _reference(retired["revision_precedente"]) == ref2
    assert third["reference"]["snapshot_id"] != second["reference"]["snapshot_id"]
    assert _cash() == cash_avant and outils._configuration_manifeste() == configuration_avant
    assert third["obligations_preparees"]["lecture"]["categories_absentes"] == ["das", "dettes"]


def test_zero_declare_est_distinct_des_categories_absentes(dossier, session):
    ref = _declarer("0.00")
    rapport = _rapport(dossier, session)
    lecture = rapport["obligations_preparees"]["lecture"]
    assert lecture["categories_absentes"] == ["das", "dettes"]
    assert _reference(lecture["obligations"][0]["reference"]) == ref
    assert lecture["obligations"][0]["declaration"]["montant"] == "0.00"
    assert lecture["obligations"][0]["etat_declaration"] == "DECLAREE"
    assert any("obligations_preparees" in m for m in rapport["rubriques"][5]["manque"])


def _issue(profile, session):
    return GRANTS._issue(session, profile, "m5_preparer_dossier_decision_cfo", ARGS)["ticket"]


def test_grant_revoque_refuse_avant_snapshot_meme_journal_corrompu(dossier, session, monkeypatch):
    _declarer()
    CFO._corrompre_maillon("obligations_preparees", 0, "categorie", "faux")
    ticket = _issue(dossier, session)
    with GRANTS._as_owner(), session() as cnx:
        current = agent_cfo_grants.lire(cnx, dossier["id"], instance_id=dossier["instance_id"])
        agent_cfo_grants.revoquer(cnx, dossier["id"], par=GRANTS.OWNER,
                                 instance_id=dossier["instance_id"], version_attendue=current["version"])
    reads = []
    original = outils._snapshot_obligations_preparees
    def read():
        reads.append("metier")
        return original()
    monkeypatch.setattr(outils, "_snapshot_obligations_preparees", read)
    before = _tables_metier()
    with contexte.appele_avec_ticket_agent_cfo(ticket, ARGS), pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        outils.preparer_dossier_decision_cfo(**ARGS)
    assert reads == [] and _tables_metier() == before


def test_grant_valide_chaine_obligations_corrompue_refuse_sans_rapport(dossier, session):
    _declarer()
    CFO._corrompre_maillon("obligations_preparees", 0, "declaration", None)
    ticket = _issue(dossier, session)
    before = _tables_metier()
    with contexte.appele_avec_ticket_agent_cfo(ticket, ARGS):
        result = outils.preparer_dossier_decision_cfo(**ARGS)
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-M5-OBLIGATIONS-REGISTRE-INVALIDE"
    assert _tables_metier() == before and "resultat" not in result


def test_enveloppe_bornee_refuse_sans_tronquer_rubriques_ou_provenance(dossier, session):
    _declarer()
    ticket = _issue(dossier, session)
    before = _tables_metier()
    with contexte.sortie_bornee(800), contexte.appele_avec_ticket_agent_cfo(ticket, ARGS):
        result = outils.preparer_dossier_decision_cfo(**ARGS)
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-PREVISION-REPONSE-TROP-GROSSE"
    assert _tables_metier() == before and "resultat" not in result


def test_dossier_riche_trois_categories_refuse_budget_existant_sans_troncature(dossier, session):
    for categorie in ("paies", "das", "dettes"):
        _declarer(categorie=categorie, cle=f"obligations-cfo-{categorie}")
    ticket = _issue(dossier, session)
    before = _tables_metier()
    with contexte.appele_avec_ticket_agent_cfo(ticket, ARGS):
        result = outils.preparer_dossier_decision_cfo(**ARGS)
    assert result["accepte"] is False
    assert result["verdict"]["code"] == "REJ-PREVISION-REPONSE-TROP-GROSSE"
    assert _tables_metier() == before and "resultat" not in result


@pytest.mark.parametrize("source,calendrier,expected", [
    (None, None, "INCOMPLETE"),
    ("déclaration fictive", {
        "autorite": "autorité fictive", "periode_debut": "2026-09-01", "periode_fin": "2026-09-30",
        "echeance_source": "pièce fictive", "source_consultee_le": "2026-09-01",
        "source_applicable_du": "2026-01-01", "source_applicable_jusqu_au": "2026-09-29",
        "annee": 2026, "version": "FICTIF-2026",
    }, "SOURCE_PERIMEE"),
])
def test_source_absente_ou_perimee_reste_inconnue_sans_promouvoir_montant(
    dossier, session, source, calendrier, expected
):
    _declarer(source=source, calendrier=calendrier, echeance="2026-09-30")
    cash_avant = _cash()
    rapport = _rapport(dossier, session, volet="obligations_preparees")
    if expected == "SOURCE_PERIMEE":
        _refus_budget(dossier, session)
    row = rapport["obligations_preparees"]["lecture"]["obligations"][0]
    state = row["calendrier_preparatoire"]
    assert state["statut"] == expected
    assert state["montant_utilisable"] is None
    assert state["echeance_statut"] == "PASSEE_A_VERIFIER"
    assert row["declaration"]["montant"] == "1000.00"
    assert rapport["obligations_preparees"]["utilisee_pour_cash"] is False

    assert _cash() == cash_avant


def test_vue_ciblee_lit_trois_categories_riches_sans_troncature(dossier, session):
    avant = _rapport(dossier, session)
    refs = {}
    calendrier = {
        "autorite": "autorité fictive", "periode_debut": "2026-09-01", "periode_fin": "2026-09-30",
        "echeance_source": "pièce fictive", "source_consultee_le": "2026-09-01",
        "source_applicable_du": "2026-01-01", "source_applicable_jusqu_au": "2026-12-31",
        "annee": 2026, "version": "FICTIF-2026",
    }
    for categorie in ("paies", "das", "dettes"):
        refs[categorie] = _declarer(categorie=categorie, calendrier=calendrier, cle=f"vue-cfo-{categorie}")
    rapport = _rapport(dossier, session, volet="obligations_preparees", question_posee="F" * 1000)
    assert rapport["type"] == "VUE_OBLIGATIONS_PREPAREES_CFO"
    assert rapport["version_contrat"] == "v1"
    assert rapport["question_posee"] == "F" * 1000
    assert rapport["reference"]["aujourd_hui"] == DATE
    assert rapport["reference"]["snapshot_id"] != avant["reference"]["snapshot_id"]
    assert "rubriques" not in rapport
    assert len(json.dumps(rapport, ensure_ascii=False)) <= outils.BUDGET_SORTIE
    contexte_ob = rapport["obligations_preparees"]
    assert contexte_ob["utilisee_pour_cash"] is False
    assert contexte_ob["lecture"]["categories_absentes"] == []
    rows = contexte_ob["lecture"]["obligations"]
    assert {row["categorie"] for row in rows} == set(refs)
    for row in rows:
        assert _reference(row["reference"]) == refs[row["categorie"]]
        assert row["declaration"]["montant"] == "1000.00"
        assert row["declaration"]["calendrier"] == calendrier
        assert row["calendrier_preparatoire"]["statut"] == "DOCUMENTEE_A_VALIDER"
        assert row["calendrier_preparatoire"]["montant_utilisable"] == "1000.00"
    source = rapport["sources"]["lignes"][contexte_ob["source_ref"]]
    assert source[1:3] == ["obligations_preparees", 3]
    assert source[3] == refs["dettes"]["ligne_id"]

    _refus_budget(dossier, session)


def _cash():
    with stockage.transaction(), contexte.appele_par_appareil(ADMIN):
        result = outils.etat_tresorerie()
    assert result.get("accepte") is not False, result
    assert result["cash_libre"]["cash_libre"] is not None
    return result["cash_libre"]


def _refus_budget(profile, session, *, volet=None):
    args = {**ARGS, **({"volet": volet} if volet is not None else {})}
    ticket = GRANTS._issue(session, profile, "m5_preparer_dossier_decision_cfo", args)["ticket"]
    before = _tables_metier()
    with contexte.appele_avec_ticket_agent_cfo(ticket, args):
        result = outils.preparer_dossier_decision_cfo(**args)
    assert result["accepte"] is False and "resultat" not in result
    assert result["verdict"]["code"] == "REJ-PREVISION-REPONSE-TROP-GROSSE"
    assert _tables_metier() == before


def test_vue_vide_est_absence_explicite_hash_legacy_et_capture_unique(dossier, session, monkeypatch):
    legacy = _rapport(dossier, session)
    reads = []
    original_ob = outils._snapshot_obligations_preparees
    original_finance = outils._lectures_finance
    def ob_read():
        reads.append("obligations")
        return original_ob()
    def finance_read(*args, **kwargs):
        reads.append("finance")
        return original_finance(*args, **kwargs)
    monkeypatch.setattr(outils, "_snapshot_obligations_preparees", ob_read)
    monkeypatch.setattr(outils, "_lectures_finance", finance_read)
    vue = _rapport(dossier, session, volet="obligations_preparees")
    assert reads == ["obligations", "finance"]
    assert vue["reference"] == legacy["reference"]
    assert "obligations_preparees" not in legacy
    projected = vue["obligations_preparees"]
    assert projected["lecture"] == {"categories_absentes": ["paies", "das", "dettes"], "obligations": []}
    assert vue["sources"]["lignes"][projected["source_ref"]] == [
        "m05-financecore", "obligations_preparees", 0, None,
    ]
    assert projected["utilisee_pour_cash"] is False
    assert _rapport(dossier, session, volet="dossier_complet") == legacy


@pytest.mark.parametrize("case", ["invalide", "revoque", "instance_etrangere", "volet_contexte",
                                   "volet_ticket", "date_contexte"])
def test_vue_ticket_lie_arguments_effectifs_refuse_avant_toutes_sources(
    dossier, session, monkeypatch, case,
):
    issued_args = {**ARGS, "volet": "obligations_preparees"}
    ticket = GRANTS._issue(session, dossier, "m5_preparer_dossier_decision_cfo", issued_args)["ticket"]
    actual, transmitted = dict(issued_args), dict(issued_args)
    if case == "invalide":
        ticket = "x" * 48
    elif case == "revoque":
        with GRANTS._as_owner(), session() as cnx:
            current = agent_cfo_grants.lire(cnx, dossier["id"], instance_id=dossier["instance_id"])
            agent_cfo_grants.revoquer(cnx, dossier["id"], par=GRANTS.OWNER,
                                     instance_id=dossier["instance_id"], version_attendue=current["version"])
    elif case == "instance_etrangere":
        table = agent_cfo_grants.AGENTS_TICKETS_CFO
        with session() as cnx:
            cnx.execute(update(table).where(table.c.ticket_hash == hashlib.sha256(ticket.encode()).hexdigest())
                        .values(instance_id="instance-etrangere-fictive"))
    elif case == "volet_contexte":
        actual["volet"] = "dossier_complet"
    elif case == "volet_ticket":
        actual["volet"] = transmitted["volet"] = "dossier_complet"
    else:
        actual["aujourd_hui"] = "2026-10-02"
    # Un journal altéré distingue le refus d'autorité de toute capture métier.
    _declarer()
    CFO._corrompre_maillon("obligations_preparees", 0, "categorie", "faux")
    reads = []
    def capture(*args, **kwargs):
        reads.append("source métier")
        raise AssertionError("aucune capture métier autorisée")
    monkeypatch.setattr(outils, "_snapshot_obligations_preparees", capture)
    monkeypatch.setattr(outils, "_lectures_finance", capture)
    before = _tables_metier()
    with contexte.appele_avec_ticket_agent_cfo(ticket, transmitted), pytest.raises(agent_cfo_grants.GrantCfoRefuse):
        outils.preparer_dossier_decision_cfo(**actual)
    assert reads == [] and _tables_metier() == before


def test_vue_grant_valide_journal_corrompu_refuse_sans_absence(dossier, session):
    _declarer()
    CFO._corrompre_maillon("obligations_preparees", 0, "declaration", None)
    args = {**ARGS, "volet": "obligations_preparees"}
    ticket = GRANTS._issue(session, dossier, "m5_preparer_dossier_decision_cfo", args)["ticket"]
    before = _tables_metier()
    with contexte.appele_avec_ticket_agent_cfo(ticket, args):
        result = outils.preparer_dossier_decision_cfo(**args)
    assert result["accepte"] is False and "resultat" not in result
    assert result["verdict"]["code"] == "REJ-M5-OBLIGATIONS-REGISTRE-INVALIDE"
    assert _tables_metier() == before


def test_schema_volet_enum_et_arguments_inconnus_refuses():
    from jsonschema import ValidationError, validate
    tool = next(t for t in outils.outils() if t.nom == "m5_preparer_dossier_decision_cfo")
    validate(ARGS, tool.parametres)
    for volet in ("dossier_complet", "obligations_preparees"):
        validate({**ARGS, "volet": volet}, tool.parametres)
    for changes in ({"volet": "inconnu"}, {"volet": None}, {"cash": "0.00"}):
        with pytest.raises(ValidationError):
            validate({**ARGS, **changes}, tool.parametres)


def test_vue_borne_active_refuse_sans_troncature(dossier, session):
    _declarer()
    args = {**ARGS, "volet": "obligations_preparees"}
    ticket = GRANTS._issue(session, dossier, "m5_preparer_dossier_decision_cfo", args)["ticket"]
    before = _tables_metier()
    with contexte.sortie_bornee(800), contexte.appele_avec_ticket_agent_cfo(ticket, args):
        result = outils.preparer_dossier_decision_cfo(**args)
    assert result["accepte"] is False and "resultat" not in result
    assert result["verdict"]["code"] == "REJ-PREVISION-REPONSE-TROP-GROSSE"
    assert _tables_metier() == before
