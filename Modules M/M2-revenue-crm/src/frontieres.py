# M2-S003 — Détection des champs interdits : frontières de vérité
# Aucune logique réseau, aucune horloge.
import re

# ── motifs monétaires ──────────────────────────────────────────────
# Justification de la branche mot-clé sans devise :
#   Un mot-clé monétaire suivi d'un nombre est une divulgation de prix,
#   même sans symbole (ex. « devis 4500 »). Ne pas le détecter créerait
#   un faux négatif indélébile (registre append-only). Un faux positif
#   (ex. identifiant opaque « conv-devis-4500 ») est corrigible en amont,
#   donc l’asymétrie impose de signaler.
#
# Deux familles de devises, aux bornes distinctes :
#   - les symboles (€, $) ne sont pas des caractères de mot : un \b
#     après « € » ou « $ » ne matche jamais, ils vont donc sans borne ;
#   - les devises alphabétiques (EUR, dollars, …) sont bornées par \b
#     des deux côtés pour interdire les sous-chaînes.
# Le nombre accepte un chiffre seul (« 9 € ») comme les groupements
# de milliers (« 4 500 ») et les décimales (« 4 500,00 »).
_NOMBRE = r"\d(?:[\d\s  ,.]*\d)?"
_SYMBOLE_MONETAIRE = r"[€\$]"
_DEVISE_ALPHABETIQUE = r"\b(?:EUR|USD|CAD|dollars?|euros?)\b"
_DEVISE = rf"(?:{_SYMBOLE_MONETAIRE}|{_DEVISE_ALPHABETIQUE})"

# Montant explicite : nombre suivi d'une devise.
_MONTANT = rf"{_NOMBRE}\s*{_DEVISE}"

# Mot-clé monétaire suivi d'un nombre, sans exiger de devise.
# Mots-clés retenus : devis, tarif, prix, coût, montant, budget.
# Le .*? autorise des espaces/punctuation entre le mot-clé et le nombre.
_MONTANT_AVEC_MOTCLE = (
    r"\b(?:devis|tarif|prix|coût|montant|budget)\b"
    r".*?"
    r"\d(?:[\d\s  ,.]*\d)?"
)

MOTIF_MONETAIRE = re.compile(
    rf"(?:{_MONTANT}|{_MONTANT_AVEC_MOTCLE})",
    re.IGNORECASE,
)

# ── motifs date + terme d'exécution ────────────────────────────────
# Une date seule ne déclenche pas. On exige la présence simultanée
# d'une expression temporelle (date relative ou absolue) ET d'un
# terme d'exécution (travaux, chantier, livraison, …).
# Extension pour les jours de semaine nus (ex. « lundi. ») : un jour
# de semaine isolé, même suivi d'une ponctuation ou en fin de chaîne,
# est désormais reconnu comme expression temporelle.
_DATE = (
    r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"                     # jj/mm/aa
    r"|\d{4}-\d{2}-\d{2}"                               # aaaa-mm-jj
    r"|\b(?:demain|après-demain)\b"
    r"|\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b"   # jour seul (y compris . , ; etc.)
    r"|\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+prochain\b"
    r"|\bdans\s+\d+\s+jours?\b"
    r"|\ble\s+\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)?"
    r"|\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\b"
)
_EXECUTION = (
    r"\b(?:travaux|chantier|intervention|livraison|pose|finir|terminer|démarrer|commencer)\b"
    r"|\b(?:finis?|terminé(?:e|es)?|commencé(?:e|es)?|démarré(?:e|es)?)\b"
)

MOTIF_DATE = re.compile(_DATE, re.IGNORECASE)
MOTIF_EXECUTION = re.compile(_EXECUTION, re.IGNORECASE)

# Tuples publics attendus par la spec.
MOTIFS_MONETAIRES = (MOTIF_MONETAIRE,)
MOTIFS_DATE_EXECUTION = (MOTIF_DATE, MOTIF_EXECUTION)


def inspecter_valeur(texte: str) -> tuple[bool, str]:
    """Inspecte une valeur textuelle à la recherche de frontières violées.

    Retourne (True, "") si la valeur est saine.
    Sinon (False, raison) où la raison décrit la famille détectée et un extrait.
    """
    # 1. Présence d’un montant (nombre + devise ou mot-clé déclencheur).
    for motif in MOTIFS_MONETAIRES:
        m = motif.search(texte)
        if m:
            return False, f"montant_detecte: {m.group()!r}"

    # 2. Cooccurrence date + terme d'exécution dans le même texte.
    date_match = MOTIF_DATE.search(texte)
    exec_match = MOTIF_EXECUTION.search(texte)
    if date_match and exec_match:
        return False, (
            f"date_execution: {date_match.group()!r} avec terme execution {exec_match.group()!r}"
        )

    return True, ""


def inspecter_contrat(contrat: dict) -> tuple[bool, str]:
    """Parcourt récursivement toutes les str du contrat (y compris contact)
    et retourne au premier problème trouvé. Ne modifie rien.
    """
    # Collecte toutes les chaînes de caractères dans le contrat.
    def _extraire_textes(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from _extraire_textes(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                yield from _extraire_textes(v)

    for texte in _extraire_textes(contrat):
        ok, raison = inspecter_valeur(texte)
        if not ok:
            return False, raison
    return True, ""
