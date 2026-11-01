"""Statut d'un client après vérification d'identité (M1.10) : la machine d'états et ses règles. Module pur.

Problème : un correspondant écrit « je suis le client X, où en est ma facture? ». L'adresse d'un courriel s'usurpe
(M1-canaux §13.4). M1 ne répond sur le dossier d'un client qu'à une personne dont l'identité est établie par des MOYENS
dont la preuve ne vient pas de l'agent :

- `code_courriel` : un code à usage unique, envoyé (après approbation d'un humain, sas N3) à l'adresse du dossier,
que le correspondant renvoie par courriel. La preuve est le RETOUR de ce code depuis la même adresse, vérifié par le
code (empreinte salée) : l'agent ne le voit jamais, il ne peut pas se l'attester ;
- les moyens ATTESTÉS PAR UNE PERSONNE authentifiée (`MOYENS_HUMAINS`) : rappel au numéro du dossier, référence de
dossier citée, connaissance du dossier, pièce d'identité vue. Jamais une pièce n'est conservée : seuls le type de
pièce et le nom de la personne qui l'a vue.

Niveaux d'accès (jamais décidés par l'agent) :
`aucun` -> `probable` (un moyen valide) -> `general` (deux moyens distincts valides) ; `sensible` exige en plus la
décision d'une personne. L'état d'une vérification : `inconnu`, `a_verifier`, `verifie` (n moyens), `refuse`,
`expire`. Tout a une durée de vie bornée (`VALIDITE_*`) ; la rétention des lignes est bornée (`RETENTION_*`, Loi 25 :
finalité déclarée, pseudonyme du correspondant, aucun texte libre non filtré).

Aucune horloge, aucun aléa, aucune base : `maintenant` est toujours fourni.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import hmac
import re
from collections.abc import Iterable, Mapping
from typing import Any

MOYEN_CODE = "code_courriel"
MOYENS_HUMAINS = ("rappel_numero_dossier", "reference_dossier", "connaissance_dossier", "piece_identite_vue")
MOYENS = (MOYEN_CODE, *MOYENS_HUMAINS)
TYPES_PIECE = ("permis_conduire", "passeport", "carte_assurance_maladie", "autre")
NIVEAUX = ("aucun", "probable", "general", "sensible")
ETATS = ("inconnu", "a_verifier", "verifie", "refuse", "expire")
FINALITES = ("statut_dossier", "changement_rendez_vous", "facturation", "donnees_personnelles")
ACTIONS_SENSIBLES = ("changement_rendez_vous", "facturation", "donnees_personnelles")

VALIDITE_CODE_MIN = 30
VALIDITE_MOYEN_MIN = 60
VALIDITE_SENSIBLE_MIN = 240
ESSAIS_MAX = 3
VERROU_MIN = 24 * 60
RETENTION_JOURS = 90
RETENTION_MAX_JOURS = 365
LONGUEUR_CODE = 6
TEXTE_SI_NON = "Je vais vérifier avec l'équipe."

TYPE_OUVERTE = "verification_ouverte"
TYPE_ESSAI = "verification_essai_code"
TYPE_ATTESTATION = "verification_attestation"
TYPE_DECISION = "verification_decision"

_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_DONNEE_IDENTIFIANTE = re.compile(r"\d{6,}|\b[A-Z]\d{4}[- ]?\d{6}[- ]?\d{2}\b|\b[A-Z]{4}\s?\d{8}\b")


class RefusIdentite(ValueError):
    """Refus typé `REJ-M1-IDENT-…` : le message commence par le code."""


def _t(valeur: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(valeur)
    if d.tzinfo is None:
        raise RefusIdentite("REJ-M1-IDENT-HORODATAGE: instant avec fuseau requis")
    return d


def _plus(valeur: str, minutes: int) -> str:
    return (_t(valeur) + dt.timedelta(minutes=minutes)).isoformat()


def empreinte_code(sel: str, code: str) -> str:
    return hashlib.sha256(f"m1-ident|{sel}|{code}".encode()).hexdigest()


def code_valide(sel: str, empreinte: str, code: str) -> bool:
    return hmac.compare_digest(empreinte_code(sel, code), empreinte)


def extraire_code(texte: str) -> str | None:
    """Le code à 6 chiffres d'une réponse, s'il y en a EXACTEMENT un (deux candidats : ambigu, refusé)."""
    trouves = set(_CODE.findall(texte or ""))
    return next(iter(trouves)) if len(trouves) == 1 else None


def exiger_sans_donnee_identifiante(texte: str | None) -> str | None:
    """Aucun numéro de pièce, de permis, d'assurance ou longue suite de chiffres ne se range au registre."""
    if texte is None:
        return None
    if _DONNEE_IDENTIFIANTE.search(texte):
        raise RefusIdentite(
            "REJ-M1-IDENT-DONNEE-IDENTIFIANTE: aucun numéro de pièce ou de dossier personnel n'est conservé"
        )
    return texte.strip()[:200]


