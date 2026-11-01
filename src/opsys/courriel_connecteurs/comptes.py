"""Comptes courriel : état de connexion, consentement (Loi 25), dernier synchro, erreurs typées, journal append-only.

La base ne contient JAMAIS un jeton, un mot de passe ni un contenu de courriel : un compte porte le NOM de son secret
dans le coffre, ses portées accordées, ses curseurs (opaques, par dossier), ses compteurs et le dernier CODE d'erreur
typé. Le journal (`courriel_journal`, append-only par déclencheurs) n'accepte que des détails de la liste blanche
`DETAILS_PERMIS`, avec des valeurs scalaires courtes : un contenu de courriel ou un secret ne peut pas y entrer, même
par erreur de programmation.

Loi 25 : un compte ne se connecte pas sans consentement enregistré (`consentement_le` : qui l'a consigné, pour quelle
finalité) ; la rétention est une durée déclarée en jours (1 à 3650) que la purge devra appliquer — la purge elle-même
n'est pas faite ici (voir la documentation).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import IntegrityError

from .. import identite
from ..secrets_coffre import coffre, masquage
from ..stockage.schema import COURRIEL_COMPTES, COURRIEL_JOURNAL
from .erreurs import ErreurCourriel

FOURNISSEURS = ("gmail", "graph", "imap", "mbox")
ETATS = ("non_connecte", "autorisation_en_cours", "connecte", "reconnexion_requise", "revoque", "erreur")
DETAILS_PERMIS = frozenset({
    "dossier", "lot_id", "messages", "ajouts", "suppressions", "doublons", "pieces", "pieces_transmises", "refuses",
    "attente_s", "revision", "brouillon_id", "empreinte", "demande_id", "fournisseur", "usage", "etat",
    "rotation_refresh",
    "nb_portees", "page", "statut", "termine", "ignores", "generation", "reprise", "recus_m1", "contacts", "bail",
})
_COMPTE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ADRESSE = re.compile(r"^[A-Za-z0-9._%+'=!#$&*/?^`{|}~-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
_CLES_CONFIG = frozenset({"hote", "port", "smtp_hote", "smtp_port", "utilisateur", "tenant", "client_id", "fichier",
                          "reception_m1", "contacts_courriel"})
# Options 0/1 d'un compte (voir CABLAGE-CONNECTEURS.md) : fermées par défaut, déclarées à la création avec la finalité.
#  - reception_m1 : après l'amorçage, les nouveaux courriels de la boîte deviennent des réceptions de M1 ;
#  - contacts_courriel : pendant l'amorçage (historique), les correspondants deviennent des brouillons «
# courriel_contact ».
OPTIONS_BINAIRES = ("reception_m1", "contacts_courriel")
# Préfixe d'une clé de `curseurs` : jamais un nom de dossier (les caractères de contrôle sont refusés).
CLE_AMORCE = "\x1famorce\x1f"


def instant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def exiger_admin(cnx: Connection, acteur: Any) -> str:
    personne = identite.personne_active(cnx, acteur) if isinstance(acteur, str) else None
    if personne is None or not personne.roles.intersection(coffre.ROLES_ADMIN):
        raise ErreurCourriel("REJ-COURRIEL-ADMIN-REQUIS", "administrateur actif requis", 403)
    return acteur


def journaliser(cnx: Connection, compte_id: str, evenement: str, acteur: str, *, code: str | None = None,
                details: Mapping[str, Any] | None = None) -> None:
    details = dict(details or {})
    for cle, valeur in details.items():
        if cle not in DETAILS_PERMIS or not (valeur is None or isinstance(valeur, (bool, int))
                                             or (isinstance(valeur, str) and len(valeur) <= 64)):
            raise ValueError(f"détail de journal courriel non permis : {cle!r}")
    cnx.execute(insert(COURRIEL_JOURNAL).values(
        quand=instant(), compte_id=compte_id[:64], evenement=evenement[:48], code=code, acteur=str(acteur)[:200],
        details=masquage.masquer_texte(json.dumps(details, sort_keys=True, ensure_ascii=False))))


def _ligne(cnx: Connection, compte_id: str) -> Mapping[str, Any]:
    ligne = cnx.execute(select(COURRIEL_COMPTES).where(COURRIEL_COMPTES.c.compte_id == compte_id)).mappings().first()
    if ligne is None:
        raise ErreurCourriel("REJ-COURRIEL-COMPTE-INCONNU", "compte courriel inconnu", 404)
    return ligne


def vue(ligne: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que l'administration voit : état, dernier synchro, dernière erreur typée, jamais un secret."""
    return {
        "compte_id": ligne["compte_id"], "fournisseur": ligne["fournisseur"], "adresse": ligne["adresse"],
        "etat": ligne["etat"], "usage": ligne["usage"], "portees": json.loads(ligne["portees"]),
        "dossiers_suivis": json.loads(ligne["dossiers_suivis"]), "finalite": ligne["finalite"],
        "retention_jours": ligne["retention_jours"], "consentement_le": ligne["consentement_le"],
        "consentement_par": ligne["consentement_par"], "derniere_synchro_le": ligne["derniere_synchro_le"],
        "derniere_synchro_statut": ligne["derniere_synchro_statut"],
        "derniere_erreur_code": ligne["derniere_erreur_code"], "derniere_erreur_le": ligne["derniere_erreur_le"],
        "messages_total": ligne["messages_total"], "revision": ligne["revision"],
        "secret_nom": ligne["secret_nom"], "generation": ligne["generation"],
    }


