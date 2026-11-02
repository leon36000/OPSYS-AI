"""Catalogue fermé des mesures (M8.2, M8.8, M8.11, M8.12, M8.14) et moteur de lecture commun.

Prouve : le catalogue est fermé et validé (clé inconnue, énuméré hors liste, doublon, synonyme partagé, fenêtre
invalide,
métrique non définie = refus typé) ; chaque entrée tient nom, unité, propriétaire et version de sa définition
gouvernée ;
le moteur lit les 59 mesures depuis les registres fictifs avec leur provenance, sans jamais inventer un zéro ; les
mesures
de synthèse (chantiers, écart d'équipe, signal de matériaux, cash libre) reprennent les verdicts des départements.
"""

from __future__ import annotations

import copy

import pytest
import yaml
from m8_analytics import catalogue_mesures, jeux_fictifs, moteur_mesures, synthese

FICTIF = True


def _ecrire(tmp_path, contenu):
    chemin = tmp_path / "catalogue.yaml"
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    return chemin


@pytest.fixture(scope="module")
def brut():
    chemin = catalogue_mesures._CHEMIN_CATALOGUE
    return yaml.safe_load(chemin.read_text(encoding="utf-8"))


def test_le_catalogue_livre_est_valide_ferme_et_complet():
    catalogue = catalogue_mesures.charger()
    ids = [entree["metric_id"] for entree in catalogue["mesures"]]
    assert len(ids) == len(set(ids)) == 59  # 18 de la tranche 1 + 20 interdépartements + 21 de la phase 2
    assert set(ids) == set(catalogue_mesures.definitions_gouvernees())  # toute métrique gouvernée est au catalogue
    assert len(catalogue["version_catalogue"]) == 64
    for entree in catalogue["mesures"]:
        assert entree["nom"] and entree["unite"] and entree["proprietaire"].startswith("m0")
        assert len(entree["version_definition"]) == 64


def test_aucune_mesure_du_catalogue_n_est_personnelle():
    catalogue = catalogue_mesures.charger()
    assert {entree["sensibilite"] for entree in catalogue["mesures"]} <= {"agregat", "financier"}
    financiers = {e["metric_id"] for e in catalogue["mesures"] if e["sensibilite"] == "financier"}
    assert financiers == {
        "m8_carnet_signe_cad", "m8_cash_libre_cad", "m8_marge_reelle_cumulee_cad", "m8_ecart_marge_cumule_cad",
        "m8_creances_ouvertes_cad", "m8_creances_90_jours_plus_cad", "m8_comptes_a_payer_cad",
        "m8_releves_depense_pub_cad", "m8_ecart_depense_pub_comptabilisee_cad", "m8_solde_tresorerie_cad",
        "m8_taxes_a_remettre_cad", "m8_depense_pub_comptabilisee_cad", "m8_facturation_emise_cad",
        "m8_valeur_ponderee_pipeline_cad", "m8_cout_par_lead_pub_cad",
    }
    for entree in catalogue["mesures"]:
        assert "technicien" not in entree["metric_id"] and "client" not in entree["metric_id"]


def test_la_version_du_catalogue_change_si_et_seulement_si_une_entree_change(tmp_path, brut):
    a = catalogue_mesures.charger()
    meme = catalogue_mesures.charger(_ecrire(tmp_path, brut))
    assert meme["version_catalogue"] == a["version_catalogue"]
    modifie = copy.deepcopy(brut)
    modifie["mesures"][0]["sens"] = "moins_est_mieux"
    assert catalogue_mesures.charger(_ecrire(tmp_path, modifie))["version_catalogue"] != a["version_catalogue"]


