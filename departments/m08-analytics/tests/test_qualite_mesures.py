"""C4 : la qualité des données BRANCHÉE sur les mesures du catalogue (M8.3), les pastilles dérivées, et ce que le
blocage change pour le wallboard, le copilote, le score de santé, la collecte et la mémoire.

Pur (aucune base) : les règles (`definitions/m8-qualite.v1.yaml`), leur évaluation déterministe sur des faits FICTIFS
(`jeux_fictifs`), le blocage d'une mesure (non calculable, aucune valeur, raison nommée), le rétablissement quand les
faits sont corrigés, les six pastilles et leur ordre, la tuile et la bannière, la réponse du copilote (refus expliqué,
jamais un chiffre douteux), la composante du score, la consolidation vers M10. Le scénario de bout en bout (vrai bus,
vrai planificateur) est dans `tests/test_m8_qualite_planifiee.py`.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from pathlib import Path

import pytest
import yaml
from m8_analytics import (
    catalogue_mesures,
    collecte,
    copilote,
    fraicheur_mesures,
    jeux_fictifs,
    memoire,
    moteur_mesures,
    pastilles,
    qualite_mesures,
    sante,
    wallboards,
)

FICTIF = True
CATALOGUE = catalogue_mesures.charger()
REGLES = moteur_mesures.regles_de_qualite(CATALOGUE)
MAINTENANT = dt.datetime(2026, 11, 12, 15, 0, tzinfo=dt.UTC)
FICHIER = Path(qualite_mesures.__file__).resolve().parents[2] / "definitions" / "m8-qualite.v1.yaml"


def _registres(**options):
    return jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True, **options)


def _lues(registres) -> dict[str, dict]:
    return {m["metric_id"]: m for m in moteur_mesures.lire(registres, CATALOGUE)}


def _avec_fraicheur(registres, maintenant=MAINTENANT) -> dict[str, dict]:
    mesures = fraicheur_mesures.lire_mesures_avec_fraicheur(moteur_mesures.lire(registres, CATALOGUE), CATALOGUE,
                                                            maintenant, {})
    return {m["metric_id"]: m for m in pastilles.ajouter(mesures)}


def _fait(registres, type_entree, **modifs):
    """Modifie (sur une copie) le(s) fait(s) d'un type de `operations`."""
    copie = copy.deepcopy(registres)
    for fait in copie["operations"]:
        if fait["type_entree"] == type_entree:
            fait.update(modifs)
    return copie


# ============================================================================================== le fichier de règles
def test_les_regles_du_depot_se_chargent_et_ne_nomment_que_des_mesures_du_catalogue_ferme():
    connues = {e["metric_id"] for e in CATALOGUE["mesures"]}
    genres = {r["type"] for r in REGLES["regles"]}
    assert genres == {"plage", "relation", "controle"}
    nommees = set()
    for r in REGLES["regles"]:
        nommees |= set(r.get("mesures", [])) | {r.get("gauche"), r.get("droite")} | set(r.get("bloque", []))
        assert r["libelle"] and r["correction"] and r["id"].startswith("Q-")
    assert (nommees - {None}) <= connues
    assert len({r["id"] for r in REGLES["regles"]}) == len(REGLES["regles"])
    assert set(qualite_mesures.verifications_possibles()) == {r["controle"] for r in REGLES["regles"]
                                                              if r["type"] == "controle"}


