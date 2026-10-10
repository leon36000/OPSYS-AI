"""Cap/SQLite FICTIF avec identité injectée : aucune preuve HTTP/DEVICE opaque."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select, update

from opsys import approbations, contexte, idempotence, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau
from opsys.stockage import codec
from opsys.stockage.schema import MUTATIONS_APPLIQUEES, PERSONNES

fixture = Path(__file__).parent / "test_documents_affaire_transactions.py"
spec = importlib.util.spec_from_file_location("fixture_cap_documents_fictifs", fixture)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
monde = fx.monde
FICTIF = True
NOMS = (
    "m10_deposer_version_document_appareil",
    "m10_activer_version_document_appareil",
    "m10_retirer_document_appareil",
)
MAPPING = {
    "CONNEXION-INVALIDE": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "DIALECTE-NON-ADMIS": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "AUTORITE-INVALIDE": "REJ-M10-DOC-AUTORITE-INVALIDE",
    "MODE-NON-ADMIS": "REJ-M10-DOC-MODE-NON-ADMIS",
    "FORME-INVALIDE": "REJ-M10-DOC-FORME-INVALIDE",
    "AFFAIRE-INCONNUE": "REJ-M10-DOC-AFFAIRE-INCONNUE",
    "REGISTRE-INVALIDE": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "QUOTA-DEPASSE": "QUOTA-DEPASSE",
    "PRECONDITION-REFUSEE": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "CONFIRMATION-INCONNUE": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    "PANNE-TRANSACTION": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
}


def cap(quota=6000, factory=stockage.transaction):
    return Capacites(charger_departements(), factory, filtre={"m10-memoire"}, memoire=False, limite_sortie=quota)


def appeler(c, args=None, *, nom=NOMS[0], meta=fx.META, actor=fx.ACTEUR, **tickets):
    with contexte.appele_par_appareil(actor):
        return c.appeler(nom, fx.ARGS if args is None else args, meta=meta, **tickets)


def tables():
    with stockage.transaction() as cnx:
        return fx._tables(cnx)


def interdite():
    raise AssertionError("La garde doit précéder toute factory/SQL.")


@pytest.mark.parametrize(
    "args",
    [None, [], [["affaire_id", fx.AFFAIRE]], "", 1, {}, {**fx.ARGS, "corps": "\ud800"}, {**fx.ARGS, "extra": "CANARI"}],
)
def test_raw_args_refuses_avant_factory(args):
    c = cap(factory=interdite)
    with contexte.appele_par_appareil(fx.ACTEUR):
        response = c.appeler(NOMS[0], args, fx.META)
    assert response == {"ok": False, "erreur": "REJ-M10-DOC-FORME-INVALIDE"}


@pytest.mark.parametrize(
    "actor",
    [None, contexte.IdentiteAppelante("x", "admin", "console"), contexte.IdentiteAppelante("x", "employe", "appareil")],
)
def test_autorite_non_device_admin_refuse_avant_factory(actor):
    assert appeler(cap(factory=interdite), actor=actor) == {"ok": False, "erreur": "REJ-M10-DOC-AUTORITE-INVALIDE"}


@pytest.mark.parametrize(
    "meta",
    [
        None,
        object(),
        idempotence.Meta("x" * 129, "d", fx.HORA),
        idempotence.Meta("c", "d" * 129, fx.HORA),
        idempotence.Meta("c", "d", "2026-10-09"),
        idempotence.Meta("c", "\ud800", fx.HORA),
    ],
)
def test_meta_strict_128_refuse_avant_factory(meta):
    assert appeler(cap(factory=interdite), meta=meta) == {"ok": False, "erreur": "REJ-M10-DOC-FORME-INVALIDE"}


@pytest.mark.parametrize("nom", NOMS)
def test_profile_refuse_avant_factory(nom):
    c = cap(factory=interdite)
    assert c.appeler_profil_runtime(
        nom, fx.ARGS, fx.META, None, profile_id="fictif", profile_revision=1, server="opsys_m10"
    ) == {"ok": False, "erreur": "REJ-M10-DOC-AUTORITE-INVALIDE"}


@pytest.mark.parametrize("ticket", ["ticket_cible", "ticket_memoire"])
def test_tickets_refuses_avant_factory(ticket):
    assert appeler(cap(factory=interdite), **{ticket: "FICTIF"}) == {
        "ok": False,
        "erreur": "REJ-M10-DOC-AUTORITE-INVALIDE",
    }


@pytest.mark.parametrize("quota", [1, 39, True, None])
def test_petit_quota_technique_avant_factory(quota):
    with pytest.raises(RuntimeError, match="^QUOTA-INSUFFISANT$"):
        appeler(cap(quota, interdite))


def test_quota40_refus_compact_sans_factory():
    with contexte.appele_par_appareil(fx.ACTEUR):
        result = cap(40, interdite).appeler(NOMS[0], None, fx.META)
    assert result == {"ok": False, "erreur": "QUOTA-DEPASSE"}
    assert len(json.dumps(result, ensure_ascii=False)) == 40


@pytest.mark.parametrize("change", ["missing", "owner", "level", "autonomy", "scope"])
def test_index_et_portee_refusent_avant_factory(change):
    c = cap(factory=interdite)
    d, outil = c.index[NOMS[0]]
    if change == "missing":
        c.index.pop(NOMS[0])
    elif change == "owner":
        c.index[NOMS[0]] = (None, outil)
    elif change == "level":
        c.index[NOMS[0]] = (d, dataclasses.replace(outil, niveau=Niveau.N4))
    elif change == "autonomy":
        c.index[NOMS[0]] = (d, dataclasses.replace(outil, autonomie=Autonomie.T0))
    else:
        c._portees_roles = {"admin": frozenset()}
    assert appeler(c) == {"ok": False, "erreur": "REJ-M10-DOC-AUTORITE-INVALIDE"}


def test_positive_sql_sans_double_claim_trace_frame_ni_generic(monde, monkeypatch):
    c = cap()
    for method in ["_distribuer", "_appeler_idempotent", "_tronquer", "_valider_au_depart"]:
        monkeypatch.setattr(c, method, lambda *a, **k: interdite())
    before = tables()
    result = appeler(c)
    assert set(result) == {"ok", "resultat", "rejoue"} and result["ok"] is True
    assert result["rejoue"] is False and result["resultat"]["accepte"] is True
    ack = result["resultat"]["resultat"]
    assert ack["intention"] == {
        "appareil": fx.META.appareil,
        "cle": fx.META.cle,
        "outil": NOMS[0],
        "empreinte_arguments": idempotence.empreinte_arguments(fx.ARGS),
    }
    assert ack["auteur"] == {"personne": fx.ACTEUR.personne, "role": "admin", "source": "appareil"}
    assert ack["horodatage_appareil_declare"] == fx.HORA
    after = tables()
    assert len(before) == 49 and {n for n in before if before[n] != after[n]} == {
        "registres_maillons",
        "mutations_appliquees",
        "approbations",
        "journal",
    }
    assert len(after["mutations_appliquees"]) == len(after["approbations"]) == len(after["journal"]) == 1
    assert not after["artefacts"] and fx.CORPS not in json.dumps(result)
    assert appeler(c) == {**result, "rejoue": True} and after == tables()


def test_propre_v1_apres_v2_retrait_reopen_et_body_conflit(monde):
    c = cap()
    first = appeler(c)
    ack = first["resultat"]["resultat"]
    args2 = {
        **fx.ARGS,
        "document_ref": ack["document_ref"],
        "version_precedente": ack["reference"],
        "corps": "FICTIF v2",
    }
    r2 = appeler(c, args2, meta=idempotence.Meta("v2", fx.META.appareil, fx.HORA))
    assert r2["ok"] is True
    retrait = {
        "affaire_id": fx.AFFAIRE,
        "document_ref": ack["document_ref"],
        "activation_attendue": None,
        "code_motif": "RETRAIT_ACCES",
    }
    assert appeler(c, retrait, nom=NOMS[2], meta=idempotence.Meta("retrait", fx.META.appareil, fx.HORA))["ok"] is True
    after = tables()
    stockage.liberer()
    assert appeler(cap()) == {**first, "rejoue": True} and after == tables()
    assert appeler(cap(), {**fx.ARGS, "titre": "FICTIF conflit"}) == {
        "ok": False,
        "erreur": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    }
    assert after == tables()


def test_role_sql_revoque_avant_rejeu_puis_restore(monde):
    first = appeler(cap())
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == fx.ACTEUR.personne).values(actif=False))
    before = tables()
    assert appeler(cap()) == {"ok": False, "erreur": "REJ-M10-DOC-AUTORITE-INVALIDE"}
    assert before == tables()
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == fx.ACTEUR.personne).values(actif=True))
    before = tables()
    assert appeler(cap()) == {**first, "rejoue": True} and before == tables()


@pytest.mark.parametrize("suffixe,code", MAPPING.items())
def test_backend_errors_sortent_savepoint_factory_avant_mapping(monde, monkeypatch, suffixe, code):
    from opsys import documents_affaire_transactions as backend

    original = backend._ajouter_liaison

    def apres_append(*a, **k):
        original(*a, **k)
        raise backend.ErreurTransactionDocumentaire(suffixe)

    monkeypatch.setattr(backend, "_ajouter_liaison", apres_append)
    before = tables()
    assert appeler(cap()) == {"ok": False, "erreur": code}
    assert before == tables()


@pytest.mark.parametrize("quota", [40, 59])
def test_unknown_ne_devient_jamais_quota_apres_effet_rollback(monde, monkeypatch, quota):
    from opsys import documents_affaire_transactions as backend

    def panne(*a, **k):
        raise backend.ErreurTransactionDocumentaire("CONFIRMATION-INCONNUE")

    monkeypatch.setattr(backend, "muter_document_m10", panne)
    before = tables()
    with pytest.raises(RuntimeError, match="^CONFIRMATION-INCONNUE$"):
        appeler(cap(quota))
    assert before == tables()


def test_fresh_quota_et_cache_quota_sans_artefact(monde):
    first = appeler(cap())
    after = tables()
    size = len(json.dumps(first, ensure_ascii=False))
    assert size > 800  # This fixture actually exercises a whole ACK larger than 800.
    with pytest.raises(RuntimeError, match="^CONFIRMATION-INCONNUE$"):
        appeler(cap(40))
    assert after == tables()
    assert appeler(cap(550)) == {"ok": False, "erreur": "REJ-M10-DOC-CONFIRMATION-INCONNUE"}
    assert after == tables()
    fresh = idempotence.Meta("quota-fictif", fx.META.appareil, fx.HORA)
    assert len(fresh.cle) == len(fx.META.cle)
    assert appeler(cap(800), meta=fresh) == {"ok": False, "erreur": "QUOTA-DEPASSE"}
    assert after == tables()
    result = appeler(cap(size), meta=fresh)
    assert result["ok"] is True and len(json.dumps(result, ensure_ascii=False)) == size
    assert len(tables()["mutations_appliquees"]) == 2
    assert appeler(cap()) == {**first, "rejoue": True}


def test_cache_negatif_ne_confirme_pas_et_restore_own(monde):
    first = appeler(cap())
    with stockage.transaction() as cnx:
        original = cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse)).scalar_one()
        cnx.execute(update(MUTATIONS_APPLIQUEES).values(reponse=codec.encoder({"ok": False, "erreur": "FICTIF"})))
    before = tables()
    assert appeler(cap()) == {"ok": False, "erreur": "REJ-M10-DOC-CONFIRMATION-INCONNUE"}
    assert before == tables()
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).values(reponse=original))
    before = tables()
    assert appeler(cap()) == {**first, "rejoue": True} and before == tables()


@pytest.mark.parametrize("personne", ["", "x", "BAD PERSON", "\ud800"])
def test_personne_inadmissible_refuse_avant_factory(personne):
    actor = contexte.IdentiteAppelante(personne, "admin", "appareil")
    assert appeler(cap(factory=interdite), actor=actor) == {"ok": False, "erreur": "REJ-M10-DOC-AUTORITE-INVALIDE"}


@pytest.mark.parametrize(
    "field",
    [
        "flag",
        "schema",
        "operation",
        "uuid",
        "bodyhash",
        "author",
        "hour",
        "refbool",
        "refhash",
        "source",
        "extra",
        "negative",
    ],
)
def test_whole_ack_altere_apres_vrai_writer_annule_caller(monde, monkeypatch, field):
    from opsys import documents_affaire_transactions as backend

    original = backend.muter_document_m10
    before = tables()
    effects = []

    def alterer(cnx, *a, **k):
        result = original(cnx, *a, **k)
        inside = fx._tables(cnx)
        effects.append({n for n in before if before[n] != inside[n]})
        ack = result["resultat"]["resultat"]
        if field == "flag":
            result["rejoue"] = 1
        elif field == "schema":
            ack["version_schema"] = True
        elif field == "operation":
            ack["operation"] = "retirer"
        elif field == "uuid":
            ack["intention"]["cle"] = "FICTIF-autre"
        elif field == "bodyhash":
            ack["intention"]["empreinte_arguments"] = "0" * 64
        elif field == "author":
            ack["auteur"]["personne"] = "autre_fictif"
        elif field == "hour":
            ack["horodatage_appareil_declare"] = "2026-10-10T00:00:00Z"
        elif field == "refbool":
            ack["reference"]["index"] = False
        elif field == "refhash":
            ack["reference"]["ligne_id"] = "pas-une-empreinte"
        elif field == "source":
            ack["source_sha256"] = "0" * 64
        elif field == "extra":
            result["corps"] = fx.CORPS
        else:
            result["resultat"] = {"accepte": False, "verdict": "FICTIF"}
        return result

    monkeypatch.setattr(backend, "muter_document_m10", alterer)
    assert appeler(cap()) == {"ok": False, "erreur": "REJ-M10-DOC-CONFIRMATION-INCONNUE"}
    assert effects == [{"registres_maillons", "mutations_appliquees", "approbations", "journal"}]
    assert before == tables()


def test_mapping_apres_factory_et_panne_sans_echo(monde, monkeypatch):
    from opsys import documents_affaire_transactions as backend

    c = cap()
    refus = c.refus_documentaire_appareil
    observed = []

    def traduire(code, **kw):
        observed.append(stockage.connexion_courante())
        assert stockage.connexion_courante() is None
        return refus(code, **kw)

    monkeypatch.setattr(c, "refus_documentaire_appareil", traduire)

    def panne(*a, **k):
        raise RuntimeError("CANARI_SQL_FICTIF_SECRET_NE_DOIT_PAS_SORTIR")

    monkeypatch.setattr(backend, "muter_document_m10", panne)
    before = tables()
    assert appeler(c) == {"ok": False, "erreur": "REJ-M10-DOC-CONFIRMATION-INCONNUE"}
    assert observed == [None] and before == tables()


@pytest.mark.parametrize("attribute", ["code", "issue", "detail"])
def test_exception_backend_attributs_plain_uniquement(monde, monkeypatch, attribute):
    from opsys import documents_affaire_transactions as backend

    class Piege:
        def __eq__(self, other):
            raise AssertionError("Ne pas invoquer un attribut arbitraire.")

        def __str__(self):
            raise AssertionError("Ne pas exposer un attribut arbitraire.")

    def panne(*a, **k):
        erreur = backend.ErreurTransactionDocumentaire("QUOTA-DEPASSE")
        setattr(erreur, attribute, Piege())
        raise erreur

    monkeypatch.setattr(backend, "muter_document_m10", panne)
    before = tables()
    assert appeler(cap()) == {"ok": False, "erreur": "REJ-M10-DOC-CONFIRMATION-INCONNUE"}
    assert before == tables()


def test_mode_sql_courant_avant_cached_et_restore(monde):
    first = appeler(cap())
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", "autonome", fx.ACTEUR.personne)
    before = tables()
    assert appeler(cap()) == {"ok": False, "erreur": "REJ-M10-DOC-MODE-NON-ADMIS"}
    assert before == tables()
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", "ombre", fx.ACTEUR.personne)
    before = tables()
    assert appeler(cap()) == {**first, "rejoue": True} and before == tables()


def test_factory_non_canonique_refuse_avant_business(monde, monkeypatch):
    from contextlib import nullcontext

    from opsys import documents_affaire_transactions as backend

    monkeypatch.setattr(backend, "muter_document_m10", lambda *a, **k: interdite())
    before = tables()
    assert appeler(cap(factory=lambda: nullcontext(object()))) == {
        "ok": False,
        "erreur": "REJ-M10-DOC-CONFIRMATION-INCONNUE",
    }
    assert before == tables()


def test_quota_reduit_apres_ecriture_unknown_reste_meme_categorie(monde, monkeypatch):
    from opsys import documents_affaire_transactions as backend

    c = cap()
    original = backend.muter_document_m10

    def apres_effet(*a, **kw):
        original(*a, **kw)
        c._limite = 1
        raise backend.ErreurTransactionDocumentaire('CONFIRMATION-INCONNUE')

    monkeypatch.setattr(backend, 'muter_document_m10', apres_effet)
    before = tables()
    with pytest.raises(RuntimeError, match='^CONFIRMATION-INCONNUE$'):
        appeler(c)
    assert before == tables()
