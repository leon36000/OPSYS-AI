"""Étape « classement » : genre du document par RÈGLES déterministes (aucun modèle).

- Tableau (CSV, `.xlsx`) : `courriel_contacts` si la première ligne est la `MAGIE` du document de correspondants des
  connecteurs courriel (`contacts_courriel`) ; sinon `liste_clients` si un en-tête de liste de clients est reconnu
  (`m2_revenue_crm.
  clients_importes.reperer_entete`), sinon `inconnu`.
- Texte : le PREMIER mot-clé de genre rencontré dans les `_LIGNES_TITRE` premières lignes non vides (le titre) décide :
  facture (« facture », « invoice »), soumission (« soumission », « estimation », « devis », « quote »), contrat
  (« contrat », « entente », « contract »). Rien dans le titre : `inconnu` (jamais deviné du corps du texte).

Le sens d'une facture (fournisseur ou client) ne se décide pas ici : il dépend des numéros et des noms extraits,
comparés à l'identité fiscale de l'entreprise, à l'étape de validation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

CLASSES = ("facture", "soumission", "contrat", "liste_clients", "courriel_contacts", "inconnu")
_LIGNES_TITRE = 5
_MOTS = {
    "facture": "facture", "invoice": "facture",
    "soumission": "soumission", "estimation": "soumission", "devis": "soumission", "quote": "soumission",
    "contrat": "contrat", "entente": "contrat", "contract": "contrat",
}


def _mots(texte: str) -> list[str]:
    simple = "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c)).casefold()
    return re.findall(r"[a-z]+", simple)


def classer(resultat_texte: dict[str, Any]) -> dict[str, Any]:
    """`{"classe", "regle"}` : la classe et la règle qui l'a donnée."""
    if resultat_texte["genre"] == "tableau":
        from m2_revenue_crm import clients_importes

        from . import contacts_courriel

        if contacts_courriel.est_document(resultat_texte["candidats"]):
            return {"classe": "courriel_contacts", "regle": f"première ligne « {contacts_courriel.MAGIE} » "
                                                            "(correspondants d'une boîte courriel)"}

        for candidat in resultat_texte["candidats"]:
            trouve = clients_importes.reperer_entete(candidat["lignes"])
            if trouve is not None:
                return {"classe": "liste_clients", "regle": f"en-tête de liste de clients à la ligne {trouve[0] + 1} "
                                                            f"(colonnes {sorted(trouve[1])})"}
        return {"classe": "inconnu", "regle": "tableau sans en-tête de liste de clients reconnu"}
    lignes = [ligne for page in resultat_texte["pages"] for ligne in page["texte"].split("\n") if ligne.strip()]
    for numero, ligne in enumerate(lignes[:_LIGNES_TITRE], 1):
        for mot in _mots(ligne):
            if mot in _MOTS:
                return {"classe": _MOTS[mot], "regle": f"mot-clé « {mot} » à la ligne {numero} du titre"}
    return {"classe": "inconnu", "regle": f"aucun mot-clé de genre dans les {_LIGNES_TITRE} premières lignes"}


__all__ = ["CLASSES", "classer"]
