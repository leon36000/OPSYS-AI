"""PLAN T4.16 : le calendrier fiscal vivant (M5.5) : `contracts/calendrier_fiscal.v1.yaml` et `calendrier_fiscal.py`.

Ce que les tests prouvent :
1. le fichier suit le patron de `taux_fiscaux.v1.yaml` (année, sources officielles avec adresse et date de
  consultation, version) et ses dates sont celles des tableaux de Revenu Québec (des dates clés vérifiées une à une) ;
2. le chargeur REFUSE tout fichier incohérent (jamais un calendrier à moitié lu) ;
3. FAIL-CLOSED : une année non déclarée est refusée, la fréquence de production (décision du propriétaire, GATE
  NATHAN) n'est jamais supposée, la date de dernière remise non plus ;
4. les échéances sont chiffrées à la date près, avec les retards, et portent la mention obligatoire.

Le calendrier propose : aucune remise, aucune déclaration, aucun paiement. Les entreprises et les dates de «
aujourd'hui » sont fictives ; les dates limites, elles, sont celles publiées par l'administration fiscale, à valider
par le CPA.
"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest
import yaml
from m5_financecore import calendrier_fiscal as cf
from m5_financecore import validation
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION

_M5 = Path(__file__).resolve().parents[1]
CHEMIN = _M5 / "contracts" / "calendrier_fiscal.v1.yaml"
AUJOURD_HUI = "2026-09-29"

TRIMESTRIELLE_DECEMBRE = {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12}


@pytest.fixture(scope="module")
def calendrier():
    dictionnaire, erreurs = cf.charger_calendrier_fiscal(CHEMIN)
    assert erreurs == []
    return dictionnaire


def _brut():
    return yaml.safe_load(CHEMIN.read_text(encoding="utf-8"))


def _charger_modifie(tmp_path, modifier):
    contenu = _brut()
    modifier(contenu)
    chemin = tmp_path / "calendrier.yaml"
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return cf.charger_calendrier_fiscal(chemin)


def _annee(contenu, annee=2026):
    return next(a for a in contenu["annees"] if a["annee"] == annee)


# ==================================================================================== 1. le fichier livré
def test_le_calendrier_livre_se_charge_sans_erreur_et_declare_deux_annees(calendrier):
    assert sorted(calendrier) == [2025, 2026]
    for donnees in calendrier.values():
        assert {f: len(p) for f, p in donnees["periodes"].items()} == {
            "mensuelle": 12, "trimestrielle": 12, "annuelle": 12}


def test_chaque_annee_cite_ses_sources_officielles_avec_adresse_date_de_consultation_et_version(calendrier):
    """Même patron que `taux_fiscaux.v1.yaml` : année, source officielle citée, version (et, T3, sa validation)."""
    for annee, donnees in calendrier.items():
        assert donnees["version"] == f"{annee}-v1"
        assert donnees["validation_cpa"] == "A_VALIDER", "aucune date n'est confirmée par le CPA"
        organismes = {source["organisme"] for source in donnees["sources"]}
        assert organismes == {"Revenu Québec", "Agence du revenu du Canada"}
        for source in donnees["sources"]:
            assert source["url"].startswith(("https://www.revenuquebec.ca/", "https://www.canada.ca/"))
            assert date.fromisoformat(source["consulte_le"]) == date(2026, 9, 29)
            assert source["titre"]


def test_le_fichier_dit_ce_qu_il_ne_couvre_pas_et_qu_il_est_a_valider():
    texte = CHEMIN.read_text(encoding="utf-8")
    assert "A VALIDER PAR LE CPA" in texte
    for hors_perimetre in ("acomptes provisionnels", "DAS", "GATE NATHAN"):
        assert hors_perimetre in texte


@pytest.mark.parametrize("annee, frequence, mois_fin, limite_paiement, limite_production", [
    # Revenu Québec, « Calendriers TVQ et TPS/TVH » (mensuel 2026) : le report d'un jour férié, de la fin de semaine
    # et des Fêtes est celui de l'administration fiscale, transcrit tel quel.
    (2026, "mensuelle", 1, "2026-03-02", "2026-03-02"),   # 28 février est un samedi
    (2026, "mensuelle", 8, "2026-10-01", "2026-10-01"),   # 30 septembre est férié
    (2026, "mensuelle", 9, "2026-11-02", "2026-11-02"),   # 31 octobre est un samedi
    (2026, "mensuelle", 11, "2027-01-05", "2027-01-05"),  # la période des Fêtes
    (2026, "mensuelle", 12, "2027-02-01", "2027-02-01"),  # 31 janvier est un dimanche
    (2025, "mensuelle", 12, "2026-02-02", "2026-02-02"),
    (2026, "trimestrielle", 3, "2026-04-30", "2026-04-30"),
    (2026, "trimestrielle", 12, "2027-02-01", "2027-02-01"),
    (2026, "annuelle", 3, "2026-06-30", "2026-06-30"),
    (2026, "annuelle", 12, "2027-03-31", "2027-03-31"),   # règle générale : trois mois après la fin
])
def test_des_dates_cles_sont_celles_du_tableau_officiel(calendrier, annee, frequence, mois_fin, limite_paiement,
                                                          limite_production):
    periode = next(p for p in calendrier[annee]["periodes"][frequence] if p["fin"].month == mois_fin)
    assert (periode["limite_paiement"].isoformat(), periode["limite_production"].isoformat()) == (
        limite_paiement, limite_production)


def test_le_particulier_en_affaires_paie_le_30_avril_et_produit_le_15_juin(calendrier):
    """Revenu Québec, « Périodes de déclaration » : période annuelle, exercice au 31 décembre, revenu d'entreprise."""
    for annee in (2025, 2026):
        periode = calendrier[annee]["annuelle_particulier_decembre"]
        assert periode["fin"] == date(annee, 12, 31)
        assert periode["limite_paiement"] == date(annee + 1, 4, 30)
        assert periode["limite_production"] == date(annee + 1, 6, 15)


