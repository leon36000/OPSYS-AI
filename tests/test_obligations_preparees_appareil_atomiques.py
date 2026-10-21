"""Corrélation interne : conservation du corps et isolation entre appels M5."""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect, text, update

from opsys import contexte, idempotence, identite, stockage
from opsys import intentions_obligations_m5 as liaison
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import MUTATIONS_APPLIQUEES


def _args():
    return {"categorie": "paies", "operation": "declarer", "declaration": {
        "montant": "0.00", "source": " source déclarée ", "au": None,
        "echeance": None, "calendrier": None,
    }, "revision_attendue": None, "motif": " déclaration "}


def _meta(cle="00000000-0000-4000-8000-000000000001"):
    return idempotence.Meta(cle, "DEVICE-FICTIF", "2026-10-09T08:00:00.000-04:00")


def test_corps_fige_et_relecture_ne_peuvent_modifier_la_correlation():
    args = _args()
    original = _args()
    meta = _meta()
    assert liaison.intention_courante() is None
    with liaison.contexte_intention(meta, args):
        args["declaration"]["montant"] = "999.00"
        lu_meta, lu_args = liaison.intention_courante()
        assert lu_meta == meta and lu_meta.horodatage_appareil == "2026-10-09T08:00:00.000-04:00"
        assert lu_args == original
        lu_args["declaration"]["source"] = "réécriture"
        assert liaison.intention_courante() == (meta, original)
    assert liaison.intention_courante() is None


def test_exception_et_contexte_imbrique_ne_fuitent_pas_une_autre_intention():
    parent = _meta()
    enfant = _meta("00000000-0000-4000-8000-000000000002")
    with liaison.contexte_intention(parent, _args()):
        with pytest.raises(RuntimeError, match="panne fictive"), liaison.contexte_intention(enfant, _args()):
            assert liaison.intention_courante()[0] == enfant
            raise RuntimeError("panne fictive")
        assert liaison.intention_courante()[0] == parent
    assert liaison.intention_courante() is None


@pytest.mark.parametrize("meta,args", [(None, _args()), (_meta(), []), (_meta(), {"montant": float("nan")})])
def test_correlation_non_json_ou_sans_meta_ne_publie_aucun_contexte(meta, args):
    with pytest.raises((TypeError, ValueError)), liaison.contexte_intention(meta, args):
        pytest.fail("un contexte invalide a été publié")
    assert liaison.intention_courante() is None


WRITER = "m5_enregistrer_obligation_preparee_appareil"
ACTEUR = "admin-declaration-m5-fictif"
READER = "m5_lire_obligations_preparees_appareil"
LECTURE = {"aujourd_hui": "2026-10-09", "decalage": 0, "limite": 1}


def _tables(cnx):
    return {name: sorted(map(tuple, cnx.execute(text(
        'SELECT * FROM "' + name.replace('"', '""') + '"',
    )).all()), key=repr) for name in inspect(cnx).get_table_names()}


def _cap(limite=5400):
    return Capacites(charger_departements(), stockage.transaction, limite_sortie=limite, memoire=False)


def _admin(cnx):
    identite.creer_personne(cnx, ACTEUR, "Déclarant fictif", "mot-de-passe-fictif-12345", ["admin"])


def test_console_avec_meta_ne_cree_ni_claim_ni_trace_positive(session):
    with session() as cnx:
        _admin(cnx)
        before = _tables(cnx)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(ACTEUR, "admin", source="console")):
        response = _cap().appeler(WRITER, _args(), meta=_meta())
    assert response.get("statut") != "en_attente_approbation"
    with session() as cnx:
        assert _tables(cnx) == before


def test_intention_device_positive_donne_son_maillon_rejouable_sans_nouvel_effet(session):
    with session() as cnx:
        _admin(cnx)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    with contexte.appele_par_appareil(identity):
        response = _cap().appeler(WRITER, _args(), meta=_meta())
    assert response.get("ok") is True and response["resultat"].get("accepte") is True, response
    with session() as cnx:
        after = _tables(cnx)
    with contexte.appele_par_appareil(identity):
        replay = _cap().appeler(WRITER, _args(), meta=_meta())
    assert replay == {**response, "rejoue": True}
    with session() as cnx:
        assert _tables(cnx) == after


