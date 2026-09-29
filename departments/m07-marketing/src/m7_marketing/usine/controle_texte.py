"""Contrôle en code d'un texte destiné au public (PLAN T4.17, M7.3 : « contrôle de marque et de confidentialité »).

Doctrine (AGENTS.md « le code calcule, le LLM orchestre », DEFINITION-PRODUIT §7 M7 « Blocages : promesse non
vérifiable, garantie ou prix inventés, photo de client sans autorisation, adresse ou visage ou plaque
visibles, exagération ») :

  - Un texte est composé par le code (gabarits, `gabarits.py`) ou rédigé par le modèle (`textes` de
    `m7_proposer_contenus_chantier`). Dans les deux cas il passe ICI avant d'entrer dans la file : la source
    du texte ne change rien à ce qu'il a le droit de dire. Un contenu refusé n'existe pas (aucun
    enregistrement) ; le refus NOMME chaque règle violée et ce qu'il faut retirer.
  - Les règles sont des motifs, jamais un jugement : même texte, même verdict. Un texte propre est accepté,
    un texte douteux est refusé (fail-closed) — l'agent le récrit, ou le propriétaire l'écrit à la main.
  - M1 a son propre garde-fou (`m1_front_office.garde_fou`, prix, dates, engagements, aveux) pour des
    messages à un client. Il n'est pas importé ici (aucun import entre départements, décision #109) et ses
    familles ne sont pas celles d'un texte public : ici, adresse, nom du client, chiffres non sourcés,
    garantie non validée. Les deux se recoupent sur le prix et la promesse de date, avec des motifs écrits
    pour ce cas ; un module du socle qui les réunirait est une évolution possible (rapport de T4.17).

Limites documentées, jamais cachées :
  - Le nom du client n'est PAS dans le WCT (M4 ne le porte pas). Le contrôle reconnaît les FORMES qui
    désignent un client (civilité + nom, « la famille X », « chez X Y », « client : X », @mention) et les
    noms et identifiants qu'on lui fournit (`ContexteControle.noms_clients`, `identifiants`). Un prénom
    seul, sans civilité, dans une phrase ordinaire, n'est pas détectable : la revue du propriétaire (N3)
    reste la dernière barrière, et le texte du gabarit n'en contient jamais.
  - Un motif ne comprend pas le sens : « meilleur » est refusé même dans une phrase inoffensive. C'est le
    prix du fail-closed ; la règle est nommée, donc contournable par une phrase plus sobre.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from collections.abc import Iterable

REGLE_TEXTE_VIDE = "REJ-TEXTE-VIDE"
REGLE_LONGUEUR = "REJ-LONGUEUR"
REGLE_LIEN = "REJ-LIEN"
REGLE_ADRESSE = "REJ-ADRESSE"
REGLE_COORDONNEES = "REJ-COORDONNEES"
REGLE_NOM_CLIENT = "REJ-NOM-CLIENT"
REGLE_IDENTIFIANT_INTERNE = "REJ-IDENTIFIANT-INTERNE"
REGLE_PRIX = "REJ-PRIX"
REGLE_CHIFFRE = "REJ-CHIFFRE-NON-SOURCE"
REGLE_GARANTIE = "REJ-GARANTIE-NON-VALIDEE"
REGLE_DATE = "REJ-PROMESSE-DE-DATE"
REGLE_EXAGERATION = "REJ-EXAGERATION"

# Ce que chaque règle interdit, en une phrase : montré au modèle qui rédige (`m7_lire_matiere_chantier`)
# et repris dans le refus. L'ordre est celui de l'évaluation, donc celui des violations rendues.
LIBELLES_REGLES: dict[str, str] = {
    REGLE_TEXTE_VIDE: "le texte ne peut pas être vide",
    REGLE_LONGUEUR: "le texte respecte la longueur maximale de la plateforme",
    REGLE_LIEN: "aucun lien dans le texte (le lien de suivi est ajouté par le code)",
    REGLE_ADRESSE: "aucune adresse (numéro civique, rue nommée, code postal, coordonnées GPS)",
    REGLE_COORDONNEES: "aucun courriel ni numéro de téléphone",
    REGLE_NOM_CLIENT: "aucun nom de client (civilité + nom, famille, « chez X Y », @mention)",
    REGLE_IDENTIFIANT_INTERNE: "aucun identifiant interne (chantier, lead, devis, technicien)",
    REGLE_PRIX: "aucun prix, montant, tarif, rabais ni offre gratuite",
    REGLE_CHIFFRE: "aucun chiffre avec une unité (pieds, heures, ans, %) : les chiffres viennent d'un outil",
    REGLE_GARANTIE: "aucune garantie, sauf un énoncé validé par l'entreprise (profil de marque)",
    REGLE_DATE: "aucune date ni promesse de délai (demain, d'ici, dans N jours, avant le…)",
    REGLE_EXAGERATION: "aucune exagération non vérifiable (meilleur, numéro 1, imbattable, 100 %…)",
}

_EXTRAIT_MAX = 48
# Aucune plateforme n'accepte un tel texte (les plafonds vont de 900 à 2 000 caractères) : au-delà, le texte est
# refusé sans être lu par les motifs, pour qu'un texte démesuré ne puisse pas occuper le processus.
TEXTE_MAX_CONTROLE = 5000


@dataclasses.dataclass(frozen=True)
class Violation:
    """Une règle violée : son code stable, et ce qui l'a déclenchée."""

    regle: str
    detail: str

    def en_dict(self) -> dict[str, str]:
        return {"regle": self.regle, "detail": self.detail}


