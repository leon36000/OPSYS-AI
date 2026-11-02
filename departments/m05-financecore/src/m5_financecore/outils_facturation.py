"""Outils M5 de la FACTURATION PAR JALONS, de la NUMÉROTATION et du PDF de facture (M5-FACT-1, M5-FACT-2).

Adaptateur (comme `outils_operations.py`) : il lit les aides d'`outils.py` (registres, taux, manifeste) et délègue tout
calcul à `facturation_jalons.py` et `facture_pdf.py`. Il ne nomme jamais le registre des mouvements : facturer ne fait
bouger aucun argent (`conformite.verifier_aucun_decaissement`, strict).

Qui décide quoi.

* Déclarer ou révoquer un PLAN (`m5_etablir_plan_facturation`, `m5_revoquer_plan_facturation`) engage l'entreprise
  envers un client : N3, une PERSONNE identifiée par le socle (propriétaire ou finance), jamais un argument ni un agent
  seul. Les pourcentages ou montants sont ceux qu'elle déclare ; rien n'est inventé.
* Préparer la facture d'un jalon (`m5_creer_facture_jalon`) est une écriture interne non finale (BROUILLON, N1) : le
  montant vient du plan, les taxes du moteur fiscal.
* ÉMETTRE la facture reste `m5_envoyer_facture` (N4, décision humaine du socle, plafond d'envoi automatique : zéro) :
  c'est
  là que le numéro et l'échéance sont fixés (`outils.envoyer_facture`). Payer reste `m5_enregistrer_paiement_facture`
  (N5).
* Les PDF (`m5_preparer_pdf_facture`, `m5_preparer_etat_compte_client`) sont des documents PRÉPARÉS : N1, rien n'est
  envoyé ; ils ne rendent que ce que le code a déjà calculé.

Portée d'appareil FERMÉE pour tous (`roles_appareil` vide), refusée dans le code (`REJ-IDENTITE-APPAREIL-INVALIDE`).
Toute
sortie porte la mention d'analyse ET la mention comptable (« À valider auprès d'un comptable (CPA) / professionnel
qualifié »).
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import (
    clients_recus,
    devis_recus,
    encodage,
    facturation,
    facturation_jalons,
    facture_pdf,
    operations_comptables,
    operations_registre,
    verdicts_facturation,
    wct_recus,
)
from . import outils as _o
from .outils_operations import _HORODATAGE, _appareil_refuse, accepte, humain_requis, refuse

__all__ = ["outils_facturation"]

_DATE = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "description": "Date AAAA-MM-JJ."}
_LANGUE = {
    "type": "string",
    "enum": ["fr", "bilingue"],
    "description": "fr (français) ou bilingue (français et anglais sur chaque étiquette).",
}
_DESTINATAIRE = {
    "type": "object",
    "properties": {
        "nom": {"type": "string", "description": "Nom du client, tel qu'il doit apparaître (M5 ne le garde pas)."},
        "adresse": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
    },
    "required": ["nom", "adresse"],
    "additionalProperties": False,
}


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_facturation.construire_verdict(code, detail=detail)


def _horodatage_refus(horodatage: Any) -> dict[str, str] | None:
    try:
        instant = datetime.fromisoformat(horodatage) if isinstance(horodatage, str) else None
    except ValueError:
        instant = None
    if instant is None or instant.tzinfo is None:
        return _verdict("REJ-FACTURATION-DATE-INVALIDE", "horodatage ISO 8601 avec fuseau requis")
    return None


def _jour(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or len(valeur) != 10:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def _declaration() -> Mapping[str, Any]:
    brut = _o._configuration_manifeste().get("facturation")
    return brut if isinstance(brut, Mapping) else {}


def contexte_facturation() -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Ce dont un outil de facturation a besoin, relu à chaque appel : registres des plans, des factures, de la
    numérotation et des scellés, leur état — ou le refus nommé (appareil, stockage non durable, chaîne invalide)."""
    refus = _appareil_refuse()
    if refus is not None:
        return None, refus
    plans = _o._registre_plans()
    if plans is None:
        return None, _verdict("REJ-PLAN-STOCKAGE-NON-DURABLE", "registres durables de la facturation requis")
    factures = _o._registre_factures(None)
    numeros = _o._registre_numerotation()
    documents = _o._registre_documents()
    for nom, registre in (("plans", plans), ("factures", factures), ("numérotation", numeros), ("scellés", documents)):
        valide, raison = _o.registre_module.Registre(maillons=registre.lire()).valider_chaine()
        if not valide:
            return None, _verdict("REJ-PLAN-CHAINE-INVALIDE", f"registre des {nom} altéré : {raison}")
    etat_des_plans = facturation_jalons.etat_plans(plans.lire())
    refus = facturation_jalons.refus_anomalies(etat_des_plans)
    if refus is not None:
        return None, refus
    return {
        "plans": plans,
        "etat_plans": etat_des_plans,
        "factures": factures,
        "etats_factures": facturation.etats_des_factures(factures),
        "numeros": numeros,
        "documents": documents,
    }, None


