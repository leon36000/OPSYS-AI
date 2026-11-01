"""Conversions HORS LIGNE importées (appel, rendez-vous, soumission signée, vente) : compter une issue, jamais
l'expliquer.

Une conversion hors ligne est un fait que le site ne voit pas. L'entreprise la saisit ou l'exporte de son CRM ; M7
la RATTACHE à une source normalisée (convention UTM gelée, `utm.py`) et l'annonce à M2 (source et issue d'un lead)
et à M8 (comptage par source) par `m7.conversion_hors_ligne_importee`. Elle n'établit AUCUNE causalité.

Minimisation (Loi 25) : la liste des champs est FERMÉE. Pas de nom, de courriel, de téléphone, d'adresse, d'identifiant
publicitaire de clic ni de texte libre : le `lead_id` est l'identifiant opaque que M2 connaît, et un identifiant qui
ressemble à un courriel ou à un téléphone est refusé. Une conversion sans source reste sans source (`null`), jamais
attribuée par défaut ; une source ou une campagne qui ne se normalise pas fait refuser le lot (rien n'est deviné).

Registre `conversions_hors_ligne` : append-only à chaîne de hachage. Même `conversion_id` et même contenu : rien
(idempotent) ; même identifiant, même révision, contenu différent : refus ; une révision explicite (`revision` + 1)
exige un motif de l'énuméré. Un lot (200 au plus) est TOUT OU RIEN : il est validé en entier avant la première
écriture, puis écrit avec ses événements dans une seule transaction.

Module : le journal est injecté ; les événements passent par `opsys.evenements` dans la transaction courante.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from opsys import evenements, stockage

from .. import journal_chaine
from . import utm
from .verdicts import construire_verdict, refus_outil

DEPARTEMENT = "m07-marketing"
REGISTRE = (DEPARTEMENT, "conversions_hors_ligne")
TYPE_MAILLON = "conversion"
TYPE_EVENEMENT = "m7.conversion_hors_ligne_importee"
PRODUCTEUR = DEPARTEMENT
LOT_MAX = 200
TYPES = ("appel", "rendez_vous", "soumission_signee", "vente")
MOTIFS_REVISION = ("correction_valeur", "correction_source", "correction_date", "correction_type")
CHAMPS_ENTREE = (
    "conversion_id",
    "lead_id",
    "type",
    "convertie_le",
    "valeur_cad",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "revision",
    "motif_revision",
)
REQUIS = ("conversion_id", "lead_id", "type", "convertie_le")
DATE_MIN = date(2020, 1, 1)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_LEAD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_VALEUR = re.compile(r"^[0-9]{1,12}(?:\.[0-9]{1,2})?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_COORDONNEE = re.compile(r"@|\d{3}[-. ]\d{3}[-. ]\d{4}|\+?\d{10,}")


class RefusConversion(ValueError):
    """Refus typé d'un import : `verdict` porte `{code, statut, detail}`."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.verdict = construire_verdict(code, detail=detail)


def _refus(code: str, detail: str) -> RefusConversion:
    return RefusConversion(code, detail)


