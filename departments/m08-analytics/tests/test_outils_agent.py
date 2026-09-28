"""Capacités d'agent de M8 : contrat des outils et chaîne de rapport composée."""

from __future__ import annotations

from pathlib import Path

from m8_analytics.outils import outils
from m8_analytics.registre import RegistreSnapshots

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer

_DEFINITION = {
    "id": "m_cpl",
    "nom": "Coût par lead",
    "definition": "Coût total marketing divisé par le nombre de leads.",
    "unite": "CAD/lead",
    "source_donnees": "module de test",
    "frequence": "mensuelle",
    "consommateur": "entrepôt M8",
}


def _dictionnaire(module_source="M-test-outils-agent"):
    return {module_source: {"m_cpl": _DEFINITION}}


def _snapshot(module_source, horodatage, valeur):
    return {"module_source": module_source, "horodatage": horodatage, "valeurs": {"m_cpl": valeur}}


def _outils_par_nom():
    """Registres EN MÉMOIRE, explicites : `outils()` sans argument adosse le registre de
    snapshots ET le registre des définitions au stockage durable de l'instance (ADR-0009),
    qu'aucun test unitaire de ce fichier ne monte — voir
    `departments/m08-analytics/tests/test_registre_durable.py` et
    `test_registre_metriques_durable.py` pour la preuve des branchements durables eux-mêmes."""
    return {o.nom: o for o in outils(RegistreSnapshots(), [])}


_DEFINITION_REGISTRE_M4 = {
    "metric_id": "m4_duree_reelle_minutes",
    "departement_proprietaire": "m04-field-ops",
    "unite": "min",
    "source": "Module M4 — WCT",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": 0, "plage_max": None},
}
# DefinitionMetrique (contrats.CHAMPS_DEFINITION_METRIQUE) correspondante, pour le paramètre
# `dictionnaire` de m8_rapport_metriques dans les tests d'intégration m8_evaluer_qualite_metrique
# ci-dessous : le même metric_id, tel qu'un metrics/*.yaml de M4 le publierait.
_DEFINITION_METRIQUE_M4 = {
    "id": "m4_duree_reelle_minutes",
    "nom": "Durée réelle",
    "definition": "Durée réelle de l'intervention, en minutes.",
    "unite": "min",
    "source_donnees": "Module M4 — WCT",
    "frequence": "à la demande",
    "consommateur": "entrepôt M8",
}


def _snapshot_m4(horodatage, valeur):
    """Comme `_snapshot` plus haut, mais avec la clé `m4_duree_reelle_minutes` (le `_snapshot`
    partagé fige la clé `m_cpl`, utilisée par les tests M8 génériques précédents)."""
    return {
        "module_source": "m04-field-ops",
        "horodatage": horodatage,
        "valeurs": {"m4_duree_reelle_minutes": valeur},
    }


def _appeler(par_nom, nom, **kwargs):
    return executer(par_nom[nom], kwargs)


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m8_rapport_metriques"
    assert all(nom.startswith("m8_") for nom in noms)
    assert {
        "m8_enregistrer_definition_metrique",
        "m8_resoudre_definition_metrique",
        "m8_evaluer_qualite_metrique",
        "m8_lister_definitions_metriques",
    }.issubset(noms)


def test_paliers_t3_1_coherents_avec_departements_md():
    """DEPARTEMENTS.md : T0 lecture/calcul pur, T1 écriture interne (registre). Seul l'outil qui
    écrit dans le registre durable des définitions est T1 ; les outils de lecture/calcul restent
    T0 (défaut de la dataclasse Outil)."""
    par_nom = _outils_par_nom()

    assert par_nom["m8_enregistrer_definition_metrique"].autonomie == Autonomie.T1
    assert par_nom["m8_resoudre_definition_metrique"].autonomie == Autonomie.T0
    assert par_nom["m8_evaluer_qualite_metrique"].autonomie == Autonomie.T0
    assert par_nom["m8_lister_definitions_metriques"].autonomie == Autonomie.T0


def test_rapport_metriques_complet_porte_provenance_et_aucun_signal_sous_le_seuil():
    par_nom = _outils_par_nom()
    module_source = "M-nominal"
    reponse = _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire=_dictionnaire(module_source),
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", "42.5"),
        metric_ids=["m_cpl"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=3,
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]
    assert resultat["etape"] == "complet" and resultat["accepte"] is True
    rapport = resultat["rapport"]
    assert rapport["metriques"][0]["metric_id"] == "m_cpl"
    assert rapport["metriques"][0]["valeur"] == 42.5
    assert rapport["metriques"][0]["n"] == 1
    # Un seul point d'historique < n_minimal=3 : le signal est DONNEES_INSUFFISANTES,
    # donc absent des signaux (m8_produire_digest_quotidien le filtrerait de toute façon).
    assert rapport["signaux"][0]["type_signal"] == "DONNEES_INSUFFISANTES"


