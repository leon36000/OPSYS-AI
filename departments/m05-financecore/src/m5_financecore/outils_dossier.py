"""Outils M5 du DOSSIER CPA (M5.6) : préparer et sceller le paquet d'une période ou d'une année, le vérifier ensuite.

Le contenu vient du module pur `dossier_cpa.py` (déterministe : mêmes registres, mêmes octets, même sceau). Cet
adaptateur l'alimente avec l'état des registres, écrit les fichiers dans le dossier CONFINÉ
`<OPSYS_HOME>/exports/dossier-cpa/ <dossier_id>/` (création exclusive, jamais d'écrasement, droits privés), consigne
le sceau au registre des opérations et publie `m5.dossier_cpa_scelle` (M10). Rien n'est envoyé : remettre le dossier
au CPA est un geste humain.

Ce que le dossier n'est pas : une compilation, un examen, un audit, une déclaration. La nature de la mission d'un
CPA et ce qu'on peut remettre à un tiers sont des questions juridiques et professionnelles que M5 ne tranche pas
(elles restent « A_FAIRE » dans la liste de contrôle). Portée d'appareil FERMÉE.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opsys import evenements, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import (
    base_fiscale,
    comptes_a_payer,
    dossier_cpa,
    operations_registre,
    verdicts_grand_livre,
    verdicts_operations,
)
from . import outils as _o
from .outils_operations import (
    _DATE,
    _HORODATAGE,
    _date_valide,
    _factures_clients_par_id,
    _recu_ecriture,
    accepte,
    contexte_operations,
    controle_taxes_bornes,
    refuse,
)

__all__ = ["outils_dossier"]

_ID_DOSSIER = r"^dos-[0-9a-f]{20}$"


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


def _racine_export() -> Path:
    return stockage.dossier_opsys() / "exports" / "dossier-cpa"


def _ecrire_dossier(dossier_id: str, fichiers: Mapping[str, bytes]) -> dict[str, str] | None:
    """Écrit les fichiers dans leur dossier confiné : création exclusive (`O_EXCL`), droits privés, aucun lien suivi. Un
    fichier déjà là doit avoir EXACTEMENT les mêmes octets (rejeu) ; sinon refus, jamais d'écrasement."""
    dossier = _racine_export() / dossier_id
    try:
        dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
        if dossier.is_symlink() or not dossier.is_dir():
            return _verdict("REJ-DOSSIER-EXPORT-IMPOSSIBLE", "le dossier d'export n'est pas un dossier ordinaire")
        for nom, octets in fichiers.items():
            chemin = dossier / nom
            try:
                descripteur = os.open(
                    chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
                )
            except FileExistsError:
                if chemin.is_symlink() or not chemin.is_file() or chemin.read_bytes() != octets:
                    return _verdict(
                        "REJ-DOSSIER-SCELLE-CONFLIT",
                        f"{nom} existe déjà avec un autre contenu : un dossier scellé ne s'écrase pas",
                    )
                continue
            with os.fdopen(descripteur, "wb") as flux:
                flux.write(octets)
    except OSError as exc:
        return _verdict("REJ-DOSSIER-EXPORT-IMPOSSIBLE", f"écriture impossible : {exc.strerror or exc}")
    return None


def _tete_hors_dossiers(maillons: list[Mapping[str, Any]]) -> str | None:
    """La tête du registre des opérations SANS compter les dossiers scellés : sceller un dossier ne change pas ce "
    "qu'il scelle."""
    for maillon in reversed(maillons):
        if maillon.get("type_entree") != "op_dossier_cpa_scelle":
            return maillon["ligne_id"]
    return None


