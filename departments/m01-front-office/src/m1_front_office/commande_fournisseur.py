"""Le canal de M1 pour les commandes de M6 (M6.6, côté M1) : du courriel de commande d'un PO à un brouillon dans le sas.

- `m6.po_courriel_pret` (M6 a généré le courriel d'un PO approuvé) devient un BROUILLON de courriel au fournisseur,
créé dans le sas d'envoi ordinaire (`courriel_connecteurs.envoi`), depuis un compte connecté qui permet l'envoi. M1
ne révise pas les quantités ni les prix : le texte est celui de M6 (source de vérité du PO), contrôlé par le
garde-fou de sortie du sas. L'agent demande ensuite l'envoi (`m1_demander_envoi_courriel`, N3) ; une PERSONNE approuve
  l'empreinte exacte.
- `m1.courriel_envoye` (le planificateur a envoyé un brouillon approuvé) devient `m1.commande_courriel_envoyee` si ce
  brouillon était une commande : M6 le constate ; il ne change pas lui-même le statut du PO.

Idempotent : un PO et une empreinte de courriel ne donnent qu'un brouillon ; un envoi ne se constate qu'une fois.
"""

from __future__ import annotations

from typing import Any

from opsys import evenements, stockage
from opsys.courriel_connecteurs import comptes, envoi
from opsys.courriel_connecteurs.erreurs import ErreurCourriel

from . import courriel_outils
from . import outils as _o
from .registre import TYPE_REPONSE_COURRIEL

DEPARTEMENT = "m01-front-office"
REGISTRE = "commandes_fournisseur"
TYPE_BROUILLON = "commande_fournisseur_brouillon"
TYPE_ENVOYEE = "m1.commande_courriel_envoyee"
PREFIXE_SIGNAL = "commande:"


def _reg() -> Any:
    return stockage.maillons(DEPARTEMENT, REGISTRE)


def _compte_d_envoi() -> str | None:
    cnx = stockage.connexion_courante()
    candidats = [c for c in comptes.lister(cnx) if c["usage"] == "lecture_envoi" and c["etat"] == "connecte"]
    return candidats[0]["compte_id"] if candidats else None


def recevoir_po_courriel_pret(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m6.po_courriel_pret`. Sans compte d'envoi connecté : lève (le répartiteur réessaie, puis met en
    quarantaine, visible) ; un refus déterministe du garde-fou est rangé, pas retenté."""
    registre = _reg()
    cle = f"{charge['po_id']}|{charge['empreinte']}"
    if any(m.get("cle") == cle for m in registre):
        return {"deja_prepare": True}
    compte_id = _compte_d_envoi()
    if compte_id is None:
        raise ValueError(
            "REJ-M1-COMMANDE-AUCUN-COMPTE: aucun compte courriel connecté avec l'usage lecture_envoi : "
            "connecter un compte (console, Plateforme > Connecteurs) puis laisser le bus réessayer"
        )
    horodatage = courriel_outils._horodatage()
    try:
        brouillon = envoi.creer_brouillon(
            stockage.connexion_courante(),
            DEPARTEMENT,
            compte_id,
            a=[charge["destinataire"]],
            objet=charge["objet"],
            corps=charge["corps"],
        )
    except ErreurCourriel as exc:
        registre.append(
            {
                "type_entree": TYPE_BROUILLON,
                "horodatage": horodatage,
                "cle": cle,
                "po_id": charge["po_id"],
                "empreinte": charge["empreinte"],
                "statut": "refuse",
                "code": exc.code,
            }
        )
        return {"refuse": exc.code}
    _o._obtenir_registre().ajouter(
        {
            "type_entree": TYPE_REPONSE_COURRIEL,
            "horodatage": horodatage,
            "signal_id": PREFIXE_SIGNAL + charge["po_id"] + ":" + charge["empreinte"][:12],
            "etape": "preparee",
            "brouillon_id": brouillon.brouillon_id,
            "revision": brouillon.revision,
            "empreinte": brouillon.empreinte,
            "compte_id": compte_id,
        }
    )
    registre.append(
        {
            "type_entree": TYPE_BROUILLON,
            "horodatage": horodatage,
            "cle": cle,
            "po_id": charge["po_id"],
            "empreinte": charge["empreinte"],
            "brouillon_id": brouillon.brouillon_id,
            "compte_id": compte_id,
            "statut": "brouillon",
        }
    )
    return {"brouillon_id": brouillon.brouillon_id, "statut": "brouillon"}


def recevoir_courriel_envoye(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m1.courriel_envoye` : si le brouillon envoyé était une commande, M6 en est informé."""
    ligne = next(
        (
            m
            for m in _reg()
            if m.get("type_entree") == TYPE_BROUILLON and m.get("brouillon_id") == charge["brouillon_id"]
        ),
        None,
    )
    if ligne is None:
        return {"ignore": True}
    # C2 : M6 prend acte de l'envoi (sans seconde approbation) seulement si c'est bien le courriel qu'il a offert.
    # `empreinte_courriel_po` : l'empreinte du courriel du PO que M6 nous a donnée ; `contenu_identique` : le brouillon
    # envoyé est celui qu'on avait préparé (même empreinte qu'à la préparation), donc personne n'a modifié le texte.
    preparee = next(
        (
            m
            for m in _o._obtenir_registre().lire()
            if m.get("type_entree") == TYPE_REPONSE_COURRIEL
            and m.get("brouillon_id") == charge["brouillon_id"]
            and m.get("etape") == "preparee"
        ),
        None,
    )
    evenements.publier(
        TYPE_ENVOYEE,
        DEPARTEMENT,
        {
            "po_id": ligne["po_id"],
            "brouillon_id": charge["brouillon_id"],
            "empreinte": charge["empreinte"],
            "envoye_le": charge["envoye_le"],
            "empreinte_courriel_po": ligne["empreinte"],
            "contenu_identique": preparee is not None and preparee.get("empreinte") == charge["empreinte"],
        },
        evenement_id=f"m1-commande-envoyee-{charge['brouillon_id']}-{charge['empreinte'][:12]}",
    )
    return {"constate": True, "po_id": ligne["po_id"]}
