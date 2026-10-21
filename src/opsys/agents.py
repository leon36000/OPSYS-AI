"""Registre versionné des profils d'agents configurables.

Ce module valide et persiste leur configuration déclarative; il ne lance pas d'agents.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, insert, select, update

from . import identite
from .departements import PALIERS, Departement
from .stockage.schema import (
    AGENTS_CONFIGURABLES,
    AGENTS_CONFIGURABLES_COMMANDES,
    AGENTS_CONFIGURABLES_HISTORIQUE,
)

_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_CLE_MUTATION = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_CRON = re.compile(r"^(\S+\s+){4}\S+$")
_COMPTE_SMS = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$", re.ASCII)
_SID_SMS = re.compile(r"^AC[0-9a-fA-F]{32}$", re.ASCII)
_CLES_CANAL_SMS = frozenset({"type", "version", "canal", "compte_id", "account_sid"})
_COMPTES_RESERVES = frozenset({"__proto__", "prototype", "constructor"})
_OUTIL_SMS = "m1_recevoir_message_canal"
_MAX_BUDGET_TOKENS = 10_000_000_000
_MAX_TOURS = 100
_MAX_REESSAIS = 10
_MAX_CONCURRENCE = 64


def _instant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _admin_actif(cnx: Connection, par: str) -> None:
    personne = identite.personne_active(cnx, par)
    if personne is None or not personne.roles.intersection({"nathan_owner", "admin"}):
        raise PermissionError("administration des profils réservée à une personne active admin ou propriétaire")


def _specification(departements: Mapping[str, Departement], spec: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, Mapping):
        raise ValueError("profil objet requis")
    cles = {
        "id", "departement", "responsabilite", "palier_modele", "outils", "budget_jour", "budget_mois",
        "limite_tours", "limite_reessais", "limite_concurrence", "declencheurs",
    }
    inconnues = sorted(set(spec) - cles)
    if inconnues:
        raise ValueError(f"champ(s) non pris en charge dans le profil : {inconnues}")
    ident = spec.get("id")
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise ValueError("id stable invalide")
    departement_id = spec.get("departement")
    departement = departements.get(departement_id) if isinstance(departement_id, str) else None
    if departement is None:
        raise ValueError("département inconnu")
    responsabilite = spec.get("responsabilite")
    if not isinstance(responsabilite, str) or not responsabilite.strip() or len(responsabilite) > 2000:
        raise ValueError("responsabilité requise (2000 caractères maximum)")
    palier = spec.get("palier_modele")
    if palier not in PALIERS:
        raise ValueError(f"palier_modele doit être un de {', '.join(PALIERS)}")
    outils = spec.get("outils")
    if not isinstance(outils, list) or not all(isinstance(x, str) for x in outils):
        raise ValueError("outils doit être une liste de noms")
    if len(set(outils)) != len(outils):
        raise ValueError("outils ne peut contenir de doublons")
    autorises = {outil.nom for outil in departement.charger_outils()}
    interdits = sorted(set(outils) - autorises)
    if interdits:
        raise ValueError(f"outil(s) hors du département {departement_id}: {interdits}")
    entiers: dict[str, int] = {}
    maxima = {
        "budget_jour": _MAX_BUDGET_TOKENS, "budget_mois": _MAX_BUDGET_TOKENS,
        "limite_tours": _MAX_TOURS, "limite_reessais": _MAX_REESSAIS,
        "limite_concurrence": _MAX_CONCURRENCE,
    }
    for cle, maximum in maxima.items():
        valeur = spec.get(cle)
        minimum = 0 if cle == "limite_reessais" else 1
        if isinstance(valeur, bool) or not isinstance(valeur, int) or not minimum <= valeur <= maximum:
            raise ValueError(f"{cle} doit être un entier entre {minimum} et {maximum}")
        entiers[cle] = valeur
    if entiers["budget_mois"] < entiers["budget_jour"]:
        raise ValueError("budget_mois doit être supérieur ou égal à budget_jour")
    declencheurs = spec.get("declencheurs")
    if not isinstance(declencheurs, list) or not declencheurs:
        raise ValueError("declencheurs doit être une liste non vide")
    propres: list[dict[str, Any]] = []
    for decl in declencheurs:
        if not isinstance(decl, Mapping):
            raise ValueError("chaque déclencheur doit être un objet")
        genre = decl.get("type")
        if genre == "manuel" and set(decl) == {"type"}:
            propre = {"type": "manuel"}
        elif genre == "cron" and set(decl) == {"type", "expression"}:
            expression = decl.get("expression")
            if not isinstance(expression, str) or not _CRON.fullmatch(expression):
                raise ValueError("expression cron invalide (5 champs requis)")
            propre = {"type": "cron", "expression": expression}
        elif genre == "evenement" and set(decl) == {"type", "nom"}:
            nom = decl.get("nom")
            if not isinstance(nom, str) or nom not in departement.evenements_consomme:
                raise ValueError(f"événement non consommé par {departement_id}")
            propre = {"type": "evenement", "nom": nom}
        elif genre == "canal" and set(decl) == _CLES_CANAL_SMS:
            version, compte, sid = decl.get("version"), decl.get("compte_id"), decl.get("account_sid")
            if type(version) is not int or version != 1 or decl.get("canal") != "sms":
                raise ValueError("déclencheur canal : version 1 et canal sms requis")
            if not isinstance(compte, str) or not _COMPTE_SMS.fullmatch(compte) or compte in _COMPTES_RESERVES:
                raise ValueError("déclencheur canal : compte_id invalide")
            if not isinstance(sid, str) or not _SID_SMS.fullmatch(sid):
                raise ValueError("déclencheur canal : account_sid invalide")
            if departement_id != "m01-front-office" or _OUTIL_SMS not in outils or len(declencheurs) != 1:
                raise ValueError("canal SMS : m01-front-office, outil m1_recevoir_message_canal et déclencheur unique")
            propre = {"type": "canal", "version": 1, "canal": "sms", "compte_id": compte, "account_sid": sid}
        else:
            raise ValueError("déclencheur invalide (manuel, cron ou événement consommé par le département)")
        propres.append(propre)
    if len({_json(x) for x in propres}) != len(propres):
        raise ValueError("déclencheurs en double")
    return {
        "id": ident, "departement": departement_id, "responsabilite": responsabilite.strip(),
        "palier_modele": palier, "outils": sorted(outils), **entiers, "declencheurs": propres,
    }


def _mutation_valide(mutation_id: str) -> None:
    if not isinstance(mutation_id, str) or not _CLE_MUTATION.fullmatch(mutation_id):
        raise ValueError("mutation_id invalide (8 à 128 caractères)")


def _json(donnees: Any) -> str:
    return json.dumps(donnees, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _compte_sms(declencheurs: list[dict[str, Any]]) -> str | None:
    for decl in declencheurs:
        if decl.get("type") == "canal" and decl.get("canal") == "sms":
            return decl["compte_id"]
    return None


def _unicite_sms(cnx: Connection, ident: str, declencheurs: list[dict[str, Any]]) -> None:
    compte = _compte_sms(declencheurs)
    if compte is None:
        return
    autres = cnx.execute(select(AGENTS_CONFIGURABLES.c.id, AGENTS_CONFIGURABLES.c.declencheurs).where(
        AGENTS_CONFIGURABLES.c.actif.is_(True), AGENTS_CONFIGURABLES.c.supprime.is_(False),
        AGENTS_CONFIGURABLES.c.id != ident,
    )).mappings()
    for autre in autres:
        if _compte_sms(json.loads(autre["declencheurs"])) == compte:
            raise ValueError(f"compte SMS déjà porté par le profil actif : {autre['id']}")


def _profil(ligne: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": ligne["id"], "departement": ligne["departement"], "responsabilite": ligne["responsabilite"],
        "palier_modele": ligne["palier_modele"], "outils": json.loads(ligne["outils"]),
        "budget_jour": ligne["budget_jour"], "budget_mois": ligne["budget_mois"],
        "limite_tours": ligne["limite_tours"], "limite_reessais": ligne["limite_reessais"],
        "limite_concurrence": ligne["limite_concurrence"], "declencheurs": json.loads(ligne["declencheurs"]),
        "actif": bool(ligne["actif"]), "supprime": bool(ligne["supprime"]),
        "revision": ligne["revision"], "cree_le": ligne["cree_le"], "modifie_le": ligne["modifie_le"],
        "modifie_par": ligne["modifie_par"],
    }


def _historiser(cnx: Connection, profil: Mapping[str, Any], par: str, mutation_id: str) -> None:
    cnx.execute(insert(AGENTS_CONFIGURABLES_HISTORIQUE).values(
        agent_id=profil["id"], revision=profil["revision"], instantane=_json(profil),
        modifie_le=profil["modifie_le"], modifie_par=par, mutation_id=mutation_id,
    ))


def _rejouer(cnx: Connection, mutation_id: str, empreinte: str) -> dict[str, Any] | None:
    ligne = cnx.execute(select(AGENTS_CONFIGURABLES_COMMANDES).where(
        AGENTS_CONFIGURABLES_COMMANDES.c.mutation_id == mutation_id
    )).mappings().fetchone()
    if ligne is None:
        return None
    if ligne["empreinte"] != empreinte:
        raise ValueError("mutation_id déjà utilisé pour une commande différente")
    return json.loads(ligne["reponse"])


def _memoriser_commande(cnx: Connection, profil: Mapping[str, Any], mutation_id: str, empreinte: str) -> None:
    cnx.execute(insert(AGENTS_CONFIGURABLES_COMMANDES).values(
        mutation_id=mutation_id, agent_id=profil["id"], empreinte=empreinte, reponse=_json(profil),
    ))


def creer(cnx: Connection, departements: Mapping[str, Departement], spec: Mapping[str, Any], *,
          par: str, mutation_id: str) -> dict[str, Any]:
    """Crée un profil désactivé et sa révision 1; l'acteur actif est revérifié en transaction."""
    _admin_actif(cnx, par)
    _mutation_valide(mutation_id)
    donnees = _specification(departements, spec)
    empreinte = hashlib.sha256(_json({"operation": "creer", "profil": donnees}).encode()).hexdigest()
    rejouee = _rejouer(cnx, mutation_id, empreinte)
    if rejouee is not None:
        return rejouee
    ancienne = cnx.execute(select(AGENTS_CONFIGURABLES).where(
        AGENTS_CONFIGURABLES.c.id == donnees["id"]
    ).with_for_update()).mappings().fetchone()
    if ancienne is not None:
        raise ValueError(f"profil déjà existant : {donnees['id']}")
    maintenant = _instant()
    valeurs = {
        **donnees, "outils": _json(donnees["outils"]), "declencheurs": _json(donnees["declencheurs"]),
        "actif": False, "supprime": False, "revision": 1, "cree_le": maintenant, "modifie_le": maintenant,
        "modifie_par": par, "mutation_id": mutation_id, "mutation_hash": empreinte,
    }
    cnx.execute(insert(AGENTS_CONFIGURABLES).values(**valeurs))
    profil = _profil(valeurs)
    _historiser(cnx, profil, par, mutation_id)
    _memoriser_commande(cnx, profil, mutation_id, empreinte)
    return profil