def test_aucune_echeance_publiee_ne_tombe_une_fin_de_semaine(calendrier):
    for donnees in calendrier.values():
        toutes = [p for periodes in donnees["periodes"].values() for p in periodes]
        toutes.append(donnees["annuelle_particulier_decembre"])
        for periode in toutes:
            assert periode["limite_paiement"].weekday() < 5 and periode["limite_production"].weekday() < 5, periode


# ==================================================================================== 2. le chargeur refuse
@pytest.mark.parametrize("nom, modifier, extrait", [
    ("schema", lambda c: c.update(schema_version=2), "schema_version invalide"),
    ("sans_annees", lambda c: c.update(annees=[]), "clé 'annees'"),
    ("annee_texte", lambda c: _annee(c).update(annee="2026"), "'annee' doit être un entier"),
    ("cle_en_trop", lambda c: _annee(c).update(surprise=1), "clés non conformes"),
    ("sans_sources", lambda c: _annee(c).update(sources=[]), "au moins une source officielle"),
    ("source_http", lambda c: _annee(c)["sources"][0].update(url="http://exemple.test/"), "adresse https"),
    ("consultation_illisible", lambda c: _annee(c)["sources"][0].update(consulte_le="hier"), "date de consultation"),
    ("validation_inconnue", lambda c: _annee(c).update(validation_cpa="OK"), "validation_cpa"),
    ("version_vide", lambda c: _annee(c).update(version=""), "version texte non vide"),
    ("onze_mois", lambda c: _annee(c)["periodes"]["mensuelle"].pop(), "douze périodes"),
    ("frequence_absente", lambda c: _annee(c)["periodes"].pop("annuelle"), "periodes doit porter exactement"),
    ("samedi", lambda c: _annee(c)["periodes"]["mensuelle"][0].update(limite_paiement="2026-02-28"),
     "un samedi ou un dimanche"),
    ("trop_tard", lambda c: _annee(c)["periodes"]["mensuelle"][0].update(limite_paiement="2026-03-10"),
     "reportée de six jours au plus"),
    ("trop_tot", lambda c: _annee(c)["periodes"]["mensuelle"][0].update(limite_paiement="2026-02-23"),
     "reportée de six jours au plus"),
    ("fin_pas_fin_de_mois", lambda c: _annee(c)["periodes"]["mensuelle"][0].update(fin="2026-01-30"),
     "dernier jour d'un mois"),
    ("debut_faux", lambda c: _annee(c)["periodes"]["trimestrielle"][2].update(debut="2026-02-01"),
     "commence le lendemain"),
    ("mauvaise_annee", lambda c: _annee(c)["periodes"]["mensuelle"][0].update(
        debut="2025-01-01", fin="2025-01-31", limite_paiement="2025-02-28"), "de l'année 2026"),
    ("date_yaml_non_citee", lambda c: _annee(c)["periodes"]["mensuelle"][0].update(
        limite_paiement=date(2026, 3, 2)), "entre guillemets"),
    ("cle_periode_manquante", lambda c: _annee(c)["periodes"]["mensuelle"][0].pop("debut"), "clés non conformes"),
    ("mois_dans_le_desordre", lambda c: _annee(c)["periodes"]["mensuelle"].reverse(), "de janvier à décembre"),
    ("particulier_pas_decembre", lambda c: _annee(c)["annuelle_particulier_decembre"].update(
        debut="2025-07-01", fin="2026-06-30", limite_paiement="2027-04-30", limite_production="2027-06-15"),
     "exercice au 31 décembre exigé"),
    ("report_de_sept_jours", lambda c: _annee(c)["periodes"]["mensuelle"][2].update(limite_paiement="2026-05-07"),
     "reportée de six jours au plus"),
    ("particulier_sans_production", lambda c: _annee(c)["annuelle_particulier_decembre"].pop("limite_production"),
     "clés non conformes"),
])
def test_le_chargeur_refuse_un_fichier_incoherent(tmp_path, nom, modifier, extrait):
    calendrier, erreurs = _charger_modifie(tmp_path, modifier)

    assert erreurs, nom
    assert any(extrait in erreur for erreur in erreurs), erreurs
    if nom not in {"schema", "sans_annees"}:
        assert 2026 not in calendrier, "une année invalide n'est jamais utilisée"