def _brut():
    return yaml.safe_load(FICHIER.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutation", "attendu"),
    [
        (lambda b: b.update(schema="autre"), "schema attendu"),
        (lambda b: b.update(extra=1), "clés inconnues"),
        (lambda b: b["regles"].append(copy.deepcopy(b["regles"][0])), "défini deux fois"),
        (lambda b: b["regles"].append({**copy.deepcopy(b["regles"][0]), "id": "Q-COPIE"}), "déclarée en double"),
        (lambda b: b["regles"][0].update(mesures=["m8_inconnue"]), "hors du catalogue fermé"),
        (lambda b: b["regles"][0].update(mesures=[]), "liste non vide"),
        (lambda b: b["regles"][0].update(mesures=["m8_leads_recus", "m8_leads_recus"]), "nommée deux fois"),
        (lambda b: b["regles"][0].update(type="inconnu"), "type"),
        (lambda b: b["regles"][0].update(extra=1), "clés inconnues"),
        (lambda b: b["regles"][0].pop("correction"), "manquantes"),
        (lambda b: b["regles"][0].update(min=0), "texte décimal"),
        (lambda b: b["regles"][0].update(min="abc"), "texte décimal"),
        (lambda b: b["regles"][0].update(min="5", max="1"), "min dépasse max"),
        (lambda b: b["regles"][0].pop("min"), "au moins une borne"),
        (lambda b: b["regles"][0].update(libelle=" "), "texte"),
        (lambda b: next(r for r in b["regles"] if r["type"] == "controle").update(controle="inconnue"), "controle"),
        (lambda b: next(r for r in b["regles"] if r["type"] == "controle").update(bloque=["m8_x"]), "catalogue"),
        (lambda b: next(r for r in b["regles"] if r["type"] == "relation").update(operateur="egal"), "operateur"),
        (lambda b: b.update(regles=[]), "1 à"),
    ],
)
def test_un_fichier_de_regles_abusif_est_refuse_en_entier(mutation, attendu):
    brut = _brut()
    mutation(brut)
    with pytest.raises(qualite_mesures.QualiteRefusee) as refus:
        qualite_mesures.valider(brut, CATALOGUE)
    assert refus.value.code == qualite_mesures.REJ_QUALITE_INVALIDE and attendu in str(refus.value)


def test_un_fichier_illisible_est_refuse_nommement(tmp_path):
    (tmp_path / "q.yaml").write_text("regles: [", encoding="utf-8")
    with pytest.raises(qualite_mesures.QualiteRefusee) as refus:
        qualite_mesures.charger(CATALOGUE, tmp_path / "q.yaml")
    assert refus.value.code == qualite_mesures.REJ_QUALITE_ILLISIBLE
    with pytest.raises(qualite_mesures.QualiteRefusee):
        qualite_mesures.charger(CATALOGUE, tmp_path / "absent.yaml")


# ================================================================================ des faits sains : rien n'est bloqué
def test_des_faits_sains_ne_bloquent_aucune_mesure_et_chaque_mesure_dit_si_elle_a_ete_jugee():
    lues = _lues(_registres())
    assert all(m["qualite"]["statut"] != "echec" for m in lues.values())
    jugees = {i for i, m in lues.items() if m["qualite"]["statut"] == "ok"}
    assert {"m8_taux_acceptation_pct", "m8_factures_emises", "m8_cash_libre_cad", "m8_creances_ouvertes_cad"} <= jugees
    # une mesure non calculable n'est pas jugée « ok » : elle est « non évaluée », dite telle
    assert lues["m8_clics_par_contenu"]["statut"] == "non_calculable"
    assert lues["m8_clics_par_contenu"]["qualite"] == {"statut": "non_evaluee", "regles_evaluees": 0, "echecs": []}


# ================================================================================ chaque genre de règle, en échec
def _bloquees(registres) -> set[str]:
    return {i for i, m in _lues(registres).items() if m["qualite"]["statut"] == "echec"}


def test_un_revenu_facture_negatif_bloque_les_deux_mesures_de_factures():
    registres = _fait(_registres(), "facture_emise", montant_avant_taxes_cad="-500.00", total_taxes_cad="-74.88",
                      montant_apres_taxes_cad="-574.88")
    assert _bloquees(registres) == {"m8_factures_emises", "m8_facturation_emise_cad"}


def test_un_total_de_facture_qui_n_est_pas_la_somme_de_ses_composantes_bloque():
    registres = _fait(_registres(), "facture_emise", montant_apres_taxes_cad="99999.00")
    assert _bloquees(registres) == {"m8_factures_emises", "m8_facturation_emise_cad"}


def test_une_facture_au_montant_illisible_est_un_echec_pas_un_zero():
    registres = _fait(_registres(), "facture_emise", montant_avant_taxes_cad=None)
    assert _bloquees(registres) == {"m8_factures_emises", "m8_facturation_emise_cad"}


def test_un_total_de_creances_different_de_la_somme_des_tranches_bloque_les_deux_mesures_de_creances():
    registres = copy.deepcopy(_registres())
    comptable = next(f for f in registres["operations"] if f["type_entree"] == "mesures_comptables_constatees")
    comptable["creances"]["total"] = "9999.99"
    lues = _lues(registres)
    assert {i for i, m in lues.items() if m["qualite"]["statut"] == "echec"} == {
        "m8_creances_ouvertes_cad", "m8_creances_90_jours_plus_cad"}
    creances = lues["m8_creances_ouvertes_cad"]
    assert creances["statut"] == "non_calculable" and creances["valeur"] is None


