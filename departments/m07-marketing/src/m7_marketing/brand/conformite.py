"""Score de conformité d'un texte au profil de marque (M7-MARQUE) : un verdict, des sous-scores et des raisons.

Ce module ne remplace pas la porte qualité binaire de l'usine (`usine.controle_texte`, familles nommées du socle) : il
l'EXPLIQUE et la complète avec les règles que le propriétaire déclare dans son profil v2.

  - **La porte binaire reste la loi.** Toute violation de la porte binaire est une raison BLOQUANTE : le verdict est
    `refuse`. Le score ne peut jamais faire passer un texte que la porte refuse, ni refuser un texte qu'elle accepte
    sans qu'une règle déclarée par le propriétaire (mot interdit, message interdit, énoncé non validé, voix, longueur
    déclarée, mention requise) le dise.
  - **Déterministe et explicable.** Même texte, même profil, même verdict, même score : aucune horloge, aucun modèle,
    aucune entrée-sortie. Le score global est la moyenne PONDÉRÉE (poids fixes, `DIMENSIONS`) des sous-scores ÉVALUÉS,
    arrondie à l'entier ; chaque sous-score inférieur à 100 porte au moins une raison nommée, et chaque raison nomme sa
    dimension. Un score n'est jamais opaque.
  - **Fail-closed, jamais inventé.** Une dimension dont le profil ne déclare rien est « non évaluable » (score `None`,
    dite en clair) ; elle ne compte ni pour ni contre le texte. Un profil absent ou non configuré donne un rapport
    `profil_marque_non_configure`, sans score.
  - **Le verdict.** `refuse` : au moins une raison bloquante. `conforme_avec_reserves` : aucune raison bloquante mais au
    moins une réserve (sous-score < 100 sur une règle non bloquante). `conforme` : rien à dire sur les dimensions
    évaluées — ce qui ne dit RIEN des dimensions non évaluables (listées).

Limites dites : un motif ne comprend pas le sens (un mot interdit cité pour le nier est refusé aussi) ; les marqueurs de
tutoiement ambigus (« ton », « ta », « te ») ne sont qu'une réserve ; un mot interdit est cherché au pluriel/féminin
simples (s, x, e, es), pas par racine.

Module pur.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from opsys.garde_fou_texte import Violation
from opsys.garde_fou_texte._types import plier

from ..usine import controle_texte, plateformes
from . import profil_v2

VERSION_REGLES = "conformite-marque/v1"

REJ_MOT_INTERDIT = "REJ-MARQUE-MOT-INTERDIT"
REJ_MESSAGE_INTERDIT = "REJ-MARQUE-MESSAGE-INTERDIT"
REJ_PROMESSE_NON_VALIDEE = "REJ-MARQUE-PROMESSE-NON-VALIDEE"
REJ_TON = "REJ-MARQUE-TON"
REJ_LONGUEUR = "REJ-MARQUE-LONGUEUR"
REJ_MENTION = "REJ-MARQUE-MENTION-REQUISE"
RES_TON = "RES-MARQUE-TON"
RES_STYLE = "RES-MARQUE-STYLE"
RES_LONGUEUR_COURTE = "RES-MARQUE-LONGUEUR-COURTE"

MOTS_INTERDITS = "mots_interdits"
MESSAGES_INTERDITS = "messages_interdits"
PROMESSES = "promesses_non_validees"
PRIX_CHIFFRES = "prix_et_chiffres"
CONFIDENTIALITE = "confidentialite"
TON = "ton"
LONGUEUR = "longueur_plateforme"
STYLE = "style_plateforme"
MENTIONS = "mentions_requises"

# (dimension, poids, libellé). Les poids sont FIXES et sont la seule source de la pondération : ils totalisent 100.
DIMENSIONS: tuple[tuple[str, int, str], ...] = (
    (MOTS_INTERDITS, 15, "aucun mot que la marque s'interdit"),
    (MESSAGES_INTERDITS, 10, "aucun message ni formule que la marque s'interdit"),
    (PROMESSES, 15, "aucune garantie, exagération ni énoncé de marque non validé"),
    (PRIX_CHIFFRES, 15, "aucun prix, chiffre ou délai inventé"),
    (CONFIDENTIALITE, 15, "aucune adresse, coordonnée, nom de client, identifiant interne ni lien"),
    (TON, 10, "la voix déclarée (vouvoiement ou tutoiement, exclamations, majuscules, émojis)"),
    (LONGUEUR, 5, "la longueur permise par la plateforme et par le style déclaré"),
    (STYLE, 5, "le style déclaré pour la plateforme (mots-clics, émojis)"),
    (MENTIONS, 10, "les mentions que tout contenu public doit porter"),
)
POIDS = {nom: poids for nom, poids, _ in DIMENSIONS}
LIBELLES = {nom: libelle for nom, _, libelle in DIMENSIONS}

# Famille de la porte binaire du socle -> dimension qui l'explique. Une famille inconnue est BLOQUANTE sous
# `confidentialite` (jamais ignorée) : voir `_dimension_de_famille`.
_FAMILLE_VERS_DIMENSION = {
    "texte_vide": LONGUEUR,
    "longueur": LONGUEUR,
    "lien": CONFIDENTIALITE,
    "adresse": CONFIDENTIALITE,
    "coordonnees": CONFIDENTIALITE,
    "nom_client": CONFIDENTIALITE,
    "identifiant_interne": CONFIDENTIALITE,
    "prix_offre": PRIX_CHIFFRES,
    "chiffre_non_source": PRIX_CHIFFRES,
    "promesse_de_date": PRIX_CHIFFRES,
    "garantie_non_validee": PROMESSES,
    "exageration": PROMESSES,
}

_LONGUEUR_MIN_ENONCE = (
    8  # un énoncé plus court ne se cherche pas mot pour mot (il se confondrait avec le texte courant)
)
_TUTOIEMENT_FORT = re.compile(r"(?<![a-z0-9])(?:tu|toi|tes)(?![a-z0-9])|(?<![a-z0-9])t'(?=[a-z])")
_TUTOIEMENT_FAIBLE = re.compile(r"(?<![a-z0-9])(?:ton|ta|te)(?![a-z0-9])")
_VOUVOIEMENT = re.compile(r"(?<![a-z0-9])(?:vous|votre|vos)(?![a-z0-9])")
_MOTS_CLICS = re.compile(r"#\w+")
_MAJUSCULES_LETTRES_MIN = 20


def _nb_emojis(texte: str) -> int:
    return sum(
        1 for c in texte if 0x1F000 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF or 0x2B50 <= ord(c) <= 0x2B55
    )


def _terme(terme: str) -> re.Pattern[str]:
    """Le terme (plié) comme mot entier, avec pluriel ou féminin simples."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(terme) + r"(?:s|x|e|es)?(?![a-z0-9])")


