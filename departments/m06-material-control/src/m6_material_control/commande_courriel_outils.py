"""Commande par courriel via M1 (M6.6) : consommateurs d'événements, outils de lecture et de décision. Adaptateur de
`commande_courriel` (pur).

Le flux (aucune étape n'envoie quoi que ce soit) :
- entrant : `m1.courriel_aiguille` (classes `commande_materiaux`, `confirmation_fournisseur`) -> brouillon de demande de
  commande rapproché des devis et des WCT, ou confirmation de PO ; idempotent par message ; la provenance (message,
  règles, confiance, empreinte de l'expéditeur) est rangée avec chaque fait ;
- sortant : `m6_generer_courriel_po` publie `m6.po_courriel_pret` ; M1 prépare le brouillon au fournisseur dans le
sas ; quand une personne a approuvé et que le courriel est parti, `m1.commande_courriel_envoyee` est constaté ici ; si
c'est
bien le courriel de CE PO (empreinte identique,
                           texte non modifié), le PO passe à « envoyé » en rangeant le constat (C2 :
l'envoi a déjà été approuvé au sas, pas de seconde approbation). Sinon une ATTENTE « marquer le PO envoyé » attend
une personne (`m6_marquer_po_envoye`, N4), comme pour un envoi hors M1.
"""

from __future__ import annotations

from typing import Any

from opsys import approbations, contexte, identite, stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import bons_commande, fournisseurs, verdicts
from . import commande_courriel as cc

_DEPARTEMENT = "m06-material-control"
_REGISTRE = "commandes_courriel"
_ROLES_HUMAINS = frozenset({"manager", "admin", "nathan_owner"})
_PAGE_MAX = 25


def _reg() -> Any:
    return stockage.maillons(_DEPARTEMENT, _REGISTRE)


def _registres() -> dict[str, Any]:
    return {
        n: stockage.maillons(_DEPARTEMENT, n) for n in ("bons_commande", "fournisseurs", "besoins_prevus", "wct_recus")
    }


def _refus(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdicts.construire_verdict(code, detail=detail)}


def _acteur_humain(nom_outil: str) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Une décision de PERSONNE : un appel d'appareil admin confirmé en base, ou l'exécution d'une demande qu'un
    humain vient
    d'approuver dans le sas. Jamais un agent seul (même patron que M1)."""
    cnx = stockage.connexion_courante()
    appelante = contexte.identite_appelante()
    if appelante is not None:
        confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
        if confirmee is None:
            return None, _refus("REJ-HUMAIN-IDENTITE-INVALIDE", "personne inconnue, inactive ou rôle retiré")
        if confirmee.role not in (identite.Role.ADMIN.value, "nathan_owner"):
            return None, _refus("REJ-HUMAIN-ROLE-INSUFFISANT", "décision réservée au rôle admin depuis un appareil")
        return {"par": confirmee.personne, "role": confirmee.role, "voie": "appareil"}, None
    approbateur = approbations.approbateur_en_cours(cnx, nom_outil, _DEPARTEMENT, roles=_ROLES_HUMAINS) if cnx else None
    if approbateur is not None:
        return {"par": approbateur.personne, "role": approbateur.role, "voie": "approbation"}, None
    return None, _refus(
        "REJ-HUMAIN-REQUIS",
        "décision humaine : propose-la et attends qu'une personne approuve la "
        "demande dans la console OPSYS ; ne la présente pas comme faite",
    )