@dataclasses.dataclass(frozen=True)
class ContexteControle:
    """Ce que le contrôle sait de ce texte, tiré du profil de marque et du chantier, jamais de l'appelant.

    `garanties_validees` : énoncés de garantie approuvés par l'entreprise, recopiés tels quels (profil de
    marque). `noms_de_marque` : le nom commercial, qui peut contenir « garantie » ou « meilleur » sans que le
    texte en fasse une promesse. `noms_clients` : noms de personnes qui ne doivent jamais apparaître (aucune
    source ne les fournit aujourd'hui : le WCT n'en porte pas). `identifiants` : les identifiants internes du
    WCT (chantier, lead, devis, technicien). `longueur_max` : plafond de la plateforme, `None` pour ne pas en
    contrôler. Un nom ou un identifiant de moins de quatre caractères n'est jamais cherché : il se
    confondrait avec un mot courant.
    """

    garanties_validees: tuple[str, ...] = ()
    noms_de_marque: tuple[str, ...] = ()
    noms_clients: tuple[str, ...] = ()
    identifiants: tuple[str, ...] = ()
    longueur_max: int | None = None


def _plier(texte: str) -> str:
    """Forme de recherche : compatibilité Unicode (espaces insécables, exposants), sans accents, minuscules,
    apostrophes droites, espaces réduits. Les mots-clés y sont cherchés ; le texte lui-même n'est pas modifié."""
    normal = unicodedata.normalize("NFKC", texte).replace("’", "'").replace("‘", "'")
    sans_accents = "".join(c for c in unicodedata.normalize("NFD", normal) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sans_accents).casefold()


def _normal(texte: str) -> str:
    """Forme qui garde les majuscules et les accents (noms propres), espaces réduits."""
    normal = unicodedata.normalize("NFKC", texte).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", normal)


def _masquer(texte: str, morceaux: Iterable[str], *, plier: bool) -> str:
    """Remplace par une espace chaque morceau (nom de marque, énoncé validé) trouvé dans `texte`."""
    resultat = texte
    for morceau in morceaux:
        cherche = _plier(morceau) if plier else _normal(morceau)
        if cherche.strip():
            resultat = re.sub(re.escape(cherche), " ", resultat, flags=0 if plier else re.IGNORECASE)
    return resultat