@dataclasses.dataclass(frozen=True)
class Evaluation:
    """Le rapport lisible et les violations (porte binaire d'abord, puis règles bloquantes du profil), prêtes pour le
    refus de l'usine."""

    rapport: dict[str, Any]
    violations: tuple[Violation, ...]

    @property
    def refuse(self) -> bool:
        return bool(self.violations)


def _raison(dimension: str, code: str, detail: str, bloquante: bool) -> dict[str, Any]:
    return {"dimension": dimension, "code": code, "detail": detail, "bloquante": bloquante}


def _extrait(texte: str, n: int = 40) -> str:
    propre = " ".join(texte.split())
    return propre if len(propre) <= n else propre[: n - 1] + "…"


def _retirer_mentions(texte: str, mentions: list[str]) -> str:
    """Le texte sans les mentions VALIDÉES (énoncés du propriétaire, mot pour mot) : elles ne doivent pas déclencher la
    porte binaire (un numéro de licence ressemble à une coordonnée)."""
    for mention in mentions:
        motif = r"\s+".join(re.escape(m) for m in mention.split())
        texte = re.sub(motif, " ", texte, flags=re.IGNORECASE)
    return texte


def _enonces_a_valider(profil: dict[str, Any]) -> list[tuple[str, str]]:
    """Les énoncés déclarés mais pas validés, qu'un texte ne peut pas citer mot pour mot : `(champ, énoncé)`."""
    sortie = [("garanties_a_valider", e) for e in profil.get("garanties_a_valider") or []]
    for champ in ("promesse", "avantages", "valeurs", "preuve_sociale", "objections_frequentes"):
        if profil_v2.est_valide(profil, champ):
            continue
        valeur = profil.get(champ)
        if isinstance(valeur, str):
            sortie.append((champ, valeur))
        elif isinstance(valeur, list):
            for item in valeur:
                if isinstance(item, str):
                    sortie.append((champ, item))
                elif isinstance(item, dict) and isinstance(item.get("reponse"), str):
                    sortie.append((champ, item["reponse"]))
    return sortie


