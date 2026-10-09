"""File et prise interne DEVICE de rappels importés. Aucun canal ou contact émis."""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from opsys import approbations, contexte, idempotence, stockage

from . import reception, transferts
from .registre import Registre

LISTE = "m1_lister_rappels_appareil"
PRISE = "m1_prendre_en_charge_rappel_appareil"
_META = contextvars.ContextVar("m1_meta_prise_rappel", default=None)


class Refus(Exception):
    """Suffixe fermé seulement ; pas de contenu métier dans les erreurs de garde."""

    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(suffixe)


@contextmanager
def contexte_mutation(meta: idempotence.Meta):
    token = _META.set(meta)
    try:
        yield
    finally:
        _META.reset(token)


def _hash(v):
    return isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v, re.ASCII) is not None


def _transfert(v):
    return isinstance(v, str) and re.fullmatch(r"tr-[0-9a-f]{20}", v, re.ASCII) is not None


def _texte(v, maximum=256):
    return (
        isinstance(v, str)
        and bool(v.strip())
        and len(v) <= maximum
        and not any(unicodedata.category(c) in {"Cc", "Cs"} for c in v)
    )


def _date(v):
    if not isinstance(v, str):
        raise Refus("HORODATAGE-INVALIDE")
    try:
        h = dt.datetime.fromisoformat(v)
        if h.tzinfo is None or h.utcoffset() is None:
            raise ValueError
        return h
    except ValueError as exc:
        raise Refus("HORODATAGE-INVALIDE") from exc


def _meta():
    m = _META.get()
    if not isinstance(m, idempotence.Meta) or not _texte(m.appareil):
        raise Refus("IDEMPOTENCE-REQUIS")
    try:
        if not isinstance(m.cle, str) or str(UUID(m.cle)) != m.cle:
            raise ValueError
    except ValueError as exc:
        raise Refus("IDEMPOTENCE-REQUIS") from exc
    _date(m.horodatage_appareil)
    return m


def _acteur():
    cnx = stockage.connexion_courante()
    appelante = contexte.identite_appelante()
    if cnx is None or not cnx.in_transaction() or appelante is None or appelante.source != "appareil":
        raise Refus("IDENTITE-INVALIDE")
    confirme = approbations.signataire_valide(cnx, appelante)
    if confirme is None or confirme.role != "admin":
        raise Refus("IDENTITE-INVALIDE")
    if (
        cnx.closed
        or cnx.dialect.name != "sqlite"
        or cnx.engine.url != stockage.moteur().url
        or not isinstance(cnx.connection.driver_connection, sqlite3.Connection)
        or not cnx.connection.driver_connection.in_transaction
    ):
        raise Refus("STOCKAGE-NON-QUALIFIE")
    return {"par": confirme.personne, "role": confirme.role, "voie": confirme.source}, cnx


def _args(arguments, nom):
    if type(arguments) is not dict:
        raise Refus("ARGUMENTS-INVALIDES")
    if nom == LISTE:
        if set(arguments) - {"apres_transfert_id", "taille_page"}:
            raise Refus("ARGUMENTS-INVALIDES")
        cle, taille = arguments.get("apres_transfert_id"), arguments.get("taille_page", 8)
        if cle is not None and not _transfert(cle):
            raise Refus("PAGINATION-INVALIDE")
        if type(taille) is not int or not 1 <= taille <= 8:
            raise Refus("PAGINATION-INVALIDE")
    elif nom == PRISE:
        if (
            set(arguments) != {"transfert_id", "snapshot_attendu"}
            or not _transfert(arguments["transfert_id"])
            or not _hash(arguments["snapshot_attendu"])
        ):
            raise Refus("ARGUMENTS-INVALIDES")
        _meta()
    else:
        raise Refus("OUTIL-INVALIDE")


