"""Graphe d'impacts M9.2 : relations métier justifiées par des champs réellement capturés, propagation sans quantité.

Module pur. Une ``Regle`` déclare, pour une lecture du catalogue, quelle liste de lignes de la réponse relie deux objets
(champ source → champ cible) et dans quel sens un changement se propage. Le graphe ne contient QUE ce que des captures
complètes, acceptées et non contradictoires prouvent : chaque arête cite sa règle, sa version, la capture (rang et
empreinte) et la ligne d'où elle vient. Une règle dont la lecture est absente, refusée, partielle ou contradictoire est
INCONNUE : elle n'ajoute aucune arête et sa liste accompagne toute propagation — l'absence d'impact n'est affirmée nulle
part
tant qu'un lien pertinent est inconnu.

La propagation dit QUI est relié et par quel chemin, jamais combien : aucune quantité, aucun montant, aucune date
promise ni
causalité n'est produite ici (les calculs restent chez M5, M4, M6, M8). Un lien est une relation de données déclarée par
le
producteur, pas une preuve que l'effet se produira.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import deque
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs

VERSION_RELATIONS = "2026-10-28.1"
SENS = frozenset({"de->vers", "vers->de", "bidirectionnel"})
MAX_PROFONDEUR = 8
MAX_NOEUDS = 5000
MAX_ARETES = 20000
_LIMITES = (
    "Un lien est une relation de données déclarée par un producteur : ni causalité établie, ni quantité, ni date "
    "promise.",
    "L'absence d'impact n'est pas affirmée tant que des règles pertinentes sont inconnues (lecture absente, refusée, "
    "partielle).",
)


@dataclasses.dataclass(frozen=True)
class Regle:
    id: str
    relation: str
    lecture_id: str
    lignes: str  # chemin (syntaxe capture_strategique.extraire) vers la liste de lignes reliant deux objets
    de_kind: str
    de_champ: str
    vers_kind: str
    vers_champ: str
    sens: str = "de->vers"  # direction dans laquelle un changement de ``de``/``vers`` se propage
    version: str = VERSION_RELATIONS
    # Lignes IMBRIQUÉES : ``sous_lignes`` (chemin relatif à chaque ligne) donne des lignes enfants ; un champ
    # préfixé par « ^ » est lu sur la ligne PARENT. Le lien n'est justifié que par l'imbrication déclarée.
    sous_lignes: str | None = None

    def __post_init__(self) -> None:
        if self.sens not in SENS:
            raise ValueError(f"{self.id} : sens inconnu")
        if not all(
            type(valeur) is str and valeur
            for valeur in (self.id, self.relation, self.lecture_id, self.lignes, self.de_kind, self.vers_kind)
        ):
            raise ValueError(f"{self.id} : règle incomplète")


def _noeud(kind: str, identifiant: str) -> str:
    return f"{kind}:{identifiant}"


def _champ(nom: str, enfant: Mapping, parent: Mapping) -> object:
    """Valeur du champ ``nom`` sur la ligne enfant, ou sur la ligne parent si le nom est préfixé par « ^ »."""
    return parent.get(nom[1:]) if nom.startswith("^") else enfant.get(nom)


def _texte_id(valeur: object) -> str | None:
    if type(valeur) is int:
        return str(valeur)
    if type(valeur) is str and valeur.strip() == valeur and 0 < len(valeur) <= 128:
        return valeur
    return None


def _dernieres_par_arguments(captures: Sequence[Mapping], lecture_id: str) -> list[Mapping]:
    """La dernière capture connue de chaque jeu d'arguments distinct de la lecture (ordre de rang)."""
    derniere: dict[str, Mapping] = {}
    for capture in captures:
        if capture["lecture_id"] == lecture_id:
            derniere[capture["arguments_sha256"]] = capture
    return sorted(derniere.values(), key=lambda capture: capture["index"])