def _dimension_de_famille(famille: str) -> str:
    return _FAMILLE_VERS_DIMENSION.get(famille, CONFIDENTIALITE)


def contexte_pour_profil(
    profil: dict[str, Any],
    longueur_max: int | None,
    identifiants: tuple[str, ...] = (),
    noms_clients: tuple[str, ...] = (),
) -> controle_texte.ContexteControle:
    garanties = profil.get("garanties_validees")
    return controle_texte.ContexteControle(
        garanties_validees=tuple(g for g in garanties if isinstance(g, str) and g.strip())
        if isinstance(garanties, list)
        else (),
        noms_de_marque=(profil["name"],),
        noms_clients=noms_clients,
        identifiants=identifiants,
        longueur_max=longueur_max,
    )


def profil_non_configure(motif: str) -> Evaluation:
    """Rapport d'un profil absent ou non configuré : aucun score, aucun contenu composé sous un nom inventé."""
    rapport = {
        "version_regles": VERSION_REGLES,
        "statut": "profil_marque_non_configure",
        "verdict": "refuse",
        "score_global": None,
        "sous_scores": {},
        "raisons": [_raison("profil", "REJ-PROFIL-MARQUE-NON-CONFIGURE", motif, True)],
        "violations_porte_binaire": [],
        "non_evaluables": [nom for nom, _, _ in DIMENSIONS],
        "profil": {"version": None, "a_fournir": []},
    }
    return Evaluation(rapport, ())


