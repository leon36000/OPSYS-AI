"""Charges FICTIVES conformes au catalogue pour les tests d'interconnexion des départements.

Chaque fabrique rend la charge qu'un producteur réel publierait (validée par `opsys.evenements.schemas.erreurs_charge` à
l'appel : une donnée de test non conforme au catalogue échoue ici, pas plus loin). Aucune donnée réelle : courriels en
`@example.test`, identifiants synthétiques. `publier_depuis` publie sur le VRAI bus avec un `evenement_id` choisi par
l'appelant (pour rejouer le même constat sous un autre identifiant).
"""

from __future__ import annotations

import hashlib
from typing import Any

from opsys import evenements
from opsys.evenements.schemas import erreurs_charge

FICTIF = True


def _valide(type_evenement: str, charge: dict[str, Any]) -> dict[str, Any]:
    erreurs = erreurs_charge(type_evenement, charge)
    assert erreurs == [], f"charge de test non conforme au catalogue {type_evenement} : {erreurs}"
    return charge


def empreinte(*parties: str) -> str:
    return hashlib.sha256("|".join(parties).encode()).hexdigest()


def signaux_marketing(
    source: str = "search_console", fin: str = "2026-10-28", lu_le: str = "2026-10-29T06:00:00-04:00", **plus: Any
) -> dict[str, Any]:
    charge = {
        "source": source,
        "compte_ref": "compte-fictif-1",
        "flux": "performance",
        "mode": "api_lecture",
        "periode_debut": "2026-10-22",
        "periode_fin": fin,
        "faits_nouveaux": 12,
        "faits_revises": 1,
        "faits_inchanges": 3,
        "derniere_lecture_reussie_le": lu_le,
        "donnees_jusqu_au": fin,
        "fraicheur_fenetre_h": 48,
        "fictif": False,
    }
    charge.update(plus)
    return _valide("m7.signaux_marketing_constates", charge)


def depense_marketing(
    releve_id: str = "releve-google-2026-10-27",
    revision: int = 1,
    canal: str = "google_ads",
    jour: str = "2026-10-27",
    montant: str = "125.40",
    base: str = "HORS_TAXES",
    **plus: Any,
) -> dict[str, Any]:
    charge = {
        "releve_id": releve_id,
        "revision": revision,
        "canal": canal,
        "periode_debut": jour,
        "periode_fin": jour,
        "montant_cad": montant,
        "devise": "CAD",
        "base_taxes": base,
        "source": "RELEVE_PLATEFORME",
        "releve_le": "2026-10-28T06:00:00-04:00",
    }
    charge.update(plus)
    return _valide("m7.depenses_marketing_constatees", charge)


def anomalie_depense(
    anomalie_id: str = "a" * 32, severite: str = "attention", regle: str = "DEP-01", **plus: Any
) -> dict[str, Any]:
    charge = {
        "anomalie_id": anomalie_id,
        "canal": "google_ads",
        "campagne_ref": "campagne-fictive-1",
        "regle": regle,
        "severite": severite,
        "valeur": "310.50",
        "seuil": "200.00",
        "unite": "CAD",
        "jour_debut": "2026-10-27",
        "jour_fin": "2026-10-27",
        "detectee_le": "2026-10-28T07:00:00-04:00",
        "fictif": False,
    }
    charge.update(plus)
    return _valide("m7.anomalie_depense_detectee", charge)


def conversion_hors_ligne(
    conversion_id: str = "conv-fictive-1",
    lead_id: str = "lead-fictif-1",
    type_: str = "rendez_vous",
    source: str | None = "google",
    **plus: Any,
) -> dict[str, Any]:
    charge = {
        "conversion_id": conversion_id,
        "lead_id": lead_id,
        "type": type_,
        "convertie_le": "2026-10-26",
        "utm_source": source,
        "utm_medium": "cpc" if source else None,
        "utm_campaign": "toitures-hiver" if source else None,
        "valeur_cad": "4500.00",
        "source_normalisee": source is not None,
        "importee_le": "2026-10-27T09:00:00-04:00",
    }
    charge.update(plus)
    return _valide("m7.conversion_hors_ligne_importee", charge)


