"""Extraction déterministe de faits d'un courriel de fournisseur ou de commande (M1.6, pont vers M5 et M6).

Le tri n'envoie pas de texte aux autres départements (le bus ne porte ni adresse ni courriel entier). Il leur donne des
faits MINIMAUX, bornés et sans interprétation :

- `jetons_reference` : identifiants candidats vus dans le texte (« PO-2026-014 », « INV-20931 »). Ce sont des chaînes à
  vérifier : le département destinataire ne retient que celles qu'il connaît déjà ;
- `lignes` : des quantités nommées (« 20 sacs de ciment ») pour un brouillon de commande, jamais un prix ;
- `etat_annonce` : ce que le fournisseur dit de sa commande (confirmée, expédiée, rupture, report, substitution) ;
- `dates_annoncees` : dates ISO lues dans le texte, en clair « annoncées », jamais promises par l'entreprise ;
- `expediteur_empreinte` : empreinte de l'adresse de l'expéditeur, pour la comparer à la fiche d'un fournisseur sans
  jamais faire circuler l'adresse.

Module pur : aucune horloge, aucun accès à la base, aucun réseau. Tout texte rendu est borné (longueur, jeu de
caractères) : un courriel hostile ne fait pas circuler de consigne.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from .tri_courriel import normaliser

JETONS_MAX = 20
JETON_LONGUEUR_MAX = 40  # borne du schéma de l'événement : un jeton plus long est ignoré, jamais tronqué
LIGNES_MAX = 30
DESIGNATION_MAX = 80
_JETON = re.compile(r"(?<![\w@./:])([A-Za-z]{1,6}[-_]?\d[A-Za-z0-9_-]{2,30})(?![\w@])")
_JETON_NUM = re.compile(r"(?<![\w@./:])(\d{4,}-[A-Za-z0-9-]{2,30})(?![\w@])")
_EXCLUS = (
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{3}-\d{3}-\d{4}$"),
    re.compile(r"^(?:tel|fax|cp)\d*$", re.I),
)
_PO = re.compile(r"^(?:PO|BC)[-_]?\d", re.I)
_UNITES = (
    r"x|sacs?|palettes?|boites?|rouleaux?|feuilles?|pieces?|unites?|verges?|pieds|planches?|gallons?|seaux|"
    r"tuyaux|poteaux|panneaux|litres?|paquets?|kg|metres?|m"
)
_LIGNE = re.compile(
    rf"(?P<q>\d{{1,5}}(?:[.,]\d{{1,2}})?)\s*(?P<u>{_UNITES})\b\s*(?:de |d'|du |des )?"
    rf"(?P<d>[a-z][a-z0-9'\-/ %]{{2,{DESIGNATION_MAX}}})"
)
_MOTS_DE_COUPE = (
    " pour ",
    " chez ",
    " avant ",
    " d'ici ",
    " livre ",
    " livrer ",
    " a livrer ",
    " au chantier ",
    " svp",
    " merci",
    " et ",
    " ainsi que ",
)
_MOIS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}
_DATE_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DATE_FR = re.compile(
    r"\b(\d{1,2}|1er) (janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)"
    r"(?: (20\d{2}))?\b"
)
_ETATS = (
    ("rupture", re.compile(r"\b(rupture de stock|en rupture|backorder|indisponible|epuise)\b")),
    ("report", re.compile(r"\b(report\w*|retard\w*|delai supplementaire|decale\w*)\b")),
    ("substitution", re.compile(r"\b(substitu\w*|equivalent|remplace par|alternative)\b")),
    ("expediee", re.compile(r"\b(expedie\w*|en route|numero de suivi|tracking|prete pour (ramassage|livraison))\b")),
    ("confirmee", re.compile(r"\b(confirm\w*|accuse de reception|bien recu|enregistree|order confirmation)\b")),
)


def empreinte_expediteur(adresse: str) -> str:
    return hashlib.sha256(("m1-expediteur|" + adresse.strip().lower()).encode("utf-8")).hexdigest()


def jetons_reference(texte: str) -> list[str]:
    vus: list[str] = []
    for motif in (_JETON, _JETON_NUM):
        for m in motif.finditer(texte or ""):
            jeton = m.group(1).upper()
            if len(jeton) > JETON_LONGUEUR_MAX or any(e.match(jeton) for e in _EXCLUS) or "[" in jeton:
                continue
            if any(jeton in v for v in vus):
                continue
            vus.append(jeton)
    return vus[:JETONS_MAX]


def references_po(jetons: list[str]) -> list[str]:
    return [j for j in jetons if _PO.match(j)]


def _decimal(q: str) -> str:
    return q.replace(",", ".")


def lignes_commande(texte: str) -> list[dict[str, Any]]:
    """Quantités nommées ; jamais plus de `LIGNES_MAX`. Sans valeur sûre, rien n'est inventé (liste vide)."""
    lignes: list[dict[str, Any]] = []
    for brut in re.split(r"[\n;•]|(?<=\d) ?- ", texte or ""):
        for n in re.split(r",| et | ainsi que | plus ", normaliser(brut)):
            for m in _LIGNE.finditer(n):
                designation = _couper(m.group("d")).strip(" -/,.")
                if len(designation) < 3 or designation.isdigit():
                    continue
                unite = m.group("u")
                q = _decimal(m.group("q"))
                try:
                    if float(q) <= 0:
                        continue
                except ValueError:
                    continue
                lignes.append(
                    {
                        "designation": designation[:DESIGNATION_MAX],
                        "quantite": q,
                        "unite": None if unite == "x" else unite,
                    }
                )
                if len(lignes) >= LIGNES_MAX:
                    return lignes
    return lignes


def _couper(designation: str) -> str:
    """La désignation, coupée au premier mot de liaison (« pour le chantier… ») : recherche simple, temps linéaire."""
    fin = len(designation)
    for mot in _MOTS_DE_COUPE:
        i = designation.find(mot)
        if i != -1:
            fin = min(fin, i)
    return designation[:fin]


def etat_annonce(texte: str) -> list[str]:
    n = normaliser(texte)
    return [nom for nom, motif in _ETATS if motif.search(n)]


def dates_annoncees(texte: str) -> list[str]:
    n = unicodedata.normalize("NFKD", (texte or "").lower())
    n = "".join(c for c in n if not unicodedata.combining(c))
    trouvees: list[str] = []
    for m in _DATE_ISO.finditer(n):
        trouvees.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    for m in _DATE_FR.finditer(n):
        annee = m.group(3)
        if not annee:
            continue  # sans année, rien n'est supposé
        jour = 1 if m.group(1) == "1er" else int(m.group(1))
        if 1 <= jour <= 31:
            trouvees.append(f"{annee}-{_MOIS[m.group(2)]:02d}-{jour:02d}")
    uniques = list(dict.fromkeys(trouvees))
    valides = []
    import datetime as dt

    for d in uniques:
        try:
            dt.date.fromisoformat(d)
        except ValueError:
            continue
        valides.append(d)
    return valides[:5]


def faits(objet: str, corps: str, expediteur: str) -> dict[str, Any]:
    """Faits minimaux pour l'événement d'aiguillage."""
    texte = f"{objet}\n{corps}"
    jetons = jetons_reference(texte)
    return {
        "jetons_reference": jetons,
        "references_po": references_po(jetons),
        "lignes": lignes_commande(corps),
        "etat_annonce": etat_annonce(texte),
        "dates_annoncees": dates_annoncees(texte),
        "expediteur_empreinte": empreinte_expediteur(expediteur),
    }
