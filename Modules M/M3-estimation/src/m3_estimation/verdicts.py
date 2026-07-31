"""Catalogue des identifiants de verdicts stables du module M3.

Patron copié-adapté des catalogues voisins (décision ratifiée : copie, jamais
import — décision #109). Le catalogue est FERMÉ : ``construire_verdict``
refuse tout code qui n'y figure pas en levant ``CodeVerdictInconnu``.
"""

__all__ = [
    "CODES_M3_LIST",
    "CODES_M3",
    "CodeVerdictInconnu",
    "est_verdict",
    "construire_verdict",
]


class CodeVerdictInconnu(Exception):
    """Levée par construire_verdict lorsque le code demandé ne figure pas dans
    le catalogue M3. Hérite d'Exception pour rester attrapable par les tests
    qui font pytest.raises(Exception).
    """


# Identifiants stables du catalogue M3 — liste FERMÉE, ordre épinglé.
CODES_M3_LIST = [
    "REJ-CLE-INTERDITE",
    "REJ-CONTRAT-INVALIDE",
    "REJ-MARQUEUR-INVALIDE",
    # La readiness est constatée par M3, jamais re-déduite :
    # seul le registre hash-chaîné de M2 fait foi sur la traversée réelle de la gate
    # NOTE D'ANCRE : la phrase d'ancre ci-dessus est une ANCRE comparée mot
    # pour mot par le gate de cohérence du cadrage, et tout reformatage qui
    # la coupe, la reformule ou la répartit sur plusieurs lignes la casse.
    "REJ-READINESS-NON-CONSTATEE",
    "REJ-LEAD-ID-DISCORDANT",
    "REJ-PHOTOS-INVALIDES",
    "REJ-PROFONDEUR-EXCESSIVE",
]
CODES_M3 = set(CODES_M3_LIST)


def est_verdict(code):
    """Retourne True si le code fait partie du catalogue M3."""
    return code in CODES_M3


def construire_verdict(code, detail=""):
    """Construit un verdict dictionnaire si le code est reconnu.

    Lève CodeVerdictInconnu dans le cas contraire.
    """
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict invalide : {code!r}")
    return {"code": code, "detail": detail}