def mesures_comptables(jour: str = "2026-10-30", version: str = "0123456789abcdef", **plus: Any) -> dict[str, Any]:
    charge = {
        "date_reference": jour,
        "version_donnees": version,
        "creances": {
            "nombre": 3,
            "total": "7210.55",
            "par_tranche": {"0-30": "4000.00", "31-60": "2210.55", "61-90": "1000.00", "90+": "0.00"},
        },
        "relances_en_brouillon": 2,
        "brouillons_en_attente": 4,
        "ecritures_definitives": 12,
        "derniere_periode_close": "2026-09",
        "paiements_prepares": {"nombre": 1, "total": "459.91"},
        "rapprochements": {"prepares": 2, "confirmes": 1, "a_ecart": 0},
        "notes_de_credit": {"nombre": 0, "total": "0.00"},
        "depenses_employes": {"nombre": 1, "total": "32.10"},
        "pieces_liees": 5,
    }
    charge.update(plus)
    return _valide("m5.mesures_comptables_constatees", charge)


def mesure_vision(candidat_id: str = "cand-fictif-1", lead_id: str = "lead-fictif-1", **plus: Any) -> dict[str, Any]:
    charge = {
        "lead_id": lead_id,
        "candidat_id": candidat_id,
        "photo_id": "photo-fictive-1",
        "objet": "facade_nord",
        "grandeur": "surface",
        "unite": "m2",
        "valeur_retenue": "42.5",
        "incertitude_emploi": "0.5",
        "origine_valeur": "vision_validee_par_reference",
        "voie": "reference",
        "decision_empreinte": empreinte("decision", candidat_id),
        "modele": {"identifiant": "detecteur-fictif", "version": "1"},
    }
    charge.update(plus)
    return _valide("m3.mesure_vision_validee", charge)


def rapprochement_po(
    facture: str = "ff-fictive-1", po_id: str = "po-fictif-1", verdict: str = "CONCORDANT", **plus: Any
) -> dict[str, Any]:
    charge = {
        "facture_fournisseur_id": facture,
        "po_id": po_id,
        "verdict": verdict,
        "sens": None,
        "facture_avant_taxes": "1200.00",
        "recu_avant_taxes": "1200.00",
        "ecart_avant_taxes": "0.00",
        "reserves": ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"],
        "date_reference": "2026-10-30",
    }
    charge.update(plus)
    return _valide("m5.rapprochement_po_constate", charge)


def dossier_cpa(dossier_id: str = "dossier-2026-09", **plus: Any) -> dict[str, Any]:
    charge = {
        "dossier_id": dossier_id,
        "periode_debut": "2026-09-01",
        "periode_fin": "2026-09-30",
        "scelle": empreinte("dossier", dossier_id),
        "fichiers": 9,
        "liste_de_controle": {"FAIT": 7, "A_FAIRE": 1, "A_VERIFIER": 2},
        "statut": "BROUILLON_POUR_CPA",
        "date_reference": "2026-10-05",
    }
    charge.update(plus)
    return _valide("m5.dossier_cpa_scelle", charge)


def creance_relance(
    relance_id: str = "relance-fictive-1",
    facture_id: str = "fc-fictive-1",
    client_id: str = "client-fictif-1",
    niveau: int = 1,
    **plus: Any,
) -> dict[str, Any]:
    charge = {
        "relance_id": relance_id,
        "facture_id": facture_id,
        "client_id": client_id,
        "niveau": niveau,
        "jours_retard": 12,
        "montant_du": "2300.00",
        "echeance": "2026-10-18",
        "date_reference": "2026-10-30",
    }
    charge.update(plus)
    return _valide("m5.creance_relance_preparee", charge)


def contexte_site(lead_id: str = "lead-fictif-1", version: int = 1, **plus: Any) -> dict[str, Any]:
    charge = {
        "lead_id": lead_id,
        "service": "toiture",
        "version": version,
        "empreinte": empreinte("site", lead_id, str(version)),
        "date_reference": "2026-10-30",
        "facteurs": [
            {"facteur": "type_batiment", "statut": "connu", "valeur": "unifamiliale"},
            {"facteur": "permis", "statut": "a_verifier", "valeur": None},
        ],
        "inconnus": ["acces_toit"],
        "a_verifier": ["permis"],
        "conflits": [],
    }
    charge.update(plus)
    return _valide("m3.contexte_site_pret", charge)


