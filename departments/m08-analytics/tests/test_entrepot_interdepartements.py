"""Entrepôt interdépartements de M8 : le moteur, la fraîcheur, l'entrepôt, les wallboards et le copilote lisent les 16
nouvelles mesures par le même chemin que les 18 premières (données fictives, vraie base SQLite migrée).

Prouve :
- le moteur exige les CINQ registres (jamais un registre vide deviné) et l'empreinte des registres suit le registre des
  constats : un constat de plus rend l'entrepôt « en retard » (il ne se croyait pas à jour sur un registre qu'il ne
  lisait pas) ;
- la fenêtre de fraîcheur que le département SOURCE déclare (M7) s'ajoute à celles du catalogue et de l'appelant : la
plus stricte des trois l'emporte, avec son origine ;
- l'entrepôt reconstruit porte les 38 mesures avec valeur, source, version, dernier fait ; une valeur à couverture
partielle garde sa valeur ET le dit dans `detail` ; une mesure sans source reste sans valeur ; rien de personnel ;
- le wallboard « finance et opérations » montre les valeurs exactes, marque une tuile partielle et ne dit pas « ok » ;
- le copilote répond avec la valeur, dit la couverture partielle, et reste en lecture seule (« comptes à payer » est une
  mesure, « paye » est un ordre).
"""

from __future__ import annotations

import json

import pytest
from m8_analytics import (
    catalogue_mesures,
    copilote,
    entrepot,
    entrepot_stockage,
    fraicheur_mesures,
    jeux_fictifs,
    moteur_mesures,
    wallboards,
)

from opsys import stockage

FICTIF = True
JOUR = "2026-10-30"
INSTANT = "2026-10-30T20:00:00-04:00"
CAT = catalogue_mesures.charger()
ENTREES = catalogue_mesures.par_identifiant(CAT)


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _lues(**params):
    registres = jeux_fictifs.registres_fictifs(avec_operations=True, **params)
    return {m["metric_id"]: m for m in moteur_mesures.lire(registres, CAT)}


def _avec_fraicheur(maintenant=INSTANT, max_s=None, **params):
    registres = jeux_fictifs.registres_fictifs(avec_operations=True, **params)
    lues = moteur_mesures.lire(registres, CAT)
    return {
        m["metric_id"]: m
        for m in fraicheur_mesures.lire_mesures_avec_fraicheur(
            lues, CAT, fraicheur_mesures.lire_maintenant(maintenant), {}, max_s
        )
    }


# ================================================================================================ moteur
def test_les_valeurs_de_l_entreprise_fictive_viennent_de_leurs_departements():
    m = _lues()
    attendu = {
        "m8_chantiers_marge_reelle": "4",
        "m8_marge_reelle_cumulee_cad": "12000.00",
        "m8_chantiers_en_perte": "0",
        "m8_ecart_marge_cumule_cad": "-2000.00",  # marge réelle 3000 contre prévue 3500 (12500 - 9000), 4 chantiers
        "m8_creances_ouvertes_cad": "7210.55",
        "m8_creances_90_jours_plus_cad": "0.00",
        "m8_comptes_a_payer_cad": "459.91",
        "m8_solde_tresorerie_cad": "37654.33",
        "m8_taxes_a_remettre_cad": "1981.69",
        "m8_ecritures_en_attente": "4",
        "m8_releves_depense_pub_cad": "413.75",
        "m8_conversions_hors_ligne": "2",
        "m8_anomalies_depense_critiques": "1",
        "m8_heures_sur_site_chantiers": "7.33",
        "m8_receptions_materiaux": "3",
        "m8_commandes_envoyees": "2",
        "m8_receptions_avec_ecart": "1",
        "m8_demandes_qualifiees_m1": "6",
        "m8_demandes_m1_sans_lead_m2": "0",
    }
    for metric_id, valeur in attendu.items():
        assert m[metric_id]["valeur"] == valeur, metric_id
        assert m[metric_id]["statut"] == "calculee" and m[metric_id]["couverture"] == {"etat": "complete"}, metric_id
    ecart = m["m8_ecart_depense_pub_comptabilisee_cad"]
    assert ecart["statut"] == "non_calculable" and ecart["valeur"] is None  # M5 ne publie pas la dépense comptabilisée


