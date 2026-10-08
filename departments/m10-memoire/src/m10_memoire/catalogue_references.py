"""Catalogue N0 métier borné : références du registre Affaires, jamais ses textes.

Le propriétaire fournit exclusivement son registre Affaires. Une seule lecture est copiée,
validée puis projetée ; aucun stockage, rôle fourni par l'appelant ou accès développement.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from . import confidentialite, contexte, contrats, decisions, humain, registre, revision, validation

LIMITE = 8
BUDGET_CARACTERES = 5400
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _refus(code: str) -> tuple[None, dict[str, Any]]:
    return None, validation.construire_verdict(code, "Catalogue métier indisponible ; vérifier le registre Affaires.")


def _identifiant(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 256
        and not any(unicodedata.category(c) in {"Cc", "Cs"} for c in value)
    )


def _hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _reference(m: dict[str, Any], positions: dict[str, int], lignes: list[dict[str, Any]]) -> dict:
    # La tête globale peut être privée. Ce préfixe s'arrête à la ligne réellement citée.
    prefixe = registre.Registre(maillons=lignes[: positions[m["ligne_id"]] + 1])
    return contexte.construire_reference(m, "affaires", prefixe)


def pieces_visibles(pieces: list[dict[str, Any]]) -> bool:
    candidats = [{"confidentialite": confidentialite.niveau_de(m)} for m in pieces]
    _, retenus = confidentialite.filtrer("regles_entreprise", None, candidats)
    return retenus == 0


def resoudre_revision(index: dict, revision_ligne_id: Any) -> tuple[dict | None, dict | None]:
    """Projection canonique et deux sources d'une révision : quatre pièces visibles ou refus entier."""
    if not isinstance(revision_ligne_id, str) or revision_ligne_id not in index["signalements"]:
        return _refus("REJ-CATALOGUE-REVISION-INCONNUE")
    sig = index["signalements"][revision_ligne_id]
    actuel = index["arbitrages"].get(revision_ligne_id, sig)
    positions, lignes = index["positions"], index["lignes"]
    a, b = lignes[positions[sig["ligne_id_a"]]], lignes[positions[sig["ligne_id_b"]]]
    if not pieces_visibles([sig, a, b, actuel]):
        return _refus("REJ-CATALOGUE-REVISION-RETENUE")
    statut = revision.statut_revision(index["snapshot"], revision_ligne_id)
    if statut is None or statut != actuel["statut"]:
        return _refus("REJ-CATALOGUE-STATUT-INCOHERENT")
    projection = {
        "genre": "revision", "revision_ligne_id": revision_ligne_id, "statut": statut,
        "signalee_le": sig["horodatage"], "statut_le": actuel["horodatage"],
        "reference": _reference(sig, positions, lignes),
        "reference_statut": _reference(actuel, positions, lignes),
        "reference_a": _reference(a, positions, lignes), "reference_b": _reference(b, positions, lignes),
    }
    return {"projection": projection, "faits": [a, b], "position": positions[actuel["ligne_id"]]}, None


def _page(candidats: list[tuple[int, dict]], retenus: int, limite: int, decalage: int) -> dict:
    candidats.sort(key=lambda c: c[0], reverse=True)
    total = len(candidats)

    def construire(nombre: int, taille: int = 0) -> dict:
        items = [item for _, item in candidats[decalage : decalage + nombre]]
        reste = max(0, total - decalage - nombre)
        return {
            "decisions": [i for i in items if i["genre"] == "decision"],
            "revisions": [i for i in items if i["genre"] == "revision"],
            "decalage": decalage,
            "suivant": decalage + nombre if reste else None,
            "reste": reste,
            "total": total,
            "affichees": nombre,
            "limite": limite,
            "borne_caracteres": BUDGET_CARACTERES,
            "taille_caracteres": taille,
            "confidentialite": {"regle": confidentialite.REGLE_VERSION, "nb_retenus": retenus},
        }

    def mesurer(nombre: int) -> dict:
        resultat = construire(nombre)
        while True:
            taille = len(
                json.dumps({"ok": True, "resultat": {"accepte": True, "resultat": resultat}}, ensure_ascii=False)
            )
            if taille == resultat["taille_caracteres"]:
                return resultat
            resultat = construire(nombre, taille)

    nombre = min(limite, max(0, total - decalage))
    page = mesurer(nombre)
    while page["taille_caracteres"] > BUDGET_CARACTERES and nombre > 0:
        nombre -= 1
        page = mesurer(nombre)
    if page["taille_caracteres"] > BUDGET_CARACTERES or (nombre == 0 and decalage < total):
        raise ValueError("budget")
    return page


