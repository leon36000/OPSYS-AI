"""Analyse de `robots.txt` selon la RFC 9309 : ce qu'un robot déclaré a le droit de demander, et à quel rythme.

Utilisé par la veille concurrentielle (on ne collecte JAMAIS ce qu'un site interdit à notre robot) et par l'analyse
GEO du
site du client (quels robots d'IA y sont autorisés). Module pur : aucune entrée-sortie ; le texte et le statut HTTP de
la
réponse sont fournis par l'appelant.

Règles appliquées (RFC 9309) :
- les groupes sont désignés par `User-agent` ; le groupe retenu est celui du jeton le plus SPÉCIFIQUE qui est contenu
dans le
  nom du robot (insensible à la casse), sinon le groupe `*`, sinon tout est autorisé ;
- le chemin le plus LONG qui correspond l'emporte ; à longueur égale, `Allow` l'emporte sur `Disallow` ; `*` (suite de
  caractères quelconques) et `$` (fin de chemin) sont des jokers ; la correspondance est sensible à la casse ;
- un fichier introuvable (4xx) autorise tout ; un fichier INACCESSIBLE (5xx, délai, réponse illisible) interdit tout (le
  robot doit supposer une interdiction complète) ; le fichier est lu jusqu'à 500 Kio (le reste est ignoré) ;
- `Crawl-delay` n'est pas dans la RFC mais il est respecté quand il est déclaré (secondes, borné à 3600) ;
- une ligne mal formée est ignorée, jamais interprétée ; une URL de plan de site déclarée est rendue telle quelle.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence

TAILLE_MAX = 500 * 1024
CRAWL_DELAY_MAX_S = 3600
_DIRECTIVE = re.compile(r"^([A-Za-z-]{1,30})\s*:\s*(.*)$")


@dataclasses.dataclass(frozen=True)
class Groupe:
    agents: tuple[str, ...]
    regles: tuple[tuple[str, str], ...]  # (« allow » | « disallow », motif)
    crawl_delay_s: int | None = None


@dataclasses.dataclass(frozen=True)
class RegleRobots:
    """Le fichier lu. `etat` : `lu`, `absent` (4xx : tout permis) ou `inaccessible` (tout interdit)."""

    etat: str
    groupes: tuple[Groupe, ...] = ()
    plans_de_site: tuple[str, ...] = ()
    tronque: bool = False


def analyser(texte: str | None, statut_http: int) -> RegleRobots:
    """Lit `robots.txt` selon la réponse obtenue. `texte` peut être None quand rien n'a pu être lu."""
    if type(statut_http) is not int or statut_http >= 500 or statut_http < 100 or texte is None and statut_http < 400:
        return RegleRobots("inaccessible")
    if 400 <= statut_http < 500:
        return RegleRobots("absent")
    if not 200 <= statut_http < 300:
        return RegleRobots("inaccessible")  # redirection non résolue ou statut inconnu : prudence
    brut = texte if texte is not None else ""
    tronque = len(brut.encode("utf-8")) > TAILLE_MAX
    if tronque:
        brut = brut.encode("utf-8")[:TAILLE_MAX].decode("utf-8", errors="ignore")
    groupes: list[Groupe] = []
    plans: list[str] = []
    agents: list[str] = []
    regles: list[tuple[str, str]] = []
    delai: int | None = None
    en_regles = False

    def clore() -> None:
        nonlocal agents, regles, delai, en_regles
        if agents:
            groupes.append(Groupe(tuple(agents), tuple(regles), delai))
        agents, regles, delai, en_regles = [], [], None, False

    for ligne in brut.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        ligne = ligne.split("#", 1)[0].strip()
        if not ligne:
            continue
        m = _DIRECTIVE.match(ligne)
        if not m:
            continue
        nom, valeur = m.group(1).lower(), m.group(2).strip()
        if nom == "user-agent":
            if en_regles:
                clore()
            if valeur:
                agents.append(valeur.lower())
        elif nom in ("allow", "disallow") and agents:
            en_regles = True
            if valeur or nom == "disallow":
                regles.append((nom, valeur))
        elif nom == "crawl-delay" and agents:
            en_regles = True
            try:
                delai = min(int(float(valeur)), CRAWL_DELAY_MAX_S)
            except ValueError:
                delai = None
            if delai is not None and delai < 0:
                delai = None
        elif nom == "sitemap" and valeur:
            plans.append(valeur[:500])
    clore()
    return RegleRobots("lu", tuple(groupes), tuple(plans[:20]), tronque)


def _glob(motif: str, texte: str) -> bool:
    """Correspondance COMPLÈTE de `motif` (où `*` vaut une suite quelconque) avec `texte`, en temps O(n·m) : aucune
    expression
    régulière, donc aucun motif hostile ne peut provoquer un retour arrière explosif."""
    p = t = 0
    etoile = -1
    reprise = 0
    while t < len(texte):
        if p < len(motif) and motif[p] == "*":
            etoile, reprise = p, t
            p += 1
        elif p < len(motif) and motif[p] == texte[t]:
            p += 1
            t += 1
        elif etoile != -1:
            reprise += 1
            p, t = etoile + 1, reprise
        else:
            return False
    while p < len(motif) and motif[p] == "*":
        p += 1
    return p == len(motif)


def _correspond(motif: str, chemin: str) -> int:
    """Longueur du motif s'il correspond au début du chemin (jokers `*` et `$`), sinon -1."""
    if motif == "" or len(motif) > 2000:
        return -1
    ancre = motif.endswith("$")
    corps = motif[:-1] if ancre else motif
    if _glob(corps if ancre else corps + "*", chemin):
        return len(motif)
    return -1


def groupe_pour(regle: RegleRobots, agent: str) -> Groupe | None:
    """Le groupe qui s'applique au robot `agent` : le jeton contenu dans son nom le plus long, sinon `*`."""
    nom = agent.lower()
    meilleur, longueur = None, -1
    for groupe in regle.groupes:
        for jeton in groupe.agents:
            if jeton != "*" and jeton in nom and len(jeton) > longueur:
                meilleur, longueur = groupe, len(jeton)
    if meilleur is not None:
        return meilleur
    # Tous les groupes `*` (déclarés plusieurs fois) valent un seul : on prend le premier.
    for groupe in regle.groupes:
        if "*" in groupe.agents:
            return groupe
    return None


def autorise(regle: RegleRobots, agent: str, chemin: str) -> bool:
    """Le robot `agent` peut-il demander `chemin` (chemin + requête, commençant par `/`) ?"""
    if regle.etat == "absent":
        return True
    if regle.etat != "lu":
        return False
    if not chemin.startswith("/"):
        chemin = "/" + chemin
    groupe = groupe_pour(regle, agent)
    if groupe is None:
        return True
    meilleur_allow = max((_correspond(m, chemin) for t, m in groupe.regles if t == "allow"), default=-1)
    meilleur_disallow = max((_correspond(m, chemin) for t, m in groupe.regles if t == "disallow"), default=-1)
    if meilleur_disallow < 0:
        return True
    return meilleur_allow >= meilleur_disallow


def delai_exige_s(regle: RegleRobots, agent: str) -> int | None:
    groupe = groupe_pour(regle, agent) if regle.etat == "lu" else None
    return groupe.crawl_delay_s if groupe else None


def agents_declares(regle: RegleRobots) -> Sequence[str]:
    return sorted({a for g in regle.groupes for a in g.agents})


__all__ = ["CRAWL_DELAY_MAX_S", "Groupe", "RegleRobots", "TAILLE_MAX", "agents_declares", "analyser", "autorise",
           "delai_exige_s", "groupe_pour"]
