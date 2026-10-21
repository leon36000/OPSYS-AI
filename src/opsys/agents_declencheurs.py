"""Intentions humaines et projection cron native ; aucun transport ni génération exécuté.

Cette phase SQLite conserve l'état de remise, sans dupliquer le canon de profils. Ses fonctions
gèrent leur transaction canonique ; une projection n'est ni une remise ni une exécution Core.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import LargeBinary, cast, func, insert, select, update
from sqlalchemy.engine import make_url

from . import admission_agents, agents, identite, stockage
from .agent_cfo_grants import instance_id
from .departements import Departement
from .etat import journaliser
from .memoire import autorite
from .outils import Autonomie, Niveau
from .stockage.schema import AGENTS_CONFIGURABLES as PROFILS
from .stockage.schema import AGENTS_DECLENCHEURS_COMMANDES as COMMANDES
from .stockage.schema import AGENTS_DECLENCHEURS_INTENTIONS as INTENTIONS

MAX_DECLARATIONS = 16
MAX_ATTENTE = 100
MAX_LECTURE = 10
_ID = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_MUTATION = re.compile(r"[A-Za-z0-9._:-]{8,128}\Z")
_SPEC = ("id", "departement", "responsabilite", "palier_modele", "outils", "budget_jour", "budget_mois",
         "limite_tours", "limite_reessais", "limite_concurrence", "declencheurs")


class DeclencheurRefuse(ValueError):
    """Diagnostic fermé, sans contenu privé du profil ou configuration du contrôleur."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _decoder(texte: str, maximum: int = 32768) -> Any:
    if not isinstance(texte, str) or len(texte.encode("utf-8")) > maximum:
        raise DeclencheurRefuse("CRON-DONNEES-EXCESSIVES")
    try:
        def constante(_valeur):
            raise ValueError("nombre non fini")

        def objet(paires):
            resultat = {}
            for cle, valeur in paires:
                if cle in resultat:
                    raise ValueError("clé dupliquée")
                resultat[cle] = valeur
            return resultat

        value = json.loads(texte, parse_constant=constante, object_pairs_hook=objet)
        pile = [(value, 0)]
        nombre = 0
        while pile:
            item, profondeur = pile.pop()
            nombre += 1
            if nombre > 512 or profondeur > 8 or isinstance(item, float) and not math.isfinite(item):
                raise ValueError("structure excessive")
            if isinstance(item, dict):
                pile.extend((x, profondeur + 1) for x in item.values())
            elif isinstance(item, list):
                pile.extend((x, profondeur + 1) for x in item)
        return value
    except (ValueError, TypeError, RecursionError) as exc:
        raise DeclencheurRefuse("CRON-DONNEES-INVALIDES") from exc


@contextmanager
def _transaction():
    if make_url(stockage.url_base()).get_backend_name() != "sqlite":
        raise DeclencheurRefuse("CRON-SQLITE-REQUIS")
    # stockage.moteur pose BEGIN IMMEDIATE avant toute lecture/écriture, y compris l'autorité.
    with stockage.transaction() as cnx:
        if cnx.dialect.name != "sqlite":
            raise DeclencheurRefuse("CRON-SQLITE-REQUIS")
        yield cnx


def _acteur(cnx, par: str) -> str:
    personne = identite.personne_active(cnx, par)
    if personne is None or not personne.roles.intersection({"admin", "nathan_owner"}):
        raise PermissionError("administration active requise pour les déclencheurs")
    return "nathan_owner" if "nathan_owner" in personne.roles else "admin"


def _arguments(ident: str, revision: int, mutation: str) -> None:
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise DeclencheurRefuse("CRON-PROFIL-INVALIDE")
    if type(revision) is not int or not 1 <= revision <= 2**53 - 1:
        raise DeclencheurRefuse("CRON-REVISION-INVALIDE")
    if not isinstance(mutation, str) or not _MUTATION.fullmatch(mutation):
        raise DeclencheurRefuse("CRON-MUTATION-INVALIDE")


