"""Entonnoir commercial (`entonnoir.py`, PLAN T4.19) : huit métriques gouvernées, calculées par le code d'après les
faits de M2 et de M3, ou « non calculable, manque X » — jamais un zéro inventé.

Module pur : les faits sont construits par les vrais constructeurs (`fait_*`) à partir de charges au format du
catalogue des événements. Identifiants, personnes et montants fictifs (`FICTIF`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from m8_analytics import contrats, dictionnaire, entonnoir, registre_metriques

FICTIF = True  # aucun client réel : des identifiants de test, des montants de test

_RACINE_M8 = Path(__file__).resolve().parents[1]
_RACINE_DEPARTEMENTS = _RACINE_M8.parent
_YAML = _RACINE_M8 / "metrics" / "m8-entonnoir.v1.yaml"

METRIQUES = (
    "m8_leads_recus", "m8_leads_qualifies", "m8_devis_envoyes", "m8_devis_acceptes", "m8_devis_sans_reponse",
    "m8_taux_acceptation_pct", "m8_delai_lead_acceptation_jours", "m8_carnet_signe_cad",
)


# ---------------------------------------------------------------------------
# Faits, construits comme le bus les livre
# ---------------------------------------------------------------------------
def _lead(lead_id, arrivee="2026-09-29T09:15:00-04:00"):
    return entonnoir.fait_lead_recu(
        {"lead_id": lead_id, "client_id": "a" * 64, "horodatage_association": arrivee}
    )


def _qualifie(lead_id, quand="2026-09-29T11:00:00-04:00"):
    return entonnoir.fait_lead_qualifie(
        {"lead_id": lead_id, "proprietaire": "Alice Vendeuse (fictif)", "horodatage_assignation": quand}
    )


def _envoye(devis_id, lead_id="lead-1-fictif", quand="2026-09-29T15:00:00-04:00"):
    return entonnoir.fait_devis_envoye(
        {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": quand}
    )


def _accepte(devis_id, lead_id="lead-1-fictif", prix="600.00", quand="2026-09-30T10:00:00-04:00"):
    return entonnoir.fait_devis_accepte({
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"reference_ligne": f"{devis_id}-L0", "description": "Gouttières (fictif)", "quantite": "40"}],
        "cout_total": "480.00", "prix_total": prix, "taux_marge": "0.25", "horodatage_acceptation": quand,
    })


def _sans_reponse(devis_id, lead_id="lead-1-fictif", statut="envoye", depuis="2026-09-29T15:30:00-04:00",
                  constat="2026-10-08T08:00:00-04:00"):
    return entonnoir.fait_devis_sans_reponse({
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "statut": statut,
        "horodatage_devis": depuis, "horodatage_reference": constat, "delai_relance_jours": 7,
    })


def _wct(wct_id, devis_id):
    """Un chantier terminé, tel que `mesures_chantier.fait_wct` le range au registre des chantiers."""
    return {
        "type_entree": "wct", "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "devis_id": devis_id,
        "technicien_id": "tech-fictif", "horodatage_completion": "2026-10-05T14:00:00-04:00",
        "duree_reelle_minutes": 100, "statut": "completed_verified",
    }


def _scenario():
    """Trois leads, quatre devis : D1 (600,00 $) accepté 24 h 45 après l'arrivée de son lead ; D2 envoyé, sans
    réponse ; D3 (1 250,50 $) accepté 3 jours pile après l'arrivée du sien, chantier déjà terminé ; D4 jamais envoyé
    (brouillon)."""
    return [
        _lead("lead-1-fictif", "2026-09-29T09:15:00-04:00"),
        _lead("lead-2-fictif", "2026-09-29T10:00:00-04:00"),
        _lead("lead-3-fictif", "2026-09-30T08:00:00-04:00"),
        _qualifie("lead-1-fictif"), _qualifie("lead-2-fictif"),
        _envoye("D1", "lead-1-fictif"), _envoye("D2", "lead-1-fictif"), _envoye("D3", "lead-2-fictif"),
        _accepte("D1", "lead-1-fictif", "600.00", "2026-09-30T10:00:00-04:00"),
        _accepte("D3", "lead-2-fictif", "1250.50", "2026-10-02T10:00:00-04:00"),
        _sans_reponse("D2", "lead-1-fictif"),
        _sans_reponse("D4", "lead-3-fictif", statut="brouillon", depuis="2026-09-30T09:00:00-04:00"),
    ]


def _mesures(entrees, faits_chantier=()):
    definitions = entonnoir.charger_definitions()
    return {m["metric_id"]: m for m in entonnoir.mesurer(list(entrees), list(faits_chantier), definitions)}


# ---------------------------------------------------------------------------
# Le registre : chaque métrique est définie une fois, avec sa source, son unité et son propriétaire
# ---------------------------------------------------------------------------
def test_le_registre_definit_huit_metriques_gouvernees_avec_source_unite_et_proprietaire():
    definitions = entonnoir.charger_definitions()

    assert tuple(definitions) == METRIQUES
    for metric_id, definition in definitions.items():
        assert set(definition) == contrats.CHAMPS_DEFINITION_METRIQUE | {"proprietaire"}, metric_id
        assert all(isinstance(definition[cle], str) and definition[cle] for cle in definition), metric_id
        assert registre_metriques.departement_connu(definition["proprietaire"]), metric_id
        assert definition["source_donnees"].startswith(("M2 ", "M3 ")), metric_id  # la source dit qui publie
    assert {m: d["unite"] for m, d in definitions.items()} == {
        "m8_leads_recus": "leads", "m8_leads_qualifies": "leads", "m8_devis_envoyes": "devis",
        "m8_devis_acceptes": "devis", "m8_devis_sans_reponse": "devis", "m8_taux_acceptation_pct": "pourcentage",
        "m8_delai_lead_acceptation_jours": "jours", "m8_carnet_signe_cad": "CAD",
    }
    assert {m: d["proprietaire"] for m, d in definitions.items()} == {
        "m8_leads_recus": "m02-revenue-crm", "m8_leads_qualifies": "m02-revenue-crm",
        "m8_devis_envoyes": "m03-estimation", "m8_devis_acceptes": "m03-estimation",
        "m8_devis_sans_reponse": "m03-estimation", "m8_taux_acceptation_pct": "m03-estimation",
        "m8_delai_lead_acceptation_jours": "m02-revenue-crm", "m8_carnet_signe_cad": "m03-estimation",
    }


def test_le_dictionnaire_compile_du_depot_contient_les_metriques_de_l_entonnoir_sans_erreur():
    """Compilées par la même garde de devise que les autres : le carnet est en CAD, aucune autre unité n'est une
    devise. Le contrat v1 (`CHAMPS_DEFINITION_METRIQUE`) n'a pas changé : le propriétaire est une clé sœur."""
    resultat, erreurs = dictionnaire.compiler_dictionnaire(_RACINE_DEPARTEMENTS)

    assert not [erreur for erreur in erreurs if "m8-entonnoir" in erreur]
    assert set(METRIQUES) <= set(resultat["m08-analytics"])
    assert resultat["m08-analytics"]["m8_carnet_signe_cad"]["unite"] == "CAD"
    assert "proprietaire" not in resultat["m08-analytics"]["m8_carnet_signe_cad"]