def _sources(lignes, etat):
    t = etat.identifiant
    revendiquees = [
        ligne
        for ligne in lignes
        if ligne.get("type_entree") == "appel_importe"
        and isinstance(ligne.get("reponse"), dict)
        and isinstance(ligne["reponse"].get("tache_rappel"), dict)
        and ligne["reponse"]["tache_rappel"].get("transfert_id") == t
    ]
    valides = transferts.sources_appel_rappel(lignes, t)
    if len(revendiquees) != len(valides):
        raise Refus("SOURCE-INVALIDE")
    if not valides:
        return ()
    o = etat.ouverture
    contact = o.get("contact")
    telephone = contact.get("telephone") if isinstance(contact, dict) else None
    if (
        o.get("type_transfert") != "ventes"
        or o.get("canal") != "telephone"
        or not isinstance(telephone, str)
        or re.fullmatch(r"\+[1-9][0-9]{6,14}", telephone) is None
        or o.get("conversation_id") != reception.identifiant_de_conversation("sms", telephone)
        or not _transfert(t)
    ):
        raise Refus("SOURCE-INVALIDE")
    index = {ligne["ligne_id"]: ligne for ligne in lignes}
    for ligne in valides:
        reponse = ligne["reponse"]
        traitement = reponse.get("traitement")
        signal = index.get(traitement.get("signal_ligne_id")) if isinstance(traitement, dict) else None
        if (
            not isinstance(signal, dict)
            or signal.get("type_entree") != "signal"
            or signal.get("conversation_id") != o["conversation_id"]
            or signal.get("canal") != "telephone"
            or reponse.get("evenement_id") != ligne.get("evenement_id")
            or not _hash(ligne.get("empreinte"))
            or ("ligne_id" in reponse["tache_rappel"] and reponse["tache_rappel"]["ligne_id"] != o["ligne_id"])
        ):
            raise Refus("SOURCE-INVALIDE")
        _date(ligne.get("horodatage"))
    return valides


@dataclass(frozen=True)
class Admission:
    acteur: dict
    registre: Registre
    lignes: list
    etats: dict
    sources: dict


def admettre(arguments, *, nom):
    # Aucune lecture de registre ni argument d'autorité avant identité SQL courante.
    acteur, cnx = _acteur()
    _args(arguments, nom)
    from . import outils

    try:
        reg, lignes = outils._lire_registre_suivi_rappel()
        if stockage.connexion_courante() is not cnx:
            raise Refus("STOCKAGE-NON-QUALIFIE")
        etats = {e.identifiant: e for e in transferts.lire(lignes)}
        # Une source revendique une tâche inconnue : jamais omission silencieuse.
        for ligne in lignes:
            if ligne.get("type_entree") == "appel_importe" and isinstance(ligne.get("reponse"), dict):
                task = ligne["reponse"].get("tache_rappel")
                if isinstance(task, dict) and task.get("transfert_id") not in etats:
                    raise Refus("SOURCE-INVALIDE")
        if nom == PRISE:
            cible = arguments["transfert_id"]
            if cible not in etats:
                raise Refus("TRANSFERT-INCONNU")
            sources = {cible: _sources(lignes, etats[cible])}
            if not sources[cible]:
                raise Refus("SOURCE-ABSENTE")
        else:
            sources = {t: _sources(lignes, e) for t, e in etats.items()}
        return Admission(acteur, reg, lignes, etats, sources)
    except Refus:
        raise
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise Refus("SOURCE-INVALIDE") from exc


def _projection(lignes, t):
    p = transferts.projection_suivi_rappel(lignes, t)
    if p is None:
        raise Refus("SOURCE-INVALIDE")
    # Projection fermée native ; validate all dates/identity, not a partial invented state.
    if (
        set(p)
        != {
            "snapshot_suivi",
            "responsable",
            "role",
            "pris_en_charge_le",
            "tentatives_sans_contact",
            "derniere_tentative_le",
            "prochaine_tentative_le",
        }
        or not _hash(p["snapshot_suivi"])
        or type(p["tentatives_sans_contact"]) is not int
        or p["tentatives_sans_contact"] < 0
    ):
        raise Refus("SOURCE-INVALIDE")
    if p["responsable"] is not None:
        if not _texte(p["responsable"]) or p["role"] not in {"admin", "nathan_owner"}:
            raise Refus("SOURCE-INVALIDE")
        _date(p["pris_en_charge_le"])
    elif p["role"] is not None or p["pris_en_charge_le"] is not None or p["tentatives_sans_contact"]:
        raise Refus("SOURCE-INVALIDE")
    for k in ("derniere_tentative_le", "prochaine_tentative_le"):
        if p[k] is not None:
            _date(p[k])
    return p


def borner(reponse, *, rejoue=None):
    enveloppe = {"ok": True, "resultat": reponse}
    if rejoue is not None:
        enveloppe["rejoue"] = rejoue
    limite = contexte.limite_sortie()
    limite = 5400 if limite is None else min(5400, limite)
    if len(json.dumps(enveloppe, ensure_ascii=False)) > limite:
        raise Refus("SORTIE-TROP-VOLUMINEUSE")
    return reponse