def _fuseau(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise DeclencheurRefuse("CRON-FUSEAU-INVALIDE")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DeclencheurRefuse("CRON-FUSEAU-INVALIDE") from exc


def _cron(expression: str) -> None:
    # Sous-ensemble numérique explicite : le validateur natif reste l'oracle lors de la remise.
    if not isinstance(expression, str) or len(expression.encode("utf-8")) > 128:
        raise DeclencheurRefuse("CRON-EXPRESSION-INVALIDE")
    champs = expression.split()
    if len(champs) != 5 or not all(re.fullmatch(r"[0-9*,/-]+", c) for c in champs):
        raise DeclencheurRefuse("CRON-EXPRESSION-INVALIDE")
    for champ, (minimum, maximum) in zip(champs, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7)), strict=True):
        for membre in champ.split(","):
            parties = membre.split("/")
            if len(parties) > 2 or len(parties) == 2 and (not parties[1].isdigit() or int(parties[1]) < 1):
                raise DeclencheurRefuse("CRON-EXPRESSION-INVALIDE")
            base = parties[0]
            if base == "*":
                continue
            valeurs = base.split("-")
            if len(valeurs) not in (1, 2) or not all(v.isdigit() and minimum <= int(v) <= maximum for v in valeurs):
                raise DeclencheurRefuse("CRON-EXPRESSION-INVALIDE")
            if len(valeurs) == 2 and int(valeurs[0]) > int(valeurs[1]):
                raise DeclencheurRefuse("CRON-EXPRESSION-INVALIDE")


def _profil(cnx, deps: Mapping[str, Departement], ident: str, revision: int, *, actif=True):
    # Ne pas matérialiser le JSON libre avant la borne SQL en octets.
    tailles = cnx.execute(select(*[
        func.length(cast(PROFILS.c[key], LargeBinary)) for key in ("responsabilite", "outils", "declencheurs")
    ]).where(PROFILS.c.id == ident)).first()
    if tailles is None or any(type(n) is not int or n > cap
                              for n, cap in zip(tailles, (8192, 32768, 32768), strict=True)):
        raise DeclencheurRefuse("CRON-PROFIL-INDISPONIBLE")
    row = cnx.execute(select(PROFILS).where(PROFILS.c.id == ident)).mappings().one()
    if row["revision"] != revision:
        raise DeclencheurRefuse("CRON-REVISION-PERIMEE")
    if actif and (not row["actif"] or row["supprime"]):
        raise DeclencheurRefuse("CRON-PROFIL-INACTIF")
    spec = {k: _decoder(row[k]) if k in {"outils", "declencheurs"} else row[k] for k in _SPEC}
    try:
        propre = agents._specification(deps, spec)
    except (ValueError, TypeError) as exc:
        raise DeclencheurRefuse("CRON-PROFIL-INVALIDE") from exc
    if len(propre["declencheurs"]) > MAX_DECLARATIONS:
        raise DeclencheurRefuse("CRON-TROP-DE-DECLENCHEURS")
    return {**propre, "revision": revision, "actif": bool(row["actif"]), "supprime": bool(row["supprime"])}


def _memoire(profil):
    try:
        politique = autorite.lire_politique()
    except ValueError as exc:
        raise DeclencheurRefuse("CRON-CLASSIFICATION-MEMOIRE-INDISPONIBLE") from exc
    attendu = {"departement": profil["departement"], "mode": "global"}
    if politique["agents"].get("opsys-agent-" + profil["id"]) != attendu:
        raise DeclencheurRefuse("CRON-CONTEXTE-MEMOIRE-REQUIS")
    # Les ajouts sans rapport à d'autres profils ne révoquent pas cette intention.
    return _hash({"version": politique["version"], "agent": "opsys-agent-" + profil["id"], "binding": attendu})


