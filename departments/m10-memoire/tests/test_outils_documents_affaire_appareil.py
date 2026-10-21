"""Façade documentaire interne fictive : aucun transport/Core/DEVICE opaque livré."""

from __future__ import annotations

import inspect as introspection
import json

import pytest
from m10_memoire import amont, outils, registre
from sqlalchemy import inspect, select, text, update

from opsys import contexte, idempotence, identite, stockage
from opsys.outils import Autonomie, Niveau
from opsys.stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES

FICTIF = True
NOMS = (
    "m10_deposer_version_document_appareil",
    "m10_activer_version_document_appareil",
    "m10_retirer_document_appareil",
)
ARGS_KEYS = (
    ("affaire_id", "document_ref", "version_precedente", "titre", "corps", "confidentialite"),
    ("affaire_id", "document_ref", "version_source", "activation_attendue"),
    ("affaire_id", "document_ref", "activation_attendue", "code_motif"),
)
ACTEUR = contexte.IdentiteAppelante("admin_fictif", "admin", "appareil")
AFFAIRE = "LEAD-FACADE-FICTIF"
HORA = "2026-10-09T20:00:00.000-04:00"
META = idempotence.Meta("uuid-facade-fictif", "device-fictif", HORA)
ARGS = {
    "affaire_id": AFFAIRE,
    "document_ref": None,
    "version_precedente": None,
    "titre": "Titre FICTIF",
    "corps": "CANARI_FACADE_FICTIF_é😀\r\n",
    "confidentialite": "INTERNAL",
}
HISTORIQUES = (
    "m10_journaliser_decision",
    "m10_contexte_preflight",
    "m10_memoriser_wct",
    "m10_signaler_revision",
    "m10_arbitrer_revision",
    "m10_statut_decision",
    "m10_statut_revision",
    "m10_verifier_reference",
    "m10_paquet_contexte_affaire",
    "m10_lire_paquet_affaire_appareil",
    "m10_rechercher_affaire_appareil",
    "m10_consolider_affaire",
    "m10_deposer_faits_candidats",
    "m10_lister_signaux",
    "m10_lire_revision",
    "m10_lister_references",
    "m10_prendre_en_compte_signal",
    "m10_clore_signal",
    "m10_lier_session_affaire",
    "m10_affaire_de_la_session",
    "m10_auditer_non_oubli",
)


def _tool(nom):
    return {o.nom: o for o in outils.outils()}[nom]


@pytest.mark.parametrize("index", range(3))
def test_declaration_fermee_t1_n3_admin_affaire_append_en_fin(index):
    alltools = outils.outils()
    assert tuple(o.nom for o in alltools) == HISTORIQUES + NOMS + (
        "m10_lister_documents_affaire_appareil",
        "m10_lire_version_document_affaire_appareil",
    )
    outil = _tool(NOMS[index])
    assert outil.autonomie is Autonomie.T1 and outil.niveau is Niveau.N3
    assert outil.roles_appareil == frozenset({"admin"})
    assert (outil.portee_contexte, outil.cible_contexte, outil.identite_contexte) == (
        "affaire",
        ("affaire_id",),
        "affaire",
    )
    schema = outil.parametres
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert tuple(schema["properties"]) == ARGS_KEYS[index] and tuple(schema["required"]) == ARGS_KEYS[index]
    signature = introspection.signature(outil.fonction)
    assert tuple(signature.parameters) == ARGS_KEYS[index]
    assert all(
        p.default is introspection.Parameter.empty and p.kind is introspection.Parameter.POSITIONAL_OR_KEYWORD
        for p in signature.parameters.values()
    )