def _ecrire(durable: Any, registre_copie: Any, taille_avant: int) -> None:
    """Pousse au registre durable les maillons ajoutés à la COPIE, un à un, chacun avec la précondition de rang : deux
    écrivains qui ont lu le même état ne se superposent jamais (`EcritureConcurrente`, la transaction est annulée)."""
    maillons = registre_copie.lire()
    for decalage, maillon in enumerate(maillons[taille_avant:]):
        durable.append(maillon, rang_attendu=taille_avant + decalage)


def _copie(registre: Any) -> Any:
    return _o.registre_module.Registre(maillons=registre.lire())


# ================================================================================================ plan de facturation
def etablir_plan_facturation(
    devis_id: str, jalons: list[dict[str, Any]], chantier_id: str | None, horodatage: str
) -> dict[str, Any]:
    ctx, refus = contexte_facturation()
    if refus is not None:
        return refuse(refus)
    humain, refus = humain_requis("m5_etablir_plan_facturation", "déclarer un plan de facturation par jalons")
    if refus is not None:
        return refuse(refus)
    refus = _horodatage_refus(horodatage)
    if refus is not None:
        return refuse(refus)
    if not isinstance(devis_id, str) or not devis_id.strip():
        return refuse(_verdict("REJ-PLAN-ENTREE-INVALIDE", "devis_id requis"))
    devis_recu = devis_recus.pour_devis_id(devis_id, stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_DEVIS_RECUS))
    if devis_recu is None:
        return refuse(
            _verdict(
                "REJ-PLAN-DEVIS-INCONNU",
                f"aucun devis accepté reçu pour {devis_id!r} : attendre m3.devis_accepte (un plan se déclare sur un "
                "devis ACCEPTÉ)",
            )
        )
    if any(
        e.get("devis_id") == devis_id and e.get("statut") != "ANNULEE" and e.get("plan_id") is None
        for e in ctx["etats_factures"]
    ):
        return refuse(
            _verdict(
                "REJ-PLAN-DEVIS-DEJA-FACTURE",
                "ce devis est déjà facturé en bloc : un plan par jalons n'est plus possible (déclarer le plan AVANT la "
                "fin des travaux)",
            )
        )
    declaration = _declaration()
    conditions, refus_conditions = facturation_jalons.lire_conditions_paiement(declaration.get("conditions_paiement"))
    if conditions is None and "conditions_paiement" in declaration:
        return refuse(refus_conditions)
    client = clients_recus.pour_lead_id(
        devis_recu["lead_id"], stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_CLIENTS_RECUS)
    )
    client_id = client["client_id"] if client is not None else devis_recu["lead_id"]
    version = len(ctx["etat_plans"]["par_devis"].get(devis_id, ())) + 1
    corps, refus = facturation_jalons.construire_plan(
        devis_recu,
        jalons,
        chantier_declare=chantier_id,
        client_id=client_id,
        version=version,
        delai_defaut=conditions["delai_jours"] if conditions is not None else None,
        humain=humain,
    )
    if refus is not None:
        return refuse(refus)
    copie = _copie(ctx["plans"])
    taille = copie.taille()
    resultat, refus = facturation_jalons.ajouter_plan(copie, ctx["etat_plans"], corps, horodatage)
    if refus is not None:
        return refuse(refus)
    if resultat["statut"] == "ecrit":
        _ecrire(stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_PLANS), copie, taille)
    plan = resultat["plan"]
    return accepte(
        {
            "statut": resultat["statut"],
            "plan_id": plan["plan_id"],
            "devis_id": devis_id,
            "mode": plan["mode"],
            "total_avant_taxes": plan["total_avant_taxes"],
            "jalons": [{k: j[k] for k in j if k != "jalon_id"} for j in plan["jalons"]],
            "declare_par": plan["declare_par"],
            "a_faire": (
                "créer la facture BROUILLON de chaque jalon (m5_creer_facture_jalon), dans l'ordre ; l'émission de "
                "chacune reste une décision humaine (m5_envoyer_facture, N4)"
            ),
        }
    )


