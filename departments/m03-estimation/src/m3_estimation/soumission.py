"""Brouillon de soumission client de M3 (PLAN T2.3, DEFINITION-PRODUIT.md §7-M3 M3.13).

Rend un texte HTML STRUCTURÉ et LISIBLE depuis un devis durable déjà assemblé
(``devis_durable.creer_devis``/``lire_devis``). Le rendu PDF (PLAN T2.3-f) vit dans
``soumission_pdf.py`` et part du MÊME contenu : ``contenu_client`` est la seule porte par laquelle un
devis devient un document pour le client, pour les deux formats. Aucune brique de rendu ici : stdlib
seule (``html.escape`` contre l'injection d'un champ texte libre comme ``description``).

Séparation coût/prix (audit M3 §2.1, même règle que ``devis_durable.projeter_devis(role=
"employe")`` et ``devis_durable.charge_evenement_devis_accepte``) : le document ne reprend QUE
``reference_ligne``, ``description``, ``quantite``, ``unite``, ``prix_unitaire``, ``prix_ligne``
par ligne, plus ``prix_total`` — JAMAIS ``cout_unitaire``/``cout_ligne``/``cout_total``/
``taux_marge``, quelle que soit la vue du devis reçue en entrée (même une vue "interne" complète
qui les porterait) : ``contenu_client`` les OMET elle-même (liste blanche), elle ne fait pas
confiance à l'appelant pour les avoir déjà filtrés.

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
from .modeles_soumission import valider_modele_fige

__all__ = ["MENTION_BROUILLON", "contenu_client", "generer_brouillon_html"]

# Mention portée par TOUT brouillon, en HTML comme en PDF. Aucune donnée d'approbation n'existe encore
# dans le devis (statuts brouillon/envoye/accepte seulement) : la mention n'est donc jamais levée ici.
MENTION_BROUILLON = "BROUILLON — non envoyé, sujet à approbation. Ceci n'est pas un engagement contractuel."

_CLES_DEVIS_REQUISES = frozenset({"devis_id", "lead_id", "statut", "horodatage", "lignes", "prix_total"})
_CLES_LIGNE_CLIENT = ("reference_ligne", "description", "quantite", "unite", "prix_unitaire", "prix_ligne")


def _ligne_client(ligne: Any) -> tuple[dict[str, Any] | None, dict | None]:
    if not isinstance(ligne, dict) or not set(_CLES_LIGNE_CLIENT).issubset(ligne):
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-LIGNE-INVALIDE",
            detail="ligne sans les clés client attendues : " + ", ".join(_CLES_LIGNE_CLIENT),
        )
    return {cle: ligne[cle] for cle in _CLES_LIGNE_CLIENT}, None


def contenu_client(devis: dict[str, Any]) -> tuple[dict[str, Any] | None, dict | None]:
    """Extrait du devis, par LISTE BLANCHE, ce qu'un document pour le client peut porter : identité et
    statut du devis, date, lignes (clés client seulement), prix total. Les valeurs restent celles du
    devis, TELLES QUELLES (aucun calcul, aucun arrondi) ; tout le reste — coût, marge, lead, chantier —
    est omis. Rend un verdict nommé si ``devis`` est structurellement inexploitable."""
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

    lignes_client: list[dict[str, Any]] = []
    for ligne in lignes:
        retenue, verdict = _ligne_client(ligne)
        if verdict is not None:
            return None, verdict
        lignes_client.append(retenue)
    resultat = {
        "devis_id": devis["devis_id"],
        "statut": devis["statut"],
        "horodatage": devis["horodatage"],
        "lignes": lignes_client,
        "prix_total": devis["prix_total"],
    }
    if "modele_soumission" in devis:
        modele = devis["modele_soumission"]
        if not valider_modele_fige(modele):
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE", detail="modèle de soumission figé invalide"
            )
        resultat["modele_soumission"] = {cle: modele[cle] for cle in ("titre", "description", "clauses")}
    return resultat, None


def _modele_html(modele: dict[str, str] | None) -> str:
    if modele is None:
        return ""
    return (
        '<section class="modele-soumission">'
        f'<h2>{escape(modele["titre"])}</h2>'
        f'<div style="white-space: pre-wrap">{escape(modele["description"])}</div>'
        '<h3>Clauses</h3>'
        f'<div style="white-space: pre-wrap">{escape(modele["clauses"])}</div>'
        '</section>'
    )


def _ligne_html(ligne: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(ligne['description']))}</td>"
        f"<td>{escape(str(ligne['quantite']))} {escape(str(ligne['unite']))}</td>"
        f"<td>{escape(str(ligne['prix_unitaire']))} $ CAD</td>"
        f"<td>{escape(str(ligne['prix_ligne']))} $ CAD</td>"
        "</tr>"
    )


def generer_brouillon_html(devis: dict[str, Any]) -> tuple[str | None, dict | None]:
    """Assemble le brouillon HTML depuis un devis (état courant de ``devis_durable``), ou rend un
    verdict nommé si ``devis`` est structurellement inexploitable. Ne calcule ni prix ni total :
    reprend TEL QUEL ce que ``devis_durable.creer_devis`` a déjà calculé et arrondi."""
    contenu, verdict = contenu_client(devis)
    if verdict is not None:
        return None, verdict

    devis_id = escape(str(contenu["devis_id"]))
    document = (
        "<!doctype html>"
        '<html lang="fr-CA"><head><meta charset="utf-8">'
        f"<title>Soumission brouillon {devis_id}</title></head><body>"
        f"<p><strong>{escape(MENTION_BROUILLON, quote=False)}</strong></p>"
        f"<h1>Soumission — {devis_id}</h1>"
        f"<p>Statut : {escape(str(contenu['statut']))} — daté du {escape(str(contenu['horodatage']))}</p>"
        + _modele_html(contenu.get("modele_soumission")) +
        '<table border="1" cellspacing="0" cellpadding="4">'
        "<thead><tr><th>Description</th><th>Quantité</th><th>Prix unitaire</th><th>Prix</th></tr></thead>"
        "<tbody>" + "".join(_ligne_html(ligne) for ligne in contenu["lignes"]) + "</tbody>"
        "</table>"
        f"<p><strong>Prix total : {escape(str(contenu['prix_total']))} $ CAD, taxes (TPS/TVQ) en "
        "sus.</strong></p>"
        "</body></html>"
    )
    return document, None