def _tables(cnx):
    return {
        n: sorted(map(tuple, cnx.execute(text('SELECT * FROM "' + n.replace('"', '""') + '"')).all()), key=repr)
        for n in inspect(cnx).get_table_names()
    }


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    monkeypatch.setenv("OPSYS_BASE_URL", f"sqlite:///{tmp_path / 'facade-fictive.db'}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ACTEUR.personne, "Admin FICTIF", "mot-de-passe-FICTIF-1234", ["admin"])
        charge = {
            "lead": {
                "schema_version": 2,
                "lead_id": AFFAIRE,
                "conversation_id": "fictif",
                "contact": {"nom": "FICTIF", "telephone": "+15145550142", "courriel": "fictif@exemple.test"},
                "service": "gouttieres",
                "ville": "Repentigny",
                "urgence_declaree": True,
                "canal": "texte",
                "source": "sms",
                "utm": {},
                "campagne": "FICTIF",
            },
            "horodatage": "2026-10-09T19:00:00-04:00",
            "signal_id": "signal-facade-fictif",
        }
        result, refus = amont.memoriser(
            "m1.lead_qualifie", charge, registre.Registre(stockage.maillons("m10-memoire", "evenements"))
        )
        assert refus is None and result["affaire"]["connue"] is True
    yield
    stockage.liberer()


def _handler(cnx, index=0, args=None, *, meta=META, quota=6000, mode="ombre", actor=ACTEUR):
    with (
        cnx.begin_nested(),
        contexte.appele_par_appareil(actor),
        outils.invocation_documentaire_appareil(cnx, meta=meta, quota=quota, mode_manifeste=mode),
    ):
        return _tool(NOMS[index]).fonction(**(ARGS if args is None else args))


def test_handler_sql_nominal_exact_sans_double_trace_claim_wrapper(monde):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        response = _handler(cnx)
        assert set(response) == {"ok", "resultat", "rejoue"} and response["ok"] is True and response["rejoue"] is False
        assert set(response["resultat"]) == {"accepte", "resultat"} and response["resultat"]["accepte"] is True
        ack = response["resultat"]["resultat"]
        assert ack["intention"] == {
            "appareil": META.appareil,
            "cle": META.cle,
            "outil": NOMS[0],
            "empreinte_arguments": idempotence.empreinte_arguments(ARGS),
        }
        assert ack["horodatage_appareil_declare"] == HORA and ARGS["corps"] not in json.dumps(response)
        apres = _tables(cnx)
        assert len(avant) == 49 and {n for n in avant if avant[n] != apres[n]} == {
            "registres_maillons",
            "mutations_appliquees",
            "approbations",
            "journal",
        }
        assert len(apres["mutations_appliquees"]) == len(apres["approbations"]) == len(apres["journal"]) == 1
        assert cnx.execute(select(APPROBATIONS.c.arguments)).scalar_one() == json.dumps(ARGS, ensure_ascii=False)
        print("TABLES_FACADE_OBSERVEES", len(avant))


def test_trois_handlers_rejeu_v1_apres_v2_retrait_et_reopen(monde):
    with stockage.transaction() as cnx:
        original = _handler(cnx)
        depot = original["resultat"]["resultat"]
        argsact = {
            "affaire_id": AFFAIRE,
            "document_ref": depot["document_ref"],
            "version_source": depot["version_source"],
            "activation_attendue": None,
        }
        metaact = idempotence.Meta("active-fictif", META.appareil, HORA)
        active = _handler(cnx, 1, argsact, meta=metaact)
        _handler(
            cnx,
            args={
                **ARGS,
                "document_ref": depot["document_ref"],
                "version_precedente": depot["version_source"],
                "corps": "V2 FICTIVE",
            },
            meta=idempotence.Meta("version2-fictive", META.appareil, HORA),
        )
        argsret = {
            "affaire_id": AFFAIRE,
            "document_ref": depot["document_ref"],
            "activation_attendue": active["resultat"]["resultat"]["reference"],
            "code_motif": "RETRAIT_ACCES",
        }
        metaret = idempotence.Meta("retire-fictif", META.appareil, HORA)
        retrait = _handler(cnx, 2, argsret, meta=metaret)
    stockage.liberer()
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        for index, args, meta, expected in [
            (0, ARGS, META, original),
            (1, argsact, metaact, active),
            (2, argsret, metaret, retrait),
        ]:
            assert _handler(cnx, index, args, meta=meta) == {**expected, "rejoue": True}
            assert _tables(cnx) == avant


def test_absence_invocation_refuse_avant_tout_sql_et_reset_apres_call(monde):
    from sqlalchemy import event

    with stockage.transaction() as cnx:
        statements = []

        def observer(_c, _cursor, statement, _params, _ctx, _many):
            statements.append(statement)

        event.listen(cnx.engine, "before_cursor_execute", observer)
        try:
            with pytest.raises(RuntimeError) as exc:
                _tool(NOMS[0]).fonction(**ARGS)
            assert str(exc.value) == "CONFIRMATION-INCONNUE" and statements == []
        finally:
            event.remove(cnx.engine, "before_cursor_execute", observer)
        _handler(cnx)
        with pytest.raises(RuntimeError) as exc:
            _tool(NOMS[0]).fonction(**ARGS)
        assert str(exc.value) == "CONFIRMATION-INCONNUE"


@pytest.mark.parametrize("champ,valeur", [("meta", None), ("quota", True), ("quota", 0), ("mode_manifeste", "invente")])
def test_invocation_contradictoire_refuse_avant_sql(monde, champ, valeur):
    from sqlalchemy import event

    with stockage.transaction() as cnx, cnx.begin_nested():
        params = {"meta": META, "quota": 6000, "mode_manifeste": "ombre", champ: valeur}
        seen = []

        def observer(*args):
            seen.append(True)

        event.listen(cnx.engine, "before_cursor_execute", observer)
        try:
            with pytest.raises(RuntimeError) as exc, outils.invocation_documentaire_appareil(cnx, **params):
                _tool(NOMS[0]).fonction(**ARGS)
            assert str(exc.value) == "CONFIRMATION-INCONNUE" and seen == []
        finally:
            event.remove(cnx.engine, "before_cursor_execute", observer)


def test_context_nested_rejete_et_outer_restaure_sur_exception(monde):
    with stockage.transaction() as cnx, cnx.begin_nested(), contexte.appele_par_appareil(ACTEUR):
        with outils.invocation_documentaire_appareil(cnx, meta=META, quota=6000, mode_manifeste="ombre"):
            with (
                pytest.raises(RuntimeError),
                outils.invocation_documentaire_appareil(cnx, meta=META, quota=6000, mode_manifeste="ombre"),
            ):
                pass
            response = _tool(NOMS[0]).fonction(**ARGS)
            assert response["rejoue"] is False
        with pytest.raises(RuntimeError):
            _tool(NOMS[0]).fonction(**ARGS)


@pytest.mark.parametrize(
    "actor",
    [
        None,
        contexte.IdentiteAppelante(ACTEUR.personne, "admin", "console"),
        contexte.IdentiteAppelante(ACTEUR.personne, "employee", "appareil"),
    ],
)
def test_handler_ne_fabrique_pas_autorite_depuis_invocation(monde, actor):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _handler(cnx, actor=actor)
        assert str(exc.value).startswith("REJ-M10-TRANSACTION-AUTORITE-INVALIDE") and _tables(cnx) == avant


@pytest.mark.parametrize("cached", [False, True])
def test_role_sql_retire_ferme_fresh_et_cache(monde, cached):
    with stockage.transaction() as cnx:
        if cached:
            _handler(cnx)
        identite.retirer_role(cnx, ACTEUR.personne, "admin")
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _handler(cnx)
        assert str(exc.value).startswith("REJ-M10-TRANSACTION-AUTORITE-INVALIDE") and _tables(cnx) == avant


@pytest.mark.parametrize("mode", ["supervise", "autonome"])
def test_mode_hors_ombre_ne_tente_pas_effet(monde, mode):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _handler(cnx, mode=mode)
        assert str(exc.value).startswith("REJ-M10-TRANSACTION-MODE-NON-ADMIS") and _tables(cnx) == avant


def test_body_closed_admission_deep_avant_sql(monde):
    from sqlalchemy import event

    with (
        stockage.transaction() as cnx,
        cnx.begin_nested(),
        outils.invocation_documentaire_appareil(cnx, meta=META, quota=6000, mode_manifeste="ombre"),
    ):
        seen = []

        def observer(*args):
            seen.append(True)

        event.listen(cnx.engine, "before_cursor_execute", observer)
        try:
            with pytest.raises(RuntimeError) as exc:
                _tool(NOMS[0]).fonction(**{**ARGS, "corps": float("nan")})
            assert str(exc.value) == "CONFIRMATION-INCONNUE" and seen == []
        finally:
            event.remove(cnx.engine, "before_cursor_execute", observer)


def test_cache_json_duplique_et_quota_ne_deviennent_pas_succes(monde):
    with stockage.transaction() as cnx:
        response = _handler(cnx)
        cnx.execute(
            update(MUTATIONS_APPLIQUEES).values(
                reponse='{"ok":false,' + json.dumps({"ok": True, "resultat": response["resultat"]})[1:]
            )
        )
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _handler(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant
        with pytest.raises(RuntimeError) as exc:
            _handler(cnx, meta=idempotence.Meta("quota-fictif", META.appareil, HORA), quota=40)
        assert exc.value.code.endswith("QUOTA-DEPASSE") and _tables(cnx) == avant


def test_invocation_frozen_et_reset_meme_sur_exception(monde):
    from dataclasses import FrozenInstanceError

    with stockage.transaction() as cnx, cnx.begin_nested():
        with (
            pytest.raises(ValueError),
            outils.invocation_documentaire_appareil(cnx, meta=META, quota=6000, mode_manifeste="ombre"),
        ):
            invocation = outils._INVOCATION_DOCUMENTAIRE.get()
            with pytest.raises(FrozenInstanceError):
                invocation.quota = 1
            raise ValueError("panne FICTIVE caller")
        assert outils._INVOCATION_DOCUMENTAIRE.get() is None


def test_invocation_sans_savepoint_et_autre_connexion_refusee(monde):
    from sqlalchemy import create_engine

    with stockage.transaction() as cnx:
        with (
            pytest.raises(RuntimeError),
            outils.invocation_documentaire_appareil(cnx, meta=META, quota=6000, mode_manifeste="ombre"),
        ):
            pass
        engine = create_engine("sqlite:///:memory:")
        try:
            with (
                engine.connect() as autre,
                autre.begin(),
                autre.begin_nested(),
                pytest.raises(RuntimeError),
                outils.invocation_documentaire_appareil(autre, meta=META, quota=6000, mode_manifeste="ombre"),
            ):
                pass
        finally:
            engine.dispose()


@pytest.mark.parametrize(
    "meta",
    [
        idempotence.Meta("x" * 129, META.appareil, HORA),
        idempotence.Meta(META.cle, "\ud800", HORA),
        idempotence.Meta(META.cle, META.appareil, "invalid"),
    ],
)
def test_meta_closed_refuse_avant_sql(monde, meta):
    from sqlalchemy import event

    with stockage.transaction() as cnx, cnx.begin_nested():
        seen = []

        def observer(*args):
            seen.append(True)

        event.listen(cnx.engine, "before_cursor_execute", observer)
        try:
            with (
                pytest.raises(RuntimeError) as exc,
                outils.invocation_documentaire_appareil(cnx, meta=meta, quota=6000, mode_manifeste="ombre"),
            ):
                pass
            assert str(exc.value) == "CONFIRMATION-INCONNUE" and seen == []
        finally:
            event.remove(cnx.engine, "before_cursor_execute", observer)


def test_affaire_hors_corpus_reste_refusee_par_backend(monde):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _handler(cnx, args={**ARGS, "affaire_id": "LEAD-ABSENT-FICTIF"})
        assert exc.value.code.endswith("AFFAIRE-INCONNUE") and _tables(cnx) == avant


def test_panne_backend_posttrace_escape_caller_pas_couple_negative(monde, monkeypatch):
    from opsys import documents_affaire_transactions as backend

    original = backend._ajouter_liaison

    def panne(cnx, candidat, rang):
        original(cnx, candidat, rang)
        raise KeyError(ARGS["corps"])

    monkeypatch.setattr(backend, "_ajouter_liaison", panne)
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _handler(cnx)
        assert (
            exc.value.code.endswith("PANNE-TRANSACTION")
            and ARGS["corps"] not in str(exc.value)
            and _tables(cnx) == avant
        )
    monkeypatch.setattr(backend, "_ajouter_liaison", original)
    with stockage.transaction() as cnx:
        assert _handler(cnx)["rejoue"] is False