def _fraicheur(valeur):
    """Une mutation du catalogue : la fraîcheur de la première entrée devient `valeur`."""
    return lambda c: c["mesures"][0].update({"fraicheur": valeur})


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda c: c["mesures"][0].update({"inconnue": 1}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][0].pop("sens"), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][0].update({"domaine": "astrologie"}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][0].update({"sensibilite": "personnel"}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][0].update({"metric_id": "m8_sql_libre"}), "REJ-CATALOGUE-METRIQUE-INCONNUE"),
        (lambda c: c["mesures"].append(copy.deepcopy(c["mesures"][0])), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][1]["synonymes"].append("leads reçus"), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][0].update({"synonymes": []}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][0].update({"synonymes": ["  !! "]}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][0].update({"fraicheur": {"fenetre_s": 0}}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c["mesures"][0].update({"fraicheur": {"fenetre_s": True}}), "REJ-CATALOGUE-INVALIDE"),
        (
            lambda c: c["mesures"][0].update({"fraicheur": {"fenetre_s": 5, "terminale": True}}),
            "REJ-CATALOGUE-INVALIDE",
        ),
        (lambda c: c["mesures"][0].update({"fraicheur": {"terminale": False}}), "REJ-CATALOGUE-INVALIDE"),
        # D7 : la cadence est OBLIGATOIRE (null quand la source est sporadique et non déclarée), valide, et seule.
        (_fraicheur({"fenetre_s": 86400}), "REJ-CATALOGUE-INVALIDE"),
        (_fraicheur({"fenetre_s": 86400, "cadence_s": 0}), "REJ-CATALOGUE-INVALIDE"),
        (_fraicheur({"fenetre_s": 86400, "cadence_s": True}), "REJ-CATALOGUE-INVALIDE"),
        (_fraicheur({"fenetre_s": 86400, "cadence_s": "7 j"}), "REJ-CATALOGUE-INVALIDE"),
        (_fraicheur({"cadence_s": 86400}), "REJ-CATALOGUE-INVALIDE"),
        (_fraicheur({"terminale": True, "cadence_s": 86400}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c.update({"schema": "autre"}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c.update({"extra": 1}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c.update({"mesures": []}), "REJ-CATALOGUE-INVALIDE"),
        (lambda c: c.update({"version": 0}), "REJ-CATALOGUE-INVALIDE"),
    ],
)
def test_un_catalogue_mal_forme_est_refuse_avec_un_code_type(tmp_path, brut, mutation, code):
    mauvais = copy.deepcopy(brut)
    mutation(mauvais)
    with pytest.raises(catalogue_mesures.CatalogueRefuse) as exc:
        catalogue_mesures.charger(_ecrire(tmp_path, mauvais))
    assert exc.value.code == code


def test_un_fichier_absent_ou_illisible_est_refuse(tmp_path):
    with pytest.raises(catalogue_mesures.CatalogueRefuse) as exc:
        catalogue_mesures.charger(tmp_path / "absent.yaml")
    assert exc.value.code == "REJ-CATALOGUE-ILLISIBLE"
    (tmp_path / "casse.yaml").write_text("a: [", encoding="utf-8")
    with pytest.raises(catalogue_mesures.CatalogueRefuse):
        catalogue_mesures.charger(tmp_path / "casse.yaml")


def test_la_normalisation_replie_accents_casse_et_ponctuation():
    assert catalogue_mesures.normaliser("  Taux d’Acceptation, des DÉVIS ?! ") == "taux d acceptation des devis"
    assert catalogue_mesures.normaliser("") == ""


# ---------------------------------------------------------------------------
# Le moteur : les registres deviennent des mesures, une seule fois
# ---------------------------------------------------------------------------
def test_le_moteur_lit_les_cinquante_neuf_mesures_avec_provenance():
    mesures = moteur_mesures.lire(jeux_fictifs.registres_fictifs())
    par_id = {m["metric_id"]: m for m in mesures}
    assert len(mesures) == 59
    assert par_id["m8_leads_recus"]["valeur"] == "20" and par_id["m8_devis_acceptes"]["valeur"] == "6"
    assert par_id["m8_taux_acceptation_pct"]["valeur"] == "50.00"
    assert par_id["m8_carnet_signe_cad"]["valeur"] == "25000.00"  # 6 devis acceptés − 4 chantiers terminés = 2 × 12500
    assert par_id["m8_chantiers_termines"]["valeur"] == "4"
    assert par_id["m8_ecart_duree_equipe_pct"]["valeur"] == "10.00"
    assert par_id["m8_chantiers_signal_materiaux"]["valeur"] == "0"
    assert par_id["m8_cash_libre_cad"]["valeur"] == "25000.00"
    for mesure in mesures:
        assert mesure["source"] or mesure["statut"] == "non_calculable"
        assert len(mesure["version_definition"]) == 64 and "fraicheur_declaree" in mesure


def test_impressions_et_clics_restent_non_calculables_jamais_zero():
    par_id = {m["metric_id"]: m for m in moteur_mesures.lire(jeux_fictifs.registres_fictifs())}
    for cle in ("m8_impressions_par_contenu", "m8_clics_par_contenu"):
        assert par_id[cle]["statut"] == "non_calculable" and par_id[cle]["valeur"] is None
        assert "impressions et des clics" in par_id[cle]["detail"] and par_id[cle]["dernier_fait_le"] is None


def test_registres_vides_toutes_les_mesures_sont_non_calculables_avec_ce_qui_manque():
    vide = {"chantier": [], "entonnoir": [], "contenus": [], "cash_libre": [], "operations": []}
    for mesure in moteur_mesures.lire(vide):
        assert mesure["statut"] == "non_calculable" and mesure["valeur"] is None
        assert mesure["manque"] and mesure["detail"].startswith("non calculable, manque")


def test_les_mesures_de_synthese_reprennent_les_verdicts_des_departements():
    registres = jeux_fictifs.registres_fictifs(chantiers=4, signaux_materiaux=3, ecart_duree_pct=25)
    par_id = {m["metric_id"]: m for m in moteur_mesures.lire(registres)}
    assert par_id["m8_chantiers_signal_materiaux"]["valeur"] == "3"
    assert par_id["m8_chantiers_signal_materiaux"]["entrees"]["n_variances_evaluees"] == 4
    assert par_id["m8_ecart_duree_equipe_pct"]["valeur"] == "25.00"


def test_sans_variance_evaluee_le_signal_de_materiaux_est_non_calculable():
    registres = jeux_fictifs.registres_fictifs(avec_variance=False)
    mesure = {m["metric_id"]: m for m in moteur_mesures.lire(registres)}["m8_chantiers_signal_materiaux"]
    assert mesure["statut"] == "non_calculable" and mesure["valeur"] is None
    assert mesure["manque"][0]["champ"] == "m6.variance_chantier"


def test_sans_duree_estimee_l_ecart_d_equipe_est_non_calculable():
    registres = jeux_fictifs.registres_fictifs()
    registres["chantier"] = [f for f in registres["chantier"] if f["type_entree"] != "devis"]
    mesure = {m["metric_id"]: m for m in moteur_mesures.lire(registres)}["m8_ecart_duree_equipe_pct"]
    assert mesure["statut"] == "non_calculable" and mesure["manque"][0]["champ"] == "duree_estimee_minutes"
    assert mesure["entrees"]["n_chantiers_sans_temps_prevu"] == 4


def test_le_cash_libre_non_calculable_de_m5_est_repris_sans_zero():
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad=None)
    mesure = {m["metric_id"]: m for m in moteur_mesures.lire(registres)}["m8_cash_libre_cad"]
    assert mesure["statut"] == "non_calculable" and mesure["valeur"] is None
    assert "REJ-CASH-SOLDE-ABSENT" in mesure["manque"][0]["raison"]