def revoquer_plan_facturation(plan_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_facturation()
    if refus is not None:
        return refuse(refus)
    humain, refus = humain_requis("m5_revoquer_plan_facturation", "révoquer un plan de facturation par jalons")
    if refus is not None:
        return refuse(refus)
    refus = _horodatage_refus(horodatage)
    if refus is not None:
        return refuse(refus)
    copie = _copie(ctx["plans"])
    taille = copie.taille()
    resultat, refus = facturation_jalons.revoquer_plan(
        copie, ctx["etat_plans"], plan_id, motif, humain, ctx["etats_factures"], horodatage
    )
    if refus is not None:
        return refuse(refus)
    _ecrire(stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_PLANS), copie, taille)
    return accepte({**resultat, "revoque_par": humain["par"]})


def creer_facture_jalon(devis_id: str, rang: int, horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_facturation()
    if refus is not None:
        return refuse(refus)
    refus = _horodatage_refus(horodatage)
    if refus is not None:
        return refuse(refus)
    plan = facturation_jalons.plan_actif_pour_devis(ctx["etat_plans"], devis_id) if isinstance(devis_id, str) else None
    if plan is None:
        return refuse(
            _verdict(
                "REJ-PLAN-INTROUVABLE",
                f"aucun plan de facturation actif pour {devis_id!r} : "
                "le déclarer d'abord (m5_etablir_plan_facturation)",
            )
        )
    travaux_termines = (
        wct_recus.pour_devis_id(devis_id, stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_WCT_RECUS)) is not None
    )
    preparation, refus = facturation_jalons.preparer_facture_jalon(
        plan, rang, ctx["etats_factures"], travaux_termines=travaux_termines
    )
    if refus is not None:
        return refuse(refus)
    existante = next((e for e in ctx["etats_factures"] if e["facture_id"] == preparation["facture_id"]), None)
    if existante is not None:
        return accepte({"statut": "deja", "facture": _vue_facture(existante)})
    dictionnaire, refus = _o._dictionnaire_taux()
    if refus is not None:
        return refuse(refus)
    copie = _copie(ctx["factures"])
    taille = copie.taille()
    maillon, verdict = facturation.creer_facture_brouillon(
        facture_id=preparation["facture_id"],
        chantier_id=plan["chantier_id"],
        devis_id=devis_id,
        client_id=plan["client_id"],
        lignes=preparation["lignes"],
        horodatage=horodatage,
        dictionnaire_taux=dictionnaire,
        registre_cible=copie,
        montant_avant_taxes_fourni=preparation["lignes"][0]["prix_unitaire"],
        rattachement_plan=preparation["rattachement"],
    )
    if verdict is not None:
        return refuse(verdict)
    _ecrire(stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_FACTURES), copie, taille)
    return accepte(
        {
            "statut": "creee",
            "facture": _vue_facture(maillon),
            "a_faire": (
                "la facture est un BROUILLON : l'émettre (numéro et échéance fixés alors) est une décision humaine "
                "(m5_envoyer_facture, N4) ; rien n'est envoyé"
            ),
        }
    )


