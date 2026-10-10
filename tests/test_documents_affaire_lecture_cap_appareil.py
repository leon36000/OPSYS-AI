"""Lectures Cap/SQLite FICTIVES ; identité injectée, aucun transport DEVICE opaque."""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import update

from opsys import contexte, idempotence, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau
from opsys.stockage.schema import PERSONNES, ROLES_PERSONNES

FICTIF = True
NOMS = ("m10_lister_documents_affaire_appareil", "m10_lire_version_document_affaire_appareil")
spec = importlib.util.spec_from_file_location(
    "lecture_cap_transactions_fictives", Path(__file__).with_name("test_documents_affaire_transactions.py"),
)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
monde = fx.monde
INDEX = {"affaire_id": fx.AFFAIRE, "decalage": 0, "limite": 1}
REF = {"registre": "documents_affaire", "index": 0, "ligne_id": "0" * 64}
DETAIL = {"affaire_id": fx.AFFAIRE, "document_ref": REF, "version_source": REF}


def cap(quota=6000, factory=stockage.transaction):
    return Capacites(charger_departements(), factory, filtre={"m10-memoire"}, memoire=False, limite_sortie=quota)


def appeler(c, args=INDEX, *, nom=NOMS[0], actor=fx.ACTEUR, **kwargs):
    with contexte.appele_par_appareil(actor):
        return c.appeler(nom, args, **kwargs)


def tables():
    with stockage.transaction() as cnx:
        return fx._tables(cnx)


def interdite():
    raise AssertionError("La factory/le générique ne doit pas être invoqué.")


@pytest.mark.parametrize("nom,args", [(NOMS[0], None), (NOMS[1], {})])
def test_forme_fermee_avant_factory(nom, args):
    assert appeler(cap(factory=interdite), args, nom=nom) == {
        "ok": False, "erreur": "REJ-M10-LECTURE-FORME-INVALIDE",
    }


def test_index_sql_reel_t0_aucune_ecriture_ni_generique(monde, monkeypatch):
    fx._first()
    c = cap()
    for name in ("_distribuer", "_tronquer", "_appeler_idempotent", "_valider_au_depart"):
        monkeypatch.setattr(c, name, lambda *a, **k: interdite())
    avant = tables()
    result = appeler(c)
    assert set(result) == {"ok", "resultat"} and result["ok"] is True
    dto = result["resultat"]["resultat"]
    assert dto["affaire_id"] == fx.AFFAIRE and dto["total_versions"] == 1
    assert dto["decalage"] == 0 and dto["limite"] == 1 and dto["suivant_decalage"] is None
    assert len(dto["versions"]) == 1 and len(dto["versions"][0]) == 16
    assert "corps" not in dto["versions"][0] and fx.CORPS not in json.dumps(result)
    assert avant == tables()
    print("TABLES_T0_OBSERVEES", len(avant))


class DictionnairePiege(dict):
    def items(self):
        raise AssertionError("Une sous-classe ne doit pas être inspectée.")


@pytest.mark.parametrize("args", [
    None, [], [["affaire_id", fx.AFFAIRE]], 7, "CANARI_FICTIF", DictionnairePiege(INDEX),
    {**INDEX, "limite": True}, {**INDEX, "limite": 0}, {**INDEX, "limite": 9},
    {**INDEX, "decalage": -1}, {**INDEX, "decalage": 65}, {**INDEX, "decalage": 0.0},
    {**INDEX, "affaire_id": "\ud800"}, {**INDEX, "extra": "CANARI_FICTIF"},
    {"affaire_id": fx.AFFAIRE},
])
def test_index_arguments_non_normalises_zero_factory(args):
    assert appeler(cap(factory=interdite), args) == {"ok": False, "erreur": "REJ-M10-LECTURE-FORME-INVALIDE"}


@pytest.mark.parametrize("args", [
    {**DETAIL, "document_ref": None}, {**DETAIL, "version_source": {**REF, "index": True}},
    {**DETAIL, "version_source": {**REF, "index": 512}},
    {**DETAIL, "version_source": {**REF, "ligne_id": "CANARI_FICTIF"}},
    {**DETAIL, "version_source": {**REF, "registre": "evenements"}},
    {**DETAIL, "version_source": DictionnairePiege(REF)}, {**DETAIL, "extra": False},
])
def test_detail_arguments_stricts_zero_factory(args):
    assert appeler(cap(factory=interdite), args, nom=NOMS[1]) == {
        "ok": False, "erreur": "REJ-M10-LECTURE-FORME-INVALIDE",
    }