def test_une_tranche_de_creances_negative_bloque():
    registres = copy.deepcopy(_registres())
    comptable = next(f for f in registres["operations"] if f["type_entree"] == "mesures_comptables_constatees")
    comptable["creances"]["par_tranche"]["0-30"] = "-1000.00"
    comptable["creances"]["par_tranche"]["31-60"] = "6210.55"  # le total reste la somme : seul le signe est fautif
    assert "m8_creances_ouvertes_cad" in _bloquees(registres)


def test_des_clics_plus_nombreux_que_les_impressions_bloquent_les_deux_mesures():
    registres = copy.deepcopy(_registres())
    for fait in registres["operations"]:
        if fait["type_entree"] == "performance_signaux" and fait["source"] == "search_console":
            fait["clics"] = "999999"
    assert _bloquees(registres) == {"m8_clics_recherche", "m8_impressions_recherche"}


def test_un_taux_hors_de_zero_a_cent_bloque():
    registres = _registres()
    registres["entonnoir"] = [f for f in registres["entonnoir"]]
    lues = _lues(registres)
    assert lues["m8_taux_acceptation_pct"]["qualite"]["statut"] == "ok"
    # on force la valeur par la règle elle-même (une mesure construite à la main, hors faits)
    mesures = [{**lues["m8_taux_acceptation_pct"], "valeur": "140.00"}]
    verdict = qualite_mesures.evaluer(REGLES, mesures, registres)["m8_taux_acceptation_pct"]
    assert verdict["statut"] == "echec" and verdict["echecs"][0]["regle"] == "Q-TAUX-ENTRE-0-ET-100"
    mesures = [{**lues["m8_taux_acceptation_pct"], "valeur": "-0.01"}]
    assert qualite_mesures.evaluer(REGLES, mesures, registres)["m8_taux_acceptation_pct"]["statut"] == "echec"
    for borne in ("0", "100", "100.00", "0.00"):  # les bornes sont incluses
        mesures = [{**lues["m8_taux_acceptation_pct"], "valeur": borne}]
        assert qualite_mesures.evaluer(REGLES, mesures, registres)["m8_taux_acceptation_pct"]["statut"] == "ok"


def test_un_compte_negatif_et_une_valeur_illisible_bloquent():
    lues = _lues(_registres())
    base = lues["m8_leads_recus"]
    for valeur in ("-1", "abc", ""):
        verdict = qualite_mesures.evaluer(REGLES, [{**base, "valeur": valeur}], _registres())["m8_leads_recus"]
        assert verdict["statut"] == "echec", valeur
    assert qualite_mesures.evaluer(REGLES, [{**base, "valeur": "0"}], _registres())["m8_leads_recus"]["statut"] == "ok"


def test_un_drapeau_de_deficit_contraire_au_signe_du_cash_libre_bloque_les_quatre_mesures_du_constat():
    registres = copy.deepcopy(_registres())
    registres["cash_libre"][0]["en_deficit"] = True  # le montant est positif
    assert _bloquees(registres) == {"m8_cash_libre_cad", "m8_solde_tresorerie_cad", "m8_comptes_a_payer_cad",
                                    "m8_taxes_a_remettre_cad"}
    registres = copy.deepcopy(_registres(cash_libre_cad="-250.00"))
    assert registres["cash_libre"][0]["en_deficit"] is False
    assert "m8_cash_libre_cad" in _bloquees(registres)
    registres["cash_libre"][0]["en_deficit"] = True  # cohérent : un déficit réel n'est PAS une erreur de qualité
    assert "m8_cash_libre_cad" not in _bloquees(registres)
    assert _lues(registres)["m8_cash_libre_cad"]["valeur"] == "-250.00"


def test_un_constat_non_calculable_qui_porte_un_montant_est_incoherent():
    registres = copy.deepcopy(_registres(cash_libre_cad=None))
    assert _bloquees(registres) == set()
    registres["cash_libre"][0]["cash_libre_cad"] = "100.00"
    assert "m8_cash_libre_cad" in _bloquees(registres)


