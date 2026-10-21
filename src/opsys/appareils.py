"""Appairage d'appareil (ADR-0009 §5 : table `appareils` appairés à une personne ; T1.4-c2).

Un appareil (téléphone employé/vendeur/admin, R12 §1.3/§6/§9) porte, une fois l'appairage approuvé
par le propriétaire, un rôle nommé OPSYS parmi le sous-ensemble `ROLES_APPAREIL` — jamais le rôle
générique d'opérateur d'OpenClaw, dont la documentation amont prévient explicitement qu'il donne un
accès complet (R12 §6 : « le secret partagé donne un accès complet »). Ce rôle est celui
qu'OPSYS-CORE (`/tools/invoke`) transmet au socle en `_meta` MCP (`opsys/personne`, `opsys/role` ;
`docs/architecture/IDEMPOTENCE.md` §7 bis) et celui que `opsys.openclaw.ecrire_appareils` projette
en configuration lue par le core, jamais écrite à la main dans le core.

`ROLES_APPAREIL` est EXACTEMENT le type `Profil` fermé du client mobile
(`mobile/src/roles/types.ts`, lu, jamais modifié ici), moins `client` (lien tokenisé, jamais un
appareil apparié durablement, R12 §6) : un jeton d'appareil ne peut jamais porter `nathan_owner`,
même pour l'appareil du propriétaire, car la garde de routes du mobile (`evaluerGarde`) refuse
fermé tout rôle hors de ce type — un rôle inconnu y équivaut à une session absente. **L'appareil du
propriétaire est donc appairé avec `role="admin"`** (les mêmes routes que n'importe quel admin) ;
sa portée d'outils supplémentaire (N5, ADR-0009 §5) ne passe jamais par le rôle du jeton mais par
la PERSONNE elle-même (`opsys/personne`), dont `opsys.identite`/`opsys.approbations` savent déjà
lire les rôles réels (`personnes`/`roles`) indépendamment de tout appareil — exactement comme
`approbations.decider` le fait déjà aujourd'hui pour une décision prise depuis la console.

Ni la liste des outils permis par rôle (`opsys.openclaw.roles_outils`), ni l'application du refus
hors portée (OPSYS-CORE, `/tools/invoke`), ne vivent ici : ce module appaire seulement un appareil
à une personne et à un rôle, et sert de source à la projection de configuration.

`appairer` exige que la PERSONNE porte déjà elle-même le rôle attribué à l'appareil : un appairage
ne peut jamais donner à un appareil plus de portée que sa personne n'en a — sinon l'appairage
deviendrait lui-même un moyen d'élévation de privilège. C'est un appel de console/CLI signé par le
propriétaire (approbation en deux temps, R12 §1.3) ; l'appareil ne s'auto-appaire jamais.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any

from sqlalchemy import Connection, delete, select

from . import identite
from .stockage.moteur import inserer
from .stockage.schema import APPAREILS

# Rôles qu'un jeton d'appareil peut porter : EXACTEMENT le type `Profil` fermé du client mobile
# (`mobile/src/roles/types.ts`), moins `client` — voir la note de tête de ce module pour pourquoi
# `nathan_owner` n'en fait PAS partie (bloquerait le routage app, `evaluerGarde` refuse fermé un
# rôle hors de `Profil`). `finance`/`manager`/`system_agent` n'ont pas de profil mobile non plus
# (§9 de la définition produit).
ROLES_APPAREIL: frozenset[str] = frozenset({
    identite.Role.ADMIN.value,
    identite.Role.EMPLOYEE.value,
    identite.Role.SELLER.value,
})


@dataclasses.dataclass(frozen=True)
class Appareil:
    identifiant: str
    personne: str
    role: str
    appaire_le: str


def _maintenant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _valider_identifiant(identifiant: str) -> str:
    if not isinstance(identifiant, str) or not identifiant.strip():
        raise ValueError("identifiant d'appareil requis (chaîne non vide)")
    return identifiant.strip()


def appairer(cnx: Connection, identifiant: str, personne_identifiant: str, role: str) -> Appareil:
    """Appaire (ou réappaire) un appareil à une personne et un rôle de jeton (ADR-0009 §5).

    Fail-closed : la personne doit être active ET porter déjà elle-même `role` ; sinon `ValueError`
    nommée, rien n'est écrit. Idempotent par `identifiant` : ré-appairer un identifiant déjà connu
    remplace la ligne existante (changement de téléphone, changement de rôle) plutôt que d'échouer.
    """
    identifiant = _valider_identifiant(identifiant)
    if role not in ROLES_APPAREIL:
        raise ValueError(f"rôle d'appareil invalide {role!r} (attendu : {sorted(ROLES_APPAREIL)})")
    personne = identite.personne_active(cnx, personne_identifiant)
    if personne is None:
        raise ValueError(f"{personne_identifiant!r} : personne inconnue ou inactive")
    if role not in personne.roles:
        raise ValueError(
            f"{personne_identifiant!r} ne porte pas le rôle {role!r} : un appareil ne peut pas "
            "recevoir plus de portée que sa personne (ADR-0009 §5)"
        )
    horodatage = _maintenant()
    insertion = inserer(cnx)(APPAREILS).values(
        identifiant=identifiant, personne=personne.identifiant, role=role, appaire_le=horodatage,
    )
    cnx.execute(insertion.on_conflict_do_update(
        index_elements=[APPAREILS.c.identifiant],
        set_={"personne": insertion.excluded.personne, "role": insertion.excluded.role,
              "appaire_le": insertion.excluded.appaire_le},
    ))
    return Appareil(identifiant, personne.identifiant, role, horodatage)


def appareil(cnx: Connection, identifiant: str) -> Appareil | None:
    """L'appairage d'un appareil, ou None s'il n'est pas (ou plus) appairé."""
    ligne = cnx.execute(
        select(APPAREILS).where(APPAREILS.c.identifiant == identifiant)
    ).mappings().fetchone()
    if ligne is None:
        return None
    return Appareil(ligne["identifiant"], ligne["personne"], ligne["role"], ligne["appaire_le"])


def lister(cnx: Connection) -> list[Appareil]:
    lignes = cnx.execute(select(APPAREILS).order_by(APPAREILS.c.identifiant)).mappings().all()
    return [Appareil(ligne["identifiant"], ligne["personne"], ligne["role"], ligne["appaire_le"])
            for ligne in lignes]


def revoquer(cnx: Connection, identifiant: str) -> None:
    resultat = cnx.execute(delete(APPAREILS).where(APPAREILS.c.identifiant == identifiant))
    if resultat.rowcount == 0:
        raise KeyError(f"appareil inconnu : {identifiant}")


def vers_json(a: Appareil) -> dict[str, Any]:
    return {"identifiant": a.identifiant, "personne": a.personne, "role": a.role,
            "appaireLe": a.appaire_le}
