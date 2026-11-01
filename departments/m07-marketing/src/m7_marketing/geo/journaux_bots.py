"""Visites des robots d'IA dans les journaux d'accès du CLIENT (format « combined » ou « common »).

C'est la mesure GEO de source primaire (R4 §4.4) : combien de fois OAI-SearchBot, PerplexityBot, ClaudeBot… ont
demandé des pages du site du client, par jour UTC, par classe de statut et par groupe de chemins.

Minimisation (Loi 25) : une adresse IP est un renseignement personnel. AUCUNE adresse n'est conservée, renvoyée ni
écrite : elle est lue au début de la ligne, comparée aux plages publiées SI l'appelant en fournit
(`PlagesIPPubliees`, avec leur source et leur date : il n'y a AUCUNE plage par défaut), puis jetée. Sans plages,
chaque décompte porte `verification = "agent_seulement"` : un agent utilisateur se falsifie, le décompte est un
indice, pas une preuve. Les chemins sont ramenés à leur premier segment, sans chaîne de requête ni fragment.

Bornes (jamais de troncature silencieuse) : 2 Mo et 100 000 lignes au total, 8 Kio par ligne (une ligne plus longue est
comptée illisible SANS être analysée : pas de regex, découpage linéaire). Une ligne illisible est comptée, jamais
devinée.

Module pur : le texte du journal est fourni par l'appelant ; `ipaddress` (stdlib) ne fait aucune résolution réseau.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from .robots_ia import PAR_NOM, ROBOTS_IA, ErreurGeo

OCTETS_MAX = 2 * 1024 * 1024
LIGNES_MAX = 100_000
LIGNE_MAX = 8192
GROUPES_MAX_PAR_ROBOT = 50
_MOIS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}
_MINUSCULES = tuple((r.nom.lower(), r) for r in sorted(ROBOTS_IA, key=lambda r: -len(r.nom)))


class PlagesIPPubliees(Protocol):
    """Les plages d'adresses PUBLIÉES par les éditeurs de robots, fournies par l'appelant avec leur origine."""

    source: str
    date: str

    def appartient(self, robot: str, ip: str) -> bool | None:
        """Vrai/faux si `robot` a des plages connues ; None si l'adresse est illisible."""


class PlagesDeclarees:
    """Implémentation de test et d'usage : un dictionnaire robot -> liste de CIDR que l'appelant a COPIÉ de la page
    publiée
    de l'éditeur (`source`, `date`). Aucune plage n'est livrée avec le dépôt."""

    def __init__(self, plages: Mapping[str, list[str]], *, source: str, date: str) -> None:
        if not isinstance(source, str) or not source.strip() or not isinstance(date, str) or not date.strip():
            raise ErreurGeo("REJ-GEO-PLAGES-SANS-SOURCE", "des plages sans source ni date ne prouvent rien")
        self.source, self.date = source.strip(), date.strip()
        self._reseaux: dict[str, list[Any]] = {}
        for robot, cidrs in plages.items():
            if robot not in PAR_NOM:
                raise ErreurGeo("REJ-GEO-PLAGES-ROBOT-INCONNU", f"robot hors de la liste fermée : {robot!r}")
            try:
                self._reseaux[robot] = [ipaddress.ip_network(c, strict=True) for c in cidrs]
            except ValueError:
                raise ErreurGeo("REJ-GEO-PLAGES-INVALIDES", f"plage illisible pour {robot}") from None

    def appartient(self, robot: str, ip: str) -> bool | None:
        try:
            adresse = ipaddress.ip_address(ip)
        except ValueError:
            return None
        return any(adresse in r for r in self._reseaux.get(robot, ()) if r.version == adresse.version)


def _citation(ligne: str, depart: int) -> tuple[str, int] | None:
    """Le texte entre guillemets à partir de `depart` (qui doit pointer un guillemet) et la position suivante ;
    `\\"` et `\\\\`
    sont des échappements. Linéaire."""
    if depart >= len(ligne) or ligne[depart] != '"':
        return None
    morceaux, i = [], depart + 1
    while i < len(ligne):
        c = ligne[i]
        if c == "\\" and i + 1 < len(ligne):
            morceaux.append(ligne[i + 1])
            i += 2
        elif c == '"':
            return "".join(morceaux), i + 1
        else:
            morceaux.append(c)
            i += 1
    return None