@pytest.mark.parametrize("actor", [
    None, contexte.IdentiteAppelante(fx.ACTEUR.personne, "admin", "console"),
    contexte.IdentiteAppelante(fx.ACTEUR.personne, "employee", "appareil"),
    contexte.IdentiteAppelante(fx.ACTEUR.personne, "seller", "appareil"),
    contexte.IdentiteAppelante(fx.ACTEUR.personne, "client", "appareil"),
    contexte.IdentiteAppelante("CANARI FICTIF", "admin", "appareil"),
])
@pytest.mark.parametrize("nom,args", [(NOMS[0], INDEX), (NOMS[1], DETAIL)])
def test_identite_refusee_zero_factory(actor, nom, args):
    assert appeler(cap(factory=interdite), args, nom=nom, actor=actor) == {
        "ok": False, "erreur": "REJ-M10-LECTURE-AUTORITE-INVALIDE",
    }


@pytest.mark.parametrize("meta", [fx.META, {}, False, "CANARI_FICTIF"])
def test_aucune_meta_mutation_zero_factory(meta):
    assert appeler(cap(factory=interdite), meta=meta) == {"ok": False, "erreur": "REJ-M10-LECTURE-FORME-INVALIDE"}


@pytest.mark.parametrize("ticket", ["ticket_cible", "ticket_memoire"])
def test_ticket_refuse_zero_factory(ticket):
    assert appeler(cap(factory=interdite), **{ticket: "CANARI_FICTIF"}) == {
        "ok": False, "erreur": "REJ-M10-LECTURE-AUTORITE-INVALIDE",
    }


def test_cfo_refuse_zero_factory():
    with contexte.appele_avec_ticket_agent_cfo("CANARI_FICTIF", {}):
        assert appeler(cap(factory=interdite)) == {"ok": False, "erreur": "REJ-M10-LECTURE-AUTORITE-INVALIDE"}


@pytest.mark.parametrize("nom", NOMS)
def test_profile_refuse_zero_factory(nom):
    assert cap(factory=interdite).appeler_profil_runtime(
        nom, INDEX, None, None, profile_id="CANARI_FICTIF", profile_revision=1, server="opsys_m10",
    ) == {"ok": False, "erreur": "REJ-M10-LECTURE-AUTORITE-INVALIDE"}
    with pytest.raises(RuntimeError, match="^QUOTA-INSUFFISANT$"):
        cap(1, interdite).appeler_profil_runtime(
            nom, INDEX, None, None, profile_id="CANARI_FICTIF", profile_revision=1, server="opsys_m10",
        )


@pytest.mark.parametrize("quota", [None, True, 0, 1, 39])
def test_quota_invalide_zero_factory(quota):
    with pytest.raises(RuntimeError, match="^QUOTA-INSUFFISANT$"):
        appeler(cap(quota, interdite))


@pytest.mark.parametrize("change", ["missing", "owner", "autonomy", "level", "role", "agent", "mode"])
def test_index_admission_fermee_zero_factory(change):
    c = cap(factory=interdite)
    d, o = c.index[NOMS[0]]
    if change == "missing":
        c.index.pop(NOMS[0])
    elif change == "owner":
        c.index[NOMS[0]] = (None, o)
    elif change == "autonomy":
        c.index[NOMS[0]] = (d, dataclasses.replace(o, autonomie=Autonomie.T1))
    elif change == "level":
        c.index[NOMS[0]] = (d, dataclasses.replace(o, niveau=Niveau.N3))
    elif change == "role":
        c._portees_roles = {"admin": frozenset()}
    elif change == "agent":
        c.appelant = d
    else:
        c.index[NOMS[0]] = (dataclasses.replace(d, mode="CANARI_FICTIF"), o)
    suffixe = "MODE-NON-ADMIS" if change == "mode" else "AUTORITE-INVALIDE"
    assert appeler(c) == {"ok": False, "erreur": "REJ-M10-LECTURE-" + suffixe}


@pytest.mark.parametrize("change", ["inactif", "role", "missing"])
def test_sql_admin_actuel_avant_copie(monde, monkeypatch, change):
    from opsys import documents_affaire_lecture_appareil as backend

    with stockage.transaction() as cnx:
        if change == "inactif":
            cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == fx.ACTEUR.personne).values(actif=False))
        elif change == "role":
            cnx.execute(update(ROLES_PERSONNES).where(ROLES_PERSONNES.c.identifiant == fx.ACTEUR.personne)
                        .values(role="employee"))
    monkeypatch.setattr(backend, "copier_registre_m10", lambda *a, **k: interdite())
    before = tables()
    actor = contexte.IdentiteAppelante("absent_fictif", "admin", "appareil") if change == "missing" else fx.ACTEUR
    assert appeler(cap(), actor=actor) == {"ok": False, "erreur": "REJ-M10-LECTURE-AUTORITE-INVALIDE"}
    assert before == tables()


