"""File d'approbation humaine (human-in-the-loop), indépendante du moteur d'agents.

Quand la politique l'exige, l'appel d'outil n'est PAS exécuté : une demande est enregistrée
et l'agent reçoit « en attente d'approbation ». Un humain décide depuis le dashboard ou la
CLI ; l'approbation exécute l'outil avec les arguments exacts enregistrés, jamais d'autres.

`decider` s'exécute dans la transaction de `cnx` (ADR-0009) : réservation, exécution de l'outil
et statut final sont donc atomiques avec les écritures métier de l'outil (`outils.executer_atomique`,
qui ouvre un point de sauvegarde puisque cette transaction est déjà ouverte).

Identité et rôles (ADR-0009 §5, PLAN T1.3-a) : `decider` exige une personne active (`opsys.identite`)
dont un rôle figure dans la politique d'approbation de SON département (`opsys.departements.
PolitiqueApprobation`) pour le niveau N de la demande — sinon refus nommé, rien exécuté, la demande
reste `en_attente`. Le niveau N est figé sur la demande à sa création (`creer_demande`), pas
recalculé à la décision : la politique lue au moment de la demande reste celle appliquée. La
décision enregistre la personne (`decide_par`, un identifiant de `personnes`) ET le rôle utilisé
(`decide_role`). Une demande N5 exige en plus une attestation du professionnel (ADR-0009 §5) :
sans elle, refus nommé.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Connection, insert, select, update

from . import identite
from .contexte import appeler_en_tant_que
from .departements import DEFAUT_ROLES_NIVEAU, Departement
from .etat import journaliser
from .outils import Niveau, Outil, executer_atomique
from .politiques import MODES, valider_mode
from .stockage.moteur import inserer
from .stockage.schema import APPROBATIONS, MODES_DEPARTEMENTS

logger = logging.getLogger("opsys.approbations")

# Forme commune d'une « attente » (file du propriétaire, ADR-0009 §5, PLAN T1.3-a §6) : que ce soit
# une demande d'approbation du socle ou une attente déclarée par un département (`attentes()`).
CHAMPS_ATTENTE = ("type", "id", "resume", "niveau", "depuis", "action_proposee")
# Champs de l'attestation professionnelle exigée pour approuver une demande N5 (ADR-0009 §5).
CHAMPS_ATTESTATION = ("nom", "profession", "reference_document")


def _maintenant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def creer_demande(
    cnx: Connection, departement: str, outil: str, arguments: Mapping[str, Any], *, niveau: Niveau,
    motif: str = "",
) -> str:
    """Enregistre une demande en attente, au niveau N figé (ADR-0009 §4) : `decider` s'y fiera pour
    savoir quels rôles peuvent trancher, même si l'outil change de niveau ensuite."""
    ident = uuid.uuid4().hex[:12]
    cnx.execute(insert(APPROBATIONS).values(
        id=ident, cree_le=_maintenant(), departement=departement, outil=outil,
        arguments=json.dumps(dict(arguments), ensure_ascii=False), motif_demande=motif, statut="en_attente",
        niveau=Niveau(niveau).value,
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
        if demande["attestation"]:
            demande["attestation"] = json.loads(demande["attestation"])
        resultat.append(demande)
    return resultat


def _valider_attestation(attestation: Mapping[str, Any] | None) -> dict[str, str]:
    """N5 exige l'attestation du professionnel (nom, profession, référence du document joint),
    ADR-0009 §5 : en plus de la signature du propriétaire, jamais automatique."""
    if not isinstance(attestation, Mapping):
        raise ValueError(
            "demande N5 : attestation du professionnel requise "
            f"({', '.join(CHAMPS_ATTESTATION)}, ADR-0009 §5)"
        )
    valeurs: dict[str, str] = {}
    for champ in CHAMPS_ATTESTATION:
        valeur = attestation.get(champ)
        if not isinstance(valeur, str) or not valeur.strip():
            raise ValueError(f"attestation N5 : champ requis manquant ou vide : {champ}")
        valeurs[champ] = valeur.strip()
    return valeurs


def decider(
    cnx: Connection,
    ident: str,
    approuver: bool,
    identifiant: str,
    outils: Mapping[str, Outil],
    departements: Mapping[str, Departement],
    motif: str = "",
    attestation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Refuse ou approuve (et exécute) une demande en attente, une seule fois.

    `identifiant` doit être celui d'une personne active (`opsys.identite`) portant, dans le
    département de la demande, un rôle autorisé pour son niveau N (ADR-0009 §5) — sinon
    `ValueError` nommée, rien exécuté, la demande reste `en_attente` : ce garde s'applique à
    l'approbation ET au refus, avant toute réservation. Une demande N5 exige en plus `attestation`
    (voir `_valider_attestation`) pour être APPROUVÉE ; un refus n'en a pas besoin.

    La demande est ensuite réservée atomiquement (`en_attente` → `en_cours`) : deux approbations
    concurrentes ne peuvent jamais exécuter l'outil deux fois. Toute exception pendant l'exécution
    termine la demande en `echec` : jamais de retour à `en_attente`.
    """
    if not identifiant or not identifiant.strip():
        raise ValueError("la décision doit être signée par une personne active (identifiant)")
    identifiant = identifiant.strip()
    ligne = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == ident)).mappings().fetchone()
    if ligne is None:
        raise KeyError(f"demande inconnue : {ident}")
    if ligne["statut"] != "en_attente":
        raise ValueError(f"demande {ident} déjà traitée ({ligne['statut']})")

    # Niveau figé à la création (fail-closed si absent : demande héritée de l'ancien etat.db,
    # pré-ADR-0009, qui n'en portait pas — voir la migration 0005).
    niveau = Niveau(ligne["niveau"]) if ligne["niveau"] else Niveau.N5
    departement = departements.get(ligne["departement"])
    roles_autorises = departement.roles_autorises(niveau) if departement is not None else DEFAUT_ROLES_NIVEAU
    personne = identite.personne_active(cnx, identifiant)
    if personne is None:
        raise ValueError(
            f"{identifiant!r} : personne inconnue ou inactive ; décision refusée, rien exécuté"
        )
    role_utilise = next((role for role in sorted(roles_autorises) if role in personne.roles), None)
    if role_utilise is None:
        raise ValueError(
            f"{identifiant} : aucun rôle autorisé pour {niveau.value} dans {ligne['departement']} "
            f"(autorisés : {', '.join(sorted(roles_autorises)) or 'aucun'}) ; décision refusée, rien exécuté"
        )
    attestation_valide = _valider_attestation(attestation) if (approuver and niveau is Niveau.N5) else None

    if not approuver:
        cnx.execute(
            update(APPROBATIONS)
            .where(APPROBATIONS.c.id == ident, APPROBATIONS.c.statut == "en_attente")
            .values(statut="refusee", decide_par=identifiant, decide_role=role_utilise, decide_le=_maintenant(),
                    motif_decision=motif)
        )
        journaliser(cnx, identifiant, "approbation.refuser", ident,
                   {"outil": ligne["outil"], "motif": motif, "role": role_utilise})
        return {"id": ident, "statut": "refusee"}
    outil = outils.get(ligne["outil"])
    if outil is None:
        raise KeyError(f"outil inconnu pour la demande {ident} : {ligne['outil']}")
    reservation = cnx.execute(
        update(APPROBATIONS)
        .where(APPROBATIONS.c.id == ident, APPROBATIONS.c.statut == "en_attente")
        .values(statut="en_cours", decide_par=identifiant, decide_role=role_utilise, decide_le=_maintenant(),
                attestation=json.dumps(attestation_valide, ensure_ascii=False) if attestation_valide else None)
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
    journaliser(cnx, identifiant, "approbation.approuver", ident,
               {"outil": ligne["outil"], "statut": statut, "role": role_utilise})
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


# -- file du propriétaire (ADR-0009 §5, PLAN T1.3-a §6) -------------------------------------------


def _valider_attente(departement_id: str, brute: Mapping[str, Any]) -> dict[str, Any]:
    """Une « attente » déclarée par `attentes()` doit porter les champs de `CHAMPS_ATTENTE`."""
    if not isinstance(brute, Mapping):
        raise TypeError(f"{departement_id} : attentes() doit renvoyer des objets (dict)")
    manquants = [champ for champ in CHAMPS_ATTENTE if champ not in brute]
    if manquants:
        raise ValueError(f"{departement_id} : attente incomplète, champs manquants : {manquants}")
    return {champ: brute[champ] for champ in CHAMPS_ATTENTE}


def file_proprietaire(
    cnx: Connection, departements: Mapping[str, Departement], limite: int = 100
) -> list[dict[str, Any]]:
    """Vue compacte de ce qui attend une décision du propriétaire : les demandes d'approbation du
    socle en attente, PLUS les « attentes » que chaque département déclare lui-même par une
    fonction `attentes()` optionnelle dans son `outils.py` (même mécanisme de découverte que
    `consommateurs()`, `opsys.departements.Departement.charger_attentes`, vérifié par `opsys
    verifier`). Forme commune de chaque élément (`CHAMPS_ATTENTE`) : type, id, resume, niveau,
    depuis, action_proposee — plus `departement`, l'origine. Triée par `depuis` croissant (la plus
    ancienne attente en premier).

    Un département dont `attentes()` échoue ou renvoie une forme invalide est journalisé (avertissement)
    et sauté : il ne bloque jamais la file. Aucun département de production n'implémente `attentes()`
    pour l'instant (PLAN T1.3-b/c) ; le mécanisme est exercé par les départements de démonstration
    des tests du socle.
    """
    items: list[dict[str, Any]] = []
    for demande in lister(cnx, "en_attente", limite):
        items.append({
            "type": "approbation",
            "id": demande["id"],
            "resume": f"{demande['outil']} ({demande['departement']})",
            "niveau": demande.get("niveau"),
            "depuis": demande["cree_le"],
            "action_proposee": "approuver ou refuser",
            "departement": demande["departement"],
        })
    for dep in departements.values():
        try:
            fonction = dep.charger_attentes()
        except Exception as exc:  # noqa: BLE001 — un département cassé ne bloque jamais la file
            logger.warning("%s : attentes() illisible (%s: %s)", dep.id, type(exc).__name__, exc)
            continue
        if fonction is None:
            continue
        try:
            declarees: Sequence[Mapping[str, Any]] = fonction() or ()
            valides = [{**_valider_attente(dep.id, brute), "departement": dep.id} for brute in declarees]
        except Exception as exc:  # noqa: BLE001 — idem : jamais une panne de la file
            logger.warning("%s : attentes() illisible (%s: %s)", dep.id, type(exc).__name__, exc)
            continue
        items.extend(valides)
    items.sort(key=lambda item: item["depuis"])
    return items