def test_rapport_metriques_snapshot_refuse_bloque_avant_ecriture():
    par_nom = _outils_par_nom()
    module_source = "M-refuse"
    reponse = _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire=_dictionnaire(module_source),
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", 42.5),  # valeur NUMÉRIQUE
        metric_ids=["m_cpl"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=3,
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]
    assert resultat["etape"] == "validation" and resultat["accepte"] is False
    assert resultat["verdict"] == "REJ-SNAPSHOT-VALEUR-NON-TEXTE"


def test_rapport_metriques_metric_id_non_declare_est_bloque():
    par_nom = _outils_par_nom()
    module_source = "M-metric-inconnu"
    reponse = _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire=_dictionnaire(module_source),
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", "1"),
        metric_ids=["m_inconnu"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=3,
    )

    resultat = reponse["resultat"]
    assert resultat["etape"] == "definition" and resultat["accepte"] is False
    assert "m_inconnu" in resultat["verdict"]


def test_rapport_metriques_detecte_un_signal_xmr_hors_limite_apres_plusieurs_ingestions():
    par_nom = _outils_par_nom()
    module_source = "M-xmr"
    dictionnaire = _dictionnaire(module_source)
    horodatages = [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
        "2026-01-04T00:00:00Z",
        "2026-01-05T00:00:00Z",
    ]
    # Même série que test_xmr.py::test_detecter_signal_retourne_signal_limite_superieure...
    # (4 points stables puis un saut) : moyenne=18, amplitude_moyenne=10,
    # limite_haute=18+2.66*10=44.6 < 50 → HORS_LIMITE_SUPERIEURE garanti.
    valeurs = ["10", "10", "10", "10", "50"]

    for horodatage, valeur in zip(horodatages[:-1], valeurs[:-1], strict=True):
        _appeler(
            par_nom, "m8_rapport_metriques",
            dictionnaire=dictionnaire,
            snapshot=_snapshot(module_source, horodatage, valeur),
            metric_ids=["m_cpl"],
            horodatage_reference=horodatage,
            n_minimal=3,
        )

    reponse = _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire=dictionnaire,
        snapshot=_snapshot(module_source, horodatages[-1], valeurs[-1]),
        metric_ids=["m_cpl"],
        horodatage_reference=horodatages[-1],
        n_minimal=3,
    )

    signaux = reponse["resultat"]["rapport"]["signaux"]
    assert signaux and signaux[0]["type_signal"] == "HORS_LIMITE_SUPERIEURE"
    assert signaux[0]["n"] == 5


