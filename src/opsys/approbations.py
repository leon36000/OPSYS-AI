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

Validation humaine au départ (ADR-0009 §4, addendum T1.4-h) : la file ci-dessus sert les actions
qu'un AGENT propose. Quand la personne authentifiée d'un appareil lance elle-même une action N3, il
n'y a rien à mettre en attente : `signataire_valide` revérifie son identité en base et
`tracer_validation_au_depart` laisse, dans cette même table `approbations` (statut `executee`) et
dans le même journal d'audit que `decider`, la trace de qui a lancé quoi. Aucun second journal ; c'est
`opsys.capacites` qui décide QUAND cette voie s'applique (niveau, portée du rôle, appel d'appareil).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from . import identite
from .contexte import IdentiteAppelante, appeler_en_tant_que
from .departements import DEFAUT_ROLES_NIVEAU, Departement
from .etat import journaliser
from .idempotence import empreinte_arguments
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

# Trace d'une validation humaine au départ (ADR-0009 §4, addendum T1.4-h).
MOTIF_VALIDATION_AU_DEPART = "validation humaine au départ par la personne qui agit, ADR-0009 §4"
ACTION_VALIDATION_AU_DEPART = "approbation.valider_au_depart"
# Arguments dont la valeur n'entre JAMAIS telle quelle dans la trace : une donnée personnelle que le
# département conserve chiffrée, avec une clé destructible (PLAN T4.2, POLITIQUE-geolocalisation.md
# §5 — le fix GPS d'un pointage ; PLAN T4.1-a — l'adresse d'un chantier de client et les coordonnées
# saisies à la main, que M4 ne garde qu'en empreinte et chiffrées). `approbations.arguments` n'est ni
# chiffrée ni purgée : y copier la valeur en clair défairait la destruction cryptographique. La trace
# garde l'empreinte des arguments réels (`empreinte_arguments`, celle de l'idempotence) : elle reste
# vérifiable sans les révéler.
ARGUMENTS_MASQUES_DANS_LA_TRACE = frozenset({
    "fix_gps", "adresse", "latitude_microdegres", "longitude_microdegres",
})
VALEUR_MASQUEE = "[masqué : donnée personnelle, conservée chiffrée dans le registre du département]"


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


def _demande_depuis_ligne(ligne: Mapping[str, Any]) -> dict[str, Any]:
    """Une ligne de `approbations`, avec ses colonnes JSON décodées (arguments, résultat, attestation)."""
    demande = dict(ligne)
    demande["arguments"] = json.loads(demande["arguments"])
    if demande["resultat"]:
        demande["resultat"] = json.loads(demande["resultat"])
    if demande["attestation"]:
        demande["attestation"] = json.loads(demande["attestation"])
    return demande


def lister(
    cnx: Connection, statut: str | None = None, limite: int = 100, *, plus_anciennes_d_abord: bool = False
) -> list[dict[str, Any]]:
    """Demandes d'approbation, la plus récente d'abord ; `plus_anciennes_d_abord` renverse l'ordre AVANT
    de limiter (la file du propriétaire traite la plus ancienne en premier : une limite ne doit jamais
    la faire tomber)."""
    ordre = APPROBATIONS.c.cree_le.asc() if plus_anciennes_d_abord else APPROBATIONS.c.cree_le.desc()
    requete = select(APPROBATIONS).order_by(ordre).limit(limite)
    if statut:
        requete = requete.where(APPROBATIONS.c.statut == statut)
    return [_demande_depuis_ligne(ligne) for ligne in cnx.execute(requete).mappings()]


def lire(cnx: Connection, ident: str) -> dict[str, Any] | None:
    """Une demande par identifiant, ou None si elle n'existe pas. Lecture seule."""
    ligne = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == ident)).mappings().fetchone()
    return None if ligne is None else _demande_depuis_ligne(ligne)


