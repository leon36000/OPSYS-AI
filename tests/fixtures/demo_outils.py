"""Outils d'un département fictif pour tester le socle OPSYS sans dépendre du métier réel."""

from __future__ import annotations

from decimal import Decimal

from opsys.outils import Autonomie, Outil

JOURNAL: list[dict] = []


def additionner(a: float, b: float) -> dict:
    return {"somme": Decimal(str(a)) + Decimal(str(b))}


def refuser_si_negatif(valeur: int) -> dict:
    if valeur < 0:
        raise ValueError("valeur négative refusée")
    return {"valeur": valeur}


def envoyer_message(destinataire: str, texte: str) -> dict:
    JOURNAL.append({"a": destinataire, "texte": texte})
    return {"envoye": True, "a": destinataire}


def payer(montant: float) -> dict:
    JOURNAL.append({"paiement": montant})
    return {"paye": montant}


def gros_rapport(lignes: int) -> dict:
    return {"lignes": [f"ligne {i} " + "x" * 50 for i in range(lignes)]}


_NB = {"type": "number"}
OUTILS = (
    Outil("m9_additionner", "Additionne deux nombres.",
          {"type": "object", "properties": {"a": _NB, "b": _NB}, "required": ["a", "b"],
           "additionalProperties": False}, additionner),
    Outil("m9_refuser_si_negatif", "Refuse une valeur négative.",
          {"type": "object", "properties": {"valeur": {"type": "integer"}}, "required": ["valeur"]},
          refuser_si_negatif),
    Outil("m9_envoyer_message", "Envoie un message à un client.",
          {"type": "object", "properties": {"destinataire": {"type": "string"}, "texte": {"type": "string"}},
           "required": ["destinataire", "texte"]}, envoyer_message, Autonomie.T2),
    Outil("m9_payer", "Paie un fournisseur.",
          {"type": "object", "properties": {"montant": _NB}, "required": ["montant"]}, payer, Autonomie.T3),
    Outil("m9_gros_rapport", "Produit un long rapport.",
          {"type": "object", "properties": {"lignes": {"type": "integer"}}, "required": ["lignes"]},
          gros_rapport),
)
