"""Writer documentaire interne SQLite : aucun RPC ni preuve DEVICE cryptographique.

L'appelant fournit la connexion canonique et le SAVEPOINT. Toute erreur doit en
sortir ; aucun refus négatif n'est finalisé et aucun fallback générique exécuté.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from m10_memoire import amont, confidentialite, encodage, humain
from m10_memoire import documents_affaire as domaine
from m10_memoire import recherche_affaire as corpus
from sqlalchemy import Connection, LargeBinary, and_, case, cast, func, insert, select
from sqlalchemy.exc import IntegrityError

from . import approbations, contexte, idempotence
from .documents_affaire_instance import copier_registre_m10
from .outils import Niveau
from .stockage import codec, connexion_courante, maillons
from .stockage.schema import APPROBATIONS, JOURNAL, MUTATIONS_APPLIQUEES

_DEP = "m10-memoire"
_DOC = "documents_affaire"
_LIENS = "documents_affaire_traces"
_HASH = re.compile(r"[0-9a-f]{64}")
_LINK = {
    "version_schema",
    "type_entree",
    "operation",
    "affaire_id",
    "document_ref",
    "mutation_ref",
    "auteur",
    "intention",
    "horodatage_appareil_declare",
    "horodatage",
    "trace",
}
_TRACE = {"approbation_id", "journal_id", "cree_le_approbation", "decide_le_approbation", "quand_journal"}
_DETAILS = {
    "CONNEXION-INVALIDE": "la transaction documentaire est indisponible",
    "DIALECTE-NON-ADMIS": "ce pilote documentaire exige SQLite",
    "AUTORITE-INVALIDE": "l'autorité documentaire courante est inadmissible",
    "MODE-NON-ADMIS": "le mode courant ne permet pas cette mutation documentaire",
    "FORME-INVALIDE": "la commande documentaire est inadmissible",
    "AFFAIRE-INCONNUE": "l'affaire documentaire n'est pas connue du corpus autorisé",
    "REGISTRE-INVALIDE": "un registre documentaire ne satisfait pas son contrat",
    "QUOTA-DEPASSE": "la confirmation documentaire dépasse le quota courant",
    "PRECONDITION-REFUSEE": "une précondition documentaire fraîche est refusée",
    "CONFIRMATION-INCONNUE": "la mutation documentaire ne peut pas être confirmée",
    "PANNE-TRANSACTION": "la transaction documentaire ne peut pas être achevée",
}


class ErreurTransactionDocumentaire(RuntimeError):
    """Signal constant à traduire hors du SAVEPOINT, jamais preuve d'absence d'effet."""

    def __init__(self, suffixe):
        self.code = "REJ-M10-TRANSACTION-" + suffixe
        self.detail = _DETAILS[suffixe]
        self.issue = "inconnue"
        super().__init__(self.code + " : " + self.detail)


def _refuser(suffixe):
    raise ErreurTransactionDocumentaire(suffixe) from None


def _connexion(cnx):
    if (
        not isinstance(cnx, Connection)
        or cnx is not connexion_courante()
        or cnx.closed
        or not cnx.in_transaction()
        or cnx.get_nested_transaction() is None
    ):
        _refuser("CONNEXION-INVALIDE")
    if cnx.engine.dialect.name != "sqlite":
        _refuser("DIALECTE-NON-ADMIS")


def _admission(cnx, mode_manifeste):
    actor = contexte.identite_appelante()
    if (
        type(actor) is not contexte.IdentiteAppelante
        or type(actor.role) is not str
        or type(actor.source) is not str
        or type(actor.personne) is not str
        or actor.role != "admin"
        or actor.source != "appareil"
    ):
        _refuser("AUTORITE-INVALIDE")
    confirmee = approbations.signataire_valide(cnx, actor)
    if confirmee is None or confirmee.role != "admin":
        _refuser("AUTORITE-INVALIDE")
    if type(mode_manifeste) is not str or mode_manifeste not in ("ombre", "supervise", "autonome"):
        _refuser("MODE-NON-ADMIS")
    if approbations.mode_effectif(cnx, _DEP, mode_manifeste) != "ombre":
        _refuser("MODE-NON-ADMIS")
    return confirmee


def _meta(meta):
    if type(meta) is not idempotence.Meta:
        _refuser("FORME-INVALIDE")
    for val in (meta.appareil, meta.cle):
        if type(val) is not str or not val.strip() or len(val) > 128:
            _refuser("FORME-INVALIDE")
        val.encode("utf-8", "strict")
    if (
        type(meta.horodatage_appareil) is not str
        or len(meta.horodatage_appareil) > 40
        or not humain.horodatage_valide(meta.horodatage_appareil)
    ):
        _refuser("FORME-INVALIDE")


def _copies(cnx, registre):
    return [row.maillon for row in copier_registre_m10(cnx, registre).lignes]


def _situation(cnx, affaire_id):
    evenements, affaires = _copies(cnx, "evenements"), _copies(cnx, "affaires")
    corpus._valider_snapshot(evenements)
    corpus._valider_snapshot(affaires)
    visibles = [m for m in evenements if corpus._dans_corpus(m) and confidentialite.niveau_de(m) in corpus._NIVEAUX]
    for m in visibles:
        corpus._valider_evenement(m)
    consolides = corpus._consolidations_admises(
        affaire_id,
        corpus._dernieres_consolidations(affaire_id, affaires),
        evenements,
        visibles,
    )
    situation = amont.situation(affaire_id, visibles)
    if consolides and not situation["connue"]:
        situation.update(connue=True, verdict=amont.AMONT_ORIGINE_NON_RECUE)
    if not situation["connue"]:
        _refuser("AFFAIRE-INCONNUE")
    return situation


def _egal(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(_egal(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(_egal(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _json(texte):
    if type(texte) is not str:
        raise ValueError("json")

    def pairs(items):
        resultat = {}
        for k, v in items:
            if k in resultat:
                raise ValueError("json")
            resultat[k] = v
        return resultat

    def constante(v):
        raise ValueError("json")

    return json.loads(texte, object_pairs_hook=pairs, parse_constant=constante)


def _lire_borne(cnx, table, filtre, textes, *, nuls=(), entiers=()):
    """CASE masque tous les champs avant retour si un seul budget/type est invalide.

    Ce contrôle borne la réception Python, pas le travail du planner SQLite.
    """
    conditions = [
        and_(func.typeof(table.c[k]) == "text", func.length(cast(table.c[k], LargeBinary)) <= cap)
        for k, cap in textes.items()
    ]
    conditions += [table.c[k].is_(None) for k in nuls]
    conditions += [and_(func.typeof(table.c[k]) == "integer", table.c[k] > 0, table.c[k] <= 2**63 - 1) for k in entiers]
    admissible = and_(*conditions)
    fields = tuple(textes) + tuple(nuls) + tuple(entiers)
    return (
        cnx.execute(
            select(
                admissible.label("raw_admis"), *(case((admissible, table.c[k]), else_=None).label(k) for k in fields)
            ).where(filtre)
        )
        .mappings()
        .one_or_none()
    )


def _claim(cnx, meta):
    return _lire_borne(
        cnx,
        MUTATIONS_APPLIQUEES,
        and_(MUTATIONS_APPLIQUEES.c.appareil == meta.appareil, MUTATIONS_APPLIQUEES.c.cle_idempotence == meta.cle),
        {
            "appareil": 512,
            "cle_idempotence": 512,
            "outil": 512,
            "empreinte_arguments": 64,
            "horodatage_appareil": 160,
            "recu_le": 160,
            "statut": 96,
            "reponse": 8192,
        },
    )


def _claim_projection(row, ctx):
    if row["raw_admis"] is not True:
        raise ValueError("claim")
    attendu = {
        "appareil": ctx["intention"]["appareil"],
        "cle_idempotence": ctx["intention"]["cle"],
        "outil": ctx["intention"]["outil"],
        "empreinte_arguments": ctx["intention"]["empreinte_arguments"],
        "horodatage_appareil": ctx["horodatage_appareil_declare"],
        "statut": "ok",
    }
    if any(not _egal(row[k], v) for k, v in attendu.items()):
        raise ValueError("claim")
    _hora(row["recu_le"])
    # Le codec canonique reste réutilisé, après refus des ambiguïtés JSON natives.
    _json(row["reponse"])
    return {
        "appareil": row["appareil"],
        "cle": row["cle_idempotence"],
        "outil": row["outil"],
        "empreinte_arguments": row["empreinte_arguments"],
        "horodatage_appareil": row["horodatage_appareil"],
        "statut": row["statut"],
        "reponse": codec.decoder(row["reponse"]),
    }


def _reclamer_claim(cnx, meta, nom_outil, arguments, recu_le):
    """INSERT identique au Socle ; aucune réponse existante n'est décodée ici."""
    empreinte = idempotence.empreinte_arguments(arguments)
    try:
        with cnx.begin_nested():
            cnx.execute(
                insert(MUTATIONS_APPLIQUEES).values(
                    appareil=meta.appareil,
                    cle_idempotence=meta.cle,
                    outil=nom_outil,
                    empreinte_arguments=empreinte,
                    reponse=codec.encoder(None),
                    horodatage_appareil=meta.horodatage_appareil,
                    recu_le=recu_le.isoformat(timespec="seconds"),
                    statut="en_cours",
                )
            )
    except IntegrityError:
        # Le sous-SAVEPOINT d'acquisition est sorti ; relire toute preuve OWN.
        return idempotence.Reclamation(rejouee=True)
    return idempotence.Reclamation(rejouee=False)


