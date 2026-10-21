"""Réservation atomique des plafonds déclarés pour les agents configurables.

Ce contrat borne une enveloppe de tokens. Il ne mesure pas les coûts du fournisseur; le runtime
doit réserver avant génération puis concilier avec l'usage exact reçu du provider.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, and_, func, insert, select, update

from . import identite
from .departements import Departement
from .stockage.moteur import inserer
from .stockage.schema import (
    AGENTS_CONFIGURABLES,
    AGENTS_POLITIQUE_ENTREPRISE,
    AGENTS_RESERVATIONS,
    AGENTS_RESERVATIONS_HISTORIQUE,
    PERSONNES,
    ROLES_PERSONNES,
    USAGE_TOKENS,
)

_MAX_TOKENS = 10_000_000_000
_MAX_I64 = (1 << 63) - 1
_MAX_TOURS = 100
_MAX_REESSAIS = 10
_REFERENCE_RELEVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")


class AdmissionRefusee(ValueError):
    """La réservation ne respecte pas un état ou plafond durable."""


def _maintenant() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _historiser(cnx: Connection, reservation_id: str, evenement: str, tokens: int | None, raison: str) -> None:
    cnx.execute(
        insert(AGENTS_RESERVATIONS_HISTORIQUE).values(
            id=uuid.uuid4().hex,
            reservation_id=reservation_id,
            evenement=evenement,
            tokens_reels=tokens,
            raison=raison,
            cree_le=_maintenant().isoformat(timespec="microseconds"),
        )
    )


def _reservation(ligne: Mapping[str, Any]) -> dict[str, Any]:
    resultat = {
        cle: ligne[cle]
        for cle in (
            "id",
            "agent_id",
            "departement",
            "cle_idempotence",
            "tokens_plafond",
            "tokens_reels",
            "execution_id",
            "jour",
            "mois",
            "tours",
            "reessais",
            "statut",
            "cree_le",
            "modifie_le",
        )
    }
    resultat["depassement_plafond"] = bool(
        resultat["tokens_reels"] is not None and resultat["tokens_reels"] > resultat["tokens_plafond"]
    )
    for cle in ("attempt_id", "cycle_id", "candidate_index", "stream_ordinal", "is_fallback_retry"):
        valeur = ligne.get(cle)
        if valeur is not None:
            resultat[cle] = bool(valeur) if cle == "is_fallback_retry" else valeur
    return resultat


def _preuve_revision_runtime(revision: int) -> str:
    """Capture structurée de la révision réellement admise, jamais celle d'un profil relu après coup."""
    return json.dumps(
        {"version": 1, "type": "runtime_admission", "revision_profil": revision},
        sort_keys=True, separators=(",", ":"),
    )


def lire_reservation(cnx: Connection, reservation_id: str, *, agent_id: str) -> dict[str, Any]:
    """Relit une réservation en la liant au profil fixé par la route, jamais à un agent fourni par le modèle."""
    ligne = _lire(cnx, reservation_id)
    if ligne["agent_id"] != agent_id:
        raise AdmissionRefusee("réservation refusée : elle n'appartient pas au profil lié à cette route")
    return _reservation(ligne)


def _verrouiller_politique(cnx: Connection) -> Mapping[str, Any]:
    """Sérialise les changements du ledger avec les calculs d'admission.

    Ordre canonique : politique entreprise, profil (pour reserver), puis réservation. Toute
    transition de réservation prend donc le verrou de politique avant de lire/modifier son état.
    Sans cela, un aggregate peut observer une réserve en vol pendant qu'une conciliation non
    commitée la remplace par un réel supérieur, puis admettre une nouvelle enveloppe sur ce stale.
    """
    ligne = (
        cnx.execute(select(AGENTS_POLITIQUE_ENTREPRISE).where(AGENTS_POLITIQUE_ENTREPRISE.c.id == 1).with_for_update())
        .mappings()
        .fetchone()
    )
    if ligne is None:
        raise AdmissionRefusee("admission refusée : plafond entreprise non configuré")
    return ligne