def evaluer(
    texte: str,
    profil: dict[str, Any] | None,
    plateforme: plateformes.Plateforme,
    contexte: controle_texte.ContexteControle | None = None,
) -> Evaluation:
    """Évalue `texte` pour `plateforme` contre `profil` (déjà validé). `TypeError` si `texte` n'est pas une chaîne
    (erreur de programmation) ; tout le reste est un verdict."""
    if not isinstance(texte, str):
        raise TypeError("le texte à évaluer doit être une chaîne")
    if not isinstance(profil, dict) or not isinstance(profil.get("name"), str) or not profil["name"].strip():
        return profil_non_configure("profil de marque absent ou sans nom commercial")
    contexte = contexte or contexte_pour_profil(profil, plateforme.longueur_max)
    plie = plier(texte)
    raisons: list[dict[str, Any]] = []
    violations: list[Violation] = []
    mentions = [m for m in profil.get("mentions_requises") or [] if isinstance(m, str)]
    mentions_validees = mentions if profil_v2.est_valide(profil, "mentions_requises") and plateforme.public else []

    # 1. La porte binaire du socle (la loi), expliquée par dimension.
    binaires = controle_texte.controler_texte(_retirer_mentions(texte, mentions_validees), contexte)
    for v in binaires:
        raisons.append(_raison(_dimension_de_famille(v.famille), v.regle, v.detail, True))
        violations.append(v)

    def bloquer(dimension: str, code: str, detail: str) -> None:
        raisons.append(_raison(dimension, code, detail, True))
        violations.append(Violation(f"marque_{dimension}", code, detail))

    # 2. Mots et messages interdits (déclarés par le propriétaire, en vigueur dès la déclaration).
    for mot in profil.get("mots_interdits") or []:
        if _terme(plier(mot)).search(plie):
            bloquer(MOTS_INTERDITS, REJ_MOT_INTERDIT, f"mot interdit par la marque : « {_extrait(mot)} » ; retire-le")
    for message in profil.get("messages_interdits") or []:
        if _terme(plier(message)).search(plie):
            bloquer(
                MESSAGES_INTERDITS,
                REJ_MESSAGE_INTERDIT,
                f"message interdit par la marque : « {_extrait(message)} » ; retire-le",
            )

    # 3. Énoncés déclarés mais non validés : jamais cités mot pour mot (le nom et l'accroche du profil v1 sont exclus).
    masque = plie
    for identite in (profil.get("name"), profil.get("tagline")):
        if isinstance(identite, str) and plier(identite).strip():
            masque = masque.replace(plier(identite), " ")
    vus: set[str] = set()
    for champ, enonce in _enonces_a_valider(profil):
        cherche = plier(enonce)
        if len(cherche) >= _LONGUEUR_MIN_ENONCE and cherche in masque and cherche not in vus:
            vus.add(cherche)
            bloquer(
                PROMESSES,
                REJ_PROMESSE_NON_VALIDEE,
                f"énoncé « {_extrait(enonce)} » ({champ}) pas encore validé par le propriétaire ; retire-le",
            )

    # 4. Ton déclaré.
    voix = profil.get("voix") if isinstance(profil.get("voix"), dict) else {}
    criteres: list[tuple[str, bool]] = []
    adresse = voix.get("adresse")
    if adresse == "vous":
        fort, faible = bool(_TUTOIEMENT_FORT.search(plie)), bool(_TUTOIEMENT_FAIBLE.search(plie))
        criteres.append(("adresse", not fort and not faible))
        if fort:
            bloquer(TON, REJ_TON, "la marque vouvoie : tutoiement détecté (tu, toi, tes) ; reformule au vous")
        elif faible:
            raisons.append(
                _raison(
                    TON,
                    RES_TON,
                    "marqueur de tutoiement possible (ton, ta, te) alors que la marque vouvoie ; à relire",
                    False,
                )
            )
    elif adresse == "tu":
        fort = bool(_VOUVOIEMENT.search(plie))
        criteres.append(("adresse", not fort))
        if fort:
            bloquer(TON, REJ_TON, "la marque tutoie : vouvoiement détecté (vous, votre, vos) ; reformule au tu")
    if "exclamations_max" in voix:
        n = texte.count("!")
        criteres.append(("exclamations", n <= voix["exclamations_max"]))
        if n > voix["exclamations_max"]:
            raisons.append(
                _raison(TON, RES_TON, f"{n} points d'exclamation, {voix['exclamations_max']} au plus", False)
            )
    if "majuscules_max_pct" in voix:
        lettres = [c for c in texte if c.isalpha()]
        pct = 100 * sum(c.isupper() for c in lettres) // len(lettres) if len(lettres) >= _MAJUSCULES_LETTRES_MIN else 0
        criteres.append(("majuscules", pct <= voix["majuscules_max_pct"]))
        if pct > voix["majuscules_max_pct"]:
            raisons.append(
                _raison(TON, RES_TON, f"{pct} % de majuscules, {voix['majuscules_max_pct']} % au plus", False)
            )
    if "emojis_max" in voix:
        n = _nb_emojis(texte)
        criteres.append(("emojis", n <= voix["emojis_max"]))
        if n > voix["emojis_max"]:
            raisons.append(_raison(TON, RES_TON, f"{n} émojis, {voix['emojis_max']} au plus", False))

    # 5. Longueur : plafond de la plateforme (porte binaire), plafond et plancher déclarés.
    style = (profil.get("style_plateforme") or {}).get(plateforme.code, {})
    taille = len(texte)
    maxi_declare = style.get("longueur_max")
    mini_declare = style.get("longueur_min")
    longueur_ok_bloquante = any(r["dimension"] == LONGUEUR and r["bloquante"] for r in raisons)
    if maxi_declare is not None and taille > maxi_declare:
        bloquer(
            LONGUEUR,
            REJ_LONGUEUR,
            f"{taille} caractères, {maxi_declare} au plus pour cette marque sur {plateforme.libelle}",
        )
        longueur_ok_bloquante = True
    score_longueur = 0 if longueur_ok_bloquante else 100
    if not longueur_ok_bloquante and mini_declare and taille < mini_declare:
        score_longueur = 100 * taille // mini_declare
        raisons.append(
            _raison(
                LONGUEUR, RES_LONGUEUR_COURTE, f"{taille} caractères, {mini_declare} au moins pour cette marque", False
            )
        )

    # 6. Style par plateforme (réserves seulement).
    criteres_style: list[tuple[str, bool]] = []
    if "hashtags_max" in style:
        n = len(_MOTS_CLICS.findall(texte))
        criteres_style.append(("hashtags", n <= style["hashtags_max"]))
        if n > style["hashtags_max"]:
            raisons.append(_raison(STYLE, RES_STYLE, f"{n} mots-clics, {style['hashtags_max']} au plus", False))
    if "emojis_max" in style:
        n = _nb_emojis(texte)
        criteres_style.append(("emojis", n <= style["emojis_max"]))
        if n > style["emojis_max"]:
            raisons.append(_raison(STYLE, RES_STYLE, f"{n} émojis, {style['emojis_max']} au plus", False))

    # 7. Mentions requises (contenu public seulement).
    presentes = 0
    for mention in mentions:
        if plateforme.public and plier(mention) in plie:
            presentes += 1
        elif plateforme.public:
            bloquer(MENTIONS, REJ_MENTION, f"mention requise absente : « {_extrait(mention)} »")

    def score_binaire(dimension: str) -> int:
        return 0 if any(r["dimension"] == dimension and r["bloquante"] for r in raisons) else 100

    def par_criteres(liste: list[tuple[str, bool]]) -> int | None:
        return None if not liste else (100 * sum(ok for _, ok in liste)) // len(liste)

    scores: dict[str, int | None] = {
        MOTS_INTERDITS: score_binaire(MOTS_INTERDITS) if profil.get("mots_interdits") else None,
        MESSAGES_INTERDITS: score_binaire(MESSAGES_INTERDITS) if profil.get("messages_interdits") else None,
        PROMESSES: score_binaire(PROMESSES),
        PRIX_CHIFFRES: score_binaire(PRIX_CHIFFRES),
        CONFIDENTIALITE: score_binaire(CONFIDENTIALITE),
        TON: par_criteres(criteres),
        LONGUEUR: score_longueur,
        STYLE: par_criteres(criteres_style),
        MENTIONS: (100 * presentes) // len(mentions) if mentions and plateforme.public else None,
    }
    sous_scores = {}
    for nom, poids, libelle in DIMENSIONS:
        du_nom = [r for r in raisons if r["dimension"] == nom]
        sous_scores[nom] = {
            "score": scores[nom],
            "evalue": scores[nom] is not None,
            "poids": poids,
            "libelle": libelle,
            "bloquante": any(r["bloquante"] for r in du_nom),
            "raisons": [r["code"] + " : " + r["detail"] for r in du_nom],
        }
    evalues = [(nom, scores[nom]) for nom, _, _ in DIMENSIONS if scores[nom] is not None]
    total_poids = sum(POIDS[nom] for nom, _ in evalues)
    global_ = (
        (sum(POIDS[nom] * s for nom, s in evalues) * 2 + total_poids) // (2 * total_poids) if total_poids else None
    )
    if violations:
        verdict = "refuse"
    elif raisons:
        verdict = "conforme_avec_reserves"
    else:
        verdict = "conforme"
    completude = profil_v2.completude(profil)
    rapport = {
        "version_regles": VERSION_REGLES,
        "statut": "evalue",
        "verdict": verdict,
        "score_global": global_,
        "sous_scores": sous_scores,
        "raisons": raisons,
        "violations_porte_binaire": [v.en_dict() for v in binaires],
        "non_evaluables": [nom for nom, _, _ in DIMENSIONS if scores[nom] is None],
        "profil": {
            "version": completude["version_de_lecture"],
            "a_fournir": completude["a_fournir"],
            "a_valider_par_le_proprietaire": completude["a_valider_par_le_proprietaire"],
        },
    }
    return Evaluation(rapport, tuple(violations))


def resume(rapport: dict[str, Any]) -> dict[str, Any]:
    """La forme compacte rangée avec une proposition : verdict, score et sous-scores (sans les raisons)."""
    return {
        "version_regles": rapport["version_regles"],
        "verdict": rapport["verdict"],
        "score_global": rapport["score_global"],
        "sous_scores": {nom: s["score"] for nom, s in rapport["sous_scores"].items()},
        "non_evaluables": list(rapport["non_evaluables"]),
    }
