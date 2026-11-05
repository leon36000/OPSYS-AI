"""Les seuils M8 restent exacts seulement tant qu'ils tiennent dans les sorties publiques.

Les exemples sont fictifs. La borne par seuil est technique (5900 caractères / quatre seuils
entonnoir) ; les charges d'alerte sont ensuite mesurées dans l'enveloppe JSON réelle lue par M9.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from m8_analytics import alertes_sortie, entonnoir, mesures_chantier, nombres
from m8_analytics import outils as m8_outils
from m8_analytics.outils import outils
from m8_analytics.registre import RegistreSnapshots
from m9_strategic_intelligence import lecture_alertes
from m9_strategic_intelligence.outils import BUDGET_SORTIE as BUDGET_SORTIE_M9

from opsys import jetons
from opsys.evenements import schemas as catalogue
from opsys.outils import executer


def _wct():
    return {
        "type_entree": "wct", "wct_id": "wct-fictif-budget", "intervention_id": "int-fictif",
        "devis_id": "devis-fictif", "technicien_id": "tech-fictif",
        "horodatage_completion": "2026-09-28T14:00:00-04:00", "duree_reelle_minutes": 120,
        "statut": "completed_pending_review",
    }


def _devis():
    return {
        "type_entree": "devis", "devis_id": "devis-fictif", "prix_total": "600.00", "cout_total": "480.00",
        "duree_estimee_minutes": "100", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
    }


def _charge_seuil(seuil: str):
    definition = mesures_chantier.charger_definitions()["m8_ecart_duree_pct"]
    return mesures_chantier._charge_franchi(
        "wct-fictif-budget",
        {"metric_id": "m8_ecart_duree_pct", "valeur": "20.00", "unite": "pourcentage",
         "sens": "au_dessus", "seuil": seuil},
        {"nom": definition["nom"], "version_definition": "a" * 64}, definition,
        "2026-09-28T14:00:00-04:00",
    )


def _seuil_decimal_longueur(longueur: int) -> Decimal:
    return Decimal("19." + "9" * (longueur - 3))


def test_borne_par_seuil_est_derivee_du_budget_public_et_du_nombre_de_seuils_visibles():
    assert nombres.LONGUEUR_TEXTE_SEUIL_MAX == nombres.BUDGET_SORTIE_SEUILS // nombres.NOMBRE_SEUILS_ENTONNOIR_MAX
    assert nombres.NOMBRE_SEUILS_ENTONNOIR_MAX == len(entonnoir._METRIQUES_SURVEILLEES) == 4
    assert m8_outils.BUDGET_SORTIE == BUDGET_SORTIE_M9 == jetons.LIMITE_SORTIE_DEFAUT - 100 == 5900


def test_seuil_exact_a_la_borne_accepte_et_un_caractere_de_plus_est_invalide_sans_echo():
    a_la_borne = {"sens": "au_dessus", "valeur": _seuil_decimal_longueur(1475)}
    trop_long = {"sens": "au_dessus", "valeur": _seuil_decimal_longueur(1476)}

    assert len(nombres.texte_seuil(nombres.seuil_valide(a_la_borne)["valeur"])) == 1475
    assert nombres.seuil_valide(trop_long) is None
    assert nombres.decimal_lu(trop_long["valeur"]) is not None  # aucun changement à la lecture des montants/durées


def test_charge_exacte_a_la_borne_tient_dans_la_vraie_page_m9_et_garde_les_anciens_seuils():
    charge = _charge_seuil(nombres.texte_seuil(_seuil_decimal_longueur(1475)))
    page_m9 = lecture_alertes.lire_alertes_m8([charge], budget_caracteres=BUDGET_SORTIE_M9)

    assert alertes_sortie.page_unique(charge) == page_m9
    assert alertes_sortie.taille_page_unique(charge) == len(json.dumps(page_m9, ensure_ascii=False))
    assert alertes_sortie.exiger_page_lisible(charge) <= BUDGET_SORTIE_M9
    ancienne = _charge_seuil("33.30")
    assert alertes_sortie.exiger_page_lisible(ancienne) <= BUDGET_SORTIE_M9
    assert catalogue.erreurs_charge("m8.alerte_proposee", charge) == []


def test_une_page_m9_exactement_au_budget_est_acceptee_et_un_caractere_de_moins_est_refuse():
    charge = _charge_seuil("33.30")
    taille = len(json.dumps(alertes_sortie.page_unique(charge), ensure_ascii=False))

    assert alertes_sortie.exiger_page_lisible(charge, budget=taille) == taille
    with pytest.raises(ValueError, match="REJ-M8-ALERTE-BORNE-SORTIE"):
        alertes_sortie.exiger_page_lisible(charge, budget=taille - 1)


def test_mesure_exacte_compte_les_echappements_et_erreur_de_borne_ne_recopie_pas_le_texte():
    charge = _charge_seuil("33.30") | {"quoi": "texte-fictif\n" * 3000}
    assert len(json.dumps(alertes_sortie.page_unique(charge), ensure_ascii=False)) > BUDGET_SORTIE_M9

    with pytest.raises(ValueError, match="REJ-M8-ALERTE-BORNE-SORTIE") as erreur:
        alertes_sortie.exiger_page_lisible(charge)
    assert "texte-fictif" not in str(erreur.value) and "\n" not in str(erreur.value)


def test_producteur_refuse_avant_publication_une_alerte_qui_ne_tiendrait_pas_chez_m9(monkeypatch):
    charge = _charge_seuil("33.30") | {"quoi": "contenu-fictif\n" * 3000}
    publiees = []
    monkeypatch.setattr(m8_outils.evenements, "deja_publie", lambda ident: False)
    monkeypatch.setattr(m8_outils.evenements, "charge_publiee", lambda *args: None)
    monkeypatch.setattr(m8_outils.evenements, "publier", lambda *args, **kwargs: publiees.append(args))

    with pytest.raises(ValueError, match="REJ-M8-ALERTE-BORNE-SORTIE"):
        m8_outils._publier_charges_mesure([charge])
    assert publiees == []


def test_catalogue_refuse_un_seuil_evenementiel_au_dela_de_la_borne_technique():
    charge_ok = _charge_seuil(nombres.texte_seuil(_seuil_decimal_longueur(1475)))
    charge_trop_longue = _charge_seuil(nombres.texte_seuil(_seuil_decimal_longueur(1476)))

    assert catalogue.erreurs_charge("m8.alerte_proposee", charge_ok) == []
    assert catalogue.erreurs_charge("m8.alerte_proposee", charge_trop_longue)


def _faits_entonnoir():
    return [
        entonnoir.fait_lead_recu({
            "lead_id": "lead-fictif", "client_id": "a" * 64,
            "horodatage_association": "2026-09-29T09:15:00-04:00",
        }),
        entonnoir.fait_devis_envoye({
            "devis_id": "D1-fictif", "lead_id": "lead-fictif", "chantier_id": None,
            "horodatage_envoi": "2026-09-29T15:00:00-04:00",
        }),
        entonnoir.fait_devis_envoye({
            "devis_id": "D2-fictif", "lead_id": "lead-fictif", "chantier_id": None,
            "horodatage_envoi": "2026-09-29T15:30:00-04:00",
        }),
        entonnoir.fait_devis_accepte({
            "devis_id": "D1-fictif", "lead_id": "lead-fictif", "prix_total": "600.00",
            "horodatage_acceptation": "2026-09-30T10:00:00-04:00",
        }),
        entonnoir.fait_devis_sans_reponse({
            "devis_id": "D2-fictif", "lead_id": "lead-fictif", "statut": "envoye",
            "horodatage_devis": "2026-09-29T15:30:00-04:00",
            "horodatage_reference": "2026-10-08T08:00:00-04:00", "delai_relance_jours": 7,
        }),
    ]


def _outil_vue(faits):
    par_nom = {
        outil.nom: outil for outil in outils(
            RegistreSnapshots(), [], [], faits, faits_cash_libre_cible=[], faits_operations_cible=[],
        )
    }
    return par_nom["m8_lire_vue_executive"]


def _poser_configuration(tmp_path, monkeypatch, seuils: dict[str, str], section="seuils_entonnoir"):
    lignes = ["configuration:", f"  {section}:"]
    for metric_id, valeur in seuils.items():
        lignes.extend([
            f"    {metric_id}:", "      sens: au_dessous", f"      valeur: {valeur}",
        ])
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)
    return manifeste


def test_yaml_5000_decimales_devient_invalide_et_la_vue_publique_n_echo_pas_la_valeur(
    tmp_path, monkeypatch,
):
    chiffres = "1" * 5000
    _poser_configuration(tmp_path, monkeypatch, {"m8_taux_acceptation_pct": "0." + chiffres})
    seuil = m8_outils._seuils_entonnoir()["m8_taux_acceptation_pct"]
    assert seuil["valeur"] is None

    reponse = executer(_outil_vue(_faits_entonnoir()), {})
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    seuils = resultat["entonnoir"]["seuils"]
    assert seuils["invalides"] == ["m8_taux_acceptation_pct"]
    assert "1475" in seuils["raison_invalide"]
    rendu = json.dumps(reponse, ensure_ascii=False)
    assert chiffres not in rendu and len(rendu) <= jetons.LIMITE_SORTIE_DEFAUT


def test_zero_lexicalement_long_reste_zero_et_exposants_inexploitables_restent_invalides(tmp_path, monkeypatch):
    zeros = "0." + "0" * 5000
    _poser_configuration(tmp_path, monkeypatch, {"m8_taux_acceptation_pct": zeros})
    seuil_zero = m8_outils._seuils_entonnoir()["m8_taux_acceptation_pct"]
    assert nombres.seuil_valide(seuil_zero)["valeur"] == Decimal(0)

    _poser_configuration(tmp_path, monkeypatch, {"m8_taux_acceptation_pct": "1e-5000"})
    seuil_exposant = m8_outils._seuils_entonnoir()["m8_taux_acceptation_pct"]
    assert nombres.seuil_valide(seuil_exposant) is None

    _poser_configuration(tmp_path, monkeypatch, {"m8_taux_acceptation_pct": "1e999999"})
    seuil_exposant_haut = m8_outils._seuils_entonnoir()["m8_taux_acceptation_pct"]
    assert nombres.seuil_valide(seuil_exposant_haut) is None


def test_quatre_seuils_individuellement_valides_mais_trop_gros_ensemble_sont_refuses_nommement(
    tmp_path, monkeypatch,
):
    valeur = "0." + "1" * (1475 - 2)
    ids = [
        "m8_devis_sans_reponse", "m8_taux_acceptation_pct", "m8_delai_lead_acceptation_jours",
        "m8_carnet_signe_cad",
    ]
    _poser_configuration(tmp_path, monkeypatch, {metric_id: valeur for metric_id in ids})

    reponse = executer(_outil_vue(_faits_entonnoir()), {})

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "REJ-M8-SEUILS-BORNE-SORTIE" in reponse["details"]
    assert all(metric_id in reponse["details"] for metric_id in ids)
    assert valeur not in reponse["details"]
    assert len(reponse["details"]) < 500


def test_lecteur_public_mesures_refuse_trois_seuils_trop_longs_ensemble_sans_les_echo(
    tmp_path, monkeypatch,
):
    chiffres = "9" * (1475 - 3)
    valeur = "19." + chiffres
    seuils = {
        metric_id: valeur
        for metric_id in ("m8_ecart_duree_pct", "m8_ecart_marge_pct", "m8_ecart_materiaux_max_pct")
    }
    _poser_configuration(tmp_path, monkeypatch, seuils, section="seuils_alerte")
    wct_id, devis_id = "wct-fictif-budget", "devis-fictif-budget"
    faits = [
        mesures_chantier.fait_wct({
            "wct_id": wct_id, "intervention_id": "int-fictif-budget", "devis_id": devis_id,
            "technicien_id": "tech-fictif", "horodatage_completion": "2026-09-28T14:00:00-04:00",
            "duree_reelle_minutes": 120, "statut": "completed_verified",
        }),
        mesures_chantier.fait_devis({
            "devis_id": devis_id, "prix_total": "600.00", "cout_total": "480.00",
            "duree_estimee_minutes": "100", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
        }),
        mesures_chantier.fait_variance({
            "wct_id": wct_id, "statut_variance": "evaluee", "signal_critique": True,
            "seuil_pourcentage": 0.3,
            "lignes": [
                {"materiau": "gouttiere-fictif", "unite": "pi", "quantite_prevue": "40",
                 "quantite_reelle": "56", "ecart_pourcentage": "0.4", "critique": True},
                {"materiau": "crochet-fictif", "unite": "u", "quantite_prevue": "20",
                 "quantite_reelle": "22", "ecart_pourcentage": "0.1", "critique": False},
            ],
        }),
        mesures_chantier.fait_rentabilite({
            "wct_id": wct_id, "devis_id": devis_id, "sequence": 1, "verdict": "CALCULEE",
            "cout_reel_complet": True, "prix_definitif": True, "marge_reelle_cad": "90.00", "manque": [],
        }),
    ]
    par_nom = {
        outil.nom: outil for outil in outils(
            RegistreSnapshots(), [], faits, faits_cash_libre_cible=[], faits_operations_cible=[],
        )
    }

    reponse = executer(par_nom["m8_lire_mesures_chantier"], {"wct_id": wct_id})

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "REJ-M8-SEUILS-BORNE-SORTIE" in reponse["details"]
    assert all(metric_id in reponse["details"] for metric_id in seuils)
    assert valeur not in reponse["details"] and len(reponse["details"]) < 500
