"""État de pilotage des profils d'agents, en lecture seule (CF038).

Quatre faits distincts, chacun avec sa source :
- le profil du registre SQL (activé ou non, révision, dernière modification) ;
- la révision exportée dans `opsys/agents.json` du dossier de configuration du core, écrit par
  `openclaw.generer` (`opsysRuntimeAdmission.profileRevision`). Le dossier est résolu côté serveur, par la même
  règle que `memoire.autorite.lire_politique` : `OPENCLAW_CONFIG_DIR`, sinon `instance.dossier_core()` ;
- les réservations d'admission actives (`admission_agents.lister_reservations_actives`) ;
- le chargement par le core et l'activité réelle : aucune attestation n'est observable ici, donc INCONNU.

Un export concordant compare la révision du profil seulement : le pack du département, les modèles et la
projection SMS ne portent pas cette révision. Une réservation ne prouve pas qu'une tâche tourne.
Aucune écriture : ni base, ni fichier, ni identifiant généré.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, String, column, func, select, values

from .. import admission_agents, agents
from ..departements import Departement
from ..stockage.schema import AGENTS_CONFIGURABLES

FICHIER_EXPORT = Path("opsys") / "agents.json"
TAILLE_MAX_EXPORT = 4 * 1024 * 1024  # octets ; au-delà, l'export est déclaré illisible
LIMITE_MAX = 50
ORPHELINS_MAX = 50
ORPHELINS_LOT = 500  # identifiants exportés comparés au registre par requête
SOURCE_REGISTRE = "registre SQL des profils configurables"
SOURCE_EXPORT = "fragment opsys/agents.json du dossier de configuration du core (résolu côté serveur)"
SOURCE_RESERVATIONS = "réservations d'admission actives du registre SQL"
LIMITE_EXPORT = (
    "Seule la révision du profil est comparée ; le pack du département, les modèles et la projection SMS "
    "ne sont pas comparés. Un export écrit ne prouve pas son chargement par le core."
)
CHARGEMENT_CORE = {
    "statut": "INCONNU",
    "raison": "Aucune attestation de chargement par le core n'est observable par la console.",
}
ACTIVITE = {
    "statut": "INCONNUE",
    "raison": "Aucune attestation d'exécution n'est observable ; une réservation ne prouve pas qu'une tâche tourne.",
}
DETAILS_EXPORT = {
    "CONCORDANT": "Révision de profil exportée identique au registre.",
    "PERIME": "Révision exportée antérieure au registre : synchronisation de la configuration requise.",
    "DIVERGENT": "Révision exportée supérieure au registre ; origine non attestée.",
    "NON_EXPORTE": "Profil activé absent de l'export : synchronisation de la configuration requise.",
    "DESACTIVE_ENCORE_EXPORTE": "Profil désactivé encore présent dans l'export : le core peut encore le charger.",
    "ABSENT_CONFORME": "Profil désactivé absent de l'export.",
    "EXPORT_ABSENT": "Aucun export d'agents dans le dossier de configuration du core.",
    "EXPORT_ILLISIBLE": "Export d'agents illisible, non régulier, trop volumineux ou malformé.",
    "NON_OBSERVABLE": "Dossier de configuration du core introuvable depuis la console.",
}


def dossier_configuration_core() -> Path | None:
    """Dossier serveur du core ; jamais une valeur de requête."""
    valeur = os.environ.get("OPENCLAW_CONFIG_DIR")
    if valeur:
        return Path(valeur)
    from ..instance import ErreurInstance, dossier_core

    try:
        return dossier_core()
    except (ErreurInstance, OSError, RuntimeError):
        return None


def _revisions(donnees: Any) -> dict[str, int] | None:
    if not isinstance(donnees, dict) or not isinstance(donnees.get("entries"), dict):
        return None
    revisions: dict[str, int] = {}
    for entree in donnees["entries"].values():
        if not isinstance(entree, dict):
            return None
        admission = entree.get("opsysRuntimeAdmission")
        if admission is None:
            continue  # agent de département, sans profil configurable
        if not isinstance(admission, dict):
            return None
        ident, revision = admission.get("profileId"), admission.get("profileRevision")
        if (
            not isinstance(ident, str) or not 1 <= len(ident) <= 64 or ident in revisions
            or type(revision) is not int or revision < 1
        ):
            return None
        revisions[ident] = revision
    return revisions


def lire_export(dossier: Path | None) -> dict[str, Any]:
    """Lit une seule fois l'export : statut LU, EXPORT_ABSENT, EXPORT_ILLISIBLE ou NON_OBSERVABLE."""

    def verdict(statut: str, ecrit_le: str | None = None) -> dict[str, Any]:
        return {"statut": statut, "ecrit_le": ecrit_le, "revisions": {}}

    if dossier is None or not dossier.is_dir():
        return verdict("NON_OBSERVABLE")
    try:
        # O_NONBLOCK : un FIFO à la place du fichier ne bloque pas la requête avant le contrôle S_ISREG.
        drapeaux = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(dossier / FICHIER_EXPORT, drapeaux)
    except FileNotFoundError:
        return verdict("EXPORT_ABSENT")
    except OSError:
        return verdict("EXPORT_ILLISIBLE")
    try:
        with os.fdopen(fd, "rb") as flux:
            info = os.fstat(flux.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > TAILLE_MAX_EXPORT:
                return verdict("EXPORT_ILLISIBLE")
            contenu = flux.read(TAILLE_MAX_EXPORT + 1)
    except OSError:
        return verdict("EXPORT_ILLISIBLE")
    ecrit_le = dt.datetime.fromtimestamp(info.st_mtime, dt.UTC).isoformat(timespec="seconds")
    if len(contenu) > TAILLE_MAX_EXPORT:
        return verdict("EXPORT_ILLISIBLE", ecrit_le)
    try:
        revisions = _revisions(json.loads(contenu))
    except (UnicodeDecodeError, ValueError, RecursionError):
        revisions = None
    if revisions is None:
        return verdict("EXPORT_ILLISIBLE", ecrit_le)
    return {"statut": "LU", "ecrit_le": ecrit_le, "revisions": revisions}


def _statut_export(profil: Mapping[str, Any], export: Mapping[str, Any]) -> tuple[str, int | None]:
    if export["statut"] != "LU":
        return export["statut"], None
    exportee = export["revisions"].get(profil["id"])
    if exportee is None:
        return ("NON_EXPORTE" if profil["actif"] else "ABSENT_CONFORME"), None
    if not profil["actif"]:
        return "DESACTIVE_ENCORE_EXPORTE", exportee
    if exportee == profil["revision"]:
        return "CONCORDANT", exportee
    return ("PERIME" if exportee < profil["revision"] else "DIVERGENT"), exportee


def _outils(profil: Mapping[str, Any], manifestes: Mapping[str, Any]) -> dict[str, Any]:
    source = "manifeste du département et outils autorisés du profil"
    if profil["departement"] not in manifestes:
        return {"statut": "DEPARTEMENT_ABSENT", "source": source, "autorises": [],
                "hors_manifeste": list(profil["outils"])}
    connus = manifestes[profil["departement"]]
    if connus is None:
        return {"statut": "MANIFESTE_INDISPONIBLE", "source": source, "autorises": [], "hors_manifeste": []}
    return {
        "statut": "LU",
        "source": source,
        "autorises": [
            {"nom": nom, "autonomie": connus[nom].autonomie.value} for nom in profil["outils"] if nom in connus
        ],
        "hors_manifeste": [nom for nom in profil["outils"] if nom not in connus],
    }


def etat_profil(
    cnx: Connection,
    profil: Mapping[str, Any],
    export: Mapping[str, Any],
    manifestes: Mapping[str, Any],
) -> dict[str, Any]:
    statut, exportee = _statut_export(profil, export)
    reservations = admission_agents.lister_reservations_actives(cnx, profil["id"], limite=1)["total"]
    return {
        "profil": {
            "statut": "ACTIVE" if profil["actif"] else "DESACTIVE",
            "revision": profil["revision"],
            "modifie_le": profil["modifie_le"],
            "source": SOURCE_REGISTRE,
        },
        "export": {
            "statut": statut,
            "revision_exportee": exportee,
            "revision_registre": profil["revision"],
            "ecrit_le": export["ecrit_le"],
            "source": SOURCE_EXPORT,
            "detail": DETAILS_EXPORT[statut],
        },
        "chargement_core": dict(CHARGEMENT_CORE),
        "reservations": {
            "statut": "OBSERVEES" if reservations else "AUCUNE",
            "actives": reservations,
            "source": SOURCE_RESERVATIONS,
        },
        "activite": dict(ACTIVITE),
        "outils": _outils(profil, manifestes),
    }


def _manifestes(deps: Mapping[str, Departement], profils: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Outils déclarés par département ; un manifeste illisible donne None, jamais son message interne."""
    manifestes: dict[str, Any] = {}
    for ident in sorted({p["departement"] for p in profils}):
        if ident not in deps:
            continue
        try:
            manifestes[ident] = {outil.nom: outil for outil in deps[ident].charger_outils()}
        except (ImportError, ValueError, TypeError):
            manifestes[ident] = None
    return manifestes


def valider_pagination(limite: int, decalage: int) -> None:
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= LIMITE_MAX:
        raise ValueError(f"limite : entier de 1 à {LIMITE_MAX}")
    if isinstance(decalage, bool) or not isinstance(decalage, int) or decalage < 0:
        raise ValueError("decalage : entier positif ou nul")


def page_registre(
    cnx: Connection, *, departement: str | None, limite: int, decalage: int
) -> tuple[list[dict[str, Any]], int]:
    """Profils non archivés d'une page (ordre stable par identifiant) et leur total exact par COUNT.

    Seules les lignes de la page sortent de la base. COUNT et page ont le même filtre mais ne forment pas un
    instantané : une écriture concurrente entre les deux peut les décaler d'autant."""
    conditions = [AGENTS_CONFIGURABLES.c.supprime.is_(False)]
    if departement is not None:
        conditions.append(AGENTS_CONFIGURABLES.c.departement == departement)
    total = cnx.execute(
        select(func.count().label("total")).select_from(AGENTS_CONFIGURABLES).where(*conditions)
    ).scalar_one()
    lignes = cnx.execute(
        select(AGENTS_CONFIGURABLES).where(*conditions)
        .order_by(AGENTS_CONFIGURABLES.c.id).limit(limite).offset(decalage)
    ).mappings()
    return [agents._profil(ligne) for ligne in lignes], total


def _orphelins(cnx: Connection, exportes: Iterable[str]) -> tuple[list[str], int]:
    """Identifiants exportés sans profil non archivé au registre : les ORPHELINS_MAX premiers et leur total exact.

    La comparaison se fait en SQL par lots ; seuls les identifiants orphelins, déjà bornés par la taille de
    l'export, sortent de la base. Le registre n'est jamais relu en entier."""
    connus = select(AGENTS_CONFIGURABLES.c.id).where(AGENTS_CONFIGURABLES.c.supprime.is_(False))
    tries = sorted(exportes)
    premiers: list[str] = []
    total = 0
    for debut in range(0, len(tries), ORPHELINS_LOT):
        lot = values(column("profil_exporte", String), name="exportes").data(
            [(ident,) for ident in tries[debut:debut + ORPHELINS_LOT]]
        ).cte()
        # Tri Python, comme les lots : l'ordre ne dépend pas de la collation de la base.
        trouves = sorted(cnx.execute(select(lot.c.profil_exporte).where(lot.c.profil_exporte.not_in(connus))).scalars())
        total += len(trouves)
        premiers.extend(trouves[:ORPHELINS_MAX - len(premiers)])
    return premiers, total


def resume_export(cnx: Connection, export: Mapping[str, Any]) -> dict[str, Any]:
    """Résumé de l'export ; les orphelins portent sur tout le registre non archivé, sans filtre de département."""
    orphelins, orphelins_total = _orphelins(cnx, export["revisions"])
    return {
        "statut": export["statut"],
        "ecrit_le": export["ecrit_le"],
        "source": SOURCE_EXPORT,
        "detail": DETAILS_EXPORT.get(export["statut"], "Export lu."),
        "limites": LIMITE_EXPORT,
        "profils_exportes": len(export["revisions"]) if export["statut"] == "LU" else None,
        "orphelins": orphelins,
        "orphelins_total": orphelins_total,
    }


def tableau(
    cnx: Connection,
    deps: Mapping[str, Departement],
    *,
    departement: str | None = None,
    limite: int = LIMITE_MAX,
    decalage: int = 0,
    export: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Une page bornée de profils avec leur état, lue par LIMIT/OFFSET ; le total vient d'un COUNT.

    `export` : la lecture déjà faite pour cette requête (une seule lecture du fichier par requête)."""
    valider_pagination(limite, decalage)
    page, total = page_registre(cnx, departement=departement, limite=limite, decalage=decalage)
    export = export if export is not None else lire_export(dossier_configuration_core())
    manifestes = _manifestes(deps, page)
    return {
        "agents": [{**p, "etat": etat_profil(cnx, p, export, manifestes)} for p in page],
        "export": resume_export(cnx, export),
        "pagination": {"total": total, "limite": limite, "decalage": decalage, "retournes": len(page)},
    }


def etat_unique(
    cnx: Connection,
    deps: Mapping[str, Departement],
    profil: Mapping[str, Any],
    *,
    export: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    export = export if export is not None else lire_export(dossier_configuration_core())
    return etat_profil(cnx, profil, export, _manifestes(deps, [profil]))
