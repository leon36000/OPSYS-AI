"""Aide NON COLLECTÉE des tests d'Athéna (M9) : pages de réponse de producteurs FICTIVES, de la forme exacte que les
VRAIS
outils rendent (constatée par `tests/test_m9_athena_raccord.py` sur les vrais départements), et chaîne de captures.

Tout est fictif (`FICTIF = True`). Les pages sont celles que `charges_athena` doit admettre ; les tests les altèrent
pour
prouver que chaque règle du contrat refuse.
"""

from __future__ import annotations

import copy

from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat

FICTIF = True
HEX = "ab" * 32
MAINTENANT = "2026-10-28T12:00:00Z"
JOUR = "2026-10-28"


def ok(corps: dict) -> dict:
    return {"ok": True, "resultat": corps}


def mesure(metric_id="m8_leads_recus", *, valeur="12", fraicheur="a_jour", age=3600, fenetre=86400, domaine="ventes",
           unite="leads", manque=None, dernier="2026-10-28T10:00:00Z") -> dict:  # fmt: skip
    calculee = valeur is not None
    return {
        "metric_id": metric_id, "domaine": domaine, "unite": unite,
        "statut": "calculee" if calculee else "non_calculable", "valeur": valeur,
        "fraicheur": fraicheur, "age_s": age if fraicheur in ("a_jour", "perime", "non_applicable") else None,
        "fenetre_s": fenetre, "dernier_fait_le": dernier if fraicheur != "manquant" else None,
        "version_definition": "0123456789abcdef",
            "manque": manque if manque is not None else ([] if calculee else ["m2.client_associe"]),
    }  # fmt: skip


def page_m8(*, determine=False, validee=False, bornes_manquantes=True, mesures=None) -> dict:
    """Santé + mesures. `determine` : score 71.50 ; sinon indéterminé (bornes à configurer ou mesure manquante)."""
    composantes = [
        {"id": "finance", "libelle": "Finance", "poids": 60, "statut": "determine" if determine else "indetermine",
         "score": "70.00" if determine else None},
        {"id": "ventes", "libelle": "Ventes", "poids": 40, "statut": "determine" if determine else "indetermine",
         "score": "73.75" if determine else None},
    ]  # fmt: skip
    manques = []
    if not determine:
        manques = [
            {"composante": "finance", "metric_id": "m8_cash_libre_cad",
             "raison": "bornes_a_configurer" if bornes_manquantes else "mesure_perimee"},
            {"composante": "ventes", "metric_id": "m8_taux_acceptation_pct", "raison": "mesure_manquante"},
        ]  # fmt: skip
    return ok({
        "type": "SYNTHESE_DIRECTION", "schema": "opsys.m8.synthese_direction/v1", "maintenant": MAINTENANT,
        "version_catalogue": HEX, "empreinte_registres": "cd" * 32,
        "sante": {
            "statut": "determine" if determine else "indetermine", "score": "71.50" if determine else None,
            "ponderations": {"validee": validee, "declaree_par": "proposition de l'architecte",
                             "validee_par": "Nathan (fictif)" if validee else None},
            "version_definition": HEX, "composantes": composantes, "manques": manques, "bornes_invalides": 0,
        },
        "mesures": mesures if mesures is not None else [
            mesure(), mesure("m8_taux_acceptation_pct", valeur="50.00", unite="pourcentage"),
            mesure("m8_contenus_exportes", valeur=None, fraicheur="manquant", domaine="marketing", unite="contenus"),
        ],
        "avertissements": {}, "mention": "Indicateur préparatoire. À valider auprès d'un comptable (CPA) / "
                                         "professionnel qualifié.",
    })  # fmt: skip