def profil_propriete(
    propriete_id: str | None = None, revision: int = 1, client_id: str | None = None, **plus: Any
) -> dict[str, Any]:
    propriete_id = propriete_id or empreinte("propriete", "fictive-1")
    charge = {
        "fait_id": empreinte("m2-propriete-confirmee-v1", propriete_id, str(revision)),
        "client_id": client_id or empreinte("client", "fictif-1"),
        "propriete_id": propriete_id,
        "revision": revision,
        "ville": "Québec",
        "type_batiment": "unifamiliale",
        "etages": 2,
        "annee_construction": 1987,
        "nb_photos_liees": 3,
        "nb_mesures_liees": 1,
        "horodatage": "2026-10-30T10:00:00-04:00",
    }
    charge.update(plus)
    return _valide("m2.profil_propriete_confirme", charge)


def message_client(
    intervention_id: str = "interv-fictive-1", lead_id: str = "lead-fictif-1", canal: str = "courriel", **plus: Any
) -> dict[str, Any]:
    charge = {
        "intervention_id": intervention_id,
        "lead_id": lead_id,
        "canal": canal,
        "fenetre_debut": "2026-11-03T09:00:00-05:00",
        "fenetre_fin": "2026-11-03T11:00:00-05:00",
        "texte": "Bonjour, notre équipe prévoit arriver entre 9 h et 11 h le 3 novembre. C'est une estimation, pas une "
        "promesse. Répondez STOP pour ne plus recevoir ces messages.",
        "statut": "brouillon",
        "envoi": "n3_requis_via_m1",
        "consentement_ligne_id": "consent-fictif-1",
        "conserve_jusqu_au": "2026-11-10T00:00:00-05:00",
    }
    charge.update(plus)
    return _valide("m4.message_client_brouillon_pret", charge)


def client_associe(lead_id: str = "lead-fictif-1", client_id: str | None = None, **plus: Any) -> dict[str, Any]:
    charge = {
        "lead_id": lead_id,
        "client_id": client_id or empreinte("client", "fictif-1"),
        "horodatage_association": "2026-10-28T09:00:00-04:00",
    }
    charge.update(plus)
    return _valide("m2.client_associe", charge)


def _mesure(
    metric_id: str, statut: str = "calculee", fraicheur: str = "a_jour", valeur: str | None = "12.50"
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "nom": "Mesure fictive " + metric_id,
        "domaine": "ventes",
        "unite": "CAD",
        "proprietaire": "m08-analytics",
        "statut": statut,
        "valeur": valeur if statut == "calculee" else None,
        "version_definition": empreinte("def", metric_id),
        "dernier_fait_le": "2026-10-30T09:00:00-04:00",
        "fraicheur": fraicheur,
    }


def fait_consolide(graine: str = "a", **plus: Any) -> dict[str, Any]:
    registres = empreinte("registres", graine)
    charge = {
        "evenement_id": "m8-faits-" + empreinte("m8-faits", registres, "catalogue"),
        "consolide_le": "2026-10-31T06:30:00-04:00",
        "empreinte_registres": registres,
        "version_catalogue": empreinte("catalogue"),
        "premiere_consolidation": True,
        "mesures": [
            _mesure("m8_taux_acceptation"),
            _mesure("m8_marge_reelle", "non_calculable", "manquant"),
            _mesure("m8_delai_acceptation", fraicheur="perime"),
        ],
        "changements_definition": [
            {"metric_id": "m8_taux_acceptation", "ancienne": empreinte("a"), "nouvelle": empreinte("b")}
        ],
        "anomalies": [{"metric_id": "m8_delai_acceptation", "type": "perimee"}],
        "mention": "Mesures d'entreprise consolidées par M8 ; les registres des départements propriétaires font foi.",
    }
    charge.update(plus)
    return _valide("m8.fait_consolide", charge)


def publier_depuis(
    producteur: str, type_evenement: str, charge: dict[str, Any], evenement_id: str | None = None
) -> str:
    """Publie sur le VRAI bus (outbox) ; la charge est validée par le catalogue à la publication."""
    return evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)