def test_sans_les_constats_des_autres_departements_ces_mesures_sont_inconnues_pas_nulles():
    registres = jeux_fictifs.registres_fictifs()  # operations vide, traces de rentabilité non définitives
    m = {x["metric_id"]: x for x in moteur_mesures.lire(registres, CAT)}
    for metric_id in (
        "m8_creances_ouvertes_cad",
        "m8_comptes_a_payer_cad",
        "m8_releves_depense_pub_cad",
        "m8_conversions_hors_ligne",
        "m8_receptions_materiaux",
        "m8_chantiers_marge_reelle",
        "m8_marge_reelle_cumulee_cad",
    ):
        assert m[metric_id]["statut"] == "non_calculable" and m[metric_id]["valeur"] is None, metric_id
        assert m[metric_id]["couverture"] == {"etat": "inconnue"}
    assert m["m8_heures_sur_site_chantiers"]["valeur"] == "7.33"  # M4 a livré : cette mesure se calcule


def test_le_moteur_exige_les_cinq_registres():
    registres = jeux_fictifs.registres_fictifs()
    quatre = {cle: valeur for cle, valeur in registres.items() if cle != "operations"}
    with pytest.raises(ValueError, match="REJ-MOTEUR-REGISTRES"):
        moteur_mesures.lire(quatre, CAT)
    with pytest.raises(ValueError, match="REJ-MOTEUR-REGISTRES"):
        moteur_mesures.lire({**registres, "intrus": []}, CAT)


def test_l_empreinte_des_registres_suit_le_registre_des_constats():
    sans = jeux_fictifs.registres_fictifs()
    avec = jeux_fictifs.registres_fictifs(avec_operations=True)
    assert moteur_mesures.empreinte_registres(sans) != moteur_mesures.empreinte_registres(avec)
    plus = jeux_fictifs.registres_fictifs(avec_operations=True)
    plus["operations"] = plus["operations"][:-1]
    assert moteur_mesures.empreinte_registres(plus) != moteur_mesures.empreinte_registres(avec)
    assert moteur_mesures.empreinte_registres(avec) == moteur_mesures.empreinte_registres(
        jeux_fictifs.registres_fictifs(avec_operations=True)
    )


# ================================================================================================ fraîcheur
def test_la_fenetre_de_m7_est_portee_par_la_mesure_et_la_plus_stricte_des_trois_l_emporte():
    m = _lues()["m8_releves_depense_pub_cad"]
    assert m["fenetre_source_s"] == 48 * 3600  # M7 : Google Ads 48 h, Meta 72 h -> la plus stricte
    entree = ENTREES["m8_releves_depense_pub_cad"]  # catalogue : 24 h
    assert fraicheur_mesures.fenetre_effective(entree, {}, None, 48 * 3600) == {
        "secondes": 86400,
        "origine": fraicheur_mesures.ORIGINE_CATALOGUE,
    }
    # M7 est plus stricte que le catalogue (12 h contre 24 h) : la source gagne
    assert fraicheur_mesures.fenetre_effective(entree, {}, None, 12 * 3600) == {
        "secondes": 43200,
        "origine": fraicheur_mesures.ORIGINE_SOURCE,
    }
    # l'appelant plus strict que la source l'emporte ; moins strict, jamais
    assert (
        fraicheur_mesures.fenetre_effective(entree, {}, 3600, 12 * 3600)["origine"]
        == fraicheur_mesures.ORIGINE_APPELANT
    )
    assert (
        fraicheur_mesures.fenetre_effective(entree, {}, 10**6, 12 * 3600)["origine"] == fraicheur_mesures.ORIGINE_SOURCE
    )
    # à égalité le producteur (M8) garde la main, puis la source
    assert (
        fraicheur_mesures.fenetre_effective(entree, {}, None, 86400)["origine"] == fraicheur_mesures.ORIGINE_CATALOGUE
    )
    assert fraicheur_mesures.fenetre_effective(entree, {}, 43200, 43200)["origine"] == fraicheur_mesures.ORIGINE_SOURCE