def indexer_snapshot_affaires(registre_snapshot: Any) -> tuple[dict | None, dict | None]:
    """Valide une copie unique des Affaires et indexe les états avant tout filtrage métier."""
    try:
        lignes = registre_snapshot.lire()
        if not isinstance(lignes, list) or any(not isinstance(m, dict) for m in lignes):
            return _refus("REJ-CATALOGUE-MAILLON-ILLISIBLE")
        snapshot = registre.Registre(maillons=lignes)
        valide, _ = snapshot.valider_chaine()
        if not valide:
            return _refus("REJ-CATALOGUE-CHAINE-INVALIDE")
    except Exception:
        return _refus("REJ-CATALOGUE-CHAINE-INVALIDE")

    positions: dict[str, int] = {}
    dernieres_decisions: dict[str, dict] = {}
    signalements: dict[str, dict] = {}
    arbitrages: dict[str, dict] = {}
    for rang, m in enumerate(lignes):
        if (
            not _hash(m.get("ligne_id"))
            or m["ligne_id"] in positions
            or not humain.horodatage_valide(m.get("horodatage"))
        ):
            return _refus("REJ-CATALOGUE-MAILLON-ILLISIBLE")
        # La chaîne valide les empreintes ; sa taxonomie reste celle du propriétaire Registre.
        genre = m.get("type_entree")
        if not isinstance(genre, str) or genre not in registre._TYPE_ENTREE_VALIDES:
            return _refus("REJ-CATALOGUE-MAILLON-ILLISIBLE")
        positions[m["ligne_id"]] = rang
        if m.get("type_entree") == "decision_enregistree":
            if not _identifiant(m.get("decision_id")) or m.get("statut") not in contrats.STATUT_DECISION:
                return _refus("REJ-CATALOGUE-DECISION-INVALIDE")
            dernieres_decisions[m["decision_id"]] = m
        elif m.get("type_entree") == "revision_signalee":
            if m.get("statut") not in contrats.STATUT_REVISION:
                return _refus("REJ-CATALOGUE-REVISION-INVALIDE")
            a, b, cible = m.get("ligne_id_a"), m.get("ligne_id_b"), m.get("revision_ligne_id")
            if (
                a is None
                and b is None
                and cible is None
                and "code_verdict" in m
                and "ligne_id_a" not in m
                and "ligne_id_b" not in m
            ):
                # Trace de préflight existante, explicitement non arbitrable : pas un signalement.
                if not isinstance(m["code_verdict"], str) or not m["code_verdict"]:
                    return _refus("REJ-CATALOGUE-REVISION-INVALIDE")
                continue
            if a is not None or b is not None:
                if (
                    not _hash(a)
                    or not _hash(b)
                    or a == b
                    or cible is not None
                    or a not in positions
                    or b not in positions
                    or positions[a] >= rang
                    or positions[b] >= rang
                ):
                    return _refus("REJ-CATALOGUE-REFERENCES-INVALIDES")
                signalements[m["ligne_id"]] = m
            elif not _hash(cible) or cible not in signalements:
                return _refus("REJ-CATALOGUE-ARBITRAGE-ORPHELIN")
            else:
                arbitrages[cible] = m

    return {
        "lignes": lignes, "snapshot": snapshot, "positions": positions,
        "decisions": dernieres_decisions, "signalements": signalements, "arbitrages": arbitrages,
    }, None


def lister_references(
    registre_snapshot: Any, limite: int = LIMITE, decalage: int = 0
) -> tuple[dict | None, dict | None]:
    """Derniers états métier avant filtrage, pages courantes ; résultat ou refus nominal.

    Les IDs de décision restent opaques et Unicode (sans contrôles, 256 caractères).
    L'offset porte sur la collection visible commune ; aucune tête globale n'est retournée.
    """
    if type(limite) is not int or not 1 <= limite <= LIMITE or type(decalage) is not int or decalage < 0:
        return _refus("REJ-CATALOGUE-PAGINATION-INVALIDE")
    index, refus = indexer_snapshot_affaires(registre_snapshot)
    if refus is not None:
        return None, refus
    lignes, snapshot, positions = index["lignes"], index["snapshot"], index["positions"]
    dernieres_decisions = index["decisions"]
    signalements = index["signalements"]

    candidats: list[tuple[int, dict]] = []
    retenus = 0
    for identifiant, m in dernieres_decisions.items():
        if not pieces_visibles([m]):
            retenus += 1
            continue
        statut = decisions.statut_courant(snapshot, identifiant)
        if statut is None or statut != m["statut"]:
            return _refus("REJ-CATALOGUE-STATUT-INCOHERENT")
        candidats.append(
            (
                positions[m["ligne_id"]],
                {
                    "genre": "decision",
                    "decision_id": identifiant,
                    "statut": statut,
                    "horodatage": m["horodatage"],
                    "reference": _reference(m, positions, lignes),
                },
            )
        )
    for identifiant in signalements:
        resolution, refus = resoudre_revision(index, identifiant)
        if refus is not None:
            if refus["code"] == "REJ-CATALOGUE-REVISION-RETENUE":
                retenus += 1
                continue
            return None, refus
        candidats.append((resolution["position"], resolution["projection"]))
    try:
        return _page(candidats, retenus, limite, decalage), None
    except (ValueError, TypeError, OverflowError):
        return _refus("REJ-CATALOGUE-BUDGET-IMPOSSIBLE")