def refus(exc):
    return {
        "accepte": False,
        "verdict": {
            "code": "REJ-M1-RAPPEL-" + exc.suffixe,
            "detail": "Dossier de rappel indisponible pour cette opération ; relire sous une autorité actuelle.",
        },
    }


def lister(apres_transfert_id=None, taille_page=8):
    try:
        a = admettre({"apres_transfert_id": apres_transfert_id, "taille_page": taille_page}, nom=LISTE)
        eligibles = sorted(t for t, e in a.etats.items() if e.ouvert and a.sources[t])
        apres = [t for t in eligibles if apres_transfert_id is None or t > apres_transfert_id]
        visibles = apres[:taille_page]
        rows = []
        for t in visibles:
            e, sources = a.etats[t], a.sources[t]
            _date(e.ouverture["horodatage"])
            lead = e.ouverture.get("lead_id")
            if lead is not None and not _texte(lead):
                raise Refus("SOURCE-INVALIDE")
            rows.append(
                {
                    "transfert_id": t,
                    "conversation_id": e.ouverture["conversation_id"],
                    "lead_id": lead,
                    "canal": e.ouverture["canal"],
                    "ouvert_le": e.ouverture["horodatage"],
                    "nombre_sources": len(sources),
                    "derniere_source": {
                        "ligne_id": sources[-1]["ligne_id"],
                        "statut": sources[-1]["statut"],
                        "recu_le": sources[-1]["horodatage"],
                    },
                    "suivi_rappel": _projection(a.lignes, t),
                }
            )
        reste = len(apres) - len(visibles)
        return borner(
            {
                "accepte": True,
                "resultat": {
                    "rappels": rows,
                    "page": {
                        "apres_transfert_id": apres_transfert_id,
                        "taille_page": taille_page,
                        "total": len(eligibles),
                        "retournes": len(rows),
                        "reste": reste,
                        "apres_suivant": visibles[-1] if reste else None,
                    },
                },
            }
        )
    except Refus as exc:
        return refus(exc)
    except (ValueError, KeyError, TypeError):
        return refus(Refus("SOURCE-INVALIDE"))


def _ack(lignes, index):
    ligne = lignes[index]
    return {
        "version": 1,
        "transfert_id": ligne["transfert_id"],
        "action": ligne["evenement"],
        "ligne_id": ligne["ligne_id"],
        "precedent_ligne_id": ligne["precedent_ligne_id"],
        "index": index,
        "snapshot_attendu": ligne["snapshot_attendu"],
        "par": ligne["par"],
        "role": ligne["role"],
        "voie": ligne["voie"],
        "appareil": ligne["appareil"],
        "intention_uuid": ligne["intention_uuid"],
        "recu_le_serveur": ligne["horodatage"],
        "horodatage_appareil": ligne["horodatage_appareil"],
        "suivi_rappel": _projection(lignes[: index + 1], ligne["transfert_id"]),
    }


def prendre(transfert_id, snapshot_attendu):
    arguments = {"transfert_id": transfert_id, "snapshot_attendu": snapshot_attendu}
    try:
        a = admettre(arguments, nom=PRISE)
        meta = _meta()
        h = contexte.horodatage_reception()
        if (
            h is None
            or h.appareil != meta.appareil
            or h.horodatage_appareil != _date(meta.horodatage_appareil)
            or h.recu_le.tzinfo is None
        ):
            raise Refus("HORODATAGE-REQUIS")
        projection = _projection(a.lignes, transfert_id)
        if not a.etats[transfert_id].ouvert:
            raise Refus("TRANSFERT-CLOS")
        if projection["snapshot_suivi"] != snapshot_attendu:
            raise Refus("SNAPSHOT-PERIME")
        if projection["responsable"] is not None:
            raise Refus("DEJA-ATTRIBUE")
        extra = {
            "appareil": meta.appareil,
            "intention_uuid": meta.cle,
            "snapshot_attendu": snapshot_attendu,
            "horodatage_appareil": _date(meta.horodatage_appareil).isoformat(),
        }
        ligne = {
            "type_entree": "transfert",
            "evenement": "prise_en_charge",
            "transfert_id": transfert_id,
            **a.acteur,
            "horodatage": h.recu_le.isoformat(),
            **extra,
        }
        fake = {**ligne, "ligne_id": "0" * 64, "precedent_ligne_id": a.lignes[-1]["ligne_id"] if a.lignes else None}
        # Quota complet contrôlé avant append ; hash factice de même longueur seulement pour ce budget.
        pre_lignes = [*a.lignes, fake]
        borner({"accepte": True, "resultat": _ack(pre_lignes, len(a.lignes))}, rejoue=False)
    except Refus as exc:
        return refus(exc)
    from . import outils

    try:
        resultat, ligne_id = outils._appliquer_suivi_rappel(
            a.acteur,
            transfert_id,
            transferts.EVT_PRISE_EN_CHARGE,
            snapshot_attendu,
            h.recu_le.isoformat(),
            None,
            champs_appareil=extra,
        )
        if not resultat.get("accepte") or ligne_id is None:
            raise RuntimeError("application du rappel incohérente après admission")
        lignes = a.registre.lire()
        if not Registre(lignes).valider_chaine()[0] or lignes[-1]["ligne_id"] != ligne_id:
            raise RuntimeError("preuve de rappel incohérente après append")
        reply = {"accepte": True, "resultat": _ack(lignes, len(lignes) - 1)}
        borner(reply, rejoue=False)
        return reply
    except Exception as exc:
        raise RuntimeError("prise de rappel non confirmée ; transaction à annuler") from exc


