"""File d'approbation humaine (human-in-the-loop), indépendante du moteur d'agents.

Quand la politique l'exige, l'appel d'outil n'est PAS exécuté : une demande est enregistrée
et l'agent reçoit « en attente d'approbation ». Un humain décide depuis le dashboard ou la
CLI ; l'approbation exécute l'outil avec les arguments exacts enregistrés, jamais d'autres.

`decider` s'exécute dans la transaction de `cnx` (ADR-0009) : réservation, exécution de l'outil
et statut final sont donc atomiques avec les écritures métier de l'outil (`outils.executer_atomique`,
qui ouvre un point de sauvegarde puisque cette transaction est déjà ouverte).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, insert, select, update

from .contexte import appeler_en_tant_que
from .etat import journaliser
from .outils import Outil, executer_atomique
from .politiques import MODES, valider_mode
from .stockage.moteur import inserer
from .stockage.schema import APPROBATIONS, MODES_DEPARTEMENTS


def _maintenant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def creer_demande(
    cnx: Connection, departement: str, outil: str, arguments: Mapping[str, Any], motif: str = ""
) -> str:
    ident = uuid.uuid4().hex[:12]
    cnx.execute(insert(APPROBATIONS).values(
        id=ident, cree_le=_maintenant(), departement=departement, outil=outil,
        arguments=json.dumps(dict(arguments), ensure_ascii=False), motif_demande=motif, statut="en_attente",
    ))
    return ident


def lister(cnx: Connection, statut: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    requete = select(APPROBATIONS).order_by(APPROBATIONS.c.cree_le.desc()).limit(limite)
    if statut:
        requete = requete.where(APPROBATIONS.c.statut == statut)
    resultat = []
    for ligne in cnx.execute(requete).mappings():
        demande = dict(ligne)
        demande["arguments"] = json.loads(demande["arguments"])
        if demande["resultat"]:
            demande["resultat"] = json.loads(demande["resultat"])
        resultat.append(demande)
    return resultat


def decider(
    cnx: Connection,
    ident: str,
    approuver: bool,
    par: str,
    outils: Mapping[str, Outil],
    motif: str = "",
) -> dict[str, Any]:
    """Refuse ou approuve (et exécute) une demande en attente, une seule fois.

    La demande est d'abord réservée atomiquement (`en_attente` → `en_cours`) : deux
    approbations concurrentes ne peuvent jamais exécuter l'outil deux fois. Toute exception
    pendant l'exécution termine la demande en `echec` : jamais de retour à `en_attente`.
    """
    if not par.strip():
        raise ValueError("la décision doit être signée (par)")
    ligne = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == ident)).mappings().fetchone()
    if ligne is None:
        raise KeyError(f"demande inconnue : {ident}")
    if ligne["statut"] != "en_attente":
        raise ValueError(f"demande {ident} déjà traitée ({ligne['statut']})")
    if not approuver:
        cnx.execute(
            update(APPROBATIONS)
            .where(APPROBATIONS.c.id == ident, APPROBATIONS.c.statut == "en_attente")
            .values(statut="refusee", decide_par=par, decide_le=_maintenant(), motif_decision=motif)
        )
        journaliser(cnx, par, "approbation.refuser", ident, {"outil": ligne["outil"], "motif": motif})
        return {"id": ident, "statut": "refusee"}
    outil = outils.get(ligne["outil"])
    if outil is None:
        raise KeyError(f"outil inconnu pour la demande {ident} : {ligne['outil']}")
    reservation = cnx.execute(
        update(APPROBATIONS)
        .where(APPROBATIONS.c.id == ident, APPROBATIONS.c.statut == "en_attente")
        .values(statut="en_cours", decide_par=par, decide_le=_maintenant())
    )
    if reservation.rowcount != 1:
        raise ValueError(f"demande {ident} déjà prise en charge par une autre décision")
    try:
        with appeler_en_tant_que(ligne["departement"]):
            reponse = executer_atomique(outil, json.loads(ligne["arguments"]))
    except Exception as exc:  # noqa: BLE001 — toute panne clôt la demande, sans la rejouer
        reponse = {"ok": False, "erreur": "panne_execution", "details": f"{type(exc).__name__}: {exc}"}
    statut = "executee" if reponse["ok"] else "echec"
    cnx.execute(
        update(APPROBATIONS)
        .where(APPROBATIONS.c.id == ident, APPROBATIONS.c.statut == "en_cours")
        .values(statut=statut, motif_decision=motif, resultat=json.dumps(reponse, ensure_ascii=False))
    )
    journaliser(cnx, par, "approbation.approuver", ident, {"outil": ligne["outil"], "statut": statut})
    return {"id": ident, "statut": statut, "reponse": reponse}


def mode_effectif(cnx: Connection, departement: str, mode_manifeste: str) -> str:
    """Mode fixé depuis le dashboard s'il existe, sinon celui du manifeste."""
    ligne = cnx.execute(
        select(MODES_DEPARTEMENTS.c.mode).where(MODES_DEPARTEMENTS.c.departement == departement)
    ).fetchone()
    return ligne[0] if ligne else valider_mode(mode_manifeste)


def fixer_mode(cnx: Connection, departement: str, mode: str, par: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode inconnu {mode!r}")
    if not par.strip():
        raise ValueError("le changement de mode doit être signé (par)")
    insertion = inserer(cnx)(MODES_DEPARTEMENTS).values(
        departement=departement, mode=mode, modifie_par=par, modifie_le=_maintenant()
    )
    cnx.execute(insertion.on_conflict_do_update(
        index_elements=[MODES_DEPARTEMENTS.c.departement],
        set_={"mode": insertion.excluded.mode, "modifie_par": insertion.excluded.modifie_par,
              "modifie_le": insertion.excluded.modifie_le},
    ))
    journaliser(cnx, par, "departement.mode", departement, {"mode": mode})