def construire(captures: Sequence[Mapping], regles: Sequence[Regle], *, connaissance: str) -> dict:
    """Graphe connu à ``connaissance`` : une arête par ligne qui relie deux identifiants valides.

    Pour chaque règle, chaque jeu d'arguments lu est évalué sur sa DERNIÈRE capture connue : absente, refusée, partielle
    ou contradictoire, ce jeu est inconnu (jamais remplacé par une capture plus ancienne)."""
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    noeuds: dict[str, dict] = {}
    aretes: dict[str, dict] = {}
    actives, inconnues = [], []
    for regle in regles:
        groupes = _dernieres_par_arguments(connues, regle.lecture_id)
        if not groupes:
            inconnues.append(_inconnue(regle, "ABSENTE", None))
            continue
        ecartees = creees = lus = 0
        for derniere in groupes:
            raison = None
            if derniere["verdict"] != "ACCEPTEE":
                raison = "REFUSEE"
            elif (regle.lecture_id, derniere["arguments_sha256"]) in en_conflit:
                raison = "CONTRADICTOIRE"
            elif not derniere["complete"]:
                # Les liens reçus sont réels et gardés ; la règle reste INCONNUE (des liens peuvent manquer).
                inconnues.append(_inconnue(regle, "PARTIELLE", derniere["arguments_sha256"]))
            if raison is not None:
                inconnues.append(_inconnue(regle, raison, derniere["arguments_sha256"]))
                continue
            lus += 1
            for numero_page, page in enumerate(derniere["pages"]):
                for numero, ligne in enumerate(cs.extraire(page, regle.lignes)):
                    if not isinstance(ligne, Mapping):
                        ecartees += 1
                        continue
                    if regle.sous_lignes is None:
                        enfants: list[tuple[int | None, object]] = [(None, ligne)]
                    else:
                        enfants = list(enumerate(cs.extraire(ligne, regle.sous_lignes)))
                    for sous_numero, enfant in enfants:
                        if not isinstance(enfant, Mapping):
                            ecartees += 1
                            continue
                        de = _texte_id(_champ(regle.de_champ, enfant, ligne))
                        vers = _texte_id(_champ(regle.vers_champ, enfant, ligne))
                        if de is None or vers is None:
                            ecartees += 1
                            continue
                        a, b = _noeud(regle.de_kind, de), _noeud(regle.vers_kind, vers)
                        noeuds.setdefault(a, {"kind": regle.de_kind, "id": de})
                        noeuds.setdefault(b, {"kind": regle.vers_kind, "id": vers})
                        identifiant = hashlib.sha256(
                            f"{regle.id}|{regle.version}|{a}|{b}|{derniere['hash_maillon']}".encode()
                        ).hexdigest()[:20]
                        if identifiant not in aretes:
                            aretes[identifiant] = {
                                "id": identifiant,
                                "de": a,
                                "vers": b,
                                "relation": regle.relation,
                                "sens": regle.sens,
                                "regle": regle.id,
                                "version_regle": regle.version,
                                "preuve": {
                                    "capture_index": derniere["index"],
                                    "capture_hash": derniere["hash_maillon"],
                                    "page": numero_page,
                                    "ligne": numero,
                                    "chemin": regle.lignes,
                                    **(
                                        {"sous_ligne": sous_numero, "sous_chemin": regle.sous_lignes}
                                        if sous_numero is not None
                                        else {}
                                    ),
                                },
                            }
                            creees += 1
        if lus:
            actives.append(
                {"regle": regle.id, "lecture_id": regle.lecture_id, "aretes": creees, "lignes_ecartees": ecartees}
            )
        if len(noeuds) > MAX_NOEUDS or len(aretes) > MAX_ARETES:
            raise ValueError("REJ-GRAPHE-BORNE : graphe au-delà de la borne, réduire les lectures")
    graphe = {
        "type": "GRAPHE_IMPACTS",
        "version_relations": VERSION_RELATIONS,
        "connaissance": connaissance,
        "noeuds": [noeuds[cle] | {"ref": cle} for cle in sorted(noeuds)],
        "aretes": sorted(aretes.values(), key=lambda a: a["id"]),
        "regles_actives": actives,
        "regles_inconnues": inconnues,
        "limites": list(_LIMITES),
    }
    graphe["graphe_id"] = hashlib.sha256(
        json.dumps(graphe, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return graphe


def _inconnue(regle: Regle, raison: str, arguments_sha256: str | None) -> dict:
    return {
        "regle": regle.id,
        "lecture_id": regle.lecture_id,
        "raison": raison,
        "arguments_sha256": arguments_sha256,
        "kinds": [regle.de_kind, regle.vers_kind],
    }


def _voisins(graphe: Mapping) -> dict[str, list[tuple[str, dict]]]:
    adjacence: dict[str, list[tuple[str, dict]]] = {}
    for arete in graphe["aretes"]:
        if arete["sens"] in ("de->vers", "bidirectionnel"):
            adjacence.setdefault(arete["de"], []).append((arete["vers"], arete))
        if arete["sens"] in ("vers->de", "bidirectionnel"):
            adjacence.setdefault(arete["vers"], []).append((arete["de"], arete))
    for liste in adjacence.values():
        liste.sort(key=lambda couple: (couple[0], couple[1]["id"]))
    return adjacence


def propager(
    graphe: Mapping,
    kind: str,
    identifiant: str,
    *,
    relations: Sequence[str] | None = None,
    profondeur_max: int = 4,
) -> dict:
    """Objets atteignables depuis ``kind:identifiant`` dans le sens d'impact, plus court chemin d'abord (déterministe).

    Un nœud de départ absent du graphe est REFUSÉ (« inconnu »), jamais rendu comme « aucun impact »."""
    if type(profondeur_max) is not int or not 1 <= profondeur_max <= MAX_PROFONDEUR:
        raise ValueError(f"REJ-GRAPHE-PROFONDEUR : entier entre 1 et {MAX_PROFONDEUR} requis")
    depart = _noeud(kind, identifiant)
    connus = {noeud["ref"] for noeud in graphe["noeuds"]}
    if depart not in connus:
        raise ValueError("REJ-GRAPHE-NOEUD-INCONNU : objet absent du graphe connu ; aucun impact n'est affirmé")
    filtre = set(relations) if relations is not None else None
    adjacence = _voisins(graphe)
    vus = {depart: 0}
    chemins: dict[str, list[str]] = {depart: []}
    file = deque([depart])
    while file:
        courant = file.popleft()
        if vus[courant] >= profondeur_max:
            continue
        for voisin, arete in adjacence.get(courant, ()):
            if filtre is not None and arete["relation"] not in filtre:
                continue
            if voisin in vus:
                continue
            vus[voisin] = vus[courant] + 1
            chemins[voisin] = [*chemins[courant], arete["id"]]
            file.append(voisin)
    par_ref = {noeud["ref"]: noeud for noeud in graphe["noeuds"]}
    impacts = [
        {
            "objet": {"kind": par_ref[ref]["kind"], "id": par_ref[ref]["id"]},
            "distance": distance,
            "chemin": chemins[ref],
        }
        for ref, distance in sorted(vus.items(), key=lambda element: (element[1], element[0]))
        if ref != depart
    ]
    kinds = {par_ref[ref]["kind"] for ref in vus}
    pertinentes = [r for r in graphe["regles_inconnues"] if set(r["kinds"]) & kinds]
    return {
        "type": "PROPAGATION_IMPACTS",
        "graphe_id": graphe["graphe_id"],
        "depart": {"kind": kind, "id": identifiant},
        "profondeur_max": profondeur_max,
        "impacts": impacts,
        "regles_inconnues_pertinentes": pertinentes,
        "complet": not pertinentes,
        "limites": list(_LIMITES),
    }