def test_le_dernier_constat_du_cash_libre_fait_foi_quel_que_soit_l_ordre():
    registres = jeux_fictifs.registres_fictifs()
    ancien = dict(registres["cash_libre"][0])
    recent = {**ancien, "evenement_id": "m5-cash-libre-2", "sequence": 2, "cash_libre_cad": "100.00"}
    registres["cash_libre"] = [recent, ancien]
    mesure = {m["metric_id"]: m for m in moteur_mesures.lire(registres)}["m8_cash_libre_cad"]
    assert mesure["valeur"] == "100.00"


def test_une_date_de_constat_illisible_donne_un_instant_inconnu_pas_une_erreur():
    registres = jeux_fictifs.registres_fictifs()
    registres["cash_libre"][0]["date_reference"] = "demain-ish"
    mesure = {m["metric_id"]: m for m in moteur_mesures.lire(registres)}["m8_cash_libre_cad"]
    assert mesure["valeur"] == "25000.00" and mesure["dernier_fait_le"] is None


def test_l_empreinte_des_registres_suit_le_contenu():
    a = jeux_fictifs.registres_fictifs()
    b = jeux_fictifs.registres_fictifs()
    assert moteur_mesures.empreinte_registres(a) == moteur_mesures.empreinte_registres(b)
    b["contenus"].pop()
    assert moteur_mesures.empreinte_registres(a) != moteur_mesures.empreinte_registres(b)


def test_les_definitions_de_synthese_sont_gouvernees_et_en_cad():
    definitions = synthese.charger_definitions()
    assert set(definitions) == {
        "m8_chantiers_termines",
        "m8_ecart_duree_equipe_pct",
        "m8_chantiers_signal_materiaux",
        "m8_cash_libre_cad",
    }
    assert definitions["m8_cash_libre_cad"]["unite"] == "CAD"
    assert "CPA" in definitions["m8_cash_libre_cad"]["definition"]


@pytest.mark.parametrize(
    "parametres",
    [
        {"qualifies": 21},
        {"envoyes": 21},
        {"acceptes": 13},
        {"sans_reponse": 7},
        {"chantiers": 7},
        {"signaux_materiaux": 5},
    ],
)
def test_les_jeux_fictifs_refusent_des_comptes_incoherents(parametres):
    with pytest.raises(ValueError, match="incoh"):
        jeux_fictifs.registres_fictifs(**parametres)


def test_la_cadence_est_declaree_la_ou_la_source_la_fixe_et_null_ailleurs():
    """D7 : aucune cadence n'est inventée. La capacité d'équipe est constatée par semaine (604800 s) ; les sources
    sporadiques
    (factures, plaintes, relevés...) déclarent `null` et le propriétaire peut les fixer (`cadences_mesures_s`)."""
    catalogue = catalogue_mesures.par_identifiant(catalogue_mesures.charger())
    avec_cadence = {m: e["fraicheur"]["cadence_s"] for m, e in catalogue.items() if e["fraicheur"].get("cadence_s")}
    assert avec_cadence == {
        "m8_capacite_heures_disponibles": 604800,
        "m8_capacite_heures_planifiees": 604800,
        "m8_charge_planifiee_pct": 604800,
    }
    for metric_id, entree in catalogue.items():
        if "terminale" not in entree["fraicheur"]:
            assert "cadence_s" in entree["fraicheur"], metric_id
