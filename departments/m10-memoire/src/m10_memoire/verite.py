"""Ordre de vérité de M10 : QUELLE source l'emporte quand deux mémoires se contredisent.

L'ordre est une DONNÉE (`contracts/ordre-verite.v1.json`, tiré du condensé de Nathan : constitution > décisions
explicites du propriétaire > matrice vivante > rapports récents validés > tests et sondes > code > documentation >
journaux > mémoires anciennes > hypothèses). Ce module ne connaît AUCUNE classe par son nom : il lit la position dans la
liste, les classes qui rendent une contradiction critique, les vocabulaires de sujets et les classes de fichiers du
dépôt. Changer l'ordre, c'est changer le fichier ; son empreinte entre dans chaque contradiction rangée, de sorte
qu'on sait toujours selon QUEL ordre une proposition a été faite.

Ce module ne tranche rien : `resoudre` PROPOSE (`retenue` = le côté de plus haute autorité, ou personne en cas
d'égalité) et dit si la contradiction est critique. Appliquer, c'est `contradictions.py` (marques) et, pour une
contradiction critique, une personne (N3).

Module pur (DA-M10-08) : seule lecture de fichier, celle du contrat de données ; aucun import d'``opsys``.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "opsys.m10.ordre_verite/v1"
CHEMIN_DEFAUT = Path(__file__).resolve().parents[2] / "contracts" / "ordre-verite.v1.json"


def domaines() -> tuple[str, ...]:
    """Les deux domaines, jamais mêlés (ADR-0012). Une fonction, pas une constante publique : les gardes de conformité
    traitent une tuple en MAJUSCULES comme un énuméré métier."""
    return ("affaires", "developpement")


def canaux() -> tuple[str, ...]:
    return ("agent", "humain", "ingestion")


def genres_fichier() -> tuple[str, ...]:
    return ("directive", "adr", "regle", "matrice", "condense", "document")


REJ_ORDRE_INVALIDE = "REJ-VERITE-ORDRE-INVALIDE"

_ID_CLASSE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_ADMISSION = re.compile(r"^(affaires|developpement):(agent|humain|ingestion)$")
_FAMILLE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_CHAMPS = {"schema", "version", "source", "avertissement", "classes", "criticite", "sujets", "sources_fichiers"}


def _refus(detail: str) -> ValueError:
    return ValueError(f"{REJ_ORDRE_INVALIDE}: {detail}")


@dataclasses.dataclass(frozen=True)
class OrdreVerite:
    version: str
    empreinte: str
    classes: tuple[str, ...]  # de la plus haute autorité à la plus basse
    admission: Mapping[str, frozenset[str]]  # classe -> {"domaine:canal"}
    classes_critiques: frozenset[str]
    attributs_critiques: frozenset[str]
    familles_sujet: Mapping[str, tuple[str, ...]]  # domaine -> familles de sujet admises
    sources_fichiers: tuple[tuple[str, str, str], ...]  # (motif, classe, genre), premier qui correspond

    def rang(self, classe: str) -> int:
        """0 = la plus haute autorité. `ValueError` si la classe n'est pas déclarée (fail-closed)."""
        try:
            return self.classes.index(classe)
        except ValueError:
            raise _refus(f"classe de source inconnue : {classe!r}") from None

    def connait(self, classe: Any) -> bool:
        return isinstance(classe, str) and classe in self.classes

    def admet(self, classe: str, domaine: str, canal: str) -> bool:
        """Cette classe peut-elle être émise dans ce domaine par ce canal ? Une classe haute ne s'obtient pas en la
        déclarant : seul le canal prévu (ingestion d'un fichier du dépôt, personne identifiée) la donne."""
        return f"{domaine}:{canal}" in self.admission.get(classe, frozenset())

    def classement(self, chemin: str) -> tuple[int, str, str] | None:
        """`(position du motif, classe, genre)` d'un fichier du dépôt d'après sa place, ou `None` (hors périmètre). La
        position sert à traiter les fichiers les plus précis d'abord."""
        for position, (motif, classe, genre) in enumerate(self.sources_fichiers):
            if fnmatch.fnmatchcase(chemin, motif):
                return position, classe, genre
        return None

    def classe_de_fichier(self, chemin: str) -> tuple[str, str] | None:
        """`(classe, genre)` d'un fichier du dépôt d'après sa place, ou `None` (fichier hors du périmètre)."""
        trouve = self.classement(chemin)
        return None if trouve is None else (trouve[1], trouve[2])