def preparer_dossier_cpa(debut: str, fin: str, date_reference: str, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    if not _date_valide(fin) or not _date_valide(debut):
        return refuse(_verdict("REJ-DOSSIER-PERIODE-INVALIDE", "debut et fin AAAA-MM-JJ"))
    registre_factures, registre_ap = _o._registre_factures(None), _o._registre_comptes_a_payer()
    base, refus_base = base_fiscale.charger_base_par_defaut()
    maillons_ops = ctx["ops"].lire()
    tetes = {
        "grand_livre": ctx["gl"].tete(),
        "operations": _tete_hors_dossiers(maillons_ops),
        "factures": registre_factures.tete(),
        "comptes_a_payer": registre_ap.tete(),
    }
    controle = None
    if debut <= fin:
        try:
            controle, refus = controle_taxes_bornes(ctx, debut, fin)
        except comptes_a_payer.RegistreComptesIncoherent:
            return refuse(
                verdicts_grand_livre.construire_verdict(
                    "REJ-GL-SOURCE-ILLISIBLE", detail="registre comptes_a_payer incohérent; source illisible"
                )
            )
        if refus is not None:
            return refuse(refus)
    factures_clients = list(_factures_clients_par_id().values())
    try:
        factures_fournisseurs = comptes_a_payer.etats_toutes_les_factures(registre_ap)
    except comptes_a_payer.RegistreComptesIncoherent:
        return refuse(
            verdicts_grand_livre.construire_verdict(
                "REJ-GL-SOURCE-ILLISIBLE", detail="registre comptes_a_payer incohérent; source illisible"
            )
        )
    resultat, refus = dossier_cpa.construire_dossier(
        debut=debut,
        fin=fin,
        date_reference=date_reference,
        etat_gl=ctx["etat_gl"],
        plan=ctx["plan"],
        etat_ops=ctx["etat_ops"],
        factures_clients=factures_clients,
        factures_fournisseurs=factures_fournisseurs,
        controle_taxes=controle,
        resume_base_fiscale=None if refus_base is not None else base_fiscale.resume_base(base),
        tetes=tetes,
    )
    if refus is not None:
        return refuse(refus)
    manifeste = resultat["manifeste"]
    cle = f"dossier:{debut}:{fin}:{resultat['scelle'][:16]}"
    refus = _ecrire_dossier(operations_registre.identifiant("op_dossier_cpa_scelle", cle), resultat["fichiers"])
    if refus is not None:
        return refuse(refus)
    corps = {
        "periode_debut": debut,
        "periode_fin": fin,
        "scelle": resultat["scelle"],
        "manifeste": manifeste,
        "chemin_relatif": "exports/dossier-cpa/" + operations_registre.identifiant("op_dossier_cpa_scelle", cle),
        "resume": resultat["resume"],
    }
    enregistre, refus = operations_registre.ajouter_operation(
        ctx["ops"], ctx["etat_ops"], "op_dossier_cpa_scelle", cle, corps, horodatage
    )
    if refus is not None:
        return refuse(refus)
    dossier_id = enregistre["operation"]["dossier_id"]
    publie = False
    if enregistre["statut"] == "ecrite":
        evenements.publier(
            "m5.dossier_cpa_scelle",
            _o._DEPARTEMENT,
            {
                "dossier_id": dossier_id,
                "periode_debut": debut,
                "periode_fin": fin,
                "scelle": resultat["scelle"],
                "fichiers": len(manifeste["fichiers"]),
                "liste_de_controle": resultat["resume"],
                "statut": "BROUILLON_POUR_CPA",
                "date_reference": date_reference,
            },
            evenement_id=f"m5-dossier-{dossier_id}",
        )
        publie = True
    return accepte(
        {
            "dossier_id": dossier_id,
            "statut": "deja_scelle" if enregistre["statut"] == "deja" else "scelle",
            "periode": {"debut": debut, "fin": fin},
            "scelle": resultat["scelle"],
            "chemin": corps["chemin_relatif"],
            "fichiers": [
                {"nom": f["nom"], "octets": f["octets"], "sha256": f["sha256"][:16]} for f in manifeste["fichiers"]
            ],
            "liste_de_controle": {
                "resume": resultat["resume"],
                "points": [{"id": i["id"], "statut": i["statut"]} for i in resultat["liste_de_controle"]],
            },
            "evenement_publie": publie,
            "recu": _recu_ecriture(ctx["ops"]),
            "nature": (
                "BROUILLON POUR LE CPA : ni compilation, ni examen, ni audit, ni déclaration ; la mission et "
                "l'attestation d'un CPA sont hors d'OPSYS, et ce qu'on peut remettre à un tiers est une question "
                "juridique que M5 ne tranche pas"
            ),
            "a_faire": (
                "faire relire la liste de contrôle (A_FAIRE, A_VERIFIER) puis remettre le dossier au CPA ; remettre "
                "est un geste humain"
            ),
        }
    )


def verifier_dossier_cpa(dossier_id: str) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    dossier = ctx["etat_ops"]["par_type"]["op_dossier_cpa_scelle"].get(dossier_id)
    if dossier is None:
        return refuse(_verdict("REJ-DOSSIER-INTROUVABLE", f"dossier {dossier_id!r} inconnu du registre"))
    manifeste = dossier["manifeste"]
    racine = _racine_export() / dossier_id
    contenus: dict[str, bytes] = {}
    for f in manifeste["fichiers"]:
        chemin = racine / f["nom"]
        try:
            if chemin.is_symlink() or not stat.S_ISREG(chemin.lstat().st_mode):
                continue
            contenus[f["nom"]] = chemin.read_bytes()
        except OSError:
            continue
    constat = dossier_cpa.verifier_fichiers(manifeste, contenus)
    canonique = (json.dumps(manifeste, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        manifeste_disque = (racine / "MANIFESTE.json").read_bytes()
    except OSError:
        manifeste_disque = None
    constat["manifeste_identique"] = manifeste_disque == canonique
    constat["scelle_au_registre"] = dossier["scelle"]
    if not constat["conforme"] or not constat["manifeste_identique"]:
        return refuse(
            _verdict(
                "REJ-DOSSIER-ALTERE",
                f"fichiers altérés : {constat['alteres']} ; manquants : {constat['manquants']} ; inattendus : "
                f"{constat['inattendus']} ; manifeste identique : {constat['manifeste_identique']}",
            )
        )
    return accepte(
        {
            "dossier_id": dossier_id,
            **constat,
            "periode": {"debut": dossier["periode_debut"], "fin": dossier["periode_fin"]},
            "verification": "les octets du disque redonnent le sceau enregistré",
        }
    )


def outils_dossier() -> tuple[Outil, ...]:
    mention = " Sortie comptable : porte la mention « À valider auprès d'un comptable (CPA) / professionnel qualifié »."
    objet = {"type": "object", "additionalProperties": False}
    return (
        Outil(
            nom="m5_preparer_dossier_cpa",
            description=(
                "Prépare et SCELLE le dossier CPA d'une période (mois, trimestre ou année, 400 jours au plus) : "
                "balance de "
                "vérification, grand livre, soldes d'ouverture, brouillons en attente, états de rapprochement, "
                "relevés TPS/TVQ "
                "PRÉPARÉS (sans ligne de formulaire officiel), liste des pièces, jugements et estimations, journal des "
                "corrections, sous-comptes, export Beancount et liste de contrôle, en CSV/JSON déterministes dans "
                "un dossier "
                "confiné ; sceau SHA-256 qui couvre les fichiers et les têtes de registres. BROUILLON pour le CPA : ni "
                "compilation, ni examen, ni audit, ni déclaration ; la mission et l'attestation d'un CPA, et ce "
                "qu'on peut "
                "remettre à un tiers, sont hors d'OPSYS. Idempotent. Publie m5.dossier_cpa_scelle (M10)." + mention
            ),
            parametres={
                **objet,
                "properties": {"debut": _DATE, "fin": _DATE, "date_reference": _DATE, "horodatage": _HORODATAGE},
                "required": ["debut", "fin", "date_reference", "horodatage"],
            },
            fonction=preparer_dossier_cpa,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_verifier_dossier_cpa",
            description=(
                "Vérifie un dossier CPA scellé : relit les fichiers du disque, recalcule leurs empreintes et le "
                "sceau, les "
                "compare au registre. Altération, fichier manquant ou ajouté : REJ-DOSSIER-ALTERE. Lecture pure."
                + mention
            ),
            parametres={
                **objet,
                "properties": {"dossier_id": {"type": "string", "pattern": _ID_DOSSIER}},
                "required": ["dossier_id"],
            },
            fonction=verifier_dossier_cpa,
            autonomie=Autonomie.T0,
        ),
    )
