"""Oracles purs fictifs : aucune identité SQL/DEVICE, transaction ou donnée réelle."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

FICTIF = True
AFFAIRE = "chantier-fictif"
HORA = "2026-10-09T14:00:00.000-04:00"
OUTILS = {
    "deposer": "m10_deposer_version_document_appareil",
    "activer": "m10_activer_version_document_appareil",
    "retirer": "m10_retirer_document_appareil",
}


def _d():
    return importlib.import_module("m10_memoire.documents_affaire")


def _ctx(args, cle="intention-fictive-1", operation="deposer", **changes):
    ctx = {
        "affaire_id": AFFAIRE,
        "auteur": {"personne": "admin_fictif", "role": "admin", "source": "appareil"},
        "intention": {
            "appareil": "appareil-fictif",
            "cle": cle,
            "outil": OUTILS[operation],
            "empreinte_arguments": hashlib.sha256(
                json.dumps(
                    args,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        },
        "horodatage_appareil_declare": HORA,
        "horodatage": "2026-10-09T18:00:02+00:00",
        "situation": {"connue": True, "origine_recue": False, "origine": None, "verdict": "AMONT-ORIGINE-NON-RECUE"},
        "mode": "ombre",
        "quota": 6000,
    }
    ctx.update(changes)
    return ctx


def _depot(corps="Note fictive : Aé😀\r\nZ", **changes):
    args = {
        "affaire_id": AFFAIRE,
        "document_ref": None,
        "version_precedente": None,
        "titre": "Note fictive",
        "corps": corps,
        "confidentialite": "INTERNAL",
    }
    args.update(changes)
    return args


def _ref(maillons, index):
    return {"registre": "documents_affaire", "index": index, "ligne_id": maillons[index]["ligne_id"]}


def _source():
    args = _depot()
    ctx = _ctx(args)
    return [_d().preparer_depot([], args, ctx)], args, ctx


def _activer(maillons, source=0, attendu=None, cle="activation-fictive"):
    args = {
        "affaire_id": AFFAIRE,
        "document_ref": _ref(maillons, 0),
        "version_source": _ref(maillons, source),
        "activation_attendue": attendu,
    }
    ctx = _ctx(args, cle, "activer")
    return maillons + [_d().preparer_activation(maillons, args, ctx)], args, ctx


def _citation(maillons, source=0, activation=1, debut=0, fin=None):
    m = maillons[source]
    raw = m["corps"].encode()
    fin = len(raw) if fin is None else fin
    return {
        "version_schema": 1,
        "affaire_id": AFFAIRE,
        "document_ref": _ref(maillons, 0),
        "version_source": _ref(maillons, source),
        "activation_ref": _ref(maillons, activation),
        "source_sha256": m["source_sha256"],
        "methode": "utf8-exact-v1",
        "debut_octet": debut,
        "fin_octet": fin,
        "extrait": raw[debut:fin].decode(),
    }


def _claim(maillons, index, ctx):
    intention = ctx["intention"]
    return {
        "appareil": intention["appareil"],
        "cle": intention["cle"],
        "outil": intention["outil"],
        "empreinte_arguments": intention["empreinte_arguments"],
        "horodatage_appareil": ctx["horodatage_appareil_declare"],
        "statut": "ok",
        "reponse": {
            "ok": True,
            "resultat": {"accepte": True, "resultat": _d().accuse_propre(maillons, _ref(maillons, index))},
        },
    }


def test_reference_initiale_projetee_et_chaine_existante():
    from m10_memoire.registre import Registre

    maillons, args, ctx = _source()
    m = maillons[0]
    assert "document_ref" not in m
    assert Registre(maillons).valider_chaine() == (True, "")
    ack = _d().accuse_propre(maillons, _ref(maillons, 0))
    assert ack["document_ref"] == _ref(maillons, 0) == ack["reference"]
    assert "corps" not in ack and "courant" not in ack
    assert args == _depot() and ctx["horodatage_appareil_declare"] == HORA


@pytest.mark.parametrize(
    "text,hexadecimal",
    [
        ("e\u0301\n😀", "65cc810af09f9880"),
        ("Aé😀\r\nZ", "41c3a9f09f98800d0a5a"),
        ("é", "c3a9"),
        ("e\u0301", "65cc81"),
    ],
)
def test_utf8_exact_vecteurs_independants(text, hexadecimal):
    args = _depot(text)
    m = _d().preparer_depot([], args, _ctx(args))
    raw = bytes.fromhex(hexadecimal)
    assert m["corps"] == text and m["taille_octets"] == len(raw)
    assert m["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert m["taille_points"] == len(text)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda a: a.update(extra=True),
        lambda a: a.pop("confidentialite"),
        lambda a: a.update(confidentialite="FINANCIAL"),
        lambda a: a.update(corps="\ud800"),
        lambda a: a.update(document_ref={"registre": "documents_affaire", "index": True, "ligne_id": "0" * 64}),
    ],
)
def test_commandes_fermees(mutation):
    args = _depot()
    mutation(args)
    with pytest.raises(_d().RefusDocument):
        _d().preparer_depot([], args, _ctx(_depot()))


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "autonome"),
        ("mode", "supervise"),
        ("mode", "invente"),
        ("quota", True),
        ("quota", 0),
        ("auteur", {"personne": "admin_fictif", "role": "nathan_owner", "source": "appareil"}),
        ("auteur", {"personne": "admin_fictif", "role": "admin", "source": "approbation"}),
        ("situation", {"connue": True, "origine_recue": False, "origine": "libre", "verdict": None}),
        ("situation", {"connue": True, "origine_recue": False, "origine": None, "verdict": {"secret": "fictif"}}),
        ("situation", {"connue": False, "origine_recue": False, "origine": None, "verdict": "AMONT-AFFAIRE-INCONNUE"}),
    ],
)
def test_contexte_forme_et_amont_fermes(field, value):
    args = _depot()
    with pytest.raises(_d().RefusDocument):
        _d().preparer_depot([], args, _ctx(args, **{field: value}))


def test_empreinte_arguments_et_no_mutation_inputs():
    args = _depot()
    ctx = _ctx(args)
    ctx["intention"]["empreinte_arguments"] = "0" * 64
    before = copy.deepcopy((args, ctx))
    with pytest.raises(_d().RefusDocument):
        _d().preparer_depot([], args, ctx)
    assert (args, ctx) == before


def test_deposee_non_activee_lisible_non_citable():
    maillons, args, ctx = _source()
    dto = _d().lire_version(maillons, AFFAIRE, _ref(maillons, 0), _ref(maillons, 0), _lecture_ctx(ctx))
    assert dto["statut"] == "DEPOSEE_NON_ACTIVEE" and dto["corps"] == args["corps"]
    assert dto["activation_ref"] is None
    fake = _citation(maillons, activation=0)
    with pytest.raises(_d().RefusDocument):
        _d().verifier_citation(maillons, fake, _lecture_ctx(ctx))


def test_citation_exacte_sur_activation():
    args = _depot("Aé😀\r\nZ")
    maillons = [_d().preparer_depot([], args, _ctx(args))]
    maillons, _, ctx = _activer(maillons)
    citation = _citation(maillons, debut=1, fin=7)
    assert citation["extrait"] == "é😀"
    assert _d().verifier_citation(maillons, citation, _lecture_ctx(ctx)) == citation


@pytest.mark.parametrize(
    "changes",
    [
        {"debut_octet": 2},
        {"fin_octet": 6},
        {"debut_octet": True},
        {"extrait": "substitution fictive"},
        {"source_sha256": "0" * 64},
        {"activation_ref": {"registre": "documents_affaire", "index": 0, "ligne_id": "0" * 64}},
    ],
)
def test_citation_corrompue_sans_extrait_partiel(changes):
    maillons, _, _ = _source()
    maillons, _, ctx = _activer(maillons)
    citation = _citation(maillons)
    citation.update(changes)
    with pytest.raises(_d().RefusDocument) as caught:
        _d().verifier_citation(maillons, citation, _lecture_ctx(ctx))
    assert "substitution" not in str(caught.value)


def test_versions_et_historique_citable():
    maillons, _, _ = _source()
    maillons, _, ctx = _activer(maillons)
    args = _depot("Version2 fictive", document_ref=_ref(maillons, 0), version_precedente=_ref(maillons, 0))
    maillons += [_d().preparer_depot(maillons, args, _ctx(args, "version-2"))]
    assert (
        _d().lire_version(maillons, AFFAIRE, _ref(maillons, 0), _ref(maillons, 0), _lecture_ctx(ctx))["statut"]
        == "COURANTE"
    )
    assert (
        _d().lire_version(maillons, AFFAIRE, _ref(maillons, 0), _ref(maillons, 2), _lecture_ctx(ctx))["statut"]
        == "DEPOSEE_NON_ACTIVEE"
    )
    maillons, _, ctx = _activer(maillons, 2, _ref(maillons, 1), "activation-2")
    old = _d().lire_version(maillons, AFFAIRE, _ref(maillons, 0), _ref(maillons, 0), _lecture_ctx(ctx))
    assert old["statut"] == "HISTORIQUE_NON_COURANTE" and old["corps"].startswith("Note fictive")
    c = _citation(maillons)
    assert _d().verifier_citation(maillons, c, _lecture_ctx(ctx)) == c
    assert (
        _d().lire_version(maillons, AFFAIRE, _ref(maillons, 0), _ref(maillons, 2), _lecture_ctx(ctx))["corps"]
        == args["corps"]
    )


def test_activation_CAS_ABA():
    maillons, _, _ = _source()
    maillons, _, _ = _activer(maillons)
    old = _ref(maillons, 1)
    args = _depot("Autre version fictive", document_ref=_ref(maillons, 0), version_precedente=_ref(maillons, 0))
    maillons += [_d().preparer_depot(maillons, args, _ctx(args, "v2"))]
    maillons, _, _ = _activer(maillons, 2, old, "activer-B")
    maillons, _, _ = _activer(maillons, 0, _ref(maillons, 3), "retour-A")
    stale = {
        "affaire_id": AFFAIRE,
        "document_ref": _ref(maillons, 0),
        "version_source": _ref(maillons, 2),
        "activation_attendue": old,
    }
    with pytest.raises(_d().RefusDocument, match="REVISION-PERIMEE"):
        _d().preparer_activation(maillons, stale, _ctx(stale, "stale", "activer"))


def test_retrait_ferme_tous_corps_mais_garde_ack_propre():
    maillons, _, ctx_source = _source()
    claim = _claim(maillons, 0, ctx_source)
    maillons, _, _ = _activer(maillons)
    c = _citation(maillons)
    args = {
        "affaire_id": AFFAIRE,
        "document_ref": _ref(maillons, 0),
        "activation_attendue": _ref(maillons, 1),
        "code_motif": "RETRAIT_ACCES",
    }
    ctx = _ctx(args, "retrait", "retirer")
    maillons += [_d().preparer_retrait(maillons, args, ctx)]
    dto = _d().lire_version(maillons, AFFAIRE, _ref(maillons, 0), _ref(maillons, 0), _lecture_ctx(ctx))
    assert dto["statut"] == "RETIREE" and "corps" not in dto
    with pytest.raises(_d().RefusDocument, match="RETIRE"):
        _d().verifier_citation(maillons, c, _lecture_ctx(ctx))
    assert _d().verifier_rejeu(maillons, claim, ctx_source) == claim["reponse"]["resultat"]["resultat"]


def test_rejeu_v1_apres_v2_heure_originale_et_quotas():
    maillons, _, ctx = _source()
    claim = _claim(maillons, 0, ctx)
    args = _depot("v2 fictive", document_ref=_ref(maillons, 0), version_precedente=_ref(maillons, 0))
    maillons += [_d().preparer_depot(maillons, args, _ctx(args, "v2"))]
    before = copy.deepcopy(maillons)
    ctx["horodatage"] = "2026-10-10T18:00:00+00:00"
    ack = _d().verifier_rejeu(maillons, claim, ctx)
    assert ack == claim["reponse"]["resultat"]["resultat"]
    assert ack["horodatage_appareil_declare"] == HORA and maillons == before
    with pytest.raises(_d().RefusDocument):
        _d().verifier_rejeu(maillons, claim, {**ctx, "quota": 40})


@pytest.mark.parametrize(
    "alteration",
    [
        lambda c: c.update(cle="autre-UUID"),
        lambda c: c.update(appareil="autre-appareil"),
        lambda c: c.update(horodatage_appareil=HORA.replace(".000", "")),
        lambda c: c.update(statut="refus_metier", reponse={"ok": False, "erreur": "REFUS-FICTIF"}),
        lambda c: c["reponse"]["resultat"]["resultat"].update(version_schema=True),
        lambda c: c["reponse"]["resultat"]["resultat"].update(
            reference={"registre": "documents_affaire", "index": False, "ligne_id": "0" * 64}
        ),
    ],
)
def test_cache_ambigu_ou_refus_est_inconnu(alteration):
    maillons, _, ctx = _source()
    c = _claim(maillons, 0, ctx)
    alteration(c)
    with pytest.raises(_d().RefusDocument, match="CONFIRMATION-INCONNUE"):
        _d().verifier_rejeu(maillons, c, ctx)


def test_deux_UUID_meme_corps_heure_pas_de_correlation_inventee():
    maillons, args, ctx = _source()
    other = _ctx(args, "autre-intention")
    maillons.append(_d().preparer_depot(maillons, args, other))
    assert _d().verifier_rejeu(maillons, _claim(maillons, 0, ctx), ctx)["reference"] == _ref(maillons, 0)
    assert _d().verifier_rejeu(maillons, _claim(maillons, 1, other), other)["reference"] == _ref(maillons, 1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("corps", "texte altéré"),
        ("taille_octets", True),
        ("version_no", 1.0),
        ("precedent_ligne_id", "0" * 64),
        ("ligne_id", "0" * 64),
    ],
)
def test_maillon_corrompu_est_refuse(field, value):
    maillons, _, _ = _source()
    maillons[0][field] = value
    with pytest.raises(_d().RefusDocument):
        _d().valider_snapshot(maillons)


def test_enveloppe_limites_exactes_et_flags():
    d = _d()
    frame = {"ok": True, "resultat": "fictif", "rejoue": False}
    exact = len(json.dumps(frame, ensure_ascii=False, allow_nan=False))
    d.borner_enveloppe(frame, exact)
    with pytest.raises(d.RefusDocument, match="QUOTA"):
        d.borner_enveloppe(frame, exact - 1)
    d.borner_enveloppe(frame, exact + 1)
    assert len(json.dumps({**frame, "rejoue": True})) == exact - 1
    payload = {"ok": True, "resultat": ""}
    n = 6000 - len(json.dumps(payload, ensure_ascii=False))
    payload["resultat"] = "x" * n
    assert len(json.dumps(payload, ensure_ascii=False)) == 6000
    d.borner_enveloppe(payload, 6000)
    with pytest.raises(d.RefusDocument):
        d.borner_enveloppe(payload, 5999)


def test_bornes_entree_2000_points_8000_octets_pas_garantie_sortie():
    d = _d()
    args = _depot("😀" * 2000)
    m = d.preparer_depot([], args, _ctx(args))
    assert m["taille_octets"] == 8000
    too = _depot("😀" * 2001)
    with pytest.raises(d.RefusDocument):
        d.preparer_depot([], too, _ctx(too))
    escaped = _depot("\x00" * 2000)
    chain = [d.preparer_depot([], escaped, _ctx(escaped))]
    with pytest.raises(d.RefusDocument, match="QUOTA"):
        d.lire_version(chain, AFFAIRE, _ref(chain, 0), _ref(chain, 0), _lecture_ctx(_ctx(escaped)))


def test_huit_documents_et_huit_versions():
    d = _d()
    maillons = []
    for i in range(8):
        args = _depot(f"Document fictif{i}")
        maillons.append(d.preparer_depot(maillons, args, _ctx(args, f"doc{i}")))
    args = _depot("Document neuf fictif")
    with pytest.raises(d.RefusDocument, match="BORNE"):
        d.preparer_depot(maillons, args, _ctx(args, "doc9"))
    maillons = [maillons[0]]
    for i in range(2, 9):
        args = _depot(
            f"Version fictive{i}", document_ref=_ref(maillons, 0), version_precedente=_ref(maillons, len(maillons) - 1)
        )
        maillons.append(d.preparer_depot(maillons, args, _ctx(args, f"version{i}")))
    args = _depot("Neuvième version", document_ref=_ref(maillons, 0), version_precedente=_ref(maillons, 7))
    with pytest.raises(d.RefusDocument, match="BORNE"):
        d.preparer_depot(maillons, args, _ctx(args, "version9"))


def test_retours_independants_et_module_sans_IO():
    maillons, _, ctx = _source()
    first = _d().lire_version(maillons, AFFAIRE, _ref(maillons, 0), _ref(maillons, 0), _lecture_ctx(ctx))
    first["document_ref"]["index"] = 99
    assert (
        _d().lire_version(maillons, AFFAIRE, _ref(maillons, 0), _ref(maillons, 0), _lecture_ctx(ctx))["document_ref"][
            "index"
        ]
        == 0
    )
    tree = ast.parse(Path(_d().__file__).read_text())
    forbidden = {"opsys", "sqlalchemy", "os", "pathlib", "psycopg", "subprocess", "socket"}
    imports = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imports |= {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not imports & forbidden
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {"open", "eval", "exec"}
        for n in ast.walk(tree)
    )


@pytest.mark.parametrize("field", ["role", "source"])
def test_acteur_nested_json_mal_type_refus_ferme(field):
    args = _depot()
    ctx = _ctx(args)
    ctx["auteur"][field] = []
    with pytest.raises(_d().RefusDocument):
        _d().preparer_depot([], args, ctx)


def test_citation_1024_octets_exactement_et_1025_refuse():
    args = _depot("a" * 1025)
    chain = [_d().preparer_depot([], args, _ctx(args))]
    chain, _, ctx = _activer(chain)
    c = _citation(chain, fin=1024)
    assert _d().verifier_citation(chain, c, _lecture_ctx(ctx))["extrait"] == "a" * 1024
    with pytest.raises(_d().RefusDocument):
        _d().verifier_citation(chain, _citation(chain, fin=1025), _lecture_ctx(ctx))


def test_droits_et_scope_affaire_ne_sont_pas_dans_la_commande():
    chain, args, ctx = _source()
    alien = copy.deepcopy(ctx)
    alien["affaire_id"] = "autre-affaire-fictive"
    with pytest.raises(_d().RefusDocument):
        _d().lire_version(chain, AFFAIRE, _ref(chain, 0), _ref(chain, 0), _lecture_ctx(alien))
    # Ceci ne valide qu'une forme pure, jamais une révocation réelle SQL ou token.
    owner = copy.deepcopy(ctx)
    owner["auteur"]["role"] = "nathan_owner"
    with pytest.raises(_d().RefusDocument):
        _d().verifier_rejeu(chain, _claim(chain, 0, ctx), owner)
    args["personne"] = "autorite-usurpee"
    with pytest.raises(_d().RefusDocument):
        _d().preparer_depot([], args, _ctx(args, "usurpee"))


def test_retrait_avant_activation_et_pas_de_reouverture():
    chain, _, ctx = _source()
    args = {
        "affaire_id": AFFAIRE,
        "document_ref": _ref(chain, 0),
        "activation_attendue": None,
        "code_motif": "RETRAIT_ACCES",
    }
    chain += [_d().preparer_retrait(chain, args, _ctx(args, "retirer-deposee", "retirer"))]
    assert "corps" not in _d().lire_version(chain, AFFAIRE, _ref(chain, 0), _ref(chain, 0), _lecture_ctx(ctx))
    new = _depot("version-fictive", document_ref=_ref(chain, 0), version_precedente=_ref(chain, 0))
    with pytest.raises(_d().RefusDocument, match="RETIRE"):
        _d().preparer_depot(chain, new, _ctx(new, "reouverture"))


def _chaine_pleine_fictive():
    # Fixture canonique RAM, pas appels répétés du préparateur O(n) pour construire512.
    from m10_memoire.encodage import empreinte

    chain, _, _ = _source()
    for i in range(1, 512):
        args = {
            "affaire_id": AFFAIRE,
            "document_ref": _ref(chain, 0),
            "version_source": _ref(chain, 0),
            "activation_attendue": _ref(chain, i - 1) if i > 1 else None,
        }
        ctx = _ctx(args, f"activation-fictive-{i}", "activer")
        payload = {
            "version_schema": 1,
            "type_entree": "document_version_activee",
            "affaire_id": AFFAIRE,
            "confidentialite": "INTERNAL",
            "auteur": ctx["auteur"],
            "intention": ctx["intention"],
            "horodatage_appareil_declare": HORA,
            "horodatage": ctx["horodatage"],
            "document_ref": args["document_ref"],
            "version_source": args["version_source"],
            "activation_attendue": args["activation_attendue"],
        }
        prior = chain[-1]["ligne_id"]
        chain.append({**payload, "ligne_id": empreinte(payload, prior), "precedent_ligne_id": prior})
    return chain


def test_corpus512_maillons_et_513_refuse():
    chain = _chaine_pleine_fictive()
    _d().valider_snapshot(chain)
    args = {
        "affaire_id": AFFAIRE,
        "document_ref": _ref(chain, 0),
        "version_source": _ref(chain, 0),
        "activation_attendue": _ref(chain, 511),
    }
    with pytest.raises(_d().RefusDocument, match="BORNE"):
        _d().preparer_activation(chain, args, _ctx(args, "activation513", "activer"))
    with pytest.raises(_d().RefusDocument, match="BORNE"):
        _d().valider_snapshot(chain + [copy.deepcopy(chain[-1])])


def test_snapshot_nonobjet_cycle_et_floats_refuses_sans_runtime():
    d = _d()
    for value in [None, 1, {}, [None], [1], [False]]:
        with pytest.raises(d.RefusDocument):
            d.valider_snapshot(value)
    args = _depot()
    args["corps"] = args
    with pytest.raises(d.RefusDocument):
        d.preparer_depot([], args, _ctx(_depot()))
    for value in [float("nan"), float("inf"), 1.0]:
        with pytest.raises(d.RefusDocument):
            d.borner_enveloppe({"fictif": value}, 6000)


def test_preparateur_mesure_les_deux_flags_avant_candidat():
    chain, args, ctx = _source()
    ack = _d().accuse_propre(chain, _ref(chain, 0))
    false_frame = {"ok": True, "resultat": {"accepte": True, "resultat": ack}, "rejoue": False}
    n = len(json.dumps(false_frame, ensure_ascii=False, allow_nan=False))
    with pytest.raises(_d().RefusDocument, match="QUOTA"):
        _d().preparer_depot([], args, {**ctx, "quota": n - 1})
    assert _d().preparer_depot([], args, {**ctx, "quota": n}) == chain[0]


@pytest.mark.parametrize("field", ["titre", "corps", "confidentialite"])
def test_snapshot_reempreinte_sans_relier_les_arguments_est_refuse(field):
    from m10_memoire.encodage import empreinte

    chain, _, _ = _source()
    if field == "titre":
        chain[0][field] = "Autre titre fictif"
    elif field == "corps":
        chain[0][field] = "Autre corps fictif"
        chain[0]["source_sha256"] = hashlib.sha256(chain[0][field].encode()).hexdigest()
        chain[0]["taille_points"] = len(chain[0][field])
        chain[0]["taille_octets"] = len(chain[0][field].encode())
    else:
        chain[0][field] = "FINANCIAL"
    payload = {k: v for k, v in chain[0].items() if k not in {"ligne_id", "precedent_ligne_id"}}
    chain[0]["ligne_id"] = empreinte(payload, None)
    with pytest.raises(_d().RefusDocument):
        _d().valider_snapshot(chain)


def _lecture_ctx(ctx):
    return {k: copy.deepcopy(ctx[k]) for k in ("affaire_id", "auteur", "situation", "mode", "quota")}


def test_T0_sans_Meta_et_modes_fermes():
    chain, _, ctx = _source()
    for mode in ("ombre", "supervise", "autonome"):
        reading = {**_lecture_ctx(ctx), "mode": mode}
        assert (
            _d().lire_version(chain, AFFAIRE, _ref(chain, 0), _ref(chain, 0), _lecture_ctx(reading))["statut"]
            == "DEPOSEE_NON_ACTIVEE"
        )
    chain, _, _ = _activer(chain)
    c = _citation(chain)
    assert _d().verifier_citation(chain, c, _lecture_ctx(ctx)) == c


@pytest.mark.parametrize("mode", ["supervise", "autonome"])
def test_replay_writer_exige_ombre_courant(mode):
    chain, _, ctx = _source()
    claim = _claim(chain, 0, ctx)
    with pytest.raises(_d().RefusDocument, match="MODE-NON-ADMIS"):
        _d().verifier_rejeu(chain, claim, {**ctx, "mode": mode})


def test_cle_JSON_surrogate_refusee_et_objet_getter_non_execute():
    d = _d()
    with pytest.raises(d.RefusDocument):
        d.borner_enveloppe({"\ud800": "fictif"}, 6000)

    class ObjetInterdit(dict):
        def items(self):
            raise AssertionError("getter interdit exécuté")

    with pytest.raises(d.RefusDocument):
        d.valider_snapshot([ObjetInterdit(fictif=True)])


def test_cible_str_subclass_ne_execute_jamais_eq_ne():
    chain, _, ctx = _source()

    class CibleInterdite(str):
        def __ne__(self, other):
            raise AssertionError("__ne__ arbitraire exécuté")

        def __eq__(self, other):
            raise AssertionError("__eq__ arbitraire exécuté")

    with pytest.raises(_d().RefusDocument):
        _d().lire_version(chain, CibleInterdite(AFFAIRE), _ref(chain, 0), _ref(chain, 0), _lecture_ctx(ctx))


def test_depot_entier_non_serialisable_refuse_sans_exception_json():
    d = _d()
    contexte = _ctx(_depot())
    contexte["intention"]["empreinte_arguments"] = "0" * 64
    arguments = _depot(corps=10**5000)
    with pytest.raises(d.RefusDocument) as erreur:
        d.preparer_depot([], arguments, contexte)
    assert erreur.value.code == "REJ-M10-DOC-FORME-INVALIDE"
    assert type(arguments["corps"]) is int
    assert arguments["corps"] == 10**5000


def test_maillon_entier_non_serialisable_refuse_sans_exception_json():
    d = _d()
    maillons, _, _ = _source()
    maillons[0]["corps"] = 10**5000
    with pytest.raises(d.RefusDocument) as erreur:
        d.valider_snapshot(maillons)
    assert erreur.value.code == "REJ-M10-DOC-FORME-INVALIDE"
    assert maillons[0]["corps"] == 10**5000


def test_rejeu_maillon_entier_non_serialisable_reste_inconnu():
    d = _d()
    maillons, _, contexte = _source()
    claim = _claim(maillons, 0, contexte)
    maillons[0]["corps"] = 10**5000
    with pytest.raises(d.RefusDocument) as erreur:
        d.verifier_rejeu(maillons, claim, contexte)
    assert erreur.value.code == "REJ-M10-DOC-CONFIRMATION-INCONNUE"
    assert maillons[0]["corps"] == 10**5000


@pytest.mark.parametrize("tail", [{}, 5, None, [1]])
@pytest.mark.parametrize("rejeu", [False, True])
def test_reference_avant_vers_tail_malforme_reste_fermee(tail, rejeu):
    d = _d()
    chain, _, ctx0 = _source()
    args = _depot("v2 fictive", document_ref=_ref(chain, 0), version_precedente=_ref(chain, 0))
    ctx = _ctx(args, "version-fictive-2")
    chain.append(d.preparer_depot(chain, args, ctx))
    claim = _claim(chain, 0, ctx0)
    ref_avant = {"registre": "documents_affaire", "index": 2, "ligne_id": "0" * 64}
    chain[1]["version_precedente"] = ref_avant
    altered_args = {**args, "version_precedente": ref_avant}
    chain[1]["intention"]["empreinte_arguments"] = hashlib.sha256(
        json.dumps(altered_args, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    chain.append(copy.deepcopy(tail))
    before = copy.deepcopy(chain)
    with pytest.raises(d.RefusDocument) as erreur:
        if rejeu:
            d.verifier_rejeu(chain, claim, ctx0)
        else:
            d.valider_snapshot(chain)
    suffixe = "CONFIRMATION-INCONNUE" if rejeu else "REFERENCE-INVALIDE"
    assert erreur.value.code == "REJ-M10-DOC-" + suffixe
    assert chain == before


@pytest.mark.parametrize(
    ("debut", "fin", "extrait"),
    [(2, 7, "\ufffd😀"), (1, 6, "é\ufffd"), (-1, 1, "A")],
)
def test_citation_manuelle_octets_malformes_ne_remplace_pas(debut, fin, extrait):
    d = _d()
    args = _depot("Aé😀\r\nZ")
    ctx = _ctx(args)
    chain = [d.preparer_depot([], args, ctx)]
    chain, _, _ = _activer(chain)
    # Vecteur littéral : A=41, é=c3a9, 😀=f09f9880, CRLF=0d0a, Z=5a.
    assert chain[0]["corps"].encode().hex() == "41c3a9f09f98800d0a5a"
    citation = {
        "version_schema": 1,
        "affaire_id": AFFAIRE,
        "document_ref": _ref(chain, 0),
        "version_source": _ref(chain, 0),
        "activation_ref": _ref(chain, 1),
        "source_sha256": chain[0]["source_sha256"],
        "methode": "utf8-exact-v1",
        "debut_octet": debut,
        "fin_octet": fin,
        "extrait": extrait,
    }
    with pytest.raises(d.RefusDocument) as erreur:
        d.verifier_citation(chain, citation, _lecture_ctx(ctx))
    assert erreur.value.code == "REJ-M10-DOC-CITATION-INVALIDE"


def test_paire_connue_avant_cap512_et_rejeu_activation_historique_sans_cas_frais():
    d = _d()
    chain = _chaine_pleine_fictive()
    args = {
        "affaire_id": AFFAIRE,
        "document_ref": _ref(chain, 0),
        "version_source": _ref(chain, 0),
        "activation_attendue": None,
    }
    ctx = _ctx(args, "activation-fictive-1", "activer")
    claim = _claim(chain, 1, ctx)
    before = copy.deepcopy(chain)
    with pytest.raises(d.RefusDocument) as erreur:
        d.preparer_activation(chain, args, ctx)
    assert erreur.value.code == "REJ-M10-DOC-CONFIRMATION-INCONNUE"
    # Le même jeton CAS n'est plus courant, mais sa propre ancienne preuve est confirmable.
    assert d.verifier_rejeu(chain, claim, ctx) == claim["reponse"]["resultat"]["resultat"]
    assert chain == before


def test_premier_maillon_vecteur_litteral_independant_sans_cycle():
    args = _depot("Aé😀\r\nZ")
    actual = _d().preparer_depot([], args, _ctx(args))
    expected = {
        "version_schema": 1,
        "type_entree": "document_depose",
        "affaire_id": "chantier-fictif",
        "confidentialite": "INTERNAL",
        "auteur": {"personne": "admin_fictif", "role": "admin", "source": "appareil"},
        "intention": {
            "appareil": "appareil-fictif",
            "cle": "intention-fictive-1",
            "outil": "m10_deposer_version_document_appareil",
            "empreinte_arguments": "4e8e6f2a8c6abe5a5125f1d54324c629fc3dec86c4389315f023aea04d6c4522",
        },
        "horodatage_appareil_declare": "2026-10-09T14:00:00.000-04:00",
        "horodatage": "2026-10-09T18:00:02+00:00",
        "version_no": 1,
        "titre": "Note fictive",
        "corps": "Aé😀\r\nZ",
        "methode": "utf8-exact-v1",
        "source_sha256": "a0d3b583b739a0bf4ea695be91304364fdd105b274fc110de1b6ab8b5072073e",
        "taille_points": 6,
        "taille_octets": 10,
        "ligne_id": "e5d3a33e38968a83bf23b00efeaaeee8f7724108f33ba8092b3ad452e84450cb",
        "precedent_ligne_id": None,
    }
    assert actual == expected
    assert "document_ref" not in actual
    assert _d().accuse_propre([actual], _ref([actual], 0))["document_ref"] == {
        "registre": "documents_affaire",
        "index": 0,
        "ligne_id": "e5d3a33e38968a83bf23b00efeaaeee8f7724108f33ba8092b3ad452e84450cb",
    }