def lire(cnx: Connection, compte_id: str) -> dict[str, Any]:
    return vue(_ligne(cnx, compte_id))


def lister(cnx: Connection) -> list[dict[str, Any]]:
    requete = select(COURRIEL_COMPTES).order_by(COURRIEL_COMPTES.c.compte_id)
    return [vue(ligne) for ligne in cnx.execute(requete).mappings()]


def ligne_brute(cnx: Connection, compte_id: str) -> Mapping[str, Any]:
    return _ligne(cnx, compte_id)


def creer_compte(cnx: Connection, acteur: str, *, compte_id: str, fournisseur: str, adresse: str, usage: str,
                 finalite: str, retention_jours: int, configuration: Mapping[str, Any] | None = None,
                 dossiers_suivis: tuple[str, ...] = ("INBOX",)) -> dict[str, Any]:
    exiger_admin(cnx, acteur)
    if not isinstance(compte_id, str) or not _COMPTE.fullmatch(compte_id):
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE",
                             "compte_id : minuscules, chiffres, _ et - (64 au plus)", 422)
    if fournisseur not in FOURNISSEURS:
        raise ErreurCourriel("REJ-COURRIEL-FOURNISSEUR-INCONNU", f"fournisseur parmi : {', '.join(FOURNISSEURS)}", 422)
    if not isinstance(adresse, str) or not _ADRESSE.fullmatch(adresse):
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "adresse du compte invalide", 422)
    if usage not in {"lecture", "lecture_envoi"}:
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "usage : lecture ou lecture_envoi", 422)
    if not isinstance(finalite, str) or not finalite.strip() or len(finalite) > 500:
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "finalité requise (500 caractères au plus)", 422)
    if type(retention_jours) is not int or not 1 <= retention_jours <= 3650:
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "rétention : 1 à 3650 jours", 422)
    configuration = dict(configuration or {})
    if any(configuration.get(o) not in (None, 0, 1) or isinstance(configuration.get(o), bool)
           for o in OPTIONS_BINAIRES):
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", f"options {OPTIONS_BINAIRES} : 0 ou 1", 422)
    if set(configuration) - _CLES_CONFIG or any(not isinstance(v, (str, int)) for v in configuration.values()):
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE",
                             f"configuration : clés permises {sorted(_CLES_CONFIG)} (jamais un secret)", 422)
    if (not dossiers_suivis or len(dossiers_suivis) > 50
            or any(not isinstance(d, str) or not d or len(d) > 255 or re.search(r"[\x00-\x1f]",
                                                                                d) for d in dossiers_suivis)):
        raise ErreurCourriel("REJ-COURRIEL-ARGUMENT-INVALIDE", "dossiers suivis invalides", 422)
    maintenant = instant()
    try:
        cnx.execute(insert(COURRIEL_COMPTES).values(
            compte_id=compte_id, fournisseur=fournisseur, adresse=adresse, etat="non_connecte", usage=usage,
            secret_nom=None, generation=0, portees="[]",
            configuration=json.dumps(configuration, sort_keys=True), finalite=finalite.strip(),
            retention_jours=retention_jours, consentement_le=None, consentement_par=None,
            dossiers_suivis=json.dumps(list(dossiers_suivis)), curseurs="{}", messages_total=0, cree_le=maintenant,
            modifie_le=maintenant, revision=1))
    except IntegrityError:
        raise ErreurCourriel("REJ-COURRIEL-COMPTE-EXISTE", "ce compte existe déjà", 409) from None
    journaliser(cnx, compte_id, "compte.cree", acteur, details={"fournisseur": fournisseur, "usage": usage})
    return lire(cnx, compte_id)


def configuration(cnx: Connection, compte_id: str) -> dict[str, Any]:
    return json.loads(_ligne(cnx, compte_id)["configuration"])


def option(ligne_compte: Mapping[str, Any], nom: str) -> bool:
    """Vrai si l'option binaire `nom` du compte vaut 1 (absente : fermée)."""
    if nom not in OPTIONS_BINAIRES:
        raise ValueError(f"option inconnue : {nom!r}")
    return json.loads(ligne_compte["configuration"]).get(nom) == 1


def amorce_terminee(curseurs_du_compte: Mapping[str, str], dossier: str) -> bool:
    """Le dossier a fini son amorçage (l'historique est lu) : ses nouveaux messages sont de l'ENTRANT."""
    return curseurs_du_compte.get(CLE_AMORCE + dossier) == "1"