def obtenir(cnx: Connection, ident: str, *, inclure_supprime: bool = False) -> dict[str, Any] | None:
    ligne = cnx.execute(select(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == ident)).mappings().fetchone()
    if ligne is None or (ligne["supprime"] and not inclure_supprime):
        return None
    return _profil(ligne)


def lister(cnx: Connection, *, departement: str | None = None, inclure_inactifs: bool = False,
           inclure_supprimes: bool = False) -> list[dict[str, Any]]:
    requete = select(AGENTS_CONFIGURABLES)
    if departement is not None:
        requete = requete.where(AGENTS_CONFIGURABLES.c.departement == departement)
    if not inclure_inactifs:
        requete = requete.where(AGENTS_CONFIGURABLES.c.actif.is_(True))
    if not inclure_supprimes:
        requete = requete.where(AGENTS_CONFIGURABLES.c.supprime.is_(False))
    return [_profil(ligne) for ligne in cnx.execute(requete.order_by(AGENTS_CONFIGURABLES.c.id)).mappings()]


def historique(cnx: Connection, ident: str) -> list[dict[str, Any]]:
    return [json.loads(ligne[0]) for ligne in cnx.execute(
        select(AGENTS_CONFIGURABLES_HISTORIQUE.c.instantane)
        .where(AGENTS_CONFIGURABLES_HISTORIQUE.c.agent_id == ident)
        .order_by(AGENTS_CONFIGURABLES_HISTORIQUE.c.revision)
    )]