def empreinte_donnees(donnees: Any) -> str:
    return hashlib.sha256(
        json.dumps(donnees, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def depuis_dict(donnees: Any) -> OrdreVerite:
    """Valide (schéma fermé) puis construit l'ordre. Un défaut est un refus nommé, jamais une valeur supposée."""
    if not isinstance(donnees, Mapping) or donnees.get("schema") != SCHEMA:
        raise _refus(f"schéma attendu {SCHEMA!r}")
    inconnus = set(donnees) - _CHAMPS
    if inconnus:
        raise _refus(f"champ(s) inconnu(s) : {sorted(map(str, inconnus))}")
    version = donnees.get("version")
    if not isinstance(version, str) or not version.strip():
        raise _refus("version requise")
    brutes = donnees.get("classes")
    if not isinstance(brutes, list) or not brutes:
        raise _refus("liste de classes requise")
    classes: list[str] = []
    admission: dict[str, frozenset[str]] = {}
    for i, classe in enumerate(brutes):
        if not isinstance(classe, Mapping) or set(classe) - {"id", "libelle", "admission"}:
            raise _refus(f"classes[{i}] : {{id, libelle, admission}} attendu")
        ident = classe.get("id")
        if not isinstance(ident, str) or not _ID_CLASSE.fullmatch(ident) or ident in classes:
            raise _refus(f"classes[{i}] : identifiant invalide ou en double")
        voies = classe.get("admission")
        if (
            not isinstance(voies, list)
            or not voies
            or not all(isinstance(v, str) and _ADMISSION.fullmatch(v) for v in voies)
        ):
            raise _refus(f"classes[{i}] ({ident}) : admission « domaine:canal » requise")
        classes.append(ident)
        admission[ident] = frozenset(voies)
    critique = donnees.get("criticite")
    if not isinstance(critique, Mapping) or set(critique) != {"classes", "attributs"}:
        raise _refus("criticite : {classes, attributs} attendu")
    classes_critiques = critique["classes"]
    attributs_critiques = critique["attributs"]
    if (
        not isinstance(classes_critiques, list)
        or not all(c in classes for c in classes_critiques)
        or not isinstance(attributs_critiques, list)
        or not all(isinstance(a, str) and _FAMILLE.fullmatch(a) for a in attributs_critiques)
    ):
        raise _refus("criticite : classes déclarées et attributs en minuscules attendus")
    sujets = donnees.get("sujets")
    if (
        not isinstance(sujets, Mapping)
        or set(sujets) != set(domaines())
        or not all(
            isinstance(v, list) and v and all(isinstance(f, str) and _FAMILLE.fullmatch(f) for f in v)
            for v in sujets.values()
        )
    ):
        raise _refus("sujets : une liste de familles par domaine (affaires, developpement) attendue")
    fichiers: list[tuple[str, str, str]] = []
    for i, entree in enumerate(donnees.get("sources_fichiers", [])):
        if (
            not isinstance(entree, Mapping)
            or set(entree) != {"motif", "classe", "genre"}
            or not isinstance(entree["motif"], str)
            or not entree["motif"]
            or entree["classe"] not in classes
            or entree["genre"] not in genres_fichier()
            or "developpement:ingestion" not in admission[entree["classe"]]
        ):
            raise _refus(f"sources_fichiers[{i}] : motif, classe déclarée (admise par ingestion) et genre attendus")
        fichiers.append((entree["motif"], entree["classe"], entree["genre"]))
    return OrdreVerite(
        version=version,
        empreinte=empreinte_donnees(dict(donnees)),
        classes=tuple(classes),
        admission=admission,
        classes_critiques=frozenset(classes_critiques),
        attributs_critiques=frozenset(attributs_critiques),
        familles_sujet={d: tuple(sujets[d]) for d in domaines()},
        sources_fichiers=tuple(fichiers),
    )


def charger(chemin: Path | str | None = None) -> OrdreVerite:
    try:
        texte = Path(chemin or CHEMIN_DEFAUT).read_text(encoding="utf-8")
        donnees = json.loads(texte)
    except (OSError, ValueError) as exc:
        raise _refus(f"fichier d'ordre illisible : {type(exc).__name__}") from None
    return depuis_dict(donnees)


def resoudre(gauche: Mapping[str, Any], droite: Mapping[str, Any], attribut: str, ordre: OrdreVerite) -> dict[str, Any]:
    """Propose une résolution entre deux affirmations (chacune porte sa `classe`). Ne modifie rien.

    - `retenue` : `"a"` (gauche) ou `"b"` (droite) si les rangs diffèrent, `None` si les classes sont de même rang ;
    - `regle` : `ordre_verite` ou `egalite_de_rang` ;
    - `critique` : une classe critique est en jeu, ou l'attribut est critique : une personne devra valider ;
    - `motifs_criticite` : pourquoi."""
    rang_a, rang_b = ordre.rang(gauche["classe"]), ordre.rang(droite["classe"])
    motifs = [
        f"classe_{cote}:{brut['classe']}"
        for cote, brut in (("a", gauche), ("b", droite))
        if brut["classe"] in ordre.classes_critiques
    ]
    if attribut in ordre.attributs_critiques:
        motifs.append(f"attribut:{attribut}")
    if rang_a == rang_b:
        retenue, regle = None, "egalite_de_rang"
    else:
        retenue, regle = ("a" if rang_a < rang_b else "b"), "ordre_verite"
    return {"retenue": retenue, "regle": regle, "critique": bool(motifs), "motifs_criticite": motifs}