def enregistrer_consentement(cnx: Connection, acteur: str, compte_id: str) -> dict[str, Any]:
    """Consigne le consentement du titulaire de la boîte pour la finalité DÉCLARÉE du compte (Loi 25). Sans lui, aucune
    autorisation OAuth ni aucun mot de passe d'application n'est accepté."""
    exiger_admin(cnx, acteur)
    ligne = _ligne(cnx, compte_id)
    if ligne["etat"] == "revoque":
        raise ErreurCourriel("REJ-COURRIEL-COMPTE-INACTIF", "compte révoqué", 409)
    cnx.execute(update(COURRIEL_COMPTES).where(COURRIEL_COMPTES.c.compte_id == compte_id).values(
        consentement_le=instant(), consentement_par=acteur, modifie_le=instant(), revision=ligne["revision"] + 1))
    journaliser(cnx, compte_id, "compte.consentement", acteur)
    return lire(cnx, compte_id)


def exiger_consentement(ligne: Mapping[str, Any]) -> None:
    if not ligne["consentement_le"]:
        raise ErreurCourriel("REJ-COURRIEL-CONSENTEMENT-ABSENT",
                             "consentement du titulaire de la boîte non consigné (Loi 25) : l'enregistrer d'abord", 403)


def changer_etat(cnx: Connection, compte_id: str, etat: str, acteur: str, *, code: str | None = None,
                 evenement: str = "compte.etat", **valeurs: Any) -> None:
    if etat not in ETATS:
        raise ValueError(f"état de compte inconnu : {etat!r}")
    ligne = _ligne(cnx, compte_id)
    if ligne["etat"] == "revoque" and etat != "revoque":
        raise ErreurCourriel("REJ-COURRIEL-COMPTE-INACTIF", "compte révoqué : créer un nouveau compte", 409)
    cnx.execute(update(COURRIEL_COMPTES).where(COURRIEL_COMPTES.c.compte_id == compte_id).values(
        etat=etat, modifie_le=instant(), revision=ligne["revision"] + 1,
        **({"derniere_erreur_code": code, "derniere_erreur_le": instant()} if code else {}), **valeurs))
    journaliser(cnx, compte_id, evenement, acteur, code=code, details={"etat": etat})


def noter_erreur(cnx: Connection, compte_id: str, acteur: str, code: str) -> None:
    """Retient le dernier CODE d'erreur typé (visible côté admin) sans changer l'état du compte."""
    ligne = _ligne(cnx, compte_id)
    cnx.execute(update(COURRIEL_COMPTES).where(COURRIEL_COMPTES.c.compte_id == compte_id).values(
        derniere_erreur_code=code, derniere_erreur_le=instant(), revision=ligne["revision"] + 1))
    journaliser(cnx, compte_id, "compte.erreur", acteur, code=code)


def marquer_connecte(cnx: Connection, compte_id: str, acteur: str, *, secret_nom: str, generation: int,
                     portees: frozenset[str]) -> None:
    exiger_consentement(_ligne(cnx, compte_id))
    changer_etat(cnx, compte_id, "connecte", acteur, evenement="compte.connecte", secret_nom=secret_nom,
                 generation=generation, portees=json.dumps(sorted(portees)), connecte_par=acteur,
                 derniere_erreur_code=None, derniere_erreur_le=None)


def nom_secret(compte_id: str, generation: int) -> str:
    return f"courriel.{compte_id}.g{generation}"


def curseurs(cnx: Connection, compte_id: str) -> dict[str, str]:
    return json.loads(_ligne(cnx, compte_id)["curseurs"])


def enregistrer_synchro(cnx: Connection, compte_id: str, acteur: str, *, curseurs_a_jour: Mapping[str, str | None],
                        statut: str, ajoutes: int, code: str | None = None) -> None:
    """Persiste les curseurs (un `None` retire le curseur : nouvel amorçage) et le résultat du dernier passage."""
    ligne = _ligne(cnx, compte_id)
    courants = json.loads(ligne["curseurs"])
    for dossier, valeur in curseurs_a_jour.items():
        if valeur is None:
            courants.pop(dossier, None)
        else:
            courants[dossier] = valeur
    cnx.execute(update(COURRIEL_COMPTES).where(COURRIEL_COMPTES.c.compte_id == compte_id).values(
        curseurs=json.dumps(courants, sort_keys=True), derniere_synchro_le=instant(), derniere_synchro_statut=statut,
        messages_total=ligne["messages_total"] + ajoutes, modifie_le=instant(), revision=ligne["revision"] + 1,
        **({"derniere_erreur_code": code, "derniere_erreur_le": instant()} if code
           else {"derniere_erreur_code": None, "derniere_erreur_le": None})))
    journaliser(cnx, compte_id, "synchro", acteur, code=code, details={"statut": statut, "messages": ajoutes})


def journal(cnx: Connection, compte_id: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    requete = select(COURRIEL_JOURNAL).order_by(COURRIEL_JOURNAL.c.id.desc()).limit(max(1, min(limite, 500)))
    if compte_id is not None:
        requete = requete.where(COURRIEL_JOURNAL.c.compte_id == compte_id)
    return [dict(r) for r in cnx.execute(requete).mappings()]