def _jour_utc(horodatage: str) -> str | None:
    """`31/Oct/2026:12:00:01 -0400` -> `2026-10-31` en UTC ; None si illisible."""
    try:
        date_heure, zone = horodatage.split(" ")
        jour, mois, reste = date_heure.split("/")
        annee, heure, minute, seconde = reste.split(":")
        if len(zone) != 5 or zone[0] not in "+-":
            return None
        decalage = timedelta(hours=int(zone[1:3]), minutes=int(zone[3:5]))
        instant = datetime(int(annee), _MOIS[mois], int(jour), int(heure), int(minute), int(seconde),
                           tzinfo=UTC) - (decalage if zone[0] == "+" else -decalage)
        return instant.date().isoformat()
    except (ValueError, KeyError):
        return None


def _decouper(ligne: str) -> tuple[str, str, str, int, str | None] | None:
    """(ip, jour UTC, chemin, statut, agent ou None) ; None si la ligne n'est pas lisible."""
    i = ligne.find(" ")
    if i <= 0:
        return None
    ip = ligne[:i]
    debut, fin = ligne.find("[", i), ligne.find("]", i)
    if debut == -1 or fin == -1 or fin < debut:
        return None
    jour = _jour_utc(ligne[debut + 1:fin])
    requete = _citation(ligne, fin + 2) if ligne[fin + 1:fin + 2] == " " else None
    if jour is None or requete is None:
        return None
    texte_requete, position = requete
    morceaux = texte_requete.split(" ")
    if len(morceaux) < 2 or not morceaux[0].isalpha():
        return None
    cible = morceaux[1]
    absolue = cible.startswith(("http://", "https://"))
    chemin = urlsplit(cible).path if absolue else cible.split("?", 1)[0].split("#", 1)[0]
    if not chemin.startswith("/"):
        return None
    reste = ligne[position:].lstrip(" ")
    jeton = reste.split(" ", 1)[0]
    if not jeton.isdigit() or len(jeton) != 3:
        return None
    statut = int(jeton)
    agent = None
    suite = reste.split(" ", 2)[2] if reste.count(" ") >= 2 else ""
    if suite.startswith('"'):
        referent = _citation(suite, 0)
        if referent is not None:
            ua = _citation(suite, referent[1] + 1) if suite[referent[1]:referent[1] + 1] == " " else None
            agent = ua[0] if ua else None
    return ip, jour, chemin, statut, agent


def _groupe(chemin: str) -> str:
    segment = chemin.strip("/").split("/", 1)[0]
    if not segment:
        return "/"
    return "/" + "".join(c if c.isalnum() or c in "._~-" else "_" for c in segment)[:60]


def _robot_de(agent: str) -> str | None:
    bas = agent.lower()
    for nom_bas, robot in _MINUSCULES:
        if nom_bas in bas:
            return robot.nom
    return None


