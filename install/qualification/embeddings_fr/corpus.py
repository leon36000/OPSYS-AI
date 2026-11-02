"""Chargeur et validateur du corpus FICTIF (passages + requêtes jugées), et perturbation déterministe des requêtes.

Le chargeur refuse ce qui ferait mentir la mesure : corpus non déclaré fictif, identifiant en double, jugement vers un
passage inexistant, question « négative » avec un pertinent (ou l'inverse), adresse courriel réelle, texte vide ou
démesuré. Aucun accès réseau.
"""

from __future__ import annotations

import dataclasses
import hashlib
import random
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

SCHEMA_PASSAGES = "opsys.qualification.passages-embeddings-fr/v1"
SCHEMA_REQUETES = "opsys.qualification.requetes-embeddings-fr/v1"
TYPES_REQUETE = ("paraphrase", "reformulation", "synonyme_qc", "faute", "anglicisme", "abreviation", "nombre_unite",
                 "negative")
TEXTE_MAX = 1200
_ID_PASSAGE = re.compile(r"^[A-Z]{1,3}\d{3}$")
_ID_REQUETE = re.compile(r"^Q\d{3}$")
_COURRIEL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_DOMAINES_FICTIFS = ("example.test", "alunord.example.test")


class ErreurCorpus(ValueError):
    """Corpus refusé ; le message dit quoi corriger."""


@dataclasses.dataclass(frozen=True)
class Requete:
    identifiant: str
    type: str
    texte: str
    pertinents: frozenset[str]
    partiels: frozenset[str]

    @property
    def negative(self) -> bool:
        return not self.pertinents

    def gains(self) -> dict[str, float]:
        """Gain 2 pour un pertinent, 1 pour un partiel (nDCG gradué)."""
        return {**{i: 1.0 for i in self.partiels}, **{i: 2.0 for i in self.pertinents}}


@dataclasses.dataclass(frozen=True)
class Corpus:
    passages: dict[str, str]
    categories: dict[str, str]  # identifiant -> catégorie
    requetes: tuple[Requete, ...]
    empreinte: str  # SHA-256 du contenu canonique : identifie la version des jugements


def _lire_yaml(chemin: Path) -> dict[str, Any]:
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    if not isinstance(donnees, dict):
        raise ErreurCorpus(f"{chemin.name} : mapping attendu à la racine")
    if donnees.get("fictif") is not True:
        raise ErreurCorpus(f"{chemin.name} : « fictif: true » obligatoire")
    return donnees


def _verifier_courriels(texte: str, ou: str) -> None:
    for domaine in (m.group(1).lower() for m in _COURRIEL.finditer(texte)):
        if not domaine.endswith(".test"):
            raise ErreurCorpus(f"{ou} : adresse courriel non fictive ({domaine}) ; seuls les .test sont permis")