# ============================================================================== le blocage : forme et rétablissement
def test_une_mesure_bloquee_n_a_ni_valeur_ni_entree_ni_chiffre_douteux_et_dit_pourquoi():
    registres = _fait(_registres(), "facture_emise", montant_avant_taxes_cad="-777777.00", total_taxes_cad="-1.00",
                      montant_apres_taxes_cad="-777778.00")
    mesure = _lues(registres)["m8_facturation_emise_cad"]
    assert (mesure["statut"], mesure["valeur"], mesure["entrees"]) == ("non_calculable", None, {})
    assert mesure["couverture"] == {"etat": "inconnue"}
    assert [m["champ"] for m in mesure["manque"]] == ["qualite"]
    assert "QUALITY_FAIL" in mesure["detail"] and "qualité" in mesure["detail"]
    assert "777" not in str(mesure)  # la valeur douteuse n'est conservée nulle part
    assert mesure["qualite"]["statut"] == "echec"
    echecs = {e["regle"]: e for e in mesure["qualite"]["echecs"]}
    assert set(echecs) == {"Q-MONTANTS-NON-NEGATIFS", "Q-FACTURES-EMISES-COHERENTES"}
    coherence = echecs["Q-FACTURES-EMISES-COHERENTES"]
    assert coherence["references"] == ["facture:facture-fictive-1", "facture:facture-fictive-2",
                                       "facture:facture-fictive-3"] and coherence["nombre"] == 3
    assert "valeur" not in coherence


def test_la_mesure_se_retablit_d_elle_meme_quand_les_faits_sont_corriges_rien_n_est_range():
    sain = _registres()
    faute = _fait(sain, "facture_emise", montant_avant_taxes_cad="-500.00", total_taxes_cad="-74.88",
                  montant_apres_taxes_cad="-574.88")
    assert "m8_facturation_emise_cad" in _bloquees(faute)
    corrige = _lues(sain)["m8_facturation_emise_cad"]
    assert corrige["statut"] == "calculee" and corrige["valeur"] is not None and corrige["qualite"]["statut"] == "ok"
    # même entrée, même verdict (déterministe) ; le verdict est une fonction des faits
    assert _lues(faute) == _lues(copy.deepcopy(faute))


def test_une_regle_qui_echoue_ne_bloque_que_les_mesures_qu_elle_nomme():
    registres = _fait(_registres(), "facture_emise", montant_avant_taxes_cad="-500.00", total_taxes_cad="-74.88",
                      montant_apres_taxes_cad="-574.88")
    sains = _lues(_registres())
    lues = _lues(registres)
    for metric_id, mesure in lues.items():
        if metric_id not in ("m8_factures_emises", "m8_facturation_emise_cad"):
            assert mesure["valeur"] == sains[metric_id]["valeur"] and mesure["qualite"]["statut"] != "echec", metric_id


def test_la_fraicheur_distingue_une_donnee_vieille_d_une_donnee_fausse():
    faute = _fait(_registres(), "facture_emise", montant_apres_taxes_cad="1.00")
    mesures = _avec_fraicheur(faute)
    bloquee = mesures["m8_facturation_emise_cad"]
    assert bloquee["fraicheur"]["statut"] == fraicheur_mesures.STATUT_MANQUANT
    assert "contrôle de qualité" in bloquee["fraicheur"]["motif"]
    vieille = _avec_fraicheur(_registres(), MAINTENANT + dt.timedelta(days=30))["m8_facturation_emise_cad"]
    assert vieille["fraicheur"]["statut"] == fraicheur_mesures.STATUT_PERIME
    assert vieille["qualite"]["statut"] == "ok"  # vieille, pas fausse
    assert pastilles.code_pastille(vieille) == pastilles.STALE and pastilles.code_pastille(bloquee) == "QUALITY_FAIL"


# ================================================================================================== les pastilles
def test_il_y_a_six_pastilles_dont_aucune_live_et_chacune_se_derive_des_etats_existants():
    assert set(pastilles.pastilles_possibles()) == {"FRESH", "STALE", "PARTIAL", "MISSING", "QUALITY_FAIL", "GATED"}
    assert "LIVE" not in pastilles.pastilles_possibles()
    saines = _avec_fraicheur(_registres())
    assert pastilles.code_pastille(saines["m8_cash_libre_cad"]) == "FRESH"
    assert pastilles.code_pastille(saines["m8_clics_par_contenu"]) == "MISSING"
    partielle = next(m for m in saines.values() if m["statut"] == "calculee" and m["couverture"]["etat"] == "partielle")
    assert pastilles.code_pastille(partielle) == "PARTIAL" and partielle["fraicheur"]["statut"] == "a_jour"
    perimee = _avec_fraicheur(_registres(), MAINTENANT + dt.timedelta(days=30))
    assert pastilles.code_pastille(perimee["m8_cash_libre_cad"]) == "STALE"