def test_un_fichier_absent_ou_illisible_est_refuse(tmp_path):
    assert cf.charger_calendrier_fiscal(tmp_path / "absent.yaml")[1]
    illisible = tmp_path / "casse.yaml"
    illisible.write_text("annees: [", encoding="utf-8")
    assert cf.charger_calendrier_fiscal(illisible)[1]
    assert cf.charger_calendrier_fiscal(illisible)[0] == {}


def test_une_annee_dupliquee_est_refusee(tmp_path):
    def dupliquer(contenu):
        contenu["annees"].append(copy.deepcopy(_annee(contenu)))

    calendrier, erreurs = _charger_modifie(tmp_path, dupliquer)

    assert any("année dupliquée 2026" in erreur for erreur in erreurs)
    assert sorted(calendrier) == [2025, 2026]


def test_une_annee_invalide_n_empeche_pas_de_nommer_l_autre_mais_le_fichier_reste_refuse(tmp_path):
    calendrier, erreurs = _charger_modifie(tmp_path, lambda c: _annee(c).update(validation_cpa="OK"))

    assert sorted(calendrier) == [2025] and erreurs


# ============================================================== 3. la configuration : rien n'est supposé
@pytest.mark.parametrize("brut", [None, {}, [], "trimestrielle", {"mois_fin_exercice": 12},
                                  {"frequence_tps_tvq": None}])
def test_sans_frequence_le_verdict_dit_quoi_declarer_et_rien_n_est_suppose(brut):
    configuration, verdict = cf.lire_configuration_fiscale(brut)

    assert configuration is None
    assert verdict["code"] == "REJ-FISCAL-FREQUENCE-A-DECLARER"
    assert "GATE NATHAN" in verdict["detail"] and "configuration.fiscal.frequence_tps_tvq" in verdict["detail"]