def _yaml_modifie(tmp_path, modifier):
    contenu = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    modifier(contenu)
    chemin = tmp_path / "m8-entonnoir-modifie.yaml"
    chemin.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    return chemin


def test_une_metrique_sans_proprietaire_n_est_pas_gouvernee(tmp_path):
    chemin = _yaml_modifie(tmp_path, lambda c: c["proprietaires"].pop("m8_carnet_signe_cad"))

    with pytest.raises(ValueError, match="sans propriétaire.*m8_carnet_signe_cad"):
        entonnoir.charger_definitions(chemin)


def test_sans_aucune_cle_proprietaires_le_registre_est_refuse(tmp_path):
    chemin = _yaml_modifie(tmp_path, lambda c: c.pop("proprietaires"))

    with pytest.raises(ValueError, match="`proprietaires` absent"):
        entonnoir.charger_definitions(chemin)


@pytest.mark.parametrize("proprietaire", ["m99-inconnu", "M3", "", None, ["m03-estimation"]])
def test_un_proprietaire_qui_n_est_pas_un_departement_connu_est_refuse(tmp_path, proprietaire):
    chemin = _yaml_modifie(tmp_path, lambda c: c["proprietaires"].update({"m8_leads_recus": proprietaire}))

    with pytest.raises(ValueError, match="propriétaire inconnu.*m8_leads_recus"):
        entonnoir.charger_definitions(chemin)


def test_un_proprietaire_sans_metrique_est_une_faute_de_frappe_refusee(tmp_path):
    chemin = _yaml_modifie(tmp_path, lambda c: c["proprietaires"].update({"m8_leads_recu": "m02-revenue-crm"}))

    with pytest.raises(ValueError, match="sans métrique.*m8_leads_recu"):
        entonnoir.charger_definitions(chemin)


def test_une_unite_monetaire_qui_n_est_pas_cad_est_refusee_par_la_garde_de_devise(tmp_path):
    def en_dollars_americains(contenu):
        for metrique in contenu["metrics"]:
            if metrique["id"] == "m8_carnet_signe_cad":
                metrique["unite"] = "USD"

    with pytest.raises(ValueError, match="REJ-DEVISE-NON-AUTORISEE"):
        entonnoir.charger_definitions(_yaml_modifie(tmp_path, en_dollars_americains))