def _extrait(texte: str) -> str:
    propre = texte.strip()
    return propre if len(propre) <= _EXTRAIT_MAX else propre[: _EXTRAIT_MAX - 1] + "…"


def _premier(motifs: Iterable[re.Pattern[str]], texte: str) -> re.Match[str] | None:
    for motif in motifs:
        trouve = motif.search(texte)
        if trouve is not None:
            return trouve
    return None


_TYPES_VOIE = (
    r"(?:rue|avenue|av|boulevard|boul|bd|chemin|ch|rang|route|rte|montee|place|impasse|croissant|allee|cote|carre|"
    r"terrasse|promenade|cercle|ruelle)"
)
_MOIS = r"(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)"
_JOURS = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"

# -- adresse (sur le texte plié) ------------------------------------------------------------------------------
_ADRESSES_PLIEES = (
    # « 1234 rue des Érables », « 12, boul. Taschereau », « 12 3e avenue »
    re.compile(rf"\b\d{{1,5}}[a-z]?(?:\s*,\s*|\s+)(?:\d{{1,3}}(?:e|re|ere|eme|ieme)\s+)?{_TYPES_VOIE}\b"),
    re.compile(r"\b[a-z]\d[a-z]\s?-?\d[a-z]\d\b"),  # code postal canadien
    re.compile(r"[-+]?\d{1,3}[.,]\d{4,}\s*[,;/ ]\s*[-+]?\d{1,3}[.,]\d{4,}"),  # coordonnées GPS
    re.compile(r"\b(?:app|apt|appartement|bureau|suite|unite|local)\.?\s*#?\s*\d+\b"),
)
# Une voie NOMMÉE, sans numéro, désigne déjà un lieu : cherchée sur le texte qui garde ses majuscules.
_VOIE_NOMMEE = re.compile(
    r"\b(?i:rue|avenue|boulevard|boul\.|chemin|rang|montée|côte|impasse|croissant|allée)\s+"
    r"(?:(?i:de la|de l'|du|des|de|d')\s*)?[A-ZÀ-ÖØ-Þ]"
)

# -- coordonnées et liens (texte plié) -----------------------------------------------------------------------
_COURRIEL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}")
_TELEPHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_LIEN = re.compile(r"https?://|\bwww\.|(?<![@\w-])[a-z0-9-]+\.(?:com|ca|org|net)\b")

# -- nom du client (texte normal : les majuscules comptent) ----------------------------------------------------
_MAJUSCULE = r"[A-ZÀ-ÖØ-Þ]"
_NOM = rf"{_MAJUSCULE}[\w'-]*"
_NOMS_CLIENT = (
    re.compile(rf"\b(?i:monsieur|madame|mademoiselle|mme|mlle|docteur|dre?|m\.)\s+{_NOM}"),
    re.compile(rf"\b(?i:la famille|famille)\s+{_NOM}"),
    re.compile(rf"\b(?i:chez)\s+{_NOM}(?:\s+{_NOM})?"),
    re.compile(rf"\b(?i:client(?:e)?s?|proprietaire|propriétaire)\s*:\s*{_MAJUSCULE}"),
    re.compile(r"(?<![\w.])@[\w.]{2,}"),
)

# -- prix (texte plié) --------------------------------------------------------------------------------------------
_PRIX = (
    # Le départ d'un nombre seulement (ni au milieu d'un chiffre ni d'un groupe « 4 500 ») et un quantificateur
    # possessif : le temps reste linéaire, même sur un texte fait uniquement de chiffres.
    re.compile(
        r"(?<!\d)(?<!\d )\d[\d ]*+(?:[.,]\d+)?\s*(?:\$|cad\b|dollars?\b|piastres?\b|€|euros?\b)"
    ),
    re.compile(r"[$€]\s*\d"),
    re.compile(
        r"\b(?:prix|tarif\w*|cout\w*|budget\w*|fourchette\w*|gratuit\w*|sans frais|rabais|escompte\w*|promo\w*|"
        r"soldes?|financement\w*|versements?|mensualit\w*|paiements?)\b"
    ),
)