@pytest.mark.parametrize("mode", ["ombre", "supervise", "autonome"])
def test_modes_lecture_et_page_vide(monde, mode):
    c = cap()
    d, o = c.index[NOMS[0]]
    c.index[NOMS[0]] = (dataclasses.replace(d, mode=mode), o)
    before = tables()
    assert appeler(c, {**INDEX, "decalage": 64}) == {"ok": True, "resultat": {"accepte": True, "resultat": {
        "version_schema": 1, "affaire_id": fx.AFFAIRE, "decalage": 64, "limite": 1,
        "total_versions": 0, "suivant_decalage": None, "versions": [],
    }}}
    assert before == tables()


def test_detail_exact_historique_activation_retrait_et_captures(monde):
    c = cap()
    ack = fx._first()["resultat"]["resultat"]
    args = {"affaire_id": fx.AFFAIRE, "document_ref": ack["document_ref"], "version_source": ack["version_source"]}
    captures = {}

    def observer(label):
        avant = tables()
        detail = appeler(c, args, nom=NOMS[1])
        page = appeler(c)
        assert detail["ok"] is True and page["ok"] is True and avant == tables()
        captures[label] = {"detail": detail, "index": page, "tables_observees": len(avant)}
        return detail["resultat"]["resultat"]

    initial = observer("deposee")
    assert len(initial) == 14 and initial["corps"] == fx.CORPS and initial["statut"] == "DEPOSEE_NON_ACTIVEE"
    with stockage.transaction() as cnx:
        active = fx._call(cnx, "activer", {**args, "activation_attendue": None},
                          meta=idempotence.Meta("activation-fictive", fx.META.appareil, fx.HORA))
    assert observer("activee")["statut"] == "COURANTE"
    with stockage.transaction() as cnx:
        fx._call(cnx, args={**fx.ARGS, "document_ref": ack["document_ref"], "version_precedente": ack["version_source"],
                            "corps": "seconde version FICTIVE"},
                 meta=idempotence.Meta("seconde-fictive", fx.META.appareil, fx.HORA))
    assert observer("seconde_deposee")["statut"] == "COURANTE"
    with stockage.transaction() as cnx:
        fx._call(cnx, "retirer", {"affaire_id": fx.AFFAIRE, "document_ref": ack["document_ref"],
                                  "activation_attendue": active["resultat"]["resultat"]["reference"],
                                  "code_motif": "RETRAIT_ACCES"},
                 meta=idempotence.Meta("retrait-fictif", fx.META.appareil, fx.HORA))
    retired = observer("retiree")
    assert len(retired) == 13 and retired["statut"] == "RETIREE" and "corps" not in retired
    stockage.liberer()
    before = tables()
    assert appeler(cap(), args, nom=NOMS[1])["resultat"]["resultat"] == retired and before == tables()
    print("CAPTURES_CAP_SQL_FICTIVES=" + json.dumps({"fictif": True, "captures": captures}, ensure_ascii=False))


def test_quota_exact_entier_et_refus_hors_factory(monde):
    fx._first()
    response = appeler(cap())
    size = len(json.dumps(response, ensure_ascii=False, allow_nan=False))
    before = tables()
    assert appeler(cap(size)) == response
    assert appeler(cap(size - 1)) == {"ok": False, "erreur": "REJ-M10-LECTURE-QUOTA-DEPASSE"}
    with pytest.raises(RuntimeError, match="^LECTURE-DOCUMENTAIRE-INDISPONIBLE$"):
        appeler(cap(40))
    assert before == tables()