def configurer_plafonds_entreprise(
    cnx: Connection,
    budget_jour: int,
    budget_mois: int,
    *,
    par: str,
    revision_attendue: int,
) -> dict[str, Any]:
    """Configure les limites globales, avec compare-and-swap et autorité active relue en DB."""
    personne = identite.personne_active(cnx, par)
    if personne is None or not personne.roles.intersection({"admin", "nathan_owner"}):
        raise PermissionError("plafonds entreprise réservés à un administrateur actif ou propriétaire")
    if any(
        isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= _MAX_TOKENS for x in (budget_jour, budget_mois)
    ):
        raise ValueError(f"les plafonds entreprise doivent être entre 1 et {_MAX_TOKENS} tokens")
    if budget_mois < budget_jour:
        raise ValueError("le plafond mensuel entreprise doit couvrir le plafond journalier")
    if isinstance(revision_attendue, bool) or not isinstance(revision_attendue, int) or revision_attendue < 0:
        raise ValueError("revision_attendue doit être un entier >= 0")
    actuelle = (
        cnx.execute(select(AGENTS_POLITIQUE_ENTREPRISE).where(AGENTS_POLITIQUE_ENTREPRISE.c.id == 1).with_for_update())
        .mappings()
        .fetchone()
    )
    courante = 0 if actuelle is None else actuelle["revision"]
    if courante != revision_attendue:
        raise ValueError(
            f"conflit de révision des plafonds entreprise: attendue {revision_attendue}, courante {courante}"
        )
    maintenant = _maintenant().isoformat(timespec="seconds")
    prochaine = courante + 1
    statement = (
        inserer(cnx)(AGENTS_POLITIQUE_ENTREPRISE)
        .values(
            id=1,
            budget_jour=budget_jour,
            budget_mois=budget_mois,
            revision=prochaine,
            modifie_le=maintenant,
            modifie_par=par,
        )
        .on_conflict_do_update(
            index_elements=[AGENTS_POLITIQUE_ENTREPRISE.c.id],
            set_={
                "budget_jour": budget_jour,
                "budget_mois": budget_mois,
                "revision": prochaine,
                "modifie_le": maintenant,
                "modifie_par": par,
            },
            where=AGENTS_POLITIQUE_ENTREPRISE.c.revision == revision_attendue,
        )
        .returning(AGENTS_POLITIQUE_ENTREPRISE)
    )
    ligne = cnx.execute(statement).mappings().fetchone()
    if ligne is None:
        raise ValueError("conflit de révision des plafonds entreprise")
    return dict(ligne)


def _usage_externe(cnx: Connection, *, jour_min: str, jour_max: str, departement: str | None = None) -> int:
    requete = select(USAGE_TOKENS.c.tokens_entree, USAGE_TOKENS.c.tokens_sortie).where(
        USAGE_TOKENS.c.jour.between(jour_min, jour_max),
        USAGE_TOKENS.c.modele.not_like("agent:%"),
    )
    if departement is not None:
        requete = requete.where(USAGE_TOKENS.c.departement == departement)
    return sum(int(ligne[0]) + int(ligne[1]) for ligne in cnx.execute(requete))


def _usage_reservations(
    cnx: Connection,
    *,
    jour_min: str,
    jour_max: str,
    mois: str,
    agent_id: str | None = None,
    departement: str | None = None,
) -> int:
    conditions = []
    if agent_id is not None:
        conditions.append(AGENTS_RESERVATIONS.c.agent_id == agent_id)
    if departement is not None:
        conditions.append(AGENTS_RESERVATIONS.c.departement == departement)
    # Une exécution encore en vol réserve dans toute période présente: elle pourrait dépenser
    # après minuit ou un changement de mois. Les réservations terminées restent classées au jour
    # de conciliation; celles libérées n'entrent plus dans les comptes.
    depenses = sum(
        int(ligne[0])
        for ligne in cnx.execute(
            select(AGENTS_RESERVATIONS.c.tokens_reels).where(
                *conditions,
                AGENTS_RESERVATIONS.c.statut == "conciliee",
                AGENTS_RESERVATIONS.c.mois == mois,
                AGENTS_RESERVATIONS.c.jour.between(jour_min, jour_max),
            )
        )
    )
    en_vol = sum(
        int(ligne[0])
        for ligne in cnx.execute(
            select(AGENTS_RESERVATIONS.c.tokens_plafond).where(
                *conditions, AGENTS_RESERVATIONS.c.statut == "reservee"
            )
        )
    )
    return depenses + en_vol


def _borne(cnx: Connection, *, budget: int, dimension: str, cle: str, debut: str, fin: str, mois: str) -> int:
    if dimension == "entreprise":
        externe = _usage_externe(cnx, jour_min=debut, jour_max=fin)
        reserves = _usage_reservations(cnx, jour_min=debut, jour_max=fin, mois=mois)
    elif dimension == "departement":
        externe = _usage_externe(cnx, jour_min=debut, jour_max=fin, departement=cle)
        reserves = _usage_reservations(cnx, jour_min=debut, jour_max=fin, mois=mois, departement=cle)
    else:
        externe = 0
        reserves = _usage_reservations(cnx, jour_min=debut, jour_max=fin, mois=mois, agent_id=cle)
    return max(0, budget - externe - reserves)


