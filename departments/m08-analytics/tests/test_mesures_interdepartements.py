"""Mesures interdépartements de M8 (M1, M3, M4, M5, M6, M7 -> entrepôt) : module pur `mesures_interdepartements`.

Ce que ce fichier prouve, sans base de données, sur des constats FICTIFS conformes au catalogue du socle :
- chaque mesure a une définition gouvernée, un propriétaire connu, une unité (CAD pour les montants) et un calcul ;
- une source absente donne « non calculable, manque X » (jamais un zéro), une source présente en partie donne une valeur
  dont la COUVERTURE est dite (« partielle », n sur N), une source complète une couverture complète ;
- les écarts de définition entre départements (marge réelle de M5 contre prévue de M3 ; relevés de M7 contre dépense
  comptabilisée de M5 ; demandes de M1 contre leads de M2) sont des mesures nommées, jamais une moyenne ;
- l'ordre de livraison du bus ne change rien (dernier état par `sequence`, par date de référence, par révision) ;
- un constat incohérent (total qui n'est pas la somme de ses tranches), un relevé qui se chevauche, des bases de taxes
  mêlées sont refusés, jamais corrigés ;
- aucune personne : ni nom, ni contact, ni technicien, ni fournisseur dans une mesure ;
- l'empreinte des faits d'une mesure change si et seulement si un fait qu'elle utilise change.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from m8_analytics import (
    cash_libre,
    catalogue_mesures,
    contenus,
    entonnoir,
    mesures_chantier,
)
from m8_analytics import (
    mesures_interdepartements as mi,
)
from m8_analytics import (
    operations_recues as op,
)

from opsys.evenements.schemas import erreurs_charge

FICTIF = True
_SRC = Path(__file__).resolve().parents[1] / "src" / "m8_analytics" / "mesures_interdepartements.py"
IDS = [
    "m8_chantiers_marge_reelle",
    "m8_marge_reelle_cumulee_cad",
    "m8_chantiers_en_perte",
    "m8_ecart_marge_cumule_cad",
    "m8_creances_ouvertes_cad",
    "m8_creances_90_jours_plus_cad",
    "m8_ecritures_en_attente",
    "m8_comptes_a_payer_cad",
    "m8_solde_tresorerie_cad",
    "m8_taxes_a_remettre_cad",
    "m8_releves_depense_pub_cad",
    "m8_conversions_hors_ligne",
    "m8_anomalies_depense_critiques",
    "m8_ecart_depense_pub_comptabilisee_cad",
    "m8_heures_sur_site_chantiers",
    "m8_receptions_materiaux",
    "m8_receptions_avec_ecart",
    "m8_demandes_qualifiees_m1",
    "m8_demandes_m1_sans_lead_m2",
    "m8_commandes_envoyees",
]


# ------------------------------------------------------------------------------------------------ constats fictifs
def _valide(type_evenement, charge):
    assert erreurs_charge(type_evenement, charge) == [], "la donnée de test doit être conforme au catalogue"
    return charge


def _wct(i, minutes=120, devis=None, jour="2026-10-20"):
    return {
        "type_entree": "wct",
        "wct_id": f"wct-{i}",
        "intervention_id": f"int-{i}",
        "devis_id": devis or f"devis-{i}",
        "technicien_id": "tech-fictif",
        "horodatage_completion": f"{jour}T16:00:00-04:00",
        "duree_reelle_minutes": minutes,
        "statut": "completed_verified",
    }


def _devis(i, prix="10000.00", cout="7000.00"):
    return {
        "type_entree": "devis",
        "devis_id": f"devis-{i}",
        "prix_total": prix,
        "cout_total": cout,
        "horodatage_acceptation": "2026-10-01T09:00:00-04:00",
    }


def _renta(i, marge="3200.00", sequence=1, definitif=True, complet=True, verdict="CALCULEE"):
    return mesures_chantier.fait_rentabilite(
        {
            "wct_id": f"wct-{i}",
            "devis_id": f"devis-{i}",
            "sequence": sequence,
            "verdict": verdict,
            "marge_reelle_cad": marge if verdict == "CALCULEE" else None,
            "manque": [] if verdict == "CALCULEE" else ["REJ-COUT-MATERIAUX-MANQUANTS"],
            "prix_definitif": definitif,
            "cout_reel_complet": complet,
            "version_entrees": "a" * 64,
        }
    )


def _chantiers():
    """Quatre chantiers : 1 marge +3200 (prévue 3000), 2 marge -500 (prévue 3000), 3 coût partiel, 4 sans M5."""
    return [
        _wct(1, 120),
        _wct(2, 90),
        _wct(3, 60),
        _wct(4, 30),
        _devis(1),
        _devis(2),
        _devis(3),
        _devis(4),
        _renta(1, "3200.00"),
        _renta(2, "-500.00"),
        _renta(3, verdict="PARTIELLE", complet=False),
    ]


def _depense(
    releve="r1",
    revision=1,
    canal="google_ads",
    debut="2026-10-27",
    fin=None,
    montant="125.40",
    base="HORS_TAXES",
    releve_le="2026-10-28T06:00:00-04:00",
):
    charge = _valide(
        "m7.depenses_marketing_constatees",
        {
            "releve_id": releve,
            "revision": revision,
            "canal": canal,
            "periode_debut": debut,
            "periode_fin": fin or debut,
            "montant_cad": montant,
            "devise": "CAD",
            "base_taxes": base,
            "source": "RELEVE_PLATEFORME",
            "releve_le": releve_le,
        },
    )
    return op.fait(op.TYPE_DEPENSE, charge)


def _signaux(source="google_ads", heures=24, lu="2026-10-28T06:00:00-04:00", fictif=False):
    charge = _valide(
        "m7.signaux_marketing_constates",
        {
            "source": source,
            "compte_ref": "compte-fictif-1",
            "flux": "depenses",
            "mode": "api_lecture",
            "periode_debut": "2026-10-22",
            "periode_fin": "2026-10-28",
            "faits_nouveaux": 1,
            "faits_revises": 0,
            "faits_inchanges": 0,
            "derniere_lecture_reussie_le": lu,
            "donnees_jusqu_au": "2026-10-28",
            "fraicheur_fenetre_h": heures,
            "fictif": fictif,
        },
    )
    return op.fait(op.TYPE_SIGNAUX, charge)


def _conversion(i, source="google", type_="rendez_vous"):
    charge = _valide(
        "m7.conversion_hors_ligne_importee",
        {
            "conversion_id": f"conv-{i}",
            "lead_id": f"lead-{i}",
            "type": type_,
            "convertie_le": "2026-10-26",
            "utm_source": source,
            "utm_medium": "cpc" if source else None,
            "utm_campaign": None,
            "valeur_cad": "4500.00",
            "source_normalisee": source is not None,
            "importee_le": f"2026-10-2{i}T09:00:00-04:00",
        },
    )
    return op.fait(op.TYPE_CONVERSION, charge)


def _anomalie(i, severite="critique", fictif=False):
    charge = _valide(
        "m7.anomalie_depense_detectee",
        {
            "anomalie_id": f"{i:032x}",
            "canal": "google_ads",
            "campagne_ref": None,
            "regle": "DEP-01",
            "severite": severite,
            "valeur": "310.50",
            "seuil": "200.00",
            "unite": "CAD",
            "jour_debut": "2026-10-27",
            "jour_fin": "2026-10-27",
            "detectee_le": f"2026-10-2{i}T07:00:00-04:00",
            "fictif": fictif,
        },
    )
    return op.fait(op.TYPE_ANOMALIE, charge)


def _comptable(jour="2026-10-30", version="0123456789abcdef", total="7210.55", tranches=None):
    tranches = tranches or {"0-30": "4000.00", "31-60": "2210.55", "61-90": "1000.00", "90+": "0.00"}
    charge = _valide(
        "m5.mesures_comptables_constatees",
        {
            "date_reference": jour,
            "version_donnees": version,
            "creances": {"nombre": 3, "total": total, "par_tranche": tranches},
            "relances_en_brouillon": 2,
            "brouillons_en_attente": 4,
            "ecritures_definitives": 12,
            "derniere_periode_close": "2026-09",
            "paiements_prepares": {"nombre": 1, "total": "459.91"},
            "rapprochements": {"prepares": 2, "confirmes": 1, "a_ecart": 0},
            "notes_de_credit": {"nombre": 0, "total": "0.00"},
            "depenses_employes": {"nombre": 1, "total": "32.10"},
            "pieces_liees": 5,
        },
    )
    return op.fait(op.TYPE_MESURES_COMPTABLES, charge)


def _reception(i, verdict="CONFORME", po="po-1"):
    charge = _valide(
        "m6.reception_enregistree",
        {
            "evenement_id": f"m6-reception-{po}-{i}",
            "po_id": po,
            "fournisseur_id": "fournisseur-fictif",
            "chantier_id": "chantier-fictif",
            "horodatage_reception": f"2026-10-2{i}T11:00:00-04:00",
            "verdict_reception": verdict,
            "statut_po": "received",
            "hash_maillon": f"{i:064x}",
            "seuil_ecart_prix_pourcentage": None,
            "lignes": [
                {
                    "materiau_id": "materiau-fictif",
                    "quantite_demandee": "10",
                    "quantite_recue": "10",
                    "prix_unitaire_prevu": "12.50",
                    "devise_prevue": "CAD",
                    "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": "12.50",
                    "verdict_prix_reception": "PRIX_CATALOGUE",
                    "ecart_prix_critique": False,
                }
            ],
        },
    )
    return op.fait(op.TYPE_RECEPTION, charge)


def _commande(i, po="po-1"):
    charge = _valide(
        "m1.commande_courriel_envoyee",
        {
            "po_id": po,
            "brouillon_id": f"brouillon-{i}",
            "empreinte": "e" * 64,
            "envoye_le": f"2026-10-2{i}T10:00:00-04:00",
        },
    )
    return op.fait(op.TYPE_COMMANDE, charge)


def _lead_m1(i, jour="2026-10-2"):
    return contenus.fait_lead_m1(
        {
            "lead": {
                "schema_version": 2,
                "lead_id": f"lead-{i}",
                "conversation_id": "c",
                "service": "toiture",
                "canal": "courriel",
                "contact": {"nom": "Nom Fictif", "courriel": "x@example.test"},
            },
            "horodatage": f"{jour}{i}T08:00:00-04:00",
            "signal_id": f"courriel:{i}",
        }
    )


def _lead_m2(i):
    return entonnoir.fait_lead_recu(
        {
            "lead_id": f"lead-{i}",
            "client_id": "a" * 64,
            "horodatage_association": f"2026-10-2{i}T08:05:00-04:00",
        }
    )


def _cash(comptes_a_payer="459.91", statut="CALCULE", plancher=None, sequence=1, jour="2026-10-29", manque=False):
    libelles = {
        "taxes_a_remettre": "TPS/TVQ",
        "paies": "Paies",
        "das": "DAS",
        "comptes_a_payer": "Comptes à payer",
        "dettes": "Dettes",
        "reserves": "Réserves",
    }

    def composante(cid, montant, st="CALCULE", plancher_cad=None):
        calculee = st == "CALCULE"
        registres = [{"registre": "mouvements", "taille": 3, "tete": "0123456789abcdef"}] if calculee else []
        return {
            "id": cid,
            "libelle": libelles.get(cid, "solde"),
            "statut": st,
            "montant_cad": montant,
            "plancher_cad": plancher_cad,
            "source": {"origine": "REGISTRE" if calculee else "AUCUNE", "registres": registres},
            "fraicheur": {"derniere_piece": "2026-09-14" if calculee else None, "pieces": 1 if calculee else 0},
        }

    composantes = [
        composante(cid, "100.00")
        if cid != "comptes_a_payer"
        else composante(cid, comptes_a_payer if statut == "CALCULE" else None, statut, plancher)
        for cid in libelles
    ]
    charge = {
        "evenement_id": f"m5-cash-libre-{sequence}-{jour}-aaaaaaaaaaaaaaaa",
        "sequence": sequence,
        "date_reference": jour,
        "version_donnees": "b" * 64,
        "devise": "CAD",
        "statut": "CALCULE" if statut == "CALCULE" else "NON_CALCULABLE",
        "cash_libre_cad": "1000.00" if statut == "CALCULE" else None,
        "au_plus_cad": None if statut == "CALCULE" else "1200.00",
        "en_deficit": False if statut == "CALCULE" else None,
        "lecture": "Cash libre fictif.",
        "solde": composante("solde", "5000.00"),
        "composantes": composantes,
        "manque": [{"composante": "comptes_a_payer", "code": "REJ-CASH-AP-INCOMPLET"}] if manque else [],
        "reserves": [],
        "hypotheses": [],
        "mention": "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision "
        "officielle ou "
        "action réelle.",
    }
    return cash_libre.fait_constat(_valide("m5.cash_libre_constate", charge))


def _registres(chantier=(), operations=(), cash=(), contenus_=(), entonnoir_=()):
    return {
        "chantier": list(chantier),
        "entonnoir": list(entonnoir_),
        "contenus": list(contenus_),
        "cash_libre": list(cash),
        "operations": list(operations),
    }


@pytest.fixture(scope="module")
def definitions():
    return mi.charger_definitions()


def _mesures(registres, definitions):
    return {m["metric_id"]: m for m in mi.mesurer(registres, definitions)}


def _vide(definitions):
    return _mesures(_registres(), definitions)


# ================================================================================================ définitions
def test_vingt_definitions_gouvernees_avec_proprietaire_connu_et_devise_cad(definitions):
    assert list(definitions) == IDS
    for metric_id, definition in definitions.items():
        assert definition["proprietaire"].startswith("m0") and definition["definition"]
        if metric_id.endswith("_cad"):
            assert definition["unite"] == "CAD"


def test_le_catalogue_les_reference_toutes_et_aucune_ne_chevauche_une_autre_definition():
    gouvernees = catalogue_mesures.definitions_gouvernees()  # lève si un metric_id est défini deux fois
    assert set(IDS) <= set(gouvernees)
    assert set(IDS) <= {e["metric_id"] for e in catalogue_mesures.charger()["mesures"]}


def test_une_metrique_sans_calcul_est_non_calculable_nommement(definitions):
    definitions = dict(definitions)
    definitions["m8_inconnue_cad"] = dict(definitions[IDS[0]], unite="CAD")
    mesures = _mesures(_registres(), definitions)
    inconnue = mesures["m8_inconnue_cad"]
    assert inconnue["statut"] == "non_calculable" and inconnue["manque"][0]["champ"] == "calcul"


# ================================================================================================ rien reçu
def test_sans_aucun_fait_aucune_mesure_n_a_de_valeur_et_aucun_zero_n_est_invente(definitions):
    for metric_id, mesure in _vide(definitions).items():
        assert mesure["statut"] == "non_calculable", metric_id
        assert mesure["valeur"] is None and mesure["manque"] and mesure["detail"].startswith("non calculable")
        assert mesure["couverture"] == {"etat": "inconnue"} and mesure["dernier_fait_le"] is None


# ================================================================================================ M5 : chantiers
def test_marge_cumulee_couverture_partielle_dite_et_valeurs_exactes(definitions):
    m = _mesures(_registres(chantier=_chantiers()), definitions)
    assert m["m8_chantiers_marge_reelle"]["valeur"] == "2"
    assert m["m8_marge_reelle_cumulee_cad"]["valeur"] == "2700.00"
    assert m["m8_chantiers_en_perte"]["valeur"] == "1"
    couverture = m["m8_marge_reelle_cumulee_cad"]["couverture"]
    assert couverture["etat"] == "partielle" and (couverture["couverts"], couverture["attendus"]) == (2, 4)
    assert "2 chantier(s) sur 4" in m["m8_marge_reelle_cumulee_cad"]["detail"]
    assert m["m8_marge_reelle_cumulee_cad"]["entrees"]["n_sans_marge_chiffree"] == 2


def test_ecart_de_marge_est_reelle_moins_prevue_et_dit_les_chantiers_non_mesurables(definitions):
    m = _mesures(_registres(chantier=_chantiers()), definitions)
    ecart = m["m8_ecart_marge_cumule_cad"]
    assert ecart["valeur"] == "-3300.00"  # (3200 - 3000) + (-500 - 3000)
    assert ecart["entrees"]["n_chantiers_mesures"] == 2 and ecart["couverture"]["etat"] == "partielle"
    assert "réelle moins prévue" in definitions["m8_ecart_marge_cumule_cad"]["nom"]


def test_couverture_complete_quand_tous_les_chantiers_sont_chiffres(definitions):
    faits = [_wct(1), _wct(2), _devis(1), _devis(2), _renta(1, "100.00"), _renta(2, "50.50")]
    m = _mesures(_registres(chantier=faits), definitions)
    assert m["m8_marge_reelle_cumulee_cad"]["valeur"] == "150.50"
    assert m["m8_marge_reelle_cumulee_cad"]["couverture"] == {"etat": "complete"}
    assert m["m8_marge_reelle_cumulee_cad"]["detail"] is None


def test_une_marge_sans_prix_definitif_ou_a_cout_partiel_n_est_jamais_comptee(definitions):
    faits = [
        _wct(1),
        _wct(2),
        _wct(3),
        _devis(1),
        _devis(2),
        _devis(3),
        _renta(1, definitif=False),
        _renta(2, complet=False),
        _renta(3, "10.00"),
    ]
    m = _mesures(_registres(chantier=faits), definitions)
    assert m["m8_chantiers_marge_reelle"]["valeur"] == "1" and m["m8_marge_reelle_cumulee_cad"]["valeur"] == "10.00"


def test_la_trace_de_plus_grand_sequence_l_emporte_quel_que_soit_l_ordre_de_livraison(definitions):
    nouveau = _renta(1, "900.00", sequence=2)
    ancien = _renta(1, "100.00", sequence=1)
    a = _mesures(_registres(chantier=[_wct(1), _devis(1), nouveau, ancien]), definitions)
    b = _mesures(_registres(chantier=[_wct(1), _devis(1), ancien, nouveau]), definitions)
    assert a["m8_marge_reelle_cumulee_cad"]["valeur"] == b["m8_marge_reelle_cumulee_cad"]["valeur"] == "900.00"
    assert a["m8_marge_reelle_cumulee_cad"]["entrees"] == b["m8_marge_reelle_cumulee_cad"]["entrees"]


def test_chantiers_termines_sans_trace_de_m5_marge_non_calculable_mais_heures_calculees(definitions):
    m = _mesures(_registres(chantier=[_wct(1, 90), _wct(2, 30)]), definitions)
    for metric_id in ("m8_chantiers_marge_reelle", "m8_marge_reelle_cumulee_cad", "m8_chantiers_en_perte"):
        assert m[metric_id]["statut"] == "non_calculable"
        assert m[metric_id]["manque"][0]["champ"] == "m5.rentabilite_chantier"
    assert m["m8_heures_sur_site_chantiers"]["valeur"] == "2.00"


def test_heures_sur_site_somme_des_minutes_en_heures_et_duree_illisible_dite(definitions):
    faits = [_wct(1, 120), _wct(2, 90), _wct(3, 60), _wct(4, 30)]
    heures = _mesures(_registres(chantier=faits), definitions)["m8_heures_sur_site_chantiers"]
    assert heures["valeur"] == "5.00" and heures["couverture"] == {"etat": "complete"}
    faits[3]["duree_reelle_minutes"] = "beaucoup"
    faits[2]["duree_reelle_minutes"] = True  # un booléen n'est pas une durée
    partielle = _mesures(_registres(chantier=faits), definitions)["m8_heures_sur_site_chantiers"]
    assert partielle["valeur"] == "3.50" and partielle["couverture"]["etat"] == "partielle"
    assert partielle["entrees"]["n_durees_illisibles"] == 2
    faits[0]["duree_reelle_minutes"] = -5
    faits[1]["duree_reelle_minutes"] = None
    assert (
        _mesures(_registres(chantier=faits), definitions)["m8_heures_sur_site_chantiers"]["statut"] == "non_calculable"
    )


def test_un_meme_chantier_recu_deux_fois_ne_compte_qu_une_fois(definitions):
    m = _mesures(_registres(chantier=[_wct(1, 60), _wct(1, 60), _devis(1), _renta(1)]), definitions)
    assert m["m8_heures_sur_site_chantiers"]["valeur"] == "1.00" and m["m8_chantiers_marge_reelle"]["valeur"] == "1"


# ================================================================================================ M5 : constats
def test_creances_reprises_telles_quelles_avec_la_tranche_90_plus(definitions):
    m = _mesures(
        _registres(
            operations=[
                _comptable(
                    tranches={"0-30": "100.00", "31-60": "0.00", "61-90": "0.00", "90+": "50.00"}, total="150.00"
                )
            ]
        ),
        definitions,
    )
    assert m["m8_creances_ouvertes_cad"]["valeur"] == "150.00"
    assert m["m8_creances_90_jours_plus_cad"]["valeur"] == "50.00"
    assert m["m8_creances_ouvertes_cad"]["dernier_fait_le"] == "2026-10-30T00:00:00+00:00"


def test_dernier_constat_par_date_de_reference_quel_que_soit_l_ordre(definitions):
    tard = _comptable(
        "2026-10-30",
        "b" * 16,
        total="500.00",
        tranches={"0-30": "500.00", "31-60": "0.00", "61-90": "0.00", "90+": "0.00"},
    )
    tot = _comptable("2026-10-29", "a" * 16)
    for ordre in ([tot, tard], [tard, tot]):
        m = _mesures(_registres(operations=ordre), definitions)
        assert m["m8_creances_ouvertes_cad"]["valeur"] == "500.00"


def test_un_constat_incoherent_est_refuse_pas_corrige(definitions):
    forge = _comptable(total="999999.00")  # le total n'est pas la somme des tranches
    m = _mesures(_registres(operations=[forge]), definitions)
    for metric_id in ("m8_creances_ouvertes_cad", "m8_creances_90_jours_plus_cad"):
        assert m[metric_id]["statut"] == "non_calculable" and m[metric_id]["valeur"] is None
        assert "incohérent" in m[metric_id]["manque"][0]["raison"]


def test_comptes_a_payer_repris_et_non_calculable_avec_plancher_dit(definitions):
    ok = _mesures(_registres(cash=[_cash("459.91")]), definitions)["m8_comptes_a_payer_cad"]
    assert ok["valeur"] == "459.91" and ok["dernier_fait_le"] == "2026-10-29T00:00:00+00:00"
    nok = _mesures(_registres(cash=[_cash(statut="NON_CALCULABLE", plancher="300.00", manque=True)]), definitions)
    mesure = nok["m8_comptes_a_payer_cad"]
    assert mesure["statut"] == "non_calculable" and mesure["valeur"] is None
    assert "REJ-CASH-AP-INCOMPLET" in mesure["detail"] and mesure["entrees"]["plancher_cad"] == "300.00"
    assert "plancher" in mesure["manque"][0]["raison"]


def test_comptes_a_payer_dernier_constat_par_sequence(definitions):
    recents = [_cash("10.00", sequence=2, jour="2026-10-29"), _cash("99.00", sequence=1, jour="2026-10-30")]
    assert _mesures(_registres(cash=recents), definitions)["m8_comptes_a_payer_cad"]["valeur"] == "10.00"


# ================================================================================================ M7 : dépenses
def test_somme_des_derniers_releves_jours_contigus_couverture_complete(definitions):
    faits = [
        _depense("r1", 1, debut="2026-10-27", montant="100.00"),
        _depense("r1", 2, debut="2026-10-27", montant="110.00"),  # la révision 2 REMPLACE la 1
        _depense("r2", 1, debut="2026-10-28", montant="40.10"),
        _depense("r3", 1, canal="meta", debut="2026-10-27", montant="7.00"),
    ]
    m = _mesures(_registres(operations=faits), definitions)["m8_releves_depense_pub_cad"]
    assert m["valeur"] == "157.10" and m["couverture"] == {"etat": "complete"}
    assert m["entrees"]["base_taxes"] == "HORS_TAXES" and m["entrees"]["n_releves"] == 3
    assert "PAS la dépense réelle" in definitions["m8_releves_depense_pub_cad"]["definition"]


def test_jours_sans_releve_a_l_interieur_de_la_periode_rendent_la_couverture_partielle(definitions):
    faits = [
        _depense("r1", 1, debut="2026-10-24"),
        _depense("r2", 1, debut="2026-10-27"),
        _depense("r3", 1, debut="2026-10-28"),
    ]
    m = _mesures(_registres(operations=faits), definitions)["m8_releves_depense_pub_cad"]
    assert m["statut"] == "calculee" and m["couverture"]["etat"] == "partielle"
    assert m["entrees"]["jours_sans_releve"] == 2  # les 25 et 26 octobre : pas des zéros
    assert "2 jour(s) sans relevé" in m["detail"]


def test_bases_de_taxes_melangees_ou_releves_qui_se_chevauchent_aucune_somme(definitions):
    melange = [_depense("r1", base="HORS_TAXES"), _depense("r2", debut="2026-10-28", base="TAXES_INCLUSES")]
    m = _mesures(_registres(operations=melange), definitions)["m8_releves_depense_pub_cad"]
    assert m["statut"] == "non_calculable" and "taxes" in m["manque"][0]["raison"]
    chevauche = [_depense("r1", debut="2026-10-27", fin="2026-10-29"), _depense("r2", debut="2026-10-29")]
    m = _mesures(_registres(operations=chevauche), definitions)["m8_releves_depense_pub_cad"]
    assert m["statut"] == "non_calculable" and "chevauch" in m["manque"][0]["raison"]


def test_un_releve_a_periode_illisible_ou_inversee_est_refuse(definitions):
    for fin in ("2026-10-26", "2026-02-30"):
        faits = [_depense("r1", debut="2026-10-27", fin=fin)]
        m = _mesures(_registres(operations=faits), definitions)["m8_releves_depense_pub_cad"]
        assert m["statut"] == "non_calculable" and "période" in m["manque"][0]["raison"]


def test_fraicheur_la_fenetre_de_m7_est_portee_et_la_plus_stricte_des_sources_gagne(definitions):
    faits = [
        _depense("r1", canal="google_ads"),
        _depense("r2", canal="meta"),
        _signaux("google_ads", 48),
        _signaux("meta_ads", 6),
        _signaux("search_console", 1),
        _signaux("meta_ads", 1, fictif=True),
    ]
    m = _mesures(_registres(operations=faits), definitions)["m8_releves_depense_pub_cad"]
    assert m["fenetre_source_s"] == 6 * 3600  # meta : 6 h ; le fictif et la source non publicitaire sont ignorés
    sans = _mesures(_registres(operations=[_depense("r1")]), definitions)["m8_releves_depense_pub_cad"]
    assert sans["fenetre_source_s"] is None and sans["entrees"]["canaux_sans_fenetre_de_m7"] == ["google_ads"]


def test_dernier_fait_est_le_releve_le_plus_recent_et_un_instant_illisible_est_dit(definitions):
    faits = [
        _depense("r1", releve_le="2026-10-28T06:00:00-04:00"),
        _depense("r2", debut="2026-10-28", releve_le="2026-10-29T06:00:00-04:00"),
        _depense("r3", debut="2026-10-29", releve_le="hier matin"),
    ]
    m = _mesures(_registres(operations=faits), definitions)["m8_releves_depense_pub_cad"]
    assert m["dernier_fait_le"] == "2026-10-29T06:00:00-04:00" and m["entrees"]["n_releve_le_illisibles"] == 1


def test_l_ecart_entre_releves_et_depense_comptabilisee_est_nomme_et_non_calculable(definitions):
    faits = [_depense("r1"), _comptable()]
    m = _mesures(_registres(operations=faits), definitions)["m8_ecart_depense_pub_comptabilisee_cad"]
    assert m["statut"] == "non_calculable" and m["valeur"] is None
    assert "M5" in m["manque"][0]["source"] and "comptabilis" in m["manque"][0]["raison"]
    assert "N4" in m["manque"][0]["raison"] or "humain" in m["manque"][0]["raison"]


def test_conversions_distinctes_et_source_non_normalisee_dite(definitions):
    faits = [_conversion(1), _conversion(1), _conversion(2, source=None, type_="vente"), _conversion(3)]
    m = _mesures(_registres(operations=faits), definitions)["m8_conversions_hors_ligne"]
    assert m["valeur"] == "3" and m["entrees"]["n_sans_source_normalisee"] == 1
    assert m["entrees"]["par_type"] == {"rendez_vous": 2, "vente": 1}
    assert m["dernier_fait_le"] == "2026-10-23T09:00:00-04:00"


def test_anomalies_critiques_comptent_les_reelles_seulement(definitions):
    faits = [
        _anomalie(1, "critique"),
        _anomalie(2, "attention"),
        _anomalie(3, "critique", fictif=True),
        _anomalie(4, "critique"),
    ]
    m = _mesures(_registres(operations=faits), definitions)["m8_anomalies_depense_critiques"]
    assert m["valeur"] == "2" and m["entrees"]["n_fictifs_ignores"] == 1 and m["entrees"]["n_anomalies_reelles"] == 3
    seulement_fictif = _mesures(_registres(operations=[_anomalie(1, fictif=True)]), definitions)
    assert seulement_fictif["m8_anomalies_depense_critiques"]["statut"] == "non_calculable"


def test_aucune_anomalie_reelle_n_est_pas_un_zero(definitions):
    m = _mesures(_registres(operations=[_depense("r1")]), definitions)["m8_anomalies_depense_critiques"]
    assert m["statut"] == "non_calculable" and m["valeur"] is None


# ================================================================================================ M6, M1, M2
def test_receptions_comptees_par_bon_et_mouvement_avec_ecart_dit(definitions):
    faits = [
        _reception(1),
        _reception(2, "RECEPTION_INFERIEURE"),
        _reception(2, "RECEPTION_INFERIEURE"),
        _reception(3, "RECEPTION_MIXTE", po="po-2"),
    ]
    m = _mesures(_registres(operations=faits), definitions)
    assert m["m8_receptions_materiaux"]["valeur"] == "3" and m["m8_receptions_avec_ecart"]["valeur"] == "2"
    assert m["m8_receptions_avec_ecart"]["entrees"]["par_verdict"] == {
        "CONFORME": 1,
        "RECEPTION_INFERIEURE": 1,
        "RECEPTION_MIXTE": 1,
    }


def test_la_reception_ne_garde_ni_fournisseur_ni_chantier_ni_lignes():
    fait = _reception(1)
    assert "fournisseur_id" not in fait and "chantier_id" not in fait and "lignes" not in fait
    assert fait["provenance"]["evenement"] == "m6.reception_enregistree"
    assert fait["provenance"]["evenement_id"] == "m6-reception-po-1-1" and len(fait["provenance"]["empreinte"]) == 64


def test_demandes_de_m1_sans_lead_chez_m2_ecart_nomme(definitions):
    registres = _registres(
        contenus_=[_lead_m1(1), _lead_m1(2), _lead_m1(3)], entonnoir_=[_lead_m2(1), _lead_m2(2), _lead_m2(7)]
    )
    m = _mesures(registres, definitions)
    assert m["m8_demandes_qualifiees_m1"]["valeur"] == "3"
    ecart = m["m8_demandes_m1_sans_lead_m2"]
    assert ecart["valeur"] == "1"
    assert ecart["entrees"] == {
        "n_demandes_m1": 3,
        "n_leads_m2": 3,
        "n_demandes_m1_avec_lead_m2": 2,
        "n_leads_m2_sans_demande_m1": 1,
        "empreinte_faits": ecart["entrees"]["empreinte_faits"],
    }


def test_sans_lead_de_m2_l_ecart_n_est_pas_toute_la_liste(definitions):
    m = _mesures(_registres(contenus_=[_lead_m1(1)]), definitions)
    assert m["m8_demandes_qualifiees_m1"]["valeur"] == "1"
    assert m["m8_demandes_m1_sans_lead_m2"]["statut"] == "non_calculable"
    assert m["m8_demandes_m1_sans_lead_m2"]["manque"][0]["champ"] == "m2.client_associe"
    sans_m1 = _mesures(_registres(entonnoir_=[_lead_m2(1)]), definitions)
    assert sans_m1["m8_demandes_m1_sans_lead_m2"]["manque"][0]["champ"] == "m1.lead_qualifie"


def test_les_demandes_de_m1_ne_gardent_ni_nom_ni_courriel():
    assert "Nom Fictif" not in json.dumps(_lead_m1(1)) and "example.test" not in json.dumps(_lead_m1(1))


# ================================================================================================ transversal
def test_aucune_personne_dans_aucune_mesure(definitions):
    tout = _registres(
        chantier=_chantiers(),
        operations=[_depense(), _conversion(1), _anomalie(1), _comptable(), _reception(1), _signaux()],
        cash=[_cash()],
        contenus_=[_lead_m1(1)],
        entonnoir_=[_lead_m2(1)],
    )
    texte = json.dumps(mi.mesurer(tout, definitions), ensure_ascii=False)
    for interdit in ("tech-fictif", "Nom Fictif", "example.test", "fournisseur-fictif", "technicien"):
        assert interdit not in texte, interdit


def test_la_meme_entree_donne_la_meme_sortie_et_l_empreinte_suit_les_faits_utilises(definitions):
    registres = _registres(operations=[_comptable()])
    a = _mesures(registres, definitions)["m8_creances_ouvertes_cad"]
    b = _mesures(_registres(operations=[_comptable()]), definitions)["m8_creances_ouvertes_cad"]
    assert a == b and len(a["entrees"]["empreinte_faits"]) == 64
    autre = _mesures(_registres(operations=[_comptable(version="f" * 16)]), definitions)["m8_creances_ouvertes_cad"]
    assert autre["entrees"]["empreinte_faits"] != a["entrees"]["empreinte_faits"]
    # un fait qu'elle n'utilise pas ne change pas son empreinte
    plus = _mesures(_registres(operations=[_comptable(), _conversion(1)]), definitions)["m8_creances_ouvertes_cad"]
    assert plus["entrees"]["empreinte_faits"] == a["entrees"]["empreinte_faits"]


def test_le_module_n_utilise_ni_flottant_ni_arrondi_ni_horloge():
    arbre = ast.parse(_SRC.read_text(encoding="utf-8"))
    appels = {n.func.id for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not appels & {"float", "round"}
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(arbre))
    assert "datetime.now" not in _SRC.read_text(encoding="utf-8") and "time.time" not in _SRC.read_text(
        encoding="utf-8"
    )


def test_sans_marge_chiffree_la_raison_dit_pourquoi_chantier_par_chantier(definitions):
    faits = [
        _wct(1),
        _wct(2),
        _wct(3),
        _devis(1),
        _devis(2),
        _devis(3),
        _renta(1, definitif=False),
        _renta(2, verdict="PARTIELLE", complet=False),
    ]
    m = _mesures(_registres(chantier=faits), definitions)
    for metric_id in ("m8_chantiers_marge_reelle", "m8_marge_reelle_cumulee_cad", "m8_chantiers_en_perte"):
        raison = m[metric_id]["manque"][0]["raison"]
        assert "1 chantier(s) : aucune trace de rentabilité reçue de M5" in raison, metric_id
        assert "prix non définitif" in raison and "REJ-COUT-MATERIAUX-MANQUANTS" in raison, metric_id


def test_l_empreinte_des_faits_ne_depend_pas_de_l_ordre_de_livraison(definitions):
    a = _mesures(_registres(operations=[_conversion(1), _conversion(2, type_="vente")]), definitions)
    b = _mesures(_registres(operations=[_conversion(2, type_="vente"), _conversion(1)]), definitions)
    assert a["m8_conversions_hors_ligne"] == b["m8_conversions_hors_ligne"]


def test_les_receptions_ne_figurent_pas_dans_la_section_de_la_vue_executive():
    assert op.section([_reception(1)]) is None
    section = op.section([_reception(1), _depense()])
    assert section["constats_recus"] == 1 and "reception_materiaux" not in json.dumps(section)


def test_la_periode_d_un_releve_a_une_borne_et_un_format(definitions):
    longue = [_depense("r1", debut="2016-10-27", fin="2026-10-25")]  # 3 650 jours d'écart : crédible
    assert _mesures(_registres(operations=longue), definitions)["m8_releves_depense_pub_cad"]["statut"] == "calculee"
    trop = [_depense("r1", debut="2006-01-01", fin="2026-10-25")]  # plus de dix ans : refusé
    assert (
        _mesures(_registres(operations=trop), definitions)["m8_releves_depense_pub_cad"]["statut"] == "non_calculable"
    )
    format_basique = _depense("r1")
    format_basique["periode_debut"] = format_basique["periode_fin"] = (
        "20261027"  # lisible par Python, pas un AAAA-MM-JJ
    )
    m = _mesures(_registres(operations=[format_basique]), definitions)["m8_releves_depense_pub_cad"]
    assert m["statut"] == "non_calculable" and "période" in m["manque"][0]["raison"]


def test_une_revision_qui_n_est_pas_un_entier_n_est_pas_une_revision(definitions):
    faux = _depense("r1")
    faux["revision"] = True
    m = _mesures(_registres(operations=[faux]), definitions)["m8_releves_depense_pub_cad"]
    assert m["statut"] == "non_calculable" and m["valeur"] is None


def test_commandes_envoyees_comptees_par_bon_de_commande_sans_brouillon_ni_adresse(definitions):
    faits = [_commande(1, "po-1"), _commande(2, "po-1"), _commande(3, "po-2")]  # un renvoi du même bon : une commande
    m = _mesures(_registres(operations=faits), definitions)["m8_commandes_envoyees"]
    assert m["valeur"] == "2" and m["dernier_fait_le"] == "2026-10-23T10:00:00-04:00"
    assert set(faits[0]) == {"type_entree", "po_id", "envoye_le", "provenance"}
    assert "brouillon" not in json.dumps(faits)
    assert op.section(faits) is None  # ni la vue exécutive ni la section n'en parlent
    vide = _mesures(_registres(), definitions)["m8_commandes_envoyees"]
    assert vide["statut"] == "non_calculable" and vide["manque"][0]["champ"] == "m1.commande_courriel_envoyee"


def test_solde_et_taxes_a_remettre_repris_tels_quels_du_dernier_constat_du_cash_libre(definitions):
    m = _mesures(_registres(cash=[_cash("459.91")]), definitions)
    assert m["m8_solde_tresorerie_cad"]["valeur"] == "5000.00" and m["m8_taxes_a_remettre_cad"]["valeur"] == "100.00"
    assert m["m8_solde_tresorerie_cad"]["entrees"]["sequence"] == 1
    # la composante que M5 n'a pas pu chiffrer ne contamine pas les autres : le solde reste calculé
    non = _mesures(_registres(cash=[_cash(statut="NON_CALCULABLE", plancher="300.00", manque=True)]), definitions)
    assert non["m8_comptes_a_payer_cad"]["statut"] == "non_calculable"
    assert (
        non["m8_solde_tresorerie_cad"]["valeur"] == "5000.00" and non["m8_taxes_a_remettre_cad"]["valeur"] == "100.00"
    )


def test_une_composante_absente_du_constat_est_nommee_pas_devinee(definitions):
    constat = _cash("459.91")
    constat["composantes"] = [c for c in constat["composantes"] if c["id"] != "taxes_a_remettre"]
    m = _mesures(_registres(cash=[constat]), definitions)["m8_taxes_a_remettre_cad"]
    assert m["statut"] == "non_calculable" and "absente du constat" in m["manque"][0]["raison"]
    sans_solde = _cash("459.91")
    sans_solde["solde"] = None
    assert _mesures(_registres(cash=[sans_solde]), definitions)["m8_solde_tresorerie_cad"]["statut"] == "non_calculable"


def test_ecritures_en_attente_reprises_du_dernier_constat_comptable_et_refusees_si_illisibles(definitions):
    ok = _mesures(_registres(operations=[_comptable()]), definitions)["m8_ecritures_en_attente"]
    assert ok["valeur"] == "4" and ok["dernier_fait_le"] == "2026-10-30T00:00:00+00:00"
    for illisible in (True, -1, "4", None):
        constat = _comptable()
        constat["brouillons_en_attente"] = illisible
        m = _mesures(_registres(operations=[constat]), definitions)["m8_ecritures_en_attente"]
        assert m["statut"] == "non_calculable" and m["valeur"] is None, illisible
    vide = _mesures(_registres(), definitions)["m8_ecritures_en_attente"]
    assert vide["manque"][0]["champ"] == "m5.mesures_comptables_constatees"


def test_un_chantier_a_marge_nulle_n_est_ni_en_perte_ni_oublie(definitions):
    faits = [
        _wct(1),
        _wct(2),
        _wct(3),
        _devis(1),
        _devis(2),
        _devis(3),
        _renta(1, "0.00"),
        _renta(2, "-0.01"),
        _renta(3, "0.01"),
    ]
    m = _mesures(_registres(chantier=faits), definitions)
    assert m["m8_chantiers_en_perte"]["valeur"] == "1"  # seulement -0.01 : zéro n'est pas une perte
    assert m["m8_chantiers_marge_reelle"]["valeur"] == "3" and m["m8_marge_reelle_cumulee_cad"]["valeur"] == "0.00"