def test_gated_est_une_mesure_non_calculable_que_retient_un_geste_humain_pas_une_donnee_manquante():
    manquante = _avec_fraicheur(_registres())["m8_clics_par_contenu"]
    for etat in ("constat_inactif", "constat_en_ombre", "constat_expire", "planificateur_coupe"):
        assert pastilles.code_pastille(manquante, etat) == "GATED", etat
    for etat in ("jamais_recue", "producteur_non_calculable", "sans_constat_planifie", "constat_en_erreur", None):
        assert pastilles.code_pastille(manquante, etat) == "MISSING", etat
    # une mesure calculée n'est jamais GATED, même si son constat est en ombre
    calculee = _avec_fraicheur(_registres())["m8_cash_libre_cad"]
    assert pastilles.code_pastille(calculee, "constat_en_ombre") == "FRESH"


def test_l_ordre_des_pastilles_la_donnee_fausse_l_emporte_sur_tout():
    mesures = _avec_fraicheur(_fait(_registres(), "facture_emise", montant_apres_taxes_cad="1.00"),
                              MAINTENANT + dt.timedelta(days=30))
    bloquee = mesures["m8_facturation_emise_cad"]
    assert bloquee["fraicheur"]["statut"] != "a_jour"
    assert pastilles.code_pastille(bloquee, "constat_inactif") == "QUALITY_FAIL"
    p = pastilles.pastille(bloquee)
    assert p["code"] == "QUALITY_FAIL" and p["libelle"] and p["explication"] and not re.search(r"\d", p["explication"])


def test_la_pastille_de_chaque_mesure_de_la_lecture_est_derivee_une_seule_fois():
    mesures = _avec_fraicheur(_registres())
    for m in mesures.values():
        assert m["pastille"] == pastilles.pastille(m)


# ================================================================================= la tuile et la bannière du wallboard
def _definition():
    return wallboards.charger(CATALOGUE)["finance-operations"]


def test_la_tuile_d_une_mesure_bloquee_porte_la_pastille_le_dit_en_toutes_lettres_et_la_banniere_aussi():
    definition = _definition()
    mesure_finance = next(t["mesure"] for t in definition["tuiles"] if t["mesure"] in
                          ("m8_facturation_emise_cad", "m8_factures_emises", "m8_creances_ouvertes_cad"))
    registres = _fait(_registres(), "facture_emise", montant_apres_taxes_cad="1.00")
    mesures = list(_avec_fraicheur(registres).values())
    cible = next(w for w in wallboards.charger(CATALOGUE).values()
                 if any(t["mesure"] in ("m8_facturation_emise_cad", "m8_factures_emises") for t in w["tuiles"]))
    etat = wallboards.evaluer(cible, mesures, maintenant=MAINTENANT.isoformat())
    bloquees = [t for t in etat["tuiles"] if t["metric_id"] in ("m8_facturation_emise_cad", "m8_factures_emises")]
    assert bloquees, mesure_finance
    for tuile in bloquees:
        assert tuile["pastille"] == "QUALITY_FAIL" and tuile["qualite_en_echec"] is True
        assert tuile["libelle_fraicheur"] == "QUALITÉ EN ÉCHEC" and tuile["valeur"] is None
        assert tuile["valeur_affichee"] == "non calculable" and tuile["a_jour"] is False
        assert tuile["etat_seuil"] in ("indetermine", "sans_seuil")
    banniere = etat["banniere"]
    assert banniere["niveau"] in ("attention", "critique") and set(banniere["qualite_en_echec"]) == {
        t["id"] for t in bloquees}
    assert any("contrôle de qualité" in m and "aucune valeur" in m for m in banniere["messages"])
    assert not any("non calculable(s)" in m and str(len(bloquees)) in m for m in banniere["messages"]
                   if "donnée manquante" in m), "une mesure bloquée n'est pas comptée comme une donnée manquante"


def test_sans_echec_aucune_tuile_ne_porte_qualite_en_echec_et_la_bannière_n_en_parle_pas():
    mesures = list(_avec_fraicheur(_registres()).values())
    for definition in wallboards.charger(CATALOGUE).values():
        etat = wallboards.evaluer(definition, mesures, maintenant=MAINTENANT.isoformat())
        assert etat["banniere"]["qualite_en_echec"] == []
        assert all(t["qualite_en_echec"] is False and t["pastille"] in pastilles.pastilles_possibles()
                   for t in etat["tuiles"])


