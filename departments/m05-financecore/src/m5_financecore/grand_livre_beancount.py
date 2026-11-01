"""Export texte du grand livre M5 au format Beancount (tranche 1), sans dépendre de beancount.

Module pur : aucun import d'`opsys`, aucune horloge. `exporter_beancount` rend le TEXTE d'un fichier `.beancount` :
une directive `open` par compte mouvementé (datée de la première écriture qui l'utilise), puis une transaction
par écriture DÉFINITIVE, dans l'ordre (date, numéro), débits positifs et crédits négatifs en CAD : chaque transaction
somme à zéro, comme l'écriture dont elle vient. Les brouillons ne sont jamais exportés.
`ecrire_fichier_beancount` écrit ce texte au chemin donné (UTF-8).

C'est la base de la contre-vérification nocturne future : un processus séparé (beancount réel, `bean-check`) relira
ce fichier pour recompter les soldes indépendamment de ce code. Ce module ne l'exécute pas et n'en prouve rien : seuls
la forme et l'équilibre du texte sont testés ici.

Noms de comptes : racine Beancount par type (`Assets`, `Liabilities`, `Equity`, `Income`, `Expenses`), puis
`C<numéro>-<Nom-sans-accents>` (lettres et chiffres ASCII, tirets), pour rester valide en Beancount v2 et v3.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

__all__ = ["exporter_beancount", "ecrire_fichier_beancount", "nom_compte_beancount"]

_RACINES = {
    "actif": "Assets",
    "passif": "Liabilities",
    "capitaux_propres": "Equity",
    "produits": "Income",
    "charges": "Expenses",
}
_PREMIER_CHIFFRE = {"1": "actif", "2": "passif", "3": "capitaux_propres", "4": "produits"}
_CENT = Decimal("0.01")
_MOTS = re.compile(r"[A-Za-z0-9]+")


def _type_du_numero(numero: str) -> str:
    return _PREMIER_CHIFFRE.get(numero[:1], "charges")


def nom_compte_beancount(numero: str, fiche: Mapping[str, Any] | None) -> str:
    """`Assets:C1010-Encaisse-Compte-Bancaire-Principal` : racine du type, numéro, nom replié en ASCII."""
    type_compte = fiche["type"] if fiche else _type_du_numero(numero)
    nom = fiche["nom"] if fiche else "Hors-plan"
    replie = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii")
    mots = [mot.capitalize() for mot in _MOTS.findall(replie)][:6]
    suffixe = "-".join(mots) if mots else "Compte"
    return f"{_RACINES[type_compte]}:C{numero}-{suffixe}"


def _chaine(texte: str) -> str:
    return '"' + texte.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _montant(valeur: Decimal) -> str:
    return str(valeur.quantize(_CENT, rounding=ROUND_HALF_UP))


def exporter_beancount(etat: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    """Le texte Beancount des écritures DÉFINITIVES de `etat` (`grand_livre.etat_grand_livre`), sous `plan`."""
    if etat["anomalies"]:
        raise ValueError("grand livre anormal : export refusé (" + "; ".join(etat["anomalies"][:3]) + ")")
    definitives = sorted(
        (e for e in etat["ecritures"].values() if e["statut"] == "DEFINITIVE"),
        key=lambda e: (e["date_effet"], e["numero"]),
    )
    ouvertures: dict[str, str] = {}
    for ecriture in definitives:
        for ligne in ecriture["lignes"]:
            ouvertures.setdefault(ligne["compte"], ecriture["date_effet"])
    noms = {numero: nom_compte_beancount(numero, plan["comptes"].get(numero)) for numero in ouvertures}
    sortie = [
        "; Grand livre OPSYS-AI M5 — export généré, ne pas modifier à la main.",
        f"; Plan comptable {plan['plan_id']} version {plan['version_effective']}.",
        "; À valider auprès d'un comptable (CPA) / professionnel qualifié.",
        'option "operating_currency" "CAD"',
        "",
    ]
    for numero in sorted(ouvertures, key=lambda n: (ouvertures[n], n)):
        sortie.append(f"{ouvertures[numero]} open {noms[numero]} CAD")
    for ecriture in definitives:
        sortie.append("")
        sortie.append(f"{ecriture['date_effet']} * {_chaine(ecriture['libelle'])}")
        sortie.append(f"  ecriture_id: {_chaine(ecriture['ecriture_id'])}")
        sortie.append(f"  numero: {_chaine(str(ecriture['numero']))}")
        sortie.append(f"  piece: {_chaine(ecriture['piece']['type'] + ':' + ecriture['piece']['reference'])}")
        if ecriture["contre_passe"] is not None:
            sortie.append(f"  contre_passe: {_chaine(ecriture['contre_passe'])}")
        for ligne in ecriture["lignes"]:
            montant = ligne["debit"] if ligne["debit"] > 0 else -ligne["credit"]
            sortie.append(f"  {noms[ligne['compte']]}  {_montant(montant)} CAD")
    return "\n".join(sortie) + "\n"


def ecrire_fichier_beancount(chemin: str | Path, etat: Mapping[str, Any], plan: Mapping[str, Any]) -> Path:
    """Écrit l'export au `chemin` (UTF-8) et rend ce chemin."""
    cible = Path(chemin)
    cible.write_text(exporter_beancount(etat, plan), encoding="utf-8")
    return cible
