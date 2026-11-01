"""Normalisation lexicale du français : accents repliés, mots vides retirés, radicaux légers. Module pur.

Le même traitement sert l'indexation (FTS5) et la requête : « Réglementations », « reglementation » et
« réglementation » deviennent le même terme. Le radical est volontairement léger (pluriels, féminin en -e) : un
racinisateur agressif confond des mots différents et rend les résultats inexplicables. Ce n'est PAS un lemmatiseur :
« acheter » et « achat » restent distincts, ce que la voie vectorielle (un vrai modèle d'embeddings) est censée
rattraper.
"""

from __future__ import annotations

import re
import unicodedata

_MOTS_VIDES = frozenset(
    ["a", "au", "aux", "avec", "ce", "ces", "cet", "cette", "dans", "de", "des", "du", "elle", "elles", "en", "et",
        "eux", "il", "ils", "je", "la", "le", "les", "leur", "leurs", "lui", "ma", "mais", "me", "meme", "memes",
            "mes", "moi", "mon", "ne", "ni", "nos", "notre", "nous", "on", "ou", "par", "pas", "pour", "qu", "que",
                "qui", "sa", "se", "ses", "si", "son", "sur", "ta", "te", "tes", "toi", "ton", "tu", "un", "une",
                    "vos", "votre", "vous", "c", "d", "j", "l", "m", "n", "s", "t", "y", "ete", "etes", "etre", "est",
                        "sont", "sera", "seront", "suis", "es", "sommes", "avoir", "ai", "as", "avons", "avez", "ont",
                            "aura", "auront", "comme", "donc", "dont", "alors", "ainsi", "aussi", "plus", "moins",
                                "tres", "tout", "tous", "toute", "toutes", "autre", "autres", "quel", "quelle",
                                    "quels", "quelles", "quand", "comment", "combien", "quoi", "ou", "peut",
                                        "peuvent", "doit", "doivent", "faut", "fait", "faire", "etc", "cela", "ceci",
                                            "celui", "celle", "ceux", "celles", "ici", "la-bas", "entre", "vers",
                                                "chez", "sans", "sous", "apres", "avant", "depuis", "pendant", "selon"]
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
TERMES_REQUETE_MAX = 32


def replier(texte: str) -> str:
    """Minuscules sans accents (NFKD, marques retirées) ; « œ » et « æ » développés."""
    texte = texte.replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae").replace("Æ", "ae")
    decompose = unicodedata.normalize("NFKD", texte.casefold())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _radical(mot: str) -> str:
    if len(mot) > 4 and mot.endswith("eaux"):
        mot = mot[:-1]  # « bureaux » -> « bureau » ; « tableaux » -> « tableau »
    elif len(mot) > 4 and mot.endswith("aux"):
        mot = mot[:-3] + "al"  # « normaux » -> « normal »
    elif len(mot) > 3 and mot[-1] in "sx":
        mot = mot[:-1]
    if len(mot) > 4 and mot.endswith("e"):
        mot = mot[:-1]
    return mot


def termes(texte: str) -> list[str]:
    """Termes normalisés dans l'ordre du texte (doublons conservés). Les chiffres sont des termes à part entière."""
    resultat: list[str] = []
    for mot in _NON_ALNUM.split(replier(texte)):
        if not mot or mot in _MOTS_VIDES:
            continue
        if len(mot) == 1 and not mot.isdigit():
            continue
        resultat.append(_radical(mot))
    return resultat


def termes_uniques(texte: str, *, maximum: int = TERMES_REQUETE_MAX) -> list[str]:
    """Termes distincts dans l'ordre de première apparition, bornés."""
    vus: dict[str, None] = {}
    for terme in termes(texte):
        vus.setdefault(terme, None)
        if len(vus) >= maximum:
            break
    return list(vus)


def requete_fts(termes_requete: list[str]) -> str:
    """Expression FTS5 « OU » de termes entre guillemets. Les termes ne contiennent que [a-z0-9] : aucune syntaxe FTS5
    (NEAR, *, ^, parenthèses, guillemets) ne peut venir de l'utilisateur."""
    sains = [t for t in termes_requete if re.fullmatch(r"[a-z0-9]{1,64}", t)]
    return " OR ".join(f'"{t}"' for t in sains)