# ======================================================================================================= le copilote
def _repondre(question, registres):
    mesures = list(_avec_fraicheur(registres).values())
    return copilote.repondre(question, mesures, CATALOGUE, maintenant=MAINTENANT.isoformat(),
                             empreinte_registres=moteur_mesures.empreinte_registres(registres))


def test_le_copilote_refuse_de_donner_une_mesure_bloquee_avec_une_explication_et_aucun_chiffre():
    faute = _fait(_registres(), "facture_emise", montant_avant_taxes_cad="-500.00", total_taxes_cad="-74.88",
                  montant_apres_taxes_cad="-574.88")
    reponse = _repondre("Quelle est la facturation émise ?", faute)
    assert reponse["statut"] == copilote.STATUT_REFUSE
    assert reponse["refus"]["code"] == copilote.REJ_QUALITE_ECHEC == "REJ-COPILOTE-QUALITE-ECHEC"
    assert "contrôle de qualité" in reponse["texte"] and "Aucune valeur" in reponse["texte"]
    assert reponse["chiffres"] == [] and "500" not in reponse["texte"] and "574" not in reponse["texte"]
    (ligne,) = reponse["mesures"]
    assert ligne["valeur"] is None and ligne["qualite_en_echec"] is True and ligne["pastille"] == "QUALITY_FAIL"
    assert copilote.verifier_recu(reponse["recu"]) and reponse["recu"]["code_refus"] == copilote.REJ_QUALITE_ECHEC


def test_le_copilote_repond_normalement_apres_la_correction_des_faits():
    sain = _repondre("Quelle est la facturation émise ?", _registres())
    assert sain["statut"] == copilote.STATUT_REPONDU and sain["chiffres"]


def test_une_question_mixte_repond_pour_les_mesures_saines_et_dit_pourquoi_pour_la_bloquee():
    faute = _fait(_registres(), "facture_emise", montant_apres_taxes_cad="1.00")
    reponse = _repondre("Quelle est la facturation émise et le cash libre ?", faute)
    assert reponse["statut"] == copilote.STATUT_REPONDU
    par_id = {ligne["metric_id"]: ligne for ligne in reponse["mesures"]}
    assert par_id["m8_facturation_emise_cad"]["valeur"] is None and par_id["m8_cash_libre_cad"]["valeur"] == "25000.00"
    assert "BLOQUÉE" in reponse["texte"] and "25 000,00" in reponse["texte"]
    assert "25000.00" in reponse["chiffres"] and len(reponse["chiffres"]) >= 1


def test_la_fraicheur_et_la_tendance_d_une_mesure_bloquee_ne_donnent_aucun_chiffre():
    faute = _fait(_registres(), "facture_emise", montant_apres_taxes_cad="1.00")
    mesures = list(_avec_fraicheur(faute).values())
    historiques = {"m8_facturation_emise_cad": [
        {"valeur": "100.00", "construit_le": "2026-11-01T00:00:00+00:00"},
        {"valeur": "200.00", "construit_le": "2026-11-05T00:00:00+00:00"}]}
    for question in ("La facturation émise est-elle à jour ?", "Quelle est la tendance de la facturation émise ?"):
        reponse = copilote.repondre(question, mesures, CATALOGUE, maintenant=MAINTENANT.isoformat(),
                                    historiques=historiques)
        assert reponse["statut"] == copilote.STATUT_REFUSE, question
        assert "100" not in reponse["texte"] and "200" not in reponse["texte"] and reponse["chiffres"] == []


# ====================================================================================== le score de santé
def _sante(mesures, bornes=None):
    definition = sante.charger(CATALOGUE)
    configuration = sante.lire_configuration({"bornes": bornes or jeux_fictifs.BORNES_SANTE_FICTIVES}, definition)
    return sante.evaluer(definition, mesures, configuration)


def test_une_mesure_du_score_bloquee_rend_sa_composante_indeterminee_pour_une_raison_de_qualite():
    sain = _sante(list(_avec_fraicheur(_registres()).values()))
    finance_saine = next(c for c in sain["composantes"] if c["id"] == "finance")
    assert finance_saine["statut"] == "determine"
    faute = copy.deepcopy(_registres())
    faute["cash_libre"][0]["en_deficit"] = True
    resultat = _sante(list(_avec_fraicheur(faute).values()))
    finance = next(c for c in resultat["composantes"] if c["id"] == "finance")
    assert finance["statut"] == "indetermine" and finance["score"] is None
    (indicateur,) = finance["indicateurs"]
    assert indicateur["raison"] == sante.RAISON_QUALITE_ECHEC and indicateur["score"] is None
    assert "contrôle de qualité en échec" in finance["explication"]
    assert resultat["statut"] == "indetermine" and resultat["score"] is None
    assert any(m["raison"] == "qualite_echec" for m in resultat["manques"])