def _vue_facture(etat: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "facture_id": etat["facture_id"],
        "statut": etat["statut"],
        "plan_id": etat.get("plan_id"),
        "jalon_rang": etat.get("jalon_rang"),
        "libelle_jalon": etat.get("libelle_jalon"),
        "montant_avant_taxes": etat["montant_avant_taxes"],
        "taxes": [
            {"id": t["id"], "version": t["version"], "taux": t["taux"], "montant": t["montant"]} for t in etat["taxes"]
        ],
        "total_taxes": etat["total_taxes"],
        "montant_apres_taxes": etat["montant_apres_taxes"],
        "numero_facture": etat.get("numero_facture"),
        "echeance": etat.get("echeance"),
    }


def _a_declarer(taxes_presentes: tuple[str, ...] = ("tps_federale", "tvq_quebec")) -> list[dict[str, str]]:
    """Ce que le propriétaire n'a pas (bien) déclaré et qui bloquera l'émission ou le PDF : une liste, jamais un "
    "défaut."""
    declaration = _declaration()
    manques: list[dict[str, str]] = []
    _num, refus = facturation_jalons.lire_numerotation(declaration.get("numerotation"))
    if refus is not None:
        manques.append({"declaration": "configuration.facturation.numerotation", "code": refus["code"]})
    _cond, refus = facturation_jalons.lire_conditions_paiement(declaration.get("conditions_paiement"))
    if refus is not None:
        manques.append({"declaration": "configuration.facturation.conditions_paiement", "code": refus["code"]})
    _ent, refus = facture_pdf.lire_entreprise(declaration.get("entreprise"), taxes_presentes)
    if refus is not None:
        manques.append(
            {"declaration": "configuration.facturation.entreprise", "code": refus["code"], "detail": refus["detail"]}
        )
    return manques


def lire_plan_facturation(devis_id: str, aujourd_hui: str | None = None) -> dict[str, Any]:
    ctx, refus = contexte_facturation()
    if refus is not None:
        return refuse(refus)
    jour = None
    if aujourd_hui is not None:
        jour = _jour(aujourd_hui)
        if jour is None:
            return refuse(_verdict("REJ-FACTURATION-DATE-INVALIDE", f"aujourd_hui {aujourd_hui!r} : AAAA-MM-JJ exigé"))
    plan = facturation_jalons.plan_actif_pour_devis(ctx["etat_plans"], devis_id) if isinstance(devis_id, str) else None
    if plan is None:
        return refuse(_verdict("REJ-PLAN-INTROUVABLE", f"aucun plan de facturation actif pour {devis_id!r}"))
    dictionnaire, refus = _o._dictionnaire_taux()
    if refus is not None:
        return refuse(refus)
    resume, refus = facturation_jalons.resume_plan(plan, ctx["etats_factures"], dictionnaire, jour)
    if refus is not None:
        return refuse(refus)
    return accepte({**resume, "a_declarer": _a_declarer(), "retard_calcule_au": aujourd_hui})


def verifier_numerotation_factures() -> dict[str, Any]:
    ctx, refus = contexte_facturation()
    if refus is not None:
        return refuse(refus)
    maillons = ctx["numeros"].lire()
    verification = facturation_jalons.verifier_numerotation(maillons)
    numerotes = {e["facture_id"]: e["numero_facture"] for e in ctx["etats_factures"] if e.get("numero_facture")}
    au_registre = {m["facture_id"]: m["numero_facture"] for m in maillons if m.get("facture_id")}
    sans_registre = sorted(f for f, n in numerotes.items() if au_registre.get(f) != n)
    sans_facture_emise = sorted(f for f in au_registre if numerotes.get(f) != au_registre[f])
    return accepte(
        {
            **verification,
            "ok": verification["ok"] and not sans_registre and not sans_facture_emise,
            "factures_numerotees_hors_registre": sans_registre[:20],
            "numeros_sans_facture_emise": sans_facture_emise[:20],
            "tete_du_registre": ctx["numeros"].tete(),
        }
    )