@pytest.mark.parametrize("patch", [
    {"horodatage_appareil": "2026-10-09T09:00:00-04:00"},
    {"statut": "en_cours"}, {"reponse": "{"}, {"reponse": "null"}, {"reponse": "[]"},
])
def test_cache_ou_claim_corrompu_reste_inconnu_sans_nouveau_maillon(session, patch):
    with session() as cnx:
        _admin(cnx)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    with contexte.appele_par_appareil(identity):
        accepted = _cap().appeler(WRITER, _args(), meta=_meta())
    assert accepted["resultat"]["accepte"] is True
    with session() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).values(**patch))
        before = _tables(cnx)
    with contexte.appele_par_appareil(identity):
        response = _cap().appeler(WRITER, _args(), meta=_meta())
    assert response.get("ok") is False and "resultat" not in response, response
    with session() as cnx:
        assert _tables(cnx) == before


def test_panne_apres_trace_annule_claim_maillon_et_journal_puis_retry(session, monkeypatch):
    from opsys import approbations

    with session() as cnx:
        _admin(cnx)
        before = _tables(cnx)
    original = approbations.tracer_validation_au_depart

    def panne(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("panne fictive après trace")

    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    monkeypatch.setattr(approbations, "tracer_validation_au_depart", panne)
    with contexte.appele_par_appareil(identity), pytest.raises(RuntimeError, match="après trace"):
        _cap().appeler(WRITER, _args(), meta=_meta())
    with session() as cnx:
        assert _tables(cnx) == before
    monkeypatch.setattr(approbations, "tracer_validation_au_depart", original)
    with contexte.appele_par_appareil(identity):
        response = _cap().appeler(WRITER, _args(), meta=_meta())
    assert response["resultat"]["accepte"] is True and response["rejoue"] is False


def test_refus_revision_perimee_ne_trace_pas_une_acceptation_n3(session):
    with session() as cnx:
        _admin(cnx)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    with contexte.appele_par_appareil(identity):
        accepted = _cap().appeler(WRITER, _args(), meta=_meta())
    assert accepted["resultat"]["accepte"] is True
    with session() as cnx:
        before = _tables(cnx)
    second = _meta("00000000-0000-4000-8000-000000000002")
    with contexte.appele_par_appareil(identity):
        refused = _cap().appeler(WRITER, _args(), meta=second)
    assert refused["resultat"]["accepte"] is False, refused
    with session() as cnx:
        after = _tables(cnx)
        assert {k: v for k, v in after.items() if k != "mutations_appliquees"} == {
            k: v for k, v in before.items() if k != "mutations_appliquees"
        }
        assert len(after["mutations_appliquees"]) == len(before["mutations_appliquees"]) + 1
    with contexte.appele_par_appareil(identity):
        replay = _cap().appeler(WRITER, _args(), meta=second)
    assert replay.get("ok") is False and "resultat" not in replay
    with session() as cnx:
        assert _tables(cnx) == after


@pytest.mark.parametrize("limite", [40, 550, 800])
@pytest.mark.parametrize("replay", [False, True])
def test_quota_fresh_et_rejeu_refusent_avant_tout_effet(session, limite, replay):
    with session() as cnx:
        _admin(cnx)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    if replay:
        with contexte.appele_par_appareil(identity):
            assert _cap().appeler(WRITER, _args(), meta=_meta())["resultat"]["accepte"] is True
    with session() as cnx:
        before = _tables(cnx)
    with contexte.appele_par_appareil(identity):
        refused = _cap(limite).appeler(WRITER, _args(), meta=_meta())
    assert refused.get("ok") is False and "resultat" not in refused, refused
    with session() as cnx:
        assert _tables(cnx) == before


@pytest.mark.parametrize("limite", [40, 550, 5400])
def test_lecture_m5_est_courante_pure_et_sans_artefact(session, limite):
    with session() as cnx:
        _admin(cnx)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    with contexte.appele_par_appareil(identity):
        assert _cap().appeler(WRITER, _args(), meta=_meta())["resultat"]["accepte"] is True
    with session() as cnx:
        before = _tables(cnx)
    with contexte.appele_par_appareil(identity):
        response = _cap(limite).appeler(READER, LECTURE)
    if limite == 5400:
        assert response["ok"] is True and response["resultat"]["accepte"] is True
        rows = response["resultat"]["resultat"]["obligations"]
        assert rows[0]["declaration"]["montant"] == "0.00"
    else:
        assert response.get("ok") is False or response["resultat"]["accepte"] is False
    with session() as cnx:
        assert _tables(cnx) == before


@pytest.mark.parametrize("retrait", ["role", "inactive"])
@pytest.mark.parametrize("replay", [False, True])
def test_autorite_sql_courante_revoquee_avant_claim_cache_et_lecture(session, retrait, replay):
    with session() as cnx:
        _admin(cnx)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    if replay:
        with contexte.appele_par_appareil(identity):
            assert _cap().appeler(WRITER, _args(), meta=_meta())["resultat"]["accepte"] is True
    with session() as cnx:
        if retrait == "role":
            identite.retirer_role(cnx, ACTEUR, "admin")
        else:
            identite.activer(cnx, ACTEUR, False)
        before = _tables(cnx)
    with contexte.appele_par_appareil(identity):
        response = _cap().appeler(WRITER, _args(), meta=_meta())
        read = _cap().appeler(READER, LECTURE)
    assert response.get("ok") is False and read.get("ok") is False
    with session() as cnx:
        assert _tables(cnx) == before


def test_propre_ack_historique_survit_revision_retrait_autre_auteur_et_redemarrage(session):
    with session() as cnx:
        _admin(cnx)
        identite.creer_personne(cnx, "autre-admin-m5-fictif", "Autre fictif", "mot-de-passe-fictif-12345", ["admin"])
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    with contexte.appele_par_appareil(identity):
        initial = _cap().appeler(WRITER, _args(), meta=_meta())
        ref = initial["resultat"]["resultat"]["reference"]
        revision = _args()
        revision["revision_attendue"] = ref
        revision["declaration"]["montant"] = "17.50"
        second = _cap().appeler(WRITER, revision, meta=_meta("00000000-0000-4000-8000-000000000002"))
        assert second["resultat"]["accepte"] is True
        retired = {**_args(), "operation": "retirer", "declaration": None,
                   "revision_attendue": second["resultat"]["resultat"]["reference"]}
        removed = _cap().appeler(WRITER, retired, meta=_meta("00000000-0000-4000-8000-000000000003"))
        assert removed["resultat"]["accepte"] is True
    other = contexte.IdentiteAppelante("autre-admin-m5-fictif", "admin", source="appareil")
    with contexte.appele_par_appareil(other):
        foreign = {**_args(), "categorie": "das"}
        appended = _cap().appeler(WRITER, foreign, meta=_meta("00000000-0000-4000-8000-000000000004"))
        assert appended["resultat"]["accepte"] is True
    stockage.liberer()
    with session() as cnx:
        before = _tables(cnx)
    with contexte.appele_par_appareil(identity):
        replay = _cap().appeler(WRITER, _args(), meta=_meta())
        current = _cap().appeler(READER, LECTURE)
    assert replay == {**initial, "rejoue": True}
    row = current["resultat"]["resultat"]["obligations"][0]
    assert row["etat_declaration"] == "RETIREE" and row["declaration"] is None
    with session() as cnx:
        assert _tables(cnx) == before


@pytest.mark.parametrize("field", ["version_schema", "registre", "intention", "auteur"])
def test_ack_corrompu_ou_copie_ne_terminalise_pas_son_intention(session, field):
    with session() as cnx:
        _admin(cnx)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    with contexte.appele_par_appareil(identity):
        response = _cap().appeler(WRITER, _args(), meta=_meta())
    bad = copy.deepcopy({k: v for k, v in response.items() if k != "rejoue"})
    if field == "version_schema":
        bad["resultat"][field] = True
    elif field == "registre":
        bad["resultat"][field] = "principal"
    elif field == "intention":
        bad["resultat"]["resultat"][field]["intention_uuid"] = "uuid-autre-intention"
    else:
        bad["resultat"]["resultat"][field]["personne"] = "autre-admin-m5-fictif"
    with session() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).values(reponse=json.dumps(bad, ensure_ascii=False)))
        before = _tables(cnx)
    with contexte.appele_par_appareil(identity):
        replay = _cap().appeler(WRITER, _args(), meta=_meta())
    assert replay.get("ok") is False and "resultat" not in replay
    with session() as cnx:
        assert _tables(cnx) == before


