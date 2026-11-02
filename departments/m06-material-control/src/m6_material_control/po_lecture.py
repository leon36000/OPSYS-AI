"""Lecture des bons de commande (C3) : ce que l'admin voit d'un PO, par LISTE BLANCHE de champs.

Avant C3, aucun outil ne listait ni ne lisait un PO : l'admin ne pouvait pas voir ce qui était à approuver, envoyé sans
réponse, partiellement reçu ou en retard. Ce module est la projection pure (aucun import `opsys`, aucune horloge, aucun
réseau, aucune écriture) ; `outils.py` lit les registres et appelle ces fonctions.

Règles :
- LISTE BLANCHE : chaque projection construit ses champs un à un ; un champ de plus au registre ne sort jamais tout seul
  (et aucun contact de fournisseur n'est dans la liste : l'adresse de commande n'est que dans le détail) ;
- « EN RETARD » : le PO est envoyé, confirmé ou partiellement reçu, sa date requise est dépassée à un jour DIT par
  l'appelant (M6 n'a pas d'horloge) ; sans jour dit, la valeur est `None` (« non évalué »), jamais « non » ;
- un PO d'avant C2 se lit : `commandable` est faux et `manques` dit quoi (il n'est ni approuvé ni envoyé tel quel) ;
- aucun mot de jugement sur une personne : ce sont des états de documents.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from . import bons_commande, reception

__all__ = [
    "STATUTS_EN_COURS_DE_LIVRAISON",
    "attentes",
    "comptes_par_statut",
    "est_en_retard",
    "jour_valide",
    "projeter_detail",
    "projeter_liste",
    "selectionner",
]

# Statuts où la marchandise est attendue du fournisseur : le retard n'a de sens que là.
STATUTS_EN_COURS_DE_LIVRAISON = frozenset({"sent_to_supplier", "supplier_confirmed", "partially_received"})
TYPE_ATTENTE_A_APPROUVER = "po_a_approuver"
TYPE_ATTENTE_EN_RETARD = "po_en_retard"
_STATUTS_A_APPROUVER = frozenset({"draft", "pending_admin_review"})


def jour_valide(texte: Any) -> date | None:
    """Un jour civil `AAAA-MM-JJ` (rien d'autre : ni heure, ni fuseau), ou `None`."""
    if not isinstance(texte, str) or len(texte) != 10:
        return None
    try:
        return date.fromisoformat(texte)
    except ValueError:
        return None


def est_en_retard(po: Mapping[str, Any], aujourd_hui: str | None) -> bool | None:
    """Vrai si le PO est en cours de livraison et sa date requise est PASSÉE (strictement) au jour dit. `None` : pas de
    jour dit. Faux : tout autre cas, y compris un PO sans date requise (un ancien PO n'est pas « en retard » sur une
    date qu'il n'a pas)."""
    jour = jour_valide(aujourd_hui)
    if jour is None:
        return None
    requise = jour_valide(po.get("date_requise"))
    return po.get("statut") in STATUTS_EN_COURS_DE_LIVRAISON and requise is not None and requise < jour


def _transitions(registre: Iterable[Mapping[str, Any]], po_id: str) -> list[Mapping[str, Any]]:
    return [m for m in registre if m.get("type_entree") == "transition_po" and m.get("po_id") == po_id]


def _derniere_date(po: Mapping[str, Any], transitions: list[Mapping[str, Any]]) -> Any:
    return (transitions[-1] if transitions else po).get("horodatage")


def projeter_liste(
    po: Mapping[str, Any], fournisseur_nom: str | None, transitions: list[Mapping[str, Any]], aujourd_hui: str | None,
    cree_le: Any = None,
) -> dict[str, Any]:
    """Une ligne de la liste : pas de contact, pas de ligne de matériau, pas de courriel."""
    manques = bons_commande.manques_commandabilite(po)
    return {
        "po_id": po["po_id"],
        "statut": po["statut"],
        "fournisseur_id": po.get("fournisseur_id"),
        "fournisseur_nom": fournisseur_nom,
        "chantier_id": po.get("chantier_id"),
        "devis_id": po.get("devis_id"),
        "date_requise": po.get("date_requise"),
        "mode_livraison": po.get("mode_livraison"),
        "ville": po.get("ville"),
        "nb_lignes": len(po.get("lignes", ())),
        "montant_total_prevu": po.get("montant_total_prevu"),
        "commandable": not manques,
        "manques": manques,
        "en_retard": est_en_retard(po, aujourd_hui),
        "nb_livraisons": sum(1 for t in transitions if isinstance(t.get("livraison"), Mapping)),
        "cree_le": cree_le,
        "mis_a_jour_le": _derniere_date(po, transitions),
    }


_CHAMPS_LIGNE = (
    "materiau_id", "designation", "unite", "unite_source", "quantite_nette", "facteur_perte", "quantite_demandee",
    "verdict_prix", "prix_unitaire_prevu", "devise_prevue", "montant_ligne_prevu", "prix_unite_confirmee",
)


def _ligne(ligne: Mapping[str, Any]) -> dict[str, Any]:
    # Un ancien PO n'a pas les champs de C2 : ils sortent à `None`, jamais devinés (`quantite_nette` : pas de perte
    # connue).
    return {cle: ligne.get(cle) for cle in _CHAMPS_LIGNE}


def _historique(transitions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    sortie = []
    for t in transitions:
        entree: dict[str, Any] = {"statut": t.get("statut"), "horodatage": t.get("horodatage")}
        for cle in ("motif_annulation", "motif_statut", "verdict_reception"):
            if t.get(cle) is not None:
                entree[cle] = t[cle]
        livraison = t.get("livraison")
        if isinstance(livraison, Mapping):
            entree["livraison"] = {
                "horodatage": livraison.get("horodatage"),
                "lignes": [
                    {"materiau_id": ligne.get("materiau_id"), "quantite_recue": ligne.get("quantite_recue")}
                    for ligne in livraison.get("lignes", ())
                ],
            }
        constat = t.get("envoi_constate")
        if isinstance(constat, Mapping):
            entree["envoi_constate"] = {
                "source": constat.get("source"), "brouillon_id": constat.get("brouillon_id"),
                "envoye_le": constat.get("envoye_le"),
            }
        confirmation = t.get("confirmation_courriel")
        if isinstance(confirmation, Mapping):
            entree["confirmation"] = {"mode": confirmation.get("mode"), "signal_id": confirmation.get("signal_id")}
        sortie.append(entree)
    return sortie


def projeter_detail(
    po: Mapping[str, Any], fournisseur_nom: str | None, transitions: list[Mapping[str, Any]], aujourd_hui: str | None,
    cree_le: Any = None,
) -> dict[str, Any]:
    """Le détail d'un PO : la ligne de liste, plus les lignes de matériaux, les conditions, le courriel, l'historique
    des transitions et ce qui a été reçu en tout (livraisons additionnées en décimal exact)."""
    detail = projeter_liste(po, fournisseur_nom, transitions, aujourd_hui, cree_le)
    courriel = po.get("courriel")
    livraisons = [t["livraison"] for t in transitions if isinstance(t.get("livraison"), Mapping)]
    cumul = (
        reception.evaluer_cumul(po.get("lignes", ()), [livraison.get("lignes", ()) for livraison in livraisons])
        if livraisons else None
    )
    detail.update(
        {
            "lieu_livraison": po.get("lieu_livraison"),
            "notes": po.get("notes"),
            "lignes": [_ligne(ligne) for ligne in po.get("lignes", ())],
            "courriel": (
                {cle: courriel.get(cle) for cle in ("objet", "destinataire", "corps", "repli_manuel_requis",
                                                    "empreinte")}
                if isinstance(courriel, Mapping) else None
            ),
            "historique": _historique(transitions),
            "reception_cumulee": cumul,
        }
    )
    return detail


def comptes_par_statut(pos: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    comptes: dict[str, int] = {}
    for po in pos:
        comptes[po["statut"]] = comptes.get(po["statut"], 0) + 1
    return dict(sorted(comptes.items()))


def selectionner(
    pos: Iterable[Mapping[str, Any]],
    *,
    statut: str | None = None,
    fournisseur_id: str | None = None,
    chantier_id: str | None = None,
    devis_id: str | None = None,
    en_retard: bool | None = None,
    aujourd_hui: str | None = None,
) -> list[Mapping[str, Any]]:
    """Les PO qui satisfont TOUS les filtres fournis, dans l'ordre reçu. `en_retard=True` exige un jour dit ; à
    l'appelant de refuser sinon."""
    choisis = []
    for po in pos:
        if statut is not None and po["statut"] != statut:
            continue
        if fournisseur_id is not None and po.get("fournisseur_id") != fournisseur_id:
            continue
        if chantier_id is not None and po.get("chantier_id") != chantier_id:
            continue
        if devis_id is not None and po.get("devis_id") != devis_id:
            continue
        if en_retard is not None and bool(est_en_retard(po, aujourd_hui)) != en_retard:
            continue
        choisis.append(po)
    return choisis


def attentes(pos: Iterable[Mapping[str, Any]], aujourd_hui: str | None) -> list[dict[str, Any]]:
    """Les attentes de l'admin tirées des PO (forme `opsys.approbations.CHAMPS_ATTENTE`) :
    - `po_a_approuver` (N3) : un PO au brouillon ou en revue ; s'il est incomplet (ancien PO), l'attente le dit et
      propose de l'annuler et de le refaire plutôt que de l'approuver ;
    - `po_en_retard` (N2) : un PO envoyé dont la date requise est dépassée au jour dit (seulement si un jour est
    dit)."""
    sortie = []
    for po in pos:
        manques = bons_commande.manques_commandabilite(po)
        if po["statut"] in _STATUTS_A_APPROUVER:
            total = po.get("montant_total_prevu")
            resume = (
                f"PO à approuver : {po['po_id']} chez {po.get('fournisseur_id')} "
                f"pour le chantier {po.get('chantier_id')}"
                + (f", {total} $ prévus" if total is not None else ", prix à compléter")
                + (f", à livrer pour le {po['date_requise']}" if po.get("date_requise") else "")
                + (f". Bon incomplet (il manque : {', '.join(manques)})" if manques else "")
                + "."
            )
            sortie.append(
                {
                    "type": TYPE_ATTENTE_A_APPROUVER,
                    "id": po["po_id"],
                    "resume": resume,
                    "niveau": "N3",
                    "depuis": po.get("horodatage", ""),
                    "action_proposee": (
                        "m6_approuver_po" if not manques
                        else "m6_annuler_po puis refaire le bon de commande (il est d'avant les conditions de commande)"
                    ),
                }
            )
        if est_en_retard(po, aujourd_hui):
            sortie.append(
                {
                    "type": TYPE_ATTENTE_EN_RETARD,
                    "id": po["po_id"],
                    "resume": (
                        f"PO en retard : {po['po_id']} chez {po.get('fournisseur_id')} devait arriver pour le "
                        f"{po['date_requise']} (statut {po['statut']})."
                    ),
                    "niveau": "N2",
                    "depuis": po["date_requise"],
                    "action_proposee": (
                        "Relancer le fournisseur ; contester le bon de commande au besoin (m6_changer_statut_po)"
                    ),
                }
            )
    return sortie