# ============================================================================================================= PDF
_OCTETS_PDF_MAX = 5 * 1024 * 1024
_NOM_SUR = re.compile(r"[^A-Za-z0-9._-]")


def _racine_export() -> Path:
    return stockage.dossier_opsys() / "exports" / "factures"


def _ecrire_pdf(nom: str, octets: bytes) -> dict[str, str] | None:
    """Écrit le PDF dans son dossier confiné (`<OPSYS_HOME>/exports/factures/`) : création exclusive (`O_EXCL`), droits
    privés, aucun lien suivi. Un fichier déjà là doit avoir EXACTEMENT les mêmes octets (rejeu) ; sinon refus, jamais
    d'écrasement. Les octets ne passent jamais par le modèle : l'outil rend le chemin, la taille et l'empreinte."""
    if len(octets) > _OCTETS_PDF_MAX:
        return _verdict("REJ-PDF-TROP-VOLUMINEUX", f"le PDF ({len(octets)} octets) dépasse {_OCTETS_PDF_MAX} octets")
    dossier = _racine_export()
    try:
        dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
        if dossier.is_symlink() or not dossier.is_dir():
            return _verdict("REJ-PDF-EXPORT-IMPOSSIBLE", "le dossier d'export n'est pas un dossier ordinaire")
        chemin = dossier / nom
        try:
            descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            if chemin.is_symlink() or not chemin.is_file() or chemin.read_bytes() != octets:
                return _verdict(
                    "REJ-PDF-FICHIER-CONFLIT", f"{nom} existe déjà avec un autre contenu : rien n'est écrasé"
                )
            return None
        with os.fdopen(descripteur, "wb") as flux:
            flux.write(octets)
    except OSError as exc:
        return _verdict("REJ-PDF-EXPORT-IMPOSSIBLE", f"écriture impossible : {exc.strerror or exc}")
    return None


def _sortie_pdf(
    octets: bytes, nom: str, scelle: Mapping[str, Any], resume: Mapping[str, Any], statut: str
) -> dict[str, Any]:
    erreur = _ecrire_pdf(nom, octets)
    if erreur is not None:
        return refuse(erreur)
    return accepte(
        {
            "type_mime": facture_pdf.TYPE_MIME,
            "fichier": {"chemin_relatif": f"exports/factures/{nom}", "taille_octets": len(octets)},
            "sha256": scelle["empreinte_pdf"],
            "empreinte_contenu": scelle["empreinte_contenu"],
            "scelle": {
                "statut": statut,
                "scelle_id": scelle["scelle_id"],
                "gabarit": scelle["gabarit"],
                "version_brique": scelle["version_brique"],
            },
            "resume": dict(resume),
            "envoi": "aucun : le PDF est PRÉPARÉ ; l'envoyer au client est une décision humaine",
        }
    )