def test_une_mesure_terminale_est_resserree_par_la_source_ou_l_appelant_jamais_assouplie():
    terminale = ENTREES["m8_heures_sur_site_chantiers"]
    assert fraicheur_mesures.fenetre_effective(terminale, {}, None, None) == {
        "secondes": None,
        "origine": fraicheur_mesures.ORIGINE_TERMINALE,
    }
    assert fraicheur_mesures.fenetre_effective(terminale, {}, None, 7200)["origine"] == fraicheur_mesures.ORIGINE_SOURCE


def test_les_constats_du_jour_sont_frais_le_jour_meme_et_perimes_apres_la_fenetre():
    frais = _avec_fraicheur("2026-10-30T12:00:00-04:00")
    assert frais["m8_creances_ouvertes_cad"]["fraicheur"]["statut"] == "a_jour"
    assert frais["m8_creances_ouvertes_cad"]["dernier_fait_le"] == "2026-10-30T00:00:00+00:00"
    # le constat est daté du DÉBUT du jour (UTC), le plus ancien possible : jamais plus récent qu'il n'est
    vieux = _avec_fraicheur("2026-11-02T12:00:00-04:00")
    assert vieux["m8_creances_ouvertes_cad"]["fraicheur"]["statut"] == "perime"
    assert vieux["m8_creances_ouvertes_cad"]["fraicheur"]["peut_etre_montree_comme_a_jour"] is False
    assert vieux["m8_heures_sur_site_chantiers"]["fraicheur"]["statut"] == "non_applicable"


def test_une_mesure_a_la_fenetre_resserree_par_m7_est_perimee_avant_celle_du_catalogue():
    # relevés lus à 06:00 -04:00 le 30 : 49 h plus tard, la fenêtre de 48 h de M7 est dépassée, pas celle de M8 (24 h
    # aussi)
    resserre = _avec_fraicheur("2026-10-30T08:00:00-04:00", max_s=3600)
    assert resserre["m8_releves_depense_pub_cad"]["fraicheur"]["statut"] == "perime"
    assert resserre["m8_releves_depense_pub_cad"]["fraicheur"]["origine_fenetre"] == fraicheur_mesures.ORIGINE_APPELANT


# ================================================================================================ entrepôt
def test_l_entrepot_porte_les_trente_huit_mesures_sans_personne_ni_zero_invente():
    registres = jeux_fictifs.registres_fictifs(avec_operations=True)
    resultat = entrepot.construire(registres, CAT, construit_le=INSTANT, rang_precedent=0)
    lignes = {ligne["metric_id"]: ligne for ligne in resultat["tables"][entrepot.TABLE_MESURES]}
    assert len(lignes) == resultat["construction"]["nb_mesures"] == 38
    assert lignes["m8_creances_ouvertes_cad"]["valeur"] == "7210.55"
    assert lignes["m8_creances_ouvertes_cad"]["source"].startswith("M5 m5.mesures_comptables_constatees")
    assert lignes["m8_ecart_depense_pub_comptabilisee_cad"]["valeur"] is None
    assert "décision requise" in lignes["m8_ecart_depense_pub_comptabilisee_cad"]["detail"]
    texte = json.dumps(resultat["tables"], ensure_ascii=False)
    for interdit in ("tech-fictif", "technicien", "example.test", "fournisseur"):
        assert interdit not in texte


def test_une_valeur_partielle_garde_sa_valeur_et_le_dit_dans_l_entrepot():
    registres = jeux_fictifs.registres_fictifs(avec_operations=True)
    registres["chantier"] = [
        f
        for f in registres["chantier"]
        if not (f.get("type_entree") == "rentabilite" and f["wct_id"] in ("wct-fictif-003", "wct-fictif-004"))
    ]
    construit = entrepot.construire(registres, CAT, construit_le=INSTANT, rang_precedent=0)
    lignes = {ligne["metric_id"]: ligne for ligne in construit["tables"][entrepot.TABLE_MESURES]}
    marge = lignes["m8_marge_reelle_cumulee_cad"]
    assert marge["statut"] == "calculee" and marge["valeur"] == "6000.00"
    assert marge["detail"].startswith("couverture partielle") and "2 chantier(s) sur 4" in marge["detail"]
    assert lignes["m8_creances_ouvertes_cad"]["detail"] is None  # une valeur complète n'a rien à dire