# ---------------------------------------------------------------------------------------------- consommateurs
def recevoir_courriel_aiguille(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m1.courriel_aiguille`. Les autres classes sont ignorées (sans aucune écriture)."""
    classe = charge["classe"]
    if classe not in ("commande_materiaux", "confirmation_fournisseur"):
        return {"ignore": True, "classe": classe}
    registres = _registres()
    registre = _reg()
    if classe == "commande_materiaux":
        commande_id = cc.identifiant_commande(charge["signal_id"])
        if any(m.get("commande_id") == commande_id for m in registre):
            return {"deja_recue": True, "commande_id": commande_id}
        fiches = fournisseurs.lister_fournisseurs(registres["fournisseurs"])
        rapprochement = cc.rapprocher(
            charge,
            registres["besoins_prevus"],
            registres["wct_recus"],
            bons_commande.lister(registres["bons_commande"]),
        )
        maillon = cc.maillon_commande(
            charge, cc.identifier_fournisseur(charge["expediteur_empreinte"], fiches), rapprochement
        )
        registre.append(maillon)
        return {
            "commande_id": commande_id,
            "statut": "a_traiter",
            "rapprochement_sans_correspondance": rapprochement["sans_rapprochement"],
        }
    confirmation_id = cc.identifiant_confirmation(charge["signal_id"])
    if any(m.get("confirmation_id") == confirmation_id for m in registre):
        return {"deja_recue": True, "confirmation_id": confirmation_id}
    evaluation = cc.evaluer_confirmation(
        charge,
        bons_commande.lister(registres["bons_commande"]),
        fournisseurs.lister_fournisseurs(registres["fournisseurs"]),
    )
    statut = {"appliquer": "appliquee", "a_valider": "a_valider", "non_rapprochee": "non_rapprochee"}[
        evaluation["decision"]
    ]
    provenance = {
        "source": "m1.courriel_aiguille",
        "signal_id": charge["signal_id"],
        "confiance": charge["confiance"],
        "version_regles": charge["version_regles"],
        "expediteur_empreinte": charge["expediteur_empreinte"],
    }
    if evaluation["decision"] == "appliquer":
        po, verdict = bons_commande.confirmer_fournisseur(
            evaluation["po_id"],
            charge["recu_le"],
            registres["bons_commande"],
            {**provenance, "dates_annoncees": evaluation["dates_annoncees"], "mode": "automatique_conditions_reunies"},
        )
        if verdict is not None:
            statut, evaluation = (
                "a_valider",
                {**evaluation, "decision": "a_valider", "raisons": [*evaluation["raisons"], verdict["code"]]},
            )
    registre.append(
        {
            "type_entree": cc.TYPE_CONFIRMATION,
            "horodatage": charge["recu_le"],
            "confirmation_id": confirmation_id,
            "signal_id": charge["signal_id"],
            "statut": statut,
            "evaluation": evaluation,
            "provenance": provenance,
        }
    )
    return {"confirmation_id": confirmation_id, "statut": statut, "po_id": evaluation["po_id"]}


def recevoir_commande_envoyee(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur de `m1.commande_courriel_envoyee` : constate l'envoi du courriel et, si c'est bien celui du PO,
    en prend acte (C2).

    L'envoi a DÉJÀ été approuvé par une personne au sas de M1 (N3, empreinte exacte du brouillon) : exiger ensuite
    `m6_marquer_po_envoye` (N4) était une seconde approbation du même geste. M6 passe donc le PO de `email_ready` à
    `sent_to_supplier`, en rangeant le constat, SEULEMENT si toutes ces conditions tiennent :
      - le PO existe et est encore `email_ready` (jamais un PO annulé, brouillon ou déjà envoyé) ;
      - M1 rapporte l'empreinte du courriel que M6 lui a offert (`empreinte_courriel_po`) et elle est celle du courriel
        PERSISTÉ sur CE PO (pas celle d'un autre bon) ;
      - M1 dit que le brouillon envoyé est celui qu'il avait préparé (`contenu_identique`), donc que personne n'a
      modifié
        le texte dans le sas.
    Sinon (vieux constat sans empreinte, texte modifié,
           autre bon) rien ne change : l'attente N4 « marquer le PO envoyé »
    reste à une personne. Aucun envoi n'est déclenché ici : M6 recopie un fait déjà approuvé."""
    registre = _reg()
    if any(m.get("type_entree") == cc.TYPE_ENVOI and m["brouillon_id"] == charge["brouillon_id"] for m in registre):
        return {"deja_constate": True}
    bons = _registres()["bons_commande"]
    po = bons_commande.lire(bons, charge["po_id"])
    marque = False
    if po is not None and po["statut"] == "email_ready":
        courriel = po.get("courriel") or {}
        if (
            charge.get("contenu_identique") is True
            and isinstance(courriel.get("empreinte"), str)
            and charge.get("empreinte_courriel_po") == courriel["empreinte"]
        ):
            _, verdict = bons_commande.marquer_envoye(
                charge["po_id"], charge["envoye_le"], bons,
                {"source": "m1.commande_courriel_envoyee", "brouillon_id": charge["brouillon_id"],
                 "empreinte_courriel_po": courriel["empreinte"], "envoye_le": charge["envoye_le"]},
            )
            marque = verdict is None
    registre.append(
        {
            "type_entree": cc.TYPE_ENVOI,
            "horodatage": charge["envoye_le"],
            "po_id": charge["po_id"],
            "brouillon_id": charge["brouillon_id"],
            "empreinte": charge["empreinte"],
            "statut_po_au_constat": None if po is None else po["statut"],
            "po_marque_envoye": marque,
        }
    )
    return {"constate": True, "po_trouve": po is not None, "statut_po": None if po is None else po["statut"],
            "po_marque_envoye": marque}


# ------------------------------------------------------------------------------------------------- lectures
def _dernier_par(registre: Any, cle: str, type_entree: str) -> dict[str, dict[str, Any]]:
    res: dict[str, dict[str, Any]] = {}
    for m in registre:
        if m.get("type_entree") == type_entree:
            res[m[cle]] = m
    return res


def _commandes_courantes() -> dict[str, dict[str, Any]]:
    res = _dernier_par(_reg(), "commande_id", cc.TYPE_COMMANDE)
    for m in _reg():
        if m.get("type_entree") == cc.TYPE_TRAITEMENT and m["commande_id"] in res:
            res[m["commande_id"]] = {
                **res[m["commande_id"]],
                "statut": m["decision"],
                "traitee_par": m["par"],
                "po_id": m.get("po_id"),
                "motif_traitement": m["motif"],
            }
    return res


def _confirmations_courantes() -> dict[str, dict[str, Any]]:
    res = _dernier_par(_reg(), "confirmation_id", cc.TYPE_CONFIRMATION)
    for m in _reg():
        if m.get("type_entree") == cc.TYPE_DECISION_CONFIRMATION and m["confirmation_id"] in res:
            res[m["confirmation_id"]] = {**res[m["confirmation_id"]], "statut": m["statut"], "decidee_par": m["par"]}
    return res


def lire_commandes_courriel(
    genre: str = "commandes", statut: str | None = None, depart: int = 0, limite: int = 10
) -> dict[str, Any]:
    if genre not in ("commandes", "confirmations", "envois"):
        return _refus("REJ-M6-COURRIEL-GENRE", "genre parmi commandes, confirmations, envois")
    if type(depart) is not int or depart < 0 or type(limite) is not int or not 1 <= limite <= _PAGE_MAX:
        return _refus("REJ-M6-COURRIEL-PAGINATION", f"depart ≥ 0, limite de 1 à {_PAGE_MAX}")
    if genre == "commandes":
        lignes = list(_commandes_courantes().values())
    elif genre == "confirmations":
        lignes = list(_confirmations_courantes().values())
    else:
        lignes = [m for m in _reg() if m.get("type_entree") == cc.TYPE_ENVOI]
    lignes = [m for m in reversed(lignes) if statut is None or m.get("statut") == statut]
    page = lignes[depart : depart + limite]
    return {
        "accepte": True,
        "resultat": {
            "genre": genre,
            "elements": page,
            "total": len(lignes),
            "depart": depart,
            "suivant": depart + limite if depart + limite < len(lignes) else None,
            "avertissement": "Faits extraits d'un courriel non fiable par un tri automatique, jamais une commande : "
            "rien n'est commandé, envoyé ni payé.",
        },
    }


# ---------------------------------------------------------------------------------------------------- décisions
def traiter_commande_courriel(
    commande_id: str, decision: str, motif: str, horodatage: str, po_id: str | None = None
) -> dict[str, Any]:
    """N2 : classe une demande reçue (traitée, rejetée) ; peut la lier à un PO existant. Aucun PO n'est créé."""
    if decision not in ("traitee", "rejetee"):
        return _refus("REJ-M6-COURRIEL-DECISION", "décision parmi traitee, rejetee")
    if not isinstance(motif, str) or not 5 <= len(motif.strip()) <= 300:
        return _refus("REJ-M6-COURRIEL-MOTIF", "motif de 5 à 300 caractères")
    courante = _commandes_courantes().get(commande_id)
    if courante is None:
        return _refus("REJ-M6-COURRIEL-INCONNUE", "demande de commande inconnue")
    if courante["statut"] != "a_traiter":
        return _refus("REJ-M6-COURRIEL-DEJA-TRAITEE", f"demande déjà « {courante['statut']} »")
    if po_id is not None and bons_commande.lire(_registres()["bons_commande"], po_id) is None:
        return _refus("REJ-M6-COURRIEL-PO-INCONNU", "ce PO n'existe pas")
    appelante = contexte.identite_appelante()
    _reg().append(
        {
            "type_entree": cc.TYPE_TRAITEMENT,
            "horodatage": horodatage,
            "commande_id": commande_id,
            "decision": decision,
            "motif": motif.strip(),
            "po_id": po_id,
            "par": appelante.personne if appelante is not None else "agent",
        }
    )
    return {"accepte": True, "resultat": {"commande_id": commande_id, "statut": decision, "po_id": po_id}}


def valider_confirmation_courriel(confirmation_id: str, decision: str, motif: str, horodatage: str) -> dict[str, Any]:
    """N3 humain : applique (`supplier_confirmed`) ou écarte une confirmation de fournisseur que les conditions
    automatiques
    n'ont pas suffi à appliquer."""
    acteur, refus = _acteur_humain("m6_valider_confirmation_courriel")
    if acteur is None:
        return refus or _refus("REJ-HUMAIN-REQUIS", "décision humaine requise")
    if decision not in ("appliquer", "ecarter"):
        return _refus("REJ-M6-COURRIEL-DECISION", "décision parmi appliquer, ecarter")
    if not isinstance(motif, str) or not 5 <= len(motif.strip()) <= 300:
        return _refus("REJ-M6-COURRIEL-MOTIF", "motif de 5 à 300 caractères")
    courante = _confirmations_courantes().get(confirmation_id)
    if courante is None:
        return _refus("REJ-M6-COURRIEL-INCONNUE", "confirmation inconnue")
    if courante["statut"] not in ("a_valider", "non_rapprochee"):
        return _refus("REJ-M6-COURRIEL-DEJA-DECIDEE", f"confirmation déjà « {courante['statut']} »")
    statut = "ecartee"
    if decision == "appliquer":
        po_id = courante["evaluation"].get("po_id")
        if po_id is None:
            return _refus("REJ-M6-COURRIEL-PO-INCONNU", "aucun PO sans ambiguïté : rien à confirmer")
        po, verdict = bons_commande.confirmer_fournisseur(
            po_id,
            horodatage,
            _registres()["bons_commande"],
            {**courante["provenance"], "mode": "valide_par_une_personne", "par": acteur["par"]},
        )
        if verdict is not None:
            return {"accepte": False, "verdict": verdict}
        statut = "appliquee_par_une_personne"
    _reg().append(
        {
            "type_entree": cc.TYPE_DECISION_CONFIRMATION,
            "horodatage": horodatage,
            "confirmation_id": confirmation_id,
            "statut": statut,
            "motif": motif.strip(),
            "par": acteur["par"],
            "role": acteur["role"],
            "voie": acteur["voie"],
        }
    )
    return {"accepte": True, "resultat": {"confirmation_id": confirmation_id, "statut": statut}}


# ------------------------------------------------------------------------------------------------ attentes
def attentes_courriel() -> list[dict[str, Any]]:
    """Ce que cette voie met devant l'admin : demandes à traiter, confirmations à trancher, POs envoyés à marquer."""
    res: list[dict[str, Any]] = []
    for c in _commandes_courantes().values():
        if c["statut"] == "a_traiter":
            res.append(
                {
                    "type": "commande_courriel_a_traiter",
                    "id": c["commande_id"],
                    "niveau": "N3",
                    "depuis": c["horodatage"],
                    "action_proposee": "m6_traiter_commande_courriel",
                    "resume": f"Demande de commande reçue par courriel ({len(c['rapprochement']['lignes'])} ligne(s)"
                    + (", sans devis cité" if c["rapprochement"]["sans_rapprochement"] else "")
                    + ").",
                }
            )
    for c in _confirmations_courantes().values():
        if c["statut"] in ("a_valider", "non_rapprochee"):
            res.append(
                {
                    "type": "confirmation_fournisseur_a_valider",
                    "id": c["confirmation_id"],
                    "niveau": "N3",
                    "depuis": c["horodatage"],
                    "action_proposee": "m6_valider_confirmation_courriel",
                    "resume": "Confirmation de fournisseur reçue par courriel : "
                    + ", ".join(c["evaluation"]["raisons"][:3])
                    + ".",
                }
            )
    bons = _registres()["bons_commande"]
    for e in (m for m in _reg() if m.get("type_entree") == cc.TYPE_ENVOI):
        po = bons_commande.lire(bons, e["po_id"])
        if po is not None and po["statut"] == "email_ready":
            res.append(
                {
                    "type": "po_envoye_a_marquer",
                    "id": e["po_id"],
                    "niveau": "N4",
                    "depuis": e["horodatage"],
                    "action_proposee": "m6_marquer_po_envoye",
                    "resume": "Le courriel de commande a été envoyé après approbation : marquer le PO envoyé.",
                }
            )
    return res


def outils_commande_courriel() -> tuple[Outil, ...]:
    horo = {"type": "string", "description": "ISO-8601 avec fuseau."}
    return (
        Outil(
            nom="m6_lire_commandes_courriel",
            description=(
                "Lit ce que M1 a aiguillé vers M6 : demandes de commande reçues par courriel (rapprochées des devis et "
                "des WCT, avec provenance), confirmations de fournisseurs (appliquées ou à trancher) et envois de "
                "courriels de commande constatés. Rien n'est une commande. Lecture."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "genre": {"type": "string", "enum": ["commandes", "confirmations", "envois"]},
                    "statut": {"type": ["string", "null"], "maxLength": 40},
                    "depart": {"type": "integer", "minimum": 0},
                    "limite": {"type": "integer", "minimum": 1, "maximum": _PAGE_MAX},
                },
                "additionalProperties": False,
            },
            fonction=lire_commandes_courriel,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m6_traiter_commande_courriel",
            description=(
                "Classe une demande de commande reçue par courriel (traitée ou rejetée, avec motif) et peut la lier à "
                "un PO existant. Ne crée, n'approuve ni n'envoie aucun PO."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "commande_id": {"type": "string", "pattern": "^cc-[0-9a-f]{16}$"},
                    "decision": {"type": "string", "enum": ["traitee", "rejetee"]},
                    "motif": {"type": "string", "minLength": 5, "maxLength": 300},
                    "horodatage": horo,
                    "po_id": {"type": ["string", "null"], "maxLength": 120},
                },
                "required": ["commande_id", "decision", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=traiter_commande_courriel,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m6_valider_confirmation_courriel",
            description=(
                "Une PERSONNE tranche une confirmation de fournisseur reçue par courriel que les conditions "
                "automatiques n'ont pas suffi à appliquer : l'appliquer (PO envoyé -> confirmé par le fournisseur) "
                "ou l'écarter. Décision humaine, jamais d'un agent seul."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "confirmation_id": {"type": "string", "pattern": "^cf-[0-9a-f]{16}$"},
                    "decision": {"type": "string", "enum": ["appliquer", "ecarter"]},
                    "motif": {"type": "string", "minLength": 5, "maxLength": 300},
                    "horodatage": horo,
                },
                "required": ["confirmation_id", "decision", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=valider_confirmation_courriel,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
    )
