"""File d'approbation humaine (human-in-the-loop), indépendante du moteur d'agents.

Quand la politique l'exige, l'appel d'outil n'est PAS exécuté : une demande est enregistrée
et l'agent reçoit « en attente d'approbation ». Un humain décide depuis le dashboard ou la
CLI ; l'approbation exécute l'outil avec les arguments exacts enregistrés, jamais d'autres.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid
from collections.abc import Mapping
from typing import Any

from .contexte import appeler_en_tant_que
from .etat import journaliser
from .outils import Outil, executer
from .politiques import MODES, valider_mode


def _maintenant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def creer_demande(
    cnx: sqlite3.Connection, departement: str, outil: str, arguments: Mapping[str, Any], motif: str = ""
) -> str:
    ident = uuid.uuid4().hex[:12]
    cnx.execute(
        "INSERT INTO approbations (id, cree_le, departement, outil, arguments, motif_demande, statut)"
        " VALUES (?, ?, ?, ?, ?, ?, 'en_attente')",
        (ident, _maintenant(), departement, outil, json.dumps(dict(arguments), ensure_ascii=False), motif),
    )
    return ident


def lister(cnx: sqlite3.Connection, statut: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    requete = "SELECT * FROM approbations"
    parametres: tuple[Any, ...] = ()
    if statut:
        requete += " WHERE statut = ?"
        parametres = (statut,)
    requete += " ORDER BY cree_le DESC LIMIT ?"
    lignes = cnx.execute(requete, (*parametres, limite)).fetchall()
    resultat = []
    for ligne in lignes:
        demande = dict(ligne)
        demande["arguments"] = json.loads(demande["arguments"])
        if demande["resultat"]:
            demande["resultat"] = json.loads(demande["resultat"])
        resultat.append(demande)
    return resultat


def decider(
    cnx: sqlite3.Connection,
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
    ligne = cnx.execute("SELECT * FROM approbations WHERE id = ?", (ident,)).fetchone()
    if ligne is None:
        raise KeyError(f"demande inconnue : {ident}")
    if ligne["statut"] != "en_attente":
        raise ValueError(f"demande {ident} déjà traitée ({ligne['statut']})")
    if not approuver:
        cnx.execute(
            "UPDATE approbations SET statut='refusee', decide_par=?, decide_le=?, motif_decision=?"
            " WHERE id=? AND statut='en_attente'",
            (par, _maintenant(), motif, ident),
        )
        journaliser(cnx, par, "approbation.refuser", ident, {"outil": ligne["outil"], "motif": motif})
        return {"id": ident, "statut": "refusee"}
    outil = outils.get(ligne["outil"])
    if outil is None:
        raise KeyError(f"outil inconnu pour la demande {ident} : {ligne['outil']}")
    reservation = cnx.execute(
        "UPDATE approbations SET statut='en_cours', decide_par=?, decide_le=? WHERE id=? AND statut='en_attente'",
        (par, _maintenant(), ident),
    )
    if reservation.rowcount != 1:
        raise ValueError(f"demande {ident} déjà prise en charge par une autre décision")
    try:
        with appeler_en_tant_que(ligne["departement"]):
            reponse = executer(outil, json.loads(ligne["arguments"]))
    except Exception as exc:  # noqa: BLE001 — toute panne clôt la demande, sans la rejouer
        reponse = {"ok": False, "erreur": "panne_execution", "details": f"{type(exc).__name__}: {exc}"}
    statut = "executee" if reponse["ok"] else "echec"
    cnx.execute(
        "UPDATE approbations SET statut=?, motif_decision=?, resultat=? WHERE id=? AND statut='en_cours'",
        (statut, motif, json.dumps(reponse, ensure_ascii=False), ident),
    )
    journaliser(cnx, par, "approbation.approuver", ident, {"outil": ligne["outil"], "statut": statut})
    return {"id": ident, "statut": statut, "reponse": reponse}


def mode_effectif(cnx: sqlite3.Connection, departement: str, mode_manifeste: str) -> str:
    """Mode fixé depuis le dashboard s'il existe, sinon celui du manifeste."""
    ligne = cnx.execute(
        "SELECT mode FROM modes_departements WHERE departement = ?", (departement,)
    ).fetchone()
    return ligne["mode"] if ligne else valider_mode(mode_manifeste)


def fixer_mode(cnx: sqlite3.Connection, departement: str, mode: str, par: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode inconnu {mode!r}")
    if not par.strip():
        raise ValueError("le changement de mode doit être signé (par)")
    cnx.execute(
        "INSERT INTO modes_departements (departement, mode, modifie_par, modifie_le) VALUES (?,?,?,?)"
        " ON CONFLICT(departement) DO UPDATE SET mode=excluded.mode,"
        " modifie_par=excluded.modifie_par, modifie_le=excluded.modifie_le",
        (departement, mode, par, _maintenant()),
    )
    journaliser(cnx, par, "departement.mode", departement, {"mode": mode})