def charger_corpus(dossier: str | Path) -> Corpus:
    dossier = Path(dossier)
    fichiers = sorted(dossier.glob("passages_*.yaml"))
    if not fichiers:
        raise ErreurCorpus(f"{dossier} : aucun fichier passages_*.yaml")
    passages: dict[str, str] = {}
    categories: dict[str, str] = {}
    for fichier in fichiers:
        donnees = _lire_yaml(fichier)
        if donnees.get("schema") != SCHEMA_PASSAGES:
            raise ErreurCorpus(f"{fichier.name} : schéma {SCHEMA_PASSAGES} attendu")
        blocs = donnees.get("categories")
        if not isinstance(blocs, dict) or not blocs:
            raise ErreurCorpus(f"{fichier.name} : « categories » attendu")
        for categorie, contenu in blocs.items():
            if not isinstance(contenu, dict) or not contenu:
                raise ErreurCorpus(f"{fichier.name} : catégorie {categorie} vide ou mal formée")
            for identifiant, texte in contenu.items():
                if not isinstance(identifiant, str) or not _ID_PASSAGE.fullmatch(identifiant):
                    raise ErreurCorpus(f"{fichier.name} : identifiant de passage invalide : {identifiant!r}")
                if identifiant in passages:
                    raise ErreurCorpus(f"passage en double : {identifiant}")
                if not isinstance(texte, str) or not texte.strip() or len(texte) > TEXTE_MAX:
                    raise ErreurCorpus(f"{identifiant} : texte non vide de {TEXTE_MAX} caractères maximum")
                _verifier_courriels(texte, identifiant)
                passages[identifiant] = texte.strip()
                categories[identifiant] = str(categorie)
    donnees_q = _lire_yaml(dossier / "requetes.yaml")
    if donnees_q.get("schema") != SCHEMA_REQUETES or not isinstance(donnees_q.get("requetes"), list):
        raise ErreurCorpus(f"requetes.yaml : schéma {SCHEMA_REQUETES} et liste « requetes » attendus")
    requetes: list[Requete] = []
    vus: set[str] = set()
    for brut in donnees_q["requetes"]:
        if not isinstance(brut, dict):
            raise ErreurCorpus("requête mal formée")
        identifiant = brut.get("id")
        if not isinstance(identifiant, str) or not _ID_REQUETE.fullmatch(identifiant):
            raise ErreurCorpus(f"identifiant de requête invalide : {identifiant!r}")
        if identifiant in vus:
            raise ErreurCorpus(f"requête en double : {identifiant}")
        vus.add(identifiant)
        genre, texte = brut.get("type"), brut.get("texte")
        if genre not in TYPES_REQUETE:
            raise ErreurCorpus(f"{identifiant} : type parmi {', '.join(TYPES_REQUETE)}")
        if not isinstance(texte, str) or not texte.strip() or len(texte) > 300:
            raise ErreurCorpus(f"{identifiant} : texte de 1 à 300 caractères")
        _verifier_courriels(texte, identifiant)
        pertinents, partiels = brut.get("pertinents"), brut.get("partiels", [])
        if not isinstance(pertinents, list) or not isinstance(partiels, list):
            raise ErreurCorpus(f"{identifiant} : pertinents et partiels sont des listes")
        for ident in (*pertinents, *partiels):
            if ident not in passages:
                raise ErreurCorpus(f"{identifiant} : jugement vers un passage inexistant : {ident}")
        if len(set(pertinents)) != len(pertinents) or len(set(partiels)) != len(partiels):
            raise ErreurCorpus(f"{identifiant} : doublon dans les jugements")
        if set(pertinents) & set(partiels):
            raise ErreurCorpus(f"{identifiant} : un passage ne peut être à la fois pertinent et partiel")
        if (genre == "negative") != (not pertinents):
            raise ErreurCorpus(f"{identifiant} : « negative » si et seulement si aucun pertinent")
        if genre == "negative" and partiels:
            raise ErreurCorpus(f"{identifiant} : une question sans réponse n'a pas de partiels")
        requetes.append(Requete(identifiant, genre, texte.strip(), frozenset(pertinents), frozenset(partiels)))
    canonique = repr((sorted(passages.items()), [(r.identifiant, r.texte, sorted(r.pertinents), sorted(r.partiels))
                                                 for r in requetes]))
    return Corpus(passages, categories, tuple(requetes), hashlib.sha256(canonique.encode()).hexdigest())


def sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def perturber_requete(texte: str, graine: int = 2026) -> str:
    """Version « mal tapée » déterministe d'une requête : accents retirés, puis, pour environ 40 % des mots de 5 lettres
    et plus, une lettre supprimée, deux lettres voisines permutées ou une lettre doublée. Les nombres et les mots courts
    sont intacts. Le résultat diffère toujours de l'original si un mot de 5 lettres ou plus existe."""
    alea = random.Random(int(hashlib.sha256(f"{graine}|{texte}".encode()).hexdigest()[:16], 16))
    mots = sans_accents(texte).split(" ")
    candidats = [i for i, m in enumerate(mots) if len(m) >= 5 and m.isalpha()]
    choisis = {i for i in candidats if alea.random() < 0.4}
    if not choisis and candidats:
        choisis = {max(candidats, key=lambda i: (len(mots[i]), -i))}
    for i in sorted(choisis):
        mot = mots[i]
        position = alea.randrange(1, len(mot) - 1)  # jamais la première ni la dernière lettre
        operation = alea.choice(("supprimer", "permuter", "doubler"))
        if operation == "supprimer":
            mot = mot[:position] + mot[position + 1:]
        elif operation == "permuter":
            mot = mot[:position] + mot[position + 1] + mot[position] + mot[position + 2:]
        else:
            mot = mot[:position] + mot[position] + mot[position:]
        if mot == mots[i]:  # permutation de deux lettres identiques : on supprime plutôt (la perturbation doit se voir)
            mot = mots[i][:position] + mots[i][position + 1:]
        mots[i] = mot
    return " ".join(mots)
