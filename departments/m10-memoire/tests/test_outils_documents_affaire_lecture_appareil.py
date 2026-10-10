"""Façade documentaire T0 fictive, vrais handlers SQLite, sans Cap/transport."""

from __future__ import annotations

import importlib.util
import inspect as introspection
import sys
from pathlib import Path

import pytest
from m10_memoire import outils
from sqlalchemy import event

from opsys import contexte, stockage
from opsys.outils import Autonomie, Niveau

FICTIF = True
_SPEC = importlib.util.spec_from_file_location(
    "fixture_lectures_documentaires_fictive",
    Path(__file__).resolve().parents[3] / "tests/test_documents_affaire_lecture_appareil.py",
)
_FX = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _FX
_SPEC.loader.exec_module(_FX)
monde = _FX.monde
NOMS = ("m10_lister_documents_affaire_appareil", "m10_lire_version_document_affaire_appareil")
KEYS = (("affaire_id", "decalage", "limite"), ("affaire_id", "document_ref", "version_source"))


def outil(index=0):
    found = {o.nom: o for o in outils.outils()}.get(NOMS[index])
    assert found is not None, "outil T0 documentaire absent"
    return found


def contexte_lecture(cnx, **changes):
    manager = getattr(outils, "invocation_lecture_documentaire_appareil", None)
    assert callable(manager), "contexte de lecture documentaire absent"
    return manager(cnx, **{"quota": 6000, "mode_manifeste": "ombre", **changes})


def appeler(cnx, index=0, args=None):
    with contexte.appele_par_appareil(_FX.ACTEUR), contexte_lecture(cnx):
        return outil(index).fonction(**(_FX.commande() if args is None else args))


@pytest.mark.parametrize("index", [0, 1])
def test_declarations_T0_N0_admin_affaire_fermees_append_et_signatures(index):
    o = outil(index)
    assert tuple(x.nom for x in outils.outils())[-2:] == NOMS
    assert len(outils.outils()) == 26
    assert o.autonomie is Autonomie.T0 and o.niveau is Niveau.N0
    assert o.roles_appareil == frozenset({"admin"})
    assert (o.portee_contexte, o.cible_contexte, o.identite_contexte) == ("affaire", ("affaire_id",), "affaire")
    assert o.parametres["additionalProperties"] is False
    assert tuple(o.parametres["properties"]) == tuple(o.parametres["required"]) == KEYS[index]
    signature = introspection.signature(o.fonction)
    assert tuple(signature.parameters) == KEYS[index]
    assert all(p.default is introspection.Parameter.empty for p in signature.parameters.values())
    if index == 0:
        assert o.parametres["properties"]["decalage"] == {"type": "integer", "minimum": 0, "maximum": 64}
        assert o.parametres["properties"]["limite"] == {"type": "integer", "minimum": 1, "maximum": 8}


def test_handlers_SQL_wholeframe_index_detail_49tables_sans_Meta(monde):
    with stockage.transaction() as cnx:
        ack = _FX.deposer(cnx)["resultat"]["resultat"]
        before = _FX.tables(cnx)
        first = appeler(cnx)
        body = appeler(cnx, 1, _FX.detail(ack))
        assert set(first) == set(body) == {"ok", "resultat"}
        assert first["resultat"]["resultat"]["versions"][0]["version_source"] == ack["version_source"]
        assert body["resultat"]["resultat"]["corps"] == _FX.ARGS["corps"]
        assert len(before) == 49 and _FX.tables(cnx) == before


def test_absence_invocation_refuse_avant_source_SQL(monde):
    with stockage.transaction() as cnx:
        emitted = []
        event.listen(cnx, "before_cursor_execute", lambda _a, _b, s, _c, _d, _e: emitted.append(s))
        with pytest.raises(RuntimeError) as exc:
            outil().fonction(**_FX.commande())
        assert str(exc.value) == "LECTURE-DOCUMENTAIRE-INDISPONIBLE" and emitted == []


@pytest.mark.parametrize("changes", [{"quota": True}, {"quota": 0}, {"mode_manifeste": "invente"}])
def test_invocation_fermee_avant_import_SQL(changes, monde):
    with stockage.transaction() as cnx:
        emitted = []
        event.listen(cnx, "before_cursor_execute", lambda _a, _b, s, _c, _d, _e: emitted.append(s))
        with pytest.raises(RuntimeError) as exc, contexte_lecture(cnx, **changes):
            outil().fonction(**_FX.commande())
        assert str(exc.value) == "LECTURE-DOCUMENTAIRE-INDISPONIBLE" and emitted == []


def test_reset_finally_et_invocation_imbriquee_ne_remplace_pas_outer(monde):
    with stockage.transaction() as cnx, contexte.appele_par_appareil(_FX.ACTEUR):
        with contexte_lecture(cnx):
            with pytest.raises(RuntimeError), contexte_lecture(cnx, quota=1):
                pass
            assert outil().fonction(**_FX.commande())["ok"] is True
        with pytest.raises(RuntimeError, match="LECTURE-DOCUMENTAIRE-INDISPONIBLE"):
            outil().fonction(**_FX.commande())
        with pytest.raises(ValueError), contexte_lecture(cnx):
            raise ValueError("fictif")
        with pytest.raises(RuntimeError, match="LECTURE-DOCUMENTAIRE-INDISPONIBLE"):
            outil().fonction(**_FX.commande())


def test_arguments_getter_invalides_refus_avant_import_backend(monde, monkeypatch):
    import builtins
    original = builtins.__import__
    class Texte(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("encode arbitraire")
    def verifier(nom, *args, **kwargs):
        if nom == "opsys.documents_affaire_lecture_appareil":
            pytest.fail("backend importé avant arguments fermés")
        return original(nom, *args, **kwargs)
    with stockage.transaction() as cnx, contexte_lecture(cnx):
        monkeypatch.setattr(builtins, "__import__", verifier)
        with pytest.raises(RuntimeError, match="LECTURE-DOCUMENTAIRE-INDISPONIBLE"):
            outil().fonction(Texte(_FX.AFFAIRE), 0, 1)
