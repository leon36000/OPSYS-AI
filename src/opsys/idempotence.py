"""Idempotence des mutations d'appareil (T1.4-b). Contrat complet : `docs/architecture/IDEMPOTENCE.md`.

La clé d'idempotence et l'identité de l'appareil voyagent dans le `_meta` MCP de `tools/call`
(`opsys/idempotencyKey`, `opsys/appareil`, `opsys/horodatageAppareil`), jamais dans les arguments de
l'outil que le modèle produit. `serveur_mcp.appeler_outil` lit `params.meta` et appelle
`depuis_meta_mcp` pour obtenir une structure typée (`Meta`), passée telle quelle à
`Capacites.appeler` : ce module ne connaît rien de MCP au-delà de cette frontière.

`reclamer` pose la réclamation `(appareil, cle_idempotence)` dans la transaction de l'appel
(`stockage.transaction`, imbriquée en point de sauvegarde comme toute écriture métier, ADR-0009) :
une réclamation concurrente de la même clé attend (SQLite : verrou exclusif `BEGIN IMMEDIATE` dès
l'ouverture de la transaction, § `stockage.moteur`) ou échoue proprement puis se résout par relecture
(PostgreSQL : contrainte unique de la clé primaire). Jamais deux exécutions.

`finaliser` n'est appelée qu'après une exécution fraîche aboutie (au sens large : succès, refus
métier ou mise en attente d'approbation — toute réponse normale, cf. `outils.py`). Une panne interne
(exception non attrapée pendant l'exécution) n'appelle jamais `finaliser` : la transaction entière,
réclamation comprise, est alors annulée par `stockage.transaction` — un renvoi réel réessaiera.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import IntegrityError

from .outils import vers_json
from .stockage import EcritureConcurrente, codec
from .stockage.schema import MUTATIONS_APPLIQUEES

CLE_META = "opsys/idempotencyKey"
APPAREIL_META = "opsys/appareil"
HORODATAGE_META = "opsys/horodatageAppareil"


class MutationConflit(ValueError):
    """La clé d'idempotence sert déjà à un autre outil ou à d'autres arguments."""


@dataclasses.dataclass(frozen=True)
class Meta:
    """Idempotence d'un appel, lue depuis le `_meta` MCP — jamais depuis les arguments de l'outil."""

    cle: str
    appareil: str
    horodatage_appareil: str  # RFC 3339 tel que reçu, conservé sans reformatage (audit, R12 §4)


@dataclasses.dataclass(frozen=True)
class Reclamation:
    rejouee: bool
    reponse: dict[str, Any] | None = None  # rendu seulement si rejouee


def _horodatage_valide(valeur: str) -> bool:
    try:
        analyse = dt.datetime.fromisoformat(valeur)
    except ValueError:
        return False
    return analyse.tzinfo is not None


def depuis_meta_mcp(meta: Mapping[str, Any] | None) -> Meta | None:
    """Structure typée depuis `params.meta` (MCP `_meta`) ; None si aucune idempotence demandée
    (aucune `opsys/idempotencyKey`) — dans ce cas, `Capacites.appeler` reste inchangée.

    Lève ValueError si la clé est présente mais l'appareil ou l'horodatage manque ou est mal formé :
    fail-closed, un refus explicite vaut mieux qu'une idempotence tue en silence.
    """
    if not meta or CLE_META not in meta:
        return None
    cle, appareil, horodatage = meta.get(CLE_META), meta.get(APPAREIL_META), meta.get(HORODATAGE_META)
    if not isinstance(cle, str) or not cle.strip():
        raise ValueError(f"{CLE_META} doit être une chaîne non vide")
    if not isinstance(appareil, str) or not appareil.strip():
        raise ValueError(f"{APPAREIL_META} requis (chaîne non vide) quand {CLE_META} est fourni")
    if not isinstance(horodatage, str) or not _horodatage_valide(horodatage):
        raise ValueError(f"{HORODATAGE_META} doit être un horodatage RFC 3339 avec fuseau")
    return Meta(cle=cle, appareil=appareil, horodatage_appareil=horodatage)


def empreinte_arguments(arguments: Mapping[str, Any]) -> str:
    """Empreinte stable des arguments (clés triées, récursivement) : distingue un renvoi légitime
    d'une réutilisation de la même clé pour un appel différent (`MutationConflit`)."""
    canonique = json.dumps(vers_json(dict(arguments)), sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"))
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def _lire(cnx: Connection, meta: Meta) -> Mapping[str, Any] | None:
    requete = select(MUTATIONS_APPLIQUEES).where(
        (MUTATIONS_APPLIQUEES.c.appareil == meta.appareil)
        & (MUTATIONS_APPLIQUEES.c.cle_idempotence == meta.cle)
    )
    return cnx.execute(requete).mappings().fetchone()


def reclamer(
    cnx: Connection, meta: Meta, nom_outil: str, arguments: Mapping[str, Any], recu_le: dt.datetime
) -> Reclamation:
    """Pose ou relit la réclamation `(appareil, cle)`, dans la transaction courante de `cnx`.

    Rend une exécution fraîche (`rejouee=False` ; rien n'est encore écrit, `finaliser` s'en charge)
    ou un renvoi (`rejouee=True`, `reponse` déjà enregistrée). Lève `MutationConflit` si la clé sert
    déjà à un autre outil ou à d'autres arguments : rien n'est exécuté ni modifié en base.
    """
    empreinte = empreinte_arguments(arguments)
    ligne = _lire(cnx, meta)
    if ligne is None:
        try:
            with cnx.begin_nested():
                cnx.execute(insert(MUTATIONS_APPLIQUEES).values(
                    appareil=meta.appareil, cle_idempotence=meta.cle, outil=nom_outil,
                    empreinte_arguments=empreinte, reponse=codec.encoder(None),
                    horodatage_appareil=meta.horodatage_appareil,
                    recu_le=recu_le.isoformat(timespec="seconds"), statut="en_cours",
                ))
        except IntegrityError:
            # Réclamée entre notre lecture et notre écriture. SQLite ne peut pas atteindre cette
            # branche (BEGIN IMMEDIATE sérialise déjà les écrivains, § stockage.moteur) ; sous
            # PostgreSQL, la gagnante a validé avant que notre insertion, bloquée par la contrainte
            # unique le temps de sa transaction, ne soit rejetée — elle est donc déjà visible ici.
            ligne = _lire(cnx, meta)
            if ligne is None:  # concurrence résolue par un rollback plutôt qu'un commit : très rare
                raise EcritureConcurrente(
                    f"réclamation concurrente non résolue pour {meta.appareil}/{meta.cle}"
                ) from None
        else:
            return Reclamation(rejouee=False)
    if ligne["outil"] != nom_outil or ligne["empreinte_arguments"] != empreinte:
        raison = "un autre outil" if ligne["outil"] != nom_outil else "d'autres arguments"
        raise MutationConflit(
            f"clé {meta.cle!r} de l'appareil {meta.appareil!r} déjà utilisée pour {raison} "
            f"({ligne['outil']!r})"
        )
    return Reclamation(rejouee=True, reponse=codec.decoder(ligne["reponse"]))


def finaliser(cnx: Connection, meta: Meta, reponse: Mapping[str, Any]) -> None:
    """Enregistre la réponse d'une exécution fraîche (jamais appelée pour un renvoi ni un conflit).

    Écrase le `en_cours` posé par `reclamer`. Si l'appelant n'atteint jamais `finaliser` (panne
    interne : exception non attrapée), `stockage.transaction` annule toute la transaction et la
    réclamation disparaît avec elle — un renvoi réel réessaiera, comme l'exige T1.4-b.
    """
    cnx.execute(update(MUTATIONS_APPLIQUEES).where(
        (MUTATIONS_APPLIQUEES.c.appareil == meta.appareil)
        & (MUTATIONS_APPLIQUEES.c.cle_idempotence == meta.cle)
    ).values(reponse=codec.encoder(dict(reponse)), statut=_statut(reponse)))


def _statut(reponse: Mapping[str, Any]) -> str:
    if reponse.get("statut") == "en_attente_approbation":
        return "en_attente_approbation"
    return "ok" if reponse.get("ok") else "refus_metier"