def test_le_constat_de_plus_reconstruit_l_entrepot_qui_se_croyait_a_jour(base):
    catalogue = CAT
    sans = jeux_fictifs.registres_fictifs()
    avec = jeux_fictifs.registres_fictifs(avec_operations=True)
    with stockage.transaction() as cnx:
        assert entrepot_stockage.reconstruire(cnx, sans, catalogue, INSTANT)["statut"] == "construit"
        assert entrepot_stockage.etat(cnx, sans, catalogue)["statut"] == "a_jour"
        etat = entrepot_stockage.etat(cnx, avec, catalogue)
        assert etat["statut"] == "en_retard" and "registres" in etat["raison"]
        assert (
            entrepot_stockage.reconstruire(cnx, avec, catalogue, "2026-10-31T09:00:00-04:00")["statut"] == "construit"
        )
        lignes = {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}
        assert lignes["m8_receptions_materiaux"]["valeur"] == "3"
        historique = entrepot_stockage.lire_historique(cnx, "m8_receptions_materiaux")
        assert [h["statut"] for h in historique] == ["calculee", "non_calculable"]  # du plus récent au plus ancien


# ================================================================================================ wallboard
def _tuiles(wallboard_id, **params):
    definition = wallboards.charger(CAT)[wallboard_id]
    etat = wallboards.evaluer(definition, list(_avec_fraicheur(**params).values()), maintenant=INSTANT)
    return etat, {t["id"]: t for t in etat["tuiles"]}


def test_le_wallboard_finance_operations_montre_les_valeurs_exactes_et_la_provenance():
    etat, t = _tuiles("finance-operations")
    assert t["creances"]["valeur"] == "7210.55" and t["creances"]["valeur_affichee"].endswith("$")
    assert t["a-payer"]["valeur"] == "459.91" and t["heures"]["valeur"] == "7.33"
    assert t["receptions-ecart"]["valeur"] == "1" and t["ecart-marge"]["valeur"] == "-2000.00"
    assert t["creances"]["source"].startswith("M5 ") and t["creances"]["proprietaire"] == "m05-financecore"
    assert etat["donnees_personnelles"] is False
    assert all(len(tuile["version_definition"]) == 64 for tuile in etat["tuiles"])


def _etat_wallboard(wallboard_id, registres, maintenant="2026-10-30T12:00:00-04:00"):
    lues = moteur_mesures.lire(registres, CAT)
    mesures = fraicheur_mesures.lire_mesures_avec_fraicheur(
        lues, CAT, fraicheur_mesures.lire_maintenant(maintenant), {}
    )
    return wallboards.evaluer(wallboards.charger(CAT)[wallboard_id], mesures, maintenant=maintenant)


def test_une_tuile_partielle_le_dit_et_la_banniere_ne_dit_pas_ok():
    complet = _etat_wallboard("finance-operations", jeux_fictifs.registres_fictifs(avec_operations=True))
    assert complet["banniere"]["partielles"] == []
    partiel = jeux_fictifs.registres_fictifs(avec_operations=True)
    partiel["chantier"] = [
        f
        for f in partiel["chantier"]
        if not (f.get("type_entree") == "rentabilite" and f["wct_id"] != "wct-fictif-001")
    ]
    etat = _etat_wallboard("finance-operations", partiel)
    tuile = next(t for t in etat["tuiles"] if t["id"] == "marge-cumulee")
    assert tuile["partielle"] is True and tuile["valeur"] == "3000.00" and "1 chantier(s) sur 4" in tuile["detail"]
    assert "marge-cumulee" in etat["banniere"]["partielles"] and etat["banniere"]["niveau"] != "ok"
    assert any("couverture partielle" in message for message in etat["banniere"]["messages"])


