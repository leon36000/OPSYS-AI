"""Lecture documentaire SQLite courante, sans effet ni preuve DEVICE autonome."""

from __future__ import annotations

from m10_memoire import affaire
from m10_memoire import documents_affaire as domaine
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from . import approbations, contexte
from .documents_affaire_instance import copier_registre_m10
from .documents_affaire_transactions import ErreurTransactionDocumentaire, _situation
from .stockage import connexion_courante

_DETAILS = {
    "CONNEXION-INVALIDE": "la connexion documentaire courante est indisponible",
    "DIALECTE-NON-ADMIS": "ce lecteur documentaire exige SQLite",
    "AUTORITE-INVALIDE": "l'autorité documentaire courante est inadmissible",
    "MODE-NON-ADMIS": "le mode documentaire courant est inadmissible",
    "FORME-INVALIDE": "la commande de lecture documentaire est inadmissible",
    "AFFAIRE-INCONNUE": "l'affaire documentaire n'est pas connue du corpus autorisé",
    "REGISTRE-INVALIDE": "un registre documentaire ne satisfait pas son contrat",
    "REFERENCE-INVALIDE": "la référence documentaire n'est pas admissible",
    "QUOTA-DEPASSE": "la lecture documentaire dépasse le quota courant",
}


class ErreurLectureDocumentaire(RuntimeError):
    """Refus fermé, sans donnée partielle ni détail SQL ou codec."""

    def __init__(self, suffixe):
        self.code = "REJ-M10-LECTURE-" + suffixe
        self.detail = _DETAILS[suffixe]
        super().__init__(self.code + " : " + self.detail)


def _refuser(suffixe):
    raise ErreurLectureDocumentaire(suffixe) from None


def _commande(operation, commande):
    if type(operation) is not str or operation not in ("lister", "lire"):
        _refuser("FORME-INVALIDE")
    try:
        args = domaine._copie(commande)
        domaine._forme(
            args,
            {"affaire_id", "decalage", "limite"} if operation == "lister"
            else {"affaire_id", "document_ref", "version_source"},
        )
        if type(args["affaire_id"]) is not str or not affaire.valide(args["affaire_id"]):
            _refuser("FORME-INVALIDE")
        if operation == "lister":
            domaine._entier(args["decalage"], 0, 64)
            domaine._entier(args["limite"], 1, 8)
        else:
            domaine._reference_forme(args["document_ref"])
            domaine._reference_forme(args["version_source"])
    except domaine.RefusDocument:
        _refuser("FORME-INVALIDE")
    return args


def _connexion(cnx):
    if type(cnx) is not Connection or cnx is not connexion_courante() or cnx.closed or not cnx.in_transaction():
        _refuser("CONNEXION-INVALIDE")
    if cnx.engine.dialect.name != "sqlite":
        _refuser("DIALECTE-NON-ADMIS")


def _admission(cnx, mode_manifeste):
    actor = contexte.identite_appelante()
    if (
        type(actor) is not contexte.IdentiteAppelante
        or type(actor.personne) is not str
        or type(actor.role) is not str
        or type(actor.source) is not str
        or actor.role != "admin"
        or actor.source != "appareil"
    ):
        _refuser("AUTORITE-INVALIDE")
    signataire = approbations.signataire_valide(cnx, actor)
    if signataire is None or signataire.role != "admin":
        _refuser("AUTORITE-INVALIDE")
    if type(mode_manifeste) is not str or mode_manifeste not in ("ombre", "supervise", "autonome"):
        _refuser("MODE-NON-ADMIS")
    mode = approbations.mode_effectif(cnx, "m10-memoire", mode_manifeste)
    if type(mode) is not str or mode not in ("ombre", "supervise", "autonome"):
        _refuser("MODE-NON-ADMIS")
    return signataire, mode


def lire_document_m10(cnx, operation, commande, *, quota, mode_manifeste):
    """Rend une enveloppe entière T0 sans Meta, rejeu ou transaction de repli.

    L'appelant possède la transaction canonique. L'identité injectée est confirmée
    en SQL avant le corpus ; la portée/authenticité DEVICE reste à son adaptateur.
    """
    _connexion(cnx)
    args = _commande(operation, commande)
    if type(quota) is not int or quota < 1:
        _refuser("FORME-INVALIDE")
    try:
        actor, mode = _admission(cnx, mode_manifeste)
        situation = _situation(cnx, args["affaire_id"])
        documents = [row.maillon for row in copier_registre_m10(cnx, "documents_affaire").lignes]
        ctx = {
            "affaire_id": args["affaire_id"],
            "auteur": {"personne": actor.personne, "role": actor.role, "source": actor.source},
            "situation": situation,
            "mode": mode,
            "quota": quota,
        }
        dto = (
            domaine.lister_versions_documentaires(documents, args, ctx)
            if operation == "lister"
            else domaine.lire_version(documents, args["affaire_id"], args["document_ref"], args["version_source"], ctx)
        )
        frame = {"ok": True, "resultat": {"accepte": True, "resultat": dto}}
        domaine.borner_enveloppe(frame, quota)
        return frame
    except ErreurLectureDocumentaire:
        raise
    except ErreurTransactionDocumentaire as exc:
        _refuser("AFFAIRE-INCONNUE" if exc.code == "REJ-M10-TRANSACTION-AFFAIRE-INCONNUE" else "REGISTRE-INVALIDE")
    except domaine.RefusDocument as exc:
        suffixe = {
            "REJ-M10-DOC-QUOTA-DEPASSE": "QUOTA-DEPASSE",
            "REJ-M10-DOC-REFERENCE-INVALIDE": "REFERENCE-INVALIDE",
        }.get(exc.code, "REGISTRE-INVALIDE")
        _refuser(suffixe)
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError, SQLAlchemyError):
        _refuser("REGISTRE-INVALIDE")