# ========================================================================================== la collecte et la mémoire
def test_la_collecte_nomme_l_echec_de_qualite_pas_un_manque_ni_un_retard():
    faute = _fait(_registres(), "facture_emise", montant_apres_taxes_cad="1.00")
    mesures = list(_avec_fraicheur(faute).values())
    diagnostic = collecte.diagnostiquer(mesures, [], planificateur_autorise=True)
    lignes = {m["metric_id"]: m for m in diagnostic["mesures"]}
    assert lignes["m8_facturation_emise_cad"]["etat_collecte"] == "qualite_en_echec"
    assert "m8_lire_rapport_qualite" in lignes["m8_facturation_emise_cad"]["action"]
    assert lignes["m8_cash_libre_cad"]["etat_collecte"] == "a_jour"


def _consolider(registres, precedente=None):
    mesures = list(_avec_fraicheur(registres).values())
    return memoire.consolider(mesures, CATALOGUE, maintenant=MAINTENANT.isoformat(),
                              empreinte_registres=moteur_mesures.empreinte_registres(registres), precedente=precedente)


def test_la_consolidation_pour_m10_porte_l_echec_de_qualite_sous_son_propre_type_et_aucune_valeur_douteuse():
    sain = _consolider(_registres())
    precedente = memoire.resume_publication(sain)
    faute = _consolider(_fait(_registres(), "facture_emise", montant_apres_taxes_cad="1.00"), precedente)
    anomalies = {(a["metric_id"], a["type"]) for a in faute["anomalies"]}
    assert ("m8_facturation_emise_cad", memoire.ANOMALIE_ECHEC_QUALITE) in anomalies
    assert ("m8_factures_emises", "echec_qualite") in anomalies
    bloquees = ("m8_facturation_emise_cad", "m8_factures_emises")
    assert not any(t == memoire.ANOMALIE_DEVENUE_NON_CALCULABLE and m in bloquees for m, t in anomalies), (
        "la cause est connue : ce n'est pas une simple mesure devenue non calculable")
    publiee = next(m for m in faute["mesures"] if m["metric_id"] == "m8_facturation_emise_cad")
    assert publiee["valeur"] is None and publiee["statut"] == "non_calculable"
    assert not any(a["type"] == "echec_qualite" for a in sain["anomalies"])
    # l'échec dure : il est répété à chaque consolidation tant qu'il dure (jamais « une fois puis oublié »)
    encore_faux = _fait(_registres(), "facture_emise", montant_apres_taxes_cad="2.00")
    suivante = _consolider(encore_faux, memoire.resume_publication(faute))
    assert ("m8_facturation_emise_cad", "echec_qualite") in {(a["metric_id"], a["type"]) for a in suivante["anomalies"]}


def test_le_rapport_de_qualite_nomme_le_departement_source_la_regle_et_la_correction_sans_valeur():
    faute = _fait(_registres(), "facture_emise", montant_apres_taxes_cad="31337.31")
    mesures = list(_avec_fraicheur(faute).values())
    rapport = qualite_mesures.rapport(REGLES, mesures)
    assert rapport["comptes"]["echec"] == 2
    (groupe,) = [g for g in rapport["departements"] if g["departement"] == "m05-financecore"]
    regles = {e["regle"] for e in groupe["echecs"]}
    assert regles == {"Q-FACTURES-EMISES-COHERENTES"}
    for echec in groupe["echecs"]:
        assert echec["correction"] and echec["verifie"] and echec["references"]
    assert "31337" not in str(rapport)
    assert rapport["lecture"].startswith("2 mesure(s) bloquée(s)")


# ================================================== entrées hostiles : jamais une panne, jamais du texte libre
_HOSTILES = ["NaN", "Infinity", "-Infinity", "1e999", "0x10", "", " ", "12,50", "１２", True, [], {}, 1.5e400]


