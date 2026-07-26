"""
M1-S005 — Filtre de provenance anti-injection (R-015).

API publique :
    filtrer(contenu_brut: str) -> tuple[str, bool]

Retourne (contenu_filtre, sain) :
  - contenu_filtre : chaîne avec les segments suspects remplacés par
    le jeton [CONTENU_NON_FIABLE].
  - sain : True si aucun marqueur d'injection n'a été détecté, False sinon.

Garanties :
  - Zéro réseau (pas d'import urllib/socket/http/requests).
  - Zéro horloge interne (pas de datetime.now() ni time.time()).
  - Déterministe : même entrée → même sortie.
  - Le contenu_brut original n'est JAMAIS retourné tel quel quand un
    marqueur est présent (étanchéité R-015).
  - Les contenus légitimes traversent sans modification (zéro faux positif
    sur les fixtures legitimes.v1.yaml).
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# Jeton de neutralisation
# ---------------------------------------------------------------------------
JETON_NON_FIABLE = "[CONTENU_NON_FIABLE]"

# ---------------------------------------------------------------------------
# Patterns de détection — marqueurs d'injection
# ---------------------------------------------------------------------------

# 1. Variantes de "ignore previous instructions" (EN/FR, avec/sans accents,
#    insensible à la casse).
_IGNORE_PATTERNS = [
    # Anglais
    re.compile(
        r"ignore\s+(?:all\s+)?previous\s+instructions?",
        re.IGNORECASE,
    ),
    # Français — avec accents (é, è) et sans
    re.compile(
        r"ignor(?:ez|ons|e|ons)?\s+les?\s+instructions?\s+pr[eé]c[eé]dentes?",
        re.IGNORECASE,
    ),
]

# 2. Préfixes de rôle (system:, assistant:, user:) — insensibles à la casse,
#    peuvent être précédés de caractères non imprimables ou d'espaces.
_ROLE_PREFIX_PATTERN = re.compile(
    r"(?:^|(?<=\n)|(?<=\r)|\b)[ \t]*(system|assistant|user)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# 3. Balises XML/pseudo-XML inattendues : <system>, <assistant>, <user>,
#    <prompt>, et leurs variantes avec attributs ou fermeture.
_XML_TAG_PATTERN = re.compile(
    r"</?(?:system|assistant|user|prompt)(?:\s[^>]*)?>",
    re.IGNORECASE,
)

# 4. Templates double-accolade : {{ ... }}
_TEMPLATE_PATTERN = re.compile(r"\{\{")

# 5. Balises [INST] / [/INST]
_INST_TAG_PATTERN = re.compile(r"\[/?INST\]", re.IGNORECASE)

# 6. Caractères de contrôle non imprimables (< 0x20, hors espace/tab/LF/CR)
#    et caractères zero-width Unicode.
_CONTROL_CHARS_PATTERN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
    r"|[\u200b\u200c\u200d\u2060\ufeff\u00ad]",
)


# ---------------------------------------------------------------------------
# Moteurs de remplacement — ligne par ligne ou span par span
# ---------------------------------------------------------------------------

def _contient_zero_width(texte: str) -> bool:
    """Détecte la présence de caractères zero-width ou de contrôle."""
    return bool(_CONTROL_CHARS_PATTERN.search(texte))


def _neutraliser_pattern(texte: str, pattern: re.Pattern) -> tuple[str, bool]:
    """
    Remplace toutes les occurrences du pattern par JETON_NON_FIABLE.
    Retourne (texte_modifie, trouvé).
    """
    nouveau, n = pattern.subn(JETON_NON_FIABLE, texte)
    return nouveau, n > 0


def _neutraliser_zero_width(texte: str) -> tuple[str, bool]:
    """
    Remplace les séquences contenant des caractères de contrôle/zero-width
    par JETON_NON_FIABLE sur la ligne entière porteuse.

    Stratégie : on neutralise ligne par ligne — toute ligne contenant au
    moins un caractère de contrôle est remplacée par JETON_NON_FIABLE.
    """
    lignes = texte.splitlines(keepends=True)
    modifie = False
    resultat = []
    for ligne in lignes:
        if _CONTROL_CHARS_PATTERN.search(ligne):
            # Supprimer les caractères suspects et insérer le jeton
            ligne_propre = _CONTROL_CHARS_PATTERN.sub("", ligne)
            resultat.append(JETON_NON_FIABLE + ligne_propre)
            modifie = True
        else:
            resultat.append(ligne)
    return "".join(resultat), modifie


# ---------------------------------------------------------------------------
# Fonction publique
# ---------------------------------------------------------------------------

def filtrer(contenu_brut: str) -> tuple[str, bool]:
    """
    Filtre anti-injection de provenance (R-015).

    Paramètre :
        contenu_brut : chaîne brute provenant d'une source externe non fiable
                       (corps de courriel, transcription voicemail, champ libre).

    Retourne :
        (contenu_filtre, sain)
        - contenu_filtre : chaîne neutralisée, sans marqueur d'injection.
        - sain : True si aucun marqueur n'a été détecté.

    Invariants :
        - Si sain is False, contenu_filtre != contenu_brut et les marqueurs
          d'injection ne sont pas présents en clair dans contenu_filtre.
        - Si sain is True, contenu_filtre == contenu_brut.
        - Déterministe, sans réseau, sans horloge.
    """
    if not contenu_brut:
        return contenu_brut, True

    texte = contenu_brut
    sain = True

    # Passe 1 — Caractères de contrôle et zero-width (doivent être détectés
    # avant les patterns textuels car ils peuvent dissimuler des marqueurs)
    texte, trouve = _neutraliser_zero_width(texte)
    if trouve:
        sain = False

    # Passe 2 — Variantes "ignore previous instructions"
    for pattern in _IGNORE_PATTERNS:
        texte, trouve = _neutraliser_pattern(texte, pattern)
        if trouve:
            sain = False

    # Passe 3 — Préfixes de rôle (system:, assistant:, user:)
    texte, trouve = _neutraliser_pattern(texte, _ROLE_PREFIX_PATTERN)
    if trouve:
        sain = False

    # Passe 4 — Balises XML inattendues
    texte, trouve = _neutraliser_pattern(texte, _XML_TAG_PATTERN)
    if trouve:
        sain = False

    # Passe 5 — Templates double-accolade
    texte, trouve = _neutraliser_pattern(texte, _TEMPLATE_PATTERN)
    if trouve:
        sain = False

    # Passe 6 — Balises [INST] / [/INST]
    texte, trouve = _neutraliser_pattern(texte, _INST_TAG_PATTERN)
    if trouve:
        sain = False

    return texte, sain