def test_la_version_d_une_definition_change_avec_son_proprietaire(tmp_path):
    """Le propriétaire fait partie de la définition gouvernée : en changer est une nouvelle version, dite dans la
    mesure (`version_definition`), jamais un changement silencieux."""
    chemin = _yaml_modifie(tmp_path, lambda c: c["proprietaires"].update({"m8_leads_recus": "m01-front-office"}))
    faits = [_lead("lead-1-fictif")]

    avant = entonnoir.mesurer(faits, [], entonnoir.charger_definitions())
    apres = entonnoir.mesurer(faits, [], entonnoir.charger_definitions(chemin))

    assert avant[0]["version_definition"] != apres[0]["version_definition"]
    assert avant[1]["version_definition"] == apres[1]["version_definition"]  # les autres métriques n'ont pas bougé
    assert len(avant[0]["version_definition"]) == 64


# ---------------------------------------------------------------------------
# Le scénario nominal : chaque chiffre, à la main
# ---------------------------------------------------------------------------
def test_le_scenario_nominal_donne_les_huit_chiffres_calcules_par_le_code():
    mesures = _mesures(_scenario(), [_wct("wct-D3", "D3")])

    assert {m: (x["statut"], x["valeur"]) for m, x in mesures.items()} == {
        "m8_leads_recus": ("calculee", "3"),
        "m8_leads_qualifies": ("calculee", "2"),
        "m8_devis_envoyes": ("calculee", "3"),  # D1, D2, D3
        "m8_devis_acceptes": ("calculee", "2"),  # D1, D3
        "m8_devis_sans_reponse": ("calculee", "1"),  # D2 : envoyé, constaté, jamais accepté
        "m8_taux_acceptation_pct": ("calculee", "66.67"),  # 2 acceptés sur 3 envoyés
        "m8_delai_lead_acceptation_jours": ("calculee", "2.02"),  # médiane de 1,03125 j et 3 j
        "m8_carnet_signe_cad": ("calculee", "600.00"),  # D1 seul : le chantier de D3 est terminé
    }
    assert mesures["m8_devis_sans_reponse"]["entrees"] == {"n_constats_recus": 2, "brouillons_en_retard": 1}
    assert mesures["m8_taux_acceptation_pct"]["entrees"] == {
        "n_envoyes": 3, "n_acceptes_parmi_envoyes": 2, "n_acceptes_sans_envoi_recu": 0,
    }
    assert mesures["m8_delai_lead_acceptation_jours"]["entrees"] == {
        "n_mesures": 2, "n_sans_arrivee_du_lead": 0, "n_instants_illisibles": 0, "n_delais_negatifs": 0,
    }
    assert mesures["m8_carnet_signe_cad"]["entrees"] == {
        "n_devis_au_carnet": 1, "n_devis_acceptes": 2, "chantiers_termines_sans_devis_relie": 0,
    }


def test_chaque_mesure_porte_sa_version_sa_source_et_son_proprietaire():
    definitions = entonnoir.charger_definitions()
    mesures = _mesures(_scenario())

    for metric_id, mesure in mesures.items():
        assert mesure["nom"] == definitions[metric_id]["nom"] and mesure["unite"] == definitions[metric_id]["unite"]
        assert mesure["proprietaire"] == definitions[metric_id]["proprietaire"]
        assert mesure["source"] == definitions[metric_id]["source_donnees"]
        assert len(mesure["version_definition"]) == 64 and mesure["manque"] == [] and mesure["detail"] is None
    assert len({m["version_definition"] for m in mesures.values()}) == 8  # une définition, une version


def test_le_resultat_ne_depend_pas_de_l_ordre_de_reception_des_faits():
    """Le bus ne garantit pas l'ordre de livraison : une mesure ne doit jamais en dépendre."""
    faits = _scenario()
    chantiers = [_wct("wct-D3", "D3")]
    attendu = entonnoir.mesurer(faits, chantiers, entonnoir.charger_definitions())

    for ordre in (list(reversed(faits)), faits[5:] + faits[:5], faits[1::2] + faits[0::2]):
        assert entonnoir.mesurer(ordre, chantiers, entonnoir.charger_definitions()) == attendu


def test_un_fait_recu_deux_fois_ne_compte_qu_une_fois():
    faits = _scenario()

    assert _mesures(faits + faits) == _mesures(faits)