def preparer_pdf_facture(facture_id: str, langue: str, destinataire: dict[str, Any], horodatage: str) -> dict[str, Any]:
    ctx, refus = contexte_facturation()
    if refus is not None:
        return refuse(refus)
    refus = _horodatage_refus(horodatage)
    if refus is not None:
        return refuse(refus)
    etat = next((e for e in ctx["etats_factures"] if e["facture_id"] == facture_id), None)
    if etat is None:
        return refuse(_verdict("REJ-PDF-FACTURE-INTROUVABLE", f"facture inconnue : {facture_id!r}"))
    plan = None
    if etat.get("plan_id") is not None:
        plan = ctx["etat_plans"]["plans"].get(etat["plan_id"])
    contenu, refus = facture_pdf.contenu_facture(etat, plan, _declaration().get("entreprise"), destinataire, langue)
    if refus is not None:
        return refuse(refus)
    octets, refus = facture_pdf.rendre(contenu)
    if refus is not None:
        return refuse(refus)
    empreinte_pdf = hashlib.sha256(octets).hexdigest()
    empreinte_destinataire = encodage.empreinte("m5.facture_pdf.destinataire", contenu["destinataire"])[:32]
    corps = {
        "facture_id": facture_id,
        "numero_facture": etat["numero_facture"],
        "plan_id": etat.get("plan_id"),
        "langue": langue,
        "gabarit": facture_pdf.VERSION_GABARIT,
        "version_brique": facture_pdf.VERSION_BRIQUE,
        "empreinte_contenu": facture_pdf.empreinte_contenu(contenu),
        "empreinte_destinataire": empreinte_destinataire,
        "taille_octets": len(octets),
    }
    copie = _copie(ctx["documents"])
    taille = copie.taille()
    resultat, refus = facture_pdf.sceller(
        copie,
        type_entree="facture_pdf_scellee",
        cle=f"{facture_id}|{langue}|{empreinte_destinataire}",
        corps=corps,
        empreinte_pdf=empreinte_pdf,
        strict=True,
        horodatage=horodatage,
    )
    if refus is not None:
        return refuse(refus)
    nom = f"facture-{_NOM_SUR.sub('_', etat['numero_facture'])}-{langue}-{empreinte_pdf[:12]}.pdf"
    resume = {
        "numero_facture": etat["numero_facture"],
        "sous_total": contenu["sous_total"],
        "total": contenu["total"],
        "echeance": contenu["echeance"],
        "langue": langue,
    }
    sortie = _sortie_pdf(octets, nom, resultat["scelle"], resume, resultat["statut"])
    if sortie["accepte"] and resultat["statut"] == "nouveau":
        _ecrire(stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_DOCUMENTS), copie, taille)
    return sortie


def preparer_etat_compte_client(
    client_id: str, au: str, langue: str, destinataire: dict[str, Any], horodatage: str
) -> dict[str, Any]:
    ctx, refus = contexte_facturation()
    if refus is not None:
        return refuse(refus)
    refus = _horodatage_refus(horodatage)
    if refus is not None:
        return refuse(refus)
    jour = _jour(au)
    if jour is None:
        return refuse(_verdict("REJ-FACTURATION-DATE-INVALIDE", f"au {au!r} : AAAA-MM-JJ exigé"))
    if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 128:
        return refuse(_verdict("REJ-PDF-CLIENT-INVALIDE", "client_id requis (identifiant opaque du client)"))
    registre_ops = _o._registre_operations()
    etat_ops = operations_registre.etat_operations(registre_ops.lire() if registre_ops is not None else [])
    refus = operations_registre.refus_anomalies(etat_ops)
    if refus is not None:
        return refuse(refus)
    contenu, refus = facture_pdf.contenu_etat_compte(
        client_id,
        ctx["etats_factures"],
        operations_comptables.credits_ttc_par_facture(etat_ops, "client"),
        jour,
        _declaration().get("entreprise"),
        destinataire,
        langue,
        horodatage,
    )
    if refus is not None:
        return refuse(refus)
    octets, refus = facture_pdf.rendre(contenu)
    if refus is not None:
        return refuse(refus)
    empreinte_pdf = hashlib.sha256(octets).hexdigest()
    empreinte_contenu = facture_pdf.empreinte_contenu(contenu)
    corps = {
        "client_id": client_id,
        "au": jour.isoformat(),
        "langue": langue,
        "gabarit": facture_pdf.VERSION_GABARIT,
        "version_brique": facture_pdf.VERSION_BRIQUE,
        "empreinte_contenu": empreinte_contenu,
        "taille_octets": len(octets),
        "nombre_de_factures": len(contenu["lignes"]),
    }
    copie = _copie(ctx["documents"])
    taille = copie.taille()
    resultat, refus = facture_pdf.sceller(
        copie,
        type_entree="etat_compte_pdf_scelle",
        cle=f"{client_id}|{jour.isoformat()}|{langue}|{empreinte_contenu}",
        corps=corps,
        empreinte_pdf=empreinte_pdf,
        strict=False,
        horodatage=horodatage,
    )
    if refus is not None:
        return refuse(refus)
    nom = f"etat-compte-{jour.isoformat()}-{langue}-{empreinte_pdf[:12]}.pdf"
    resume = {
        "au": jour.isoformat(),
        "nombre_de_factures": len(contenu["lignes"]),
        "totaux": contenu["totaux"],
        "langue": langue,
    }
    sortie = _sortie_pdf(octets, nom, resultat["scelle"], resume, resultat["statut"])
    if sortie["accepte"] and resultat["statut"] == "nouveau":
        _ecrire(stockage.maillons(_o._DEPARTEMENT, _o._NOM_REGISTRE_DOCUMENTS), copie, taille)
    return sortie