def page_m5_statut(*, approuves=0, renseignes=62, sujets=None) -> dict:
    sujets = sujets if sujets is not None else [
        {"sujet": "controle_des_taux_appliques", "genre": "analyse", "statut_sources": "ESSAI_NON_APPROUVE",
         "regles_requises": 2, "regles_non_renseignees": 0, "regles_non_approuvees": 2},
        {"sujet": "structure_juridique", "genre": "piste", "statut_sources": "REGLE_NON_RENSEIGNEE",
         "regles_requises": 3, "regles_non_renseignees": 3, "regles_non_approuvees": 0},
    ]  # fmt: skip
    return ok({"accepte": True, "resultat": {
        "schema": "opsys.m5.statut_revue_fiscale/v1", "aujourd_hui": JOUR,
        "base": {"parametres_renseignes": renseignes,
                 "par_statut": {"brouillon": renseignes - approuves, "revu_1": 0, "approuve": approuves},
                 "non_renseignes": 9, "empreinte_base": HEX},
        "sujets": sujets, "mention": "Analyse préparatoire IA.", "mention_comptable": "À valider auprès d'un "
                                                                                      "comptable (CPA) / "
                                                                                      "professionnel qualifié.",
    }})  # fmt: skip


def page_m5_calendrier(*, taxes=True, validation="A_VALIDER") -> dict:
    echeances = [{
        "periode_debut": "2026-07-01", "periode_fin": "2026-09-30", "periode_terminee": True,
        "limite_paiement": "2026-11-02", "limite_production": "2026-11-02", "jours_avant_paiement": 5,
        "jours_avant_production": 5, "statut": "A_VENIR",
        "taxes_nettes": {"a_remettre": "89.85", "couverture": {"statut": "PARTIELLE", "detail": "x"},
                         "factures_clients": 1, "factures_fournisseurs": 0},
    }] if taxes else []  # fmt: skip
    return ok({"accepte": True, "resultat": {
        "role": "admin", "type": "CALENDRIER_PREPARATOIRE_M5", "aujourd_hui": JOUR,
        "obligations": [{
            "id": "paies", "nom": "Paies", "autorite": None, "periode": {"debut": None, "fin": None},
            "echeance": "2026-11-09", "montant": "4200.00", "devise": "CAD",
            "source_montant": {"description": "brouillon de paie (fictif)", "au": "2026-10-25"},
            "source_echeance": {"description": None, "consultee_le": None, "applicable_du": None,
                "applicable_jusqu_au": None},
            "annee": None, "version": None, "montant_utilisable": "4200.00", "echeance_statut": "A_VENIR",
            "statut": "INCOMPLETE", "manque": [{"code": "REJ-CALENDRIER-PAIES-SOURCE-INVALIDE", "detail": "x"}],
        }],
        "echeances_tps_tvq": {"statut": "DOCUMENTE_A_VALIDER", "echeances": echeances,
                              "validation_cpa": {"2026": validation}},
        "limites": ["x"], "mention": "Analyse préparatoire IA.",
    }})  # fmt: skip


def intervalle(bas="80.00", haut="140.00", centre="110.00", niveau=80) -> dict:
    return {"centre": centre, "intervalle": {"niveau": niveau, "bas": bas, "haut": haut}}


def page_m2_analyse(*, avec_valeur=True, taux_suffisant=True) -> dict:
    taux_ok = {"valeur": "0.3333", "n": 30, "seuil": 20, "succes": 10}
    taux_ko = {
        "valeur": None,
        "n": 4,
        "seuil": 20,
        "refus": "échantillon insuffisant pour le taux : 4 observé(s), 20 exigés",
    }
    taux = taux_ok if taux_suffisant else taux_ko
    pondere: dict = {"ouverts": 5, "sans_valeur_declaree": 0, "valeur_declaree_totale": "25000.00"}
    if avec_valeur:
        pondere["valeur_ponderee"] = {**intervalle("2000.00", "9000.00", "5000.00"), "methode": "x"}
        pondere["unite"] = "CAD"
    else:
        pondere.update(valeur_ponderee=None, refus="non calculable : aucune valeur déclarée sur les leads ouverts")
    return ok({"accepte": True, "resultat": {
        "perimetre": "tous les leads", "reference": MAINTENANT,
        "pipeline": {"par_statut": {"nouveau": 3, "qualifie": 2, "converti": 10, "perdu": 5}, "ouverts": 5,
            "total": 20},
        "entonnoir": {"ingeres": 20, "qualifies_un_jour": 15, "convertis_un_jour": 10, "perdus": 5, "resolus": 15},
        "taux_conversion_des_resolus": taux, "taux_qualification": taux,
        "delai_de_cycle": {"n": 4, "seuil": 10, "unite": "jours", "valeurs": None, "refus": "échantillon insuffisant"},
        "probabilite_de_conversion_par_etape": {"nouveau": taux, "qualifie": taux},
        "valeur_ponderee": pondere, "seuils_declares": {"resolus_conversion": 20},
        "avertissements": ["Information commerciale."], "empreinte_recu": "ef" * 32,
    }})  # fmt: skip


