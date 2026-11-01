"""Commande par courriel via M1 (M6.6) : les règles pures. M1 est le CANAL, M6 reste la source de vérité du PO.

Deux courriels viennent de M1 par l'événement `m1.courriel_aiguille` (jamais le texte, seulement des faits minimaux) :

- une DEMANDE DE COMMANDE (classe `commande_materiaux`, un employé ou le terrain) devient un brouillon de demande
  (`commande_courriel`), rapproché des soumissions (besoins prévus d'un devis) et des WCT reçus quand le courriel
  cite un identifiant que M6 connaît. Aucun bon de commande n'est créé ni envoyé : un humain ou un agent crée le PO
  avec les outils existants (N3 pour l'envoi). Idempotent par clé de message ;
- une CONFIRMATION de fournisseur (classe `confirmation_fournisseur`) met à jour le suivi d'un PO. Elle n'est
appliquée seule (`sent_to_supplier` -> `supplier_confirmed`) que si TOUT tient : PO nommé sans ambiguïté, expéditeur
= boîte de commande du fournisseur du PO, authentification complète, aucune relecture exigée par le tri, et le
fournisseur ne signale ni rupture, ni report, ni substitution. Sinon : une attente, qu'une personne tranche.

Rien n'est un prix : les quantités sont des textes décimaux, aucune unité n'est convertie ni devinée.

Module pur : aucun import `opsys`, aucune horloge (l'heure vient de l'événement).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

TYPE_COMMANDE = "commande_courriel_recue"
TYPE_CONFIRMATION = "confirmation_fournisseur_recue"
TYPE_ENVOI = "envoi_courriel_constate"
TYPE_TRAITEMENT = "commande_courriel_traitee"
TYPE_DECISION_CONFIRMATION = "confirmation_fournisseur_decidee"
ANOMALIES = frozenset({"rupture", "report", "substitution"})


def empreinte_expediteur(adresse: str) -> str:
    """Même formule que `m1_front_office.tri_extraction.empreinte_expediteur` (un test pose l'égalité) : l'adresse d'un
    fournisseur ne circule jamais sur le bus, seulement son empreinte."""
    return hashlib.sha256(("m1-expediteur|" + adresse.strip().lower()).encode("utf-8")).hexdigest()


def normaliser(texte: Any) -> str:
    d = unicodedata.normalize("NFKD", str(texte or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in d if not unicodedata.combining(c))).strip()


def _plie(s: Any) -> str:
    return str(s or "").casefold()


def identifier_fournisseur(empreinte: str, fournisseurs: Iterable[Mapping[str, Any]]) -> str | None:
    """Le fournisseur dont la boîte de commande a cette empreinte, ou `None` (inconnu ou ambigu : jamais deviné)."""
    trouves = [
        f["fournisseur_id"]
        for f in fournisseurs
        if f.get("courriel_commande") and empreinte_expediteur(f["courriel_commande"]) == empreinte
    ]
    return trouves[0] if len(set(trouves)) == 1 else None


def _decimal(q: str) -> Decimal | None:
    try:
        return Decimal(q)
    except InvalidOperation:
        return None


def rapprocher(
    charge: Mapping[str, Any],
    besoins: Iterable[Mapping[str, Any]],
    wct_recus: Iterable[Mapping[str, Any]],
    bons: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Relie le courriel à ce que M6 connaît, par IDENTIFIANT EXACT cité dans le courriel (comparé sans casse). Rien
    n'est
    rapproché par ressemblance : une désignation ne s'apparie qu'à un `materiau_id` identique après normalisation."""
    jetons = {_plie(j) for j in charge.get("jetons_reference", ())}
    besoins = list(besoins)
    devis_trouves = sorted({b["devis_id"] for b in besoins if _plie(b.get("devis_id")) in jetons})
    chantiers_trouves = sorted(
        {b["chantier_id"] for b in besoins if b.get("chantier_id") and _plie(b["chantier_id"]) in jetons}
    )
    # Un chantier cité désigne aussi son devis, mais seulement s'il est unique.
    if not devis_trouves and chantiers_trouves:
        par_chantier = {b["devis_id"] for b in besoins if b.get("chantier_id") in chantiers_trouves}
        if len(par_chantier) == 1:
            devis_trouves = sorted(par_chantier)
    po_ids = sorted({b["po_id"] for b in bons if _plie(b.get("po_id")) in jetons})
    resultat: dict[str, Any] = {
        "devis": devis_trouves,
        "chantiers": chantiers_trouves,
        "po": po_ids,
        "lignes": [],
        "wct": [],
        "sans_rapprochement": not (devis_trouves or po_ids),
    }
    prevu: dict[str, Mapping[str, Any]] = {}
    for d in devis_trouves:
        dernier = None
        for b in besoins:
            if b.get("devis_id") == d:
                dernier = b
        if dernier is not None:
            for ligne in dernier.get("lignes", ()):
                prevu[normaliser(ligne["materiau_id"])] = ligne
    for ligne in charge.get("lignes", ()):
        cle = normaliser(ligne["designation"])
        correspond = prevu.get(cle)
        demande = _decimal(str(ligne["quantite"]))
        entree = {
            "designation": ligne["designation"],
            "quantite_demandee": ligne["quantite"],
            "unite": ligne.get("unite"),
            "materiau_id": correspond["materiau_id"] if correspond else None,
            "quantite_prevue": None,
            "ecart_a_prevu": "inconnu",
        }
        if correspond is not None:
            entree["quantite_prevue"] = str(correspond["quantite_estimee"])
            prevue = _decimal(str(correspond["quantite_estimee"]))
            if prevue is not None and demande is not None:
                entree["ecart_a_prevu"] = (
                    "au_dessus_du_prevu"
                    if demande > prevue
                    else "egal_au_prevu"
                    if demande == prevue
                    else "sous_le_prevu"
                )
            if (
                correspond.get("unite")
                and ligne.get("unite")
                and normaliser(correspond["unite"]) != normaliser(ligne["unite"])
            ):
                entree["ecart_a_prevu"] = "unite_differente"
        resultat["lignes"].append(entree)
    for w in wct_recus:
        if w.get("devis_id") in devis_trouves:
            resultat["wct"].append({"wct_id": w["wct_id"], "horodatage_completion": w.get("horodatage_completion")})
    return resultat


def identifiant_commande(signal_id: str) -> str:
    return "cc-" + hashlib.sha256(("m6-commande-courriel|" + signal_id).encode()).hexdigest()[:16]


def maillon_commande(
    charge: Mapping[str, Any], fournisseur_id: str | None, rapprochement: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "type_entree": TYPE_COMMANDE,
        "horodatage": charge["recu_le"],
        "commande_id": identifiant_commande(charge["signal_id"]),
        "signal_id": charge["signal_id"],
        "compte_id": charge["compte_id"],
        "statut": "a_traiter",
        "fournisseur_id": fournisseur_id,
        "rapprochement": dict(rapprochement),
        "revue_humaine": bool(charge["revue_humaine"]),
        "motifs_revue": list(charge["motifs_revue"]),
        "provenance": {
            "source": "m1.courriel_aiguille",
            "classe": charge["classe"],
            "confiance": charge["confiance"],
            "version_regles": charge["version_regles"],
            "regles": list(charge["regles"])[:40],
            "authentification_complete": bool(charge["authentification_complete"]),
            "expediteur_empreinte": charge["expediteur_empreinte"],
        },
        "suggestion": suggestion(rapprochement),
    }


def suggestion(rapprochement: Mapping[str, Any]) -> dict[str, Any]:
    """Ce qu'une personne ou un agent peut faire ensuite avec les OUTILS EXISTANTS (rien n'est fait ici)."""
    if len(rapprochement.get("devis", ())) == 1:
        return {
            "outil": "m6_creer_po_brouillon",
            "devis_id": rapprochement["devis"][0],
            "note": "créer le PO brouillon depuis le prévu du devis ; fournisseur à choisir ; l'envoi reste N4",
        }
    return {
        "outil": None,
        "note": "aucun devis cité : rattacher la demande à un devis ou à un chantier avant de commander",
    }


def evaluer_confirmation(
    charge: Mapping[str, Any], bons: Iterable[Mapping[str, Any]], fournisseurs: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Décision sur une confirmation de fournisseur : `appliquer` (tout tient), `a_valider` (PO trouvé mais une
    condition
    manque : une personne tranche) ou `non_rapprochee` (aucun PO nommé)."""
    bons = list(bons)
    refs = {_plie(r) for r in charge.get("references_po", ())} | {_plie(j) for j in charge.get("jetons_reference", ())}
    candidats = sorted({b["po_id"] for b in bons if _plie(b.get("po_id")) in refs})
    base = {
        "po_id": candidats[0] if len(candidats) == 1 else None,
        "candidats": candidats,
        "etat_annonce": list(charge.get("etat_annonce", ())),
        "dates_annoncees": list(charge.get("dates_annoncees", ())),
    }
    if not candidats:
        return {**base, "decision": "non_rapprochee", "raisons": ["aucun_po_nomme"]}
    if len(candidats) > 1:
        return {**base, "decision": "a_valider", "raisons": ["plusieurs_po_nommes"]}
    po = next(b for b in bons if b["po_id"] == candidats[0])
    fournisseur = identifier_fournisseur(charge["expediteur_empreinte"], fournisseurs)
    raisons: list[str] = []
    if fournisseur is None or fournisseur != po.get("fournisseur_id"):
        raisons.append("expediteur_different_du_fournisseur_du_po")
    if not charge.get("authentification_complete"):
        raisons.append("authentification_incomplete")
    if charge.get("revue_humaine"):
        raisons.append("revue_humaine_exigee_par_le_tri")
    annonce = set(charge.get("etat_annonce", ()))
    if annonce & ANOMALIES:
        raisons.append("anomalie_signalee:" + ",".join(sorted(annonce & ANOMALIES)))
    if "confirmee" not in annonce:
        raisons.append("aucune_confirmation_explicite")
    if po.get("statut") != "sent_to_supplier":
        raisons.append(f"po_au_statut_{po.get('statut')}")
    return {
        **base,
        "decision": "a_valider" if raisons else "appliquer",
        "raisons": raisons,
        "fournisseur_id": fournisseur,
        "statut_po": po.get("statut"),
    }


def identifiant_confirmation(signal_id: str) -> str:
    return "cf-" + hashlib.sha256(("m6-confirmation-fournisseur|" + signal_id).encode()).hexdigest()[:16]