# ======================================================================================================== déclaration
def outils_facturation() -> tuple[Outil, ...]:
    mention = " Sortie comptable : porte la mention « À valider auprès d'un comptable (CPA) / professionnel qualifié »."
    objet = {"type": "object", "additionalProperties": False}
    return (
        Outil(
            nom="m5_etablir_plan_facturation",
            description=(
                "DÉCLARE le plan de facturation par jalons d'un devis ACCEPTÉ (acompte à l'acceptation, jalons de "
                "chantier, solde à la fin des travaux), avec les pourcentages OU les montants avant taxes que la "
                "personne déclare : la somme doit tomber juste au cent (pourcentages : 100, le solde absorbe "
                "l'arrondi). "
                "Jamais inventé : somme fausse, délai de paiement non déclaré (jalon ou "
                "configuration.facturation.conditions_paiement), chantier absent, devis déjà facturé en bloc = refus "
                "qui dit quoi corriger. N3 : l'appel attend la décision du propriétaire ou de la finance ; un agent "
                "seul est refusé (REJ-PLAN-HUMAIN-REQUIS). Idempotent : redéclarer le même plan ne crée rien." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "devis_id": {"type": "string"},
                    "jalons": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 12,
                        "items": {
                            "type": "object",
                            "properties": {
                                "libelle": {"type": "string", "description": "Une ligne, 80 caractères au plus."},
                                "declencheur": {"type": "string", "enum": ["acceptation", "chantier", "fin_travaux"]},
                                "pourcentage": {"type": ["string", "null"], "description": 'Texte décimal, ex. "30".'},
                                "montant_avant_taxes": {
                                    "type": ["string", "null"],
                                    "description": 'Texte décimal au cent, ex. "1500.00".',
                                },
                                "delai_paiement_jours": {"type": ["integer", "null"], "minimum": 0, "maximum": 365},
                            },
                            "required": ["libelle", "declencheur"],
                            "additionalProperties": False,
                        },
                    },
                    "chantier_id": {
                        "type": ["string", "null"],
                        "description": "Seulement si le devis n'a pas encore de chantier ; jamais inventé.",
                    },
                    "horodatage": _HORODATAGE,
                },
                "required": ["devis_id", "jalons", "chantier_id", "horodatage"],
            },
            fonction=etablir_plan_facturation,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m5_revoquer_plan_facturation",
            description=(
                "RÉVOQUE un plan de facturation par jalons, seulement tant qu'AUCUNE facture (pas même un "
                "brouillon) n'en "
                "est issue ; motif obligatoire. N3 : décision du propriétaire ou de la finance, jamais d'un agent seul."
                + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "plan_id": {"type": "string"},
                    "motif": {"type": "string", "description": "Une ligne, 300 caractères au plus."},
                    "horodatage": _HORODATAGE,
                },
                "required": ["plan_id", "motif", "horodatage"],
            },
            fonction=revoquer_plan_facturation,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m5_creer_facture_jalon",
            description=(
                "Prépare la facture BROUILLON d'un jalon du plan actif du devis : montant du plan, TPS/TVQ du moteur "
                "fiscal (taux versionnés), jamais plus que le prix du devis, jalons dans l'ordre, jalon « fin des "
                "travaux » "
                "seulement après m4.travaux_termines. Idempotent par jalon. Écriture interne non finale (N1) : rien "
                "n'est "
                "numéroté ni envoyé ; l'émission est m5_envoyer_facture (N4, humain)." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "devis_id": {"type": "string"},
                    "rang": {"type": "integer", "minimum": 1, "maximum": 12},
                    "horodatage": _HORODATAGE,
                },
                "required": ["devis_id", "rang", "horodatage"],
            },
            fonction=creer_facture_jalon,
            autonomie=Autonomie.T1,
            niveau=Niveau.N1,
        ),
        Outil(
            nom="m5_lire_plan_facturation",
            description=(
                "Lit le plan de facturation actif d'un devis : chaque jalon avec sa facture (statut, numéro, échéance, "
                "retard calculé à aujourd_hui) ou « à facturer » (taxes calculées par le moteur fiscal), le "
                "facturé, le "
                "solde à facturer, l'écart d'arrondi des taxes, et la liste de ce que le propriétaire doit encore "
                "déclarer (numérotation, conditions de paiement, profil de l'entreprise). Lecture pure." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "devis_id": {"type": "string"},
                    "aujourd_hui": {"type": ["string", "null"], "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                },
                "required": ["devis_id"],
            },
            fonction=lire_plan_facturation,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_verifier_numerotation_factures",
            description=(
                "Relit la suite des numéros de facture : contiguë (aucun trou), sans doublon, chaque numéro "
                "attribué à une "
                "facture émise et chaque facture numérotée présente au registre. Dit chaque défaut. Lecture pure."
                + mention
            ),
            parametres={**objet, "properties": {}},
            fonction=verifier_numerotation_factures,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_preparer_pdf_facture",
            description=(
                "Prépare le PDF d'une facture APPROUVÉE (N4) et NUMÉROTÉE : même contenu que la facture, aucun chiffre "
                "recalculé ; raison sociale, adresse et numéros de TPS/TVQ viennent de "
                "configuration.facturation.entreprise "
                "(absents : refus qui dit quoi déclarer) ; le nom et l'adresse du client sont fournis à l'appel (M5 "
                "ne les "
                "garde pas). Français ou bilingue. Déterministe : mêmes entrées, mêmes octets ; l'empreinte SHA-256 "
                "est "
                "scellée au registre et se rejoue (REJ-PDF-SCELLE-DIFFERENT si elle changeait). Rien n'est envoyé."
                + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "facture_id": {"type": "string"},
                    "langue": _LANGUE,
                    "destinataire": _DESTINATAIRE,
                    "horodatage": _HORODATAGE,
                },
                "required": ["facture_id", "langue", "destinataire", "horodatage"],
            },
            fonction=preparer_pdf_facture,
            autonomie=Autonomie.T1,
            niveau=Niveau.N1,
        ),
        Outil(
            nom="m5_preparer_etat_compte_client",
            description=(
                "Prépare le PDF de l'ÉTAT DE COMPTE d'un client à une date : ses factures émises (envoyées ou payées), "
                "crédits des notes de crédit, payé, solde et retard calculés par le code à cette date (jamais "
                "devinée). "
                "Mêmes données déclarées et mêmes garanties que le PDF de facture (déterministe, scellé, rien "
                "d'envoyé)."
                + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "client_id": {
                        "type": "string",
                        "description": "Identifiant opaque du client (celui des factures).",
                    },
                    "au": _DATE,
                    "langue": _LANGUE,
                    "destinataire": _DESTINATAIRE,
                    "horodatage": _HORODATAGE,
                },
                "required": ["client_id", "au", "langue", "destinataire", "horodatage"],
            },
            fonction=preparer_etat_compte_client,
            autonomie=Autonomie.T1,
            niveau=Niveau.N1,
        ),
    )
