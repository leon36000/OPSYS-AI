"""Charges FICTIVES conformes au catalogue pour les tests d'interconnexion des départements.

Chaque fabrique rend la charge qu'un producteur réel publierait (validée par `opsys.evenements.schemas.erreurs_charge` à
l'appel : une donnée de test non conforme au catalogue échoue ici, pas plus loin). Aucune donnée réelle : courriels en
`@example.test`, identifiants synthétiques. `publier_depuis` publie sur le VRAI bus avec un `evenement_id` choisi par
l'appelant (pour rejouer le même constat sous un autre identifiant).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
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


def apprentissage_marketing(variante: int = 1, **plus: Any) -> dict[str, Any]:
    """Une observation d'apprentissage marketing de M7 (M7-MEMOIRE) : un contenu gagnant, `variante` en change la
    clé."""
    cle = f"facebook-{variante:016x}"
    charge = {
        "observation_id": "m7-appr-" + empreinte("appr", str(variante))[:40],
        "semaine": "2026-10-26",
        "genre_observation": "contenu_gagnant",
        "canal": "facebook",
        "cle_mesure": cle,
        "resultat": {"leads": 3, "devis_envoyes": 2, "devis_acceptes": 1, "occurrences": None, "avis_positifs": None,
                     "avis_negatifs": None},
        "rapport_empreinte": empreinte("rapport", str(variante)),
    }
    charge.update(plus)
    return _valide("m7.apprentissage_marketing_constate", charge)


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


def consentement_suivi_retire(
    intervention_id: str = "interv-fictive-1",
    lead_id: str = "lead-fictif-1",
    canal: str = "courriel",
    retire_le: str = "2026-11-02T09:00:00-05:00",
    consentement_ligne_id: str | None = "consent-fictif-1",
    **plus: Any,
) -> dict[str, Any]:
    charge = {
        "intervention_id": intervention_id,
        "lead_id": lead_id,
        "canal": canal,
        "retire_le": retire_le,
        "consentement_ligne_id": consentement_ligne_id,
    }
    charge.update(plus)
    return _valide("m4.consentement_suivi_retire", charge)


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


def travaux_termines(wct_id: str = "wct-fictif-1", devis_id: str | None = "devis-fictif-1", minutes: int = 120,
                     **plus: Any) -> dict[str, Any]:
    """Un chantier terminé de M4 (charge du catalogue ; le technicien est un identifiant fictif de M4)."""
    charge = {
        "wct_id": wct_id, "intervention_id": "int-" + wct_id, "lead_id": "lead-" + wct_id,
        "technicien_id": "tech-fictif-a", "horodatage_completion": "2026-10-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5}, "duree_reelle_minutes": minutes,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "deadbeef", "consommateurs_cibles": ["M8"],
        "devis_id": devis_id, "statut": "completed_verified",
    }
    charge.update(plus)
    return _valide("m4.travaux_termines", charge)


def devis_accepte(devis_id: str = "devis-fictif-1", prix: str = "10000.00", cout: str = "7000.00",
                  **plus: Any) -> dict[str, Any]:
    charge = {
        "devis_id": devis_id, "lead_id": "lead-" + devis_id, "chantier_id": None,
        "lignes": [{
            "reference_ligne": devis_id + "-L0", "description": "Gouttières (fictif)", "quantite": "40", "unite": "pi",
            "prix_unitaire": "250.00", "prix_ligne": prix, "reference_besoin_materiau": None,
        }],
        "cout_total": cout, "prix_total": prix, "taux_marge": "0.30", "duree_estimee_minutes": "100",
        "horodatage_acceptation": "2026-10-20T09:00:00-04:00",
    }
    charge.update(plus)
    return _valide("m3.devis_accepte", charge)


def rentabilite(wct_id: str = "wct-fictif-1", devis_id: str = "devis-fictif-1", sequence: int = 1,
                marge: str | None = "3200.00", definitif: bool = True, **plus: Any) -> dict[str, Any]:
    """Trace de rentabilité de M5 : CALCULÉE (marge chiffrée) ou PARTIELLE (`marge=None`, aucune marge ne part)."""
    calculee = marge is not None
    charge = {
        "evenement_id": f"m5-rentabilite-{devis_id}-{sequence}-{empreinte('v', wct_id, str(sequence))[:16]}",
        "devis_id": devis_id, "chantier_id": None, "wct_id": wct_id, "sequence": sequence,
        "version_entrees": empreinte("entrees", wct_id, str(sequence)),
        "horodatage_completion": "2026-10-28T14:00:00-04:00", "verdict": "CALCULEE" if calculee else "PARTIELLE",
        "devise": "CAD", "prix_definitif": definitif, "cout_reel_complet": calculee,
        "cout_reel_cad": "6800.00" if calculee else None, "cout_connu_cad": "6800.00" if calculee else "3000.00",
        "marge_reelle_cad": marge, "marge_prevue_cad": "3000.00" if calculee else None,
        "ecart_marge_cad": None, "manque": [] if calculee else ["REJ-COUT-MATERIAUX-MANQUANTS"],
    }
    if calculee:
        charge["ecart_marge_cad"] = "200.00"
    charge.update(plus)
    return _valide("m5.rentabilite_chantier", charge)


def cash_libre(sequence: int = 1, jour: str = "2026-10-29", comptes_a_payer: str | None = "459.91",
               **plus: Any) -> dict[str, Any]:
    """Constat du cash libre de M5 (seules les composantes utiles : solde et comptes à payer ; le reste à 100,00)."""
    libelles = {"taxes_a_remettre": "TPS/TVQ", "paies": "Paies", "das": "DAS", "comptes_a_payer": "Comptes à payer",
                "dettes": "Dettes", "reserves": "Réserves"}

    def composante(cid: str, montant: str | None, calculee: bool = True) -> dict[str, Any]:
        registres = [{"registre": "mouvements", "taille": 3, "tete": "0123456789abcdef"}] if calculee else []
        return {
            "id": cid, "libelle": libelles.get(cid, "solde"), "statut": "CALCULE" if calculee else "NON_CALCULABLE",
            "montant_cad": montant, "plancher_cad": None if calculee else "300.00",
            "source": {"origine": "REGISTRE" if calculee else "AUCUNE", "registres": registres},
            "fraicheur": {"derniere_piece": "2026-09-14" if calculee else None, "pieces": 1 if calculee else 0},
        }

    complet = comptes_a_payer is not None
    composantes = [
        composante(cid, comptes_a_payer if cid == "comptes_a_payer" else "100.00", complet or cid != "comptes_a_payer")
        for cid in libelles
    ]
    charge = {
        "evenement_id": f"m5-cash-libre-{sequence}-{jour}-aaaaaaaaaaaaaaaa", "sequence": sequence,
        "date_reference": jour,
        "version_donnees": empreinte("cash", str(sequence), jour), "devise": "CAD",
        "statut": "CALCULE" if complet else "NON_CALCULABLE", "cash_libre_cad": "1000.00" if complet else None,
        "au_plus_cad": None if complet else "1200.00", "en_deficit": False if complet else None,
        "lecture": "Cash libre fictif.", "solde": composante("solde", "5000.00"), "composantes": composantes,
        "manque": [] if complet else [{"composante": "comptes_a_payer", "code": "REJ-CASH-AP-INCOMPLET"}],
        "reserves": [], "hypotheses": [],
        "mention": "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision "
                   "officielle ou action réelle.",
    }
    charge.update(plus)
    return _valide("m5.cash_libre_constate", charge)


def reception_m6(po_id: str = "po-fictif-1", rang: int = 1, verdict: str = "CONFORME", **plus: Any) -> dict[str, Any]:
    """Une réception de M6 (le fournisseur et les lignes voyagent dans la charge : M8 n'en garde rien)."""
    charge = {
        "evenement_id": f"m6-reception-{po_id}-{rang}", "po_id": po_id, "fournisseur_id": "fournisseur-fictif-x",
        "chantier_id": "chantier-fictif-1", "horodatage_reception": f"2026-10-2{rang}T11:00:00-04:00",
        "verdict_reception": verdict, "statut_po": "received", "hash_maillon": f"{rang:064x}",
        "seuil_ecart_prix_pourcentage": None,
        "lignes": [{
            "materiau_id": "materiau-fictif", "quantite_demandee": "10", "quantite_recue": "10",
            "prix_unitaire_prevu": "12.50", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
            "prix_unitaire_reception": "12.50", "verdict_prix_reception": "PRIX_CATALOGUE",
            "ecart_prix_critique": False,
        }],
    }
    charge.update(plus)
    return _valide("m6.reception_enregistree", charge)


def commande_envoyee(po_id: str = "po-fictif-1", rang: int = 1, **plus: Any) -> dict[str, Any]:
    """Un bon de commande de M6 dont le courriel est parti (M1 est le canal ; ni adresse ni texte dans la charge)."""
    charge = {
        "po_id": po_id, "brouillon_id": f"brouillon-{po_id}-{rang}", "empreinte": empreinte("courriel", po_id),
        "envoye_le": f"2026-10-2{rang}T10:00:00-04:00",
    }
    charge.update(plus)
    return _valide("m1.commande_courriel_envoyee", charge)


def lead_qualifie_m1(lead_id: str = "lead-fictif-1", **plus: Any) -> dict[str, Any]:
    """Une demande qualifiée par M1 : la charge porte le CONTACT (nom, courriel, téléphone fictifs) que M8 ne garde
    pas."""
    charge = {
        "lead": {
            "schema_version": 2, "lead_id": lead_id, "conversation_id": "conv-" + lead_id,
            "contact": {
                "nom": "Jeanne Fictive", "courriel": "jeanne.fictive@example.test", "telephone": "514-555-0199",
            },
            "service": "toiture", "ville": "Québec", "urgence_declaree": False, "canal": "courriel",
        },
        "horodatage": "2026-10-28T08:00:00-04:00", "signal_id": "courriel:" + lead_id,
    }
    charge.update(plus)
    return _valide("m1.lead_qualifie", charge)


# -- Phase 2 (D1 à D3, docs/architecture/M8-ENTREPOT-SOURCES.md) : les résumés agrégés que les producteurs publient
# pour M8 ----
def depense_comptabilisee(
    sequence: int = 1, debut: str = "2026-10-28", fin: str = "2026-10-30", comptabilise: str = "300.00", **plus: Any
) -> dict[str, Any]:
    charge = {
        "evenement_id": f"m5-depense-pub-{sequence}-{debut}-{fin}-{sequence:016x}",
        "sequence": sequence,
        "date_reference": fin,
        "periode_debut": debut,
        "periode_fin": fin,
        "version_donnees": f"{sequence:016x}",
        "devise": "CAD",
        "base_taxes": "HORS_TAXES",
        "comptabilise_cad": comptabilise,
        "ecritures_definitives": 3,
        "brouillons_en_attente": 2,
        "brouillons_en_attente_cad": "113.75",
    }
    charge.update(plus)
    return _valide("m5.depense_publicitaire_constatee", charge)


def facture_emise(
    facture_id: str = "facture-fictive-1", statut: str = "ENVOYEE", avant: str = "1000.00", **plus: Any
) -> dict[str, Any]:
    charge = {
        "evenement_id": f"m5-facture-emise-{facture_id}-{statut}",
        "facture_id": facture_id,
        "statut": statut,
        "emise_le": "2026-10-29",
        "devise": "CAD",
        "montant_avant_taxes_cad": avant,
        "total_taxes_cad": "149.75",
        # le total avec taxes est le montant avant taxes plus les taxes : le contrôle de qualité de M8 (C4) bloque une
        # facture dont le total n'est pas cette somme, et une donnée fictive incohérente serait bloquée à tort
        "montant_apres_taxes_cad": str(Decimal(avant) + Decimal("149.75")),
    }
    charge.update(plus)
    return _valide("m5.facture_emise_constatee", charge)


def performance_signaux(
    source: str = "search_console", version: str = "a" * 16, clics: str | None = "120", **plus: Any
) -> dict[str, Any]:
    charge = {
        "evenement_id": f"m7-perf-{source}-site-fictif-2026-10-24-2026-10-30-{version}",
        "source": source,
        "compte_ref": "site-fictif",
        "periode_debut": "2026-10-24",
        "periode_fin": "2026-10-30",
        "jours_periode": 7,
        "jours_couverts": 7,
        "clics": clics,
        "impressions": "4300",
        "visites": None,
        "derniere_observation_le": "2026-10-30T06:00:00-04:00",
        "fraicheur_fenetre_h": 48,
        "fictif": False,
        "version_donnees": version,
    }
    charge.update(plus)
    return _valide("m7.performance_signaux_constatee", charge)


def capacite_equipe(
    semaine: str = "2026-10-26", version: str = "b" * 16, constate_le: str = "2026-10-30T07:00:00-04:00", **plus: Any
) -> dict[str, Any]:
    charge = {
        "evenement_id": f"m4-capacite-{semaine}-journees_datees_seulement-{version}-{constate_le[11:13]}",
        "semaine_debut": semaine,
        "portee": "journees_datees_seulement",
        "calculable": True,
        "heures_disponibles": "80",
        "heures_planifiees": "62",
        "manque": [],
        "constate_le": constate_le,
        "version_donnees": version,
    }
    charge.update(plus)
    return _valide("m4.capacite_equipe_constatee", charge)


def pipeline_constate(
    jour: str = "2026-10-30", version: str = "c" * 16, constate_le: str = "2026-10-30T07:00:00-04:00", **plus: Any
) -> dict[str, Any]:
    charge = {
        "evenement_id": f"m2-pipeline-{jour}-{version}-{constate_le[11:13]}",
        "date_reference": jour,
        "constate_le": constate_le,
        "version_donnees": version,
        "total": 40,
        "ouverts": 12,
        "par_statut": {"nouveau": 4, "qualifie": 8, "converti": 9, "perdu": 15},
        "convertis_un_jour": 9,
        "perdus": 15,
        "resolus": 24,
        "taux_conversion_resolus_pct": "37.50",
        "valeur_ponderee_cad": "41250.00",
    }
    charge.update(plus)
    return _valide("m2.pipeline_constate", charge)


def disponibilite_constatee(
    jour: str = "2026-10-30", version: str = "d" * 16, constate_le: str = "2026-10-30T07:00:00-04:00", **plus: Any
) -> dict[str, Any]:
    charge = {
        "evenement_id": f"m6-disponibilite-{jour}-{version}-{constate_le[11:13]}",
        "date_reference": jour,
        "constate_le": constate_le,
        "version_donnees": version,
        "articles_suivis": 42,
        "articles_en_rupture": 3,
        "articles_sur_reserves": 1,
        "reservations_actives": 5,
        "reservations_incompletes": 2,
    }
    charge.update(plus)
    return _valide("m6.disponibilite_constatee", charge)


def plaintes_constatees(
    jour: str = "2026-10-30",
    jours: int = 30,
    empreinte_contenu: str = "ab" * 32,
    etat: str = "CONNUE",
    nombre: int | None = 2,
    **plus: Any,
) -> dict[str, Any]:
    charge = {
        "evenement_id": f"m1-plaintes-{jour}-{jours}-{empreinte_contenu[:16]}",
        "date_reference": jour,
        "jours": jours,
        "etat": etat,
        "nombre": nombre if etat == "CONNUE" else None,
        "empreinte_contenu": empreinte_contenu,
    }
    charge.update(plus)
    return _valide("m1.plaintes_constatees", charge)


def preaudit_constate(
    jour: str = "2026-10-30",
    version: str = "0123456789abcdef",
    constate_le: str = "2026-10-30T07:00:00-04:00",
    **plus: Any,
) -> dict[str, Any]:
    """Le résumé du pré-audit de M5 : des comptes par règle (null pour une règle non évaluée), jamais une facture ni un
    montant."""
    par_regle = {
        "FACTURE_SANS_PAIEMENT": 1,
        "PAIEMENT_SANS_FACTURE": 0,
        "DEPENSE_SANS_RECU": 2,
        "TAXE_INCOHERENTE": 0,
        "DOUBLON_PROBABLE": 1,
        "TRANSACTION_HORS_NORME": None,
        "FACTURE_MODIFIEE": 0,
        "CHANGEMENT_COMPTE_INHABITUEL": None,
        "PISTE_AUDIT_INCOMPLETE": 0,
        "DOCUMENT_MANQUANT": 0,
    }
    charge = {
        "evenement_id": f"m5-preaudit-{jour}-{version}-{hashlib.sha256(constate_le.encode()).hexdigest()[:8]}",
        "date_reference": jour,
        "constate_le": constate_le,
        "version_donnees": version,
        "constats_par_regle": par_regle,
        "constats_total": 4,
        "constats_par_gravite": {"haute": 1, "moyenne": 3, "faible": 0},
        "regles_non_evaluees": ["TRANSACTION_HORS_NORME", "CHANGEMENT_COMPTE_INHABITUEL"],
        "regles_partielles": [],
    }
    charge.update(plus)
    return _valide("m5.preaudit_constate", charge)


def publier_depuis(
    producteur: str, type_evenement: str, charge: dict[str, Any], evenement_id: str | None = None
) -> str:
    """Publie sur le VRAI bus (outbox) ; la charge est validée par le catalogue à la publication."""
    return evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)
