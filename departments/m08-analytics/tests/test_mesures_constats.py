"""Mesures de la phase 2 de l'entrepôt (D1 à D3, D5, D6) : module pur `mesures_constats`, sur des RÉSUMÉS FICTIFS
conformes au
catalogue d'événements du socle.

Ce que ce fichier prouve, sans base de données :
- chaque résumé publié par M5, M7, M4, M2, M6 et M1 devient une mesure reprise telle quelle (ou sommée / rapportée avec
ses
  entrées dites) ; la version qui fait foi est la dernière PUBLIÉE (`publie_le`), quel que soit l'ordre de livraison ;
  la dépense
  comptabilisée suit le plus grand `sequence` et une facture son état le plus avancé ;
- une absence n'est jamais un zéro : capacité sans profil, taux sous le seuil de M2, plaintes « aucune déclarée par la
source »,
  aucun article suivi, aucune correspondance canaux -> sources UTM donnent une mesure NON CALCULABLE qui cite sa cause ;
- l'écart entre les relevés de M7 et la dépense comptabilisée de M5 (D1) est une mesure nommée, avec ce qu'elle écarte ;
- le coût par lead publicitaire (D6) n'existe que si le propriétaire a déclaré la correspondance, et refuse de diviser
par zéro ;
- aucune personne, aucun client, aucun article ni fournisseur dans aucune mesure ; aucun flottant dans le code.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from m8_analytics import entonnoir, jeux_fictifs, mesures_constats
from m8_analytics import mesures_interdepartements as mi
from m8_analytics import operations_recues as op

from opsys.evenements.schemas import erreurs_charge

FICTIF = True
_SRC = Path(__file__).resolve().parents[1] / "src" / "m8_analytics" / "mesures_constats.py"
JOUR = "2026-10-30"
LUNDI = "2026-10-26"


def _valide(type_evenement, charge):
    assert erreurs_charge(type_evenement, charge) == [], "la donnée de test doit être conforme au catalogue"
    return charge


def _fait(type_entree, evenement, charge, heure=7):
    return op.fait(type_entree, _valide(evenement, charge), f"{JOUR}T{heure:02d}:00:00-04:00")


def _depense(
    sequence=1, comptabilise="300.00", en_attente=2, en_attente_cad="113.75", debut="2026-10-28", fin=JOUR, heure=7
):
    return _fait(
        op.TYPE_DEPENSE_COMPTABILISEE,
        "m5.depense_publicitaire_constatee",
        {
            "evenement_id": f"m5-depense-pub-{sequence}-{debut}-{fin}-{comptabilise}",
            "sequence": sequence,
            "date_reference": JOUR,
            "periode_debut": debut,
            "periode_fin": fin,
            "version_donnees": f"{sequence:016x}",
            "devise": "CAD",
            "base_taxes": "HORS_TAXES",
            "comptabilise_cad": comptabilise,
            "ecritures_definitives": 3,
            "brouillons_en_attente": en_attente,
            "brouillons_en_attente_cad": en_attente_cad,
        },
        heure,
    )


def _releve(identifiant, canal, debut, fin, montant, revision=1, base="HORS_TAXES"):
    return op.fait(
        op.TYPE_DEPENSE,
        _valide(
            "m7.depenses_marketing_constatees",
            {
                "releve_id": identifiant,
                "revision": revision,
                "canal": canal,
                "periode_debut": debut,
                "periode_fin": fin,
                "montant_cad": montant,
                "devise": "CAD",
                "base_taxes": base,
                "source": "RELEVE_PLATEFORME",
                "releve_le": f"{JOUR}T06:00:00-04:00",
            },
        ),
    )


def _facture(identifiant, statut, avant="1000.00", taxes="149.75", apres="1149.75", heure=9, jour="2026-10-29"):
    return _fait(
        op.TYPE_FACTURE_EMISE,
        "m5.facture_emise_constatee",
        {
            "evenement_id": f"m5-facture-emise-{identifiant}-{statut}",
            "facture_id": identifiant,
            "statut": statut,
            "emise_le": jour,
            "devise": "CAD",
            "montant_avant_taxes_cad": avant,
            "total_taxes_cad": taxes,
            "montant_apres_taxes_cad": apres,
        },
        heure,
    )


def _perf(
    source,
    debut,
    fin,
    jours,
    couverts,
    clics=None,
    impressions=None,
    visites=None,
    version="a" * 16,
    heure=8,
    fictif=False,
    compte="site-fictif",
    fenetre_h=48,
):
    return _fait(
        op.TYPE_PERFORMANCE,
        "m7.performance_signaux_constatee",
        {
            "evenement_id": f"m7-perf-{source}-{compte}-{debut}-{fin}-{version}",
            "source": source,
            "compte_ref": compte,
            "periode_debut": debut,
            "periode_fin": fin,
            "jours_periode": jours,
            "jours_couverts": couverts,
            "clics": clics,
            "impressions": impressions,
            "visites": visites,
            "derniere_observation_le": f"{JOUR}T06:00:00-04:00",
            "fraicheur_fenetre_h": fenetre_h,
            "fictif": fictif,
            "version_donnees": version,
        },
        heure,
    )


def _capacite(
    semaine=LUNDI,
    dispo="80",
    planif="62",
    calculable=True,
    manque=(),
    portee="journees_datees_seulement",
    version="b" * 16,
    heure=7,
    constate=f"{JOUR}T07:00:00-04:00",
):
    return _fait(
        op.TYPE_CAPACITE,
        "m4.capacite_equipe_constatee",
        {
            "evenement_id": f"m4-capacite-{semaine}-{portee}-{version}-{heure}",
            "semaine_debut": semaine,
            "portee": portee,
            "calculable": calculable,
            "heures_disponibles": dispo if calculable else None,
            "heures_planifiees": planif if calculable else None,
            "manque": list(manque),
            "constate_le": constate,
            "version_donnees": version,
        },
        heure,
    )


def _pipeline(date=JOUR, ouverts=12, taux="37.50", valeur="41250.00", version="c" * 16, heure=7, resolus=24):
    return _fait(
        op.TYPE_PIPELINE,
        "m2.pipeline_constate",
        {
            "evenement_id": f"m2-pipeline-{date}-{version}-{heure}",
            "date_reference": date,
            "constate_le": f"{date}T07:00:00-04:00",
            "version_donnees": version,
            "total": 40,
            "ouverts": ouverts,
            "par_statut": {"nouveau": 4, "qualifie": 8, "converti": 9, "perdu": 15},
            "convertis_un_jour": 9,
            "perdus": 15,
            "resolus": resolus,
            "taux_conversion_resolus_pct": taux,
            "valeur_ponderee_cad": valeur,
        },
        heure,
    )


def _dispo(date=JOUR, suivis=42, rupture=3, sur=1, actives=5, incompletes=2, version="d" * 16, heure=7):
    return _fait(
        op.TYPE_DISPONIBILITE,
        "m6.disponibilite_constatee",
        {
            "evenement_id": f"m6-disponibilite-{date}-{version}-{heure}",
            "date_reference": date,
            "constate_le": f"{date}T07:00:00-04:00",
            "version_donnees": version,
            "articles_suivis": suivis,
            "articles_en_rupture": rupture,
            "articles_sur_reserves": sur,
            "reservations_actives": actives,
            "reservations_incompletes": incompletes,
        },
        heure,
    )


def _plaintes(etat="CONNUE", nombre=2, date=JOUR, jours=30, empreinte="ab" * 32, heure=7):
    return _fait(
        op.TYPE_PLAINTES,
        "m1.plaintes_constatees",
        {
            "evenement_id": f"m1-plaintes-{date}-{jours}-{empreinte[:16]}",
            "date_reference": date,
            "jours": jours,
            "etat": etat,
            "nombre": nombre if etat == "CONNUE" else None,
            "empreinte_contenu": empreinte,
        },
        heure,
    )


def _lead(rang, source=None, jour=JOUR):
    charge = {
        "lead_id": f"lead-fictif-{rang:03d}",
        "client_id": "a" * 64,
        "horodatage_association": f"{jour}T08:{rang:02d}:00-04:00",
    }
    if source is not None:
        charge["utm"] = {"utm_source": source}
    return entonnoir.fait_lead_recu(charge)


def _canaux(**canaux):
    return [{"type_entree": "canaux_marketing", "canaux": {c: list(s) for c, s in canaux.items()}}]


def _registres(operations=(), entonnoir_=(), declarations=()):
    return {
        "chantier": [],
        "entonnoir": list(entonnoir_),
        "contenus": [],
        "cash_libre": [],
        "operations": list(operations),
        "declarations": list(declarations),
    }


@pytest.fixture(scope="module")
def definitions():
    return mi.charger_definitions()


def _m(registres, definitions, metric_id):
    return {m["metric_id"]: m for m in mi.mesurer(registres, definitions)}[metric_id]


def _op(definitions, metric_id, *faits, **autres):
    return _m(_registres(faits, **autres), definitions, metric_id)


def _non_calculable(m, champ=None):
    assert m["statut"] == "non_calculable" and m["valeur"] is None and m["couverture"] == {"etat": "inconnue"}, m
    if champ is not None:
        assert champ in {x["champ"] for x in m["manque"]}, m["manque"]


# ================================================================================================ D1 : comptabilisé
def test_la_depense_comptabilisee_est_reprise_telle_quelle_avec_ses_brouillons_dits(definitions):
    m = _op(definitions, "m8_depense_pub_comptabilisee_cad", _depense())
    assert m["statut"] == "calculee" and m["valeur"] == "300.00"
    assert m["entrees"]["sequence"] == 1 and m["entrees"]["periode_debut"] == "2026-10-28"
    assert m["entrees"]["brouillons_en_attente"] == 2 and m["entrees"]["brouillons_en_attente_cad"] == "113.75"
    assert m["couverture"]["etat"] == "partielle" and m["couverture"]["manquants"] == 2
    assert "brouillon" in m["detail"] and m["dernier_fait_le"] == f"{JOUR}T00:00:00+00:00"


def test_sans_brouillon_en_attente_la_couverture_est_complete(definitions):
    m = _op(definitions, "m8_depense_pub_comptabilisee_cad", _depense(en_attente=0, en_attente_cad="0.00"))
    assert m["valeur"] == "300.00" and m["couverture"] == {"etat": "complete"}


def test_le_plus_grand_sequence_l_emporte_quel_que_soit_l_ordre_de_livraison_et_le_retour_en_arriere_aussi(definitions):
    un, deux, trois = _depense(1, "100.00"), _depense(2, "200.00"), _depense(3, "100.00")
    for ordre in ((un, deux, trois), (trois, deux, un), (deux, trois, un)):
        assert (
            _op(definitions, "m8_depense_pub_comptabilisee_cad", *ordre)["valeur"] == "100.00"
        )  # le rang 3 : retour au 1
    assert _op(definitions, "m8_depense_pub_comptabilisee_cad", trois, deux, un)["entrees"]["sequence"] == 3


def test_aucun_constat_de_m5_la_depense_comptabilisee_est_non_calculable_pas_zero(definitions):
    m = _op(definitions, "m8_depense_pub_comptabilisee_cad")
    _non_calculable(m, "m5.depense_publicitaire_constatee")
    assert "M5" in m["manque"][0]["source"]


def test_un_constat_au_montant_illisible_est_non_calculable(definitions):
    illisible = {**_depense(), "comptabilise_cad": "pas-un-nombre"}
    _non_calculable(_op(definitions, "m8_depense_pub_comptabilisee_cad", illisible), "comptabilise_cad")


# ================================================================================================ D1 : écart
def _releves_fictifs():
    return [
        _releve("r-g1", "google_ads", "2026-10-28", "2026-10-28", "120.00"),
        _releve("r-g2", "google_ads", "2026-10-29", "2026-10-29", "135.50"),
        _releve("r-g3", "google_ads", JOUR, JOUR, "98.25"),
        _releve("r-m1", "meta", "2026-10-29", "2026-10-29", "60.00"),
    ]


def test_l_ecart_est_la_somme_des_releves_moins_le_comptabilise_et_dit_les_brouillons(definitions):
    m = _op(definitions, "m8_ecart_depense_pub_comptabilisee_cad", _depense(), *_releves_fictifs())
    assert m["statut"] == "calculee" and m["valeur"] == "113.75"
    assert m["entrees"]["somme_releves_cad"] == "413.75" and m["entrees"]["comptabilise_cad"] == "300.00"
    assert m["entrees"]["n_releves_compares"] == 4 and m["entrees"]["brouillons_en_attente_cad"] == "113.75"
    assert m["couverture"]["etat"] == "partielle" and "2 brouillon(s)" in m["couverture"]["raison"]
    assert m["couverture"]["couverts"] == 3 and m["couverture"]["attendus"] == 5


def test_un_ecart_negatif_est_dit_tel_quel_quand_le_comptabilise_depasse_les_releves(definitions):
    m = _op(
        definitions,
        "m8_ecart_depense_pub_comptabilisee_cad",
        _depense(comptabilise="500.00", en_attente=0, en_attente_cad="0.00"),
        *_releves_fictifs(),
    )
    assert m["valeur"] == "-86.25" and m["couverture"] == {"etat": "complete"}


def test_une_revision_remplace_la_precedente_et_ne_s_y_additionne_pas(definitions):
    revisee = _releve("r-g3", "google_ads", JOUR, JOUR, "150.00", revision=2)
    m = _op(definitions, "m8_ecart_depense_pub_comptabilisee_cad", _depense(), *_releves_fictifs(), revisee)
    assert m["entrees"]["somme_releves_cad"] == "465.50" and m["valeur"] == "165.50"


def test_les_releves_a_cheval_ou_taxes_incluses_sont_ecartes_et_dits(definitions):
    a_cheval = _releve("r-cheval", "google_ads", "2026-10-27", "2026-10-28", "50.00")
    taxes = _releve("r-ttc", "meta", "2026-10-29", "2026-10-29", "999.00", base="TAXES_INCLUSES")
    hors = _releve("r-hors", "meta", "2026-09-01", "2026-09-01", "70.00")
    m = _op(
        definitions,
        "m8_ecart_depense_pub_comptabilisee_cad",
        _depense(en_attente=0, en_attente_cad="0.00"),
        _releve("r-ok", "google_ads", JOUR, JOUR, "100.00"),
        a_cheval,
        taxes,
        hors,
    )
    assert m["valeur"] == "-200.00" and m["entrees"]["somme_releves_cad"] == "100.00"
    assert (m["entrees"]["n_releves_a_cheval"], m["entrees"]["n_releves_taxes_incluses"]) == (1, 1)
    assert m["entrees"]["n_releves_hors_periode"] == 1
    assert m["couverture"]["etat"] == "partielle" and "2 relevé(s) ne sont pas comparés" in m["couverture"]["raison"]


def test_aucun_releve_comparable_l_ecart_est_non_calculable_et_nomme_pourquoi(definitions):
    hors = _releve("r-hors", "meta", "2026-09-01", "2026-09-01", "70.00")
    m = _op(definitions, "m8_ecart_depense_pub_comptabilisee_cad", _depense(), hors)
    _non_calculable(m, "m7.depenses_marketing_constatees")
    assert "1 hors de la période" in m["manque"][0]["raison"]


def test_sans_releve_ou_sans_constat_l_ecart_est_non_calculable(definitions):
    _non_calculable(
        _op(definitions, "m8_ecart_depense_pub_comptabilisee_cad", _depense()), "m7.depenses_marketing_constatees"
    )
    _non_calculable(
        _op(definitions, "m8_ecart_depense_pub_comptabilisee_cad", *_releves_fictifs()),
        "m5.depense_publicitaire_constatee",
    )


def test_un_releve_a_periode_inversee_refuse_l_ecart_au_lieu_de_le_corriger(definitions):
    inverse = {
        **_releve("r-inv", "google_ads", JOUR, JOUR, "10.00"),
        "periode_debut": JOUR,
        "periode_fin": "2026-10-01",
    }
    _non_calculable(
        _op(definitions, "m8_ecart_depense_pub_comptabilisee_cad", _depense(), *_releves_fictifs(), inverse), "periode"
    )


def test_la_fenetre_de_m7_s_applique_a_l_ecart_et_l_instant_est_le_plus_ancien_des_deux_sources(definitions):
    signal = op.fait(
        op.TYPE_SIGNAUX,
        _valide(
            "m7.signaux_marketing_constates",
            {
                "source": "google_ads",
                "compte_ref": "compte-fictif-1",
                "flux": "depenses",
                "mode": "api_lecture",
                "periode_debut": "2026-10-28",
                "periode_fin": JOUR,
                "faits_nouveaux": 1,
                "faits_revises": 0,
                "faits_inchanges": 0,
                "derniere_lecture_reussie_le": f"{JOUR}T06:00:00-04:00",
                "donnees_jusqu_au": JOUR,
                "fraicheur_fenetre_h": 12,
                "fictif": False,
            },
        ),
    )
    m = _op(definitions, "m8_ecart_depense_pub_comptabilisee_cad", _depense(), *_releves_fictifs(), signal)
    assert m["fenetre_source_s"] == 12 * 3600
    assert (
        m["dernier_fait_le"] == f"{JOUR}T00:00:00+00:00"
    )  # le jour de M5 (début de jour) est plus ancien que le relevé de M7


# ================================================================================================ D3 : factures
def test_une_facture_payee_ne_redevient_pas_envoyee_quel_que_soit_l_ordre_de_livraison(definitions):
    envoyee, payee = _facture("f-1", "ENVOYEE", heure=9), _facture("f-1", "PAYEE", heure=11)
    for ordre in ((envoyee, payee), (payee, envoyee)):
        m = _op(definitions, "m8_factures_emises", *ordre)
        assert m["valeur"] == "1" and m["entrees"]["par_statut"] == {"PAYEE": 1}  # l'état courant, pas l'historique
    # même si « envoyée » a été PUBLIÉE après « payée » (le bus ne garantit pas l'ordre des enveloppes), l'état avancé
    # gagne
    tardive = _facture("f-1", "ENVOYEE", heure=15)
    assert _op(definitions, "m8_factures_emises", tardive, payee)["entrees"]["par_statut"] == {"PAYEE": 1}
    annulee = _facture("f-2", "ANNULEE", heure=10)
    tardive_2 = _facture("f-2", "ENVOYEE", heure=16)
    assert _op(definitions, "m8_factures_emises", tardive_2, annulee)["valeur"] == "0"


def test_une_facture_annulee_apres_envoi_n_est_pas_comptee_ni_facturee(definitions):
    faits = [
        _facture("f-1", "ENVOYEE"),
        _facture("f-1", "PAYEE", avant="1000.00"),
        _facture("f-2", "ENVOYEE", avant="500.00"),
        _facture("f-3", "ENVOYEE", avant="800.00"),
        _facture("f-3", "ANNULEE", avant="800.00"),
    ]
    nombre = _op(definitions, "m8_factures_emises", *faits)
    assert nombre["valeur"] == "2" and nombre["entrees"]["n_annulees_apres_envoi"] == 1
    somme = _op(definitions, "m8_facturation_emise_cad", *faits)
    assert somme["valeur"] == "1500.00" and somme["entrees"]["montant_apres_taxes_cad"] == "2299.50"
    assert somme["entrees"]["total_taxes_cad"] == "299.50" and somme["entrees"]["n_factures"] == 2


def test_rejouer_une_facture_ou_la_livrer_sous_un_autre_evenement_ne_double_rien(definitions):
    f = _facture("f-1", "ENVOYEE")
    assert _op(definitions, "m8_factures_emises", f, dict(f))["valeur"] == "1"
    assert _op(definitions, "m8_facturation_emise_cad", f, dict(f))["valeur"] == "1000.00"


def test_aucune_facture_ou_toutes_annulees_les_mesures_sont_non_calculables(definitions):
    _non_calculable(_op(definitions, "m8_factures_emises"), "m5.facture_emise_constatee")
    _non_calculable(_op(definitions, "m8_facturation_emise_cad"), "m5.facture_emise_constatee")
    toutes = [_facture("f-1", "ENVOYEE"), _facture("f-1", "ANNULEE")]
    assert (
        _op(definitions, "m8_factures_emises", *toutes)["valeur"] == "0"
    )  # une facture annulée : 0 facture émise active
    _non_calculable(_op(definitions, "m8_facturation_emise_cad", *toutes), "factures_emises")


def test_un_montant_illisible_rend_la_facturation_non_calculable(definitions):
    illisible = {**_facture("f-1", "ENVOYEE"), "montant_avant_taxes_cad": "beaucoup"}
    _non_calculable(_op(definitions, "m8_facturation_emise_cad", illisible), "montant_avant_taxes_cad")


# ================================================================================================ M7 : performance
def test_les_clics_et_impressions_se_somment_entre_sources_de_recherche_et_disent_les_jours(definitions):
    google = _perf("search_console", "2026-10-24", JOUR, 7, 7, clics="120", impressions="4300")
    bing = _perf("bing_webmaster", "2026-10-24", JOUR, 7, 5, clics="15", impressions="600", fenetre_h=24)
    clics = _op(definitions, "m8_clics_recherche", google, bing)
    assert clics["valeur"] == "135" and clics["couverture"]["etat"] == "partielle"
    assert (clics["couverture"]["couverts"], clics["couverture"]["attendus"], clics["couverture"]["manquants"]) == (
        12,
        14,
        2,
    )
    assert clics["fenetre_source_s"] == 24 * 3600
    assert clics["entrees"]["par_source"]["bing_webmaster"] == {"resumes": 1, "jours_couverts": 5, "jours_periode": 7}
    assert _op(definitions, "m8_impressions_recherche", google, bing)["valeur"] == "4900"


def test_la_derniere_version_publiee_d_une_periode_remplace_la_precedente(definitions):
    v1 = _perf("search_console", "2026-10-24", JOUR, 7, 6, clics="100", version="1" * 16, heure=8)
    v2 = _perf("search_console", "2026-10-24", JOUR, 7, 7, clics="130", version="2" * 16, heure=9)
    for ordre in ((v1, v2), (v2, v1)):
        assert _op(definitions, "m8_clics_recherche", *ordre)["valeur"] == "130"


def test_deux_periodes_qui_se_chevauchent_pour_une_meme_source_refusent_la_somme(definitions):
    a = _perf("search_console", "2026-10-01", "2026-10-15", 15, 15, clics="10")
    b = _perf("search_console", "2026-10-10", JOUR, 21, 21, clics="20", version="b" * 16)
    _non_calculable(_op(definitions, "m8_clics_recherche", a, b), "periode")
    contigu = _perf("search_console", "2026-10-16", JOUR, 15, 15, clics="20", version="c" * 16)
    assert _op(definitions, "m8_clics_recherche", a, contigu)["valeur"] == "30"
    # un seul jour en commun (le 15) compte déjà deux fois : la borne est incluse
    un_jour = _perf("search_console", "2026-10-15", JOUR, 16, 16, clics="20", version="d" * 16)
    _non_calculable(_op(definitions, "m8_clics_recherche", a, un_jour), "periode")


def test_deux_outils_d_audience_ne_s_additionnent_pas_un_seul_oui(definitions):
    umami = _perf("umami", "2026-10-24", JOUR, 7, 6, visites="410")
    matomo = _perf("matomo", "2026-10-24", JOUR, 7, 7, visites="395")
    _non_calculable(_op(definitions, "m8_visites_site", umami, matomo), "visites")
    m = _op(definitions, "m8_visites_site", umami)
    assert m["valeur"] == "410" and m["couverture"]["etat"] == "partielle" and m["couverture"]["manquants"] == 1


def test_un_compte_de_demonstration_n_entre_dans_aucune_somme(definitions):
    reel = _perf("search_console", "2026-10-24", JOUR, 7, 7, clics="120")
    demo = _perf(
        "search_console", "2026-10-24", JOUR, 7, 7, clics="99999", compte="demo-fictif", fictif=True, version="d" * 16
    )
    assert _op(definitions, "m8_clics_recherche", reel, demo)["valeur"] == "120"
    _non_calculable(_op(definitions, "m8_clics_recherche", demo), "m7.performance_signaux_constatee")


def test_une_mesure_que_la_source_ne_porte_pas_est_non_calculable_pas_zero(definitions):
    sans_clics = _perf("search_console", "2026-10-24", JOUR, 7, 7, impressions="4300")
    _non_calculable(_op(definitions, "m8_clics_recherche", sans_clics), "clics")
    assert _op(definitions, "m8_impressions_recherche", sans_clics)["valeur"] == "4300"
    _non_calculable(_op(definitions, "m8_visites_site", sans_clics), "m7.performance_signaux_constatee")


# ================================================================================================ M4 : capacité
def test_la_capacite_de_la_semaine_la_plus_recente_est_reprise_et_le_rapport_calcule(definitions):
    ancienne = _capacite(semaine="2026-10-19", dispo="40", planif="10", version="1" * 16)
    recente = _capacite()
    for ordre in ((ancienne, recente), (recente, ancienne)):
        assert _op(definitions, "m8_capacite_heures_disponibles", *ordre)["valeur"] == "80.00"
    assert _op(definitions, "m8_capacite_heures_planifiees", recente)["valeur"] == "62.00"
    pct = _op(definitions, "m8_charge_planifiee_pct", recente)
    assert pct["valeur"] == "77.50" and pct["entrees"]["heures_disponibles"] == "80.00"
    assert pct["dernier_fait_le"] == f"{JOUR}T07:00:00-04:00"


def test_la_semaine_type_n_est_pas_la_capacite_de_la_semaine(definitions):
    type_ = _capacite(portee="semaine_type", dispo="999")
    _non_calculable(_op(definitions, "m8_capacite_heures_disponibles", type_), "m4.capacite_equipe_constatee")


def test_une_capacite_non_calculable_cite_les_causes_de_m4_jamais_zero(definitions):
    sans_profil = _capacite(calculable=False, manque=["profil_equipes_non_declare"], version="e" * 16)
    for metric_id in ("m8_capacite_heures_disponibles", "m8_capacite_heures_planifiees", "m8_charge_planifiee_pct"):
        m = _op(definitions, metric_id, sans_profil)
        _non_calculable(m, "profil_equipes_non_declare")
        assert "pas zéro" in m["manque"][0]["raison"]


def test_un_changement_de_profil_dans_la_meme_semaine_le_dernier_publie_l_emporte(definitions):
    avant = _capacite(dispo="80", version="1" * 16, heure=7)
    apres = _capacite(dispo="40", planif="30", version="2" * 16, heure=9)
    retour = _capacite(dispo="80", version="1" * 16, heure=11, constate=f"{JOUR}T11:00:00-04:00")
    for ordre in ((avant, apres, retour), (retour, apres, avant), (apres, retour, avant)):
        assert _op(definitions, "m8_capacite_heures_disponibles", *ordre)["valeur"] == "80.00"


def test_aucune_heure_disponible_declaree_un_pourcentage_n_a_pas_de_sens(definitions):
    zero = _capacite(dispo="0", planif="5", version="f" * 16)
    _non_calculable(_op(definitions, "m8_charge_planifiee_pct", zero), "heures_disponibles")
    assert (
        _op(definitions, "m8_capacite_heures_disponibles", zero)["valeur"] == "0.00"
    )  # déclaré 0 : une valeur, pas une absence


def test_un_pourcentage_au_dessus_de_cent_est_dit_tel_quel(definitions):
    surcharge = _capacite(dispo="40", planif="50", version="9" * 16)
    assert _op(definitions, "m8_charge_planifiee_pct", surcharge)["valeur"] == "125.00"


# ================================================================================================ M2 : pipeline
def test_le_pipeline_du_jour_le_plus_recent_est_repris_quel_que_soit_l_ordre(definitions):
    hier = _pipeline(date="2026-10-29", ouverts=99, taux="10.00", valeur="1.00", version="1" * 16)
    aujourd_hui = _pipeline()
    for ordre in ((hier, aujourd_hui), (aujourd_hui, hier)):
        assert _op(definitions, "m8_pipeline_leads_ouverts", *ordre)["valeur"] == "12"
    assert _op(definitions, "m8_taux_conversion_resolus_pct", aujourd_hui)["valeur"] == "37.50"
    m = _op(definitions, "m8_valeur_ponderee_pipeline_cad", aujourd_hui)
    assert m["valeur"] == "41250.00" and m["dernier_fait_le"] == f"{JOUR}T07:00:00-04:00"


def test_un_taux_ou_une_valeur_que_m2_refuse_d_etablir_est_non_calculable_pas_zero(definitions):
    refus = _pipeline(taux=None, valeur=None, resolus=7)
    assert _op(definitions, "m8_pipeline_leads_ouverts", refus)["valeur"] == "12"
    taux = _op(definitions, "m8_taux_conversion_resolus_pct", refus)
    _non_calculable(taux, "taux_conversion_resolus_pct")
    assert "7 lead(s) résolu(s)" in taux["manque"][0]["raison"] and "0 %" in taux["manque"][0]["raison"]
    _non_calculable(_op(definitions, "m8_valeur_ponderee_pipeline_cad", refus), "valeur_ponderee_cad")


def test_deux_constats_du_meme_jour_le_dernier_publie_l_emporte(definitions):
    matin = _pipeline(ouverts=10, version="1" * 16, heure=7)
    soir = _pipeline(ouverts=15, version="2" * 16, heure=18)
    for ordre in ((matin, soir), (soir, matin)):
        assert _op(definitions, "m8_pipeline_leads_ouverts", *ordre)["valeur"] == "15"


def test_aucun_constat_du_pipeline_les_trois_mesures_sont_non_calculables(definitions):
    for metric_id in ("m8_pipeline_leads_ouverts", "m8_taux_conversion_resolus_pct", "m8_valeur_ponderee_pipeline_cad"):
        _non_calculable(_op(definitions, metric_id), "m2.pipeline_constate")


# ================================================================================================ M2 : filet anti-perte
REGLES_SLA = (
    "prochaine_action_obligatoire", "lead_chaud_non_contacte", "photos_non_recues", "soumission_non_relancee",
    "plainte_non_escaladee", "lead_sans_proprietaire", "tache_en_retard",
)
CONTROLES_INTEGRITE = (
    "lead_sans_statut", "client_sans_contact", "tache_sans_proprietaire", "soumission_orpheline", "activite_sans_lead",
    "lead_sans_client", "pipeline_incoherent", "doublon_probable",
)


def _filet(
    date=JOUR, violations=None, non_evaluees=(), partielles=(), anomalies=None, non_evalues=(), version="e" * 16,
    heure=7, leads=40,
):
    violations = violations or {}
    par_regle = {r: None if r in non_evaluees else violations.get(r, 0) for r in REGLES_SLA}
    evaluees = [n for n in par_regle.values() if n is not None]
    anomalies = anomalies or {}
    par_controle = {c: None if c in non_evalues else anomalies.get(c, 0) for c in CONTROLES_INTEGRITE}
    return _fait(
        op.TYPE_FILET,
        "m2.filet_anti_perte_constate",
        {
            "evenement_id": f"m2-filet-{date}-{version}-{heure}",
            "date_reference": date,
            "constate_le": f"{date}T07:00:00-04:00",
            "version_donnees": version,
            "leads_examines": leads,
            "violations_par_regle": par_regle,
            "violations_total": sum(evaluees) if evaluees else None,
            "regles_non_evaluees": list(non_evaluees),
            "regles_partielles": list(partielles),
            "anomalies_par_controle": par_controle,
            "anomalies_total": sum(n for n in par_controle.values() if n is not None),
            "controles_non_evalues": list(non_evalues),
        },
        heure,
    )


def test_le_filet_complet_donne_les_deux_mesures_reprises_telles_quelles_a_couverture_complete(definitions):
    f = _filet(violations={"lead_chaud_non_contacte": 3, "tache_en_retard": 2}, anomalies={"pipeline_incoherent": 4})
    v = _op(definitions, "m8_violations_sla_commercial", f)
    assert v["statut"] == "calculee" and v["valeur"] == "5" and v["couverture"] == {"etat": "complete"}
    assert v["entrees"]["violations_par_regle"]["lead_chaud_non_contacte"] == 3
    assert v["entrees"]["leads_examines"] == 40 and v["dernier_fait_le"] == f"{JOUR}T07:00:00-04:00"
    a = _op(definitions, "m8_anomalies_integrite_crm", f)
    assert a["statut"] == "calculee" and a["valeur"] == "4" and a["couverture"] == {"etat": "complete"}
    assert a["entrees"]["anomalies_par_controle"]["pipeline_incoherent"] == 4


def test_zero_violation_avec_toutes_les_regles_evaluees_est_un_vrai_zero(definitions):
    f = _filet()
    assert _op(definitions, "m8_violations_sla_commercial", f)["valeur"] == "0"
    assert _op(definitions, "m8_anomalies_integrite_crm", f)["valeur"] == "0"


def test_aucun_delai_declare_la_mesure_des_violations_est_non_calculable_pas_zero_l_audit_se_calcule(definitions):
    sans_delai = _filet(
        non_evaluees=(*REGLES_SLA[1:5], REGLES_SLA[6]), partielles=(REGLES_SLA[0], REGLES_SLA[5]), version="f" * 16
    )
    m = _op(definitions, "m8_violations_sla_commercial", sans_delai)
    _non_calculable(m, "regles_sla")
    assert "aucune règle SLA n'est évaluée en entier" in m["manque"][0]["raison"] and "zéro" in m["manque"][0]["raison"]
    assert _op(definitions, "m8_anomalies_integrite_crm", sans_delai)["statut"] == "calculee"
    # une seule règle évaluée en entier suffit pour que la mesure existe (couverture partielle, dite)
    une = _filet(non_evaluees=REGLES_SLA[1:5], partielles=(REGLES_SLA[0], REGLES_SLA[5]), version="a" * 16)
    assert _op(definitions, "m8_violations_sla_commercial", une)["statut"] == "calculee"


def test_des_regles_non_evaluees_ou_partielles_rendent_la_couverture_partielle_et_la_disent(definitions):
    f = _filet(
        violations={"tache_en_retard": 2}, non_evaluees=("photos_non_recues",), partielles=("lead_sans_proprietaire",)
    )
    m = _op(definitions, "m8_violations_sla_commercial", f)
    assert m["statut"] == "calculee" and m["valeur"] == "2"
    assert m["couverture"]["etat"] == "partielle"
    assert (m["couverture"]["couverts"], m["couverture"]["attendus"]) == (5, 7)
    assert "photos_non_recues" in m["couverture"]["raison"] and "lead_sans_proprietaire" in m["couverture"]["raison"]
    assert m["entrees"]["regles_non_evaluees"] == ["photos_non_recues"]
    assert m["entrees"]["regles_partielles"] == ["lead_sans_proprietaire"]


def test_un_controle_non_evalue_rend_la_couverture_de_l_audit_partielle_et_le_nomme(definitions):
    f = _filet(anomalies={"client_sans_contact": 1}, non_evalues=("soumission_orpheline",))
    m = _op(definitions, "m8_anomalies_integrite_crm", f)
    assert m["statut"] == "calculee" and m["valeur"] == "1" and m["couverture"]["etat"] == "partielle"
    assert (m["couverture"]["couverts"], m["couverture"]["attendus"]) == (7, 8)
    assert "soumission_orpheline" in m["couverture"]["raison"]
    assert m["entrees"]["controles_non_evalues"] == ["soumission_orpheline"]


def test_le_filet_du_jour_le_plus_recent_est_repris_le_dernier_publie_l_emporte_quel_que_soit_l_ordre(definitions):
    hier = _filet(date="2026-10-29", violations={"tache_en_retard": 99}, version="1" * 16)
    matin = _filet(violations={"tache_en_retard": 1}, version="2" * 16, heure=7)
    soir = _filet(violations={"tache_en_retard": 4}, version="3" * 16, heure=18)
    for ordre in ((hier, matin, soir), (soir, matin, hier), (matin, hier, soir)):
        assert _op(definitions, "m8_violations_sla_commercial", *ordre)["valeur"] == "4"


def test_aucun_constat_du_filet_les_deux_mesures_sont_non_calculables(definitions):
    for metric_id in ("m8_violations_sla_commercial", "m8_anomalies_integrite_crm"):
        _non_calculable(_op(definitions, metric_id), "m2.filet_anti_perte_constate")


@pytest.mark.parametrize("abime", [
    {"violations_total": -1}, {"violations_total": "3"}, {"violations_par_regle": {}}, {"anomalies_total": -2},
    {"anomalies_total": None}, {"anomalies_par_controle": {}},
])
def test_un_constat_illisible_est_non_calculable_jamais_une_valeur_devinee(definitions, abime):
    fait = {**_filet(violations={"tache_en_retard": 1}), **abime}
    if "violations_total" in abime or "violations_par_regle" in abime:
        _non_calculable(_op(definitions, "m8_violations_sla_commercial", fait))
    else:
        _non_calculable(_op(definitions, "m8_anomalies_integrite_crm", fait))


def test_le_filet_ne_garde_rien_de_plus_que_ses_comptes_une_propriete_en_trop_ne_traverse_pas():
    brut = {**_filet().copy()}
    charge = {k: v for k, v in brut.items() if k not in ("type_entree", "provenance", "publie_le")}
    charge["evenement_id"] = brut["provenance"]["evenement_id"]
    charge.update({"lead_id": "L05", "contact": {"nom": "Jeanne"}, "vendeur": "vendeur.un"})
    range_ = op.fait(op.TYPE_FILET, charge, f"{JOUR}T07:00:00-04:00")
    assert not {"lead_id", "contact", "vendeur"} & set(range_)
    assert op.cles_unicite(op.TYPE_FILET) == ("date_reference", "version_donnees", "constate_le")
    texte = json.dumps(range_, ensure_ascii=False)
    for interdit in ("L05", "Jeanne", "vendeur.un"):
        assert interdit not in texte


# ================================================================================================ M6 : disponibilité
def test_les_cinq_comptes_de_disponibilite_sont_repris(definitions):
    d = _dispo()
    assert _op(definitions, "m8_articles_en_rupture", d)["valeur"] == "3"
    assert _op(definitions, "m8_articles_sur_reserves", d)["valeur"] == "1"
    m = _op(definitions, "m8_reservations_incompletes", d)
    assert m["valeur"] == "2" and m["entrees"]["reservations_actives"] == 5
    assert m["dernier_fait_le"] == f"{JOUR}T07:00:00-04:00"


def test_aucun_article_suivi_les_comptes_d_articles_sont_non_calculables_pas_zero(definitions):
    vide = _dispo(suivis=0, rupture=0, sur=0, actives=0, incompletes=0, version="0" * 16)
    _non_calculable(_op(definitions, "m8_articles_en_rupture", vide), "articles_suivis")
    _non_calculable(_op(definitions, "m8_articles_sur_reserves", vide), "articles_suivis")
    assert (
        _op(definitions, "m8_reservations_incompletes", vide)["valeur"] == "0"
    )  # aucune réservation active : 0 véridique


def test_le_dernier_constat_de_disponibilite_publie_l_emporte_y_compris_un_retour_en_arriere(definitions):
    a = _dispo(rupture=3, version="1" * 16, heure=7)
    b = _dispo(rupture=5, version="2" * 16, heure=9)
    a_encore = _dispo(rupture=3, version="1" * 16, heure=11)
    a_encore = {**a_encore, "constate_le": f"{JOUR}T11:00:00-04:00"}
    for ordre in ((a, b, a_encore), (a_encore, b, a)):
        assert _op(definitions, "m8_articles_en_rupture", *ordre)["valeur"] == "3"


def test_aucun_constat_de_disponibilite_les_mesures_sont_non_calculables(definitions):
    for metric_id in ("m8_articles_en_rupture", "m8_articles_sur_reserves", "m8_reservations_incompletes"):
        _non_calculable(_op(definitions, metric_id), "m6.disponibilite_constatee")


# ================================================================================================ M1 : plaintes
def test_des_plaintes_connues_donnent_leur_nombre(definitions):
    m = _op(definitions, "m8_plaintes_periode", _plaintes())
    assert m["valeur"] == "2" and m["entrees"]["jours"] == 30 and m["entrees"]["etat"] == "CONNUE"
    assert _op(definitions, "m8_plaintes_periode", _plaintes(nombre=0))["valeur"] == "0"  # CONNUE à zéro : un vrai zéro


def test_aucune_declaree_par_la_source_n_est_pas_zero_plainte(definitions):
    m = _op(definitions, "m8_plaintes_periode", _plaintes(etat="AUCUNE_DECLAREE_PAR_SOURCE"))
    _non_calculable(m, "nombre")
    assert "pas « zéro plainte »" in m["manque"][0]["raison"]


def test_un_constat_forge_qui_porte_un_nombre_sans_etre_connue_n_est_pas_cru(definitions):
    for etat in ("AUCUNE_DECLAREE_PAR_SOURCE", "NON_BRANCHEE"):
        forge = {**_plaintes(etat=etat), "nombre": 0}
        _non_calculable(_op(definitions, "m8_plaintes_periode", forge), "nombre")


def test_non_branchee_n_est_pas_zero_non_plus(definitions):
    m = _op(definitions, "m8_plaintes_periode", _plaintes(etat="NON_BRANCHEE"))
    _non_calculable(m, "nombre")
    assert "NON_BRANCHEE" in m["manque"][0]["raison"]


def test_le_constat_de_plaintes_du_jour_le_plus_recent_l_emporte(definitions):
    hier = _plaintes(nombre=9, date="2026-10-29", empreinte="01" * 32)
    aujourd_hui = _plaintes(nombre=2)
    for ordre in ((hier, aujourd_hui), (aujourd_hui, hier)):
        assert _op(definitions, "m8_plaintes_periode", *ordre)["valeur"] == "2"
    _non_calculable(_op(definitions, "m8_plaintes_periode"), "m1.plaintes_constatees")


# ================================================================================================ D6 : leads
# publicitaires
def _leads_fictifs():
    return [_lead(1, "google"), _lead(2, "facebook"), _lead(3, "google-ads"), _lead(4), _lead(5, "bouche-a-oreille")]


def test_sans_correspondance_declaree_les_mesures_publicitaires_sont_non_calculables(definitions):
    for metric_id in ("m8_leads_publicitaires", "m8_cout_par_lead_pub_cad"):
        m = _op(definitions, metric_id, *_releves_fictifs(), entonnoir_=_leads_fictifs())
        _non_calculable(m, "canaux_marketing")
        assert "n'en devine aucune" in m["manque"][0]["raison"]


def test_un_profil_invalide_n_est_pas_lu_comme_une_absence(definitions):
    invalide = [{"type_entree": "canaux_marketing", "canaux": {}, "verdict": "REJ-PROFIL-INVALIDE"}]
    m = _op(definitions, "m8_leads_publicitaires", entonnoir_=_leads_fictifs(), declarations=invalide)
    _non_calculable(m, "canaux_marketing")
    assert "invalide" in m["manque"][0]["raison"]


def test_les_leads_publicitaires_sont_classes_par_la_correspondance_du_proprietaire(definitions):
    m = _op(
        definitions,
        "m8_leads_publicitaires",
        entonnoir_=_leads_fictifs(),
        declarations=_canaux(google_ads=["google", "google-ads"], meta=["facebook"]),
    )
    assert m["valeur"] == "3" and m["entrees"]["par_canal"] == {"google_ads": 2, "meta": 1}
    assert m["entrees"]["n_leads_sans_source"] == 1 and m["entrees"]["n_leads_source_non_declaree"] == 1
    assert m["couverture"]["etat"] == "partielle" and (m["couverture"]["couverts"], m["couverture"]["attendus"]) == (
        4,
        5,
    )


def test_un_lead_recu_deux_fois_compte_une_fois_et_la_source_est_en_minuscules(definitions):
    leads = [_lead(1, "GOOGLE"), _lead(1, "google")]
    m = _op(definitions, "m8_leads_publicitaires", entonnoir_=leads, declarations=_canaux(google_ads=["google"]))
    assert m["valeur"] == "1"


def test_aucun_lead_recu_n_est_pas_zero_lead_publicitaire(definitions):
    m = _op(definitions, "m8_leads_publicitaires", declarations=_canaux(google_ads=["google"]))
    _non_calculable(m, "m2.client_associe")


def test_le_cout_par_lead_divise_la_depense_des_releves_par_les_leads_de_la_periode(definitions):
    m = _op(
        definitions,
        "m8_cout_par_lead_pub_cad",
        *_releves_fictifs(),
        entonnoir_=_leads_fictifs(),
        declarations=_canaux(google_ads=["google", "google-ads"], meta=["facebook"]),
    )
    # relevés Google du 28 au 30 octobre (353,75 $) et Meta du 29 (60 $) ; leads du 30 : Google 2 ; Meta 0 (pas le 29)
    assert m["statut"] == "calculee" and m["valeur"] == "206.88"  # 413,75 / 2, arrondi au cent (ROUND_HALF_UP)
    assert m["entrees"]["depense_totale_cad"] == "413.75" and m["entrees"]["leads_publicitaires"] == 2
    assert m["entrees"]["par_canal"]["meta"]["leads"] == 0 and m["entrees"]["par_canal"]["google_ads"]["leads"] == 2
    assert m["couverture"] == {"etat": "complete"}  # aucun jour sans relevé, tous les canaux ont une source déclarée


def test_un_canal_avec_releves_sans_source_declaree_n_entre_pas_et_c_est_dit(definitions):
    m = _op(
        definitions,
        "m8_cout_par_lead_pub_cad",
        *_releves_fictifs(),
        entonnoir_=_leads_fictifs(),
        declarations=_canaux(google_ads=["google", "google-ads"]),
    )
    assert m["valeur"] == "176.88"  # 353,75 / 2
    assert m["entrees"]["canaux_sans_source_declaree"] == ["meta"]
    assert m["couverture"]["etat"] == "partielle" and "meta" in m["couverture"]["raison"]


def test_aucun_lead_rattache_dans_la_periode_refuse_de_diviser_par_zero(definitions):
    hors_periode = [_lead(1, "google", jour="2026-09-01")]
    m = _op(
        definitions,
        "m8_cout_par_lead_pub_cad",
        *_releves_fictifs(),
        entonnoir_=hors_periode,
        declarations=_canaux(google_ads=["google"]),
    )
    _non_calculable(m, "m2.client_associe")
    assert "diviser par zéro" in m["manque"][0]["raison"]


def test_releves_qui_se_chevauchent_ou_bases_de_taxes_melangees_le_cout_par_lead_est_non_calculable(definitions):
    declarations = _canaux(google_ads=["google"])
    double = [
        _releve("r-1", "google_ads", "2026-10-28", JOUR, "10.00"),
        _releve("r-2", "google_ads", JOUR, JOUR, "5.00"),
    ]
    _non_calculable(
        _op(
            definitions, "m8_cout_par_lead_pub_cad", *double, entonnoir_=[_lead(1, "google")], declarations=declarations
        ),
        "periode",
    )
    mixte = [
        _releve("r-1", "google_ads", JOUR, JOUR, "10.00"),
        _releve("r-2", "meta", JOUR, JOUR, "5.00", base="TAXES_INCLUSES"),
    ]
    _non_calculable(
        _op(
            definitions, "m8_cout_par_lead_pub_cad", *mixte, entonnoir_=[_lead(1, "google")], declarations=declarations
        ),
        "base_taxes",
    )


def test_aucun_releve_ou_aucun_canal_commun_le_cout_par_lead_est_non_calculable(definitions):
    declarations = _canaux(google_ads=["google"])
    _non_calculable(
        _op(definitions, "m8_cout_par_lead_pub_cad", entonnoir_=[_lead(1, "google")], declarations=declarations),
        "m7.depenses_marketing_constatees",
    )
    seulement_meta = [_releve("r-1", "meta", JOUR, JOUR, "5.00")]
    m = _op(
        definitions,
        "m8_cout_par_lead_pub_cad",
        *seulement_meta,
        entonnoir_=[_lead(1, "google")],
        declarations=declarations,
    )
    _non_calculable(m, "canaux_marketing")


# ================================================================================================ garanties communes
def test_les_declarations_se_lisent_sans_deviner():
    canaux, manque = mesures_constats.declarations_canaux(_canaux(google_ads=["google"], meta=["facebook"]))
    assert canaux == {"google_ads": ("google",), "meta": ("facebook",)} and manque is None
    for vide in ([], _canaux(), [{"type_entree": "canaux_marketing", "canaux": {"meta": []}}]):
        canaux, manque = mesures_constats.declarations_canaux(vide)
        assert canaux == {} and manque["champ"] == "canaux_marketing"


def test_l_empreinte_des_faits_suit_les_faits_utilises_et_pas_l_ordre(definitions):
    a, b = _facture("f-1", "ENVOYEE"), _facture("f-2", "ENVOYEE", avant="500.00")
    un = _op(definitions, "m8_facturation_emise_cad", a, b)["entrees"]["empreinte_faits"]
    assert _op(definitions, "m8_facturation_emise_cad", b, a)["entrees"]["empreinte_faits"] == un
    autre = _op(definitions, "m8_facturation_emise_cad", a, _facture("f-2", "ENVOYEE", avant="501.00"))
    assert autre["entrees"]["empreinte_faits"] != un


def test_toutes_les_mesures_de_la_phase_2_sont_calculees_sur_l_entreprise_fictive_et_sans_personne(definitions):
    registres = jeux_fictifs.registres_fictifs(avec_operations=True)
    mesures = {m["metric_id"]: m for m in mi.mesurer(registres, definitions)}
    nouvelles = [i for i in mesures_constats.CALCULS]
    assert len(nouvelles) == 22 and set(nouvelles) <= set(mesures)
    assert all(mesures[i]["statut"] == "calculee" for i in nouvelles), [
        i for i in nouvelles if mesures[i]["statut"] != "calculee"
    ]
    texte = json.dumps([mesures[i] for i in nouvelles], ensure_ascii=False)
    for interdit in ("tech-fictif", "technicien", "example.test", "fournisseur", "client_id", "a" * 64):
        assert interdit not in texte


def test_aucun_flottant_ni_horloge_dans_le_code_des_mesures():
    source = _SRC.read_text(encoding="utf-8")
    arbre = ast.parse(source)
    appels = {n.func.id for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not appels & {"float", "round"}
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(arbre))
    assert "datetime.now" not in source and "time.time" not in source and "import opsys" not in source