def analyser_journaux(texte: str, plages: PlagesIPPubliees | None = None) -> dict[str, Any]:
    """Décomptes des robots d'IA connus. Voir le module pour les bornes et la minimisation."""
    if not isinstance(texte, str):
        raise ErreurGeo("REJ-GEO-JOURNAL-INVALIDE", "texte du journal attendu")
    if len(texte.encode("utf-8")) > OCTETS_MAX:
        raise ErreurGeo("REJ-GEO-JOURNAL-TROP-GROS",
            f"journal de plus de {OCTETS_MAX} octets : le découper (rien n'est "
                        "tronqué en silence)")
    lignes = texte.splitlines()
    if len(lignes) > LIGNES_MAX:
        raise ErreurGeo("REJ-GEO-JOURNAL-TROP-GROS", f"journal de plus de {LIGNES_MAX} lignes : le découper")
    robots: dict[str, dict[str, Any]] = {}
    lisibles = illisibles = sans_agent = autres = 0
    jours_couverts: dict[str, int] = {}
    premier = dernier = None
    for ligne in lignes:
        if not ligne.strip():
            continue
        if len(ligne) > LIGNE_MAX:
            illisibles += 1
            continue
        lu = _decouper(ligne)
        if lu is None:
            illisibles += 1
            continue
        ip, jour, chemin, statut, agent = lu
        lisibles += 1
        jours_couverts[jour] = jours_couverts.get(jour, 0) + 1
        premier, dernier = min(premier or jour, jour), max(dernier or jour, jour)
        if agent is None:
            sans_agent += 1
            continue
        nom = _robot_de(agent)
        if nom is None:
            autres += 1
            continue
        bilan = robots.setdefault(nom, {"total": 0, "par_jour": {}, "par_statut": {}, "par_groupe_chemin": {},
                                        "detail_jour": {}, "ip_verifiees": 0, "ip_non_verifiees": 0,
                                        "ip_illisibles": 0})
        bilan["total"] += 1
        bilan["par_jour"][jour] = bilan["par_jour"].get(jour, 0) + 1
        classe = f"{statut // 100}xx"
        bilan["par_statut"][classe] = bilan["par_statut"].get(classe, 0) + 1
        detail = bilan["detail_jour"].setdefault(jour, {"visites": 0, "ip_verifiees": 0, "ok_2xx": 0,
                                                       "redirections_3xx": 0, "erreurs_4xx": 0, "erreurs_5xx": 0})
        detail["visites"] += 1
        cle_classe = {"2xx": "ok_2xx", "3xx": "redirections_3xx", "4xx": "erreurs_4xx",
            "5xx": "erreurs_5xx"}.get(classe)
        if cle_classe:
            detail[cle_classe] += 1
        groupe = _groupe(chemin)
        if groupe not in bilan["par_groupe_chemin"] and len(bilan["par_groupe_chemin"]) >= GROUPES_MAX_PAR_ROBOT:
            groupe = "(autres)"
        bilan["par_groupe_chemin"][groupe] = bilan["par_groupe_chemin"].get(groupe, 0) + 1
        if plages is not None:
            verdict = plages.appartient(nom, ip)  # l'adresse n'est utilisée que pour ce calcul, puis jetée
            cle = "ip_illisibles" if verdict is None else "ip_verifiees" if verdict else "ip_non_verifiees"
            bilan[cle] += 1
            if verdict:
                detail["ip_verifiees"] += 1
    resultat_robots = []
    for nom in sorted(robots):
        b = robots[nom]
        resultat_robots.append({
            "robot": nom, "categorie": PAR_NOM[nom].categorie, "total": b["total"],
            "par_jour": dict(sorted(b["par_jour"].items())), "par_statut": dict(sorted(b["par_statut"].items())),
            "par_groupe_chemin": dict(sorted(b["par_groupe_chemin"].items())),
            "detail_jour": {j: b["detail_jour"][j] for j in sorted(b["detail_jour"])},
            "verification": ("agent_seulement" if plages is None else
                             {"mode": "ip_verifiee", "ip_verifiees": b["ip_verifiees"],
                              "ip_non_verifiees": b["ip_non_verifiees"], "ip_illisibles": b["ip_illisibles"]}),
        })
    return {
        "type": "VISITES_ROBOTS_IA",
        "lignes": {"total": lisibles + illisibles, "lisibles": lisibles, "illisibles": illisibles,
                   "sans_agent": sans_agent, "autres_agents": autres},
        "periode": {"debut": premier, "fin": dernier} if premier else None,
        "jours_couverts": dict(sorted(jours_couverts.items())),
        "robots": resultat_robots,
        "plages": {"source": plages.source, "date": plages.date} if plages is not None else None,
        "avertissements": [
            "Aucune adresse IP n'est conservée ni renvoyée (Loi 25, minimisation).",
            ("Sans plages publiées, un agent utilisateur se falsifie : décomptes indicatifs (agent_seulement)."
             if plages is None else
             "Appartenance aux plages calculée avec les plages fournies par l'appelant ; une plage périmée donne des "
             "faux négatifs."),
            "Une visite d'un robot n'est ni une citation ni une garantie d'apparition dans une réponse d'IA.",
        ],
    }


def lignes_visites(analyse: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Les lignes à importer comme faits `visites_robots_ia` (une par robot et par jour, plus une ligne de
    COUVERTURE par
    jour lu : un jour sans visite d'un robot n'a ainsi pas de fait robot, mais la couverture prouve que le journal
    l'a vu)."""
    lignes: list[dict[str, Any]] = []
    for jour, nombre in analyse["jours_couverts"].items():
        lignes.append({"robot": "journal_couverture", "jour": jour, "visites": 0, "lignes_lues": nombre,
                       "ip_verifiees": 0, "ok_2xx": 0, "redirections_3xx": 0, "erreurs_4xx": 0, "erreurs_5xx": 0})
    for r in analyse["robots"]:
        for jour, d in r["detail_jour"].items():
            lignes.append({"robot": r["robot"], "jour": jour, "visites": d["visites"], "lignes_lues": 0,
                           "ip_verifiees": d["ip_verifiees"], "ok_2xx": d["ok_2xx"],
                           "redirections_3xx": d["redirections_3xx"], "erreurs_4xx": d["erreurs_4xx"],
                           "erreurs_5xx": d["erreurs_5xx"]})
    return lignes


__all__ = ["GROUPES_MAX_PAR_ROBOT", "LIGNES_MAX", "LIGNE_MAX", "OCTETS_MAX", "PlagesDeclarees", "PlagesIPPubliees",
           "analyser_journaux", "lignes_visites"]