# ---------------------------------------------------------------------------
# Une donnée absente : « non calculable, manque X », jamais un zéro inventé
# ---------------------------------------------------------------------------
def test_sans_aucun_fait_tout_est_non_calculable_et_nomme_ses_sources():
    """Zéro fait de l'entonnoir : M8 ne peut pas dire si l'entreprise n'a rien fait ou si le bus n'a rien livré. Aucun
    comptage n'est donc un zéro : chacun dit quelle source manque."""
    mesures = _mesures([])

    assert tuple(mesures) == METRIQUES
    for metric_id, mesure in mesures.items():
        assert mesure["statut"] == "non_calculable" and mesure["valeur"] is None, metric_id
        assert mesure["manque"] and mesure["detail"].startswith("non calculable, manque "), metric_id
        assert {m["source"][:2] for m in mesure["manque"]} <= {"M2", "M3"}
    assert [m["champ"] for m in mesures["m8_taux_acceptation_pct"]["manque"]] == ["m3.devis_envoye", "m3.devis_accepte"]
    assert [m["champ"] for m in mesures["m8_delai_lead_acceptation_jours"]["manque"]] == [
        "m2.client_associe", "m3.devis_accepte",
    ]
    assert [m["champ"] for m in mesures["m8_carnet_signe_cad"]["manque"]] == ["m3.devis_accepte"]


def test_des_qu_un_fait_est_recu_un_comptage_a_zero_est_un_zero_mais_un_rapport_exige_son_denominateur():
    mesures = _mesures([_lead("lead-1-fictif")])

    assert (mesures["m8_leads_recus"]["statut"], mesures["m8_leads_recus"]["valeur"]) == ("calculee", "1")
    for metric_id in ("m8_leads_qualifies", "m8_devis_envoyes", "m8_devis_acceptes", "m8_devis_sans_reponse"):
        assert (mesures[metric_id]["statut"], mesures[metric_id]["valeur"]) == ("calculee", "0"), metric_id
    assert mesures["m8_carnet_signe_cad"]["valeur"] == "0.00"  # un carnet vide est un carnet de zéro dollar
    taux = mesures["m8_taux_acceptation_pct"]
    assert taux["statut"] == "non_calculable" and taux["valeur"] is None
    assert taux["manque"][0]["champ"] == "m3.devis_envoye" and "dénominateur" in taux["manque"][0]["raison"]
    delai = mesures["m8_delai_lead_acceptation_jours"]
    assert delai["statut"] == "non_calculable" and delai["manque"][0]["raison"] == "aucun devis accepté reçu"


def test_le_taux_d_acceptation_compte_les_devis_envoyes_puis_acceptes_et_dit_ce_qu_il_laisse_de_cote():
    faits = [
        _envoye("A"), _envoye("B"), _envoye("C"),
        _accepte("A"), _accepte("D"),  # D est accepté sans envoi reçu : hors du taux, mais dit
    ]

    mesures = _mesures(faits)

    assert mesures["m8_devis_acceptes"]["valeur"] == "2"
    assert mesures["m8_taux_acceptation_pct"]["valeur"] == "33.33"  # A sur A, B, C : jamais 2 sur 3
    assert mesures["m8_taux_acceptation_pct"]["entrees"] == {
        "n_envoyes": 3, "n_acceptes_parmi_envoyes": 1, "n_acceptes_sans_envoi_recu": 1,
    }


def test_le_taux_d_acceptation_ne_depasse_jamais_cent_pour_cent():
    faits = [_envoye("A"), _accepte("A"), _accepte("B"), _accepte("C")]  # trois acceptés, un seul envoyé

    assert _mesures(faits)["m8_taux_acceptation_pct"]["valeur"] == "100.00"


def test_les_devis_en_attente_sont_du_plus_ancien_au_plus_recent_et_un_brouillon_n_est_pas_sans_reponse():
    faits = [
        _sans_reponse("D-recent", depuis="2026-10-01T08:00:00-04:00"),
        _sans_reponse("D-ancien", depuis="2026-09-20T08:00:00-04:00"),
        _sans_reponse("D-illisible", depuis="hier"),
        _sans_reponse("D-accepte-depuis", depuis="2026-09-01T08:00:00-04:00"),
        _accepte("D-accepte-depuis"),
        _sans_reponse("B-jamais-envoye", statut="brouillon", depuis="2026-09-25T08:00:00-04:00"),
        _sans_reponse("B-envoye-ensuite", statut="brouillon", depuis="2026-09-24T08:00:00-04:00"),
        _envoye("B-envoye-ensuite"),
        _sans_reponse("B-accepte-ensuite", statut="brouillon"),
        _accepte("B-accepte-ensuite"),
    ]

    assert entonnoir.etat_des_devis(faits) == {
        "sans_reponse": ["D-ancien", "D-recent", "D-illisible"],  # l'instant illisible passe en dernier
        "brouillons_en_retard": ["B-jamais-envoye"],  # ni envoyé, ni accepté depuis : à envoyer ou abandonner
    }
    mesure = _mesures(faits)["m8_devis_sans_reponse"]
    assert mesure["valeur"] == "3" and mesure["entrees"] == {"n_constats_recus": 7, "brouillons_en_retard": 1}