@pytest.mark.parametrize("brut, code", [
    ({"frequence_tps_tvq": "bimestrielle"}, "REJ-FISCAL-CONFIGURATION-INVALIDE"),
    ({"frequence_tps_tvq": "Mensuelle"}, "REJ-FISCAL-CONFIGURATION-INVALIDE"),
    ({"frequence_tps_tvq": "trimestrielle"}, "REJ-FISCAL-FIN-EXERCICE-A-DECLARER"),
    ({"frequence_tps_tvq": "annuelle"}, "REJ-FISCAL-FIN-EXERCICE-A-DECLARER"),
    ({"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 13}, "REJ-FISCAL-CONFIGURATION-INVALIDE"),
    ({"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 0}, "REJ-FISCAL-CONFIGURATION-INVALIDE"),
    ({"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": "12"}, "REJ-FISCAL-CONFIGURATION-INVALIDE"),
    ({"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": True}, "REJ-FISCAL-CONFIGURATION-INVALIDE"),
    ({"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12}, "REJ-FISCAL-STATUT-INSCRIT-A-DECLARER"),
    ({"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": "oui"},
     "REJ-FISCAL-CONFIGURATION-INVALIDE"),
])
def test_la_configuration_incomplete_ou_illisible_est_refusee_avec_son_verdict(brut, code):
    configuration, verdict = cf.lire_configuration_fiscale(brut)

    assert configuration is None and verdict["code"] == code
    assert verdict["code"] in validation.CODES_M5


@pytest.mark.parametrize("brut, attendu", [
    ({"frequence_tps_tvq": "mensuelle"}, {"frequence": "mensuelle", "mois_fin_exercice": None, "particulier": None}),
    ({"frequence_tps_tvq": "mensuelle", "mois_fin_exercice": 6},
     {"frequence": "mensuelle", "mois_fin_exercice": None, "particulier": None}),
    (TRIMESTRIELLE_DECEMBRE, {"frequence": "trimestrielle", "mois_fin_exercice": 12, "particulier": None}),
    ({"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 6},
     {"frequence": "annuelle", "mois_fin_exercice": 6, "particulier": None}),
    ({"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": False},
     {"frequence": "annuelle", "mois_fin_exercice": 12, "particulier": False}),
])
def test_la_configuration_complete_est_lue_telle_quelle(brut, attendu):
    assert cf.lire_configuration_fiscale(brut) == (attendu, None)


# ================================================================================ 4. les périodes de l'entreprise
def _fins(periodes):
    return [p["fin"].isoformat() for p in periodes]


def test_mensuelle_douze_periodes_par_annee(calendrier):
    periodes = cf.periodes_applicables(calendrier, {"frequence": "mensuelle", "mois_fin_exercice": None,
                                                    "particulier": None}, (2026,))
    assert len(periodes) == 12 and periodes[0]["fin"] == date(2026, 1, 31) and periodes[-1]["fin"] == date(2026, 12, 31)


@pytest.mark.parametrize("mois_fin, fins", [
    (12, ["2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"]),
    (2, ["2026-02-28", "2026-05-31", "2026-08-31", "2026-11-30"]),
    (1, ["2026-01-31", "2026-04-30", "2026-07-31", "2026-10-31"]),
])
def test_trimestrielle_quatre_periodes_selon_le_mois_de_fin_d_exercice(calendrier, mois_fin, fins):
    configuration = {"frequence": "trimestrielle", "mois_fin_exercice": mois_fin, "particulier": None}
    assert _fins(cf.periodes_applicables(calendrier, configuration, (2026,))) == fins


def test_annuelle_une_periode_et_celle_du_particulier_seulement_pour_lui(calendrier):
    general = {"frequence": "annuelle", "mois_fin_exercice": 12, "particulier": False}
    particulier = {"frequence": "annuelle", "mois_fin_exercice": 12, "particulier": True}
    juin = {"frequence": "annuelle", "mois_fin_exercice": 6, "particulier": None}

    (periode_generale,) = cf.periodes_applicables(calendrier, general, (2026,))
    (periode_particulier,) = cf.periodes_applicables(calendrier, particulier, (2026,))
    (periode_juin,) = cf.periodes_applicables(calendrier, juin, (2026,))

    assert periode_generale["limite_paiement"] == date(2027, 3, 31)
    assert (periode_particulier["limite_paiement"], periode_particulier["limite_production"]) == (
        date(2027, 4, 30), date(2027, 6, 15))
    assert (periode_juin["fin"], periode_juin["limite_paiement"]) == (date(2026, 6, 30), date(2026, 10, 1))


def test_une_annee_absente_ne_donne_aucune_periode(calendrier):
    configuration = {"frequence": "mensuelle", "mois_fin_exercice": None, "particulier": None}
    assert cf.periodes_applicables(calendrier, configuration, (2024, 2027)) == []


# ================================================================ 5. les prochaines échéances, à la date près
def _echeances(calendrier, fiscal, aujourd_hui=AUJOURD_HUI, **kwargs):
    resultat, verdict = cf.prochaines_echeances(calendrier, aujourd_hui, fiscal, **kwargs)
    assert verdict is None, verdict
    return resultat


def _resume(resultat):
    return [(e["periode_fin"], e["limite_paiement"], e["limite_production"], e["statut"], e["jours_avant_paiement"])
            for e in resultat["echeances"]]


def test_trimestrielle_au_31_decembre_apres_une_remise_les_deux_prochaines_echeances(calendrier):
    fiscal = {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": "2026-06-30"}

    resultat = _echeances(calendrier, fiscal)

    assert _resume(resultat) == [
        ("2026-09-30", "2026-11-02", "2026-11-02", "A_VENIR", 34),
        ("2026-12-31", "2027-02-01", "2027-02-01", "A_VENIR", 125),
    ]
    assert resultat["manque"] == [] and resultat["non_affichees"] == 0
    assert [e["periode_debut"] for e in resultat["echeances"]] == ["2026-07-01", "2026-10-01"]
    assert [e["periode_terminee"] for e in resultat["echeances"]] == [False, False]


def test_une_periode_echue_non_remise_est_en_retard(calendrier):
    fiscal = {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": "2026-03-31"}

    resultat = _echeances(calendrier, fiscal)

    assert _resume(resultat) == [
        ("2026-06-30", "2026-07-31", "2026-07-31", "EN_RETARD", -60),
        ("2026-09-30", "2026-11-02", "2026-11-02", "A_VENIR", 34),
        ("2026-12-31", "2027-02-01", "2027-02-01", "A_VENIR", 125),
    ]
    assert resultat["echeances"][0]["periode_terminee"] is True


def test_sans_date_de_derniere_remise_aucun_retard_n_est_dit_et_la_reponse_le_signale(calendrier):
    resultat = _echeances(calendrier, TRIMESTRIELLE_DECEMBRE)

    assert resultat["taxes_remises_jusqu_au"] is None
    assert [e["statut"] for e in resultat["echeances"]] == ["A_VENIR", "A_VENIR"]
    assert [e["periode_fin"] for e in resultat["echeances"]] == ["2026-09-30", "2026-12-31"], "le trimestre échu " \
        "(échéance passée) n'est pas nommé : on ne sait pas s'il est remis"
    assert [m["code"] for m in resultat["manque"]] == ["REJ-FISCAL-REMISE-A-DECLARER"]
    assert "aucun retard" in resultat["manque"][0]["detail"]


def test_mensuelle_sans_remise_les_periodes_dont_une_limite_n_est_pas_passee(calendrier):
    resultat = _echeances(calendrier, {"frequence_tps_tvq": "mensuelle"}, limite=4)

    assert _resume(resultat) == [
        ("2026-08-31", "2026-10-01", "2026-10-01", "A_VENIR", 2),
        ("2026-09-30", "2026-11-02", "2026-11-02", "A_VENIR", 34),
        ("2026-10-31", "2026-11-30", "2026-11-30", "A_VENIR", 62),
        ("2026-11-30", "2027-01-05", "2027-01-05", "A_VENIR", 98),
    ]
    assert resultat["non_affichees"] == 1, "décembre existe aussi (2027-02-01)"


def test_la_limite_borne_les_echeances_rendues_et_compte_le_reste(calendrier):
    resultat = _echeances(calendrier, {"frequence_tps_tvq": "mensuelle"}, limite=2)

    assert len(resultat["echeances"]) == 2 and resultat["non_affichees"] == 3


def test_annuelle_au_31_decembre_le_particulier_paie_le_30_avril_et_produit_le_15_juin(calendrier):
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": True,
              "taxes_remises_jusqu_au": "2025-12-31"}

    (echeance,) = _echeances(calendrier, fiscal)["echeances"]

    assert (echeance["limite_paiement"], echeance["limite_production"]) == ("2027-04-30", "2027-06-15")
    assert (echeance["jours_avant_paiement"], echeance["jours_avant_production"]) == (213, 259)
    assert echeance["periode_debut"] == "2026-01-01" and echeance["periode_fin"] == "2026-12-31"


def test_annuelle_au_31_decembre_hors_particulier_paie_et_produit_le_31_mars(calendrier):
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": False,
              "taxes_remises_jusqu_au": "2025-12-31"}

    (echeance,) = _echeances(calendrier, fiscal)["echeances"]

    assert (echeance["limite_paiement"], echeance["limite_production"], echeance["jours_avant_paiement"]) == (
        "2027-03-31", "2027-03-31", 183)


def test_annuelle_particulier_entre_le_paiement_et_la_production_la_periode_reste_nommee(calendrier):
    """Le 15 mai 2026, le paiement du 30 avril est passé et la production du 15 juin ne l'est pas : la période 2025
    reste nommée. Sans date de dernière remise, aucun retard n'est dit (on ne sait pas si elle est remise)."""
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": True}

    resultat = _echeances(calendrier, fiscal, aujourd_hui="2026-05-15")

    premiere = resultat["echeances"][0]
    assert (premiere["periode_fin"], premiere["limite_paiement"], premiere["limite_production"]) == (
        "2025-12-31", "2026-04-30", "2026-06-15")
    assert (premiere["jours_avant_paiement"], premiere["jours_avant_production"]) == (-15, 31)
    assert premiere["statut"] == "A_VENIR"
    assert [m["code"] for m in resultat["manque"]] == ["REJ-FISCAL-REMISE-A-DECLARER"]


def test_la_reponse_cite_ses_sources_ses_versions_ce_qu_elle_ne_couvre_pas_et_porte_la_mention(calendrier):
    resultat = _echeances(calendrier, {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": "2026-06-30"})

    assert resultat["type"] == "ECHEANCES_FISCALES" and resultat["aujourd_hui"] == AUJOURD_HUI
    assert resultat["mention"] == MENTION
    assert resultat["versions"] == {"2025": "2025-v1", "2026": "2026-v1"}
    assert resultat["validation_cpa"] == {"2025": "A_VALIDER", "2026": "A_VALIDER"}
    assert {s["organisme"] for s in resultat["sources"]} == {"Revenu Québec", "Agence du revenu du Canada"}
    assert all(s["url"].startswith("https://") and s["consulte_le"] for s in resultat["sources"])
    assert any("acomptes provisionnels" in ligne for ligne in resultat["hors_perimetre"])
    assert resultat["annees_declarees"] == [2025, 2026] and resultat["connu_jusqu_au"] == "2027-02-01"
    assert "2027" in resultat["avertissement_couverture"]


def test_la_reponse_est_deterministe_et_ne_change_pas_le_calendrier(calendrier):
    avant = copy.deepcopy(calendrier)
    fiscal = {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": "2026-06-30"}

    assert _echeances(calendrier, fiscal) == _echeances(calendrier, fiscal)
    assert calendrier == avant


# ============================================================= 6. fail-closed : les refus, sans rien rendre
@pytest.mark.parametrize("aujourd_hui", ["2027-01-02", "2027-03-01", "2028-06-01", "2024-06-01", "2023-12-31"])
def test_une_annee_non_declaree_est_refusee_et_aucune_date_n_est_supposee(calendrier, aujourd_hui):
    resultat, verdict = cf.prochaines_echeances(calendrier, aujourd_hui, {"frequence_tps_tvq": "mensuelle"})

    assert resultat is None
    assert verdict["code"] == "REJ-CALENDRIER-ANNEE-NON-DECLAREE"
    assert "déclarées : [2025, 2026]" in verdict["detail"]
    assert "contracts/calendrier_fiscal.v1.yaml" in verdict["detail"] and "valider par le CPA" in verdict["detail"]


def test_l_annee_precedente_est_aussi_exigee(calendrier):
    """Une échéance de janvier vient d'une période terminée l'an d'avant : sans elle, la réponse serait incomplète."""
    seulement_2026 = {2026: calendrier[2026]}

    resultat, verdict = cf.prochaines_echeances(seulement_2026, AUJOURD_HUI, {"frequence_tps_tvq": "mensuelle"})

    assert resultat is None and verdict["code"] == "REJ-CALENDRIER-ANNEE-NON-DECLAREE"
    assert "[2025]" in verdict["detail"]


def _annee_minimale(annee):
    """Une année déclarée réduite à sa période de décembre (forme du chargeur) : de quoi valider une date de
    remise."""
    periode = {"frequence": "mensuelle", "debut": date(annee, 12, 1), "fin": date(annee, 12, 31),
               "limite_paiement": date(annee + 1, 1, 31), "limite_production": date(annee + 1, 1, 31)}
    return {"annee": annee, "version": f"{annee}-v1", "validation_cpa": "A_VALIDER", "sources": [],
            "periodes": {"mensuelle": [periode], "trimestrielle": [], "annuelle": []},
            "annuelle_particulier_decembre": periode}


def test_une_remise_ancienne_exige_toutes_les_annees_qui_la_separent_d_aujourd_hui(calendrier):
    """Une remise de 2023 avec 2024 absente laisserait passer un retard de 2024 : refusé. Avec 2024 déclarée, le
    retard le plus ancien est nommé le premier."""
    fiscal = {"frequence_tps_tvq": "mensuelle", "taxes_remises_jusqu_au": "2023-12-31"}
    sans_2024 = {2023: _annee_minimale(2023), 2025: calendrier[2025], 2026: calendrier[2026]}

    resultat, verdict = cf.prochaines_echeances(sans_2024, AUJOURD_HUI, fiscal)

    assert resultat is None and verdict["code"] == "REJ-CALENDRIER-ANNEE-NON-DECLAREE"
    assert "[2024]" in verdict["detail"]

    avec_2024 = {**sans_2024, 2024: _annee_minimale(2024)}
    resultat = _echeances(avec_2024, fiscal, limite=1)
    (plus_ancien,) = resultat["echeances"]
    assert (plus_ancien["periode_fin"], plus_ancien["statut"], plus_ancien["limite_paiement"]) == (
        "2024-12-31", "EN_RETARD", "2025-01-31")
    assert resultat["non_affichees"] > 10


@pytest.mark.parametrize("aujourd_hui", [None, "", "2026-9-29", "29 septembre 2026", "2026-02-30", 20260929,
                                         date(2026, 9, 29)])
def test_une_date_du_jour_illisible_est_refusee(calendrier, aujourd_hui):
    resultat, verdict = cf.prochaines_echeances(calendrier, aujourd_hui, {"frequence_tps_tvq": "mensuelle"})

    assert resultat is None and verdict["code"] == "REJ-FISCAL-DATE-INVALIDE"


@pytest.mark.parametrize("limite", [0, 13, -1, "4", 2.5, True])
def test_une_limite_hors_bornes_est_refusee(calendrier, limite):
    resultat, verdict = cf.prochaines_echeances(calendrier, AUJOURD_HUI, {"frequence_tps_tvq": "mensuelle"},
                                                limite=limite)

    assert resultat is None and verdict["code"] == "REJ-FISCAL-LIMITE-INVALIDE"


@pytest.mark.parametrize("fiscal, code", [
    (None, "REJ-FISCAL-FREQUENCE-A-DECLARER"),
    ({"taxes_remises_jusqu_au": "2026-06-30"}, "REJ-FISCAL-FREQUENCE-A-DECLARER"),
    ({"frequence_tps_tvq": "trimestrielle"}, "REJ-FISCAL-FIN-EXERCICE-A-DECLARER"),
    ({"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12}, "REJ-FISCAL-STATUT-INSCRIT-A-DECLARER"),
])
def test_sans_decision_du_proprietaire_aucune_echeance_n_est_nommee(calendrier, fiscal, code):
    resultat, verdict = cf.prochaines_echeances(calendrier, AUJOURD_HUI, fiscal)

    assert resultat is None and verdict["code"] == code


@pytest.mark.parametrize("remise, code", [
    ("2026-06-29", "REJ-FISCAL-REMISE-HORS-PERIODE"),      # au milieu d'une période
    ("2026-05-31", "REJ-FISCAL-REMISE-HORS-PERIODE"),      # la fin d'une période... mensuelle, pas trimestrielle
    ("2024-12-31", "REJ-CALENDRIER-ANNEE-NON-DECLAREE"),
    ("2026-06-30 ", "REJ-FISCAL-DATE-INVALIDE"),
    ("30 juin 2026", "REJ-FISCAL-DATE-INVALIDE"),
    (date(2026, 6, 30), "REJ-FISCAL-DATE-INVALIDE"),        # YAML sans guillemets : jamais réinterprété
    ("2026-09-30", "REJ-FISCAL-CONFIGURATION-INVALIDE"),    # la période finit après aujourd'hui : rien n'est remis
    ("2026-12-31", "REJ-FISCAL-CONFIGURATION-INVALIDE"),
])
def test_une_date_de_derniere_remise_incoherente_est_refusee(calendrier, remise, code):
    fiscal = {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": remise}

    resultat, verdict = cf.prochaines_echeances(calendrier, AUJOURD_HUI, fiscal)

    assert resultat is None and verdict["code"] == code


def test_lire_taxes_remises_rend_la_date_ou_dit_quoi_declarer(calendrier):
    configuration, _ = cf.lire_configuration_fiscale(TRIMESTRIELLE_DECEMBRE)

    assert cf.lire_taxes_remises({"taxes_remises_jusqu_au": "2026-06-30"}, calendrier, configuration) == (
        date(2026, 6, 30), None)
    jour, verdict = cf.lire_taxes_remises({}, calendrier, configuration)
    assert jour is None and verdict["code"] == "REJ-FISCAL-REMISE-A-DECLARER"
    assert "taxes_remises_jusqu_au" in verdict["detail"]
    jour, verdict = cf.lire_taxes_remises(None, calendrier, configuration)
    assert jour is None and verdict["code"] == "REJ-FISCAL-REMISE-A-DECLARER"


def test_le_module_ne_lit_aucune_horloge_ni_aucun_registre():
    """Module pur (ADR-0009) : l'AST ne nomme ni horloge, ni réseau, ni registre (le chemin du calendrier est
    surveillé aussi par `verifier_aucun_decaissement`, voir test_cash_libre_sans_decaissement.py)."""
    import ast

    arbre = ast.parse((_M5 / "src" / "m5_financecore" / "calendrier_fiscal.py").read_text(encoding="utf-8"))
    importes = {alias.name for n in ast.walk(arbre) if isinstance(n, ast.Import) for alias in n.names}
    importes |= {n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module}
    assert importes <= {"__future__", "calendar", "re", "collections.abc", "datetime", "pathlib", "typing", "yaml"}
    appels = {n.func.attr for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not appels & {"today", "now", "utcnow", "time", "monotonic"}


# ------------------------------------------------------------------------------------------ cas limites
def test_un_report_de_six_jours_exactement_est_accepte(tmp_path):
    """La règle du 30 avril, reportée de six jours (le 6 mai est un mercredi), passe ; sept jours ne passent pas."""
    calendrier, erreurs = _charger_modifie(
        tmp_path, lambda c: _annee(c)["periodes"]["mensuelle"][2].update(limite_paiement="2026-05-06"))

    assert erreurs == [] and calendrier[2026]["periodes"]["mensuelle"][2]["limite_paiement"] == date(2026, 5, 6)


def test_le_jour_meme_de_l_echeance_la_periode_reste_nommee_a_venir_avec_zero_jour(calendrier):
    """Le 2 novembre 2026, le trimestre échu le 30 septembre est dû AUJOURD'HUI : ni en retard, ni oublié."""
    fiscal = {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": "2026-06-30"}

    resultat = _echeances(calendrier, fiscal, aujourd_hui="2026-11-02")

    premiere = resultat["echeances"][0]
    assert (premiere["periode_fin"], premiere["statut"], premiere["jours_avant_paiement"]) == (
        "2026-09-30", "A_VENIR", 0)
    assert premiere["periode_terminee"] is True


def test_le_lendemain_de_l_echeance_la_periode_non_remise_est_en_retard(calendrier):
    fiscal = {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": "2026-06-30"}

    premiere = _echeances(calendrier, fiscal, aujourd_hui="2026-11-03")["echeances"][0]

    assert (premiere["periode_fin"], premiere["statut"], premiere["jours_avant_paiement"]) == (
        "2026-09-30", "EN_RETARD", -1)


def test_sans_remise_une_echeance_due_aujourd_hui_est_nommee_mais_pas_celle_d_hier(calendrier):
    aujourd_hui = _echeances(calendrier, TRIMESTRIELLE_DECEMBRE, aujourd_hui="2026-11-02")
    lendemain = _echeances(calendrier, TRIMESTRIELLE_DECEMBRE, aujourd_hui="2026-11-03")

    assert aujourd_hui["echeances"][0]["periode_fin"] == "2026-09-30"
    assert lendemain["echeances"][0]["periode_fin"] == "2026-12-31"


def test_la_periode_d_aujourd_hui_n_est_terminee_qu_a_partir_du_lendemain_de_sa_fin(calendrier):
    fiscal = {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": "2026-06-30"}

    dernier_jour = _echeances(calendrier, fiscal, aujourd_hui="2026-09-30")["echeances"][0]
    lendemain = _echeances(calendrier, fiscal, aujourd_hui="2026-10-01")["echeances"][0]

    assert dernier_jour["periode_fin"] == lendemain["periode_fin"] == "2026-09-30"
    assert (dernier_jour["periode_terminee"], lendemain["periode_terminee"]) == (False, True)


def test_une_remise_le_jour_meme_de_la_fin_de_periode_est_refusee(calendrier):
    """Une période finie ce soir n'est pas remise ce soir : la date de remise précède strictement aujourd'hui."""
    fiscal = {**TRIMESTRIELLE_DECEMBRE, "taxes_remises_jusqu_au": "2026-09-30"}

    resultat, verdict = cf.prochaines_echeances(calendrier, "2026-09-30", fiscal)
    veille, verdict_veille = cf.prochaines_echeances(calendrier, "2026-10-01", fiscal)

    assert resultat is None and verdict["code"] == "REJ-FISCAL-CONFIGURATION-INVALIDE"
    assert verdict_veille is None and veille["echeances"][0]["periode_fin"] == "2026-12-31"


@pytest.mark.parametrize("limite, attendu", [(1, 1), (12, 5)])
def test_la_limite_accepte_ses_deux_bornes(calendrier, limite, attendu):
    resultat = _echeances(calendrier, {"frequence_tps_tvq": "mensuelle"}, limite=limite)

    assert len(resultat["echeances"]) == attendu


def test_la_couverture_connue_est_la_derniere_limite_de_production_du_calendrier_de_l_entreprise(calendrier):
    fiscal = {"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": True}

    resultat = _echeances(calendrier, fiscal)

    assert resultat["connu_jusqu_au"] == "2027-06-15", "la production (15 juin) suit le paiement (30 avril)"
