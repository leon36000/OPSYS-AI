import re
from typing import Set


def _load_stopwords(path: str) -> Set[str]:
    """Charge un ensemble de stopwords depuis un fichier (un mot par ligne).
    Retourne un set vide si le chemin est vide ou le fichier inaccessible."""
    if not path:
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            lines = [line.strip() for line in f]
    except Exception:
        return set()
    return {line.lower() for line in lines if line}


def calculate_coverage(texte_a: str, texte_b: str, stopwords_path: str) -> float:
    """Jaccard sur les tokens significatifs.
    texte_a et texte_b sont des chaînes de texte brut (pas de HTML).
    stopwords_path est un chemin vers un fichier de stopwords (un mot par ligne)."""
    stopwords = _load_stopwords(stopwords_path)
    pattern = re.compile(r"[a-zàâçéèêëîïôûùüÿœæ]+")
    tokens_a = set()
    tokens_b = set()
    for w in pattern.findall(texte_a.lower()):
        if len(w) >= 3 and w not in stopwords:
            tokens_a.add(w)
    for w in pattern.findall(texte_b.lower()):
        if len(w) >= 3 and w not in stopwords:
            tokens_b.add(w)
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / len(union)