def _outils(cnx, deps, profil):
    dep = deps[profil["departement"]]
    catalogue = {o.nom: o for o in dep.charger_outils()}
    noms = []
    for nom in profil["outils"]:
        outil = catalogue[nom]
        if outil.autonomie not in {Autonomie.T0, Autonomie.T1} or outil.niveau_effectif not in {
            Niveau.N0, Niveau.N1, Niveau.N2,
        }:
            raise DeclencheurRefuse("CRON-OUTIL-FRONTIERE-HUMAINE")
        natif = f"opsys_{dep.prefixe_outils}__{nom}"
        admission_agents.verifier_outil_runtime(cnx, profil["id"], deps, natif, profil["revision"], verrouiller=True)
        noms.append(natif)
    return noms


def _rejouer(cnx, par, mutation, empreinte):
    row = cnx.execute(select(COMMANDES.c.empreinte, COMMANDES.c.reponse).where(
        COMMANDES.c.acteur == par, COMMANDES.c.mutation_id == mutation,
    )).first()
    if row is None:
        return None
    if row.empreinte != empreinte:
        raise DeclencheurRefuse("CRON-IDEMPOTENCE-CONFLIT")
    return _decoder(row.reponse, 8192)


def _memoriser(cnx, par, mutation, empreinte, reponse, instant):
    cnx.execute(insert(COMMANDES).values(
        acteur=par, mutation_id=mutation, empreinte=empreinte, reponse=_json(reponse), cree_le=instant,
    ))


def _valider_mandat(cnx, deps, row):
    """Source canonique commune ; relit le mandant sans lui attribuer l'appel de service."""
    _identite_intention(row)
    _acteur(cnx, row["demande_par"])
    if row["statut"] != "a_declarer" or instance_id(cnx) != row["instance_id"]:
        raise DeclencheurRefuse("CRON-INTENTION-PERIMEE")
    profil = _profil(cnx, deps, row["agent_id"], row["profile_revision"])
    if _hash(profil) != row["profile_hash"] or _memoire(profil) != row["memory_policy_hash"]:
        raise DeclencheurRefuse("CRON-SOURCE-MODIFIEE")
    decls = [d for d in profil["declencheurs"] if d["type"] == "cron" and _hash(d) == row["trigger_hash"]]
    if len(decls) != 1:
        raise DeclencheurRefuse("CRON-DECLENCHEUR-PERIME")
    _cron(decls[0]["expression"])
    _fuseau(row["fuseau"])
    outils = _outils(cnx, deps, profil)
    _acteur(cnx, row["demande_par"])
    return profil, decls[0], outils


def _revalider(cnx, deps, row, par):
    _acteur(cnx, par)
    result = _valider_mandat(cnx, deps, row)
    _acteur(cnx, par)
    return result


def _identite_intention(row):
    ident = _hash({"instance": row["instance_id"], "profil": row["agent_id"],
                   "revision": row["profile_revision"], "cron": row["trigger_hash"], "fuseau": row["fuseau"]})
    if row["id"] != ident or row["declaration_key"] != "opsys-profile:" + ident:
        raise DeclencheurRefuse("CRON-INTENTION-ALTEREE")


