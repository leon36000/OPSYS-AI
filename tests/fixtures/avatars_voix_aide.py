"""Aides des tests « voix et visages des avatars » : scénario fictif complet (profil, fournisseurs, entrées).

Aucun appel réseau : les moteurs sont des fournisseurs FICTIFS dont le point d'accès est `module:json` (le module
standard `json` : la sonde locale RÉELLE du serveur vérifie sa présence, sans réseau). Toute donnée est fictive.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

from opsys import avatars, identite
from opsys.avatars_voix import registre
from opsys.departements import charger_departements
from opsys.fournisseurs import registre as fournisseurs

FICTIF = True
MOT_DE_PASSE = "mot-de-passe-avatars-fictif-2026"
ADMIN = "admin_fictif"
LICENCE_LIBRE = {"code": "MIT", "poids": "MIT", "usage_commercial": "autorise", "service_tiers": "autorise",
                 "integration": "bibliotheque", "verification": "verifiee", "source": "test fictif"}
TTS = "tts.fictif-local"
AVATAR = "avatar.fictif-local"
STT = "stt.fictif-local"
DEPARTEMENT = "m01-front-office"
SHA = hashlib.sha256(b"contrat fictif signe").hexdigest()
TOUS_LES_CANAUX = frozenset(avatars.CANAUX_AVATAR)


def declaration(capacite: str, *, licence: dict[str, Any] | None = None, point_acces: str | None = "module:json",
                modele: str = "Moteur fictif", mode: str = "local", **extra: Any) -> dict[str, Any]:
    return {"capacite": capacite, "mode": mode, "modele": modele, "licence": {**LICENCE_LIBRE, **(licence or {})},
            "point_acces": point_acces, **extra}


def creer_personnes(session) -> None:
    with session() as cnx:
        comptes = ((ADMIN, "Admin fictif", "admin"), ("vendeur_fictif", "Vendeur fictif", "seller"))
        for identifiant, nom, role in comptes:
            if identite.personne(cnx, identifiant) is None:
                identite.creer_personne(cnx, identifiant, nom, MOT_DE_PASSE, [role])


def profil(session, revision: int = 0, **valeurs: Any) -> dict[str, Any]:
    base = {"usage_commercial": True, "revenu_annuel_usd": 400_000, "territoires": ["CA"], "heberge_pour_tiers": False}
    with session() as cnx:
        return fournisseurs.declarer_profil(cnx, acteur=ADMIN, revision_attendue=revision, **{**base, **valeurs})


def fournisseur(session, identifiant: str, capacite: str, *, activer: bool = True, **options: Any) -> None:
    with session() as cnx:
        fournisseurs.configurer(cnx, acteur=ADMIN, identifiant=identifiant,
                                declaration=declaration(capacite, **options), revision_attendue=0)
        if activer:
            decision = fournisseurs.activer(cnx, acteur=ADMIN, identifiant=identifiant)
            assert decision.conforme, decision.codes


def identite_m01():
    deps = charger_departements()
    return avatars.resoudre_identites(deps)[DEPARTEMENT]


def changer_profil(session, **valeurs: Any) -> dict[str, Any]:
    with session() as cnx:
        courant = fournisseurs.profil_brut(cnx)
    base = {k: courant[k] for k in ("usage_commercial", "revenu_annuel_usd", "territoires", "heberge_pour_tiers")}
    return profil(session, revision=courant["revision"], **{**base, **valeurs})


def monter(session, *, qualifier_tout: bool = True, tts_licence: dict[str, Any] | None = None,
           revenu: int = 400_000) -> SimpleNamespace:
    """Instance avec profil de licence, trois moteurs fictifs actifs (STT sélectionné pour M1), les entrées voix et
    visage de Léa liées, et (par défaut) leurs trois moteurs qualifiés par la sonde locale réelle."""
    creer_personnes(session)
    profil(session, revenu_annuel_usd=revenu)
    fournisseur(session, TTS, "tts", licence=tts_licence)
    fournisseur(session, AVATAR, "avatar")
    fournisseur(session, STT, "stt")
    identites = identite_m01()
    with session() as cnx:
        fournisseurs.selectionner(cnx, acteur=ADMIN, capacite="stt", identifiant=STT, departement=DEPARTEMENT)
        registre.inscrire_entree(cnx, acteur=ADMIN, identifiant=identites.voix, accent="quebecois")
        registre.inscrire_entree(cnx, acteur=ADMIN, identifiant=identites.visage, actif_usage_commercial="autorise")
        registre.lier_runtime(cnx, acteur=ADMIN, identifiant=identites.voix, fournisseur_id=TTS)
        registre.lier_runtime(cnx, acteur=ADMIN, identifiant=identites.visage, fournisseur_id=AVATAR)
    if qualifier_tout:
        for ident in (TTS, AVATAR, STT):
            resultat = registre.qualifier(session, acteur=ADMIN, fournisseur_id=ident)
            assert resultat["qualifiante"], resultat
    return SimpleNamespace(identite=identites, voix=identites.voix, visage=identites.visage)