def test_rapport_metriques_role_sans_liste_est_refus_metier_via_executer():
    par_nom = _outils_par_nom()
    module_source = "M-role-refuse"

    reponse = _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire=_dictionnaire(module_source),
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", "1"),
        metric_ids=["m_cpl"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=1,
        role="terrain",
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"


def test_snapshot_avec_devise_non_cad_refuse_par_le_dictionnaire_reel_et_par_l_outil():
    """Bout en bout, contre le dépôt réel : une devise non CAD compilée par
    m8_compiler_dictionnaire ne peut ensuite jamais être ingérée pour cette métrique
    (elle est absente du dictionnaire compilé, donc traitée comme non déclarée).
    """
    depart = Path(__file__).resolve().parents[2]  # departments/
    par_nom = _outils_par_nom()

    reponse = _appeler(par_nom, "m8_compiler_dictionnaire", racine_modules=str(depart))

    assert reponse["ok"] is True
    dictionnaire_reel = reponse["resultat"]["dictionnaire"]
    metriques_m7 = dictionnaire_reel.get("M7-marketing", {})
    for metric_id, definition in metriques_m7.items():
        assert not definition["unite"].startswith("EUR/"), metric_id


def test_n_minimal_de_mauvais_type_refuse_par_le_schema():
    par_nom = _outils_par_nom()
    reponse = executer(
        par_nom["m8_detecter_signal_xmr"],
        {"metric_id": "m", "valeurs_historiques": [], "n_minimal": "trois"},
    )
    assert reponse["erreur"] == "arguments_invalides"


def test_construire_rapport_role_sans_liste_via_executer_est_refus_metier():
    par_nom = _outils_par_nom()
    reponse = executer(
        par_nom["m8_construire_rapport"],
        {"metriques": [], "signaux": [], "role": "admin", "metric_ids_autorises": None},
    )
    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"


def test_outils_partagent_le_meme_registre_entre_deux_appels():
    """Preuve de la fermeture (closure) sur registre_cible : deux outils de la même instance
    voient les écritures l'un de l'autre, comme avant le passage à l'injection."""
    registre_memoire = RegistreSnapshots()
    par_nom = {o.nom: o for o in outils(registre_memoire)}
    module_source = "M-partage"

    _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire=_dictionnaire(module_source),
        snapshot=_snapshot(module_source, "2026-01-04T00:00:00Z", "1"),
        metric_ids=["m_cpl"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=1,
    )

    assert len(registre_memoire.lire()) == 1
    assert registre_memoire.lire()[0]["module_source"] == module_source


# ---------------------------------------------------------------------------
# T3.1 : registre de métriques, qualité/fraîcheur, alertes proposées (outils m8_enregistrer_
# definition_metrique, m8_resoudre_definition_metrique, m8_evaluer_qualite_metrique).
# ---------------------------------------------------------------------------


def test_enregistrer_puis_resoudre_definition_metrique_via_executer():
    par_nom = _outils_par_nom()

    enregistree = _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)
    assert enregistree["ok"] is True
    assert enregistree["resultat"] == {"enregistree": True, "deja_a_jour": False, "verdict": None}

    resolue = _appeler(par_nom, "m8_resoudre_definition_metrique", metric_id="m4_duree_reelle_minutes")
    assert resolue["ok"] is True
    assert resolue["resultat"] == {
        "trouvee": True,
        "verdict": None,
        "definition": _DEFINITION_REGISTRE_M4,
    }


def test_enregistrer_definition_metrique_structure_invalide_via_executer():
    par_nom = _outils_par_nom()

    reponse = _appeler(
        par_nom, "m8_enregistrer_definition_metrique",
        definition={**_DEFINITION_REGISTRE_M4, "unite": "USD"},
    )

    assert reponse["ok"] is True  # refus MÉTIER nommé, jamais une exception technique
    assert reponse["resultat"]["enregistree"] is False
    assert reponse["resultat"]["verdict"].startswith("REJ-DEFINITION-DEVISE-NON-AUTORISEE:")


def test_enregistrer_definition_metrique_est_idempotent_via_executer():
    par_nom = _outils_par_nom()

    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)
    reponse = _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)

    assert reponse["resultat"] == {"enregistree": True, "deja_a_jour": True, "verdict": None}


def test_resoudre_definition_metrique_inconnue_via_executer():
    par_nom = _outils_par_nom()

    reponse = _appeler(par_nom, "m8_resoudre_definition_metrique", metric_id="jamais_enregistre")

    assert reponse["ok"] is True
    assert reponse["resultat"] == {
        "trouvee": False,
        "verdict": "REJ-DEFINITION-METRIQUE-INCONNUE:jamais_enregistre",
        "definition": None,
    }


def test_evaluer_qualite_metrique_definition_inconnue_via_executer():
    par_nom = _outils_par_nom()

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="jamais_enregistre", horodatage_reference="2026-01-04T00:00:00Z",
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]
    assert resultat["definition_trouvee"] is False
    assert resultat["verdict"] == "REJ-DEFINITION-METRIQUE-INCONNUE:jamais_enregistre"
    assert resultat["alertes_proposees"] == []


def test_evaluer_qualite_metrique_donnee_absente_propose_une_alerte_a_qui_de_droit():
    """Aucun snapshot jamais ingéré pour cette métrique : verdict nommé qui dit quoi demander
    (n=0), et une alerte PROPOSÉE au département propriétaire — jamais une valeur devinée."""
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m4_duree_reelle_minutes", horodatage_reference="2026-01-04T00:00:00Z",
    )

    resultat = reponse["resultat"]
    assert resultat["definition_trouvee"] is True
    assert resultat["n"] == 0
    assert resultat["valeur"] is None
    assert len(resultat["alertes_proposees"]) == 1
    alerte = resultat["alertes_proposees"][0]
    assert alerte["a_qui"] == "m04-field-ops"
    assert "m4_duree_reelle_minutes" in alerte["quoi"]