def _ref(m, index):
    return {"registre": _DOC, "index": index, "ligne_id": m["ligne_id"]}


def _hora(val):
    if type(val) is not str or len(val) > 40 or not humain.horodatage_valide(val):
        raise ValueError("hora")


def _valider_liaisons(liens, documents):
    precedent = None
    mutations = set()
    pairs = set()
    captures = set()
    apps = set()
    journals = set()
    for m in liens:
        if type(m) is not dict or set(m) != _LINK | {"ligne_id", "precedent_ligne_id"}:
            raise ValueError("liaison")
        payload = {k: v for k, v in m.items() if k not in ("ligne_id", "precedent_ligne_id")}
        if (
            type(m["version_schema"]) is not int
            or m["version_schema"] != 1
            or m["type_entree"] != "document_trace_liee"
        ):
            raise ValueError("liaison")
        if m["operation"] not in domaine.OUTILS or m["precedent_ligne_id"] != precedent:
            raise ValueError("liaison")
        if (
            type(m["ligne_id"]) is not str
            or _HASH.fullmatch(m["ligne_id"]) is None
            or encodage.empreinte(payload, precedent) != m["ligne_id"]
        ):
            raise ValueError("liaison")
        ack = domaine.accuse_propre(documents, m["mutation_ref"])
        source = documents[m["mutation_ref"]["index"]]
        for k in ("operation", "document_ref", "auteur", "intention", "horodatage_appareil_declare", "horodatage"):
            if not _egal(ack[k], m[k]):
                raise ValueError("liaison")
        if not _egal(m["affaire_id"], source["affaire_id"]):
            raise ValueError("liaison")
        pair = (m["intention"]["appareil"], m["intention"]["cle"])
        mutation = (m["mutation_ref"]["index"], m["mutation_ref"]["ligne_id"])
        trace = m["trace"]
        if type(trace) is not dict or set(trace) != _TRACE:
            raise ValueError("trace")
        if (
            type(trace["approbation_id"]) is not str
            or len(trace["approbation_id"]) != 12
            or type(trace["journal_id"]) is not int
            or not 0 < trace["journal_id"] <= 2**63 - 1
        ):
            raise ValueError("trace")
        for k in ("cree_le_approbation", "decide_le_approbation", "quand_journal"):
            _hora(trace[k])
        capture = (trace["approbation_id"], trace["journal_id"])
        if (
            pair in pairs
            or mutation in mutations
            or capture in captures
            or trace["approbation_id"] in apps
            or trace["journal_id"] in journals
        ):
            raise ValueError("doublon")
        pairs.add(pair)
        mutations.add(mutation)
        captures.add(capture)
        apps.add(trace["approbation_id"])
        journals.add(trace["journal_id"])
        precedent = m["ligne_id"]


