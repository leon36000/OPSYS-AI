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
  - Si contenu_brut est None ou non-str, retourne ("", True).
  - Couvre les contournements par infinitif/impératif/participe (FR + EN).
"""

import re

# ---------------------------------------------------------------------------
# Jeton de neutralisation
# ---------------------------------------------------------------------------
JETON_NON_FIABLE = "[CONTENU_NON_FIABLE]"

# ---------------------------------------------------------------------------
# Verbes de neutralisation FR (conformes à la spécification)
# ---------------------------------------------------------------------------
_VERBES_FR = [
    r"ignore",
    r"ignorez",
    r"ignorer",
    r"ignorant",
    r"oublie",
    r"oubliez",
    r"oublier",
    r"laissez?\ tomber",                     # laisse / laissez tomber
    r"ne\ t(?:iens?|enez)\ pas\ compte",     # ne tiens / tenez pas compte
    r"fai(?:t(?:es)?|s)\ abstraction",       # fais / fait / faites abstraction
]

# ---------------------------------------------------------------------------
# Verbes de neutralisation EN (conformes à la spécification)
# ---------------------------------------------------------------------------
_VERBES_EN = [
    r"ignore",
    r"disregard",
    r"forget",
    r"override",
    r"bypass",
    r"skip",
]

# ---------------------------------------------------------------------------
# Cibles communes (FR + EN)
# Correctif R2 : retrait de previous/précédent qui sont des MODIFICATEURS
# et non des cibles autonomes. Les cibles réelles subsistent.
# ---------------------------------------------------------------------------
_CIBLES = [
    r"instructions?",
    r"consignes?",
    r"directives?",
    r"r[èe]gles?",
    r"rules?",
    r"prompts?",
    r"syst[èe]mes?",
]

# ---------------------------------------------------------------------------
# Mots intercalaires : toute séquence (hors saut de ligne) ≤ 40 caractères
# ---------------------------------------------------------------------------
_INTER = r".{0,40}?"

# ---------------------------------------------------------------------------
# Construction des patterns combinés verbe + inter + cible
# ---------------------------------------------------------------------------

def _build_vt_pattern(verbes, cibles, inter):
    v = "(?:" + "|".join(verbes) + ")"
    c = "(?:" + "|".join(cibles) + ")"
    return re.compile(v + inter + c, re.IGNORECASE)

_PATTERN_NEUTRALISATION_FR = _build_vt_pattern(_VERBES_FR, _CIBLES, _INTER)
_PATTERN_NEUTRALISATION_EN = _build_vt_pattern(_VERBES_EN, _CIBLES, _INTER)

# Formulations polies FR (gardées pour robustesse)
_VEUILLEZ_PATTERN = re.compile(
    r"veuillez\s+" + "(?:" + "|".join(_VERBES_FR) + ")" + _INTER + "(?:" + "|".join(_CIBLES) + ")",
    re.IGNORECASE,
)

_DEMANDE_PATTERN = re.compile(
    r"(?:je\s+vous\s+demande\s+(?:de\s+)?|pri[èe]re\s+de\s+)"
    + "(?:" + "|".join(_VERBES_FR) + ")" + _INTER + "(?:" + "|".join(_CIBLES) + ")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Patterns additionnels (non verbe-cible)
# ---------------------------------------------------------------------------

# 1. Préfixes de rôle (system:, assistant:, user:)
_ROLE_PREFIX_PATTERN = re.compile(
    r"(?<!\w)(system|assistant|user)\s*:",
    re.IGNORECASE,
)

# 2. Balises XML/pseudo-XML inattendues
_XML_TAG_PATTERN = re.compile(
    r"</?(?:system|assistant|user|prompt|instruction|rule)(?:\s[^>]*)?>",
    re.IGNORECASE,
)

# 3. Templates double-accolade {{ ... }}
_TEMPLATE_PATTERN = re.compile(r"\{\{")

# 4. Balises [INST] / [/INST]
_INST_TAG_PATTERN = re.compile(r"\[/?INST\]", re.IGNORECASE)

# 5. Caractères de contrôle non imprimables (< 0x20, hors espace/tab/LF/CR)
#    et zero-width Unicode
_CONTROL_CHARS_PATTERN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"
    r"|[\u200b\u200c\u200d\u2060\ufeff\u00ad]",
)


# ---------------------------------------------------------------------------
# Moteurs de remplacement
# ---------------------------------------------------------------------------

def _neutraliser_pattern(texte: str, pattern: re.Pattern) -> tuple[str, bool]:
    """
    Remplace toutes les occurrences du pattern par JETON_NON_FIABLE.
    Retourne (texte_modifie, trouvé).
    """
    nouveau, n = pattern.subn(JETON_NON_FIABLE, texte)
    return nouveau, n > 0


def _neutraliser_zero_width(texte: str) -> tuple[str, bool]:
    """
    Remplace les lignes contenant des caractères de contrôle/zero-width
    par JETON_NON_FIABLE sur la ligne entière.
    """
    lignes = texte.splitlines(keepends=True)
    modifie = False
    resultat = []
    for ligne in lignes:
        if _CONTROL_CHARS_PATTERN.search(ligne):
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
        - Si contenu_brut est None ou non-str, retourne ("", True).
        - Ne bloque PAS un texte métier contenant le mot « instructions »
          sans verbe de neutralisation (ex. « J'ai suivi vos instructions »).
    """
    # Robustesse : entrée non conforme
    if contenu_brut is None or not isinstance(contenu_brut, str):
        return "", True

    if not contenu_brut:
        return contenu_brut, True

    texte = contenu_brut
    sain = True

    # Passe 1 — Caractères de contrôle et zero-width
    # (doit précéder les patterns textuels car ils peuvent dissimuler des marqueurs)
    texte, trouve = _neutraliser_zero_width(texte)
    if trouve:
        sain = False

    # Passe 2 — Neutralisation verbe-cible FR
    texte, trouve = _neutraliser_pattern(texte, _PATTERN_NEUTRALISATION_FR)
    if trouve:
        sain = False

    # Passe 3 — Neutralisation verbe-cible EN
    texte, trouve = _neutraliser_pattern(texte, _PATTERN_NEUTRALISATION_EN)
    if trouve:
        sain = False

    # Passe 4 — Formulations polies FR
    texte, trouve = _neutraliser_pattern(texte, _VEUILLEZ_PATTERN)
    if trouve:
        sain = False

    texte, trouve = _neutraliser_pattern(texte, _DEMANDE_PATTERN)
    if trouve:
        sain = False

    # Passe 5 — Préfixes de rôle (system:, assistant:, user:)
    texte, trouve = _neutraliser_pattern(texte, _ROLE_PREFIX_PATTERN)
    if trouve:
        sain = False

    # Passe 6 — Balises XML inattendues
    texte, trouve = _neutraliser_pattern(texte, _XML_TAG_PATTERN)
    if trouve:
        sain = False

    # Passe 7 — Templates double-accolade
    texte, trouve = _neutraliser_pattern(texte, _TEMPLATE_PATTERN)
    if trouve:
        sain = False

    # Passe 8 — Balises [INST] / [/INST]
    texte, trouve = _neutraliser_pattern(texte, _INST_TAG_PATTERN)
    if trouve:
        sain = False

    return texte, sain