def _cycle_suivant(
    cnx: Connection,
    *,
    agent_id: str,
    execution_id: str,
    attempt_id: str,
    candidate_index: int,
    stream_ordinal: int,
    is_fallback_retry: bool,
) -> None:
    """Valide la séquence runtime depuis les cycles persistés, pas depuis un compteur fourni."""
    rows = (
        cnx.execute(
            select(AGENTS_RESERVATIONS)
            .where(
                AGENTS_RESERVATIONS.c.agent_id == agent_id,
                AGENTS_RESERVATIONS.c.execution_id == execution_id,
            )
            .order_by(
                AGENTS_RESERVATIONS.c.candidate_index,
                AGENTS_RESERVATIONS.c.stream_ordinal,
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        if candidate_index != 0 or stream_ordinal != 0:
            raise AdmissionRefusee("admission refusée : le premier cycle doit commencer au candidat et ordinal 0")
        return
    if any(row["cycle_id"] is None for row in rows):
        raise AdmissionRefusee("admission refusée : protocoles legacy/runtime mélangés dans une exécution")

    dernier_candidat = max(int(row["candidate_index"]) for row in rows)
    derniers = [row for row in rows if row["candidate_index"] == dernier_candidat]
    if candidate_index == dernier_candidat:
        dernier = derniers[-1]
        if attempt_id != dernier["attempt_id"]:
            raise AdmissionRefusee("admission refusée : identifiant du candidat déjà utilisé avec une autre intention")
        if is_fallback_retry != bool(dernier["is_fallback_retry"]):
            raise AdmissionRefusee("admission refusée : indicateur fallback modifié pour le candidat")
        ordinal_attendu = max(int(row["stream_ordinal"]) for row in derniers) + 1
        if stream_ordinal != ordinal_attendu:
            raise AdmissionRefusee(f"admission refusée : ordinal de stream incohérent, attendu {ordinal_attendu}")
        return

    if candidate_index != dernier_candidat + 1:
        raise AdmissionRefusee("admission refusée : saut ou recul d'indice candidat")
    if not is_fallback_retry:
        raise AdmissionRefusee("admission refusée : nouveau candidat doit être marqué fallback")
    if stream_ordinal != 0:
        raise AdmissionRefusee("admission refusée : le premier stream d'un fallback doit avoir l'ordinal 0")
    if attempt_id in {row["attempt_id"] for row in rows}:
        raise AdmissionRefusee("admission refusée : le nouvel indice doit porter un nouvel attempt_id")


def reserver(
    cnx: Connection,
    agent_id: str,
    departements: Mapping[str, Departement],
    execution_id: str,
    cle_idempotence: str,
    tokens_plafond: int,
    *,
    tours: int,
    reessais: int | None = None,
    attempt_id: str | None = None,
    cycle_id: str | None = None,
    candidate_index: int | None = None,
    stream_ordinal: int | None = None,
    is_fallback_retry: bool | None = None,
    revision_profil: int | None = None,
) -> dict[str, Any]:
    """Réserve atomiquement une enveloppe avant appel runtime/provider.

    L'appelant doit utiliser une transaction d'écriture (`stockage.transaction`). La ligne politique
    entreprise est verrouillée avant les comptes, sérialisant les admissions transversales.
    """
    if not isinstance(execution_id, str) or not 8 <= len(execution_id) <= 128:
        raise ValueError("execution_id doit avoir de 8 à 128 caractères")
    if not isinstance(cle_idempotence, str) or not 8 <= len(cle_idempotence) <= 128:
        raise ValueError("cle_idempotence doit avoir de 8 à 128 caractères")
    if (
        isinstance(tokens_plafond, bool)
        or not isinstance(tokens_plafond, int)
        or not 1 <= tokens_plafond <= _MAX_TOKENS
    ):
        raise ValueError(f"tokens_plafond doit être entre 1 et {_MAX_TOKENS}")
    if isinstance(tours, bool) or not isinstance(tours, int) or not 1 <= tours <= _MAX_TOURS:
        raise ValueError(f"tours doit être entre 1 et {_MAX_TOURS}")
    runtime_values = (attempt_id, cycle_id, candidate_index, stream_ordinal, is_fallback_retry)
    runtime_mode = any(value is not None for value in runtime_values)
    if runtime_mode:
        if any(value is None for value in runtime_values):
            raise ValueError(
                "cycle runtime incomplet : attempt_id, cycle_id, candidate_index, stream_ordinal et fallback requis"
            )
        if not isinstance(attempt_id, str) or not 8 <= len(attempt_id) <= 160:
            raise ValueError("attempt_id doit avoir de 8 à 160 caractères")
        if not isinstance(cycle_id, str) or not 8 <= len(cycle_id) <= 160:
            raise ValueError("cycle_id doit avoir de 8 à 160 caractères")
        if isinstance(candidate_index, bool) or not isinstance(candidate_index, int) or candidate_index < 0:
            raise ValueError("candidate_index doit être un entier >= 0")
        if isinstance(stream_ordinal, bool) or not isinstance(stream_ordinal, int) or stream_ordinal < 0:
            raise ValueError("stream_ordinal doit être un entier >= 0")
        if not isinstance(is_fallback_retry, bool):
            raise ValueError("is_fallback_retry doit être booléen")
        if isinstance(revision_profil, bool) or not isinstance(revision_profil, int) or revision_profil < 1:
            raise ValueError("revision_profil doit être un entier positif pour une admission runtime")
        if attempt_id != f"{execution_id}:{candidate_index}":
            raise ValueError("attempt_id ne correspond pas à l'exécution et au candidat")
        if cycle_id != f"{attempt_id}:{stream_ordinal}":
            raise ValueError("cycle_id ne correspond pas à l'attempt et à l'ordinal")
        if is_fallback_retry != (candidate_index > 0):
            raise AdmissionRefusee("admission refusée : indicateur fallback incohérent avec le candidat")
        if tours != 1:
            raise AdmissionRefusee("admission refusée : chaque stream runtime compte exactement un tour")
        retries_canoniques = candidate_index
        if reessais is not None:
            if isinstance(reessais, bool) or not isinstance(reessais, int):
                raise ValueError("reessais doit être un entier non booléen")
            if reessais != retries_canoniques:
                raise AdmissionRefusee("admission refusée : compteur reessais incohérent avec le candidat")
        reessais = retries_canoniques
    elif reessais is None:
        reessais = 0
    if isinstance(reessais, bool) or not isinstance(reessais, int) or not 0 <= reessais <= _MAX_REESSAIS:
        raise ValueError(f"reessais doit être entre 0 et {_MAX_REESSAIS}")

    politique = _verrouiller_politique(cnx)
    profil = (
        cnx.execute(select(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == agent_id).with_for_update())
        .mappings()
        .fetchone()
    )
    if profil is None or not profil["actif"] or profil["supprime"]:
        raise AdmissionRefusee("admission refusée : profil inexistant, inactif ou supprimé")
    if runtime_mode and profil["revision"] != revision_profil:
        raise AdmissionRefusee("admission refusée : configuration de profil périmée")
    departement = departements.get(profil["departement"])
    if departement is None:
        raise AdmissionRefusee("admission refusée : budget du département indisponible")

    ancienne = (
        cnx.execute(
            select(AGENTS_RESERVATIONS).where(
                AGENTS_RESERVATIONS.c.agent_id == agent_id,
                AGENTS_RESERVATIONS.c.cle_idempotence == cle_idempotence,
            )
        )
        .mappings()
        .fetchone()
    )
    if ancienne is not None:
        intention_ancienne = (
            ancienne["execution_id"],
            ancienne["tokens_plafond"],
            ancienne["tours"],
            ancienne["reessais"],
            ancienne["attempt_id"],
            ancienne["cycle_id"],
            ancienne["candidate_index"],
            ancienne["stream_ordinal"],
            ancienne["is_fallback_retry"],
        )
        intention = (
            execution_id,
            tokens_plafond,
            tours,
            reessais,
            attempt_id,
            cycle_id,
            candidate_index,
            stream_ordinal,
            is_fallback_retry,
        )
        if intention_ancienne != intention:
            raise ValueError("conflit d'idempotence : clé réutilisée avec une réservation différente")
        return _reservation(ancienne)
    if runtime_mode:
        cycle_existant = (
            cnx.execute(
                select(AGENTS_RESERVATIONS).where(
                    AGENTS_RESERVATIONS.c.agent_id == agent_id,
                    AGENTS_RESERVATIONS.c.cycle_id == cycle_id,
                )
            )
            .mappings()
            .fetchone()
        )
        if cycle_existant is not None:
            raise ValueError("conflit de cycle : cycle_id rejoué avec une clé ou une intention différente")
        if candidate_index > profil["limite_reessais"]:
            raise AdmissionRefusee("admission refusée : limite de reessais dépassée")
        _cycle_suivant(
            cnx,
            agent_id=agent_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            candidate_index=candidate_index,
            stream_ordinal=stream_ordinal,
            is_fallback_retry=is_fallback_retry,
        )
    else:
        lignes_execution = cnx.execute(
            select(AGENTS_RESERVATIONS.c.cycle_id).where(
                AGENTS_RESERVATIONS.c.agent_id == agent_id,
                AGENTS_RESERVATIONS.c.execution_id == execution_id,
            )
        ).all()
        if any(row.cycle_id is not None for row in lignes_execution):
            raise AdmissionRefusee("admission refusée : protocoles runtime/legacy mélangés dans une exécution")
    if tours > profil["limite_tours"]:
        raise AdmissionRefusee("admission refusée : limite de tours dépassée")
    if not runtime_mode:
        tentatives_avant = int(
            cnx.execute(
                select(func.count())
                .select_from(AGENTS_RESERVATIONS)
                .where(
                    AGENTS_RESERVATIONS.c.agent_id == agent_id,
                    AGENTS_RESERVATIONS.c.execution_id == execution_id,
                )
            ).scalar_one()
        )
        if reessais != tentatives_avant:
            raise AdmissionRefusee("admission refusée : numéro de reessai incohérent avec l'exécution")
        if reessais > profil["limite_reessais"]:
            raise AdmissionRefusee("admission refusée : limite de reessais dépassée")
    tours_deja_reserves = int(
        cnx.execute(
            select(func.coalesce(func.sum(AGENTS_RESERVATIONS.c.tours), 0)).where(
                AGENTS_RESERVATIONS.c.agent_id == agent_id,
                AGENTS_RESERVATIONS.c.execution_id == execution_id,
            )
        ).scalar_one()
    )
    if tours_deja_reserves + tours > profil["limite_tours"]:
        raise AdmissionRefusee("admission refusée : limite de tours cumulée dépassée")
    actifs = int(
        cnx.execute(
            select(func.count())
            .select_from(AGENTS_RESERVATIONS)
            .where(AGENTS_RESERVATIONS.c.agent_id == agent_id, AGENTS_RESERVATIONS.c.statut == "reservee")
        ).scalar_one()
    )
    if actifs >= profil["limite_concurrence"]:
        raise AdmissionRefusee("admission refusée : limite de concurrence atteinte")

    now = _maintenant()
    jour = now.date().isoformat()
    debut_mois = now.date().replace(day=1).isoformat()
    mois = now.strftime("%Y-%m")
    plafonds = (
        ("agent", agent_id, profil["budget_jour"], jour, jour),
        ("agent", agent_id, profil["budget_mois"], debut_mois, jour),
        ("departement", profil["departement"], departement.budget.tokens_jour, jour, jour),
        ("departement", profil["departement"], departement.budget.tokens_mois, debut_mois, jour),
        ("entreprise", "entreprise", politique["budget_jour"], jour, jour),
        ("entreprise", "entreprise", politique["budget_mois"], debut_mois, jour),
    )
    for dimension, cle, plafond, debut, fin in plafonds:
        disponible = _borne(cnx, budget=plafond, dimension=dimension, cle=cle, debut=debut, fin=fin, mois=mois)
        if tokens_plafond > disponible:
            raise AdmissionRefusee(
                f"admission refusée : budget {dimension} insuffisant; disponible {disponible} tokens"
            )

    ident = hashlib.sha256(f"{agent_id}\0{cle_idempotence}".encode()).hexdigest()[:32]
    stamp = now.isoformat(timespec="seconds")
    cnx.execute(
        insert(AGENTS_RESERVATIONS).values(
            id=ident,
            agent_id=agent_id,
            departement=profil["departement"],
            cle_idempotence=cle_idempotence,
            execution_id=execution_id,
            tokens_plafond=tokens_plafond,
            tokens_reels=None,
            jour=jour,
            mois=mois,
            tours=tours,
            reessais=reessais,
            attempt_id=attempt_id,
            cycle_id=cycle_id,
            candidate_index=candidate_index,
            stream_ordinal=stream_ordinal,
            is_fallback_retry=is_fallback_retry,
            statut="reservee",
            cree_le=stamp,
            modifie_le=stamp,
        )
    )
    _historiser(
        cnx, ident, "reservee", None,
        _preuve_revision_runtime(revision_profil) if runtime_mode else "enveloppe réservée avant exécution",
    )
    ligne = cnx.execute(select(AGENTS_RESERVATIONS).where(AGENTS_RESERVATIONS.c.id == ident)).mappings().one()
    return _reservation(ligne)


def admettre_cycle_runtime(
    cnx: Connection,
    agent_id: str,
    departements: Mapping[str, Departement],
    execution_id: str,
    cle_idempotence: str,
    tokens_plafond: int,
    *,
    revision_profil: int,
    attempt_id: str,
    cycle_id: str,
    candidate_index: int,
    stream_ordinal: int,
    is_fallback_retry: bool,
    reessais: int | None = None,
) -> dict[str, Any]:
    """Délivre une autorisation de dispatch une seule fois par cycle runtime.

    Le verrou global et la recherche d'un cycle antérieur précèdent la création de la réservation,
    dans la même transaction. Contrairement à `reserver`, un rejeu déjà admis est refusé : un
    RPC dont le résultat commit n'est pas connu ne peut donc jamais redispatcher le provider.
    """
    _verrouiller_politique(cnx)
    if not isinstance(cycle_id, str) or not 8 <= len(cycle_id) <= 160:
        raise ValueError("cycle_id doit avoir de 8 à 160 caractères")
    existant = cnx.execute(
        select(AGENTS_RESERVATIONS.c.id).where(AGENTS_RESERVATIONS.c.cycle_id == cycle_id).with_for_update()
    ).first()
    if existant is not None:
        raise AdmissionRefusee("cycle déjà admis : rediffusion provider interdite")
    reservation = reserver(
        cnx,
        agent_id,
        departements,
        execution_id,
        cle_idempotence,
        tokens_plafond,
        tours=1,
        reessais=reessais,
        attempt_id=attempt_id,
        cycle_id=cycle_id,
        candidate_index=candidate_index,
        stream_ordinal=stream_ordinal,
        is_fallback_retry=is_fallback_retry,
        revision_profil=revision_profil,
    )
    return {**reservation, "accord_neuf": True}


def verifier_outil_runtime(
    cnx: Connection,
    agent_id: str,
    departements: Mapping[str, Departement],
    outil: str,
    revision_profil: int,
    *,
    verrouiller: bool = False,
) -> dict[str, Any]:
    """Vérifie la capacité profilée; le dispatch demande le verrou jusqu'à l'effet métier."""
    if not isinstance(outil, str) or not outil or len(outil) > 256:
        raise ValueError("outil runtime invalide")
    if isinstance(revision_profil, bool) or not isinstance(revision_profil, int) or revision_profil < 1:
        raise ValueError("revision_profil doit être un entier positif")
    requete = select(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == agent_id)
    if verrouiller:
        requete = requete.with_for_update()
    profil = cnx.execute(requete).mappings().fetchone()
    if profil is None or not profil["actif"] or profil["supprime"]:
        raise AdmissionRefusee("outil refusé : profil inexistant, inactif ou supprimé")
    if profil["revision"] != revision_profil:
        raise AdmissionRefusee("outil refusé : configuration de profil périmée")
    departement = departements.get(profil["departement"])
    if departement is None:
        raise AdmissionRefusee("outil refusé : département du profil indisponible")
    prefixe = f"opsys_{departement.prefixe_outils}__"
    if not outil.startswith(prefixe):
        raise AdmissionRefusee("outil refusé : serveur hors du département du profil")
    nom_outil = outil[len(prefixe) :]
    if not nom_outil or nom_outil not in json.loads(profil["outils"]):
        raise AdmissionRefusee("outil refusé : capacité absente de la politique courante")
    return {"autorise": True, "revision_profil": profil["revision"]}


def verifier_outil_generique_runtime(
    cnx: Connection,
    agent_id: str,
    departements: Mapping[str, Departement],
    outil: str,
    revision_profil: int,
    *,
    verrouiller: bool = False,
) -> dict[str, Any]:
    """Ferme la réception générique du profil SMS, sans retirer son droit natif.

    Les RPC internes utilisent verifier_outil_runtime. Les deux entrées génériques
    revalident ici la sélection SQL courante, indépendamment du canal des arguments.
    """
    resultat = verifier_outil_runtime(
        cnx, agent_id, departements, outil, revision_profil, verrouiller=verrouiller
    )
    if outil != "opsys_m1__m1_recevoir_message_canal":
        return resultat
    from . import agents

    try:
        profil = agents.obtenir(cnx, agent_id)
        if profil is None:
            raise ValueError("profil absent")
        specification = {cle: profil[cle] for cle in (
            "id", "departement", "responsabilite", "palier_modele", "outils", "budget_jour", "budget_mois",
            "limite_tours", "limite_reessais", "limite_concurrence", "declencheurs",
        )}
        propre = agents._specification(departements, specification)
    except (ValueError, TypeError, KeyError) as exc:
        raise AdmissionRefusee("outil refusé : sélection du profil invalide") from exc
    if any(decl["type"] == "canal" for decl in propre["declencheurs"]):
        raise AdmissionRefusee("outil refusé : réception SMS réservée à l'hôte")
    return resultat


def _lire(cnx: Connection, reservation_id: str, *, verrou: bool = False) -> Mapping[str, Any]:
    requete = select(AGENTS_RESERVATIONS).where(AGENTS_RESERVATIONS.c.id == reservation_id)
    if verrou:
        requete = requete.with_for_update()
    ligne = cnx.execute(requete).mappings().fetchone()
    if ligne is None:
        raise KeyError("réservation inconnue")
    return ligne


def _concilier(cnx: Connection, reservation_id: str, tokens_reels: int, *, raison_historique: str) -> dict[str, Any]:
    if isinstance(tokens_reels, bool) or not isinstance(tokens_reels, int) or not 0 <= tokens_reels <= _MAX_I64:
        raise ValueError("tokens_reels doit être un entier entre 0 et 2^63-1")
    _verrouiller_politique(cnx)
    ligne = _lire(cnx, reservation_id, verrou=True)
    if ligne["statut"] == "conciliee":
        if ligne["tokens_reels"] == tokens_reels:
            return _reservation(ligne)
        raise ValueError("conflit d'idempotence de conciliation")
    if ligne["statut"] != "reservee":
        raise ValueError("une réservation libérée ne peut pas être conciliée")
    now = _maintenant().isoformat(timespec="seconds")
    jour_reel = now[:10]
    mois_reel = now[:7]
    insertion = inserer(cnx)(USAGE_TOKENS).values(
        jour=jour_reel,
        departement=ligne["departement"],
        modele=f"agent:{ligne['agent_id']}",
        appels=1,
        tokens_entree=tokens_reels,
        tokens_sortie=0,
        tokens_cache_lus=0,
    )
    point = cnx.begin_nested()
    try:
        ecriture_usage = cnx.execute(
            insertion.on_conflict_do_update(
                index_elements=[USAGE_TOKENS.c.jour, USAGE_TOKENS.c.departement, USAGE_TOKENS.c.modele],
                set_={
                    "appels": USAGE_TOKENS.c.appels + 1,
                    "tokens_entree": USAGE_TOKENS.c.tokens_entree + insertion.excluded.tokens_entree,
                },
                where=and_(
                    USAGE_TOKENS.c.appels < _MAX_I64,
                    USAGE_TOKENS.c.tokens_entree <= _MAX_I64 - insertion.excluded.tokens_entree,
                ),
            )
            .returning(USAGE_TOKENS.c.modele)
        )
        if ecriture_usage.first() is None:
            raise AdmissionRefusee("le compteur d'usage a atteint sa limite 64 bits")
        transition = cnx.execute(
            update(AGENTS_RESERVATIONS)
            .where(AGENTS_RESERVATIONS.c.id == reservation_id, AGENTS_RESERVATIONS.c.statut == "reservee")
            .values(statut="conciliee", tokens_reels=tokens_reels, jour=jour_reel, mois=mois_reel, modifie_le=now)
            .returning(AGENTS_RESERVATIONS.c.id)
        )
        if transition.first() is None:
            raise AdmissionRefusee("la réservation a changé pendant le rapprochement")
        raison = raison_historique
        if tokens_reels > ligne["tokens_plafond"]:
            raison += "; dépassement de l'enveloppe déclaré, futures admissions comptent le réel"
        _historiser(cnx, reservation_id, "conciliee", tokens_reels, raison)
        point.commit()
    except Exception:
        point.rollback()
        raise
    return _reservation(_lire(cnx, reservation_id))


def concilier(cnx: Connection, reservation_id: str, tokens_reels: int) -> dict[str, Any]:
    """Enregistre la déclaration d'usage reçue du chemin runtime après le retour du provider."""
    return _concilier(cnx, reservation_id, tokens_reels, raison_historique="usage provider enregistré")


def concilier_manuellement(
    cnx: Connection,
    reservation_id: str,
    agent_id: str,
    tokens_reels: int,
    *,
    par: str,
    reference_releve: str,
) -> dict[str, Any]:
    """Rapprochement déclaré par une personne; OPSYS ne vérifie pas le relevé externe."""
    ligne_personne = cnx.execute(
        select(PERSONNES.c.identifiant)
        .where(PERSONNES.c.identifiant == par, PERSONNES.c.actif.is_(True))
        .with_for_update()
    ).first()
    roles = set(
        cnx.execute(
            select(ROLES_PERSONNES.c.role)
            .where(
                ROLES_PERSONNES.c.identifiant == par,
                ROLES_PERSONNES.c.role.in_(("nathan_owner", "admin")),
            )
            .with_for_update()
        ).scalars()
    )
    if ligne_personne is None or not roles:
        raise PermissionError("rapprochement réservé au propriétaire ou à un administrateur actif")
    if not isinstance(reference_releve, str) or not _REFERENCE_RELEVE.fullmatch(reference_releve):
        raise ValueError("référence du relevé fournisseur invalide")
    if isinstance(tokens_reels, bool) or not isinstance(tokens_reels, int) or not 0 <= tokens_reels <= _MAX_I64:
        raise ValueError("le total déclaré doit être un entier entre 0 et 2^63-1")
    _verrouiller_politique(cnx)
    ligne = _lire(cnx, reservation_id, verrou=True)
    if ligne["agent_id"] != agent_id:
        raise AdmissionRefusee("réservation refusée : elle n'appartient pas à ce profil")
    if ligne["statut"] != "reservee":
        raise AdmissionRefusee("réservation refusée : elle n'est plus active; aucun nouvel ajustement manuel")
    raison = (
        f"déclaration humaine non vérifiée par OPSYS; relevé déclaré final; "
        f"appel déclaré terminé et ne pouvant plus générer de frais; déclarant={par}; "
        f"référence relevé fournisseur={reference_releve}"
    )
    return _concilier(cnx, reservation_id, tokens_reels, raison_historique=raison)


def liberer(cnx: Connection, reservation_id: str, *, raison: str) -> dict[str, Any]:
    """Libère une réservation qui n'a pas consommé de tokens et conserve la trace."""
    if not isinstance(raison, str) or not raison.strip() or len(raison) > 1000:
        raise ValueError("raison de libération requise (1000 caractères maximum)")
    _verrouiller_politique(cnx)
    ligne = _lire(cnx, reservation_id, verrou=True)
    if ligne["statut"] == "liberee":
        return _reservation(ligne)
    if ligne["statut"] != "reservee":
        raise ValueError("une réservation conciliée ne peut pas être libérée")
    now = _maintenant().isoformat(timespec="seconds")
    cnx.execute(
        update(AGENTS_RESERVATIONS)
        .where(AGENTS_RESERVATIONS.c.id == reservation_id, AGENTS_RESERVATIONS.c.statut == "reservee")
        .values(statut="liberee", modifie_le=now)
    )
    _historiser(cnx, reservation_id, "liberee", None, raison.strip())
    return _reservation(_lire(cnx, reservation_id))


def liberer_cycle_runtime_avant_dispatch(
    cnx: Connection,
    reservation_id: str,
    *,
    agent_id: str,
    execution_id: str,
    attempt_id: str,
    cycle_id: str,
    candidate_index: int,
    stream_ordinal: int,
    revision_profil: int,
) -> dict[str, Any]:
    """Canal hôte privé : le runtime garantit qu'il n'a jamais invoqué son provider.

    Le profil provient de la route authentifiée. Les champs doivent correspondre à la
    réservation et à sa capture historique initiale. Une perte de droits n'empêche pas
    ce cleanup sans consommation ; les anciennes captures sans preuve restent ouvertes.
    Cette fonction ne peut pas constater elle-même un dispatch chez un fournisseur.
    """
    for valeur, maximum in ((reservation_id, 128), (execution_id, 128), (attempt_id, 160), (cycle_id, 160)):
        if not isinstance(valeur, str) or not 8 <= len(valeur) <= maximum:
            raise ValueError("identifiant de capture runtime invalide")
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (candidate_index, stream_ordinal)):
        raise ValueError("indices de capture runtime invalides")
    if isinstance(revision_profil, bool) or not isinstance(revision_profil, int) or revision_profil < 1:
        raise ValueError("révision de capture runtime invalide")
    if attempt_id != f"{execution_id}:{candidate_index}" or cycle_id != f"{attempt_id}:{stream_ordinal}":
        raise AdmissionRefusee("capture runtime incohérente")
    _verrouiller_politique(cnx)
    ligne = _lire(cnx, reservation_id, verrou=True)
    capture = (agent_id, execution_id, attempt_id, cycle_id, candidate_index, stream_ordinal)
    attendue = tuple(ligne[cle] for cle in (
        "agent_id", "execution_id", "attempt_id", "cycle_id", "candidate_index", "stream_ordinal",
    ))
    if capture != attendue:
        raise AdmissionRefusee("libération refusée : capture différente de la réservation liée")
    preuves = cnx.execute(
        select(AGENTS_RESERVATIONS_HISTORIQUE.c.raison).where(
            AGENTS_RESERVATIONS_HISTORIQUE.c.reservation_id == reservation_id,
            AGENTS_RESERVATIONS_HISTORIQUE.c.evenement == "reservee",
        ).limit(2)
    ).scalars().all()
    if preuves != [_preuve_revision_runtime(revision_profil)]:
        raise AdmissionRefusee("libération refusée : preuve de capture runtime absente ou différente")
    return liberer(cnx, reservation_id, raison="hôte runtime : provider non invoqué avant dispatch (v1)")


def historique(cnx: Connection, reservation_id: str) -> list[dict[str, Any]]:
    return [
        dict(ligne)
        for ligne in cnx.execute(
            select(AGENTS_RESERVATIONS_HISTORIQUE)
            .where(AGENTS_RESERVATIONS_HISTORIQUE.c.reservation_id == reservation_id)
            .order_by(AGENTS_RESERVATIONS_HISTORIQUE.c.cree_le, AGENTS_RESERVATIONS_HISTORIQUE.c.id)
        ).mappings()
    ]


def lister_reservations_actives(
    cnx: Connection,
    agent_id: str,
    *,
    limite: int = 50,
) -> dict[str, Any]:
    """Lecture console bornée des enveloppes actives, sans détails libres ni action de reprise."""
    if not isinstance(agent_id, str) or not agent_id or len(agent_id) > 64:
        raise ValueError("profil invalide")
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= 50:
        raise ValueError("la limite doit être entre 1 et 50")
    ids_actifs_du_profil = select(AGENTS_RESERVATIONS.c.id).where(
        AGENTS_RESERVATIONS.c.agent_id == agent_id,
        AGENTS_RESERVATIONS.c.statut == "reservee",
    )
    historique_classe = (
        select(
            AGENTS_RESERVATIONS_HISTORIQUE.c.reservation_id.label("reservation_id"),
            AGENTS_RESERVATIONS_HISTORIQUE.c.evenement.label("evenement"),
            AGENTS_RESERVATIONS_HISTORIQUE.c.cree_le.label("cree_le"),
            func.row_number()
            .over(
                partition_by=AGENTS_RESERVATIONS_HISTORIQUE.c.reservation_id,
                order_by=(AGENTS_RESERVATIONS_HISTORIQUE.c.cree_le.desc(), AGENTS_RESERVATIONS_HISTORIQUE.c.id.desc()),
            )
            .label("rang"),
        )
        .where(AGENTS_RESERVATIONS_HISTORIQUE.c.reservation_id.in_(ids_actifs_du_profil))
        .subquery()
    )
    lignes = cnx.execute(
        select(
            AGENTS_RESERVATIONS.c.agent_id,
            AGENTS_RESERVATIONS.c.id.label("reservation_id"),
            AGENTS_RESERVATIONS.c.execution_id,
            AGENTS_RESERVATIONS.c.cycle_id,
            AGENTS_RESERVATIONS.c.tokens_plafond,
            AGENTS_RESERVATIONS.c.cree_le,
            func.count().over().label("total"),
            historique_classe.c.evenement.label("dernier_evenement"),
            historique_classe.c.cree_le.label("derniere_transition_le"),
        )
        .select_from(
            AGENTS_RESERVATIONS.outerjoin(
                historique_classe,
                and_(
                    AGENTS_RESERVATIONS.c.id == historique_classe.c.reservation_id,
                    historique_classe.c.rang == 1,
                ),
            )
        )
        .where(AGENTS_RESERVATIONS.c.agent_id == agent_id, AGENTS_RESERVATIONS.c.statut == "reservee")
        .order_by(AGENTS_RESERVATIONS.c.cree_le.desc(), AGENTS_RESERVATIONS.c.id.desc())
        .limit(limite)
    ).mappings().all()
    total = int(lignes[0]["total"]) if lignes else 0
    maintenant = dt.datetime.now(dt.UTC)
    sorties = []
    for ligne in lignes:
        age = None
        age_statut = "INCONNU_HORODATAGE_INVALIDE"
        try:
            cree_le = dt.datetime.fromisoformat(ligne["cree_le"])
            if cree_le.tzinfo is not None and cree_le.utcoffset() is not None:
                secondes = int((maintenant - cree_le.astimezone(dt.UTC)).total_seconds())
                if secondes >= 0:
                    age = secondes
                    age_statut = "CONNU"
                else:
                    age_statut = "INCONNU_DATE_FUTURE"
        except (OverflowError, TypeError, ValueError):
            pass
        sorties.append({
            "agent_id": ligne["agent_id"],
            "reservation_id": ligne["reservation_id"],
            "execution_id": ligne["execution_id"],
            "cycle_id": ligne["cycle_id"],
            "tokens_plafond": ligne["tokens_plafond"],
            "usage": "INCONNU",
            "age_secondes": age,
            "age_statut": age_statut,
            "dernier_evenement": ligne["dernier_evenement"] or "INCONNU",
            "derniere_transition_le": ligne["derniere_transition_le"],
        })
    return {"reservations": sorties, "total": total, "retournees": len(sorties), "omises": max(0, total - len(sorties))}
