"""Capture/projection techniques SQLite FICTIF, pas writer ni autorité DEVICE."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, inspect, select, text, update

from opsys import approbations as a
from opsys import approbations_appareil, etat, identite, tableau_de_bord
from opsys.contexte import IdentiteAppelante
from opsys.outils import Niveau
from opsys.stockage.schema import APPROBATIONS, JOURNAL

FICTIF = True
NOMS = (
    "m10_deposer_version_document_appareil",
    "m10_activer_version_document_appareil",
    "m10_retirer_document_appareil",
)
ACTEUR = IdentiteAppelante("admin.fictif", "admin", "appareil")
APPAREIL = "device-fictif"
CORPS = "CANARI_CORPS_DOCUMENT_FICTIF"
EXTRAIT = "CANARI_EXTRAIT_DOCUMENT_FICTIF"
MASQUE = "[contenu documentaire masqué]"
ARGS = {"corps": CORPS, "extrait": EXTRAIT, "titre": "Titre visible fictif", "document_ref": {"index": 0}}
REPONSE = {"ok": True, "resultat": {"accepte": True}}


def _tables(cnx):
    return {
        n: sorted(map(tuple, cnx.execute(text('SELECT * FROM "' + n.replace('"', '""') + '"')).all()), key=repr)
        for n in inspect(cnx).get_table_names()
    }


def _capture(cnx, nom=NOMS[0], **kwargs):
    params = {"niveau": Niveau.N3, "signataire": ACTEUR, "reponse": REPONSE, "appareil": APPAREIL}
    params.update(kwargs)
    return a.tracer_validation_documentaire_m10(cnx, "m10-memoire", nom, ARGS, **params)


@pytest.mark.parametrize("nom", NOMS)
def test_capture_pk_natives_frozen_meme_savepoint_et_raw_json(session, nom):
    with session() as cnx:
        avant = _tables(cnx)
        etat.journaliser(cnx, "autre.fictif", "autre", "autre")
        with cnx.begin_nested():
            trace = _capture(cnx, nom)
        assert type(trace.approbation_id) is str and len(trace.approbation_id) == 12
        assert type(trace.journal_id) is int and 0 < trace.journal_id <= 2**63 - 1
        with pytest.raises(dataclasses.FrozenInstanceError):
            trace.journal_id = 0
        app = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == trace.approbation_id)).mappings().one()
        journal = cnx.execute(select(JOURNAL).where(JOURNAL.c.id == trace.journal_id)).mappings().one()
        assert app["arguments"] == json.dumps(ARGS, ensure_ascii=False)
        assert app["statut"] == "executee" and app["niveau"] == "N3"
        assert app["decide_par"] == ACTEUR.personne and app["decide_role"] == "admin"
        assert app["resultat"] == json.dumps({"ok": True, "accepte": True}, ensure_ascii=False)
        assert journal["cible"] == trace.approbation_id and journal["action"] == a.ACTION_VALIDATION_AU_DEPART
        assert json.loads(journal["details"])["appareil"] == APPAREIL
        apres = _tables(cnx)
        assert {n for n in avant if avant[n] != apres[n]} == {"approbations", "journal"}


@pytest.mark.parametrize("type_erreur", [ValueError, TypeError, KeyError])
def test_panne_apres_app_ou_j_sort_techniquement_et_annule_savepoint(session, monkeypatch, type_erreur):
    with session() as cnx:
        avant = _tables(cnx)
        original = etat._journaliser_documentaire_m10

        def panne(*args, **kwargs):
            original(*args, **kwargs)
            raise type_erreur(CORPS)

        monkeypatch.setattr(etat, "_journaliser_documentaire_m10", panne)
        with pytest.raises(RuntimeError) as exc, cnx.begin_nested():
            _capture(cnx)
        assert not isinstance(exc.value, (ValueError, TypeError, KeyError))
        assert CORPS not in str(exc.value)
        assert _tables(cnx) == avant


@pytest.mark.parametrize("pk", [None, True, 0, -1, 2**63, "1", 1.0])
def test_pk_j_invalide_apres_insert_rollback_sans_renforcer_legacy(session, monkeypatch, pk):
    with session() as cnx:
        original = cnx.execute

        def executer(statement, *args, **kwargs):
            result = original(statement, *args, **kwargs)
            if getattr(statement, "table", None) is JOURNAL:
                return SimpleNamespace(inserted_primary_key=(pk,))
            return result

        monkeypatch.setattr(cnx, "execute", executer)
        # L'ancienne voie ignore toujours la PK et conserve son retour None.
        assert etat.journaliser(cnx, "fictif", "legacy", "x") is None
        avant = _tables(cnx)
        with pytest.raises(RuntimeError), cnx.begin_nested():
            _capture(cnx)
        assert _tables(cnx) == avant


@pytest.mark.parametrize("pk", [None, True, 12, "x", "a" * 13])
def test_pk_app_invalide_apres_insert_rollback(session, monkeypatch, pk):
    with session() as cnx:
        original = cnx.execute

        def executer(statement, *args, **kwargs):
            result = original(statement, *args, **kwargs)
            if getattr(statement, "table", None) is APPROBATIONS:
                return SimpleNamespace(inserted_primary_key=(pk,))
            return result

        monkeypatch.setattr(cnx, "execute", executer)
        avant = _tables(cnx)
        with pytest.raises(RuntimeError), cnx.begin_nested():
            _capture(cnx)
        assert _tables(cnx) == avant


@pytest.mark.parametrize("probleme", ["absente", "etrangere", "fermee", "sans_transaction", "sans_savepoint"])
def test_cnx_canonique_et_savepoint_caller_avant_toute_ecriture(session, probleme):
    with session() as cnx:
        if probleme == "absente":
            cible = None
        elif probleme == "etrangere":
            moteur = create_engine("sqlite://")
            cible = moteur.connect()
            cible.begin()
            cible.begin_nested()
        else:
            cible = cnx
            if probleme == "fermee":
                cnx.close()
            if probleme == "sans_transaction":
                cnx.commit()
        statements = []
        event.listen(cnx.engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
        with pytest.raises(RuntimeError):
            _capture(cible)
        assert not statements
        if probleme == "etrangere":
            cible.close()
            moteur.dispose()


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("departement", "m09-demo"),
        ("outil", "m10_autre"),
        ("niveau", Niveau.N4),
        ("signataire", IdentiteAppelante("fictif", "employee", "appareil")),
        ("signataire", IdentiteAppelante("fictif", "admin", "console")),
        ("appareil", None),
        ("appareil", " "),
    ],
)
def test_correlation_nommee_avant_app_j(session, champ, valeur):
    with session() as cnx, cnx.begin_nested():
        params = dict(
            cnx=cnx,
            departement="m10-memoire",
            outil=NOMS[0],
            arguments=ARGS,
            niveau=Niveau.N3,
            signataire=ACTEUR,
            reponse=REPONSE,
            appareil=APPAREIL,
        )
        params[champ] = valeur
        avant = _tables(cnx)
        with pytest.raises(RuntimeError):
            a.tracer_validation_documentaire_m10(**params)
        assert _tables(cnx) == avant


@pytest.mark.parametrize("nom", NOMS)
@pytest.mark.parametrize("en_attente", [False, True])
def test_projection_publique_raw_preservee_sans_index_outil(session, nom, en_attente):
    with session() as cnx:
        ident = a.tracer_validation_au_depart(
            cnx, "m10-memoire", nom, ARGS, niveau=Niveau.N3, signataire=ACTEUR, reponse=REPONSE, appareil=APPAREIL
        )
        if en_attente:
            cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(statut="en_attente"))
        avant = _tables(cnx)
        detail = a.lire(cnx, ident)
        assert detail["arguments"] == {**ARGS, "corps": MASQUE, "extrait": MASQUE}
        detail["arguments"]["document_ref"]["index"] = 99
        assert a.lire(cnx, ident)["arguments"]["document_ref"] == {"index": 0}
        assert CORPS not in json.dumps(a.lister(cnx)) and EXTRAIT not in json.dumps(a.lister(cnx))
        assert CORPS not in json.dumps(tableau_de_bord.lister_approbations(cnx, {}))
        assert EXTRAIT not in json.dumps(tableau_de_bord.file_proprietaire(cnx, {}))
        # L'index des outils est vide : le masque ne dépend pas de sa présence.
        assert _tables(cnx) == avant
        assert cnx.execute(
            select(APPROBATIONS.c.arguments).where(APPROBATIONS.c.id == ident)
        ).scalar_one() == json.dumps(ARGS, ensure_ascii=False)


def test_projection_null_keys_titre_et_legacy_inchanges(session):
    with session() as cnx:
        args = {**ARGS, "corps": None, "extrait": None}
        ident = a.creer_demande(cnx, "m10-memoire", NOMS[0], args, niveau=Niveau.N3)
        assert a.lire(cnx, ident)["arguments"] == args
        ident = a.tracer_validation_au_depart(
            cnx, "m09-demo", "legacy", ARGS, niveau=Niveau.N3, signataire=ACTEUR, reponse=REPONSE
        )
        assert type(ident) is str and len(ident) == 12
        assert a.lire(cnx, ident)["arguments"] == ARGS


def test_console_api_html_et_app_lectures_reelles_sans_canari(session):
    from fastapi.testclient import TestClient

    from opsys.console.application import creer_application
    from opsys.console.securite import Configuration

    password = "mot-de-passe-FICTIF-console-1234"
    with session() as cnx:
        identite.creer_personne(cnx, ACTEUR.personne, "Admin FICTIF", password, ["admin", "nathan_owner"])
        ident = a.creer_demande(cnx, "m10-memoire", NOMS[0], ARGS, niveau=Niveau.N3)
        reponse, verdict = approbations_appareil.lister_demandes(cnx, {}, ACTEUR)
        assert verdict is None and CORPS not in json.dumps(reponse) and EXTRAIT not in json.dumps(reponse)
        avant = _tables(cnx)
        assert a.lire(cnx, ident)["arguments"]["titre"] == ARGS["titre"]
        assert _tables(cnx) == avant
    config = Configuration("secret-FICTIF-console-" + "x" * 40)
    app = creer_application(config, {}, session)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        assert (
            client.post(
                "/connexion", data={"identifiant": ACTEUR.personne, "mot_de_passe": password}, follow_redirects=False
            ).status_code
            == 303
        )
        for route in ("/api/approbations", "/api/approbations/file", "/approbations"):
            response = client.get(route)
            assert response.status_code == 200
            assert CORPS not in response.text and EXTRAIT not in response.text


@pytest.mark.parametrize("champ", ["role", "source"])
def test_champs_correlation_plain_avant_methodes_hostiles(session, champ):
    calls = []

    class Texte(str):
        def __ne__(self, other):
            calls.append("ne")
            return False

    valeurs = {"personne": ACTEUR.personne, "role": "admin", "source": "appareil"}
    valeurs[champ] = Texte(valeurs[champ])
    with session() as cnx, cnx.begin_nested():
        avant = _tables(cnx)
        with pytest.raises(RuntimeError):
            _capture(cnx, signataire=IdentiteAppelante(**valeurs))
        assert calls == [] and _tables(cnx) == avant


def test_capture_ne_fait_ni_select_pk_ni_savepoint_propre(session):
    with session() as cnx, cnx.begin_nested():
        statements = []

        def observe(*args):
            statements.append(args[2].strip().split()[0].upper())

        event.listen(cnx.engine, "before_cursor_execute", observe)
        try:
            trace = _capture(cnx)
        finally:
            event.remove(cnx.engine, "before_cursor_execute", observe)
        assert trace.journal_id > 0
        assert statements == ["INSERT", "INSERT"]


def test_projection_reste_fermee_apres_retrait_fictif_sans_registry_lookup(session):
    import datetime as dt

    from sqlalchemy import insert

    from opsys.stockage.schema import REGISTRES

    with session() as cnx:
        ident = a.creer_demande(cnx, "m10-memoire", NOMS[0], ARGS, niveau=Niveau.N3)
        avant = a.lire(cnx, ident)
        # Etat de retrait FICTIF technique ; aucune chaîne domaine/transition qualifiée.
        cnx.execute(
            insert(REGISTRES).values(
                departement="m10-memoire",
                registre="documents_affaire",
                rang=0,
                cree_le=dt.datetime(2026, 10, 9, tzinfo=dt.UTC),
                maillon=json.dumps({"fictif": True, "type_entree": "document_retire"}),
            )
        )
        assert a.lire(cnx, ident) == avant
        assert avant["arguments"]["corps"] == MASQUE and avant["arguments"]["extrait"] == MASQUE
        assert tableau_de_bord.lister_approbations(cnx, {})[0]["arguments"] == avant["arguments"]


def test_projection_legacy_ne_recopie_pas_une_arborescence_json_historique(session):
    arbre = {"fictif": True}
    for _ in range(600):
        arbre = {"enfant": arbre}
    with session() as cnx:
        ident = a.creer_demande(cnx, "m09-demo", "outil_historique_fictif", arbre, niveau=Niveau.N3)
        lu = a.lire(cnx, ident)["arguments"]
        for _ in range(600):
            lu = lu["enfant"]
        assert lu == {"fictif": True}


@pytest.mark.parametrize(
    "charge",
    [
        [{"corps": CORPS}],
        EXTRAIT,
        None,
        5,
        True,
    ],
)
def test_projection_app_json_top_corrompue_refuse_liste_detail_sans_echo(session, charge):
    with session() as cnx:
        ident = a.creer_demande(cnx, "m10-memoire", NOMS[0], ARGS, niveau=Niveau.N3)
        cnx.execute(
            update(APPROBATIONS)
            .where(APPROBATIONS.c.id == ident)
            .values(
                arguments=json.dumps(charge, ensure_ascii=False),
            )
        )
        avant = _tables(cnx)
        for lire in (lambda: a.lire(cnx, ident), lambda: a.lister(cnx)):
            with pytest.raises(ValueError) as exc:
                lire()
            assert str(exc.value) == "projection documentaire indisponible"
            assert exc.value.__suppress_context__ is True
            assert CORPS not in str(exc.value) and EXTRAIT not in str(exc.value)
        assert _tables(cnx) == avant


def test_projection_app_json_dict_copie_impossible_refus_ferme(session):
    arbre = {"corps": CORPS}
    for _ in range(600):
        arbre = {"enfant": arbre}
    with session() as cnx:
        ident = a.creer_demande(cnx, "m10-memoire", NOMS[0], arbre, niveau=Niveau.N3)
        avant = _tables(cnx)
        with pytest.raises(ValueError) as exc:
            a.lire(cnx, ident)
        assert str(exc.value) == "projection documentaire indisponible"
        assert exc.value.__suppress_context__ is True
        assert _tables(cnx) == avant
