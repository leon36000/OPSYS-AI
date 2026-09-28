"""Brouillon de soumission client de M3 (PLAN T2.3, DEFINITION-PRODUIT.md §7-M3 M3.13).

Rend un texte HTML STRUCTURÉ et LISIBLE depuis un devis durable déjà assemblé
(``devis_durable.creer_devis``/``lire_devis``), jamais un PDF : aucune brique de rendu PDF n'est
ajoutée par cette tranche. ``docs/departements/M3-audit.md`` §3.3 documente WeasyPrint
(BSD-3-Clause) et Typst (Apache-2.0) comme pistes retenues pour une Phase 2, mais les ajouter
exige un paquet système (Pango/cairo pour WeasyPrint) hors de portée d'un simple câblage — et le
mandat de cette tranche autorise explicitement le repli : « sinon livre un brouillon structuré
(HTML ou texte) et dis-le ». Un brouillon HTML reste imprimable par le navigateur du vendeur
(Ctrl+P -> PDF) en attendant cette décision, documentée mais non prise ici. Aucune nouvelle
dépendance : stdlib seule (``html.escape`` contre l'injection d'un champ texte libre comme
``description``).

Séparation coût/prix (audit M3 §2.1, même règle que ``devis_durable.projeter_devis(role=
"employe")`` et ``devis_durable.charge_evenement_devis_accepte``) : le brouillon ne reprend QUE
``reference_ligne``, ``description``, ``quantite``, ``unite``, ``prix_unitaire``, ``prix_ligne``
par ligne, plus ``prix_total`` — JAMAIS ``cout_unitaire``/``cout_ligne``/``cout_total``/
``taux_marge``, quelle que soit la vue du devis reçue en entrée (même une vue "interne" complète
qui les porterait) : ce module les OMET lui-même, il ne fait pas confiance à l'appelant pour les
avoir déjà filtrés.

AUCUN ENVOI : ce module rend une CHAÎNE, il ne transmet rien à personne (SOUL.md : « Envoyer un
devis au client sans approbation : c'est une action externe » — l'envoi reste GATÉ, T1.3,
approbations du socle, absent de ce paquet par construction). Module pur (ADR-0009) : aucun import
``opsys``, aucune horloge interne (l'horodatage affiché est celui DÉJÀ porté par le devis, jamais
relu depuis une horloge), aucun accès réseau.
"""

from __future__ import annotations

from html import escape
from typing import Any

from . import verdicts

__all__ = ["generer_brouillon_html"]

_CLES_DEVIS_REQUISES = frozenset({"devis_id", "lead_id", "statut", "horodatage", "lignes", "prix_total"})
_CLES_LIGNE_CLIENT = ("reference_ligne", "description", "quantite", "unite", "prix_unitaire", "prix_ligne")


def _ligne_html(ligne: Any) -> tuple[str | None, dict | None]:
    if not isinstance(ligne, dict) or not set(_CLES_LIGNE_CLIENT).issubset(ligne):
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-LIGNE-INVALIDE",
            detail="ligne sans les clés client attendues : " + ", ".join(_CLES_LIGNE_CLIENT),
        )
    return (
        "<tr>"
        f"<td>{escape(str(ligne['description']))}</td>"
        f"<td>{escape(str(ligne['quantite']))} {escape(str(ligne['unite']))}</td>"
        f"<td>{escape(str(ligne['prix_unitaire']))} $ CAD</td>"
        f"<td>{escape(str(ligne['prix_ligne']))} $ CAD</td>"
        "</tr>"
    ), None


def generer_brouillon_html(devis: dict[str, Any]) -> tuple[str | None, dict | None]:
    """Assemble le brouillon HTML depuis un devis (état courant de ``devis_durable``), ou rend un
    verdict nommé si ``devis`` est structurellement inexploitable. Ne calcule ni prix ni total :
    reprend TEL QUEL ce que ``devis_durable.creer_devis`` a déjà calculé et arrondi."""
    if not isinstance(devis, dict) or not _CLES_DEVIS_REQUISES.issubset(devis):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="devis doit porter au moins " + ", ".join(sorted(_CLES_DEVIS_REQUISES)),
        )
    lignes = devis.get("lignes")
    if not isinstance(lignes, list) or not lignes:
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-LIGNES-VIDES", detail="au moins une ligne est requise pour générer un brouillon"
        )

    lignes_html: list[str] = []
    for ligne in lignes:
        rendu, verdict = _ligne_html(ligne)
        if verdict is not None:
            return None, verdict
        lignes_html.append(rendu)

    devis_id = escape(str(devis["devis_id"]))
    document = (
        "<!doctype html>"
        '<html lang="fr-CA"><head><meta charset="utf-8">'
        f"<title>Soumission brouillon {devis_id}</title></head><body>"
        "<p><strong>BROUILLON — non envoyé, sujet à approbation. Ceci n'est pas un engagement "
        "contractuel.</strong></p>"
        f"<h1>Soumission — {devis_id}</h1>"
        f"<p>Statut : {escape(str(devis['statut']))} — daté du {escape(str(devis['horodatage']))}</p>"
        '<table border="1" cellspacing="0" cellpadding="4">'
        "<thead><tr><th>Description</th><th>Quantité</th><th>Prix unitaire</th><th>Prix</th></tr></thead>"
        "<tbody>" + "".join(lignes_html) + "</tbody>"
        "</table>"
        f"<p><strong>Prix total : {escape(str(devis['prix_total']))} $ CAD, taxes (TPS/TVQ) en "
        "sus.</strong></p>"
        "</body></html>"
    )
    return document, None