def test_postflight_whole_envelope_annule_tout_si_dispatch_deborde(session, monkeypatch):
    with session() as cnx:
        _admin(cnx)
        before = _tables(cnx)
    cap = _cap()
    original = cap._distribuer

    def debordement(*args, **kwargs):
        response = original(*args, **kwargs)
        return {**response, "details": "x" * 5400}

    monkeypatch.setattr(cap, "_distribuer", debordement)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    with contexte.appele_par_appareil(identity), pytest.raises(RuntimeError, match="hors borne"):
        cap.appeler(WRITER, _args(), meta=_meta())
    with session() as cnx:
        assert _tables(cnx) == before


@pytest.mark.parametrize("nom,replay", [(READER, False), (WRITER, False), (WRITER, True)])
def test_portee_manifestes_revalidee_avant_lecture_claim_et_cache(session, monkeypatch, nom, replay):
    from m5_financecore import outils

    with session() as cnx:
        _admin(cnx)
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    if replay:
        with contexte.appele_par_appareil(identity):
            assert _cap().appeler(WRITER, _args(), meta=_meta())["resultat"]["accepte"] is True
    cap = _cap()
    cap._portees_roles = {"admin": frozenset()}

    def source_interdite():
        pytest.fail("la portée doit être revérifiée avant toute source métier")

    monkeypatch.setattr(outils, "_snapshot_obligations_preparees", source_interdite)
    with session() as cnx:
        before = _tables(cnx)
    with contexte.appele_par_appareil(identity):
        response = cap.appeler(nom, LECTURE if nom == READER else _args(),
                               meta=None if nom == READER else _meta())
    assert response.get("ok") is False
    with session() as cnx:
        assert _tables(cnx) == before