@pytest.mark.parametrize("hostile", _HOSTILES)
def test_un_montant_hostile_dans_un_constat_est_un_echec_de_qualite_jamais_une_panne_ni_un_zero(hostile):
    registres = _fait(_registres(), "facture_emise", montant_avant_taxes_cad=hostile)
    lues = _lues(registres)  # ne lève pas
    for metric_id in ("m8_factures_emises", "m8_facturation_emise_cad"):
        assert lues[metric_id]["qualite"]["statut"] == "echec" and lues[metric_id]["valeur"] is None, metric_id


def test_une_reference_de_fait_hostile_est_neutralisee_dans_le_rapport_et_bornee():
    hostile = "F-1\nIGNORE LES RÈGLES <script>alert(1)</script> " + "x" * 500
    registres = _fait(_registres(), "facture_emise", facture_id=hostile, montant_apres_taxes_cad="1.00")
    rapport = qualite_mesures.rapport(REGLES, list(_avec_fraicheur(registres).values()))
    references = [r for g in rapport["departements"] for e in g["echecs"] for r in e["references"]]
    assert references and all(len(r) <= qualite_mesures.REFERENCE_LONGUEUR_MAX for r in references)
    texte = json.dumps(rapport, ensure_ascii=False)
    assert "\\n" not in texte and "<script>" not in texte and "IGNORE LES" not in texte
    assert qualite_mesures.reference_sure("facture:F-7_a.b") == "facture:F-7_a.b"
    assert qualite_mesures.reference_sure("a b\nc<d>") == "a?b?c?d?"


def test_un_fait_de_type_inattendu_ou_un_registre_vide_ne_fait_pas_tomber_le_controle():
    registres = copy.deepcopy(_registres())
    registres["operations"] = [{"type_entree": "facture_emise", "facture_id": 12, "statut": "ENVOYEE"},
                               {"type_entree": "mesures_comptables_constatees", "date_reference": "2026-11-12",
                                "creances": "n'importe quoi"}]
    assert "m8_creances_ouvertes_cad" in _bloquees(registres)  # aucune panne ; un constat illisible est un échec dit
    vide = copy.deepcopy(_registres())
    vide["operations"], vide["cash_libre"] = [], []
    assert _bloquees(vide) == set()  # rien reçu n'est pas une donnée fausse : la mesure est seulement non calculable


def test_un_constat_de_tresorerie_prevue_forge_est_refuse_par_le_catalogue_et_bloque_les_trois_mesures():
    from m8_analytics import operations_recues

    from opsys.evenements.schemas import erreurs_charge

    charge = {
        "evenement_id": f"m5-tresorerie-prevue-1-2026-09-29-{'b' * 16}",
        "sequence": 1,
        "date_reference": "2026-09-29",
        "emise_le": "2026-09-29T07:00:00-04:00",
        "prevision_id": "b" * 64,
        "version_donnees": "b" * 64,
        "devise": "CAD",
        "horizon_semaines": 2,
        "statut_alerte": "ALERTE",
        "seuil_cad": "16000.00",
        "semaines_sous_seuil": [1, 1],
        "solde_minimal_prevu_cad": "99999.00",
        "semaine_solde_minimal": 26,
        "non_calculable_a_partir_de": 2,
        "manque": [{"code": "REJ-PREVISION-DELAI-FOURNISSEURS-A-DECLARER", "a_partir_de_semaine": 2}],
        "soldes_hebdo": [
            {"semaine": 1, "statut": "CALCULE", "solde_fin_cad": "19000.00"},
            {"semaine": 2, "statut": "NON_CALCULABLE", "solde_fin_cad": "18000.00"},
        ],
        "mention": (
            "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision "
            "officielle ou action réelle."
        ),
    }
    assert erreurs_charge("m5.tresorerie_prevue_constatee", charge) != []
    fait = operations_recues.fait(operations_recues.TYPE_TRESORERIE_PREVUE, charge, "2026-09-29T07:00:00-04:00")
    registres = {"chantier": [], "entonnoir": [], "contenus": [], "cash_libre": [], "operations": [fait]}
    lues = {m["metric_id"]: m for m in moteur_mesures.lire(registres, CATALOGUE)}

    # Même si un producteur fautif contournait le catalogue, la règle de qualité bloque les trois mesures C5.
    for metric_id in ("m8_solde_minimal_prevu_cad", "m8_semaines_sous_seuil",
                      "m8_ecart_tresorerie_prevue_reelle_cad"):
        assert lues[metric_id]["qualite"]["statut"] == "echec", metric_id