def demander(deps, profil_id: str, *, par: str, revision_attendue: int, fuseau: str, mutation_id: str):
    """Crée des intentions, aucune remise. Rejeu exact revalidé, pas de réarmement implicite."""
    _arguments(profil_id, revision_attendue, mutation_id)
    _fuseau(fuseau)
    with _transaction() as cnx:
        role = _acteur(cnx, par)
        profil = _profil(cnx, deps, profil_id, revision_attendue)
        memoire_hash = _memoire(profil)
        _outils(cnx, deps, profil)
        decls = [d for d in profil["declencheurs"] if d["type"] == "cron"]
        if not decls:
            raise DeclencheurRefuse("CRON-DECLENCHEUR-ABSENT")
        for decl in decls:
            _cron(decl["expression"])
        empreinte = _hash({"operation": "demander", "profil": profil_id,
                           "revision": revision_attendue, "fuseau": fuseau})
        replay = _rejouer(cnx, par, mutation_id, empreinte)
        if replay is not None:
            for ident in replay["intentions"]:
                row = cnx.execute(select(INTENTIONS).where(INTENTIONS.c.id == ident)).mappings().one()
                _revalider(cnx, deps, row, par)
            return replay
        inst = instance_id(cnx)
        instant = dt.datetime.now(dt.UTC).isoformat()
        nouveaux = []
        ids = []
        for decl in decls:
            thash = _hash(decl)
            ident = _hash({"instance": inst, "profil": profil_id, "revision": revision_attendue,
                           "cron": thash, "fuseau": fuseau})
            ids.append(ident)
            ancienne = cnx.execute(select(INTENTIONS).where(INTENTIONS.c.id == ident)).mappings().first()
            if ancienne:
                _revalider(cnx, deps, ancienne, par)
            else:
                nouveaux.append({"id": ident, "instance_id": inst, "agent_id": profil_id,
                    "profile_revision": revision_attendue, "profile_hash": _hash(profil), "trigger_hash": thash,
                    "memory_policy_hash": memoire_hash, "fuseau": fuseau, "declaration_key": "opsys-profile:" + ident,
                    "statut": "a_declarer", "demande_par": par, "demande_role": role,
                    "cree_le": instant, "modifie_le": instant})
        autres = (INTENTIONS.c.statut == "a_declarer", INTENTIONS.c.agent_id != profil_id)
        actifs = cnx.scalar(select(func.count()).select_from(INTENTIONS).where(*autres))
        attente = cnx.scalar(select(func.count()).select_from(INTENTIONS).where(INTENTIONS.c.statut != "retiree"))
        if actifs + len(ids) > MAX_DECLARATIONS or attente + len(nouveaux) > MAX_ATTENTE:
            raise DeclencheurRefuse("CRON-FILE-SATUREE")
        _acteur(cnx, par)
        if _hash(_profil(cnx, deps, profil_id, revision_attendue)) != _hash(profil) or _memoire(profil) != memoire_hash:
            raise DeclencheurRefuse("CRON-SOURCE-MODIFIEE")
        cnx.execute(update(INTENTIONS).where(
            INTENTIONS.c.agent_id == profil_id, INTENTIONS.c.statut == "a_declarer", INTENTIONS.c.id.not_in(ids),
        ).values(statut="a_retirer", retrait_par=par, modifie_le=instant))
        if nouveaux:
            cnx.execute(insert(INTENTIONS), nouveaux)
        reponse = {"profil": profil_id, "revision": revision_attendue, "intentions": ids, "execute": False}
        _memoriser(cnx, par, mutation_id, empreinte, reponse, instant)
        journaliser(cnx, par, "agents.cron.demande", profil_id, {"revision": revision_attendue,
                    "intentions": ids, "fuseau": fuseau})
        for ident in ids:
            row = cnx.execute(select(INTENTIONS).where(INTENTIONS.c.id == ident)).mappings().one()
            _identite_intention(row)
            _revalider(cnx, deps, row, par)
        return reponse


def retirer(deps, profil_id: str, *, par: str, revision_attendue: int, mutation_id: str):
    """Demande le retrait, y compris d'un profil désactivé ; n'affirme pas le retrait Core."""
    _arguments(profil_id, revision_attendue, mutation_id)
    with _transaction() as cnx:
        _acteur(cnx, par)
        _profil(cnx, deps, profil_id, revision_attendue, actif=False)
        empreinte = _hash({"operation": "retirer", "profil": profil_id, "revision": revision_attendue})
        replay = _rejouer(cnx, par, mutation_id, empreinte)
        if replay is not None:
            _acteur(cnx, par)
            return replay
        instant = dt.datetime.now(dt.UTC).isoformat()
        ids = list(cnx.scalars(select(INTENTIONS.c.id).where(
            INTENTIONS.c.agent_id == profil_id, INTENTIONS.c.statut != "retiree",
        ).order_by(INTENTIONS.c.id).limit(MAX_ATTENTE + 1)))
        if len(ids) > MAX_ATTENTE:
            raise DeclencheurRefuse("CRON-FILE-SATUREE")
        _acteur(cnx, par)
        cnx.execute(update(INTENTIONS).where(INTENTIONS.c.id.in_(ids)).values(
            statut="a_retirer", retrait_par=par, modifie_le=instant,
        ))
        reponse = {"profil": profil_id, "revision": revision_attendue, "intentions": ids, "execute": False}
        _memoriser(cnx, par, mutation_id, empreinte, reponse, instant)
        journaliser(cnx, par, "agents.cron.retrait_demande", profil_id, {"intentions": ids})
        _profil(cnx, deps, profil_id, revision_attendue, actif=False)
        _acteur(cnx, par)
        return reponse


