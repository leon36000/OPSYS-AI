"""Boucle d'apprentissage de M1 (M1.13) : des retours humains deviennent des PROPOSITIONS, jamais des changements.

Principe : un humain corrige une classe de tri ou un brouillon ; le système garde le fait (pas le texte du client) ;
à la demande, du code déterministe en tire des propositions d'amélioration (règles de tri, phrases de gabarit). Une
proposition est mesurée hors ligne contre le corpus d'évaluation, puis ne devient active que par une PROMOTION humaine
(N3) : canari (une part des courriels, choisie par une fonction de hachage du signal), puis promotion complète, ou
retour arrière. Rien ici n'appelle un modèle, le réseau, une horloge ; le registre est un journal append-only.

Garde-fous du moteur :
- une règle apprise pèse au plus `POIDS_MAX_APPRIS` : elle aide un cas douteux, elle ne renverse jamais une règle
forte ;
- une expression n'est proposée que si elle revient dans au moins `SUPPORT_MIN` retours de signaux DISTINCTS venant d'au
  moins `SOURCES_MIN` expéditeurs distincts (un expéditeur ne fabrique pas une règle en se corrigeant lui-même), et
  si elle est rare ailleurs (`FUITE_MAX` : part des exemples d'autres classes qui la portent) ;
- jamais de chiffre, d'adresse, de lien, de jeton de neutralisation ni de mot de la liste d'interdits dans une
expression ;
- une promotion exige que la mesure sur le corpus de garde ne régresse sur aucune classe au-delà de `TOLERANCE`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from . import tri_courriel as tri
from .tri_regles import CLASSES, JEU_V1, POIDS_MAX_APPRIS, JeuRegles, RegleTri

SUPPORT_MIN = 2
SOURCES_MIN = 2
FUITE_MAX = Decimal("0.10")
MAX_REGLES_PAR_PROPOSITION = 12
TOLERANCE = Decimal("0.020")
GRAMMES_MAX = 3
LONGUEUR_MIN_MOT = 4
PHRASE_GABARIT_MIN_MOTS = 3
PHRASE_GABARIT_MAX_MOTS = 14
SUPPORT_GABARIT_MIN = 3

TYPE_RETOUR_TRI = "retour_tri"
TYPE_RETOUR_BROUILLON = "retour_brouillon"
TYPE_PROPOSITION = "proposition"
TYPE_DECISION = "decision"
ETAPES = ("canari", "complete", "retour_arriere", "refusee")
ISSUES_BROUILLON = ("accepte", "corrige", "rejete")

_MOTS_VIDES = frozenset(
    [
        "avec",
        "dans",
        "pour",
        "sans",
        "chez",
        "cette",
        "cela",
        "celui",
        "celle",
        "ceux",
        "elles",
        "nous",
        "vous",
        "leur",
        "leurs",
        "votre",
        "notre",
        "vos",
        "nos",
        "mais",
        "donc",
        "alors",
        "ainsi",
        "aussi",
        "comme",
        "tout",
        "tous",
        "toute",
        "toutes",
        "tres",
        "plus",
        "moins",
        "bien",
        "fait",
        "faire",
        "etre",
        "avoir",
        "suis",
        "sommes",
        "sont",
        "etait",
        "serait",
        "sera",
        "peut",
        "peux",
        "veux",
        "voir",
        "bonjour",
        "merci",
        "cordialement",
        "salutations",
        "madame",
        "monsieur",
        "svp",
        "le",
        "la",
        "les",
        "une",
        "des",
        "que",
        "qui",
        "quoi",
        "dont",
        "quand",
        "comment",
        "pourquoi",
        "ici",
        "voila",
    ]
)
_INTERDITS = frozenset(
    [
        "ignore",
        "ignorez",
        "instructions",
        "instruction",
        "consigne",
        "consignes",
        "prompt",
        "systeme",
        "system",
        "assistant",
        "model",
        "modele",
        "classe",
        "classer",
        "route",
        "router",
        "aiguille",
        "aiguiller",
        "admin",
        "password",
    ]
)
_MOT = re.compile(r"[a-z]+(?:'[a-z]+)?")


# --------------------------------------------------------------------------------------------- extraction
def _a_ecarter(jeton: str) -> bool:
    return (
        "@" in jeton
        or "contenu_non_fiable" in jeton
        or jeton.startswith(("http", "www."))
        or any(c.isdigit() for c in jeton)
    )


def _segments(texte: str) -> list[list[str]]:
    """Suites de mots du texte normalisé, coupées à chaque lien, adresse, jeton de neutralisation ou mot qui contient un
    chiffre : une expression apprise ne traverse jamais, et ne contient jamais, ces éléments. Lecture linéaire."""
    segments: list[list[str]] = []
    courant: list[str] = []
    for jeton in tri.normaliser(texte).split(" "):
        if _a_ecarter(jeton):
            if courant:
                segments.append(courant)
            courant = []
            continue
        courant.extend(_MOT.findall(jeton))
    if courant:
        segments.append(courant)
    return segments


def _mots(texte: str) -> list[str]:
    return _MOT.findall(tri.normaliser(texte))


def _grammes(texte: str) -> set[str]:
    """Expressions candidates d'un texte : suites de 1 à 3 mots sans chiffre, sans mot vide aux extrémités."""
    res: set[str] = set()
    for mots in _segments(texte):
        for n in range(1, GRAMMES_MAX + 1):
            for i in range(len(mots) - n + 1):
                g = mots[i : i + n]
                if n == 1 and (len(g[0]) < LONGUEUR_MIN_MOT or g[0] in _MOTS_VIDES):
                    continue
                if n > 1 and (g[0] in _MOTS_VIDES or g[-1] in _MOTS_VIDES):
                    continue
                if any(m in _INTERDITS for m in g):
                    continue
                res.add(" ".join(g))
    return res