def _trace_raw(cnx, trace, ctx, operation, args):
    ident, jid = trace["approbation_id"], trace["journal_id"]
    if type(ident) is not str or len(ident) != 12 or type(jid) is not int or not 0 < jid <= 2**63 - 1:
        raise ValueError("pk")
    app = _lire_borne(
        cnx,
        APPROBATIONS,
        APPROBATIONS.c.id == ident,
        {
            "id": 48,
            "departement": 256,
            "outil": 512,
            "niveau": 16,
            "statut": 64,
            "decide_par": 256,
            "decide_role": 128,
            "motif_decision": 512,
            "motif_demande": 512,
            "arguments": 16384,
            "resultat": 512,
            "cree_le": 160,
            "decide_le": 160,
        },
        nuls=("attestation", "ticket_cible_hash"),
    )
    journal = _lire_borne(
        cnx,
        JOURNAL,
        JOURNAL.c.id == jid,
        {"quand": 160, "par": 256, "action": 512, "cible": 48, "details": 4096},
        entiers=("id",),
    )
    if app is None or journal is None or app["raw_admis"] is not True or journal["raw_admis"] is not True:
        raise ValueError("trace")
    attendu = {
        "id": ident,
        "departement": _DEP,
        "outil": domaine.OUTILS[operation],
        "niveau": "N3",
        "statut": "executee",
        "decide_par": ctx["auteur"]["personne"],
        "decide_role": "admin",
        "motif_decision": approbations.MOTIF_VALIDATION_AU_DEPART,
        "motif_demande": "",
    }
    if any(not _egal(app[k], v) for k, v in attendu.items()):
        raise ValueError("app")
    if not _egal(domaine.valider_commande(operation, _json(app["arguments"])), args) or not _egal(
        _json(app["resultat"]), {"ok": True, "accepte": True}
    ):
        raise ValueError("app")
    if app["attestation"] is not None or app["ticket_cible_hash"] is not None:
        raise ValueError("app")
    if (
        not _egal(journal["par"], ctx["auteur"]["personne"])
        or journal["action"] != approbations.ACTION_VALIDATION_AU_DEPART
        or journal["cible"] != ident
    ):
        raise ValueError("j")
    details = {
        "outil": domaine.OUTILS[operation],
        "departement": _DEP,
        "niveau": "N3",
        "role": "admin",
        "appareil": ctx["intention"]["appareil"],
        "motif": approbations.MOTIF_VALIDATION_AU_DEPART,
        "empreinte_arguments": ctx["intention"]["empreinte_arguments"],
    }
    if not _egal(_json(journal["details"]), details):
        raise ValueError("j")
    times = {
        "approbation_id": ident,
        "journal_id": jid,
        "cree_le_approbation": app["cree_le"],
        "decide_le_approbation": app["decide_le"],
        "quand_journal": journal["quand"],
    }
    for k in ("cree_le_approbation", "decide_le_approbation", "quand_journal"):
        _hora(times[k])
    return times


