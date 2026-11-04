"""Outils M5 des OPÉRATIONS COMPTABLES (M5.1) : relances de créances, notes de crédit, dépenses d'employés, pièces
justificatives, flux des factures fournisseurs, paiements PRÉPARÉS, jugements et estimations, ouverture et préclôture de
période, mesures pour M8, et le cycle qui enchaîne l'essentiel jusqu'aux BROUILLONS (docs/architecture/M5-SOPHIE.md).

Adaptateur (comme `outils_base_fiscale.py`, mais il lit les aides d'`outils.py` : registres, plan, taux, manifeste).
Séparé d'`outils.py` pour ne pas grossir un fichier de 7 900 lignes. Ce module ne nomme jamais le registre des
mouvements : une opération comptable ne fait bouger aucun argent (`conformite.verifier_aucun_decaissement`, strict).

Autonomie. Les brouillons (relances, notes de crédit, dépenses, flux, mesures, pièces, ouverture, préclôture, cycle)
sont des écritures INTERNES non finales : T1, niveau N1 ou N2, sans approbation. Ce qui engage une personne exige un
HUMAIN identifié par le socle (`approbations.approbateur_en_cours`, jamais un argument) : paiement préparé et
jugements (N3), confirmation d'un rapprochement (N4, `outils_bancaire.py`). Aucun outil ne paie, n'envoie, ne rend
une écriture définitive ni ne clôt une période. Portée d'appareil FERMÉE pour tous (`roles_appareil` vide) et
refusée dans le code (`REJ-IDENTITE-APPAREIL-INVALIDE`).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from opsys import approbations, contexte, evenements, jetons, stockage
from opsys.evenements import constats
from opsys.outils import Autonomie, Niveau, Outil

from . import (
    analyse,
    charges_marketing_recues,
    comptes_a_payer,
    constats_pour_m8,
    encodage,
    facturation,
    grand_livre,
    operations_comptables,
    operations_periodes,
    operations_registre,
    plan_comptable,
    validation,
    verdicts_grand_livre,
    verdicts_operations,
)
from . import outils as _o

__all__ = ["outils_operations", "contexte_operations", "refuse", "accepte", "humain_requis", "lire_fichier_confine"]

_ACTEUR_AGENT = "agent:m05-financecore"
_ROLES_DECISION = frozenset({"nathan_owner", "finance"})
_BUDGET = jetons.LIMITE_SORTIE_DEFAUT - 700
_OCTETS_PIECE_MAX = 25 * 1024 * 1024
_LIMITE_DEFAUT = 8
_LIMITE_MAX = 15
_HORODATAGE = {
    "type": "string",
    "description": "ISO 8601 avec fuseau : le moment de la demande (M5 n'a pas d'horloge).",
}
_DATE = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "description": "Date AAAA-MM-JJ."}
_PERIODE = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$", "description": "Mois AAAA-MM."}
_MONTANT = {
    "type": "string",
    "pattern": "^(?:0|[1-9][0-9]{0,11})(?:\\.[0-9]{1,2})?$",
    "description": "Texte décimal au cent, jamais un nombre JSON.",
}


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


def refuse(verdict: Mapping[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": dict(verdict)}


def accepte(corps: Mapping[str, Any]) -> dict[str, Any]:
    """Une sortie acceptée : les deux mentions, et bornée sous le budget de sortie du socle (jamais coupée en deux)."""
    complet = analyse.avec_mention_comptable(corps)
    if len(json.dumps(complet, ensure_ascii=False, default=str)) > _BUDGET:
        return refuse(
            _verdict("REJ-OPS-LIMITE-INVALIDE", "la réponse dépasse le budget de sortie : restreindre la demande")
        )
    return {"accepte": True, "resultat": complet}


def _appareil_refuse() -> dict[str, str] | None:
    if contexte.identite_appelante() is not None:
        return validation.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail="les opérations comptables ne sont ouvertes à aucun rôle d'appareil (portée fermée) : passer par "
            "l'agent finance",
        )
    return None


def contexte_operations() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Ce dont une opération a besoin, relu à chaque appel : grand livre (registre, plan, état), registre des opérations
    (état) — ou le refus nommé (appareil, stockage non durable, chaîne invalide, anomalie)."""
    refus = _appareil_refuse()
    if refus is not None:
        return None, refus
    ctx, refus = _o._contexte_grand_livre()
    if refus is not None:
        return None, refus
    registre_gl, plan = ctx
    registre_ops = _o._registre_operations()
    if registre_ops is None:
        return None, _verdict("REJ-OPS-STOCKAGE-NON-DURABLE", "registre durable des opérations requis")
    valide, raison = registre_ops.valider_chaine()
    if not valide:
        return None, _verdict("REJ-OPS-CHAINE-INVALIDE", raison)
    etat_ops = operations_registre.etat_operations(registre_ops.lire())
    refus = operations_registre.refus_anomalies(etat_ops)
    if refus is not None:
        return None, refus
    etat_gl = grand_livre.etat_grand_livre(registre_gl.lire())
    return {"gl": registre_gl, "plan": plan, "ops": registre_ops, "etat_ops": etat_ops, "etat_gl": etat_gl}, None


def humain_requis(nom_outil: str, geste: str) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """La personne qui a approuvé la demande en cours d'exécution (propriétaire ou finance), dite par le SOCLE ; sinon
    `REJ-OPS-HUMAIN-REQUIS`. Ni argument, ni texte du modèle, ni appareil : un agent seul n'obtient jamais ce geste,
    même
    en mode « autonome »."""
    cnx = stockage.connexion_courante()
    approbateur = (
        approbations.approbateur_en_cours(cnx, nom_outil, _o._DEPARTEMENT, roles=_ROLES_DECISION)
        if cnx is not None
        else None
    )
    if approbateur is None:
        return None, _verdict(
            "REJ-OPS-HUMAIN-REQUIS",
            f"{geste} se décide par le propriétaire ou la finance dans la file OPSYS ; un agent le "
            "prépare, il ne le fait jamais",
        )
    return {"par": approbateur.personne, "role": approbateur.role, "voie": "approbation"}, None


