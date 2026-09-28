"""Dépôt de fichiers adressé par contenu (T1.4-e2, ADR-0009 §2 « tout dans la même base »).

Un binaire (photo après-chantier, signature client — `docs/architecture/MOBILE.md`) est transmis
par blocs depuis un appareil hors ligne d'abord (R12 §4) et adressé par le SHA-256 de son contenu
COMPLET : deux dépôts du même contenu, par n'importe quel appelant, convergent vers la même ligne
`fichiers` — dédoublonnage naturel, jamais un choix explicite de l'appelant. Voir
`docs/architecture/FICHIERS.md` pour le contrat complet (limites, types permis, rétention).

Module socle, impur (accès `Connection` direct — comme `cles_chiffrement.py`). `recu_le` (heure de
réception, ADR-0009/IDEMPOTENCE.md §5) est fourni par l'appelant quand il le connaît (pendant un
appel d'appareil, l'heure de réception du serveur fait foi — même discipline que
`cles_chiffrement.obtenir_ou_creer`) ; sinon (appel console/agent/test, hors du contrat fixe de
`m4_deposer_fichier`) ce module lit lui-même l'heure courante, comme `opsys.approbations.
creer_demande` le fait déjà pour `cree_le` — un département, lui, ne lit JAMAIS l'horloge (garde
AST `m4_field_ops.digest.garde_absence_horloge`), d'où ce report au socle plutôt qu'à l'appelant.

Département-agnostique à dessein (PLAN T1.4-e2 point 6) : ce module ne connaît AUCUN catalogue de
verdicts — les raisons de refus (`DepotResultat.raison`) sont de courtes chaînes génériques,
JAMAIS un code `REJ-*`. Chaque département appelant traduit ces raisons dans son propre catalogue
fermé (voir `m4_field_ops.outils._depuis_depot_fichier` pour M4), exactement comme aucun autre
module socle ne connaît le catalogue de verdicts d'un département. Un futur département (M5
reçus, M7 contenus) réutilise `etat`/`deposer_bloc` tels quels, avec sa propre traduction.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as _dt
import hashlib
import re

from sqlalchemy import Connection, select

from .stockage.moteur import inserer
from .stockage.schema import FICHIERS, FICHIERS_BLOCS

# Taille de bloc FIXE (T1.4-e2) : chaque bloc décodé fait exactement ce nombre d'octets, sauf le
# dernier bloc d'un fichier (1..TAILLE_BLOC_OCTETS). Ni négociée ni devinée : dérivée de
# `taille_octets`/`nombre_blocs` et vérifiée contre le bloc réellement reçu.
TAILLE_BLOC_OCTETS = 262144
TAILLE_MAX_OCTETS = 10 * 1024 * 1024
NOMBRE_BLOCS_MAX = 64
TYPES_MIME_PERMIS: tuple[str, ...] = ("image/jpeg", "image/png")
PREFIXE_REFERENCE = "fichier:sha256:"

# Octets magiques du type annoncé (T1.4-e2) : vérifiés contre le contenu RÉELLEMENT assemblé,
# jamais déduits du seul `type_mime` déclaré par l'appelant.
_SIGNATURES_MAGIQUES: dict[str, bytes] = {
    "image/jpeg": bytes((0xFF, 0xD8, 0xFF)),
    "image/png": bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)),
}

_EMPREINTE_HEX = re.compile(r"^[0-9a-f]{64}$")

__all__ = [
    "TAILLE_BLOC_OCTETS", "TAILLE_MAX_OCTETS", "NOMBRE_BLOCS_MAX", "TYPES_MIME_PERMIS",
    "PREFIXE_REFERENCE", "EtatFichier", "DepotResultat",
    "empreinte_valide", "reference_pour", "empreinte_depuis_reference",
    "etat", "deposer_bloc",
]


def empreinte_valide(valeur: object) -> bool:
    """``True`` seulement si `valeur` est EXACTEMENT 64 caractères hexadécimaux minuscules —
    fail-closed sur tout le reste (type, longueur, casse)."""
    return isinstance(valeur, str) and bool(_EMPREINTE_HEX.match(valeur))


def reference_pour(empreinte_sha256: str) -> str:
    return f"{PREFIXE_REFERENCE}{empreinte_sha256}"


def empreinte_depuis_reference(reference: object) -> str | None:
    """Empreinte extraite d'une référence ``fichier:sha256:<hex>``, ou ``None`` si la forme ne
    correspond pas EXACTEMENT — fail-closed, jamais une extraction partielle ou permissive."""
    if not isinstance(reference, str) or not reference.startswith(PREFIXE_REFERENCE):
        return None
    empreinte = reference[len(PREFIXE_REFERENCE):]
    return empreinte if empreinte_valide(empreinte) else None


@dataclasses.dataclass(frozen=True)
class EtatFichier:
    existe: bool
    complet: bool
    blocs_recus: tuple[int, ...]
    type_mime: str | None
    reference: str | None


def etat(cnx: Connection, empreinte_sha256: str) -> EtatFichier:
    """État courant d'un dépôt (`m4_etat_fichier`) : permet à un appareil de reprendre un envoi
    interrompu sans retransmettre les blocs déjà reçus."""
    ligne = cnx.execute(
        select(FICHIERS.c.complet, FICHIERS.c.type_mime)
        .where(FICHIERS.c.empreinte_sha256 == empreinte_sha256)
    ).one_or_none()
    if ligne is None:
        return EtatFichier(existe=False, complet=False, blocs_recus=(), type_mime=None, reference=None)
    complet = bool(ligne.complet)
    return EtatFichier(
        existe=True, complet=complet, blocs_recus=_blocs_recus(cnx, empreinte_sha256),
        type_mime=ligne.type_mime, reference=reference_pour(empreinte_sha256) if complet else None,
    )


def _blocs_recus(cnx: Connection, empreinte_sha256: str) -> tuple[int, ...]:
    return tuple(cnx.execute(
        select(FICHIERS_BLOCS.c.index_bloc)
        .where(FICHIERS_BLOCS.c.empreinte_sha256 == empreinte_sha256)
        .order_by(FICHIERS_BLOCS.c.index_bloc)
    ).scalars().all())


@dataclasses.dataclass(frozen=True)
class DepotResultat:
    accepte: bool
    raison: str | None  # None si accepte=True ; sinon une des 5 raisons génériques ci-dessous.
    detail: str
    complet: bool
    blocs_recus: tuple[int, ...]
    reference: str | None


# Raisons génériques rendues par `deposer_bloc` (jamais un code `REJ-*` : voir docstring du module).
RAISON_PARAMETRES_INVALIDES = "parametres_invalides"
RAISON_TROP_VOLUMINEUX = "trop_volumineux"
RAISON_INCOHERENT = "incoherent"
RAISON_EMPREINTE_DISCORDANTE = "empreinte_discordante"
RAISON_TYPE_NON_PERMIS = "type_non_permis"


def _maintenant() -> str:
    """Heure courante UTC, ISO 8601 (même patron que `opsys.approbations._maintenant`) : lue ICI,
    à la frontière impure du socle, jamais par un département (garde AST M4, voir docstring)."""
    return _dt.datetime.now(_dt.UTC).isoformat()


def _refus(raison: str, detail: str) -> DepotResultat:
    return DepotResultat(
        accepte=False, raison=raison, detail=detail, complet=False, blocs_recus=(), reference=None,
    )


def deposer_bloc(
    cnx: Connection,
    empreinte_sha256: object,
    taille_octets: object,
    type_mime: object,
    index_bloc: object,
    nombre_blocs: object,
    bloc_base64: object,
    *,
    recu_le: str | None = None,
) -> DepotResultat:
    """Dépose un bloc (`m4_deposer_fichier`). Idempotent : renvoyer un bloc déjà reçu, à
    l'identique, est un no-op accepté. Refuse fail-closed, sans rien écrire, si l'empreinte est
    déjà déclarée avec des caractéristiques différentes, ou si ce même bloc revient avec un
    contenu différent. Quand tous les blocs annoncés sont là, le contenu assemblé est vérifié
    (taille, SHA-256, octets magiques du type annoncé) avant d'être marqué complet ; toute
    discordance efface les blocs déjà reçus pour cette empreinte (l'appelant doit tout renvoyer).

    Ordre des contrôles, épinglé (comme `m4_field_ops.preuves.valider_preuves_completion`) :
    forme des paramètres (indépendamment de tout état déjà en base) -> cohérence avec une
    éventuelle déclaration déjà en base -> le bloc lui-même -> assemblage final si complet.

    `recu_le` : heure de réception ISO 8601 qui fait foi. Fournie par l'appelant pendant un appel
    d'appareil (`opsys.contexte.horodatage_reception()`, T1.4-d) ; sinon `None` lit l'heure
    courante ICI (frontière impure du socle — jamais dans `m4_field_ops`, voir docstring module).
    """
    if recu_le is None:
        recu_le = _maintenant()

    # 1. Forme des six paramètres, seuls (aucune lecture en base à ce stade).
    if not empreinte_valide(empreinte_sha256):
        return _refus(
            RAISON_PARAMETRES_INVALIDES,
            "empreinte_sha256 doit être exactement 64 caractères hexadécimaux minuscules",
        )
    if type(nombre_blocs) is not int or not (1 <= nombre_blocs <= NOMBRE_BLOCS_MAX):
        return _refus(
            RAISON_PARAMETRES_INVALIDES, f"nombre_blocs doit être un entier entre 1 et {NOMBRE_BLOCS_MAX}",
        )
    if type(index_bloc) is not int or not (0 <= index_bloc < nombre_blocs):
        return _refus(
            RAISON_PARAMETRES_INVALIDES, "index_bloc doit être un entier entre 0 et nombre_blocs - 1",
        )
    if type_mime not in TYPES_MIME_PERMIS:
        return _refus(RAISON_PARAMETRES_INVALIDES, f"type_mime doit être l'un de {TYPES_MIME_PERMIS}")
    if type(taille_octets) is not int:
        return _refus(RAISON_PARAMETRES_INVALIDES, "taille_octets doit être un entier")
    if not (1 <= taille_octets <= TAILLE_MAX_OCTETS):
        return _refus(RAISON_TROP_VOLUMINEUX, f"taille_octets doit être entre 1 et {TAILLE_MAX_OCTETS}")
    if not isinstance(bloc_base64, str) or bloc_base64 == "":
        return _refus(RAISON_PARAMETRES_INVALIDES, "bloc_base64 doit être une chaîne base64 non vide")
    try:
        contenu_bloc = base64.b64decode(bloc_base64, validate=True)
    except ValueError:
        return _refus(RAISON_PARAMETRES_INVALIDES, "bloc_base64 n'est pas du base64 standard valide")

    # nombre_blocs doit être EXACTEMENT celui qu'implique taille_octets à bloc fixe — jamais un
    # autre découpage pour la même taille déclarée.
    nombre_blocs_attendu = -(-taille_octets // TAILLE_BLOC_OCTETS)  # division entière arrondie au sup.
    if nombre_blocs != nombre_blocs_attendu:
        return _refus(
            RAISON_PARAMETRES_INVALIDES,
            f"nombre_blocs={nombre_blocs} incohérent avec taille_octets={taille_octets} "
            f"(attendu {nombre_blocs_attendu} à {TAILLE_BLOC_OCTETS} octets/bloc)",
        )
    est_dernier = index_bloc == nombre_blocs - 1
    taille_attendue = taille_octets - index_bloc * TAILLE_BLOC_OCTETS if est_dernier else TAILLE_BLOC_OCTETS
    if len(contenu_bloc) > TAILLE_BLOC_OCTETS:
        return _refus(
            RAISON_TROP_VOLUMINEUX, f"bloc de {len(contenu_bloc)} octets > {TAILLE_BLOC_OCTETS} (taille fixe)",
        )
    if len(contenu_bloc) != taille_attendue:
        return _refus(
            RAISON_PARAMETRES_INVALIDES,
            f"bloc {index_bloc} : {len(contenu_bloc)} octets reçus, {taille_attendue} attendus",
        )

    # 2. Cohérence avec une éventuelle déclaration déjà en base pour cette empreinte : la première
    # déclaration gagne, jamais écrasée par une redéclaration divergente.
    existante = cnx.execute(
        select(FICHIERS.c.taille_octets, FICHIERS.c.type_mime, FICHIERS.c.nombre_blocs, FICHIERS.c.complet)
        .where(FICHIERS.c.empreinte_sha256 == empreinte_sha256)
    ).one_or_none()
    if existante is None:
        cnx.execute(
            inserer(cnx)(FICHIERS)
            .values(
                empreinte_sha256=empreinte_sha256, taille_octets=taille_octets, type_mime=type_mime,
                nombre_blocs=nombre_blocs, complet=False, cree_le=recu_le,
            )
            .on_conflict_do_nothing(index_elements=["empreinte_sha256"])
        )
        existante = cnx.execute(
            select(FICHIERS.c.taille_octets, FICHIERS.c.type_mime, FICHIERS.c.nombre_blocs, FICHIERS.c.complet)
            .where(FICHIERS.c.empreinte_sha256 == empreinte_sha256)
        ).one()
    if (existante.taille_octets, existante.type_mime, existante.nombre_blocs) != (
        taille_octets, type_mime, nombre_blocs,
    ):
        return _refus(
            RAISON_INCOHERENT,
            f"empreinte {empreinte_sha256} déjà déclarée avec taille_octets={existante.taille_octets}, "
            f"type_mime={existante.type_mime!r}, nombre_blocs={existante.nombre_blocs} — "
            "valeurs différentes reçues pour la même empreinte",
        )

    # 3. Le bloc lui-même : no-op si un bloc identique existe déjà à cet index, refus nommé s'il
    # diverge (comparaison sur le contenu DÉCODÉ, insensible à un padding base64 équivalent).
    bloc_existant_b64 = cnx.execute(
        select(FICHIERS_BLOCS.c.contenu_base64).where(
            (FICHIERS_BLOCS.c.empreinte_sha256 == empreinte_sha256)
            & (FICHIERS_BLOCS.c.index_bloc == index_bloc)
        )
    ).scalar_one_or_none()
    if bloc_existant_b64 is None:
        cnx.execute(
            inserer(cnx)(FICHIERS_BLOCS)
            .values(
                empreinte_sha256=empreinte_sha256, index_bloc=index_bloc, contenu_base64=bloc_base64,
                taille_octets=len(contenu_bloc), recu_le=recu_le,
            )
            .on_conflict_do_nothing(index_elements=["empreinte_sha256", "index_bloc"])
        )
    elif base64.b64decode(bloc_existant_b64) != contenu_bloc:
        return _refus(
            RAISON_INCOHERENT, f"bloc {index_bloc} déjà reçu avec un contenu différent pour cette empreinte",
        )
    # sinon : exactement le même bloc renvoyé -> no-op accepté (idempotence, T1.4-e2).

    if existante.complet:
        return DepotResultat(
            accepte=True, raison=None, detail="", complet=True,
            blocs_recus=_blocs_recus(cnx, empreinte_sha256), reference=reference_pour(empreinte_sha256),
        )

    blocs_recus = _blocs_recus(cnx, empreinte_sha256)
    if len(blocs_recus) < nombre_blocs:
        return DepotResultat(
            accepte=True, raison=None, detail="", complet=False, blocs_recus=blocs_recus, reference=None,
        )

    # 4. Tous les blocs annoncés sont là : assemblage et triple vérification. Discordance = blocs
    # effacés (jamais une ligne « complète » douteuse) et refus nommé ; l'appelant doit tout
    # redéposer (la déclaration en base, elle, reste : une redéclaration cohérente au prochain essai
    # retombe directement à l'étape 3).
    lignes_b64 = cnx.execute(
        select(FICHIERS_BLOCS.c.contenu_base64)
        .where(FICHIERS_BLOCS.c.empreinte_sha256 == empreinte_sha256)
        .order_by(FICHIERS_BLOCS.c.index_bloc)
    ).scalars().all()
    assemble = b"".join(base64.b64decode(morceau) for morceau in lignes_b64)

    # Invariant structurel, pas un verdict métier atteignable par cette API : chaque bloc accepté
    # a déjà passé la vérification de longueur EXACTE pour sa position (étape 1), sous
    # taille_octets/nombre_blocs PINNÉS par la première déclaration pour cette empreinte (étape 2)
    # — la somme ne peut donc jamais différer de taille_octets. Assertion défensive (même patron
    # que `cles_chiffrement.obtenir_ou_creer`), jamais un chemin que l'appelant peut déclencher.
    assert len(assemble) == taille_octets, "invariant violé : taille assemblée != taille_octets déclarée"
    empreinte_calculee = hashlib.sha256(assemble).hexdigest()
    if empreinte_calculee != empreinte_sha256:
        _effacer_blocs(cnx, empreinte_sha256)
        return _refus(
            RAISON_EMPREINTE_DISCORDANTE,
            f"SHA-256 du contenu assemblé ({empreinte_calculee}) diffère de l'empreinte annoncée",
        )
    signature = _SIGNATURES_MAGIQUES[type_mime]
    if assemble[: len(signature)] != signature:
        _effacer_blocs(cnx, empreinte_sha256)
        return _refus(RAISON_TYPE_NON_PERMIS, f"octets magiques absents pour le type annoncé {type_mime!r}")

    cnx.execute(
        FICHIERS.update()
        .where(FICHIERS.c.empreinte_sha256 == empreinte_sha256)
        .values(complet=True, complete_le=recu_le)
    )
    return DepotResultat(
        accepte=True, raison=None, detail="", complet=True,
        blocs_recus=blocs_recus, reference=reference_pour(empreinte_sha256),
    )


def _effacer_blocs(cnx: Connection, empreinte_sha256: str) -> None:
    cnx.execute(FICHIERS_BLOCS.delete().where(FICHIERS_BLOCS.c.empreinte_sha256 == empreinte_sha256))