@pytest.mark.parametrize("meme_uuid", [False, True])
def test_concurrence_cap_un_seul_maillon_et_une_seule_trace_n3(session, meme_uuid):
    with session() as cnx:
        _admin(cnx)
        before = _tables(cnx)
    barrier = Barrier(2)

    def appeler(n):
        identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
        cle = "00000000-0000-4000-8000-00000000000" + str(1 if meme_uuid else n)
        barrier.wait(timeout=10)
        with contexte.appele_par_appareil(identity):
            return _cap().appeler(WRITER, _args(), meta=_meta(cle))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(appeler, [1, 2]))
    assert sum(r.get("rejoue") is False and r.get("resultat", {}).get("accepte") is True for r in results) == 1
    if meme_uuid:
        assert sum(r.get("rejoue") is True for r in results) == 1
    else:
        assert sum(r.get("resultat", {}).get("accepte") is False for r in results) == 1
    with session() as cnx:
        after = _tables(cnx)
        traces = cnx.execute(text("SELECT statut, niveau, decide_par FROM approbations")).all()
        assert list(map(tuple, traces)) == [("executee", "N3", ACTEUR)]
    assert len(after["registres_maillons"]) == len(before["registres_maillons"]) + 1
    assert len(after["approbations"]) == len(before["approbations"]) + 1
    assert len(after["journal"]) == len(before["journal"]) + 1
    assert len(after["mutations_appliquees"]) == len(before["mutations_appliquees"]) + (1 if meme_uuid else 2)
    writes = {"registres_maillons", "journal", "mutations_appliquees", "approbations"}
    assert {k: v for k, v in after.items() if k not in writes} == {
        k: v for k, v in before.items() if k not in writes
    }


@pytest.mark.parametrize("field,value", [("montant", float("nan")), ("source", "\ud800")])
def test_arguments_non_json_stricts_rendent_refus_ferme_avant_correlation(session, field, value):
    with session() as cnx:
        _admin(cnx)
        before = _tables(cnx)
    args = _args()
    args["declaration"][field] = value
    identity = contexte.IdentiteAppelante(ACTEUR, "admin", source="appareil")
    with contexte.appele_par_appareil(identity):
        response = _cap().appeler(WRITER, args, meta=_meta())
    assert response.get("ok") is False and response["erreur"] == "REJ-M5-OBLIGATIONS-ARGUMENTS-INVALIDES"
    assert liaison.intention_courante() is None
    with session() as cnx:
        assert _tables(cnx) == before