def verifier_rejeu(arguments, reponse):
    a = admettre(arguments, nom=PRISE)
    meta = _meta()
    try:
        if (
            type(reponse) is not dict
            or set(reponse) != {"ok", "resultat"}
            or reponse["ok"] is not True
            or type(reponse["resultat"]) is not dict
        ):
            raise Refus("REJEU-INCOHERENT")
        resultat = reponse["resultat"]
        if resultat.get("accepte") is False:
            # Seules les négations certaines émises AVANT append par le writer frais.
            # Claim/clé/corps sont déjà liés par la Cap ; aucun maillon n'existe à exiger ici.
            certain = {"TRANSFERT-CLOS", "SNAPSHOT-PERIME", "DEJA-ATTRIBUE", "SORTIE-TROP-VOLUMINEUSE"}
            if set(resultat) != {"accepte", "verdict"} or type(resultat["verdict"]) is not dict:
                raise Refus("REJEU-INCOHERENT")
            verdict = resultat["verdict"]
            code = verdict.get("code")
            if type(code) is not str or code not in {"REJ-M1-RAPPEL-" + suffixe for suffixe in certain}:
                raise Refus("REJEU-INCOHERENT")
            canonique = refus(Refus(code.removeprefix("REJ-M1-RAPPEL-")))
            if json.dumps(resultat, sort_keys=True, ensure_ascii=False, allow_nan=False) != json.dumps(
                canonique, sort_keys=True, ensure_ascii=False, allow_nan=False
            ):
                raise Refus("REJEU-INCOHERENT")
            if any(
                ligne.get("type_entree") == transferts.TYPE_ENTREE
                and ligne.get("evenement") == transferts.EVT_PRISE_EN_CHARGE
                and ligne.get("voie") == "appareil"
                and ligne.get("appareil") == meta.appareil
                and ligne.get("intention_uuid") == meta.cle
                for ligne in a.lignes
            ):
                # Une négation sans effet contredit la propre preuve DEVICE déjà persistée.
                raise Refus("REJEU-INCOHERENT")
            borner(resultat, rejoue=True)
            return
        if set(resultat) != {"accepte", "resultat"} or resultat.get("accepte") is not True:
            raise Refus("REJEU-INCOHERENT")
        ack = resultat["resultat"]
        if type(ack) is not dict or type(ack.get("index")) is not int or not 0 <= ack["index"] < len(a.lignes):
            raise Refus("REJEU-INCOHERENT")
        ligne = a.lignes[ack["index"]]
        if (
            ligne.get("type_entree") != "transfert"
            or ligne.get("evenement") != "prise_en_charge"
            or ligne.get("transfert_id") != arguments["transfert_id"]
            or ligne.get("par") != a.acteur["par"]
            or ligne.get("role") != "admin"
            or ligne.get("voie") != "appareil"
            or ligne.get("appareil") != meta.appareil
            or ligne.get("intention_uuid") != meta.cle
            or ligne.get("snapshot_attendu") != arguments["snapshot_attendu"]
            or ligne.get("horodatage_appareil") != _date(meta.horodatage_appareil).isoformat()
            or json.dumps(ack, sort_keys=True, ensure_ascii=False, allow_nan=False)
            != json.dumps(_ack(a.lignes, ack["index"]), sort_keys=True, ensure_ascii=False, allow_nan=False)
        ):
            raise Refus("REJEU-INCOHERENT")
        _date(ligne["horodatage"])
        borner(reponse["resultat"], rejoue=True)
    except Refus:
        raise
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise Refus("REJEU-INCOHERENT") from exc