# ---------------------------------------------------------------------------
# Le délai du lead à l'acceptation : une médiane, et tout ce qu'elle écarte est compté
# ---------------------------------------------------------------------------
def _accepte_apres(numero, jours, heures=0):
    """Un devis accepté `jours` jours et `heures` heures après l'arrivée de son lead (2026-09-01, midi UTC)."""
    lead_id = f"lead-{numero}-fictif"
    arrivee = "2026-09-01T12:00:00Z"
    acceptation = f"2026-09-{1 + jours:02d}T{12 + heures:02d}:00:00+00:00"
    return [_lead(lead_id, arrivee), _accepte(f"D{numero}", lead_id, quand=acceptation)]


def test_le_delai_est_la_mediane_en_jours_avec_un_nombre_impair_de_devis():
    faits = [*_accepte_apres(1, 1), *_accepte_apres(2, 2), *_accepte_apres(3, 10)]

    assert _mesures(faits)["m8_delai_lead_acceptation_jours"]["valeur"] == "2.00"  # pas la moyenne (4,33)


def test_le_delai_est_la_moyenne_des_deux_valeurs_du_milieu_avec_un_nombre_pair_de_devis():
    faits = [*_accepte_apres(1, 1), *_accepte_apres(2, 2, heures=6)]  # 1 j et 2 j 6 h : médiane 1 j 15 h

    assert _mesures(faits)["m8_delai_lead_acceptation_jours"]["valeur"] == "1.63"  # 1,625 arrondi au demi supérieur


def test_le_delai_ecarte_et_compte_ce_qui_ne_se_mesure_pas_au_lieu_de_l_ignorer_en_silence():
    faits = [
        *_accepte_apres(1, 3),  # mesurable : 3 jours
        _accepte("D-sans-arrivee", "lead-inconnu-fictif"),  # aucun fait d'arrivée pour ce lead
        _lead("lead-illisible-fictif", "hier midi"), _accepte("D-illisible", "lead-illisible-fictif"),
        _lead("lead-naif-fictif", "2026-09-01T12:00:00"),  # sans fuseau : jamais un fuseau deviné
        _accepte("D-naif", "lead-naif-fictif", quand="2026-09-05T12:00:00+00:00"),
        _lead("lead-futur-fictif", "2026-12-01T12:00:00+00:00"),  # arrivé APRÈS l'acceptation : instants incohérents
        _accepte("D-futur", "lead-futur-fictif", quand="2026-09-05T12:00:00+00:00"),
    ]

    mesure = _mesures(faits)["m8_delai_lead_acceptation_jours"]

    assert mesure["valeur"] == "3.00"
    assert mesure["entrees"] == {
        "n_mesures": 1, "n_sans_arrivee_du_lead": 1, "n_instants_illisibles": 2, "n_delais_negatifs": 1,
    }


def test_sans_aucun_delai_mesurable_le_delai_dit_pourquoi_par_cause():
    faits = [
        _accepte("D-sans-arrivee", "lead-inconnu-fictif"),
        _lead("lead-naif-fictif", "2026-09-01T12:00:00"), _accepte("D-naif", "lead-naif-fictif"),
        _lead("lead-futur-fictif", "2026-12-01T12:00:00+00:00"),
        _accepte("D-futur", "lead-futur-fictif", quand="2026-09-05T12:00:00+00:00"),
    ]

    mesure = _mesures(faits)["m8_delai_lead_acceptation_jours"]

    assert mesure["statut"] == "non_calculable" and mesure["valeur"] is None
    raisons = " | ".join(m["raison"] for m in mesure["manque"])
    assert "1 devis accepté(s) dont le lead n'a aucun fait d'arrivée reçu" in raisons
    assert "1 devis accepté(s) dont un instant est illisible" in raisons
    assert "1 devis accepté(s) acceptés avant l'arrivée de leur lead" in raisons
    assert mesure["entrees"]["n_mesures"] == 0


def test_le_delai_est_exact_a_la_seconde_pres():
    faits = [
        _lead("lead-1-fictif", "2026-09-29T09:15:00-04:00"),
        _accepte("D1", "lead-1-fictif", quand="2026-09-30T10:00:00-04:00"),  # 24 h 45 min = 1,03125 j
    ]

    assert _mesures(faits)["m8_delai_lead_acceptation_jours"]["valeur"] == "1.03"