def _modifier(cnx: Connection, ident: str, departements: Mapping[str, Departement], *, par: str,
              mutation_id: str, revision_attendue: int, spec: Mapping[str, Any] | None,
              actif: bool | None = None, supprime: bool | None = None) -> dict[str, Any]:
    _admin_actif(cnx, par)
    _mutation_valide(mutation_id)
    if isinstance(revision_attendue, bool) or not isinstance(revision_attendue, int) or revision_attendue <= 0:
        raise ValueError("revision_attendue doit être un entier positif")
    empreinte_requete = hashlib.sha256(_json({
        "operation": "modifier" if spec is not None else "definir_actif" if actif is not None else "supprimer",
        "id": ident,
        "revision_attendue": revision_attendue,
        "spec": spec,
        "actif": actif,
        "supprime": supprime,
    }).encode()).hexdigest()
    rejouee = _rejouer(cnx, mutation_id, empreinte_requete)
    if rejouee is not None:
        return rejouee
    ligne = cnx.execute(select(AGENTS_CONFIGURABLES).where(
        AGENTS_CONFIGURABLES.c.id == ident
    ).with_for_update()).mappings().fetchone()
    if ligne is None:
        raise KeyError(f"profil inconnu : {ident}")
    actuel = _profil(ligne)
    donnees = {k: actuel[k] for k in (
        "id", "departement", "responsabilite", "palier_modele", "outils", "budget_jour", "budget_mois",
        "limite_tours", "limite_reessais", "limite_concurrence", "declencheurs",
    )}
    if spec is not None:
        donnees.update(spec)
    valide = _specification(departements, donnees)
    if actif is not None:
        if not isinstance(actif, bool):
            raise ValueError("actif doit être booléen")
        if actuel["supprime"] and actif:
            raise ValueError("un profil supprimé logiquement ne peut pas être réactivé")
    if supprime is not None and not isinstance(supprime, bool):
        raise ValueError("supprime doit être booléen")
    payload = {**valide, "actif": actuel["actif"] if actif is None else actif,
               "supprime": actuel["supprime"] if supprime is None else supprime}
    empreinte = empreinte_requete
    if ligne["revision"] != revision_attendue:
        raise ValueError(f"conflit de révision : attendue {revision_attendue}, courante {ligne['revision']}")
    if payload["actif"] and not payload["supprime"]:
        _unicite_sms(cnx, ident, valide["declencheurs"])
    maintenant = _instant()
    revision = ligne["revision"] + 1
    valeurs = {
        **valide, "outils": _json(valide["outils"]), "declencheurs": _json(valide["declencheurs"]),
        "actif": payload["actif"], "supprime": payload["supprime"], "revision": revision,
        "modifie_le": maintenant, "modifie_par": par, "mutation_id": mutation_id, "mutation_hash": empreinte,
    }
    resultat = cnx.execute(update(AGENTS_CONFIGURABLES).where(
        AGENTS_CONFIGURABLES.c.id == ident, AGENTS_CONFIGURABLES.c.revision == revision_attendue
    ).values(**valeurs))
    if resultat.rowcount != 1:
        raise ValueError("conflit de révision")
    profil = {**payload, "revision": revision, "cree_le": ligne["cree_le"],
              "modifie_le": maintenant, "modifie_par": par}
    _historiser(cnx, profil, par, mutation_id)
    _memoriser_commande(cnx, profil, mutation_id, empreinte)
    return profil


def modifier(cnx: Connection, ident: str, departements: Mapping[str, Departement], spec: Mapping[str, Any], *,
             par: str, mutation_id: str, revision_attendue: int) -> dict[str, Any]:
    """Remplace la déclaration sans changer l'identifiant stable."""
    if spec.get("id") != ident:
        raise ValueError("l'id stable du profil ne peut pas être modifié")
    return _modifier(cnx, ident, departements, par=par, mutation_id=mutation_id,
                     revision_attendue=revision_attendue, spec=spec)


def definir_actif(cnx: Connection, ident: str, departements: Mapping[str, Departement], actif: bool, *,
                  par: str, mutation_id: str, revision_attendue: int) -> dict[str, Any]:
    return _modifier(cnx, ident, departements, par=par, mutation_id=mutation_id,
                     revision_attendue=revision_attendue, spec=None, actif=actif)


def supprimer(cnx: Connection, ident: str, departements: Mapping[str, Departement], *, par: str,
              mutation_id: str, revision_attendue: int) -> dict[str, Any]:
    """Suppression logique et désactivation; l'historique reste durable."""
    return _modifier(cnx, ident, departements, par=par, mutation_id=mutation_id,
                     revision_attendue=revision_attendue, spec=None, actif=False, supprime=True)