def test_evaluer_qualite_metrique_donnee_fraiche_et_dans_la_plage_ne_propose_aucune_alerte():
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)
    module_source = "m04-field-ops"
    _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire={module_source: {"m4_duree_reelle_minutes": _DEFINITION_METRIQUE_M4}},
        snapshot=_snapshot_m4("2026-01-04T00:00:00Z", "42"),
        metric_ids=["m4_duree_reelle_minutes"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=1,
    )

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m4_duree_reelle_minutes", horodatage_reference="2026-01-04T12:00:00Z",  # +12h < 2j
    )

    resultat = reponse["resultat"]
    assert resultat["n"] == 1
    assert resultat["valeur"] == 42.0
    assert resultat["alertes_proposees"] == []


def test_evaluer_qualite_metrique_donnee_perimee_propose_une_alerte():
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)
    module_source = "m04-field-ops"
    _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire={module_source: {"m4_duree_reelle_minutes": _DEFINITION_METRIQUE_M4}},
        snapshot=_snapshot_m4("2026-01-01T00:00:00Z", "42"),
        metric_ids=["m4_duree_reelle_minutes"],
        horodatage_reference="2026-01-01T00:00:00Z",
        n_minimal=1,
    )

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        # fraicheur_attendue_jours=2 dans _DEFINITION_REGISTRE_M4 ; ici l'écart est de 10 jours.
        metric_id="m4_duree_reelle_minutes", horodatage_reference="2026-01-11T00:00:00Z",
    )

    resultat = reponse["resultat"]
    assert resultat["fraicheur_jours"] == 10.0
    assert len(resultat["alertes_proposees"]) == 1
    alerte = resultat["alertes_proposees"][0]
    assert alerte["type_alerte"] == "REJ-QUALITE-DONNEE-PERIMEE"
    assert alerte["preuve"]["fraicheur_jours"] == 10.0


def test_evaluer_qualite_metrique_hors_plage_propose_une_alerte_sans_doublon_de_fraicheur():
    par_nom = _outils_par_nom()
    definition = {**_DEFINITION_REGISTRE_M4, "regles_qualite": {"plage_min": 0, "plage_max": 30}}
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=definition)
    module_source = "m04-field-ops"
    _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire={module_source: {"m4_duree_reelle_minutes": _DEFINITION_METRIQUE_M4}},
        snapshot=_snapshot_m4("2026-01-04T00:00:00Z", "42"),  # > plage_max=30
        metric_ids=["m4_duree_reelle_minutes"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=1,
    )

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m4_duree_reelle_minutes", horodatage_reference="2026-01-04T01:00:00Z",  # frais
    )

    resultat = reponse["resultat"]
    assert len(resultat["alertes_proposees"]) == 1  # fraîche -> pas de doublon, seule la plage manque
    assert resultat["alertes_proposees"][0]["type_alerte"] == "REJ-QUALITE-HORS-PLAGE"


def test_evaluer_qualite_metrique_perimee_et_hors_plage_propose_deux_alertes_distinctes():
    """Fraîcheur et plage sont deux dimensions indépendantes : une valeur PÉRIMÉE ET hors plage
    propose les DEUX alertes, jamais une seule au détriment de l'autre."""
    par_nom = _outils_par_nom()
    definition = {**_DEFINITION_REGISTRE_M4, "regles_qualite": {"plage_min": 0, "plage_max": 30}}
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=definition)
    module_source = "m04-field-ops"
    _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire={module_source: {"m4_duree_reelle_minutes": _DEFINITION_METRIQUE_M4}},
        snapshot=_snapshot_m4("2026-01-01T00:00:00Z", "42"),  # > plage_max=30
        metric_ids=["m4_duree_reelle_minutes"],
        horodatage_reference="2026-01-01T00:00:00Z",
        n_minimal=1,
    )

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m4_duree_reelle_minutes", horodatage_reference="2026-01-11T00:00:00Z",  # +10j > 2j
    )

    types_alertes = {a["type_alerte"] for a in reponse["resultat"]["alertes_proposees"]}
    assert types_alertes == {"REJ-QUALITE-DONNEE-PERIMEE", "REJ-QUALITE-HORS-PLAGE"}


# ---------------------------------------------------------------------------
# T3.1-suite : unicité (doublons d'observation), cohérence entre séries, listage compact paginé.
# ---------------------------------------------------------------------------