def expression_admissible(expression: str) -> bool:
    if not isinstance(expression, str) or not 4 <= len(expression) <= 60:
        return False
    if re.search(r"[\d@/\\:<>\[\]{}]|https?|contenu_non_fiable", expression):
        return False
    return all(m not in _INTERDITS for m in expression.split())


def pseudonyme_expediteur(adresse: str) -> str:
    """Empreinte courte de l'adresse : sert seulement à compter des sources distinctes, jamais à la retrouver."""
    return hashlib.sha256(("m1-retour|" + adresse.strip().lower()).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------------------------- propositions
@dataclasses.dataclass(frozen=True)
class ExempleCorrige:
    signal_id: str
    texte: str  # texte neutralisé (objet + corps), lu au moment du calcul, jamais recopié au registre
    classe_attendue: str  # décidée par la personne
    source: str  # pseudonyme de l'expéditeur


def proposer_regles(
    exemples: Sequence[ExempleCorrige],
    jeu: JeuRegles,
    ailleurs: Iterable[tuple[str, str]] = (),
) -> list[RegleTri]:
    """Règles candidates à partir des corrections. `ailleurs` : (classe, texte) d'exemples déjà validés, pour mesurer la
    fuite d'une expression vers d'autres classes. Déterministe : tri par support décroissant puis ordre alphabétique."""
    par_classe: dict[str, list[ExempleCorrige]] = defaultdict(list)
    for e in exemples:
        if e.classe_attendue in CLASSES and e.classe_attendue != "autre":
            par_classe[e.classe_attendue].append(e)
    autres = [(e.classe_attendue, e.texte) for e in exemples] + list(ailleurs)
    gram_autres = [(c, _grammes(t)) for c, t in autres]
    propositions: list[tuple[int, str, str]] = []
    deja = {r.motif for r in jeu.regles}
    for classe, liste in par_classe.items():
        support: dict[str, set[str]] = defaultdict(set)
        sources: dict[str, set[str]] = defaultdict(set)
        for e in liste:
            for g in _grammes(e.texte):
                support[g].add(e.signal_id)
                sources[g].add(e.source)
        for g, signaux in support.items():
            if len(signaux) < SUPPORT_MIN or len(sources[g]) < SOURCES_MIN or not expression_admissible(g):
                continue
            ici = sum(1 for c, gs in gram_autres if c == classe and g in gs)
            ailleurs_n = sum(1 for c, gs in gram_autres if c != classe and g in gs)
            total_autres = sum(1 for c, _ in gram_autres if c != classe)
            if total_autres and Decimal(ailleurs_n) / Decimal(total_autres) > FUITE_MAX:
                continue
            if ailleurs_n and Decimal(ailleurs_n) / Decimal(ailleurs_n + ici) > FUITE_MAX:
                continue
            motif = r"\b" + re.escape(g) + r"\b"
            if motif in deja:
                continue
            propositions.append((len(signaux), classe, g))
    # Une expression incluse dans une autre retenue de la même classe est redondante.
    propositions.sort(key=lambda p: (-p[0], -len(p[2]), p[1], p[2]))
    retenues: list[tuple[int, str, str]] = []
    for sup, classe, g in propositions:
        if any(c == classe and g in autre_g for _, c, autre_g in retenues):
            continue
        retenues.append((sup, classe, g))
        if len(retenues) >= MAX_REGLES_PAR_PROPOSITION:
            break
    regles = []
    for sup, classe, g in retenues:
        identifiant = "ap-" + hashlib.sha256(f"{classe}|{g}".encode()).hexdigest()[:10]
        regles.append(
            RegleTri(
                identifiant,
                classe,
                f"règle apprise : l'expression « {g} » accompagne la classe {classe} dans {sup} corrections humaines",
                "tout",
                r"\b" + re.escape(g) + r"\b",
                2 if sup >= 3 else 1,
            )
        )
    assert all(r.poids <= POIDS_MAX_APPRIS for r in regles)
    return regles


# --------------------------------------------------------------------------------------------- mesure et garde
def mesurer(
    avant: JeuRegles,
    apres: JeuRegles,
    cas: Sequence[Mapping[str, Any]],
    domaines: Sequence[str] = ("atelier.example.test",),
) -> dict[str, Any]:
    """Compare deux jeux sur un corpus : justesse, F1 macro, précision et rappel par classe, régressions nommées."""
    a, b = tri.evaluer(cas, avant, domaines), tri.evaluer(cas, apres, domaines)
    regressions = []
    ameliorations = []
    for k in CLASSES:
        pa, pb = a["par_classe"][k], b["par_classe"][k]
        for mesure in ("precision", "rappel"):
            va, vb = pa[mesure], pb[mesure]
            if va is None or vb is None:
                continue
            delta = Decimal(vb) - Decimal(va)
            if delta < -TOLERANCE:
                regressions.append({"classe": k, "mesure": mesure, "avant": va, "apres": vb})
            elif delta > TOLERANCE:
                ameliorations.append({"classe": k, "mesure": mesure, "avant": va, "apres": vb})
    ids_a = {e["id"] for e in a["erreurs"]}
    ids_b = {e["id"] for e in b["erreurs"]}
    return {
        "effectif": a["effectif"],
        "justesse_avant": a["justesse"],
        "justesse_apres": b["justesse"],
        "f1_macro_avant": a["f1_macro"],
        "f1_macro_apres": b["f1_macro"],
        "corriges": sorted(ids_a - ids_b),
        "casses": sorted(ids_b - ids_a),
        "regressions": regressions,
        "ameliorations": ameliorations,
        "promouvable": not regressions and Decimal(b["justesse"]) >= Decimal(a["justesse"]),
        "empreinte_avant": avant.empreinte(),
        "empreinte_apres": apres.empreinte(),
    }


# --------------------------------------------------------------------------------------------- gabarits
def phrases_ajoutees(texte_avant: str, texte_apres: str) -> list[str]:
    """Phrases du texte final absentes du brouillon (ajoutées par la personne), admissibles pour un gabarit. Jamais un
    chiffre, une adresse, un lien : voir `expression_admissible` ; et jamais plus de 14 mots."""
    avant = {_phrase_normalisee(p) for p in _phrases(texte_avant)}
    res = []
    for p in _phrases(texte_apres):
        n = _phrase_normalisee(p)
        mots = n.split()
        if n in avant or not PHRASE_GABARIT_MIN_MOTS <= len(mots) <= PHRASE_GABARIT_MAX_MOTS:
            continue
        if re.search(r"[\d@/\\<>\[\]{}]|https?|www\.|contenu_non_fiable", p, re.IGNORECASE) or any(
            m in _INTERDITS for m in mots
        ):
            continue
        res.append(p.strip())
    return res[:5]


def _phrases(texte: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", texte) if p.strip()]


def _phrase_normalisee(p: str) -> str:
    return " ".join(_mots(p))


def proposer_ajouts_gabarit(retours: Sequence[Mapping[str, Any]], gabarit_id: str) -> list[dict[str, Any]]:
    """Phrases ajoutées dans au moins `SUPPORT_GABARIT_MIN` BROUILLONS distincts de ce gabarit. Le support compte les
    brouillons, pas les personnes : les décisions N3 d'une petite entreprise viennent d'une seule personne (la
    propriétaire), et c'est sa promotion (canari, retour arrière) qui protège, pas le nombre de signataires. Un même
    brouillon corrigé plusieurs fois ne compte qu'une fois."""
    comptes: dict[str, set[str]] = defaultdict(set)
    forme: dict[str, str] = {}
    for r in retours:
        if r.get("type_entree") != TYPE_RETOUR_BROUILLON or r.get("gabarit_id") != gabarit_id:
            continue
        for p in r.get("phrases_ajoutees", ()):
            n = _phrase_normalisee(p)
            comptes[n].add(str(r.get("brouillon_id", "")))
            forme.setdefault(n, p)
    sortie = [
        {"gabarit_id": gabarit_id, "phrase": forme[n], "support": len(brouillons)}
        for n, brouillons in comptes.items()
        if len(brouillons) >= SUPPORT_GABARIT_MIN
    ]
    return sorted(sortie, key=lambda x: (-x["support"], x["phrase"]))


# --------------------------------------------------------------------------------------------- état du registre
class RefusApprentissage(ValueError):
    """Refus typé (`REJ-M1-APPR-…`) : le message commence par le code."""


def identifiant_proposition(genre: str, contenu: Any) -> str:
    import json

    canon = json.dumps([genre, contenu], sort_keys=True, ensure_ascii=False)
    return "pr-" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:20]


def _regle_depuis_json(d: Mapping[str, Any]) -> RegleTri:
    if d.get("poids", 99) > POIDS_MAX_APPRIS:
        raise RefusApprentissage("REJ-M1-APPR-POIDS: une règle apprise pèse 2 au plus")
    return RegleTri(d["identifiant"], d["classe"], d["libelle"], d["champ"], d["motif"], d["poids"])


@dataclasses.dataclass(frozen=True)
class EtatApprentissage:
    jeu_actif: JeuRegles
    canari: tuple[str, JeuRegles, int] | None  # (proposition_id, jeu candidat complet, pourcentage)
    propositions: Mapping[str, Mapping[str, Any]]
    etats: Mapping[str, str]  # proposition_id -> proposee|canari|complete|retiree|refusee
    gabarits: Mapping[str, tuple[str, ...]]  # gabarit_id -> phrases ajoutées actives (ordre de promotion)
    pile_completes: tuple[str, ...]
    # (proposition_id, gabarit_id, phrase, pourcentage) : la phrase d'un gabarit en canari ne s'applique qu'aux messages
    # dont la clé tombe dans le canari ; les autres gardent le texte actif.
    canari_gabarit: tuple[str, str, str, int] | None = None


def etat(maillons: Iterable[Mapping[str, Any]], base: JeuRegles = JEU_V1) -> EtatApprentissage:
    """Rejoue le registre : quelles propositions sont actives. Le seul chemin vers une règle active est une décision."""
    propositions: dict[str, Mapping[str, Any]] = {}
    etats: dict[str, str] = {}
    pile: list[str] = []
    canari: str | None = None
    pct: dict[str, int] = {}
    for m in maillons:
        t = m.get("type_entree")
        if t == TYPE_PROPOSITION:
            propositions[m["proposition_id"]] = m
            etats.setdefault(m["proposition_id"], "proposee")
        elif t == TYPE_DECISION:
            pid, etape = m["proposition_id"], m["etape"]
            if pid not in propositions:
                raise RefusApprentissage("REJ-M1-APPR-INCONNUE: décision sur une proposition absente")
            courant = etats[pid]
            if etape == "canari" and courant == "proposee" and canari is None:
                etats[pid], canari, pct[pid] = "canari", pid, int(m["pourcentage"])
            elif etape == "complete" and courant == "canari":
                etats[pid] = "complete"
                pile.append(pid)
                if canari == pid:
                    canari = None
            elif etape == "retour_arriere" and courant == "canari":
                etats[pid], canari = "retiree", None
            elif etape == "retour_arriere" and courant == "complete" and pile and pile[-1] == pid:
                etats[pid] = "retiree"
                pile.pop()
            elif etape == "refusee" and courant == "proposee":
                etats[pid] = "refusee"
            else:
                raise RefusApprentissage(f"REJ-M1-APPR-TRANSITION: « {etape} » illégal depuis « {courant} »")
    jeu = base
    gabarits: dict[str, list[str]] = defaultdict(list)
    for pid in pile:
        p = propositions[pid]
        if p["genre"] == "regle_tri":
            jeu = jeu.avec([_regle_depuis_json(r) for r in p["regles"]], f"{jeu.version}+{pid[3:9]}")
        elif p["genre"] == "gabarit":
            gabarits[p["gabarit_id"]].append(p["phrase"])
    cand = None
    if canari is not None and propositions[canari]["genre"] == "regle_tri":
        cand = (
            canari,
            jeu.avec(
                [_regle_depuis_json(r) for r in propositions[canari]["regles"]], f"{jeu.version}~canari-{canari[3:9]}"
            ),
            pct[canari],
        )
    cg = None
    if canari is not None and propositions[canari]["genre"] == "gabarit":
        p = propositions[canari]
        cg = (canari, p["gabarit_id"], p["phrase"], pct[canari])
    return EtatApprentissage(
        jeu, cand, propositions, etats, {k: tuple(v) for k, v in gabarits.items()}, tuple(pile), cg
    )


def phrases_gabarit(e: EtatApprentissage, gabarit_id: str, cle: str) -> tuple[str, ...]:
    """Les phrases ajoutées qui s'appliquent au message de clé `cle` : les promues, plus celle en canari si la clé y
    tombe. Pure ; la clé est stable (un message rejoué reçoit le même texte)."""
    actives = e.gabarits.get(gabarit_id, ())
    c = e.canari_gabarit
    if c is not None and c[1] == gabarit_id and dans_le_canari(cle, c[3]) and c[2] not in actives:
        return (*actives, c[2])
    return actives


def dans_le_canari(signal_id: str, pourcentage: int) -> bool:
    return int(hashlib.sha256(("canari|" + signal_id).encode()).hexdigest()[:8], 16) % 100 < pourcentage


def jeu_pour(signal_id: str, e: EtatApprentissage) -> tuple[JeuRegles, bool]:
    """Le jeu qui décide pour CE signal (actif, ou candidat si le signal tombe dans le canari) et si c'est le canari."""
    if e.canari is not None and dans_le_canari(signal_id, e.canari[2]):
        return e.canari[1], True
    return e.jeu_actif, False