# ---------------------------------------------------------------------------
# Le carnet signé : les prix de M3, jamais recalculés, moins ce qui est déjà terminé
# ---------------------------------------------------------------------------
def test_le_carnet_est_la_somme_exacte_des_prix_de_m3_des_devis_dont_le_chantier_n_est_pas_termine():
    faits = [_accepte("A", prix="0.10"), _accepte("B", prix="0.20"), _accepte("C", prix="1250.50")]

    mesure = _mesures(faits, [_wct("w1", "C")])["m8_carnet_signe_cad"]

    assert mesure["valeur"] == "0.30"  # Decimal : 0,10 + 0,20 sans erreur de flottant
    assert mesure["entrees"]["n_devis_au_carnet"] == 2 and mesure["entrees"]["n_devis_acceptes"] == 3


def test_un_chantier_termine_sans_devis_relie_ne_sort_aucun_devis_du_carnet_mais_est_dit():
    faits = [_accepte("A", prix="600.00")]

    mesure = _mesures(faits, [_wct("w-sans-devis", None), _wct("w-sans-devis-2", "")])["m8_carnet_signe_cad"]

    assert mesure["valeur"] == "600.00"  # rien n'autorise à deviner de quel devis il s'agit
    assert mesure["entrees"]["chantiers_termines_sans_devis_relie"] == 2


def test_le_carnet_ignore_les_faits_du_registre_des_chantiers_qui_ne_sont_pas_des_chantiers_termines():
    autres = [
        {"type_entree": "devis", "devis_id": "A", "prix_total": "1.00", "cout_total": "0.50"},
        {"type_entree": "rentabilite", "wct_id": "w1", "devis_id": "A", "sequence": 1},
    ]

    assert _mesures([_accepte("A", prix="600.00")], autres)["m8_carnet_signe_cad"]["valeur"] == "600.00"


@pytest.mark.parametrize("prix_illisible", ["abc", "", "NaN", "12,50"])
def test_un_prix_illisible_rend_le_carnet_non_calculable_jamais_une_somme_partielle(prix_illisible):
    faits = [_accepte("A", prix="600.00"), _accepte("B-fictif", prix=prix_illisible)]

    mesure = _mesures(faits)["m8_carnet_signe_cad"]

    assert mesure["statut"] == "non_calculable" and mesure["valeur"] is None
    assert mesure["manque"][0]["champ"] == "m3.devis_accepte"
    assert "1 devis du carnet sans prix lisible (prix_total) : B-fictif" in mesure["manque"][0]["raison"]


def test_un_prix_illisible_d_un_devis_deja_termine_ne_bloque_pas_le_carnet():
    faits = [_accepte("A", prix="600.00"), _accepte("B", prix="abc")]

    assert _mesures(faits, [_wct("w1", "B")])["m8_carnet_signe_cad"]["valeur"] == "600.00"


# ---------------------------------------------------------------------------
# Les faits : des identifiants, des instants et un prix arrêté, jamais de donnée de client
# ---------------------------------------------------------------------------
def test_les_faits_ne_gardent_ni_contact_ni_client_ni_proprietaire_ni_cout_ni_ligne():
    faits = _scenario()
    texte = json.dumps(faits, ensure_ascii=False)

    interdits = (
        "a" * 64, "Alice Vendeuse", "cout_total", "480.00", "taux_marge", "lignes", "Gouttières", "chantier_id",
    )
    for confidence in interdits:
        assert confidence not in texte, confidence
    assert {f["type_entree"] for f in faits} == {
        "lead_recu", "lead_qualifie", "devis_envoye", "devis_accepte", "devis_sans_reponse",
    }
    accepte = next(f for f in faits if f["type_entree"] == "devis_accepte")
    assert set(accepte) == {"type_entree", "devis_id", "lead_id", "prix_total", "horodatage"}


def test_l_instant_du_fait_est_celui_de_l_evenement_et_le_constat_de_m3_est_repris_tel_quel():
    constat = _sans_reponse("D2", constat="2026-10-08T08:00:00-04:00", depuis="2026-09-29T15:30:00-04:00")

    assert constat == {
        "type_entree": "devis_sans_reponse", "devis_id": "D2", "lead_id": "lead-1-fictif", "statut": "envoye",
        "horodatage": "2026-10-08T08:00:00-04:00",  # l'instant du constat
        "horodatage_devis": "2026-09-29T15:30:00-04:00",  # l'instant du dernier état du devis
        "delai_relance_jours": 7,
    }
    assert _envoye("D1", quand="2026-09-29T15:00:00-04:00")["horodatage"] == "2026-09-29T15:00:00-04:00"
    assert _lead("L", "2026-09-29T09:15:00-04:00")["horodatage"] == "2026-09-29T09:15:00-04:00"
    assert _qualifie("L", "2026-09-29T11:00:00-04:00")["horodatage"] == "2026-09-29T11:00:00-04:00"