def _declaration(row, profil, decl, outils):
    message = f"Exécute le mandat interne canonique du profil {profil['id']}, révision {profil['revision']}."
    params = {
        "name": "OPSYS profil " + profil["id"], "declarationKey": row["declaration_key"],
        "agentId": "opsys-agent-" + profil["id"], "sessionTarget": "isolated", "wakeMode": "now",
        "schedule": {"kind": "cron", "expr": decl["expression"], "tz": row["fuseau"]},
        "payload": {"kind": "agentTurn", "message": message, "timeoutSeconds": 120, "toolsAllow": outils},
        "delivery": {"mode": "none"},
    }
    argv = ["opsys", "automations", "add", "--name", params["name"], "--declaration-key", row["declaration_key"],
            "--agent", params["agentId"], "--session", "isolated", "--cron", decl["expression"],
            "--tz", row["fuseau"], "--message", message, "--tools", ",".join(outils),
            "--timeout-seconds", "120", "--no-deliver"]
    return {"native": {"method": "cron.add", "params": params}, "argv": argv}


def projeter(deps, intention_id: str, *, par: str):
    """Plan privé ; aucun CLI appelé et aucun état marqué transmis ou exécuté."""
    if not isinstance(intention_id, str) or not re.fullmatch(r"[0-9a-f]{64}", intention_id):
        raise DeclencheurRefuse("CRON-INTENTION-INVALIDE")
    with _transaction() as cnx:
        _acteur(cnx, par)
        row = cnx.execute(select(INTENTIONS).where(INTENTIONS.c.id == intention_id)).mappings().first()
        if row is None or instance_id(cnx) != row["instance_id"]:
            raise DeclencheurRefuse("CRON-INTENTION-ABSENTE")
        _identite_intention(row)
        if row["statut"] == "a_retirer":
            _acteur(cnx, par)
            return {"intention": intention_id, "etat": "a_retirer", "execute": False,
                    "declaration_key": row["declaration_key"],
                    "reconciliation": "rechercher_id_natif_puis_retirer", "native": None, "argv": None}
        profil, decl, outils = _revalider(cnx, deps, row, par)
        result = {"intention": intention_id, "etat": row["statut"], "execute": False,
                  **_declaration(row, profil, decl, outils)}
        _revalider(cnx, deps, row, par)  # Après construction du plan, avant le retour.
        if len(_json(result).encode("utf-8")) > 16384:
            raise DeclencheurRefuse("CRON-PROJECTION-EXCESSIVE")
        return result


def lire_en_attente(*, par: str, limite: int = MAX_LECTURE):
    """État de remise expurgé borné ; aucune projection ou validation d'exécution inventée."""
    if type(limite) is not int or not 1 <= limite <= MAX_LECTURE:
        raise DeclencheurRefuse("CRON-LIMITE-INVALIDE")
    with _transaction() as cnx:
        _acteur(cnx, par)
        total = cnx.scalar(select(func.count()).select_from(INTENTIONS).where(INTENTIONS.c.statut != "retiree"))
        rows = cnx.execute(select(INTENTIONS.c.id, INTENTIONS.c.agent_id, INTENTIONS.c.profile_revision,
                                 INTENTIONS.c.statut, INTENTIONS.c.fuseau).where(
            INTENTIONS.c.statut != "retiree",
        ).order_by(INTENTIONS.c.cree_le, INTENTIONS.c.id).limit(limite)).mappings()
        items = [dict(r) for r in rows]
        _acteur(cnx, par)
        return {"total": total, "retournes": len(items), "omis": total - len(items),
                "items": items, "execution_core": "non_observee"}