def page_m2_prevision(*, periodes=16, evenements=80, horizon=2) -> dict:
    return ok({"accepte": True, "resultat": {
        "reference": MAINTENANT,
        "serie": {"nom": "leads_ingeres", "unite": "semaine", "periodes": periodes, "evenements": evenements},
        "prevision_totale": {"horizon_periodes": horizon, **intervalle("8.00", "20.00", "14.00")},
        "par_periode": [{"periode": k + 1, **intervalle("3.00", "11.00", "7.00")} for k in range(horizon)],
        "erreur_absolue_moyenne_un_pas": "1.5000", "niveau_courant": "7.0000",
        "seuils_declares": {"periodes_minimum": 12, "evenements_minimum": 20},
        "methode": "moyenne_mobile (fenêtre 3)", "avertissements": ["Le centre n'est pas une promesse."],
        "empreinte_recu": "12" * 32,
    }})  # fmt: skip


def page_m10(consolidations=None, total=None) -> dict:
    consolidations = consolidations if consolidations is not None else [{
        "evenement_id": "m8-faits-" + "34" * 32, "consolide_le": "2026-10-28T06:30:00Z", "ligne_id": "L1",
        "n_mesures": 18, "changements_definition": [],
        "anomalies": [{"metric_id": "m8_cash_libre_cad", "type": "perimee"}], "premiere_consolidation": False,
    }]  # fmt: skip
    total = len(consolidations) if total is None else total
    return ok({"total": total, "decalage": 0, "limite": 8, "consolidations": consolidations, "suivant": None,
               "confidentialite": "FINANCIAL"})  # fmt: skip


ARGUMENTS = {
    "m8.synthese_direction": {"maintenant": MAINTENANT},
    "m2.analyse_pipeline": {"horodatage": MAINTENANT},
    "m2.prevision_pipeline": {"horodatage": MAINTENANT, "serie": "leads_ingeres", "methode": "moyenne_mobile",
                              "fenetre": 3, "horizon": 2},
    "m5.statut_revue_fiscale": {"aujourd_hui": JOUR},
    "m5.calendrier_obligations": {"aujourd_hui": JOUR},
    "m10.faits_analytiques": {},
}  # fmt: skip


def capturer(chaine: list, lecture_id: str, page: dict, recu_a: str, *, arguments: dict | None = None) -> dict:
    """Ajoute à `chaine` la capture de `page` (refus si la charge viole son contrat) et la rend."""
    lecture = cat.PAR_ID[lecture_id]
    args = copy.deepcopy(arguments if arguments is not None else ARGUMENTS[lecture_id])
    reference = args.get(lecture.reference) if lecture.reference else None
    capture = cs.construire(
        lecture, args, [page], recu_a=recu_a, reference=reference, index=len(chaine),
        hash_precedent=chaine[-1]["hash_maillon"] if chaine else cs.HASH_INITIAL,
        dernier_recu_a=chaine[-1]["recu_a"] if chaine else None,
    )  # fmt: skip
    chaine.append(capture)
    return capture