def test_evaluer_qualite_metrique_detecte_un_doublon_d_observation():
    """Deux maillons distincts pour le MÊME horodatage : une anomalie de qualité, jamais résolue
    en silence par « le dernier gagne » (semantique.deriver_metrique choisit quand même UNE
    valeur à afficher, mais qualite.evaluer_unicite signale l'ambiguïté que ce choix masque)."""
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)
    module_source = "m04-field-ops"
    for valeur in ("42", "43"):  # même horodatage, deux valeurs concurrentes
        _appeler(
            par_nom, "m8_rapport_metriques",
            dictionnaire={module_source: {"m4_duree_reelle_minutes": _DEFINITION_METRIQUE_M4}},
            snapshot=_snapshot_m4("2026-01-04T00:00:00Z", valeur),
            metric_ids=["m4_duree_reelle_minutes"],
            horodatage_reference="2026-01-04T00:00:00Z",
            n_minimal=1,
        )

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m4_duree_reelle_minutes", horodatage_reference="2026-01-04T01:00:00Z",  # frais
    )

    resultat = reponse["resultat"]
    alerte = next(a for a in resultat["alertes_proposees"] if a["type_alerte"] == "REJ-QUALITE-DOUBLON")
    assert alerte["preuve"]["horodatages_doublons"] == {"2026-01-04T00:00:00Z": 2}
    assert alerte["a_qui"] == "m04-field-ops"


def test_evaluer_qualite_metrique_sans_doublon_ne_signale_rien_a_ce_titre():
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)
    module_source = "m04-field-ops"
    _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire={module_source: {"m4_duree_reelle_minutes": _DEFINITION_METRIQUE_M4}},
        snapshot=_snapshot_m4("2026-01-04T00:00:00Z", "42"),
        metric_ids=["m4_duree_reelle_minutes"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=1,
    )

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m4_duree_reelle_minutes", horodatage_reference="2026-01-04T01:00:00Z",
    )

    types_alertes = {a["type_alerte"] for a in reponse["resultat"]["alertes_proposees"]}
    assert "REJ-QUALITE-DOUBLON" not in types_alertes


_DEFINITION_REGISTRE_M5_REVENU = {
    "metric_id": "m5_revenu_cad",
    "departement_proprietaire": "m05-financecore",
    "unite": "CAD",
    "source": "Module M5 — Finance",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": None, "plage_max": None},
}
_DEFINITION_REGISTRE_M5_COUT = {
    "metric_id": "m5_cout_cad",
    "departement_proprietaire": "m05-financecore",
    "unite": "CAD",
    "source": "Module M5 — Finance",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": None, "plage_max": None},
}
_DEFINITION_REGISTRE_M5_MARGE = {
    "metric_id": "m5_marge_cad",
    "departement_proprietaire": "m05-financecore",
    "unite": "CAD",
    "source": "Module M5 — Finance",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": None, "plage_max": None},
}


def _ingerer_m5(par_nom, metric_id, valeur, horodatage="2026-01-04T00:00:00Z"):
    _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire={"m05-financecore": {metric_id: {}}},  # définition dictionnaire vide, sans effet
        snapshot={
            "module_source": "m05-financecore", "horodatage": horodatage, "valeurs": {metric_id: valeur},
        },
        metric_ids=[metric_id],
        horodatage_reference=horodatage,
        n_minimal=1,
    )


def test_evaluer_qualite_metrique_composantes_coherentes_ne_propose_aucune_alerte_de_coherence():
    par_nom = _outils_par_nom()
    for definition in (_DEFINITION_REGISTRE_M5_REVENU, _DEFINITION_REGISTRE_M5_COUT, _DEFINITION_REGISTRE_M5_MARGE):
        _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=definition)
    _ingerer_m5(par_nom, "m5_revenu_cad", "500")
    _ingerer_m5(par_nom, "m5_cout_cad", "350")
    _ingerer_m5(par_nom, "m5_marge_cad", "150")  # 500 - 350 = 150 : cohérent

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m5_marge_cad", horodatage_reference="2026-01-04T01:00:00Z",
        composantes={"m5_revenu_cad": 1.0, "m5_cout_cad": -1.0}, tolerance_coherence=0.01,
    )

    types_alertes = {a["type_alerte"] for a in reponse["resultat"]["alertes_proposees"]}
    assert "REJ-QUALITE-INCOHERENCE" not in types_alertes