def compter(cnx: Connection, statut: str) -> int:
    """Nombre exact de demandes à ce statut (`tableau_de_bord.nombre_en_attente` plafonne, pas ceci)."""
    return int(cnx.execute(select(func.count()).select_from(APPROBATIONS)
                           .where(APPROBATIONS.c.statut == statut)).scalar_one())


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
    *,
    role: str | None = None,
    appareil: str | None = None,
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

    `role` (T1.4-f, décision depuis l'app) : le rôle sous lequel la personne signe, s'il faut le
    nommer plutôt que prendre le premier rôle autorisé dans l'ordre alphabétique (une personne qui
    porte `admin` ET `nathan_owner` signerait sinon `admin`). Il doit être porté par la personne ET
    autorisé pour ce niveau dans ce département : sinon le même refus nommé, rien exécuté. Sans lui,
    comportement inchangé. `appareil` (T1.4-f) : l'appareil d'où vient la décision, ajouté au journal
    d'audit à côté de la personne et du rôle ; absent, l'entrée de journal ne change pas.
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
    if role is None:
        role_utilise = next((r for r in sorted(roles_autorises) if r in personne.roles), None)
    else:
        role_utilise = role if (role in roles_autorises and role in personne.roles) else None
    if role_utilise is None:
        demande_de_role = f" ; rôle demandé : {role}" if role is not None else ""
        raise ValueError(
            f"{identifiant} : aucun rôle autorisé pour {niveau.value} dans {ligne['departement']} "
            f"(autorisés : {', '.join(sorted(roles_autorises)) or 'aucun'}{demande_de_role}) ; "
            "décision refusée, rien exécuté"
        )
    trace_appareil = {"appareil": appareil} if appareil else {}
    attestation_valide = _valider_attestation(attestation) if (approuver and niveau is Niveau.N5) else None

    if not approuver:
        cnx.execute(
            update(APPROBATIONS)
            .where(APPROBATIONS.c.id == ident, APPROBATIONS.c.statut == "en_attente")
            .values(statut="refusee", decide_par=identifiant, decide_role=role_utilise, decide_le=_maintenant(),
                    motif_decision=motif)
        )
        journaliser(cnx, identifiant, "approbation.refuser", ident,
                   {"outil": ligne["outil"], "motif": motif, "role": role_utilise, **trace_appareil})
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
               {"outil": ligne["outil"], "statut": statut, "role": role_utilise, **trace_appareil})
    return {"id": ident, "statut": statut, "reponse": reponse}


# -- validation humaine au départ (ADR-0009 §4, addendum T1.4-h) -----------------------------------


def signataire_valide(cnx: Connection, appelante: IdentiteAppelante | None) -> IdentiteAppelante | None:
    """L'identité de jeton d'appareil `appelante`, si et seulement si elle est encore valide EN BASE ;
    None sinon (chemin normal : rien n'est refusé ici, l'appelant retombe sur la file d'approbation).

    Valide = la personne existe ET est active ET porte encore le rôle que le jeton déclare
    (`identite.personne_active`, relu à chaque appel : une personne désactivée ou dont on a retiré
    le rôle depuis l'appairage n'obtient aucun passe-droit). `IdentiteAppelante` ne fait que rendre ce
    que le core a transmis en `_meta` (`contexte.identite_appelante`) ; c'est ici qu'on la revérifie.

    Ne vérifie PAS l'authenticité de l'appel, que le socle ne peut pas établir seul : elle repose sur
    OPSYS-CORE, qui n'émet `opsys/personne`/`opsys/role` que pour un jeton d'appareil vérifié
    (docs/architecture/IDEMPOTENCE.md §7 bis). Ne vérifie pas non plus la portée d'outil du rôle :
    c'est `opsys.capacites` qui la contrôle. Aucune écriture.
    """
    if appelante is None:
        return None
    personne = identite.personne_active(cnx, appelante.personne)
    if personne is None or appelante.role not in personne.roles:
        return None
    return appelante


