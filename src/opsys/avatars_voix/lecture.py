"""Lecture ADMIN de l'état des avatars : registre des voix et visages, canaux, preuves. Aucune écriture.

Alimente `opsys-metier avatars` et la page « Plateforme > Avatars » de la console. Ne montre ni empreinte vocale, ni
référence de locuteur, ni transcription ; les consentements sont comptés, leurs documents désignés par référence.
La messagerie vient du manifeste (`disponible`) ; la voix et l'audiovisuel viennent de la politique (`politique`) :
`prevu`, `configure`, `qualifie`, `disponible` ou `suspendu`, avec les refus qui expliquent ce qui manque.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Mapping
from typing import Any

from sqlalchemy import Connection

from .. import avatars
from . import modele, politique, registre


def _resume_licence(licence: Mapping[str, Any]) -> dict[str, Any]:
    return {cle: licence[cle] for cle in (
        "code", "poids", "usage_commercial", "seuil_revenu_usd", "territoires_exclus", "service_tiers",
        "verification")}


def vue_entree(cnx: Connection, entree: Mapping[str, Any], *, maintenant: dt.datetime) -> dict[str, Any]:
    fournisseur = registre.fournisseur_de(cnx, entree["fournisseur_id"])
    consentements = registre.consentements_de(cnx, entree["identifiant"])
    modifie = (fournisseur is not None
               and entree["manifeste"]["empreinte_runtime"] != modele.empreinte_runtime(fournisseur))
    derniere = (registre.derniere_qualification(cnx, fournisseur.identifiant, modele.empreinte_runtime(fournisseur))
                if fournisseur is not None else None)
    aujourdhui = maintenant.astimezone(dt.UTC).date().isoformat()
    revoques = [c for c in consentements if c["revoque_le"] is not None]
    expires = [c for c in consentements if c["revoque_le"] is None and c["expire_le"] and c["expire_le"] < aujourdhui]
    return {
        "identifiant": entree["identifiant"], "genre": entree["genre"], "etat": entree["etat"],
        "etat_effectif": modele.ETAT_CONFIGURE if modifie and entree["etat"] == modele.ETAT_QUALIFIE
        else entree["etat"],
        "manifeste_modifie": modifie, "empreinte_manifeste": entree["empreinte_manifeste"],
        "langue": entree["langue"], "accent": entree["accent"], "origine": entree["origine"],
        "fournisseur": None if fournisseur is None else {
            "identifiant": fournisseur.identifiant, "modele": fournisseur.modele, "mode": fournisseur.mode,
            "licence": _resume_licence(fournisseur.licence.vers_json())},
        "consentements": {"total": len(consentements), "revoques": len(revoques), "expires": len(expires),
                          "actifs": len(consentements) - len(revoques) - len(expires),
                          "documents": [c["document_ref"] for c in consentements if c["revoque_le"] is None]},
        "empreinte_vocale_tiers": entree["empreinte_vocale_tiers"],
        "declaration_biometrie": entree["declaration_biometrie"],
        "derniere_qualification": None if derniere is None else {
            cle: derniere[cle] for cle in ("quand", "nature", "statut", "detail")},
        "revision": entree["revision"],
    }


def etat_avatars(cnx: Connection, identites: Mapping[str, avatars.IdentiteEffective], *,
                 maintenant: dt.datetime | None = None,
                 canaux_realises: Collection[str] = avatars.CANAUX_REALISES) -> dict[str, Any]:
    """État de chaque avatar (ordre des départements) et registre complet. `identites` : résultat de
    `avatars.identites_effectives`."""
    quand = maintenant or registre.maintenant_utc()
    entrees = {e["identifiant"]: vue_entree(cnx, e, maintenant=quand) for e in registre.lister_entrees(cnx)}
    emploi: dict[str, list[str]] = {}
    for identite in identites.values():
        for identifiant in (identite.voix, identite.visage):
            emploi.setdefault(identifiant, []).append(identite.departement)
    liste = []
    for identite in identites.values():  # déjà dans l'ordre des départements (`avatars.resoudre_identites`)
        canaux: dict[str, Any] = {"messagerie": {
            "canal": "messagerie", "etat": identite.canaux.get("messagerie", "prevu"), "declare": True,
            "refus": [], "codes": []}}
        for canal in politique.CANAUX_GOUVERNES:
            canaux[canal] = politique.etat_canal(cnx, identite, canal, maintenant=quand,
                                                 canaux_realises=canaux_realises)
        liste.append({
            "departement": identite.departement, "code": identite.code, "nom": identite.nom, "role": identite.role,
            "voix": identite.voix, "visage": identite.visage, "canaux": canaux,
            "entrees": {"voix": entrees.get(identite.voix), "visage": entrees.get(identite.visage)},
            "partage": {identifiant: sorted(set(emploi[identifiant]) - {identite.departement})
                        for identifiant in (identite.voix, identite.visage)
                        if set(emploi[identifiant]) - {identite.departement}},
        })
    etats = [a["canaux"][c]["etat"] for a in liste for c in politique.CANAUX_GOUVERNES]
    return {
        "avatars": liste, "registre": list(entrees.values()),
        "canaux_realises": sorted(canaux_realises),
        "resume": {etat: etats.count(etat) for etat in sorted(set(etats))},
        "avertissement": ("La voix n'est pas prouvée de bout en bout : aucun moteur vocal ni transport n'est livré. "
                          "« qualifie » signifie un test de connexion réel journalisé, pas une qualité mesurée."),
    }