def lire_fichier_confine(
    sous_dossier: str, nom: Any, taille_max: int, role: str
) -> tuple[bytes | None, dict[str, Any] | None]:
    """Les octets d'un fichier déposé par un humain dans `<OPSYS_HOME>/imports/<sous_dossier>/`, par son NOM seul :
    refus pour un nom à chemin, caché, démesuré, un fichier absent, un lien symbolique, autre chose qu'un fichier
    ordinaire, ou
    plus de `taille_max` octets."""
    if (
        not isinstance(nom, str)
        or not 1 <= len(nom) <= 120
        or "/" in nom
        or "\\" in nom
        or ".." in nom
        or nom.startswith(".")
        or not nom.isprintable()
    ):
        return None, _verdict(
            "REJ-BANQUE-FICHIER-INVALIDE",
            f"{role} : un nom de fichier seul (sans chemin, sans « .. », 120 caractères au plus)",
        )
    chemin = stockage.dossier_opsys() / "imports" / sous_dossier / nom
    try:
        descripteur = os.open(chemin, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None, _verdict(
            "REJ-BANQUE-FICHIER-INTROUVABLE",
            f"{role} : {nom!r} absent du dossier imports/{sous_dossier}, ou lien symbolique",
        )
    try:
        etat = os.fstat(descripteur)
        if not stat.S_ISREG(etat.st_mode) or etat.st_size > taille_max:
            return None, _verdict(
                "REJ-BANQUE-FICHIER-INVALIDE", f"{role} : pas un fichier ordinaire, ou plus de {taille_max} octets"
            )
        with os.fdopen(os.dup(descripteur), "rb") as flux:
            return flux.read(taille_max + 1), None
    finally:
        os.close(descripteur)


def _recu_ecriture(registre_ops: Any) -> dict[str, Any]:
    """Le reçu d'une écriture au registre : la tête de la chaîne après l'appel et sa taille."""
    return {"tete_du_registre": registre_ops.tete(), "taille_du_registre": registre_ops.taille()}


def _limite(limite: Any) -> tuple[int | None, dict[str, str] | None]:
    valeur = _LIMITE_DEFAUT if limite is None else limite
    if type(valeur) is not int or not 1 <= valeur <= _LIMITE_MAX:
        return None, _verdict("REJ-OPS-LIMITE-INVALIDE", f"limite : entier de 1 à {_LIMITE_MAX}")
    return valeur, None


def _factures_clients_par_id(registre_factures: Any | None = None) -> dict[str, dict[str, Any]]:
    registre_factures = _o._registre_factures(None) if registre_factures is None else registre_factures
    resultat: dict[str, dict[str, Any]] = {}
    for statut in ("BROUILLON", "ENVOYEE", "PAYEE", "ANNULEE"):
        for facture in facturation.factures_par_statut(registre_factures, statut):
            resultat[facture["facture_id"]] = facture
    return resultat


def _instantane_cloture(ctx: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Capture les registres qui alimentent préclôture/CPA par un seul SELECT.

    Les fichiers de configuration et taux restent lus selon leurs contrats propres; seule la cohérence des lignes
    SQL de ces quatre registres est couverte.
    """
    from . import registre as registre_module

    noms = (
        _o._NOM_REGISTRE_GRAND_LIVRE,
        _o._NOM_REGISTRE_FACTURES,
        _o._NOM_REGISTRE_COMPTES_A_PAYER,
        _o._NOM_REGISTRE_OPERATIONS,
    )
    maillons = stockage.lire_instantane_maillons(_o._DEPARTEMENT, noms)
    registres = {nom: registre_module.Registre(maillons=maillons[nom]) for nom in noms}

    valide, raison = registres[_o._NOM_REGISTRE_GRAND_LIVRE].valider_chaine()
    if not valide:
        return None, verdicts_grand_livre.construire_verdict("REJ-GL-CHAINE-INVALIDE", detail=raison)
    valide, raison = registres[_o._NOM_REGISTRE_OPERATIONS].valider_chaine()
    if not valide:
        return None, _verdict("REJ-OPS-CHAINE-INVALIDE", raison)
    etat_ops = operations_registre.etat_operations(maillons[_o._NOM_REGISTRE_OPERATIONS])
    refus = operations_registre.refus_anomalies(etat_ops)
    if refus is not None:
        return None, refus

    resultat = dict(ctx)
    resultat.update(
        etat_gl=grand_livre.etat_grand_livre(maillons[_o._NOM_REGISTRE_GRAND_LIVRE]),
        etat_ops=etat_ops,
        maillons_cloture=maillons,
        registre_factures_cloture=registres[_o._NOM_REGISTRE_FACTURES],
        registre_ap_cloture=registres[_o._NOM_REGISTRE_COMPTES_A_PAYER],
        registre_ops_cloture=registres[_o._NOM_REGISTRE_OPERATIONS],
        tetes_cloture={nom: registres[nom].tete() for nom in noms},
    )
    return resultat, None


def _factures_fournisseurs_par_id() -> dict[str, dict[str, Any]]:
    return {
        f["facture_fournisseur_id"]: f
        for f in comptes_a_payer.etats_toutes_les_factures(_o._registre_comptes_a_payer())
    }


def _config_operations() -> dict[str, Any]:
    brut = _o._configuration_manifeste().get("operations")
    return brut if isinstance(brut, dict) else {}


# ============================================================================================ relances de créances
def _relances_impl(ctx: Mapping[str, Any], aujourd_hui: Any, horodatage: Any) -> tuple[dict | None, dict | None]:
    politique, refus = operations_comptables.lire_politique_relances(_config_operations().get("relances"))
    if refus is not None:
        return None, refus
    factures = [f for f in _o._factures_emises() if f.get("statut") == "ENVOYEE"]
    resultat, refus = operations_comptables.preparer_relances(
        ctx["ops"], ctx["etat_ops"], factures, politique, aujourd_hui, horodatage
    )
    if refus is not None:
        return None, refus
    for evenement in resultat["evenements"]:
        charge = {k: v for k, v in evenement.items() if k != "evenement_id"}
        evenements.publier(
            "m5.creance_relance_preparee", _o._DEPARTEMENT, charge, evenement_id=evenement["evenement_id"]
        )
    return resultat, None


def preparer_relances_clients(aujourd_hui: str, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    resultat, refus = _relances_impl(ctx, aujourd_hui, horodatage)
    if refus is not None:
        return refuse(refus)
    etat = operations_registre.etat_operations(ctx["ops"].lire())
    textes = [
        {
            "relance_id": c["relance_id"],
            "facture_id": c["facture_id"],
            "niveau": c["niveau"],
            "jours_retard": c["jours_retard"],
            "montant_du": c["montant_du"],
            "brouillon": etat["par_type"]["op_relance_preparee"][c["relance_id"]]["texte"],
        }
        for c in resultat["creees"][:_LIMITE_DEFAUT]
    ]
    return accepte(
        {
            "creees": len(resultat["creees"]),
            "brouillons": textes,
            "brouillons_reste": max(0, len(resultat["creees"]) - len(textes)),
            "deja_preparees": resultat["deja"],
            "sans_retard": resultat["sans_retard"],
            "soldees_par_notes_de_credit": resultat["soldees"],
            "ignorees": resultat["ignorees"],
            "politique": resultat["politique"],
            "evenements_publies": len(resultat["evenements"]),
            "recu": _recu_ecriture(ctx["ops"]),
            "a_faire": (
                "chaque relance est un BROUILLON : l'envoi appartient à M1 (approbation humaine) ; rien n'est envoyé"
            ),
        }
    )


# ================================================================================================ notes de crédit
def proposer_note_credit(
    genre: str, facture_id: str, reference: str, montant_avant_taxes: str, date_effet: str, motif: str, horodatage: str
) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    dictionnaire, refus = _o._dictionnaire_taux()
    if refus is not None:
        return refuse(refus)
    if genre == "client":
        facture = _factures_clients_par_id().get(facture_id)
    elif genre == "fournisseur":
        facture = _factures_fournisseurs_par_id().get(facture_id)
    else:
        facture = None
    resultat, refus = operations_comptables.proposer_note_credit(
        ctx["ops"],
        ctx["etat_ops"],
        ctx["gl"],
        ctx["plan"],
        dictionnaire,
        genre=genre,
        facture=facture,
        reference=reference,
        montant_avant_taxes=montant_avant_taxes,
        date_effet=date_effet,
        motif=motif,
        horodatage=horodatage,
    )
    if refus is not None:
        return refuse(refus)
    return accepte({**resultat, "recu": _recu_ecriture(ctx["ops"])})


# ====================================================================================== dépenses d'employés
def proposer_depense_employe(
    employe_id: str,
    reference: str,
    date_depense: str,
    categorie: str,
    description: str,
    montant_avant_taxes: str,
    taxable: bool,
    total_recu: str,
    horodatage: str,
) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    dictionnaire, refus = _o._dictionnaire_taux()
    if refus is not None:
        return refuse(refus)
    categories, refus = comptes_a_payer.lire_categories_depense(_o._categories_depense_sans_po())
    if refus is not None:
        return refuse(refus)
    if categorie not in categories:
        return refuse(
            _verdict(
                "REJ-OPS-ENTREE-INVALIDE",
                f"categorie {categorie!r} hors de la liste fermée du propriétaire {list(categories)}",
            )
        )
    resultat, refus = operations_comptables.proposer_depense_employe(
        ctx["ops"],
        ctx["etat_ops"],
        ctx["gl"],
        ctx["plan"],
        dictionnaire,
        employe_id=employe_id,
        reference=reference,
        date_depense=date_depense,
        categorie=categorie,
        description=description,
        montant_avant_taxes=montant_avant_taxes,
        taxable=taxable,
        total_recu=total_recu,
        compte_remboursement=_config_operations().get("compte_remboursement_employes"),
        horodatage=horodatage,
    )
    if refus is not None:
        return refuse(refus)
    return accepte({**resultat, "recu": _recu_ecriture(ctx["ops"])})


# ================================================================================== pièces justificatives
def _cibles_connues(ctx: Mapping[str, Any], cible_type: str) -> list[str]:
    if cible_type == "facture_client":
        return list(_factures_clients_par_id())
    if cible_type == "facture_fournisseur":
        return list(_factures_fournisseurs_par_id())
    if cible_type == "ecriture":
        return list(ctx["etat_gl"]["ecritures"])
    table = {
        "note_credit": "op_note_credit_proposee",
        "depense_employe": "op_depense_employe_proposee",
        "paiement_prepare": "op_paiement_prepare",
        "rapprochement": "op_rapprochement_prepare",
        "releve_bancaire": "op_rapprochement_prepare",
    }
    type_op = table.get(cible_type)
    return [] if type_op is None else list(ctx["etat_ops"]["par_type"][type_op])


def lier_piece_justificative(cible_type: str, cible_id: str, fichier: str, horodatage: str) -> dict[str, Any]:
    """Lie la pièce déposée dans `<OPSYS_HOME>/imports/pieces/` : l'empreinte SHA-256 et la taille sont CALCULÉES
    ici, jamais
    reprises d'un argument (un modèle ne fabrique pas l'empreinte d'un reçu)."""
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    octets, refus = lire_fichier_confine("pieces", fichier, _OCTETS_PIECE_MAX, "fichier")
    if refus is not None:
        return refuse(refus)
    resultat, refus = operations_comptables.lier_piece(
        ctx["ops"],
        ctx["etat_ops"],
        cible_type=cible_type,
        cible_id=cible_id,
        cibles_connues={cible_type: _cibles_connues(ctx, cible_type)} if isinstance(cible_type, str) else {},
        nom=fichier,
        sha256=hashlib.sha256(octets).hexdigest(),
        taille=len(octets),
        lie_par=_ACTEUR_AGENT,
        horodatage=horodatage,
    )
    if refus is not None:
        return refuse(refus)
    return accepte({**resultat, "taille": len(octets), "recu": _recu_ecriture(ctx["ops"])})


# ============================================================================================= flux fournisseur
def _rapprochement_po(facture: Mapping[str, Any]) -> dict[str, Any] | None:
    if facture.get("po_id") is None:
        return None
    dictionnaire, refus = _o._dictionnaire_taux()
    if refus is not None:
        return None
    vue, verdict = comptes_a_payer.proposer_rapprochement(
        _o._registre_comptes_a_payer(), dictionnaire, facture["po_id"]
    )
    return vue if verdict is None else None


def _etat_flux(ctx: Mapping[str, Any], facture: Mapping[str, Any]) -> dict[str, Any]:
    ident = facture["facture_fournisseur_id"]
    ecriture = ctx["etat_gl"]["ecritures"].get(
        grand_livre.identifiant_ecriture(f"auto:facture_fournisseur:{ident}:saisie")
    )
    paiements = [
        p for p in ctx["etat_ops"]["par_type"]["op_paiement_prepare"].values() if p["facture_fournisseur_id"] == ident
    ]
    notes = [
        n
        for n in ctx["etat_ops"]["par_type"]["op_note_credit_proposee"].values()
        if n["genre"] == "fournisseur" and n["facture_id"] == ident
    ]
    return operations_periodes.flux_fournisseur(
        facture, _rapprochement_po(facture), ecriture, paiements[0] if paiements else None, notes
    )


def lire_flux_fournisseur(facture_fournisseur_id: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    facture = _factures_fournisseurs_par_id().get(facture_fournisseur_id)
    if facture is None:
        return refuse(_verdict("REJ-OPS-FACTURE-INTROUVABLE", "facture fournisseur absente du registre de M5"))
    return accepte(_etat_flux(ctx, facture))


def _avancer_impl(
    ctx: Mapping[str, Any],
    facture: Mapping[str, Any],
    horodatage: Any,
    aujourd_hui: Any,
) -> tuple[dict | None, dict | None]:
    """Fait avancer UNE facture fournisseur jusqu'au brouillon : le brouillon d'écriture (idempotent), puis, pour une
    facture sur PO, le constat de rapprochement publié pour M6 (une fois par état)."""
    if facture["statut"] == "ANNULEE":
        return {"flux": _etat_flux(ctx, facture), "brouillon": "aucun (facture annulée)", "evenement": False}, None
    propositions, ignorees = grand_livre.propositions_factures_fournisseurs([facture], ctx["plan"])
    brouillon = "deja"
    for proposition in propositions:
        resultat, refus = grand_livre.proposer_ecriture(
            ctx["gl"], ctx["plan"], horodatage=horodatage, origine="generation_automatique", **proposition
        )
        if refus is not None:
            return None, refus
        brouillon = "cree" if resultat["statut"] == "proposee" else "deja"
    if ignorees:
        brouillon = "ignoree : " + ignorees[0]["code"]
    publie = False
    rapprochement = _rapprochement_po(facture)
    if facture.get("po_id") is not None and rapprochement is not None and _date_valide(aujourd_hui):
        empreinte = encodage.empreinte(
            "m5.flux.rapprochement.v1",
            {
                k: rapprochement.get(k)
                for k in ("verdict", "sens", "facture_avant_taxes", "recu_avant_taxes", "reserves")
            },
            facture["montant_apres_taxes"],
        )
        cle = f"flux:{facture['facture_fournisseur_id']}:{empreinte[:16]}"
        corps = {
            "facture_fournisseur_id": facture["facture_fournisseur_id"],
            "po_id": facture["po_id"],
            "verdict": rapprochement["verdict"],
        }  # sans date : l'identité d'un constat est son état, pas son jour
        etat_ops = operations_registre.etat_operations(ctx["ops"].lire())
        enregistre, refus = operations_registre.ajouter_operation(
            ctx["ops"], etat_ops, "op_flux_fournisseur_constate", cle, corps, horodatage
        )
        if refus is not None:
            return None, refus
        if enregistre["statut"] == "ecrite":
            ecart = rapprochement.get("facture_moins_recu")
            evenements.publier(
                "m5.rapprochement_po_constate",
                _o._DEPARTEMENT,
                {
                    "facture_fournisseur_id": facture["facture_fournisseur_id"],
                    "po_id": facture["po_id"],
                    "verdict": rapprochement["verdict"],
                    "sens": rapprochement.get("sens"),
                    "facture_avant_taxes": rapprochement.get("facture_avant_taxes"),
                    "recu_avant_taxes": rapprochement.get("recu_avant_taxes"),
                    "ecart_avant_taxes": ecart,
                    "reserves": rapprochement["reserves"],
                    "date_reference": aujourd_hui,
                },
                evenement_id=f"m5-rappo-{facture['facture_fournisseur_id']}-{empreinte[:16]}",
            )
            publie = True
    contexte_apres = {
        **ctx,
        "etat_gl": grand_livre.etat_grand_livre(ctx["gl"].lire()),
        "etat_ops": operations_registre.etat_operations(ctx["ops"].lire()),
    }
    return {"flux": _etat_flux(contexte_apres, facture), "brouillon": brouillon, "evenement": publie}, None


def _date_valide(valeur: Any) -> bool:
    try:
        return isinstance(valeur, str) and date.fromisoformat(valeur) is not None
    except ValueError:
        return False


def avancer_flux_fournisseur(facture_fournisseur_id: str, aujourd_hui: str, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    if not _date_valide(aujourd_hui):
        return refuse(_verdict("REJ-OPS-DATE-INVALIDE", f"aujourd_hui {aujourd_hui!r} : AAAA-MM-JJ exigé"))
    facture = _factures_fournisseurs_par_id().get(facture_fournisseur_id)
    if facture is None:
        return refuse(_verdict("REJ-OPS-FACTURE-INTROUVABLE", "facture fournisseur absente du registre de M5"))
    resultat, refus = _avancer_impl(ctx, facture, horodatage, aujourd_hui)
    if refus is not None:
        return refuse(refus)
    return accepte({**resultat, "recu": _recu_ecriture(ctx["ops"])})


def preparer_paiement_fournisseur(
    facture_fournisseur_id: str, date_prevue: str, derogation_motif: str | None, horodatage: str
) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    humain, refus = humain_requis("m5_preparer_paiement_fournisseur", "préparer le paiement d'une facture fournisseur")
    if refus is not None:
        return refuse(refus)
    facture = _factures_fournisseurs_par_id().get(facture_fournisseur_id)
    resultat, refus = operations_comptables.preparer_paiement(
        ctx["ops"],
        ctx["etat_ops"],
        facture=facture,
        rapprochement=None if facture is None else _rapprochement_po(facture),
        date_prevue=date_prevue,
        derogation_motif=derogation_motif,
        humain=humain,
        horodatage=horodatage,
    )
    if refus is not None:
        return refuse(refus)
    ecriture = ctx["etat_gl"]["ecritures"].get(
        grand_livre.identifiant_ecriture(f"auto:facture_fournisseur:{facture_fournisseur_id}:saisie")
    )
    avertissements = []
    if ecriture is None or ecriture["statut"] != "DEFINITIVE":
        avertissements.append("l'écriture de la facture n'est pas encore définitive : valider d'abord (N4)")
    return accepte(
        {
            **resultat,
            "prepare_par": humain["par"],
            "avertissements": avertissements,
            "recu": _recu_ecriture(ctx["ops"]),
            "a_faire": "une personne autorisée exécute le paiement HORS d'OPSYS (N5, propriétaire ET attestation)",
        }
    )


# ==================================================================================== jugements et périodes
def consigner_jugement_comptable(
    genre: str,
    periode: str,
    sujet: str,
    description: str,
    montant: str | None,
    hypotheses: list[str],
    base: str,
    horodatage: str,
) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    humain, refus = humain_requis(
        "m5_consigner_jugement_comptable", "consigner un jugement ou une estimation comptable"
    )
    if refus is not None:
        return refuse(refus)
    resultat, refus = operations_comptables.enregistrer_jugement(
        ctx["ops"],
        ctx["etat_ops"],
        genre=genre,
        periode=periode,
        sujet=sujet,
        description=description,
        montant=montant,
        hypotheses=hypotheses,
        base=base,
        humain=humain,
        horodatage=horodatage,
    )
    if refus is not None:
        return refuse(refus)
    return accepte(
        {
            **resultat,
            "consigne_par": humain["par"],
            "recu": _recu_ecriture(ctx["ops"]),
            "nature": "consigné par une personne ; OPSYS ne le valide pas",
        }
    )


def ouvrir_periode_comptable(periode: str, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    resultat, refus = operations_periodes.ouvrir_periode(
        ctx["ops"], ctx["etat_ops"], ctx["etat_gl"], periode=periode, horodatage=horodatage
    )
    if refus is not None:
        return refuse(refus)
    return accepte({**resultat, "recu": _recu_ecriture(ctx["ops"])})


def controle_taxes_bornes(
    ctx: Mapping[str, Any], debut: str, fin: str
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Retourne `(rapprochement, refus)` pour les notes de crédit et dépenses d'employés sur `debut`..`fin`.

    Le taux ou la date indisponible garde le résultat à `None`; une incohérence Ops ou AP retourne un refus nommé.
    """
    dictionnaire, refus = _o._dictionnaire_taux()
    if refus is not None:
        return None, None
    registre_factures = ctx.get("registre_factures_cloture")
    if registre_factures is None:
        factures_clients = _o._factures_emises()
    else:
        refus_chaine = _o._verdict_chaine_financiere(
            _o._NOM_REGISTRE_FACTURES, ctx["maillons_cloture"][_o._NOM_REGISTRE_FACTURES]
        )
        if refus_chaine is not None:
            return None, verdicts_grand_livre.construire_verdict(
                "REJ-GL-SOURCE-ILLISIBLE", detail="registre factures incohérent; source illisible"
            )
        factures_clients = _o._factures_emises(registre_factures)
    try:
        registre_ap = ctx.get("registre_ap_cloture")
        if registre_ap is not None:
            refus_chaine = _o._verdict_chaine_financiere(
                _o._NOM_REGISTRE_COMPTES_A_PAYER,
                ctx["maillons_cloture"][_o._NOM_REGISTRE_COMPTES_A_PAYER],
            )
            if refus_chaine is not None:
                raise comptes_a_payer.RegistreComptesIncoherent("chaîne AP invalide")
        factures_fournisseurs_vivantes = _o._factures_fournisseurs_vivantes(registre_ap)
    except comptes_a_payer.RegistreComptesIncoherent:
        return None, verdicts_grand_livre.construire_verdict(
            "REJ-GL-SOURCE-ILLISIBLE", detail="registre comptes_a_payer incohérent; source illisible"
        )
    autres_pieces, refus = _o._autres_pieces_taxees_verifiees(
        ctx.get("registre_ops_cloture", ctx.get("ops")), etat_ops=ctx.get("etat_ops")
    )
    if refus is not None:
        return None, refus
    resultat, refus = grand_livre.rapprocher(
        ctx["etat_gl"],
        ctx["plan"],
        factures_clients,
        dictionnaire,
        debut=debut,
        fin=fin,
        limite_ecarts=3,
        factures_fournisseurs=factures_fournisseurs_vivantes,
        autres_pieces_taxees=autres_pieces or [],
    )
    return (None if refus is not None else resultat), None


def _controle_taxes(
    ctx: Mapping[str, Any], periode: str
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    fin = grand_livre.fin_de_periode(periode)
    return (None, None) if fin is None else controle_taxes_bornes(
        ctx, fin.replace(day=1).isoformat(), fin.isoformat()
    )


def _precloture_impl(ctx: Mapping[str, Any], periode: Any, horodatage: Any) -> tuple[dict | None, dict | None]:
    ctx, refus = _instantane_cloture(ctx)
    if refus is not None:
        return None, refus
    refus_chaine = _o._verdict_chaine_financiere(
        _o._NOM_REGISTRE_FACTURES, ctx["maillons_cloture"][_o._NOM_REGISTRE_FACTURES]
    )
    if refus_chaine is not None:
        return None, verdicts_grand_livre.construire_verdict(
            "REJ-GL-SOURCE-ILLISIBLE", detail="registre factures incohérent; source illisible"
        )
    factures_clients = list(_factures_clients_par_id(ctx["registre_factures_cloture"]).values())
    try:
        refus_chaine = _o._verdict_chaine_financiere(
            _o._NOM_REGISTRE_COMPTES_A_PAYER,
            ctx["maillons_cloture"][_o._NOM_REGISTRE_COMPTES_A_PAYER],
        )
        if refus_chaine is not None:
            raise comptes_a_payer.RegistreComptesIncoherent("chaîne AP invalide")
        factures_fournisseurs = comptes_a_payer.etats_toutes_les_factures(ctx["registre_ap_cloture"])
    except comptes_a_payer.RegistreComptesIncoherent:
        return None, verdicts_grand_livre.construire_verdict(
            "REJ-GL-SOURCE-ILLISIBLE", detail="registre comptes_a_payer incohérent; source illisible"
        )
    controle_taxes = None
    if isinstance(periode, str):
        controle_taxes, refus = _controle_taxes(ctx, periode)
        if refus is not None:
            return None, refus
    return operations_periodes.preclore_periode(
        ctx["ops"],
        ctx["etat_ops"],
        ctx["etat_gl"],
        periode=periode,
        factures_clients=factures_clients,
        factures_fournisseurs=factures_fournisseurs,
        controle_taxes=controle_taxes,
        horodatage=horodatage,
    )


def precloturer_periode_comptable(periode: str, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    resultat, refus = _precloture_impl(ctx, periode, horodatage)
    if refus is not None:
        return refuse(refus)
    resultat = {**resultat, "controles": [{**c, "detail": c["detail"][:220]} for c in resultat["controles"]]}
    resultat["recu"] = {
        **{k: resultat["recu"][k] for k in ("moteur", "empreinte", "empreinte_entrees")},
        **_recu_ecriture(ctx["ops"]),
    }
    return accepte(resultat)


# ============================================================================================ mesures pour M8
def _creances(aujourd_hui: str) -> dict[str, Any]:
    age, _ = facturation.calculer_age_creances(_o._registre_factures(None), aujourd_hui)
    tranches = {
        t: format(Decimal(montant).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
        for t, montant in age["total_par_tranche"].items()
    }
    nombre = sum(len(v) for v in age["tranches"].values())
    total = sum((Decimal(m) for m in age["total_par_tranche"].values()), Decimal("0.00"))
    return {
        "nombre": nombre,
        "total": format(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
        "par_tranche": tranches,
    }


def _mesures_impl(ctx: Mapping[str, Any], aujourd_hui: str, horodatage: str) -> tuple[dict | None, dict | None]:
    mesures = operations_periodes.mesures_comptables(
        ctx["etat_gl"], ctx["etat_ops"], creances=_creances(aujourd_hui), date_reference=aujourd_hui
    )
    version = encodage.empreinte("m5.mesures.v1", mesures)[:16]
    dernieres = list(ctx["etat_ops"]["par_type"]["op_mesures_constatees"].values())
    if dernieres and (dernieres[-1]["date_reference"], dernieres[-1]["version_donnees"]) == (aujourd_hui, version):
        return {"deja_constate": True, "publie": False, "version_donnees": version, "mesures": mesures}, None
    sequence = len(dernieres) + 1
    corps = {"date_reference": aujourd_hui, "version_donnees": version, "sequence": sequence, "mesures": mesures}
    resultat, refus = operations_registre.ajouter_operation(
        ctx["ops"],
        ctx["etat_ops"],
        "op_mesures_constatees",
        f"mesures:{sequence}:{aujourd_hui}:{version}",
        corps,
        horodatage,
    )
    if refus is not None:
        return None, refus
    charge = {k: v for k, v in mesures.items()}
    charge["version_donnees"] = version
    evenements.publier(
        "m5.mesures_comptables_constatees",
        _o._DEPARTEMENT,
        charge,
        evenement_id=f"m5-mesures-{sequence}-{aujourd_hui}-{version}",
    )
    return {
        "deja_constate": False,
        "publie": True,
        "version_donnees": version,
        "sequence": sequence,
        "mesures": mesures,
    }, None


def constater_mesures_comptables(aujourd_hui: str, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    if not _date_valide(aujourd_hui):
        return refuse(_verdict("REJ-OPS-DATE-INVALIDE", f"aujourd_hui {aujourd_hui!r} : AAAA-MM-JJ exigé"))
    resultat, refus = _mesures_impl(ctx, aujourd_hui, horodatage)
    if refus is not None:
        return refuse(refus)
    return accepte({**resultat, "recu": _recu_ecriture(ctx["ops"])})


# ================================================================== constats pour M8 : dépense publicitaire, factures
def _depense_pub_impl(
    ctx: Mapping[str, Any], debut: Any, fin: Any, aujourd_hui: str, horodatage: str
) -> tuple[dict | None, dict | None]:
    """Constate ce que le grand livre a comptabilisé des relevés publicitaires de M7 pour `[debut, fin]` et le publie
    (`m5.depense_publicitaire_constatee`). Un constat par période et par version des données : le redire à l'identique
    ne
    publie rien ; une version nouvelle est un constat de plus (`sequence`), le consommateur retient le plus grand."""
    compte, refus = plan_comptable.compte_de_charge(
        ctx["plan"], po_id=None, categorie=charges_marketing_recues.CATEGORIE_CHARGE
    )
    if refus is not None:
        return None, refus
    mesure, raison = constats_pour_m8.depense_publicitaire_comptabilisee(ctx["etat_gl"], compte, debut, fin)
    if mesure is None:
        return None, _verdict("REJ-OPS-DATE-INVALIDE", f"période {debut!r} à {fin!r} : {raison}")
    version = constats_pour_m8.version_depense(mesure, debut, fin)
    existants = list(ctx["etat_ops"]["par_type"]["op_depense_pub_constatee"].values())
    memes = [c for c in existants if (c["periode_debut"], c["periode_fin"]) == (debut, fin)]
    resume = {
        "periode_debut": debut,
        "periode_fin": fin,
        "version_donnees": version,
        "comptabilise_cad": format(mesure["comptabilise"], "f"),
        "ecritures_definitives": mesure["ecritures_definitives"],
        "brouillons_en_attente": mesure["brouillons_en_attente"],
    }
    if memes and memes[-1]["version_donnees"] == version:
        return {"deja_constate": True, "publie": False, **resume}, None
    sequence = len(existants) + 1
    corps = {
        "periode_debut": debut,
        "periode_fin": fin,
        "date_reference": aujourd_hui,
        "version_donnees": version,
        "sequence": sequence,
    }
    resultat, refus = operations_registre.ajouter_operation(
        ctx["ops"],
        ctx["etat_ops"],
        "op_depense_pub_constatee",
        f"depense-pub:{sequence}:{debut}:{fin}:{version}",
        corps,
        horodatage,
    )
    if refus is not None:
        return None, refus
    charge = constats_pour_m8.charge_depense_publicitaire(
        mesure, debut=debut, fin=fin, date_reference=aujourd_hui, sequence=sequence, version_donnees=version
    )
    evenements.publier(
        "m5.depense_publicitaire_constatee", _o._DEPARTEMENT, charge, evenement_id=charge["evenement_id"]
    )
    return {"deja_constate": False, "publie": True, "sequence": sequence, **resume}, None


def constater_depense_publicitaire(debut: str, fin: str, aujourd_hui: str, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    if not _date_valide(aujourd_hui):
        return refuse(_verdict("REJ-OPS-DATE-INVALIDE", f"aujourd_hui {aujourd_hui!r} : AAAA-MM-JJ exigé"))
    resultat, refus = _depense_pub_impl(ctx, debut, fin, aujourd_hui, horodatage)
    if refus is not None:
        return refuse(refus)
    return accepte({**resultat, "recu": _recu_ecriture(ctx["ops"])})


def _factures_emises_impl() -> dict[str, Any]:
    """Publie `m5.facture_emise_constatee` pour chaque facture client envoyée (ENVOYEE, PAYEE, ANNULEE après envoi) : un
    événement par (facture, statut), identifiant déterministe (un rejeu est un no-op du bus). Rien n'est écrit chez
    M5."""
    publiees = 0
    ignorees = 0
    for facture in _factures_clients_par_id().values():
        charge = constats_pour_m8.charge_facture_emise(facture)
        if charge is None:
            ignorees += 1
            continue
        evenements.publier("m5.facture_emise_constatee", _o._DEPARTEMENT, charge, evenement_id=charge["evenement_id"])
        publiees += 1
    return {"factures_publiees": publiees, "factures_non_emises_ignorees": ignorees}


def constater_factures_emises(horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    if not isinstance(horodatage, str) or not horodatage.strip():
        return refuse(_verdict("REJ-OPS-ENTREE-INVALIDE", "horodatage : ISO 8601 avec fuseau exigé"))
    return accepte({**_factures_emises_impl(), "recu": _recu_ecriture(ctx["ops"])})


# ====================================================================================================== le cycle
def executer_cycle_comptable(aujourd_hui: str, horodatage: str, periode: str | None) -> dict[str, Any]:
    """Enchaîne, jusqu'aux BROUILLONS seulement : brouillons d'écriture des factures, relances préparées, flux des
    factures fournisseurs (rapprochement publié pour M6), préclôture du mois demandé, mesures pour M8. Idempotent :
    rejoué à l'identique, il ne crée rien. Chaque étape dit son issue ; ce qui attend une PERSONNE est listé."""
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    if not _date_valide(aujourd_hui):
        return refuse(_verdict("REJ-OPS-DATE-INVALIDE", f"aujourd_hui {aujourd_hui!r} : AAAA-MM-JJ exigé"))
    etapes: list[dict[str, Any]] = []
    # 1. brouillons d'écriture des factures clients et fournisseurs (idempotent)
    brouillons = _o.generer_brouillons_comptables(horodatage, None)
    if brouillons.get("accepte") is False:
        etapes.append({"etape": "brouillons_d_ecriture", "issue": "REFUSEE", "code": brouillons["verdict"]["code"]})
    else:
        corps = brouillons["resultat"]
        etapes.append(
            {
                "etape": "brouillons_d_ecriture",
                "issue": "FAIT",
                "crees": len(corps["brouillons_crees"]),
                "deja": corps["deja_proposes"],
                "ignorees": len(corps["sources_ignorees"]) + len(corps["refuses"]),
                "reste": corps["reste"],
            }
        )
    # 2. relances
    ctx = contexte_operations()[0] or ctx
    resultat, refus = _relances_impl(ctx, aujourd_hui, horodatage)
    if refus is not None:
        issue = "A_DECLARER" if refus["code"] == "REJ-OPS-CONFIGURATION-A-DECLARER" else "REFUSEE"
        etapes.append(
            {"etape": "relances_de_creances", "issue": issue, "code": refus["code"], "detail": refus["detail"][:200]}
        )
    else:
        etapes.append(
            {
                "etape": "relances_de_creances",
                "issue": "FAIT",
                "crees": len(resultat["creees"]),
                "deja": resultat["deja"],
                "sans_retard": resultat["sans_retard"],
            }
        )
    # 3. flux des factures fournisseurs
    ctx = contexte_operations()[0] or ctx
    publies = 0
    sans_paiement_prepare = 0
    factures_vivantes = comptes_a_payer.factures_saisies(_o._registre_comptes_a_payer())
    for facture in factures_vivantes:
        ctx = contexte_operations()[0] or ctx
        flux, refus = _avancer_impl(ctx, facture, horodatage, aujourd_hui)
        if refus is not None:
            etapes.append(
                {
                    "etape": "flux_fournisseur",
                    "issue": "REFUSEE",
                    "code": refus["code"],
                    "facture": facture["facture_fournisseur_id"],
                }
            )
            break
        publies += flux["evenement"]
        sans_paiement_prepare += all(
            e["etat"] == "ABSENT" for e in flux["flux"]["etapes"] if e["etape"] == "paiement_prepare"
        )
    else:
        etapes.append(
            {
                "etape": "flux_fournisseur",
                "issue": "FAIT",
                "factures": len(factures_vivantes),
                "rapprochements_publies": publies,
            }
        )
    # 4. préclôture
    ctx = contexte_operations()[0] or ctx
    if periode is not None:
        resultat, refus = _precloture_impl(ctx, periode, horodatage)
        if refus is not None:
            etapes.append({"etape": "precloture", "issue": "REFUSEE", "code": refus["code"], "periode": periode})
        else:
            etapes.append(
                {
                    "etape": "precloture",
                    "issue": "FAIT",
                    "periode": periode,
                    "statut": resultat["statut"],
                    "bloquants": resultat["bloquants"],
                    "a_verifier": resultat["a_verifier"],
                }
            )
    else:
        etapes.append({"etape": "precloture", "issue": "NON_DEMANDEE"})
    # 5. mesures pour M8
    ctx = contexte_operations()[0] or ctx
    resultat, refus = _mesures_impl(ctx, aujourd_hui, horodatage)
    if refus is not None:
        etapes.append({"etape": "mesures_pour_m8", "issue": "REFUSEE", "code": refus["code"]})
    else:
        etapes.append(
            {
                "etape": "mesures_pour_m8",
                "issue": "FAIT",
                "publie": resultat["publie"],
                "deja_constate": resultat["deja_constate"],
            }
        )
    # 6. factures émises et dépense publicitaire comptabilisée du mois, pour M8 (constats, rien n'est validé ni envoyé)
    ctx = contexte_operations()[0] or ctx
    etapes.append({"etape": "factures_emises_pour_m8", "issue": "FAIT", **_factures_emises_impl()})
    debut_mois = aujourd_hui[:8] + "01"
    resultat, refus = _depense_pub_impl(ctx, debut_mois, aujourd_hui, aujourd_hui, horodatage)
    if refus is not None:
        issue = "A_DECLARER" if refus["code"] == "REJ-GL-CATEGORIE-SANS-COMPTE" else "REFUSEE"
        etapes.append({"etape": "depense_publicitaire_pour_m8", "issue": issue, "code": refus["code"]})
    else:
        etapes.append(
            {
                "etape": "depense_publicitaire_pour_m8",
                "issue": "FAIT",
                "publie": resultat["publie"],
                "deja_constate": resultat["deja_constate"],
            }
        )
    final = contexte_operations()[0] or ctx
    en_attente = {
        "brouillons_a_valider_n4": sum(1 for e in final["etat_gl"]["ecritures"].values() if e["statut"] == "BROUILLON"),
        "paiements_a_preparer_n3": sans_paiement_prepare,
        "relances_a_envoyer_via_m1": len(final["etat_ops"]["par_type"]["op_relance_preparee"]),
        "periode_a_clore_n4": None if periode is None else periode,
    }
    contradictions = constats.compter(stockage.maillons(_o._DEPARTEMENT, constats.REGISTRE))
    if contradictions:
        # Un relevé de M7 reçu deux fois avec le même (relevé, révision) mais un contenu différent : le premier état
        # (et son brouillon) restent, une personne tranche (registre constats_contradictoires). Absent quand il n'y en a
        # aucune : l'empreinte du cycle ne change pas pour qui n'en a pas.
        en_attente["constats_contradictoires_m7_a_examiner"] = contradictions
    empreinte = encodage.empreinte("m5.cycle.v1", etapes, en_attente)
    return accepte(
        {
            "date_reference": aujourd_hui,
            "etapes": etapes,
            "en_attente_d_une_personne": en_attente,
            "recu": {
                "empreinte": empreinte[:32],
                **_recu_ecriture(final["ops"]),
                "tete_grand_livre": final["gl"].tete(),
            },
            "garantie": (
                "jusqu'aux BROUILLONS : aucune écriture n'est définitive, aucune relance n'est envoyée, aucun "
                "paiement n'est fait, aucune période n'est close ; rejouer ce cycle ne crée rien de plus"
            ),
        }
    )


# ===================================================================================================== déclaration
def outils_operations() -> tuple[Outil, ...]:
    mention = " Sortie comptable : porte la mention « À valider auprès d'un comptable (CPA) / professionnel qualifié »."
    objet = {"type": "object", "additionalProperties": False}
    return (
        Outil(
            nom="m5_preparer_relances_clients",
            description=(
                "Prépare, pour chaque facture client ENVOYÉE en retard, le BROUILLON de la relance de son niveau "
                "courant "
                "(un seul niveau par facture), selon la politique de relance que le propriétaire a déclarée "
                "(configuration.operations.relances : délai d'échéance et paliers de retard ; absente, refus qui "
                "dit quoi "
                "déclarer). Rien n'est envoyé : l'envoi appartient à M1 sous approbation humaine. Idempotent par "
                "(facture, "
                "niveau) ; une facture soldée par des notes de crédit n'est pas relancée. Publie "
                "m5.creance_relance_preparee "
                "pour M2." + mention
            ),
            parametres={
                **objet,
                "properties": {"aujourd_hui": _DATE, "horodatage": _HORODATAGE},
                "required": ["aujourd_hui", "horodatage"],
            },
            fonction=preparer_relances_clients,
            autonomie=Autonomie.T1,
            niveau=Niveau.N1,
        ),
        Outil(
            nom="m5_proposer_note_credit",
            description=(
                "Propose une NOTE DE CRÉDIT (client ou fournisseur) sur une facture de M5 et son BROUILLON "
                "d'écriture : taxes "
                "recalculées avec les taux versionnés, la note qui solde la facture reprend exactement les taxes "
                "restantes, "
                "jamais plus que la facture ne permet de créditer, jamais avant la facture, jamais dans une "
                "période close. "
                "Idempotente par (genre, facture, référence). Sur une facture PAYÉE, le remboursement ou l'avoir "
                "au client est "
                "une décision humaine. Le brouillon attend m5_valider_ecriture_comptable (N4)." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "genre": {"type": "string", "enum": ["client", "fournisseur"]},
                    "facture_id": {"type": "string", "description": "facture_id (client) ou facture_fournisseur_id."},
                    "reference": {"type": "string", "description": "Numéro de la note (lettres, chiffres, . _ : / -)."},
                    "montant_avant_taxes": _MONTANT,
                    "date_effet": _DATE,
                    "motif": {"type": "string", "description": "Une ligne, 300 caractères au plus."},
                    "horodatage": _HORODATAGE,
                },
                "required": [
                    "genre",
                    "facture_id",
                    "reference",
                    "montant_avant_taxes",
                    "date_effet",
                    "motif",
                    "horodatage",
                ],
            },
            fonction=proposer_note_credit,
            autonomie=Autonomie.T1,
            niveau=Niveau.N1,
        ),
        Outil(
            nom="m5_proposer_depense_employe",
            description=(
                "Propose une DÉPENSE D'EMPLOYÉ à rembourser et son BROUILLON d'écriture : débit du compte de "
                "charge de sa "
                "catégorie (liste fermée du propriétaire), CTI et RTI recalculés aux taux versionnés, crédit du "
                "compte de "
                "remboursement des employés que le propriétaire a DÉSIGNÉ (configuration.operations."
                "compte_remboursement_employes ; absent, refus qui dit quoi déclarer). Le total du reçu doit "
                "égaler le total "
                "recalculé. employe_id est un identifiant, jamais un nom. Rien n'est remboursé ici." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "employe_id": {"type": "string"},
                    "reference": {"type": "string"},
                    "date_depense": _DATE,
                    "categorie": {"type": "string"},
                    "description": {"type": "string", "description": "120 caractères au plus."},
                    "montant_avant_taxes": _MONTANT,
                    "taxable": {"type": "boolean"},
                    "total_recu": {**_MONTANT, "description": "Le total (taxes comprises) imprimé sur le reçu."},
                    "horodatage": _HORODATAGE,
                },
                "required": [
                    "employe_id",
                    "reference",
                    "date_depense",
                    "categorie",
                    "description",
                    "montant_avant_taxes",
                    "taxable",
                    "total_recu",
                    "horodatage",
                ],
            },
            fonction=proposer_depense_employe,
            autonomie=Autonomie.T1,
            niveau=Niveau.N1,
        ),
        Outil(
            nom="m5_lier_piece_justificative",
            description=(
                "Lie une PIÈCE JUSTIFICATIVE (reçu, facture PDF, relevé) déposée par un humain dans le dossier confiné "
                "imports/pieces/ à une opération de M5 qui existe (facture, écriture, note de crédit, dépense "
                "d'employé, "
                "paiement préparé, rapprochement). L'empreinte SHA-256 et la taille sont calculées par le code. Le "
                "même "
                "fichier lié à une autre opération est signalé. Idempotent." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "cible_type": {"type": "string", "enum": list(operations_comptables.cibles_piece())},
                    "cible_id": {"type": "string"},
                    "fichier": {"type": "string", "description": "NOM du fichier déposé."},
                    "horodatage": _HORODATAGE,
                },
                "required": ["cible_type", "cible_id", "fichier", "horodatage"],
            },
            fonction=lier_piece_justificative,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_lire_flux_fournisseur",
            description=(
                "Où en est une facture fournisseur : facture reçue, appariement avec la commande de M6 "
                "(rapprochement PROPOSÉ), "
                "brouillon d'écriture, paiement préparé ; le paiement réel est hors d'OPSYS. Dit la prochaine "
                "action. Lecture "
                "pure." + mention
            ),
            parametres={
                **objet,
                "properties": {"facture_fournisseur_id": {"type": "string"}},
                "required": ["facture_fournisseur_id"],
            },
            fonction=lire_flux_fournisseur,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_avancer_flux_fournisseur",
            description=(
                "Fait avancer une facture fournisseur jusqu'au BROUILLON : génère le brouillon d'écriture "
                "(idempotent) et, "
                "pour une facture sur PO, publie le constat de rapprochement PO/réception/facture pour M6 "
                "(m5.rapprochement_po_constate, une fois par état). N'approuve ni ne paie rien." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "facture_fournisseur_id": {"type": "string"},
                    "aujourd_hui": _DATE,
                    "horodatage": _HORODATAGE,
                },
                "required": ["facture_fournisseur_id", "aujourd_hui", "horodatage"],
            },
            fonction=avancer_flux_fournisseur,
            autonomie=Autonomie.T1,
            niveau=Niveau.N1,
        ),
        Outil(
            nom="m5_preparer_paiement_fournisseur",
            description=(
                "PRÉPARE (jamais n'exécute) le paiement d'une facture fournisseur : une fiche (fournisseur, "
                "montant net des "
                "notes de crédit, date voulue, état du rapprochement PO) qu'une personne autorisée exécute HORS "
                "d'OPSYS "
                "(N5). N3 : l'appel attend la décision du propriétaire ou de la finance ; un agent seul est refusé "
                "(REJ-OPS-HUMAIN-REQUIS). Une facture sur PO dont le rapprochement n'est pas CONCORDANT est "
                "refusée, sauf "
                "dérogation motivée ; un seul paiement préparé par facture." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "facture_fournisseur_id": {"type": "string"},
                    "date_prevue": _DATE,
                    "derogation_motif": {
                        "type": ["string", "null"],
                        "description": "Seulement si le rapprochement n'est pas CONCORDANT : 10 caractères au moins.",
                    },
                    "horodatage": _HORODATAGE,
                },
                "required": ["facture_fournisseur_id", "date_prevue", "derogation_motif", "horodatage"],
            },
            fonction=preparer_paiement_fournisseur,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m5_consigner_jugement_comptable",
            description=(
                "Consigne un JUGEMENT ou une ESTIMATION comptable faite par une personne (provision, durée "
                "d'amortissement, "
                "créance douteuse) : sujet, description, hypothèses, base, montant déclaré. Alimente le dossier du "
                "CPA ; OPSYS "
                "ne le valide ni ne le calcule. N3 : propriétaire ou finance dans la file ; un agent seul est refusé."
                + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "genre": {"type": "string", "enum": ["jugement", "estimation"]},
                    "periode": _PERIODE,
                    "sujet": {"type": "string"},
                    "description": {"type": "string"},
                    "montant": {"type": ["string", "null"]},
                    "hypotheses": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
                    "base": {"type": "string"},
                    "horodatage": _HORODATAGE,
                },
                "required": ["genre", "periode", "sujet", "description", "montant", "hypotheses", "base", "horodatage"],
            },
            fonction=consigner_jugement_comptable,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m5_ouvrir_periode_comptable",
            description=(
                "Consigne l'OUVERTURE d'un mois : ses soldes d'ouverture (écritures définitives avant le 1er) et "
                "l'état de la "
                "période précédente (close ou non : soldes provisoires). Refuse un mois déjà clos. N'ouvre rien "
                "d'autre : une "
                "période n'est verrouillée que par sa clôture (N4)." + mention
            ),
            parametres={
                **objet,
                "properties": {"periode": _PERIODE, "horodatage": _HORODATAGE},
                "required": ["periode", "horodatage"],
            },
            fonction=ouvrir_periode_comptable,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_precloturer_periode_comptable",
            description=(
                "Liste de contrôle de PRÉCLÔTURE d'un mois : brouillons en attente, balance, factures sans écriture, "
                "rapprochement bancaire, pièces justificatives, TPS/TVQ, jugements, ouverture ; chacun OK, "
                "A_VERIFIER ou "
                "BLOQUANT, statut global BLOQUE, PRET_AVEC_RESERVES ou PRET_A_CLORE, avec reçu. Ne clôt RIEN : "
                "clore est "
                "m5_clore_periode_comptable (N4, une personne)." + mention
            ),
            parametres={
                **objet,
                "properties": {"periode": _PERIODE, "horodatage": _HORODATAGE},
                "required": ["periode", "horodatage"],
            },
            fonction=precloturer_periode_comptable,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_constater_mesures_comptables",
            description=(
                "Fait CONSTATER les mesures des opérations comptables du jour (créances par tranche d'âge, relances en "
                "brouillon, brouillons en attente, paiements préparés, rapprochements, notes de crédit, dépenses, "
                "pièces) et "
                "les publie au bus (m5.mesures_comptables_constatees) pour M8, qui les affiche sans les "
                "recalculer. Un constat "
                "par jour et par version des données." + mention
            ),
            parametres={
                **objet,
                "properties": {"aujourd_hui": _DATE, "horodatage": _HORODATAGE},
                "required": ["aujourd_hui", "horodatage"],
            },
            fonction=constater_mesures_comptables,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_constater_depense_publicitaire",
            description=(
                "Fait CONSTATER, pour une période (au plus 366 jours), ce que le grand livre a COMPTABILISÉ des "
                "relevés "
                "publicitaires de M7 : le solde net des écritures DÉFINITIVES qui viennent d'un relevé (l'origine et "
                "sa "
                "contre-passation s'annulent), et ce qui attend encore sa validation humaine (brouillons : nombre et "
                "montant). Publie au bus m5.depense_publicitaire_constatee pour M8, qui en tire l'écart avec la somme "
                "des "
                "relevés de M7. Que des nombres et des montants : aucun fournisseur, aucune pièce. Un constat par "
                "période "
                "et par version des données. Ne valide, n'envoie et ne paie rien." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "debut": _DATE,
                    "fin": _DATE,
                    "aujourd_hui": _DATE,
                    "horodatage": _HORODATAGE,
                },
                "required": ["debut", "fin", "aujourd_hui", "horodatage"],
            },
            fonction=constater_depense_publicitaire,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_constater_factures_emises",
            description=(
                "Fait CONSTATER les factures clients ÉMISES (envoyées par une personne : ENVOYEE, PAYEE, ANNULEE après "
                "envoi) et les publie au bus, une par état (m5.facture_emise_constatee), pour M8 : identifiant "
                "opaque, jour "
                "d'émission et montants en CAD, SANS client, chantier, devis ni ligne. Une facture brouillon n'est "
                "jamais "
                "publiée. Rejouer ne publie rien de plus. Ne crée, n'envoie et ne modifie aucune facture." + mention
            ),
            parametres={**objet, "properties": {"horodatage": _HORODATAGE}, "required": ["horodatage"]},
            fonction=constater_factures_emises,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_executer_cycle_comptable",
            description=(
                "Enchaîne les opérations comptables AUTONOMES jusqu'aux BROUILLONS : brouillons d'écriture des "
                "factures, relances "
                "préparées, flux des factures fournisseurs (rapprochement publié pour M6), préclôture du mois demandé "
                "(facultatif), mesures pour M8. Idempotent : rejoué, il ne crée rien. Liste ce qui attend une personne "
                "(validation N4, paiements à préparer N3, relances à envoyer, clôture N4). Aucune écriture "
                "définitive, aucun "
                "envoi, aucun paiement, aucune clôture." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "aujourd_hui": _DATE,
                    "horodatage": _HORODATAGE,
                    "periode": {"type": ["string", "null"], "pattern": "^[0-9]{4}-[0-9]{2}$"},
                },
                "required": ["aujourd_hui", "horodatage", "periode"],
            },
            fonction=executer_cycle_comptable,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
    )