@pytest.mark.parametrize("mutation", [
    "top_extra", "accepted_false", "schema_bool", "wrong_affaire", "wrong_offset", "wrong_limit",
    "total_bool", "wrong_next", "empty_rows", "body_index", "row_affaire", "row_ref", "row_size", "row_author",
])
def test_fausse_projection_index_refusee_et_ecriture_handler_rollback(monde, mutation):
    fx._first()
    c = cap()
    result = appeler(c)
    dto = result["resultat"]["resultat"]
    row = dto["versions"][0]
    if mutation == "top_extra":
        result["rejoue"] = False
    elif mutation == "accepted_false":
        result["resultat"]["accepte"] = False
    elif mutation == "schema_bool":
        dto["version_schema"] = True
    elif mutation == "wrong_affaire":
        dto["affaire_id"] = "LEAD-AUTRE-FICTIF"
    elif mutation == "wrong_offset":
        dto["decalage"] = 1
    elif mutation == "wrong_limit":
        dto["limite"] = 2
    elif mutation == "total_bool":
        dto["total_versions"] = True
    elif mutation == "wrong_next":
        dto["suivant_decalage"] = True
    elif mutation == "empty_rows":
        dto["versions"] = []
    elif mutation == "body_index":
        row["corps"] = fx.CORPS
    elif mutation == "row_affaire":
        row["affaire_id"] = "LEAD-AUTRE-FICTIF"
    elif mutation == "row_ref":
        row["version_source"]["index"] = True
    elif mutation == "row_size":
        row["taille_octets"] = 9000
    else:
        row["auteur"]["role"] = "employee"
    d, o = c.index[NOMS[0]]

    def invalide(**args):
        stockage.connexion_courante().execute(update(PERSONNES).values(actif=False))
        return copy.deepcopy(result)

    c.index[NOMS[0]] = (d, dataclasses.replace(o, fonction=invalide))
    before = tables()
    assert appeler(c) == {"ok": False, "erreur": "REJ-M10-LECTURE-INDISPONIBLE"}
    assert before == tables()


@pytest.mark.parametrize("mutation", ["root", "version", "body", "body_type", "hash", "retired_body", "missing_body"])
def test_fausse_projection_detail_refusee(monde, mutation):
    ack = fx._first()["resultat"]["resultat"]
    args = {"affaire_id": fx.AFFAIRE, "document_ref": ack["document_ref"], "version_source": ack["version_source"]}
    c = cap()
    result = appeler(c, args, nom=NOMS[1])
    dto = result["resultat"]["resultat"]
    if mutation in ("root", "version"):
        dto["document_ref" if mutation == "root" else "version_source"]["ligne_id"] = "0" * 64
    elif mutation == "body":
        dto["corps"] += "CANARI_FICTIF"
    elif mutation == "body_type":
        dto["corps"] = []
    elif mutation == "hash":
        dto["source_sha256"] = "0" * 64
    elif mutation == "retired_body":
        dto["statut"] = "RETIREE"
    else:
        dto.pop("corps")
    d, o = c.index[NOMS[1]]
    c.index[NOMS[1]] = (d, dataclasses.replace(o, fonction=lambda **a: result))
    before = tables()
    assert appeler(c, args, nom=NOMS[1]) == {"ok": False, "erreur": "REJ-M10-LECTURE-INDISPONIBLE"}
    assert before == tables()


def test_affaire_inconnue_reference_inconnue_et_sanitisation(monde):
    before = tables()
    assert appeler(cap(), {**INDEX, "affaire_id": "LEAD-INCONNU-FICTIF"}) == {
        "ok": False, "erreur": "REJ-M10-LECTURE-AFFAIRE-INCONNUE",
    }
    assert appeler(cap(), DETAIL, nom=NOMS[1]) == {"ok": False, "erreur": "REJ-M10-LECTURE-REFERENCE-INVALIDE"}
    c = cap()
    d, o = c.index[NOMS[0]]

    def panne(**args):
        raise RuntimeError(fx.CORPS)

    c.index[NOMS[0]] = (d, dataclasses.replace(o, fonction=panne))
    assert appeler(c) == {"ok": False, "erreur": "REJ-M10-LECTURE-INDISPONIBLE"}
    assert before == tables()


def test_refus_et_budget_traduits_apres_sortie_factory(monde, monkeypatch):
    ouvert = []

    @contextmanager
    def factory():
        with stockage.transaction() as cnx:
            ouvert.append(cnx)
            try:
                yield cnx
            finally:
                ouvert.pop()

    c = cap(factory=factory)
    original = c.refus_lecture_documentaire_appareil

    def verifier(code):
        assert ouvert == []
        return original(code)

    monkeypatch.setattr(c, "refus_lecture_documentaire_appareil", verifier)
    before = tables()
    assert appeler(c, DETAIL, nom=NOMS[1])["erreur"] == "REJ-M10-LECTURE-REFERENCE-INVALIDE"
    c._limite = 40
    with pytest.raises(RuntimeError, match="^LECTURE-DOCUMENTAIRE-INDISPONIBLE$"):
        appeler(c, DETAIL, nom=NOMS[1])
    assert before == tables()


def test_connexion_non_canonique_ne_permet_pas_handler(monde):
    @contextmanager
    def invalide():
        yield object()

    c = cap(factory=invalide)
    d, o = c.index[NOMS[0]]
    c.index[NOMS[0]] = (d, dataclasses.replace(o, fonction=lambda **a: interdite()))
    before = tables()
    assert appeler(c) == {"ok": False, "erreur": "REJ-M10-LECTURE-INDISPONIBLE"}
    assert before == tables()
