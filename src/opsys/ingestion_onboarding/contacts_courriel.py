"""Genre de brouillon « courriel_contact » : l'historique d'une boîte courriel devient des CANDIDATS pour le CRM de M2.

Chemin : les connecteurs courriel (`opsys.courriel_connecteurs.ingestion`), pendant l'amorçage d'un compte qui l'a
demandé
(`contacts_courriel = 1`, déclaré avec la finalité, Loi 25), déposent à chaque page un document de correspondants
(`MAGIE` en première ligne) dans la file d'onboarding EXISTANTE ; le lot est reprenable comme tout lot (tâches durables,
bail, reprise). Cinq étapes déterministes ici : lecture, validation (adresse normalisée, adresse automatisée repérée,
nom absent), dédoublonnage contre les brouillons et les contacts/clients déjà importés, proposition.

RIEN n'est écrit au CRM : chaque candidat est un brouillon à confirmer
(`m2_valider_brouillon_onboarding_contact_courriel`,
N3, décision humaine). Le nom affiché d'un correspondant est une donnée NON FIABLE (neutralisée à la collecte) ; une
adresse automatisée (noreply, notifications, infolettre…) est signalée `A_VERIFIER`, jamais écartée en silence.

Module pur : aucune entrée-sortie ; la file d'onboarding lui passe les lignes déjà lues du CSV.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

MAGIE = "opsys-courriel-contacts/v1"
COLONNES = ("nom", "courriel", "organisation", "recus", "envoyes", "premier", "dernier")
LIGNES_MAX = 5_000
CODES_RAISONS: tuple[str, ...] = (
    "REJ-ING-COURRIEL-AUTOMATISE",
    "REJ-ING-COURRIEL-ADRESSE-INVALIDE",
    "REJ-ING-COURRIEL-SANS-NOM",
    "REJ-ING-COURRIEL-TROP-DE-LIGNES",
    "REJ-ING-COURRIEL-ENTETE-INTROUVABLE",
)
_AUTOMATISE = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|mailer[-_.]?daemon|postmaster|bounces?|notifications?|"
    r"newsletter|infolettre|alerts?|alertes?|automated|auto[-_.]?reply|support-no|invoice[s]?|facturation-auto)"
    r"([-_.+][a-z0-9]+)*$")
_ENTIER = re.compile(r"^[0-9]{1,6}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$|^$")


def _raison(code: str, detail: str) -> dict[str, str]:
    if code not in CODES_RAISONS:
        raise ValueError(f"raison hors catalogue : {code!r}")
    return {"code": code, "detail": detail}


def est_document(candidats: Sequence[Mapping[str, Any]]) -> bool:
    """Vrai si un candidat de lecture du tableau commence par la ligne `MAGIE` (et par elle seule)."""
    return any(c["lignes"] and len(c["lignes"][0]) >= 1 and str(c["lignes"][0][0]).strip() == MAGIE
               and not any(str(x).strip() for x in c["lignes"][0][1:]) for c in candidats)


def lire(candidats: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Les lignes du premier candidat qui porte la `MAGIE` et l'en-tête exact ; `(lecture, None)` ou `(None, raison)`.
    Une ligne mal formée est REFUSÉE avec sa raison, jamais corrigée."""
    for candidat in candidats:
        lignes = candidat["lignes"]
        if not est_document([candidat]):
            continue
        if len(lignes) < 2 or tuple(str(c).strip() for c in lignes[1][:len(COLONNES)]) != COLONNES:
            return None, _raison("REJ-ING-COURRIEL-ENTETE-INTROUVABLE", f"colonnes attendues : {', '.join(COLONNES)}")
        if len(lignes) - 2 > LIGNES_MAX:
            return None, _raison("REJ-ING-COURRIEL-TROP-DE-LIGNES", f"plus de {LIGNES_MAX} correspondants")
        retenues, refusees = [], []
        for numero, ligne in enumerate(lignes[2:], 3):
            if not any(str(c).strip() for c in ligne):
                continue
            cellules = [" ".join(str(c).split()) for c in ligne[:len(COLONNES)]]
            cellules += [""] * (len(COLONNES) - len(cellules))
            champs = dict(zip(COLONNES, cellules, strict=True))
            if (not _ENTIER.fullmatch(champs["recus"]) or not _ENTIER.fullmatch(champs["envoyes"])
                    or not _DATE.fullmatch(champs["premier"]) or not _DATE.fullmatch(champs["dernier"])):
                refusees.append({"ligne": numero, **_raison("REJ-ING-COURRIEL-ADRESSE-INVALIDE",
                                                            "compteurs ou dates mal formés")})
                continue
            retenues.append({"ligne": numero, "champs": champs})
        return {"lignes": retenues, "refusees": refusees}, None
    return None, _raison("REJ-ING-COURRIEL-ENTETE-INTROUVABLE", "document de correspondants non reconnu")


def _empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def proposer(lignes: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(fiches, refusees)` : une fiche par adresse normalisée (les lignes d'une même adresse se cumulent), avec ses
    raisons et son statut (`PRET` ou `A_VERIFIER`). Le dédoublonnage contre le CRM est fait par le service."""
    from m2_revenue_crm import clients_importes

    par_adresse: dict[str, dict[str, Any]] = {}
    refusees: list[dict[str, Any]] = []
    for ligne in lignes:
        champs = ligne["champs"]
        adresse = clients_importes.normaliser_courriel(champs["courriel"])
        if adresse is None:
            refusees.append({"ligne": ligne["ligne"], **_raison("REJ-ING-COURRIEL-ADRESSE-INVALIDE",
                                                                "adresse mal formée : écartée de la proposition")})
            continue
        fiche = par_adresse.setdefault(adresse, {
            "courriel": adresse, "nom": "", "organisation": champs["organisation"].lower(), "recus": 0, "envoyes": 0,
            "premier": "", "dernier": "", "lignes": []})
        fiche["nom"] = fiche["nom"] or champs["nom"]
        fiche["recus"] += int(champs["recus"])
        fiche["envoyes"] += int(champs["envoyes"])
        if champs["premier"] and (not fiche["premier"] or champs["premier"] < fiche["premier"]):
            fiche["premier"] = champs["premier"]
        if champs["dernier"] > fiche["dernier"]:
            fiche["dernier"] = champs["dernier"]
        fiche["lignes"].append(ligne["ligne"])
    fiches = []
    for adresse in sorted(par_adresse):
        fiche = par_adresse[adresse]
        raisons = []
        if _AUTOMATISE.match(adresse.split("@", 1)[0]):
            raisons.append(_raison("REJ-ING-COURRIEL-AUTOMATISE", "adresse d'envoi automatisé probable : un humain "
                                   "décide de l'écarter ou de la garder"))
        if not fiche["nom"]:
            raisons.append(_raison("REJ-ING-COURRIEL-SANS-NOM", "aucun nom affiché : le fournir à la validation"))
        cles = sorted(set(clients_importes.empreintes_cles({"nom": fiche["nom"], "courriel": adresse})))
        fiche.update(raisons=raisons, statut="A_VERIFIER" if raisons else "PRET", cles=cles,
                     cle_metier=_empreinte("courriel-contact|" + adresse))
        fiches.append(fiche)
    return fiches, refusees


__all__ = ["CODES_RAISONS", "COLONNES", "MAGIE", "est_document", "lire", "proposer"]
