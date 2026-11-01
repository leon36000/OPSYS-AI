"""Règles du graphe partagées par TOUS les moteurs : transitions d'état, validité à une date, parcours borné.

Le stockage change d'un moteur à l'autre (SQL, mémoire) ; les règles, non. Le parcours en largeur (`voisinage`,
`chemin`)
ne demande au moteur qu'une chose : `incidentes(ids) -> arêtes vivantes touchant ces nœuds`. Le test de parité
(`tests/test_mnemo_graphe_parite.py`) vérifie que le filtre « vivante à cette date » de chaque stockage donne les mêmes
arêtes que `vivante` ci-dessous.

**Validité.** Deux temps distincts. La date demandée (`a_la_date`) est le temps du MONDE : l'arête est vivante si
`valide_de <= date` et (`valide_a` absent ou `date < valide_a`). L'état est ce que nous savons AUJOURD'HUI : seules les
arêtes confirmées (ou fermées, qui l'ont été) comptent ; un brouillon ne compte qu'à la demande expresse
(`inclure_brouillons`) et est alors marqué comme tel ; une arête rejetée ne compte jamais.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from .. import codes
from ..codes import ErreurMnemo
from .port import ARETES_MAX, K_MAX, NOEUDS_MAX, Arete, Chemin, Noeud

TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"brouillon"}),
    "brouillon": frozenset({"confirmee", "rejetee"}),
    "confirmee": frozenset({"fermee"}),
    "fermee": frozenset(),
    "rejetee": frozenset(),
}


def exiger_transition(courant: str | None, nouveau: str) -> None:
    if nouveau not in TRANSITIONS.get(courant, frozenset()):
        raise ErreurMnemo(codes.ARETE_TRANSITION, f"{courant or 'aucun état'} → {nouveau} n'est pas permis")


def vivante(etat: str, valide_de: str, valide_a: str | None, date: str, *, inclure_brouillons: bool) -> bool:
    if etat == "rejetee":
        return False
    if etat == "brouillon" and not inclure_brouillons:
        return False
    if valide_de > date:
        return False
    return valide_a is None or date < valide_a


def exiger_k(k: object) -> int:
    if type(k) is not int or not 1 <= k <= K_MAX:
        raise ErreurMnemo(codes.REQUETE_TROP_LARGE, f"k : entier de 1 à {K_MAX} sauts")
    return k


Incidentes = Callable[[Sequence[str]], Iterable[Arete]]


def _autre(arete: Arete, noeud_id: str) -> Noeud:
    return arete.vers if arete.de.noeud_id == noeud_id else arete.de


def parcourir(
    depart: Noeud, k: int, incidentes: Incidentes, *, types_arete: Sequence[str] | None, noeuds_max: int = NOEUDS_MAX
) -> tuple[tuple[tuple[Noeud, int], ...], tuple[Arete, ...], bool]:
    """Voisinage à `k` sauts (les arêtes se parcourent dans les deux sens), en largeur, borné. Rend
    `(nœuds avec distance, arêtes, tronqué)`. Le résultat est trié : même graphe, même sortie, sur toute machine."""
    k = exiger_k(k)
    noeuds_max = min(noeuds_max, NOEUDS_MAX)
    distance: dict[str, int] = {depart.noeud_id: 0}
    noeuds: dict[str, Noeud] = {depart.noeud_id: depart}
    aretes: dict[str, Arete] = {}
    front = [depart.noeud_id]
    tronque = False
    for niveau in range(1, k + 1):
        if not front:
            break
        suivants: list[str] = []
        for arete in sorted(incidentes(front), key=lambda a: a.arete_id):
            if types_arete is not None and arete.type not in types_arete:
                continue
            origine = arete.de.noeud_id if arete.de.noeud_id in front else arete.vers.noeud_id
            autre = _autre(arete, origine)
            if autre.noeud_id not in distance:
                if len(distance) >= noeuds_max:
                    tronque = True
                    continue
                distance[autre.noeud_id] = niveau
                noeuds[autre.noeud_id] = autre
                suivants.append(autre.noeud_id)
            if len(aretes) >= ARETES_MAX:
                tronque = True
                continue
            aretes[arete.arete_id] = arete
        front = suivants
    ordre = sorted(noeuds.values(), key=lambda n: (distance[n.noeud_id], n.type, n.cle))
    return (
        tuple((n, distance[n.noeud_id]) for n in ordre),
        tuple(sorted(aretes.values(), key=lambda a: a.arete_id)),
        tronque,
    )


def plus_court_chemin(de: Noeud, vers: Noeud, k_max: int, incidentes: Incidentes) -> Chemin | None:
    """Plus court chemin (largeur d'abord), départage déterministe par identifiant d'arête. `None` s'il n'y en a pas à
    `k_max` sauts au plus."""
    k_max = exiger_k(k_max)
    if de.noeud_id == vers.noeud_id:
        return Chemin((de,), ())
    parent: dict[str, tuple[str, Arete]] = {}
    vus = {de.noeud_id}
    noeuds: dict[str, Noeud] = {de.noeud_id: de, vers.noeud_id: vers}
    front = [de.noeud_id]
    for _ in range(k_max):
        if not front:
            return None
        suivants: list[str] = []
        for arete in sorted(incidentes(front), key=lambda a: a.arete_id):
            origine = arete.de.noeud_id if arete.de.noeud_id in front else arete.vers.noeud_id
            autre = _autre(arete, origine)
            if autre.noeud_id in vus:
                continue
            vus.add(autre.noeud_id)
            noeuds[autre.noeud_id] = autre
            parent[autre.noeud_id] = (origine, arete)
            if autre.noeud_id == vers.noeud_id:
                return _reconstruire(de, vers, parent, noeuds)
            suivants.append(autre.noeud_id)
        if len(vus) > 20 * NOEUDS_MAX:
            raise ErreurMnemo(codes.REQUETE_TROP_LARGE, "le parcours dépasse le plafond : précise la question")
        front = suivants
    return None


def _reconstruire(de: Noeud, vers: Noeud, parent: dict[str, tuple[str, Arete]], noeuds: dict[str, Noeud]) -> Chemin:
    suite_noeuds = [vers]
    suite_aretes: list[Arete] = []
    courant = vers.noeud_id
    while courant != de.noeud_id:
        precedent, arete = parent[courant]
        suite_aretes.append(arete)
        suite_noeuds.append(noeuds[precedent])
        courant = precedent
    return Chemin(tuple(reversed(suite_noeuds)), tuple(reversed(suite_aretes)))


def explication(arete: Arete, historique: Sequence[dict]) -> str:
    """Pourquoi ce lien, en une phrase construite par le code (jamais par un modèle)."""
    morceaux = [
        f"« {arete.type} » relie {arete.de.libelle} à {arete.vers.libelle} depuis le {arete.valide_de}"
        + (f" jusqu'au {arete.valide_a}" if arete.valide_a else ""),
        f"source : {arete.source_type} ({arete.source_ref}), origine {arete.origine}, confiance {arete.confiance}",
    ]
    for h in historique:
        qui = f"{h['par']} ({h['mode']}{', ' + h['role'] if h.get('role') else ''})"
        raison = f" — {h['raison']}" if h.get("raison") else ""
        morceaux.append(f"{h['etat']} le {h['quand'][:10]} par {qui}{raison}")
    if arete.sensible and arete.etat == "brouillon":
        morceaux.append("lien sensible (donnée personnelle) : en attente de la confirmation d'une personne")
    return " ; ".join(morceaux)