def _borner_frames(response, quota):
    try:
        for flag in (False, True):
            domaine.borner_enveloppe({**response, "rejoue": flag}, quota)
    except domaine.RefusDocument:
        _refuser("QUOTA-DEPASSE")


def _confirmer_own(cnx, operation, args, meta, ctx):
    try:
        row = _claim(cnx, meta)
        if row is None:
            raise ValueError("claim")
        claim = _claim_projection(row, ctx)
        docs, liens = _copies(cnx, _DOC), _copies(cnx, _LIENS)
        domaine.valider_snapshot(docs)
        _valider_liaisons(liens, docs)
        ack = domaine.verifier_rejeu(docs, claim, ctx)
        owns = [
            m
            for m in liens
            if _egal(m["intention"], ctx["intention"])
            and _egal(m["auteur"], ctx["auteur"])
            and m["affaire_id"] == ctx["affaire_id"]
            and m["horodatage_appareil_declare"] == meta.horodatage_appareil
        ]
        if len(owns) != 1 or not _egal(owns[0]["mutation_ref"], ack["reference"]):
            raise ValueError("own")
        times = _trace_raw(cnx, owns[0]["trace"], ctx, operation, args)
        if not _egal(times, owns[0]["trace"]):
            raise ValueError("hora")
        if not _egal(row["recu_le"], ack["horodatage"]):
            raise ValueError("claim")
        response = {"ok": True, "resultat": {"accepte": True, "resultat": ack}}
        _borner_frames(response, ctx["quota"])
        return response
    except ErreurTransactionDocumentaire:
        raise
    except Exception:
        _refuser("CONFIRMATION-INCONNUE")


def _ajouter_document(cnx, candidat, rang):
    _connexion(cnx)
    maillons(_DEP, _DOC).append(candidat, rang_attendu=rang)


def _ajouter_liaison(cnx, candidat, rang):
    _connexion(cnx)
    maillons(_DEP, _LIENS).append(candidat, rang_attendu=rang)