def test_un_fait_est_unique_par_lead_ou_par_devis():
    assert entonnoir.cles_unicite(entonnoir.TYPE_LEAD_RECU) == ("lead_id",)
    assert entonnoir.cles_unicite(entonnoir.TYPE_LEAD_QUALIFIE) == ("lead_id",)
    for type_entree in (entonnoir.TYPE_DEVIS_ENVOYE, entonnoir.TYPE_DEVIS_ACCEPTE, entonnoir.TYPE_DEVIS_SANS_REPONSE):
        assert entonnoir.cles_unicite(type_entree) == ("devis_id",)


# ---------------------------------------------------------------------------
# Les sources : ce que M8 a reçu, et jusqu'où vont ses faits
# ---------------------------------------------------------------------------
def test_les_sources_disent_combien_de_faits_par_evenement_et_l_instant_du_plus_recent():
    sources = entonnoir.sources(_scenario())

    assert sources == [
        {"evenement": "m2.client_associe", "n": 3, "dernier_fait_le": "2026-09-30T08:00:00-04:00"},
        {"evenement": "m2.lead_assigne", "n": 2, "dernier_fait_le": "2026-09-29T11:00:00-04:00"},
        {"evenement": "m3.devis_envoye", "n": 3, "dernier_fait_le": "2026-09-29T15:00:00-04:00"},
        {"evenement": "m3.devis_accepte", "n": 2, "dernier_fait_le": "2026-10-02T10:00:00-04:00"},
        {"evenement": "m3.devis_sans_reponse", "n": 2, "dernier_fait_le": "2026-10-08T08:00:00-04:00"},
    ]


def test_une_source_sans_fait_est_dite_a_zero_et_un_instant_illisible_n_est_jamais_le_plus_recent():
    faits = [_lead("L1", "n'importe quoi"), _lead("L2", "2026-09-29T09:15:00-04:00")]

    par_evenement = {s["evenement"]: s for s in entonnoir.sources(faits)}

    assert par_evenement["m2.client_associe"] == {
        "evenement": "m2.client_associe", "n": 2, "dernier_fait_le": "2026-09-29T09:15:00-04:00",
    }
    assert par_evenement["m3.devis_accepte"] == {"evenement": "m3.devis_accepte", "n": 0, "dernier_fait_le": None}
    assert entonnoir.sources([_lead("L1", "illisible")])[0]["dernier_fait_le"] is None


# ---------------------------------------------------------------------------
# Les seuils : GATE NATHAN, aucun seuil inventé
# ---------------------------------------------------------------------------
def _evaluations(seuils, faits=None):
    mesures = entonnoir.mesurer(faits if faits is not None else _scenario(), [], entonnoir.charger_definitions())
    return {e["metric_id"]: e for e in entonnoir.evaluer_seuils(mesures, seuils)}


def test_sans_seuil_configure_chaque_metrique_surveillee_dit_seuil_a_configurer_et_rien_n_est_franchi():
    for seuils in ({}, None, [], "n'importe quoi"):
        evaluations = _evaluations(seuils)

        assert set(evaluations) == {
            "m8_devis_sans_reponse", "m8_taux_acceptation_pct", "m8_delai_lead_acceptation_jours",
            "m8_carnet_signe_cad",
        }
        for evaluation in evaluations.values():
            assert evaluation["statut"] == "seuil_a_configurer" and evaluation["seuil"] is None
            assert evaluation["sens"] is None


def test_un_seuil_configure_est_franchi_quand_la_valeur_l_atteint_ou_le_depasse_dans_son_sens():
    evaluations = _evaluations({
        "m8_taux_acceptation_pct": {"sens": "au_dessous", "valeur": 66.67},  # 66.67 : l'atteint, donc franchi
        "m8_devis_sans_reponse": {"sens": "au_dessus", "valeur": 2},  # 1 sur 2 : non franchi
        "m8_delai_lead_acceptation_jours": {"sens": "au_dessus", "valeur": 2.02},  # égal : franchi
        "m8_carnet_signe_cad": {"sens": "au_dessous", "valeur": 100},  # 600,00 : non franchi
    })

    assert {m: e["statut"] for m, e in evaluations.items()} == {
        "m8_taux_acceptation_pct": "franchi", "m8_devis_sans_reponse": "non_franchi",
        "m8_delai_lead_acceptation_jours": "franchi", "m8_carnet_signe_cad": "non_franchi",
    }
    taux = evaluations["m8_taux_acceptation_pct"]
    assert (taux["valeur"], taux["sens"], taux["seuil"]) == ("66.67", "au_dessous", "66.67")
    assert taux["unite"] == "pourcentage"
    assert evaluations["m8_carnet_signe_cad"]["seuil"] == "100.00"