def test_la_tuile_de_l_ecart_de_depense_dit_non_calculable_et_jamais_un_zero():
    etat, t = _tuiles("marketing")
    tuile = t["ecart-depense"]
    assert tuile["valeur"] is None and tuile["statut_mesure"] == "non_calculable" and tuile["a_jour"] is False
    assert "décision requise" in tuile["detail"]
    assert "ecart-depense" in etat["banniere"]["non_calculables"]


# ================================================================================================ copilote
def _repondre(question, **params):
    mesures = list(_avec_fraicheur(**params).values())
    return copilote.repondre(question, mesures, CAT, maintenant=INSTANT, empreinte_registres="r" * 64)


def test_le_copilote_repond_avec_la_valeur_exacte_et_la_source_du_departement():
    reponse = _repondre("Quelles sont nos créances ouvertes ?")
    assert reponse["statut"] == "repondu" and "7 210,55 $" in reponse["texte"]
    assert reponse["mesures"][0]["valeur"] == "7210.55" and reponse["mention"] == copilote.MENTION_PROFESSIONNEL
    assert reponse["sources"] == [
        "M5 m5.mesures_comptables_constatees (creances.total, creances.par_tranche, date_reference)"
    ]
    assert reponse["recu"]["mesures"][0]["couverture"] == "complete"


def test_le_copilote_dit_la_couverture_partielle_meme_quand_la_mesure_est_a_jour():
    registres = jeux_fictifs.registres_fictifs(avec_operations=True)
    registres["chantier"] = [
        f
        for f in registres["chantier"]
        if not (f.get("type_entree") == "rentabilite" and f["wct_id"] != "wct-fictif-001")
    ]
    lues = moteur_mesures.lire(registres, CAT)
    mesures = fraicheur_mesures.lire_mesures_avec_fraicheur(lues, CAT, fraicheur_mesures.lire_maintenant(INSTANT), {})
    reponse = copilote.repondre("Quelle est la marge réelle cumulée ?", mesures, CAT, maintenant=INSTANT)
    assert reponse["statut"] == "repondu" and "Couverture PARTIELLE" in reponse["texte"]
    assert "1 chantier(s) sur 4" in reponse["texte"] and {"1", "4", "3"} <= set(reponse["chiffres"])
    assert reponse["recu"]["mesures"][0]["couverture"] == "partielle"


def test_comptes_a_payer_est_une_mesure_paye_est_un_ordre():
    assert _repondre("Combien de comptes à payer ?")["mesures"][0]["valeur"] == "459.91"
    for ordre in ("Paye les comptes à payer", "Paye la facture du fournisseur"):
        refus = _repondre(ordre)
        assert refus["statut"] == "refuse" and refus["refus"]["code"] == copilote.REJ_ACTION


def test_l_ecart_de_depense_est_nomme_et_dit_non_calculable_par_le_copilote():
    reponse = _repondre("Quel est l'écart de dépense publicitaire ?")
    assert reponse["statut"] == "repondu" and reponse["mesures"][0]["valeur"] is None
    assert "non calculable" in reponse["texte"] and reponse["mesures"][0]["manque"] == [
        "charges_marketing_comptabilisees"
    ]


def test_les_dix_huit_premieres_mesures_disent_aussi_leur_couverture():
    """Complète quand calculée, inconnue quand non calculable : la même forme pour les 38 mesures."""
    lues = {
        m["metric_id"]: m
        for m in moteur_mesures.lire(jeux_fictifs.registres_fictifs(cash_libre_cad=None, avec_operations=True), CAT)
    }
    assert lues["m8_leads_recus"]["couverture"] == {"etat": "complete"}
    assert lues["m8_cash_libre_cad"]["statut"] == "non_calculable"
    assert lues["m8_cash_libre_cad"]["couverture"] == {"etat": "inconnue"}
    assert lues["m8_impressions_par_contenu"]["couverture"] == {"etat": "inconnue"}
    assert all(m["couverture"]["etat"] in ("complete", "partielle", "inconnue") for m in lues.values())