def ligne_ouverture(
    *,
    verification_id: str,
    cle: str,
    canal: str,
    finalite: str,
    signal_id: str,
    maintenant: str,
    sel: str,
    empreinte: str | None,
    brouillon_id: str | None,
    retention_jours: int,
) -> dict[str, Any]:
    if finalite not in FINALITES:
        raise RefusIdentite(f"REJ-M1-IDENT-FINALITE: finalité parmi {', '.join(FINALITES)}")
    if type(retention_jours) is not int or not 1 <= retention_jours <= RETENTION_MAX_JOURS:
        raise RefusIdentite(f"REJ-M1-IDENT-RETENTION: rétention de 1 à {RETENTION_MAX_JOURS} jours")
    _t(maintenant)
    return {
        "type_entree": TYPE_OUVERTE,
        "horodatage": maintenant,
        "verification_id": verification_id,
        "cle": cle,
        "canal": canal,
        "finalite": finalite,
        "signal_id": signal_id,
        "sel": sel,
        "empreinte_code": empreinte,
        "brouillon_id": brouillon_id,
        "expire_le": _plus(maintenant, VALIDITE_CODE_MIN),
        "conserver_jusqu_au": _plus(maintenant, retention_jours * 24 * 60),
    }


@dataclasses.dataclass(frozen=True)
class Projection:
    verification_id: str
    etat: str
    niveau_acces: str
    moyens_valides: tuple[str, ...]
    nb_moyens: int
    essais_restants: int
    finalite: str
    expire_le: str | None
    decision: str | None
    raisons: tuple[str, ...]

    def vers_json(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["moyens_valides"] = list(self.moyens_valides)
        d["raisons"] = list(self.raisons)
        d["reponse_autorisee"] = {
            "statut_general": self.niveau_acces in ("general", "sensible"),
            "sensible": self.niveau_acces == "sensible",
            "texte_si_refuse": TEXTE_SI_NON,
        }
        return d


def projeter(lignes: Iterable[Mapping[str, Any]], verification_id: str, maintenant: str) -> Projection:
    """L'état d'une vérification à l'instant `maintenant`, rejoué depuis ses lignes. Pure."""
    now = _t(maintenant)
    mes = [m for m in lignes if m.get("verification_id") == verification_id]
    ouverture = next((m for m in mes if m["type_entree"] == TYPE_OUVERTE), None)
    if ouverture is None:
        return Projection(verification_id, "inconnu", "aucun", (), 0, ESSAIS_MAX, "", None, None, ("inconnue",))
    if now > _t(ouverture["conserver_jusqu_au"]):
        return Projection(
            verification_id, "expire", "aucun", (), 0, 0, ouverture["finalite"], None, None, ("retention_depassee",)
        )
    raisons: list[str] = []
    echecs = [m for m in mes if m["type_entree"] == TYPE_ESSAI and not m["reussi"]]
    reussites = [m for m in mes if m["type_entree"] == TYPE_ESSAI and m["reussi"]]
    valides: dict[str, str] = {}
    if reussites and _t(reussites[0]["horodatage"]) <= _t(ouverture["expire_le"]):
        valides[MOYEN_CODE] = _plus(reussites[0]["horodatage"], VALIDITE_MOYEN_MIN)
    for m in mes:
        if m["type_entree"] == TYPE_ATTESTATION:
            valides.setdefault(m["moyen"], _plus(m["horodatage"], VALIDITE_MOYEN_MIN))
    vivants = tuple(sorted(k for k, fin in valides.items() if now <= _t(fin)))
    decisions = [m for m in mes if m["type_entree"] == TYPE_DECISION]
    derniere = decisions[-1] if decisions else None
    essais_restants = max(ESSAIS_MAX - len(echecs), 0)
    expire_le: str | None = None
    if derniere is not None and derniere["decision"] == "refuser":
        if now <= _t(_plus(derniere["horodatage"], VERROU_MIN)):
            return Projection(
                verification_id,
                "refuse",
                "aucun",
                (),
                0,
                0,
                ouverture["finalite"],
                _plus(derniere["horodatage"], VERROU_MIN),
                "refuser",
                ("refus_humain",),
            )
        return Projection(
            verification_id, "expire", "aucun", (), 0, 0, ouverture["finalite"], None, "refuser", ("refus_humain_echu",)
        )
    if len(echecs) >= ESSAIS_MAX and not vivants:
        dernier_echec = echecs[-1]["horodatage"]
        if now <= _t(_plus(dernier_echec, VERROU_MIN)):
            return Projection(
                verification_id,
                "refuse",
                "aucun",
                (),
                0,
                0,
                ouverture["finalite"],
                _plus(dernier_echec, VERROU_MIN),
                None,
                ("essais_epuises",),
            )
        return Projection(
            verification_id, "expire", "aucun", (), 0, 0, ouverture["finalite"], None, None, ("essais_epuises_echus",)
        )
    niveau = "aucun"
    if len(vivants) >= 1:
        niveau = "probable"
    if len(vivants) >= 2:
        niveau = "general"
    sensible = False
    if derniere is not None and derniere["decision"] == "valider" and vivants:
        fin = _plus(derniere["horodatage"], VALIDITE_SENSIBLE_MIN)
        if now <= _t(fin) and ouverture["finalite"] in FINALITES:
            sensible = True
            expire_le = fin
    if sensible:
        niveau = "sensible"
        raisons.append("valide_par_une_personne")
    if vivants:
        etat = "verifie"
        expire_le = expire_le or max(valides[m] for m in vivants)
    elif reussites or any(m["type_entree"] == TYPE_ATTESTATION for m in mes) or derniere is not None:
        etat, raisons = "expire", [*raisons, "moyens_expires"]
    elif now > _t(ouverture["expire_le"]):
        etat, raisons = "expire", [*raisons, "code_expire"]
    else:
        etat, expire_le = "a_verifier", ouverture["expire_le"]
    if len(vivants) == 1:
        raisons.append("un_seul_moyen")
    return Projection(
        verification_id,
        etat,
        niveau if etat == "verifie" else "aucun",
        vivants,
        len(vivants),
        essais_restants,
        ouverture["finalite"],
        expire_le,
        None if derniere is None else derniere["decision"],
        tuple(raisons),
    )


def exiger_niveau(projection: Projection, finalite: str) -> bool:
    """Vrai si le niveau d'accès suffit pour répondre sur cette finalité. Une action sensible exige la décision d'une
    personne ; un simple statut, deux moyens."""
    if finalite in ACTIONS_SENSIBLES:
        return projection.niveau_acces == "sensible"
    return projection.niveau_acces in ("general", "sensible")
