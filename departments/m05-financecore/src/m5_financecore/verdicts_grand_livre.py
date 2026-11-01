"""Catalogue fermé des refus du grand livre (tranche 1), à part de `validation.CODES_M5_LIST`.

Pourquoi un catalogue à part : `validation.py` fait partie du code de paie épinglé par empreinte
(`contracts/admission_paie_preparatoire.v1.json`, `generation.fichiers`) ; le modifier pour le grand livre ferait tomber
le diagnostic d'admission de la paie. Même forme de verdict que `validation.construire_verdict` (`{code, detail}`),
même fermeture : un code hors catalogue lève. Module pur.
"""

from __future__ import annotations

__all__ = ["CODES_GL", "construire_verdict"]

CODES_GL = [
    "REJ-GL-PLAN-INVALIDE",
    "REJ-GL-COMPTE-INCONNU",
    "REJ-GL-COMPTE-INACTIF",
    "REJ-GL-MONTANT-INVALIDE",
    "REJ-GL-LIGNES-INSUFFISANTES",
    "REJ-GL-LIGNE-INVALIDE",
    "REJ-GL-ECRITURE-DESEQUILIBREE",
    "REJ-GL-CHAMP-INVALIDE",
    "REJ-GL-DATE-INVALIDE",
    "REJ-GL-PERIODE-INVALIDE",
    "REJ-GL-PERIODE-CLOSE",
    "REJ-GL-PERIODE-DEJA-CLOSE",
    "REJ-GL-PIECE-INVALIDE",
    "REJ-GL-PIECE-INTROUVABLE",
    "REJ-GL-PIECE-CONFLIT",
    "REJ-GL-ECRITURE-INTROUVABLE",
    "REJ-GL-ECRITURE-DEJA-VALIDEE",
    "REJ-GL-ECRITURE-NON-DEFINITIVE",
    "REJ-GL-DEJA-CONTRE-PASSEE",
    "REJ-GL-CONTRE-PASSATION-INVALIDE",
    "REJ-GL-MOTIF-REQUIS",
    "REJ-GL-CHAINE-INVALIDE",
    "REJ-GL-SOURCE-ILLISIBLE",
    "REJ-GL-HUMAIN-REQUIS",
    "REJ-GL-LIMITE-INVALIDE",
    "REJ-GL-STOCKAGE-NON-DURABLE",
]
_CODES = frozenset(CODES_GL)


class CodeGrandLivreInconnu(ValueError):
    pass


def construire_verdict(code: str, detail: str = "") -> dict[str, str]:
    if code not in _CODES:
        raise CodeGrandLivreInconnu(f"code de refus du grand livre inconnu : {code!r}")
    return {"code": code, "detail": detail}
