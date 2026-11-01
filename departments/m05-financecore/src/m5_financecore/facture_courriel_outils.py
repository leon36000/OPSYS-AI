"""Factures de fournisseurs reçues par courriel : consommateur de `m1.courriel_aiguille`, attente et classement humain.

Voir `facture_courriel.py` (pur). Ce module lit le registre des comptes à payer (réceptions de M6) pour reconnaître
les PO cités, range une ligne de suivi par message (idempotent), expose l'attente « à saisir » et laisse une PERSONNE
la classer (saisie faite, doublon, fausse facture écartée). Il ne saisit, ne corrige et ne paie rien.
"""

from __future__ import annotations

from typing import Any

from opsys import approbations, contexte, identite, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import facture_courriel as fc

_DEPARTEMENT = "m05-financecore"
_REGISTRE = "factures_courriel"
_REGISTRE_AP = "comptes_a_payer"
_TYPE_FACTURE_AP = "facture_fournisseur_saisie"
_TYPE_CLASSEMENT = "facture_courriel_classee"
_ROLES_HUMAINS = frozenset({"finance", "admin", "nathan_owner"})


def _reg() -> Any:
    return stockage.maillons(_DEPARTEMENT, _REGISTRE)


def _refus(code: str, detail: str) -> Any:
    """Refus typé : `ValueError("CODE: détail")`, rendu en refus métier par le répartiteur d'outils (le catalogue de
    verdicts de M5 est fermé et ne connaît pas ces codes)."""
    raise ValueError(f"{code}: {detail}")


def recevoir_courriel_aiguille(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m1.courriel_aiguille` : seule la classe `facture_fournisseur` est retenue."""
    if charge["classe"] != "facture_fournisseur":
        return {"ignore": True, "classe": charge["classe"]}
    registre = _reg()
    ident = fc.identifiant(charge["signal_id"])
    if any(m.get("facture_courriel_id") == ident for m in registre if m.get("type_entree") == fc.TYPE_FACTURE_COURRIEL):
        return {"deja_recue": True, "facture_courriel_id": ident}
    po = fc.po_reconnus(charge, stockage.maillons(_DEPARTEMENT, _REGISTRE_AP))
    registre.append(fc.maillon(charge, po))
    return {"facture_courriel_id": ident, "statut": "a_saisir", "po_reconnus": len(po)}


def _etats() -> dict[str, dict[str, Any]]:
    res: dict[str, dict[str, Any]] = {}
    for m in _reg():
        if m.get("type_entree") == fc.TYPE_FACTURE_COURRIEL:
            res[m["facture_courriel_id"]] = dict(m)
        elif m.get("type_entree") == _TYPE_CLASSEMENT and m["facture_courriel_id"] in res:
            res[m["facture_courriel_id"]].update(statut=m["statut"], classee_par=m["par"])
    ap = [m for m in stockage.maillons(_DEPARTEMENT, _REGISTRE_AP) if m.get("type_entree") == _TYPE_FACTURE_AP]
    for e in res.values():
        if e["statut"] == "a_saisir" and any(
            f.get("po_id") in e["po_reconnus"] and str(f.get("horodatage")) >= str(e["horodatage"]) for f in ap
        ):
            e["statut"] = "saisie_constatee"
    return res


def attentes_factures_courriel() -> list[dict[str, Any]]:
    return [fc.attente(e) for e in _etats().values() if e["statut"] == "a_saisir"]


def lister_factures_courriel(statut: str | None = None) -> dict[str, Any]:
    elements = [e for e in _etats().values() if statut is None or e["statut"] == statut]
    return {
        "accepte": True,
        "resultat": {
            "factures_courriel": elements[-50:],
            "total": len(elements),
            "avertissement": "Courriel non fiable, trié automatiquement : aucun montant n'est lu, aucune facture "
            "n'est créée. À valider auprès d'un comptable (CPA) / professionnel qualifié.",
        },
    }


def _acteur_humain(nom_outil: str) -> dict[str, str]:
    cnx = stockage.connexion_courante()
    appelante = contexte.identite_appelante()
    if appelante is not None:
        confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
        if confirmee is None or confirmee.role not in (identite.Role.ADMIN.value, "nathan_owner"):
            return _refus("REJ-HUMAIN-IDENTITE-INVALIDE", "personne admin confirmée en base requise")
        return {"par": confirmee.personne, "role": confirmee.role}
    approbateur = approbations.approbateur_en_cours(cnx, nom_outil, _DEPARTEMENT, roles=_ROLES_HUMAINS) if cnx else None
    if approbateur is not None:
        return {"par": approbateur.personne, "role": approbateur.role}
    return _refus("REJ-HUMAIN-REQUIS", "décision humaine : propose-la et attends l'approbation d'une personne")


def classer_facture_courriel(facture_courriel_id: str, statut: str, motif: str, horodatage: str) -> dict[str, Any]:
    acteur = _acteur_humain("m5_classer_facture_courriel")
    if statut not in ("saisie_faite", "doublon", "ecartee"):
        return _refus("REJ-M5-COURRIEL-STATUT", "statut parmi saisie_faite, doublon, ecartee")
    if not isinstance(motif, str) or not 5 <= len(motif.strip()) <= 300:
        return _refus("REJ-M5-COURRIEL-MOTIF", "motif de 5 à 300 caractères")
    courant = _etats().get(facture_courriel_id)
    if courant is None:
        return _refus("REJ-M5-COURRIEL-INCONNUE", "facture reçue par courriel inconnue")
    if courant["statut"] not in ("a_saisir", "saisie_constatee"):
        return _refus("REJ-M5-COURRIEL-DEJA-CLASSEE", f"déjà « {courant['statut']} »")
    _reg().append(
        {
            "type_entree": _TYPE_CLASSEMENT,
            "horodatage": horodatage,
            "facture_courriel_id": facture_courriel_id,
            "statut": statut,
            "motif": motif.strip(),
            "par": acteur["par"],
            "role": acteur["role"],
        }
    )
    return {"accepte": True, "resultat": {"facture_courriel_id": facture_courriel_id, "statut": statut}}


def outils_facture_courriel() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m5_lister_factures_courriel",
            description=(
                "Liste les factures de fournisseurs arrivées par courriel et aiguillées par M1 (à saisir, saisies, "
                "classées), avec les PO reconnus et le drapeau « à vérifier » (fausse facture possible). Aucun montant "
                "n'est lu du courriel. Lecture."
            ),
            parametres={
                "type": "object",
                "properties": {"statut": {"type": ["string", "null"], "maxLength": 40}},
                "additionalProperties": False,
            },
            fonction=lister_factures_courriel,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m5_classer_facture_courriel",
            description=(
                "Une PERSONNE classe une facture reçue par courriel : saisie faite, doublon ou écartée (fausse "
                "facture). Ne saisit ni ne paie rien. Décision humaine."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_courriel_id": {"type": "string", "pattern": "^fc-[0-9a-f]{16}$"},
                    "statut": {"type": "string", "enum": ["saisie_faite", "doublon", "ecartee"]},
                    "motif": {"type": "string", "minLength": 5, "maxLength": 300},
                    "horodatage": {"type": "string", "description": "ISO-8601 avec fuseau."},
                },
                "required": ["facture_courriel_id", "statut", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=classer_facture_courriel,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
    )