# -- chiffres avec unité : jamais produits par un modèle (AGENTS.md), sauf sourcés par un outil ------------------
_CHIFFRE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|pi2|m2|pieds?\b|pi\b|pouces?\b|po\b|metres?\b|m\b|cm\b|mm\b|km\b|kg\b|lb\b|"
    r"livres?\b|litres?\b|heures?\b|h\b|jours?\b|semaines?\b|mois\b|ans?\b|annees?\b|minutes?\b|min\b)"
)

# -- garantie (texte plié, après masquage des énoncés validés et du nom de marque) -------------------------------
_GARANTIE = re.compile(
    r"\bgarant\w*|\ba vie\b|\bsatisfait ou rembours\w*|\brembours\w*|\bsans risque\b|\bzero risque\b|"
    r"\baucun risque\b|\bresultats? assures?\b"
)

# -- date et promesse de délai (texte plié) ----------------------------------------------------------------------
_DATES = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
    re.compile(rf"\b\d{{1,2}}(?:er)?\s+{_MOIS}\b"),
    re.compile(r"\ble \d{1,2}(?:er)?\b"),
    re.compile(rf"\ble\s+{_JOURS}\b"),
    re.compile(rf"\b{_JOURS}\s+(?:prochain|dernier)\b"),
    re.compile(r"\b(?:demain|apres-demain)\b"),
    re.compile(
        rf"\b(?:la semaine|le mois|l'an|l'annee|la fin de semaine|le week-end)\s+prochaine?\b|"
        rf"\bprochaine?s?\s+(?:semaine|mois|annee|fin de semaine|week-end|jour|{_JOURS})\b"
    ),
    re.compile(r"\bd'ici\b|\bau plus tard\b|\bavant le\b"),
    re.compile(r"\b(?:dans|sous)\s+(?:\d+|un|une|deux|trois|quatre|cinq|quelques)\s+(?:jours?|semaines?|mois|heures?|minutes?)\b"),
    re.compile(rf"\bdes\s+(?:{_JOURS}|maintenant|aujourd'hui)\b"),
)

# -- exagération (texte plié, après masquage du nom de marque) ---------------------------------------------------
_EXAGERATION = (
    re.compile(
        r"\bmeilleur\w*|\bnumero (?:1|un)\b|\bno\.? ?1\b|\bn° ?1\b|#\s?1\b|\bimbattable\w*|\bincomparable\w*|"
        r"\binegal\w*|\bsans equivalent\b|\bunique au quebec\b|\bleader\w*|\b100 ?%|\bparfait\w*|"
        r"\bsans faute\b|\binfaillible\w*|\birreprochable\w*|\bmoins cher\b|\ble plus bas\b|"
        r"\bla seule?\b|\ble seul\b"
    ),
)


def _adresse(plie: str, normal: str) -> Violation | None:
    trouve = _premier(_ADRESSES_PLIEES, plie) or _VOIE_NOMMEE.search(normal)
    if trouve is None:
        return None
    return Violation(REGLE_ADRESSE, f"adresse ou lieu précis : « {_extrait(trouve.group(0))} » ; retire-le")


def _coordonnees(plie: str) -> Violation | None:
    trouve = _premier((_COURRIEL, _TELEPHONE), plie)
    if trouve is None:
        return None
    return Violation(REGLE_COORDONNEES, f"courriel ou téléphone : « {_extrait(trouve.group(0))} » ; retire-le")


