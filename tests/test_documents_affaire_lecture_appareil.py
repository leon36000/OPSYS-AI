"""Lectures SQLite fictives et identité injectée ; aucun Cap/HTTP/DEVICE opaque."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, update

from opsys import approbations, contexte, idempotence, identite, stockage
from opsys.stockage.schema import REGISTRES

FICTIF = True
_SPEC = importlib.util.spec_from_file_location(
    "fixture_transactions_documentaires_fictive",
    Path(__file__).with_name("test_documents_affaire_transactions.py"),
)
_FX = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _FX
_SPEC.loader.exec_module(_FX)
monde = _FX.monde
ACTEUR, AFFAIRE, ARGS, HORA = _FX.ACTEUR, _FX.AFFAIRE, _FX.ARGS, _FX.HORA
tables = _FX._tables


def module():
    assert importlib.util.find_spec("opsys.documents_affaire_lecture_appareil") is not None, "lecteur SQLite non livré"
    return importlib.import_module("opsys.documents_affaire_lecture_appareil")


def commande(decalage=0, limite=1):
    return {"affaire_id": AFFAIRE, "decalage": decalage, "limite": limite}


def lire(cnx, operation="lister", args=None, *, actor=ACTEUR, quota=6000, mode="ombre"):
    with contexte.appele_par_appareil(actor):
        return module().lire_document_m10(
            cnx, operation, commande() if args is None else args, quota=quota, mode_manifeste=mode,
        )


def deposer(cnx, args=None, cle="depot-lecture-fictif"):
    return _FX._call(cnx, args=ARGS if args is None else args, meta=idempotence.Meta(cle, "device-fictif", HORA))


def detail(ack):
    return {"affaire_id": AFFAIRE, "document_ref": ack["document_ref"], "version_source": ack["version_source"]}


def test_affaire_connue_index_vide_couple_entier_sans_rejoue_et49tables(monde):
    with stockage.transaction() as cnx:
        avant = tables(cnx)
        response = lire(cnx)
        assert response == {"ok": True, "resultat": {"accepte": True, "resultat": {
            "version_schema": 1, "affaire_id": AFFAIRE, "decalage": 0, "limite": 1,
            "total_versions": 0, "suivant_decalage": None, "versions": [],
        }}}
        assert len(avant) == 49 and tables(cnx) == avant


def test_index_et_detail_octets_originaux_sans_trace_claim_ou_publication(monde):
    with stockage.transaction() as cnx:
        ack = deposer(cnx)["resultat"]["resultat"]
        avant = tables(cnx)
        index = lire(cnx)["resultat"]["resultat"]
        precise = lire(cnx, "lire", detail(ack))["resultat"]["resultat"]
        assert set(index) == {
            "version_schema", "affaire_id", "decalage", "limite", "total_versions", "suivant_decalage", "versions",
        }
        row = index["versions"][0]
        assert len(row) == 16 and "corps" not in row and "intention" not in row
        assert row["document_ref"] == ack["document_ref"] and row["version_source"] == ack["version_source"]
        assert precise["corps"] == _FX.CORPS and len(precise) == 14
        assert tables(cnx) == avant and len(avant) == 49
        precise["auteur"]["personne"] = "autre-fictif"
        assert lire(cnx, "lire", detail(ack))["resultat"]["resultat"]["auteur"]["personne"] == ACTEUR.personne


def test_pages_courantes_v2_activation_et_retrait_puis_reopen(monde):
    with stockage.transaction() as cnx:
        ack = deposer(cnx)["resultat"]["resultat"]
        active = _FX._call(cnx, "activer", {**detail(ack), "activation_attendue": None},
                          meta=idempotence.Meta("activation-lecture", "device-fictif", HORA))
        second = deposer(cnx, {**ARGS, "document_ref": ack["document_ref"],
                             "version_precedente": ack["version_source"], "corps": "V2 fictive 😀\r\n"}, "v2-lecture")
        avant = tables(cnx)
        page1 = lire(cnx)["resultat"]["resultat"]
        page2 = lire(cnx, args=commande(1))["resultat"]["resultat"]
        assert page1["total_versions"] == 2 and page1["suivant_decalage"] == 1
        assert page1["versions"][0]["statut"] == "COURANTE"
        assert page1["versions"][0]["version_precedente_attendue"] == second["resultat"]["resultat"]["version_source"]
        assert page2["versions"][0]["statut"] == "DEPOSEE_NON_ACTIVEE" and page2["suivant_decalage"] is None
        assert tables(cnx) == avant
        _FX._call(cnx, "retirer", {"affaire_id": AFFAIRE, "document_ref": ack["document_ref"],
                                  "activation_attendue": active["resultat"]["resultat"]["reference"],
                                  "code_motif": "RETRAIT_ACCES"},
                  meta=idempotence.Meta("retrait-lecture", "device-fictif", HORA))
        avant = tables(cnx)
        removed = lire(cnx, "lire", detail(ack))
        assert len(removed["resultat"]["resultat"]) == 13 and "corps" not in removed["resultat"]["resultat"]
        assert lire(cnx)["resultat"]["resultat"]["versions"][0]["statut"] == "RETIREE"
        assert tables(cnx) == avant
    stockage.liberer()
    with stockage.transaction() as cnx:
        avant = tables(cnx)
        assert lire(cnx, "lire", detail(ack)) == removed and tables(cnx) == avant


@pytest.mark.parametrize("actor", [None, contexte.IdentiteAppelante(ACTEUR.personne, "employee", "appareil"),
                                  contexte.IdentiteAppelante(ACTEUR.personne, "admin", "console"),
                                  contexte.IdentiteAppelante("absent-fictif", "admin", "appareil")])
def test_autorite_avant_toute_copie_source(monde, monkeypatch, actor):
    m = module()
    def interdit(*args):
        raise AssertionError("source avant autorité")
    monkeypatch.setattr(m, "_situation", interdit)
    monkeypatch.setattr(m, "copier_registre_m10", interdit)
    with stockage.transaction() as cnx:
        avant = tables(cnx)
        with pytest.raises(m.ErreurLectureDocumentaire) as exc:
            lire(cnx, actor=actor)
        assert exc.value.code == "REJ-M10-LECTURE-AUTORITE-INVALIDE" and tables(cnx) == avant


@pytest.mark.parametrize("retrait", ["role", "inactive"])
def test_revoquer_identite_SQL_et_restaurer_sans_cache_source(monde, monkeypatch, retrait):
    m = module()
    with stockage.transaction() as cnx:
        assert lire(cnx)["ok"] is True
        if retrait == "role":
            identite.retirer_role(cnx, ACTEUR.personne, "admin")
        else:
            identite.activer(cnx, ACTEUR.personne, False)
        avant = tables(cnx)
        with monkeypatch.context() as patch:
            patch.setattr(m, "_situation", lambda *args: pytest.fail("source après révocation"))
            with pytest.raises(m.ErreurLectureDocumentaire, match="AUTORITE-INVALIDE"):
                lire(cnx)
        assert tables(cnx) == avant
        if retrait == "role":
            identite.ajouter_role(cnx, ACTEUR.personne, "admin")
        else:
            identite.activer(cnx, ACTEUR.personne, True)
        avant = tables(cnx)
        assert lire(cnx)["ok"] is True and tables(cnx) == avant


@pytest.mark.parametrize("mode", ["ombre", "supervise", "autonome"])
def test_mode_courant_SQL_trois_modes_lecture_sans_admission_writer(monde, mode):
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", mode, ACTEUR.personne)
        avant = tables(cnx)
        assert lire(cnx)["ok"] is True and tables(cnx) == avant


@pytest.mark.parametrize("args", [[], [["affaire_id", AFFAIRE]], "CANARI-FICTIF", {},
                                  {**commande(), "extra": "CANARI-FICTIF"}, commande(True), commande(65),
                                  commande(limite=True), commande(limite=9)])
def test_forme_stricte_avant_copies_sans_coercition(monde, monkeypatch, args):
    m = module()
    monkeypatch.setattr(m, "_situation", lambda *a: pytest.fail("copies avant forme"))
    with stockage.transaction() as cnx:
        avant = tables(cnx)
        with pytest.raises(m.ErreurLectureDocumentaire) as exc:
            lire(cnx, args=args)
        assert exc.value.code == "REJ-M10-LECTURE-FORME-INVALIDE" and "CANARI" not in str(exc.value)
        assert tables(cnx) == avant


def test_detail_reference_fermee_bool_et_source_etrangere(monde):
    with stockage.transaction() as cnx:
        ack = deposer(cnx)["resultat"]["resultat"]
        avant = tables(cnx)
        bad = detail(ack)
        bad["version_source"] = {**bad["version_source"], "index": True}
        with pytest.raises(module().ErreurLectureDocumentaire, match="FORME-INVALIDE"):
            lire(cnx, "lire", bad)
        bad = detail(ack)
        bad["affaire_id"] = "AFFAIRE-INCONNUE-FICTIVE"
        with pytest.raises(module().ErreurLectureDocumentaire, match="AFFAIRE-INCONNUE"):
            lire(cnx, "lire", bad)
        assert tables(cnx) == avant


@pytest.mark.parametrize("quota", [40, 1, 800])
def test_quota_whole_frame_pas_artefact_ou_fragment(monde, quota):
    with stockage.transaction() as cnx:
        deposer(cnx)
        avant = tables(cnx)
        with pytest.raises(module().ErreurLectureDocumentaire) as exc:
            lire(cnx, quota=quota)
        assert exc.value.code == "REJ-M10-LECTURE-QUOTA-DEPASSE" and tables(cnx) == avant
        assert _FX.CORPS not in str(exc.value)


def test_quota_frontiere_exacte_json_caracteres_et_detail_independant(monde):
    with stockage.transaction() as cnx:
        ack = deposer(cnx)["resultat"]["resultat"]
        response = lire(cnx)
        n = len(json.dumps(response, ensure_ascii=False, allow_nan=False))
        avant = tables(cnx)
        assert lire(cnx, quota=n) == response
        with pytest.raises(module().ErreurLectureDocumentaire, match="QUOTA-DEPASSE"):
            lire(cnx, quota=n - 1)
        assert tables(cnx) == avant
        large = {**ARGS, "document_ref": ack["document_ref"], "version_precedente": ack["version_source"],
                 "corps": "\x01" * 2000}
        v2 = deposer(cnx, large, "large-lecture")["resultat"]["resultat"]
        avant = tables(cnx)
        assert lire(cnx, args=commande(1))["ok"] is True
        with pytest.raises(module().ErreurLectureDocumentaire, match="QUOTA-DEPASSE"):
            lire(cnx, "lire", detail(v2))
        assert tables(cnx) == avant


@pytest.mark.parametrize("registre,raw", [("documents_affaire", "null"),
                                          ("documents_affaire", "[" * 2000 + "0" + "]" * 2000),
                                          ("evenements", "CANARI-CODEC-FICTIF")])
def test_codec_source_corrompu_refus_constant_49tables(monde, registre, raw):
    with stockage.transaction() as cnx:
        deposer(cnx)
        cnx.execute(update(REGISTRES).where(REGISTRES.c.registre == registre).values(maillon=raw))
        avant = tables(cnx)
        with pytest.raises(module().ErreurLectureDocumentaire) as exc:
            lire(cnx)
        assert exc.value.code == "REJ-M10-LECTURE-REGISTRE-INVALIDE"
        assert "CANARI" not in str(exc.value) and "SQL" not in str(exc.value) and tables(cnx) == avant


def test_connexion_etrangere_absente_et_fermee_refuse_avant_SELECT(monde):
    m = module()
    engine = create_engine("sqlite://")
    with stockage.transaction() as cnx, engine.connect() as other:
        before = tables(cnx)
        emitted = []
        event.listen(cnx, "before_cursor_execute", lambda _a, _b, s, _c, _d, _e: emitted.append(s))
        with other.begin():
            for cible in (other, None):
                with pytest.raises(m.ErreurLectureDocumentaire, match="CONNEXION-INVALIDE"):
                    lire(cible)
        other.close()
        with pytest.raises(m.ErreurLectureDocumentaire, match="CONNEXION-INVALIDE"):
            lire(other)
        assert emitted == [] and tables(cnx) == before
    engine.dispose()


def test_lecture_ne_fait_que_SELECT_PRAGMA_et_renvoie_copie(monde):
    with stockage.transaction() as cnx:
        deposer(cnx)
        statements = []
        event.listen(cnx, "before_cursor_execute", lambda _a, _b, s, _c, _d, _e: statements.append(s))
        args = commande()
        original = copy.deepcopy(args)
        assert lire(cnx, args=args)["ok"] is True and args == original
        assert statements and all(s.lstrip().upper().startswith(("SELECT", "PRAGMA")) for s in statements)
