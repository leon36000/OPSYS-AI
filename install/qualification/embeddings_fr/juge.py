"""Reclassement par un petit modèle de discussion utilisé comme JUGE de pertinence sur les k premiers candidats.

Le juge reçoit la question et les passages dans un ordre MÉLANGÉ de façon déterministe (il ne voit donc pas le rang
de la recherche) et note chacun de 0 à 3 dans un objet JSON. Le reclassement trie par note décroissante puis, à
égalité, par rang initial : il réordonne la tête, ne retire aucun candidat. Une réponse inexploitable laisse l'ordre
initial (comptée).

Limites assumées : un seul modèle juge, une seule consigne, pas de calibration ; ce n'est PAS un reranker dédié
(cross-encodeur). Il dit seulement ce que coûte et rapporte un juge générique par-dessus la recherche.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from .cache import Cache
from .passerelle import ClientPasserelle

NOTE_MIN, NOTE_MAX = 0, 3
SEUIL_REPONSE = 2  # une note >= 2 veut dire « répond au moins en partie »
# La consigne décrit le secteur du corpus : elle vit avec les DONNÉES (docs/qualification/corpus-embeddings-fr/), pas
# dans le code du banc. Son empreinte est épinglée par un test : changer un mot change les clés du cache des jugements
# et rend les preuves publiées non rejouables.
CONSIGNE = (Path(__file__).resolve().parents[3] / "docs" / "qualification" / "corpus-embeddings-fr"
            / "consigne_juge.txt")
SYSTEME = CONSIGNE.read_text(encoding="utf-8").strip()


def ordre_presentation(identifiants: Sequence[str], graine: str) -> list[str]:
    """Ordre de présentation mélangé de façon reproductible : indépendant du rang de la recherche."""
    alea = random.Random(int(hashlib.sha256(graine.encode()).hexdigest()[:16], 16))
    melange = sorted(identifiants)
    alea.shuffle(melange)
    return melange


def construire_messages(requete: str, presentes: Sequence[tuple[str, str]]) -> list[dict[str, str]]:
    corps = "\n".join(f"[{i}] {texte}" for i, (_, texte) in enumerate(presentes, start=1))
    return [{"role": "system", "content": SYSTEME},
            {"role": "user", "content": f"Question : {requete}\n\nPassages :\n{corps}"}]


def analyser_notes(texte: str, attendu: int) -> list[int] | None:
    """Notes entières du JSON de la réponse, ou None si la forme n'est pas exactement celle demandée."""
    trouve = re.search(r"\{.*\}", texte, re.DOTALL)
    if not trouve:
        return None
    try:
        objet = json.loads(trouve.group(0))
    except ValueError:
        return None
    notes = objet.get("notes") if isinstance(objet, dict) else None
    if (not isinstance(notes, list) or len(notes) != attendu
            or any(isinstance(n, bool) or not isinstance(n, int) or not NOTE_MIN <= n <= NOTE_MAX for n in notes)):
        return None
    return notes


def reclasser(classement: Sequence[str], notes: Mapping[str, int]) -> list[str]:
    """Trie par note décroissante, à égalité par rang initial ; les candidats sans note gardent leur place relative
    après les notés (ici tous les candidats sont notés)."""
    position = {identifiant: i for i, identifiant in enumerate(classement)}
    return sorted(classement, key=lambda identifiant: (-notes.get(identifiant, NOTE_MIN), position[identifiant]))


def juger(client: ClientPasserelle | None, cache: Cache, modele: str, requete_id: str, requete: str,
          candidats: Sequence[str], passages: Mapping[str, str]) -> dict[str, int] | None:
    """Notes par identifiant, ou None si le juge n'a pas rendu un JSON exploitable. Réponse mise en cache disque."""
    presentes = [(i, passages[i]) for i in ordre_presentation(candidats, f"{requete_id}|{modele}")]
    messages = construire_messages(requete, presentes)
    cle = hashlib.sha256(json.dumps([modele, messages], ensure_ascii=False).encode()).hexdigest()
    brut = cache.lire_jugement(cle)
    if brut is None:
        if client is None:
            raise RuntimeError("jugement absent du cache et appels interdits (--sans-appel)")
        reponse = client.discussion(modele, messages, max_tokens=160)
        cache.journaliser_appel(modele, "juge", "juge", len(presentes), reponse.secondes, reponse.jetons_entree,
                                reponse.jetons_sortie, reponse.cout_usd)
        cache.ecrire_jugement(cle, modele, reponse.texte)
        brut = reponse.texte
    notes = analyser_notes(brut, len(presentes))
    if notes is None:
        return None
    return {identifiant: note for (identifiant, _), note in zip(presentes, notes, strict=True)}