def muter_document_m10(cnx, operation, commande, *, meta, quota, mode_manifeste):
    """Frame positive avec rejoue ; toutes erreurs sortent du SAVEPOINT fourni."""
    try:
        if type(quota) is not int or quota < 40:
            _refuser("QUOTA-DEPASSE")
        _connexion(cnx)
        actor = _admission(cnx, mode_manifeste)
        _meta(meta)
        try:
            args = domaine.valider_commande(operation, commande)
        except domaine.RefusDocument:
            _refuser("FORME-INVALIDE")
        situation = _situation(cnx, args["affaire_id"])
        reception = dt.datetime.now(dt.UTC)
        ctx = {
            "affaire_id": args["affaire_id"],
            "auteur": {"personne": actor.personne, "role": "admin", "source": "appareil"},
            "intention": {
                "appareil": meta.appareil,
                "cle": meta.cle,
                "outil": domaine.OUTILS[operation],
                "empreinte_arguments": idempotence.empreinte_arguments(args),
            },
            "horodatage_appareil_declare": meta.horodatage_appareil,
            "horodatage": reception.isoformat(timespec="seconds"),
            "situation": situation,
            "mode": "ombre",
            "quota": quota,
        }
        if _claim(cnx, meta) is not None:
            return {**_confirmer_own(cnx, operation, args, meta, ctx), "rejoue": True}
        docs, liens = _copies(cnx, _DOC), _copies(cnx, _LIENS)
        domaine.valider_snapshot(docs)
        _valider_liaisons(liens, docs)
        try:
            preparateur = {
                "deposer": domaine.preparer_depot,
                "activer": domaine.preparer_activation,
                "retirer": domaine.preparer_retrait,
            }[operation]
            candidat = preparateur(docs, args, ctx)
        except domaine.RefusDocument as exc:
            _refuser(
                "CONFIRMATION-INCONNUE"
                if exc.code.endswith("CONFIRMATION-INCONNUE")
                else "QUOTA-DEPASSE"
                if exc.code.endswith("QUOTA-DEPASSE")
                else "PRECONDITION-REFUSEE"
            )
        reference = _ref(candidat, len(docs))
        ack = domaine.accuse_propre(docs + [candidat], reference)
        response = {"ok": True, "resultat": {"accepte": True, "resultat": ack}}
        _borner_frames(response, quota)
        try:
            reclamation = _reclamer_claim(cnx, meta, domaine.OUTILS[operation], args, reception)
        except Exception:
            _refuser("CONFIRMATION-INCONNUE")
        if reclamation.rejouee:
            # Discard any fresh plan; only the durable proper row is evidence.
            return {**_confirmer_own(cnx, operation, args, meta, ctx), "rejoue": True}
        if not _egal(_admission(cnx, mode_manifeste), actor):
            _refuser("AUTORITE-INVALIDE")
        _ajouter_document(cnx, candidat, len(docs))
        persisted = _copies(cnx, _DOC)
        domaine.valider_snapshot(persisted)
        if not _egal(domaine.accuse_propre(persisted, reference), ack):
            raise ValueError("projection")
        capture = approbations.tracer_validation_documentaire_m10(
            cnx,
            _DEP,
            domaine.OUTILS[operation],
            args,
            niveau=Niveau.N3,
            signataire=actor,
            reponse=response,
            appareil=meta.appareil,
        )
        ident = {"approbation_id": capture.approbation_id, "journal_id": capture.journal_id}
        trace = _trace_raw(cnx, ident, ctx, operation, args)
        payload = {
            "version_schema": 1,
            "type_entree": "document_trace_liee",
            "operation": operation,
            "affaire_id": args["affaire_id"],
            "document_ref": ack["document_ref"],
            "mutation_ref": reference,
            "auteur": ctx["auteur"],
            "intention": ctx["intention"],
            "horodatage_appareil_declare": meta.horodatage_appareil,
            "horodatage": ctx["horodatage"],
            "trace": trace,
        }
        precedent = liens[-1]["ligne_id"] if liens else None
        lien = {**payload, "ligne_id": encodage.empreinte(payload, precedent), "precedent_ligne_id": precedent}
        _valider_liaisons(liens + [lien], persisted)
        _ajouter_liaison(cnx, lien, len(liens))
        _borner_frames(response, quota)
        if not _egal(_admission(cnx, mode_manifeste), actor):
            _refuser("AUTORITE-INVALIDE")
        idempotence.finaliser(cnx, meta, response)
        if not _egal(_confirmer_own(cnx, operation, args, meta, ctx), response):
            raise ValueError("finalisation")
        return {**response, "rejoue": False}
    except ErreurTransactionDocumentaire:
        raise
    except Exception:
        _refuser("PANNE-TRANSACTION")