def test_un_seuil_invalide_est_dit_invalide_jamais_devine():
    evaluations = _evaluations({
        "m8_taux_acceptation_pct": {"sens": "au-dessous", "valeur": 30},
        "m8_devis_sans_reponse": {"sens": "au_dessus", "valeur": "3"},
        "m8_carnet_signe_cad": 500,
    })

    assert evaluations["m8_taux_acceptation_pct"]["statut"] == "seuil_invalide"
    assert evaluations["m8_devis_sans_reponse"]["statut"] == "seuil_invalide"
    assert evaluations["m8_carnet_signe_cad"]["statut"] == "seuil_invalide"
    assert evaluations["m8_delai_lead_acceptation_jours"]["statut"] == "seuil_a_configurer"


def test_un_comptage_cumule_n_a_pas_de_seuil_meme_configure_et_une_mesure_non_calculable_n_est_pas_evaluee():
    seuils = {
        "m8_leads_recus": {"sens": "au_dessous", "valeur": 10},
        "m8_devis_acceptes": {"sens": "au_dessous", "valeur": 1},
    }

    evaluations = _evaluations(seuils)
    assert "m8_leads_recus" not in evaluations and "m8_devis_acceptes" not in evaluations

    sans_devis = _evaluations({}, faits=[_lead("lead-1-fictif")])  # ni taux, ni délai : non calculables
    assert set(sans_devis) == {"m8_devis_sans_reponse", "m8_carnet_signe_cad"}


def test_une_cle_de_seuil_qui_ne_surveille_rien_est_dite_jamais_ignoree_en_silence():
    """Une faute de frappe ou un comptage cumulé : le propriétaire croirait sa surveillance en place."""
    seuils = {
        "m8_leads_recus": {"sens": "au_dessous", "valeur": 10},  # un comptage cumulé : ne se surveille pas
        "m8_taux_acceptation": {"sens": "au_dessous", "valeur": 30},  # « _pct » oublié
        "m8_taux_acceptation_pct": {"sens": "au_dessous", "valeur": 30},  # celle-ci surveille
    }

    assert entonnoir.seuils_ignores(seuils) == ["m8_leads_recus", "m8_taux_acceptation"]
    assert entonnoir.seuils_ignores({}) == [] and entonnoir.seuils_ignores(None) == []
    assert entonnoir.seuils_ignores("n'importe quoi") == [] and entonnoir.seuils_ignores([1, 2]) == []
    assert entonnoir.situation(_scenario(), [], entonnoir.charger_definitions(), seuils)["seuils_ignores"] == [
        "m8_leads_recus", "m8_taux_acceptation",
    ]


def test_chaque_metrique_du_registre_a_son_calcul_et_ses_sources_et_chaque_seuil_vise_une_metrique_du_registre():
    """Le registre gouverné et le code restent d'accord : une métrique ajoutée au fichier sans calcul serait
    « non calculable, aucun calcul enregistré » (fail-closed) ; ce garde la fait échouer avant."""
    definitions = set(entonnoir.charger_definitions())

    types_requis = {t for types in entonnoir._SOURCES_REQUISES.values() for t in types}
    assert set(entonnoir._CALCULS) == definitions == set(entonnoir._SOURCES_REQUISES)
    assert definitions >= entonnoir._METRIQUES_SURVEILLEES
    assert set(entonnoir._EVENEMENT_DE_TYPE) >= types_requis


def test_la_situation_assemble_mesures_sources_seuils_et_devis_en_attente():
    situation = entonnoir.situation(_scenario(), [_wct("wct-D3", "D3")], entonnoir.charger_definitions(), {})

    assert set(situation) == {"mesures", "sources", "seuils", "seuils_ignores", "devis"}
    assert [m["metric_id"] for m in situation["mesures"]] == list(METRIQUES)
    assert len(situation["sources"]) == 5 and len(situation["seuils"]) == 4 and situation["seuils_ignores"] == []
    assert situation["devis"] == {"sans_reponse": ["D2"], "brouillons_en_retard": ["D4"]}


# ---------------------------------------------------------------------------
# Une métrique du registre sans calcul est non calculable, nommément
# ---------------------------------------------------------------------------
def test_une_metrique_du_registre_sans_calcul_est_non_calculable_nommement():
    definitions = dict(entonnoir.charger_definitions())
    definitions["m8_metrique_sans_calcul"] = {**definitions["m8_leads_recus"], "nom": "Sans calcul"}

    mesures = {m["metric_id"]: m for m in entonnoir.mesurer(_scenario(), [], definitions)}

    sans_calcul = mesures["m8_metrique_sans_calcul"]
    assert sans_calcul["statut"] == "non_calculable" and sans_calcul["valeur"] is None
    assert sans_calcul["manque"] == [
        {"champ": "calcul", "source": "M8", "raison": "aucun calcul enregistré pour cette métrique"}
    ]
    assert mesures["m8_leads_recus"]["valeur"] == "3"  # les autres ne sont pas touchées