def valeur_canonique(brut: Any) -> str | None:
    """La valeur en CAD en texte à deux décimales, ou `None` si absente. Un nombre JSON (flottant, entier) est "
    "refusé."""
    if brut is None:
        return None
    if not isinstance(brut, str) or not _VALEUR.fullmatch(brut):
        raise _refus(
            "REJ-MESURE-CONVERSION-VALEUR",
            "valeur_cad : TEXTE décimal >= 0 à deux décimales au plus (jamais un nombre JSON)",
        )
    try:
        return format(Decimal(brut).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    except InvalidOperation:  # pragma: no cover — le motif l'exclut
        raise _refus("REJ-MESURE-CONVERSION-VALEUR", "valeur_cad illisible") from None


def normaliser_entree(brut: Any, maintenant: datetime) -> dict[str, Any]:
    """La forme canonique d'une conversion à importer (révision et motif compris), ou `RefusConversion`."""
    if not isinstance(brut, Mapping):
        raise _refus("REJ-MESURE-CONVERSION-INVALIDE", "conversion attendue : objet")
    inconnus = sorted(set(brut) - set(CHAMPS_ENTREE))
    if inconnus:
        raise _refus(
            "REJ-MESURE-CONVERSION-CHAMP-INCONNU",
            f"champs hors de la liste fermée : {inconnus} (aucun nom, courriel, téléphone ni identifiant publicitaire)",
        )
    manquants = [c for c in REQUIS if c not in brut]
    if manquants:
        raise _refus("REJ-MESURE-CONVERSION-INVALIDE", f"champs requis absents : {manquants}")
    if not isinstance(brut["conversion_id"], str) or not _ID.fullmatch(brut["conversion_id"]):
        raise _refus(
            "REJ-MESURE-CONVERSION-INVALIDE", "conversion_id invalide (80 caractères, lettres, chiffres, . _ : -)"
        )
    if not isinstance(brut["lead_id"], str) or not _LEAD.fullmatch(brut["lead_id"]):
        raise _refus("REJ-MESURE-CONVERSION-INVALIDE", "lead_id invalide : l'identifiant opaque de M2 est attendu")
    if _COORDONNEE.search(brut["lead_id"]) or _COORDONNEE.search(brut["conversion_id"]):
        raise _refus(
            "REJ-MESURE-CONVERSION-COORDONNEE",
            "un identifiant ressemble à un courriel ou à un téléphone : refusé (Loi 25)",
        )
    if brut["type"] not in TYPES:
        raise _refus("REJ-MESURE-CONVERSION-INVALIDE", f"type attendu parmi {list(TYPES)}")
    jour_brut = brut["convertie_le"]
    if not isinstance(jour_brut, str) or not _DATE.fullmatch(jour_brut):
        raise _refus("REJ-MESURE-CONVERSION-INVALIDE", "convertie_le attendu AAAA-MM-JJ")
    try:
        jour = date.fromisoformat(jour_brut)
    except ValueError:
        raise _refus("REJ-MESURE-CONVERSION-INVALIDE", "convertie_le n'est pas une date civile") from None
    if jour < DATE_MIN:
        raise _refus("REJ-MESURE-CONVERSION-INVALIDE", f"convertie_le avant {DATE_MIN.isoformat()}")
    if jour > maintenant.astimezone(UTC).date():
        raise _refus("REJ-MESURE-CONVERSION-FUTURE", "convertie_le est dans le futur par rapport à l'import")
    revision = brut.get("revision", 1)
    if type(revision) is not int or not 1 <= revision <= 99:
        raise _refus("REJ-MESURE-CONVERSION-INVALIDE", "revision : entier de 1 à 99")
    motif = brut.get("motif_revision")
    if revision == 1 and motif is not None:
        raise _refus("REJ-MESURE-CONVERSION-MOTIF", "motif_revision n'a de sens qu'à partir de la révision 2")
    if revision > 1 and motif not in MOTIFS_REVISION:
        raise _refus("REJ-MESURE-CONVERSION-MOTIF", f"une révision exige un motif parmi {list(MOTIFS_REVISION)}")
    normalises = {}
    for champ_brut, fonction in (
        ("utm_source", utm.normaliser_source),
        ("utm_medium", utm.normaliser_medium),
        ("utm_campaign", utm.normaliser_campagne),
    ):
        valeur = brut.get(champ_brut)
        if valeur is None:
            normalises[champ_brut] = None
            continue
        r = fonction(valeur)
        if r["verdict"] == utm.NON_NORMALISABLE:
            raise _refus("REJ-MESURE-UTM-NON-NORMALISABLE", f"{champ_brut} : {r['raison']}")
        normalises[champ_brut] = r["normalise"]
    return {
        "conversion_id": brut["conversion_id"],
        "revision": revision,
        "lead_id": brut["lead_id"],
        "type_conversion": brut["type"],
        "convertie_le": jour.isoformat(),
        "valeur_cad": valeur_canonique(brut.get("valeur_cad")),
        **normalises,
        "motif_revision": motif,
    }


def _contenu(enregistrement: Mapping[str, Any]) -> dict[str, Any]:
    """Ce qui fait l'IDENTITÉ de contenu d'une conversion (tout sauf la révision et le motif)."""
    return {k: v for k, v in enregistrement.items() if k not in ("revision", "motif_revision")}


def charger(journal: Sequence[Any]) -> list[dict[str, Any]]:
    """Les enregistrements du registre, chaîne vérifiée. Une altération est une ERREUR, jamais une lecture partielle."""
    if journal_chaine.verifier(journal):
        raise _refus("REJ-MESURE-JOURNAL-ALTERE", "la chaîne de hachage du registre des conversions ne correspond plus")
    sortie = []
    for m in journal:
        if m["type"] != TYPE_MAILLON:
            raise _refus("REJ-MESURE-JOURNAL-ALTERE", "maillon inattendu dans le registre des conversions")
        sortie.append({k: v for k, v in m.items() if k not in journal_chaine.CLES_RESERVEES and k != "par"})
    return sortie


def courantes(journal: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """La dernière révision de chaque conversion (par `conversion_id`)."""
    derniers: dict[str, dict[str, Any]] = {}
    for e in charger(journal):
        attendu = 1 if e["conversion_id"] not in derniers else derniers[e["conversion_id"]]["revision"] + 1
        if e["revision"] != attendu:
            raise _refus("REJ-MESURE-JOURNAL-ALTERE", "révisions d'une conversion incohérentes")
        derniers[e["conversion_id"]] = e
    return derniers


def _instant_texte(maintenant: datetime) -> str:
    return maintenant.astimezone(UTC).isoformat().replace("+00:00", "Z")


def importer(journal: Any, conversions: Iterable[Any], par: str, maintenant: datetime) -> dict[str, Any]:
    """Importe un lot de conversions (tout ou rien). Rend `{accepte, ecrites, deja_presentes, revisions, conversions}`
    ou `{accepte: False, refus: [...]}` ; en cas de refus RIEN n'est écrit ni annoncé."""
    if maintenant.tzinfo is None:
        raise ValueError("horloge sans fuseau")
    try:
        liste = list(conversions) if not isinstance(conversions, (str, bytes, Mapping)) else None
        if liste is None:
            raise _refus("REJ-MESURE-CONVERSION-INVALIDE", "liste de conversions attendue")
        if not 1 <= len(liste) <= LOT_MAX:
            code = "REJ-MESURE-LOT-TROP-GROS" if len(liste) > LOT_MAX else "REJ-MESURE-CONVERSION-INVALIDE"
            raise _refus(code, f"un lot compte de 1 à {LOT_MAX} conversions")
        presents = courantes(journal)
        a_ecrire: list[dict[str, Any]] = []
        dans_le_lot: dict[str, dict[str, Any]] = {}
        deja = 0
        for rang, brut in enumerate(liste):
            try:
                e = normaliser_entree(brut, maintenant)
            except RefusConversion as refus:
                raise _refus(refus.verdict["code"], f"conversion {rang} : {refus.verdict['detail']}") from None
            ident = e["conversion_id"]
            precedent = dans_le_lot.get(ident) or presents.get(ident)
            if precedent is None:
                if e["revision"] != 1:
                    raise _refus(
                        "REJ-MESURE-CONVERSION-REVISION-INITIALE",
                        f"conversion {rang} : une nouvelle conversion commence à la révision 1",
                    )
            elif e["revision"] == precedent["revision"]:
                if _contenu(e) != _contenu(precedent):
                    raise _refus(
                        "REJ-MESURE-CONVERSION-CONFLIT",
                        f"conversion {rang} : même révision, contenu différent (réviser avec revision + 1)",
                    )
                deja += 1
                continue
            elif e["revision"] < precedent["revision"]:
                raise _refus(
                    "REJ-MESURE-CONVERSION-REVISION-PERIMEE",
                    f"conversion {rang} : la révision {precedent['revision']} existe déjà",
                )
            elif e["revision"] != precedent["revision"] + 1:
                raise _refus(
                    "REJ-MESURE-CONVERSION-REVISION-SAUTEE",
                    f"conversion {rang} : révision suivante attendue : {precedent['revision'] + 1}",
                )
            elif _contenu(e) == _contenu(precedent):
                raise _refus(
                    "REJ-MESURE-CONVERSION-REVISION-PERIMEE",
                    f"conversion {rang} : une révision doit changer le contenu",
                )
            dans_le_lot[ident] = e
            a_ecrire.append(e)
    except RefusConversion as refus:
        return refus_outil(refus.verdict)
    instant = _instant_texte(maintenant)
    with stockage.transaction():
        for e in a_ecrire:
            journal_chaine.ajouter(journal, TYPE_MAILLON, {**e, "par": par}, instant)
            evenements.publier(
                TYPE_EVENEMENT,
                PRODUCTEUR,
                {
                    "conversion_id": e["conversion_id"],
                    "lead_id": e["lead_id"],
                    "type": e["type_conversion"],
                    "convertie_le": e["convertie_le"],
                    "utm_source": e["utm_source"],
                    "utm_medium": e["utm_medium"],
                    "utm_campaign": e["utm_campaign"],
                    "valeur_cad": e["valeur_cad"],
                    "source_normalisee": e["utm_source"] is not None,
                    "importee_le": instant,
                },
                evenement_id=f"m7-conversion-{e['conversion_id']}-r{e['revision']}",
            )
    revisions = sum(1 for e in a_ecrire if e["revision"] > 1)
    return {
        "accepte": True,
        "ecrites": len(a_ecrire) - revisions,
        "revisions": revisions,
        "deja_presentes": deja,
        "conversions": [{"conversion_id": e["conversion_id"], "revision": e["revision"]} for e in a_ecrire],
    }


def dans_la_periode(courantes_: Mapping[str, Mapping[str, Any]], debut: date, fin: date) -> list[dict[str, Any]]:
    """Les conversions courantes dont le jour est dans [debut, fin], triées (jour, identifiant)."""
    bas, haut = debut.isoformat(), fin.isoformat()
    return sorted(
        (dict(e) for e in courantes_.values() if bas <= e["convertie_le"] <= haut),
        key=lambda e: (e["convertie_le"], e["conversion_id"]),
    )


__all__ = [
    "CHAMPS_ENTREE",
    "LOT_MAX",
    "MOTIFS_REVISION",
    "REGISTRE",
    "RefusConversion",
    "TYPES",
    "TYPE_EVENEMENT",
    "charger",
    "courantes",
    "dans_la_periode",
    "importer",
    "normaliser_entree",
    "valeur_canonique",
]