def _nom_client(normal_sans_marque: str, plie: str, noms_clients: Iterable[str]) -> Violation | None:
    trouve = _premier(_NOMS_CLIENT, normal_sans_marque)
    if trouve is not None:
        return Violation(REGLE_NOM_CLIENT, f"nom de client : « {_extrait(trouve.group(0))} » ; désigne « le client »")
    for nom in noms_clients:
        cherche = _plier(nom)
        if len(cherche) >= 4 and re.search(rf"(?<![a-z0-9]){re.escape(cherche)}(?![a-z0-9])", plie):
            return Violation(REGLE_NOM_CLIENT, "un nom fourni comme confidentiel apparaît dans le texte ; retire-le")
    return None


def _identifiant_interne(plie: str, identifiants: Iterable[str]) -> Violation | None:
    for identifiant in identifiants:
        cherche = _plier(identifiant)
        if len(cherche) >= 4 and cherche in plie:
            return Violation(REGLE_IDENTIFIANT_INTERNE, "un identifiant interne du chantier apparaît dans le texte")
    return None


def _regle_a_motifs(regle: str, motifs: Iterable[re.Pattern[str]], plie: str, quoi: str) -> Violation | None:
    trouve = _premier(motifs, plie)
    if trouve is None:
        return None
    return Violation(regle, f"{quoi} : « {_extrait(trouve.group(0))} » ; retire-le")


def controler_texte(texte: str, contexte: ContexteControle | None = None) -> tuple[Violation, ...]:
    """Les règles que `texte` viole, dans l'ordre de `LIBELLES_REGLES` ; vide si le texte est accepté.

    Ne lève rien pour un texte étrange : un texte qui n'est pas une chaîne est le seul cas d'erreur de
    programmation (`TypeError`), tout le reste est un verdict."""
    if not isinstance(texte, str):
        raise TypeError("le texte à contrôler doit être une chaîne")
    ctx = contexte or ContexteControle()
    if not texte.strip():
        return (Violation(REGLE_TEXTE_VIDE, "le texte est vide"),)

    if len(texte) > TEXTE_MAX_CONTROLE:
        return (Violation(REGLE_LONGUEUR, f"{len(texte)} caractères, {TEXTE_MAX_CONTROLE} au plus pour tout texte"),)

    plie = _plier(texte)
    normal = _normal(texte)
    marques = tuple(ctx.noms_de_marque)
    plie_sans_marque = _masquer(plie, marques, plier=True)
    normal_sans_marque = _masquer(normal, marques, plier=False)
    plie_sans_garantie = _masquer(plie_sans_marque, ctx.garanties_validees, plier=True)

    violations: list[Violation | None] = []
    if ctx.longueur_max is not None and len(texte) > ctx.longueur_max:
        violations.append(Violation(REGLE_LONGUEUR, f"{len(texte)} caractères, {ctx.longueur_max} au plus"))
    violations.append(_regle_a_motifs(REGLE_LIEN, (_LIEN,), plie, "lien"))
    violations.append(_adresse(plie, normal))
    violations.append(_coordonnees(plie))
    violations.append(_nom_client(normal_sans_marque, plie_sans_marque, ctx.noms_clients))
    violations.append(_identifiant_interne(plie, ctx.identifiants))
    violations.append(_regle_a_motifs(REGLE_PRIX, _PRIX, plie_sans_marque, "prix ou offre"))
    violations.append(_regle_a_motifs(REGLE_CHIFFRE, (_CHIFFRE,), plie_sans_marque, "chiffre non sourcé"))
    violations.append(_regle_a_motifs(REGLE_GARANTIE, (_GARANTIE,), plie_sans_garantie, "garantie non validée"))
    violations.append(_regle_a_motifs(REGLE_DATE, _DATES, plie_sans_marque, "date ou promesse de délai"))
    violations.append(_regle_a_motifs(REGLE_EXAGERATION, _EXAGERATION, plie_sans_marque, "exagération"))
    return tuple(v for v in violations if v is not None)


def motif_de_refus(violations: Iterable[Violation]) -> str:
    """Le refus, en une phrase qui nomme chaque règle violée (vide s'il n'y en a aucune)."""
    return " ; ".join(f"{v.regle} ({v.detail})" for v in violations)