def arguments_masques(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Copie des arguments où les valeurs de `ARGUMENTS_MASQUES_DANS_LA_TRACE` sont remplacées par
    `VALEUR_MASQUEE` (une valeur nulle reste nulle : rien à masquer, et « masqué » serait faux).
    Pour la trace d'une validation au départ ET pour tout affichage d'arguments hors de la console
    (l'app du propriétaire, T1.4-f) : une seule règle de masquage."""
    return {
        cle: VALEUR_MASQUEE if (cle in ARGUMENTS_MASQUES_DANS_LA_TRACE and valeur is not None) else valeur
        for cle, valeur in arguments.items()
    }


_arguments_de_la_trace = arguments_masques  # nom d'origine (la trace), gardé : un test l'appelle


def tracer_validation_au_depart(
    cnx: Connection, departement: str, outil: str, arguments: Mapping[str, Any], *, niveau: Niveau,
    signataire: IdentiteAppelante, reponse: Mapping[str, Any], appareil: str | None = None,
) -> str:
    """Trace, dans la transaction de `cnx`, une action que `signataire` a lancée lui-même et que
    l'outil a déjà exécutée ; rend l'identifiant de la trace.

    Deux écritures, aucune autre : (1) une ligne `approbations` au statut `executee` — qui
    (`decide_par`, `decide_role`), quoi (`outil`, `arguments`, `niveau`), quand (`cree_le`,
    `decide_le`), pourquoi (`motif_decision` = `MOTIF_VALIDATION_AU_DEPART`) ; c'est la même table que
    celle de la file, donc `opsys_demandes_approbation` et la console la montrent ; (2) l'entrée
    d'audit `ACTION_VALIDATION_AU_DEPART` dans le journal que `decider` alimente déjà (appareil et
    empreinte des arguments réels y figurent). Pas de table ni de journal nouveaux.

    `arguments` est conservé tel quel, sauf `ARGUMENTS_MASQUES_DANS_LA_TRACE`. `resultat` ne garde que
    l'issue (`ok`, et `accepte` quand l'outil rend un verdict au sens de `outils.depuis_couple`) : les
    données produites vivent dans les registres du département, écrits dans la même transaction.

    L'appelant (`Capacites._valider_au_depart`) l'appelle DANS le même point de sauvegarde que
    l'exécution de l'outil : si cette insertion échoue, l'exécution est annulée avec elle.
    """
    ident = uuid.uuid4().hex[:12]
    maintenant = _maintenant()
    issue: dict[str, Any] = {"ok": bool(reponse.get("ok"))}
    resultat = reponse.get("resultat")
    if isinstance(resultat, Mapping) and "accepte" in resultat:
        issue["accepte"] = resultat["accepte"]
    cnx.execute(insert(APPROBATIONS).values(
        id=ident, cree_le=maintenant, departement=departement, outil=outil,
        arguments=json.dumps(arguments_masques(arguments), ensure_ascii=False),
        statut="executee", niveau=Niveau(niveau).value,
        decide_par=signataire.personne, decide_role=signataire.role, decide_le=maintenant,
        motif_decision=MOTIF_VALIDATION_AU_DEPART, resultat=json.dumps(issue, ensure_ascii=False),
    ))
    journaliser(cnx, signataire.personne, ACTION_VALIDATION_AU_DEPART, ident, {
        "outil": outil, "departement": departement, "niveau": Niveau(niveau).value,
        "role": signataire.role, "appareil": appareil, "motif": MOTIF_VALIDATION_AU_DEPART,
        "empreinte_arguments": empreinte_arguments(arguments),
    })
    return ident


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


def attentes_departements(
    cnx: Connection, departements: Mapping[str, Departement]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Les « attentes » que chaque département déclare par sa fonction `attentes()` optionnelle
    (forme `CHAMPS_ATTENTE`, plus `departement`, l'origine), triées par `depuis` croissant, ET les
    identifiants des départements dont `attentes()` n'a pas pu être lue.

    Un département dont `attentes()` échoue ou renvoie une forme invalide est journalisé (avertissement)
    et sauté : il ne bloque jamais la file. Mais son silence ne veut pas dire « rien à signaler » : il est
    rendu dans la seconde liste, pour que l'appelant puisse le dire (fail-closed, PLAN T1.5).
    """
    items: list[dict[str, Any]] = []
    illisibles: list[str] = []
    for dep in departements.values():
        try:
            fonction = dep.charger_attentes()
        except Exception as exc:  # noqa: BLE001 — un département cassé ne bloque jamais la file
            logger.warning("%s : attentes() illisible (%s: %s)", dep.id, type(exc).__name__, exc)
            illisibles.append(dep.id)
            continue
        if fonction is None:
            continue
        try:
            declarees: Sequence[Mapping[str, Any]] = fonction() or ()
            valides = [{**_valider_attente(dep.id, brute), "departement": dep.id} for brute in declarees]
        except Exception as exc:  # noqa: BLE001 — idem : jamais une panne de la file
            logger.warning("%s : attentes() illisible (%s: %s)", dep.id, type(exc).__name__, exc)
            illisibles.append(dep.id)
            continue
        items.extend(valides)
    items.sort(key=lambda item: item["depuis"])
    return items, illisibles


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
    et sauté : il ne bloque jamais la file (voir `attentes_departements`). M4 (complétions en revue) et
    M5 (factures à envoyer, chantiers à réviser) déclarent les leurs depuis T1.3-b et T1.3-c.
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
    items.extend(attentes_departements(cnx, departements)[0])
    items.sort(key=lambda item: item["depuis"])
    return items