def test_evaluer_qualite_metrique_composantes_incoherentes_propose_une_alerte():
    par_nom = _outils_par_nom()
    for definition in (_DEFINITION_REGISTRE_M5_REVENU, _DEFINITION_REGISTRE_M5_COUT, _DEFINITION_REGISTRE_M5_MARGE):
        _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=definition)
    _ingerer_m5(par_nom, "m5_revenu_cad", "500")
    _ingerer_m5(par_nom, "m5_cout_cad", "350")
    _ingerer_m5(par_nom, "m5_marge_cad", "999")  # 500 - 350 = 150 ≠ 999 : incohérent

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m5_marge_cad", horodatage_reference="2026-01-04T01:00:00Z",
        composantes={"m5_revenu_cad": 1.0, "m5_cout_cad": -1.0}, tolerance_coherence=0.01,
    )

    alerte = next(
        a for a in reponse["resultat"]["alertes_proposees"] if a["type_alerte"] == "REJ-QUALITE-INCOHERENCE"
    )
    assert alerte["preuve"]["valeur"] == 999.0
    assert alerte["preuve"]["valeur_attendue"] == 150.0
    assert alerte["a_qui"] == "m05-financecore"


def test_evaluer_qualite_metrique_composante_inconnue_ignore_silencieusement_la_coherence():
    """Fail-closed « silencieux » : une composante jamais enregistrée ne peut pas être comparée,
    donc aucune alerte de cohérence n'est inventée — mais l'appel réussit quand même (jamais un
    crash pour un contrôle optionnel non concluant ; les AUTRES alertes déjà trouvées restent)."""
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)
    _appeler(
        par_nom, "m8_rapport_metriques",
        dictionnaire={"m04-field-ops": {"m4_duree_reelle_minutes": _DEFINITION_METRIQUE_M4}},
        snapshot=_snapshot_m4("2026-01-04T00:00:00Z", "42"),
        metric_ids=["m4_duree_reelle_minutes"],
        horodatage_reference="2026-01-04T00:00:00Z",
        n_minimal=1,
    )

    reponse = _appeler(
        par_nom, "m8_evaluer_qualite_metrique",
        metric_id="m4_duree_reelle_minutes", horodatage_reference="2026-01-04T01:00:00Z",
        composantes={"jamais_enregistre": 1.0}, tolerance_coherence=0.01,
    )

    assert reponse["ok"] is True
    types_alertes = {a["type_alerte"] for a in reponse["resultat"]["alertes_proposees"]}
    assert "REJ-QUALITE-INCOHERENCE" not in types_alertes


def test_evaluer_qualite_metrique_composantes_sans_tolerance_est_refus_metier():
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)

    reponse = executer(
        par_nom["m8_evaluer_qualite_metrique"],
        {
            "metric_id": "m4_duree_reelle_minutes", "horodatage_reference": "2026-01-04T00:00:00Z",
            "composantes": {"autre_metrique": 1.0},
        },
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"


def test_evaluer_qualite_metrique_tolerance_sans_composantes_est_refus_metier():
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)

    reponse = executer(
        par_nom["m8_evaluer_qualite_metrique"],
        {
            "metric_id": "m4_duree_reelle_minutes", "horodatage_reference": "2026-01-04T00:00:00Z",
            "tolerance_coherence": 0.5,
        },
    )

    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"


def test_lister_definitions_metriques_via_executer():
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)

    reponse = _appeler(par_nom, "m8_lister_definitions_metriques", limite=10)

    assert reponse["ok"] is True
    resultat = reponse["resultat"]
    assert resultat["total"] == 1
    assert resultat["definitions"] == [{
        "metric_id": "m4_duree_reelle_minutes",
        "departement_proprietaire": "m04-field-ops",
        "unite": "min",
        "fraicheur_attendue_jours": 2,
        "version": 1,
    }]
    assert resultat["curseur_suivant"] is None


def test_lister_definitions_metriques_jamais_l_historique_complet_via_executer():
    par_nom = _outils_par_nom()
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=_DEFINITION_REGISTRE_M4)
    modifiee = {**_DEFINITION_REGISTRE_M4, "fraicheur_attendue_jours": 5}
    _appeler(par_nom, "m8_enregistrer_definition_metrique", definition=modifiee)

    reponse = _appeler(par_nom, "m8_lister_definitions_metriques", limite=10)

    resultat = reponse["resultat"]
    assert resultat["total"] == 1  # une seule ligne, jamais une par version
    assert resultat["definitions"][0]["version"] == 2
    assert resultat["definitions"][0]["fraicheur_attendue_jours"] == 5


def test_lister_definitions_metriques_limite_invalide_est_un_refus_metier():
    par_nom = _outils_par_nom()

    reponse = executer(par_nom["m8_lister_definitions_metriques"], {"limite": 0})

    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"
