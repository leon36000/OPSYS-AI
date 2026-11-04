"""Batterie de questions-tests « non-oubli » (M10-05) : corpus fictif, rappel/précision/couverture,
suppression d'un fait, sources absentes, documents interdits et fuite de texte.

Les faits du scénario de bout en bout sont semés avec les vrais outils d'écriture de M10 (amont, WCT,
variance, rentabilité) dans les registres réels en mémoire. Aucune donnée réelle, aucun réseau.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from m10_memoire import amont, batterie, registre, rentabilite, transferts, variance, wct

RACINE = Path(__file__).resolve().parents[1]
BATTERIE = RACINE / "evals" / "non-oubli.v1.yaml"
HORODATAGE = "2026-11-02T09:00:00-05:00"
WCT_HORODATAGE = "2026-11-05T16:00:00-05:00"


# ---------------------------------------------------------------------------------------------------------------
# Corpus de test minimal (les faits sont des clés de registre, jamais des textes)
# ---------------------------------------------------------------------------------------------------------------
def _mini(**overrides):
    corpus = {
        "schema": batterie.SCHEMA_BATTERIE,
        "fictif": True,
        "version": "test-v1",
        "auteur": "test fictif",
        "entreprise": "Entreprise fictive de test",
        "documents": [{"id": "DOC-A", "domaine": "affaires", "texte": "Texte fictif du document A."}],
        "faits": [
            {
                "id": "F-A",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m1.lead_qualifie",
                "identifiant": "A-FICTIF-1",
                "sources": ["DOC-A"],
            }
        ],
        "questions": [
            {
                "id": "Q-A",
                "texte": "Quel lead fictif a été qualifié ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m1.lead_qualifie"],
                "attendus": ["F-A"],
            }
        ],
    }
    corpus.update(copy.deepcopy(overrides))
    return corpus


def _corpus():
    return yaml.safe_load(BATTERIE.read_text(encoding="utf-8"))


def _inventaire(corpus=None):
    """Inventaire EXPLICITE du magasin fictif : les documents voulus présents, jamais présumés."""
    return [document["id"] for document in (corpus or _corpus())["documents"]]


def _lead(registre_cible, lead_id="A-FICTIF-1", service="gouttieres", horodatage=HORODATAGE):
    resultat, verdict = amont.memoriser(
        "m1.lead_qualifie",
        {
            "lead": {
                "lead_id": lead_id,
                "service": service,
                "canal": "texte",
                "urgence_declaree": False,
            },
            "horodatage": horodatage,
        },
        registre_cible,
    )
    assert verdict is None and resultat is not None
    return resultat["maillon"]


def _wct(registre_cible, wct_id="WCT-FICTIF-1", lead_id="A-FICTIF-1"):
    resultat, verdict = wct.memoriser_wct(
        {
            "wct_id": wct_id,
            "intervention_id": f"INT-{wct_id}",
            "lead_id": lead_id,
            "technicien_id": "TECH-FICTIF-1",
            "horodatage_completion": WCT_HORODATAGE,
            "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
            "duree_reelle_minutes": 90,
            "ecart_signale": False,
            "revue_id": None,
            "hash_maillon": "a" * 64,
            "consommateurs_cibles": ["M10"],
            "devis_id": f"DEV-{wct_id}",
        },
        registre_cible,
    )
    assert verdict is None and resultat is not None
    return resultat


def _scenario_complet():
    """Deux affaires fictives, semées par les outils réels : sept faits attendus + le compagnon FINANCIAL."""
    evenements = registre.Registre()
    affaires = registre.Registre()
    _lead(evenements, "A-FICTIF-001", "gouttieres", "2026-11-02T09:00:00-05:00")
    _lead(evenements, "A-FICTIF-002", "revetement", "2026-11-02T10:00:00-05:00")

    resultat, verdict = amont.memoriser(
        "m2.client_associe",
        {
            "lead_id": "A-FICTIF-001",
            "client_id": "CLI-FICTIF-001",
            "horodatage_association": "2026-11-02T11:00:00-05:00",
        },
        evenements,
    )
    assert verdict is None and resultat is not None

    resultat, verdict = amont.memoriser(
        "m3.devis_accepte",
        {
            "lead_id": "A-FICTIF-001",
            "devis_id": "D-FICTIF-001",
            "chantier_id": "CH-FICTIF-001",
            "horodatage_acceptation": "2026-11-03T13:00:00-05:00",
            "prix_total": "1200.00",
            "cout_total": "1000.00",
            "taux_marge": "0.20",
        },
        evenements,
    )
    assert verdict is None and resultat is not None

    resultat, verdict = amont.memoriser(
        "m3.devis_sans_reponse",
        {
            "lead_id": "A-FICTIF-002",
            "devis_id": "D-FICTIF-002",
            "chantier_id": None,
            "statut": "envoye",
            "horodatage_devis": "2026-11-03T14:00:00-05:00",
            "delai_relance_jours": 7,
            "horodatage_reference": "2026-11-10T14:00:00-05:00",
        },
        evenements,
    )
    assert verdict is None and resultat is not None

    _wct(evenements, "WCT-FICTIF-001", "A-FICTIF-001")

    resultat, verdict = variance.memoriser_variance(
        {
            "evenement_id": "VAR-FICTIF-001",
            "wct_id": "WCT-FICTIF-001",
            "intervention_id": "INT-WCT-FICTIF-001",
            "chantier_id": "CH-FICTIF-001",
            "statut_variance": "evaluee",
            "signal_critique": False,
            "seuil_pourcentage": 0.1,
            "horodatage_completion": WCT_HORODATAGE,
            "lignes": [],
        },
        evenements,
    )
    assert verdict is None and resultat is not None

    resultat, verdict = rentabilite.memoriser_rentabilite(
        {
            "evenement_id": "RENT-FICTIF-001",
            "devis_id": "D-FICTIF-001",
            "chantier_id": "CH-FICTIF-001",
            "wct_id": "WCT-FICTIF-001",
            "sequence": 1,
            "version_entrees": "b" * 64,
            "horodatage_completion": WCT_HORODATAGE,
            "verdict": "CALCULEE",
            "devise": "CAD",
            "prix_definitif": True,
            "cout_reel_complet": True,
            "cout_reel_cad": "1000.00",
            "cout_connu_cad": "1000.00",
            "marge_reelle_cad": "200.00",
            "marge_prevue_cad": "180.00",
            "ecart_marge_cad": "20.00",
            "taux_marge_reelle": "0.1667",
            "taux_marge_prevue": "0.1500",
            "prix_facture_cad": "1200.00",
            "manque": [],
        },
        evenements,
    )
    assert verdict is None and resultat is not None
    return evenements, affaires


# ---------------------------------------------------------------------------------------------------------------
# 1. La batterie livrée
# ---------------------------------------------------------------------------------------------------------------
def test_la_batterie_livree_est_fictive_complete_et_valide():
    corpus = _corpus()
    valide = batterie.valider_batterie(corpus)
    assert valide == corpus
    assert valide["fictif"] is True
    assert len(valide["documents"]) == 8
    assert len(valide["faits"]) == 8
    assert len(valide["questions"]) == 6
    assert {f["affaire_id"] for f in valide["faits"]} == {"A-FICTIF-001", "A-FICTIF-002"}
    assert {q["affaire_id"] for q in valide["questions"]} == {"A-FICTIF-001", "A-FICTIF-002"}
    assert batterie.empreinte_batterie(valide) == batterie.empreinte_batterie(corpus)
    assert len(batterie.empreinte_batterie(valide)) == 64


def test_la_batterie_livree_ne_contient_aucun_texte_dans_les_faits_ni_les_questions():
    corpus = _corpus()
    for fait in corpus["faits"]:
        assert set(fait) == {"id", "affaire_id", "type_evenement", "identifiant", "sources"}
        assert all(isinstance(source, str) for source in fait["sources"])
    for question in corpus["questions"]:
        assert set(question) == {"id", "texte", "affaire_id", "types_evenement", "attendus"}


# ---------------------------------------------------------------------------------------------------------------
# 2. Refus de forme : un corpus faux n'évalue rien
# ---------------------------------------------------------------------------------------------------------------
def _refus(corpus, code):
    with pytest.raises(batterie.BatterieInvalide) as erreur:
        batterie.valider_batterie(corpus)
    assert erreur.value.code == code
    return erreur.value


def test_un_corpus_non_fictif_ou_un_champ_inconnu_est_refuse():
    _refus(_mini(fictif=False), "REJ-BATTERIE-FICTIF")
    corpus = _mini()
    corpus["champ_inconnu"] = True
    _refus(corpus, "REJ-BATTERIE-CHAMP-INCONNU")
    corpus = _mini()
    corpus["faits"][0]["texte"] = "un fait n'est pas un texte"
    _refus(corpus, "REJ-BATTERIE-CHAMP-INCONNU")


def test_un_identifiant_duplique_une_source_inconnue_ou_un_fait_duplique_sont_refuses():
    corpus = _mini()
    corpus["documents"].append({"id": "DOC-A", "domaine": "affaires", "texte": "doublon"})
    _refus(corpus, "REJ-BATTERIE-DOUBLON")

    corpus = _mini()
    corpus["faits"][0]["sources"] = ["DOC-INCONNU"]
    _refus(corpus, "REJ-BATTERIE-SOURCE-INCONNUE")

    corpus = _mini()
    corpus["faits"].append(copy.deepcopy(corpus["faits"][0]))
    _refus(corpus, "REJ-BATTERIE-DOUBLON")

    corpus = _mini()
    corpus["faits"].append(
        {
            "id": "F-B",
            "affaire_id": "A-FICTIF-1",
            "type_evenement": "m1.lead_qualifie",
            "identifiant": "A-FICTIF-1",
            "sources": ["DOC-A"],
        }
    )
    _refus(corpus, "REJ-BATTERIE-DOUBLON")

    corpus = _mini()
    corpus["faits"][0]["sources"] = ["DOC-A", "DOC-A"]
    _refus(corpus, "REJ-BATTERIE-DOUBLON")


def test_les_liens_question_fait_sont_verifies_avant_toute_mesure():
    corpus = _mini()
    corpus["questions"][0]["attendus"] = ["F-INCONNU"]
    _refus(corpus, "REJ-BATTERIE-FAIT-INCONNU")

    corpus = _mini()
    corpus["questions"][0]["interdits"] = ["F-INCONNU"]
    _refus(corpus, "REJ-BATTERIE-FAIT-INCONNU")

    corpus = _mini()
    corpus["questions"][0]["interdits"] = ["F-A"]
    _refus(corpus, "REJ-BATTERIE-QUESTION-INCOHERENTE")

    corpus = _mini()
    corpus["faits"][0]["affaire_id"] = "A-FICTIF-2"
    _refus(corpus, "REJ-BATTERIE-QUESTION-INCOHERENTE")

    corpus = _mini()
    corpus["questions"][0]["types_evenement"] = ["m4.travaux_termines"]
    _refus(corpus, "REJ-BATTERIE-QUESTION-INCOHERENTE")

    corpus = _mini()
    corpus["questions"][0]["types_evenement"] = ["m4.travaux_termines", "m4.travaux_termines"]
    _refus(corpus, "REJ-BATTERIE-QUESTION-INCOHERENTE")

    corpus = _mini()
    corpus["questions"][0]["types_evenement"] = []
    _refus(corpus, "REJ-BATTERIE-QUESTION-INCOHERENTE")

    corpus = _mini()
    corpus["questions"][0]["types_evenement"] = ["m9.type_inconnu"]
    _refus(corpus, "REJ-BATTERIE-QUESTION-INCOHERENTE")

    corpus = _mini()
    corpus["faits"][0]["affaire_id"] = "affaire forgee"
    _refus(corpus, "REJ-BATTERIE-FORME")


def test_une_batterie_vide_ou_hors_bornes_est_refusee():
    corpus = _mini()
    corpus["questions"] = []
    _refus(corpus, "REJ-BATTERIE-VIDE")

    corpus = _mini()
    corpus["documents"] = [
        {"id": f"DOC-{i}", "domaine": "affaires", "texte": "x"} for i in range(batterie.MAX_DOCUMENTS + 1)
    ]
    _refus(corpus, "REJ-BATTERIE-BORNE")

    corpus = _mini()
    corpus["questions"] = [
        {
            "id": f"Q-{i}",
            "texte": "question",
            "affaire_id": "A-FICTIF-1",
            "types_evenement": ["m1.lead_qualifie"],
            "attendus": ["F-A"],
        }
        for i in range(batterie.MAX_QUESTIONS + 1)
    ]
    _refus(corpus, "REJ-BATTERIE-BORNE")

    corpus = _mini()
    corpus["documents"][0]["texte"] = "x" * (batterie.MAX_TEXTE_DOCUMENT + 1)
    _refus(corpus, "REJ-BATTERIE-BORNE")

    corpus = _mini()
    corpus["questions"][0]["texte"] = "x" * (batterie.MAX_TEXTE_QUESTION + 1)
    _refus(corpus, "REJ-BATTERIE-BORNE")

    corpus = _mini()
    corpus["faits"][0]["sources"] = [f"DOC-{i}" for i in range(batterie.MAX_SOURCES_PAR_FAIT + 1)]
    corpus["documents"] = [
        {"id": f"DOC-{i}", "domaine": "affaires", "texte": "x"}
        for i in range(batterie.MAX_SOURCES_PAR_FAIT + 1)
    ]
    _refus(corpus, "REJ-BATTERIE-BORNE")


# ---------------------------------------------------------------------------------------------------------------
# 3. Scénario de bout en bout : mémoire intacte
# ---------------------------------------------------------------------------------------------------------------
def test_le_scenario_fictif_complet_donne_rappel_et_precision_parfaits_et_couverture_complete():
    evenements, affaires = _scenario_complet()
    rapport = batterie.evaluer_batterie(_corpus(), evenements.lire(), affaires.lire(), _inventaire())

    assert rapport["mode_sources"] == batterie.MODE_SOURCES_INVENTAIRE_EXPLICITE
    assert rapport["rappel"]["evaluable"] is True
    assert rapport["rappel"]["numerateur"] == rapport["rappel"]["denominateur"] == 11
    assert rapport["rappel"]["valeur"] == 1.0
    assert rapport["precision"]["evaluable"] is True
    assert rapport["precision"]["valeur"] == 1.0
    assert rapport["couverture"]["valeur_pct"] == 100.0
    assert rapport["couverture_sources"]["valeur"] == 1.0
    assert rapport["non_evaluables"] == []
    assert rapport["manquants"] == []
    assert rapport["sources_absentes"] == []
    assert rapport["fuites"] == []
    assert rapport["nb_questions"] == 6
    assert [q["id"] for q in rapport["par_question"]] == [
        "Q-LEAD-001",
        "Q-CLIENT-001",
        "Q-ENTENTE-001",
        "Q-TRAVAUX-001",
        "Q-MARGE-001",
        "Q-DEVIS-002",
    ]
    # le rapport cite les sources attendues, jamais leur texte
    q_marge = next(q for q in rapport["par_question"] if q["id"] == "Q-MARGE-001")
    assert q_marge["sources"] == ["DOC-MARGE-001", "DOC-TRAVAUX-001", "DOC-VARIANCE-001"]
    assert all("texte" not in question for question in rapport["par_question"])


def test_une_suppression_de_fait_est_detectee_et_reduit_le_rappel():
    evenements, affaires = registre.Registre(), registre.Registre()
    _lead(evenements)
    resultat, verdict = amont.memoriser(
        "m3.devis_accepte",
        {
            "lead_id": "A-FICTIF-001",
            "devis_id": "D-FICTIF-001",
            "chantier_id": "CH-FICTIF-001",
            "horodatage_acceptation": "2026-11-03T13:00:00-05:00",
            "prix_total": "1200.00",
            "cout_total": "1000.00",
            "taux_marge": "0.20",
        },
        evenements,
    )
    assert verdict is None and resultat is not None
    # Le WCT est absent : la variance et la rentabilité qui le citent ne sont plus rattachables à l'affaire.
    variance.memoriser_variance(
        {
            "evenement_id": "VAR-FICTIF-001",
            "wct_id": "WCT-FICTIF-001",
            "intervention_id": "INT-WCT-FICTIF-001",
            "chantier_id": "CH-FICTIF-001",
            "statut_variance": "evaluee",
            "signal_critique": False,
            "seuil_pourcentage": 0.1,
            "horodatage_completion": WCT_HORODATAGE,
            "lignes": [],
        },
        evenements,
    )
    rapport = batterie.evaluer_batterie(_corpus(), evenements.lire(), affaires.lire(), _inventaire())

    assert rapport["rappel"]["evaluable"] is True
    assert rapport["rappel"]["numerateur"] < rapport["rappel"]["denominateur"]
    assert rapport["rappel"]["valeur"] < 1.0
    assert any(manquant["fait"] == "F-WCT-001" for manquant in rapport["manquants"])
    q_travaux = next(q for q in rapport["par_question"] if q["id"] == "Q-TRAVAUX-001")
    assert q_travaux["rappel"]["valeur"] == 0.0
    assert q_travaux["trouves"] == []


def test_un_registre_vide_donne_un_rappel_nul_et_une_precision_non_evaluable_pas_un_zero_invente():
    rapport = batterie.evaluer_batterie(_corpus(), [], [], _inventaire())

    assert rapport["mode_sources"] == batterie.MODE_SOURCES_INVENTAIRE_EXPLICITE
    assert rapport["rappel"]["evaluable"] is True
    assert rapport["rappel"]["valeur"] == 0.0
    assert rapport["rappel"]["numerateur"] == 0
    assert rapport["rappel"]["denominateur"] == 11
    assert rapport["precision"]["evaluable"] is False
    assert "raison" in rapport["precision"]
    assert rapport["couverture"]["valeur_pct"] == 100.0
    assert rapport["couverture_sources"]["valeur"] == 1.0
    assert len(rapport["manquants"]) == 11


def test_un_transfert_m10_02_reel_n_altere_pas_les_metriques_du_corpus_sans_rapport():
    corpus = _mini()
    sans_transfert = registre.Registre()
    _lead(sans_transfert, lead_id="A-FICTIF-1")
    rapport_sans_transfert = batterie.evaluer_batterie(
        corpus, sans_transfert.lire(), [], ["DOC-A"]
    )

    avec_transfert = registre.Registre()
    _lead(avec_transfert, lead_id="A-FICTIF-1")
    transfert_id = "tr-" + "a" * 20
    resultat, verdict = transferts.memoriser(
        transferts.TYPE_TRANSFERT_OUVERT,
        {
            "evenement_id": f"m1-transfert-ouvert-{transfert_id}",
            "transfert_id": transfert_id,
            "conversation_id": "pseudo-fictif-evaluation",
            "lead_id": "A-FICTIF-1",
            "type_transfert": "ventes",
            "categories": ["insatisfaction"],
            "niveau": "N4",
            "canal": "sms",
            "declenche_par": "regles",
            "horodatage": HORODATAGE,
        },
        avec_transfert,
    )
    assert verdict is None and resultat is not None and resultat["ecrit"] is True
    assert resultat["maillon"] in avec_transfert.lire()

    rapport_avec_transfert = batterie.evaluer_batterie(
        corpus, avec_transfert.lire(), [], ["DOC-A"]
    )

    # Le nouvel événement est classifiable et rattaché au lead, mais le corpus ne pose aucune
    # question sur lui : rappel, précision, couverture et chaque question doivent donc rester stables.
    assert rapport_avec_transfert == rapport_sans_transfert


# ---------------------------------------------------------------------------------------------------------------
# 4. Sources absentes, non-évaluables, documents interdits et fuite de texte
# ---------------------------------------------------------------------------------------------------------------
def test_l_absence_d_inventaire_est_dite_non_evaluable_et_ne_pretend_pas_connaitre_les_sources():
    evenements, affaires = _scenario_complet()
    rapport = batterie.evaluer_batterie(_corpus(), evenements.lire(), affaires.lire())

    assert rapport["mode_sources"] == "inventaire_absent"
    assert rapport["couverture_sources"] == {
        "evaluable": False,
        "raison": "AUCUN_INVENTAIRE_SOURCES",
    }
    assert rapport["sources_absentes"] == []
    assert rapport["rappel"]["valeur"] == 1.0
    assert rapport["precision"]["valeur"] == 1.0
    for question in rapport["par_question"]:
        assert question["couverture_sources"] == {
            "evaluable": False,
            "raison": "AUCUN_INVENTAIRE_SOURCES",
        }
        assert question["sources_presentes"] == []
        assert question["sources_absentes"] == []

    # Le cas exact reproduit par l'architecte : corpus livré, aucun maillon, aucun inventaire.
    sans_maillon = batterie.evaluer_batterie(_corpus(), [], [])
    assert sans_maillon["rappel"] == {
        "evaluable": True,
        "numerateur": 0,
        "denominateur": 11,
        "valeur": 0.0,
        "valeur_pct": 0.0,
    }
    assert sans_maillon["precision"] == {
        "evaluable": False,
        "raison": batterie.RAISON_AUCUN_FAIT_RETOURNE,
    }
    assert sans_maillon["couverture_sources"] == {
        "evaluable": False,
        "raison": batterie.RAISON_AUCUN_INVENTAIRE_SOURCES,
    }
    assert sans_maillon["sources_absentes"] == []


def test_un_inventaire_explicite_vide_est_un_zero_connu_et_les_faits_restent_evalues():
    evenements, affaires = _scenario_complet()
    rapport = batterie.evaluer_batterie(_corpus(), evenements.lire(), affaires.lire(), [])

    assert rapport["mode_sources"] == batterie.MODE_SOURCES_INVENTAIRE_EXPLICITE
    assert rapport["couverture_sources"] == {
        "evaluable": True,
        "numerateur": 0,
        "denominateur": 11,
        "valeur": 0.0,
        "valeur_pct": 0.0,
    }
    # Le rappel et la précision ne dépendent pas du magasin de sources : ils restent parfaits.
    assert rapport["rappel"]["valeur"] == 1.0
    assert rapport["precision"]["valeur"] == 1.0
    assert len(rapport["sources_absentes"]) == 11
    for question in rapport["par_question"]:
        assert question["couverture_sources"]["evaluable"] is True
        assert question["couverture_sources"]["numerateur"] == 0
        assert question["couverture_sources"]["denominateur"] == len(question["sources"])
        assert question["sources_presentes"] == []
        assert len(question["sources_absentes"]) == len(question["sources"])


def test_une_source_absente_reduit_la_couverture_des_sources_sans_faire_disparaitre_le_fait():
    evenements, affaires = _scenario_complet()
    disponibles = {doc["id"] for doc in _corpus()["documents"]} - {"DOC-MARGE-001"}
    rapport = batterie.evaluer_batterie(_corpus(), evenements.lire(), affaires.lire(), disponibles)

    assert rapport["rappel"]["valeur"] == 1.0
    assert rapport["couverture_sources"]["evaluable"] is True
    assert rapport["couverture_sources"]["numerateur"] == 10
    assert rapport["couverture_sources"]["denominateur"] == 11
    assert rapport["couverture_sources"]["valeur"] == pytest.approx(10 / 11, abs=1e-4)
    assert rapport["sources_absentes"] == [{"question": "Q-MARGE-001", "fait": "F-RENT-001", "source": "DOC-MARGE-001"}]
    q_marge = next(q for q in rapport["par_question"] if q["id"] == "Q-MARGE-001")
    assert q_marge["sources_presentes"] == ["DOC-TRAVAUX-001", "DOC-VARIANCE-001"]
    assert q_marge["couverture_sources"] == {
        "evaluable": True,
        "numerateur": 2,
        "denominateur": 3,
        "valeur": 0.6667,
        "valeur_pct": 66.7,
    }


def test_une_question_sans_fait_attendu_est_non_evaluable_et_n_entre_pas_au_denominateur():
    corpus = _mini()
    corpus["questions"].append(
        {
            "id": "Q-VIDE",
            "texte": "Que sait-on de l'affaire sans fait déclaré ?",
            "affaire_id": "A-FICTIF-1",
            "types_evenement": ["m1.lead_qualifie"],
            "attendus": [],
        }
    )
    evenements = registre.Registre()
    _lead(evenements, "A-FICTIF-1")
    rapport = batterie.evaluer_batterie(corpus, evenements.lire(), [], _inventaire(corpus))

    q_vide = next(q for q in rapport["par_question"] if q["id"] == "Q-VIDE")
    assert q_vide["evaluable"] is False
    assert q_vide["raison"] == batterie.RAISON_AUCUN_FAIT_ATTENDU
    assert rapport["couverture"]["numerateur"] == 1 and rapport["couverture"]["denominateur"] == 2
    assert rapport["couverture"]["valeur_pct"] == 50.0
    assert rapport["rappel"]["numerateur"] == rapport["rappel"]["denominateur"] == 1
    assert rapport["non_evaluables"] == [{"question": "Q-VIDE", "raison": batterie.RAISON_AUCUN_FAIT_ATTENDU}]


def test_un_fait_source_d_un_document_de_developpement_est_non_evaluable_jamais_compte_comme_memoire_d_affaires():
    corpus = _mini(
        documents=[
            {"id": "DOC-A", "domaine": "affaires", "texte": "Texte fictif du document A."},
            {"id": "DOC-DEV", "domaine": "developpement", "texte": "FUITE-DEVELOPPEMENT-INTERDITE"},
        ],
        faits=[
            {
                "id": "F-DEV",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m1.lead_qualifie",
                "identifiant": "A-FICTIF-1",
                "sources": ["DOC-DEV"],
            }
        ],
        questions=[
            {
                "id": "Q-DEV",
                "texte": "Que dit la note de développement ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m1.lead_qualifie"],
                "attendus": ["F-DEV"],
            }
        ],
    )
    evenements = registre.Registre()
    _lead(evenements, "A-FICTIF-1")
    rapport = batterie.evaluer_batterie(corpus, evenements.lire(), [], _inventaire(corpus))

    q = rapport["par_question"][0]
    assert q["evaluable"] is False
    assert q["raison"] == batterie.RAISON_SOURCE_HORS_DOMAINE
    assert rapport["rappel"]["evaluable"] is False
    assert "raison" in rapport["rappel"]
    assert rapport["couverture"]["valeur_pct"] == 0.0
    assert rapport["fuites"] == [{"question": "Q-DEV", "fait": "F-DEV", "motif": batterie.MOTIF_SOURCE_HORS_DOMAINE}]
    assert "FUITE-DEVELOPPEMENT-INTERDITE" not in json.dumps(rapport, ensure_ascii=False)


def test_un_fait_interdit_retourne_baisse_la_precision_et_ne_laisse_passer_aucun_texte():
    corpus = _mini(
        documents=[
            {"id": "DOC-A", "domaine": "affaires", "texte": "Texte fictif du document A."},
            {"id": "DOC-DEV", "domaine": "developpement", "texte": "FUITE-SECRETE-DU-DEVELOPPEMENT"},
        ],
        faits=[
            {
                "id": "F-OK",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m4.travaux_termines",
                "identifiant": "WCT-OK",
                "sources": ["DOC-A"],
            },
            {
                "id": "F-FUITE",
                "affaire_id": "A-FICTIF-1",
                "type_evenement": "m4.travaux_termines",
                "identifiant": "WCT-FUITE",
                "sources": ["DOC-DEV"],
            },
        ],
        questions=[
            {
                "id": "Q-FUITE",
                "texte": "Quels travaux terminés appartiennent à l'affaire ?",
                "affaire_id": "A-FICTIF-1",
                "types_evenement": ["m4.travaux_termines"],
                "attendus": ["F-OK"],
                "interdits": ["F-FUITE"],
            }
        ],
    )
    evenements = registre.Registre()
    _wct(evenements, "WCT-OK", "A-FICTIF-1")
    _wct(evenements, "WCT-FUITE", "A-FICTIF-1")
    rapport = batterie.evaluer_batterie(corpus, evenements.lire(), [], _inventaire(corpus))

    q = rapport["par_question"][0]
    assert q["evaluable"] is True
    assert q["retournes"] == 2
    assert q["precision"]["numerateur"] == 1 and q["precision"]["denominateur"] == 2
    assert q["precision"]["valeur"] == 0.5
    assert rapport["fuites"] == [
        {"question": "Q-FUITE", "fait": "F-FUITE", "motif": batterie.MOTIF_SOURCE_HORS_DOMAINE}
    ]
    assert "FUITE-SECRETE-DU-DEVELOPPEMENT" not in json.dumps(rapport, ensure_ascii=False)


def test_un_document_disponible_inconnu_est_refuse_avant_toute_mesure():
    with pytest.raises(batterie.BatterieInvalide) as erreur:
        batterie.evaluer_batterie(_mini(), [], [], {"DOC-INCONNU"})
    assert erreur.value.code == "REJ-BATTERIE-DOCUMENT-INCONNU"


# ---------------------------------------------------------------------------------------------------------------
# 5. Idempotence, ordre et bornes de calcul
# ---------------------------------------------------------------------------------------------------------------
def test_le_rapport_est_idempotent_et_independant_de_l_ordre_du_registre():
    evenements, affaires = _scenario_complet()
    avant = len(evenements.lire())
    premier = batterie.evaluer_batterie(_corpus(), evenements.lire(), affaires.lire(), _inventaire())
    second = batterie.evaluer_batterie(_corpus(), evenements.lire(), affaires.lire(), _inventaire())
    assert premier == second
    assert len(evenements.lire()) == avant

    inverse = batterie.evaluer_batterie(
        _corpus(), list(reversed(evenements.lire())), affaires.lire(), _inventaire()
    )
    assert inverse == premier


def test_les_faits_hors_du_scope_ne_sont_jamais_retournes_et_ne_sont_pas_une_fuite():
    corpus = _mini()
    evenements = registre.Registre()
    _lead(evenements, "A-FICTIF-1")
    _lead(evenements, "A-FICTIF-2")  # autre affaire
    rapport = batterie.evaluer_batterie(corpus, evenements.lire(), [], _inventaire(corpus))

    q = rapport["par_question"][0]
    assert q["retournes"] == 1
    assert rapport["fuites"] == []
    assert rapport["rappel"]["valeur"] == 1.0


def test_les_bornes_exactes_sont_acceptees_et_les_sources_vides_refusees():
    corpus = _mini(version="v" * batterie.MAX_VERSION)
    corpus["documents"][0]["texte"] = "x" * batterie.MAX_TEXTE_DOCUMENT
    corpus["questions"][0]["texte"] = "x" * batterie.MAX_TEXTE_QUESTION
    batterie.valider_batterie(corpus)

    corpus = _mini()
    corpus["documents"] = [{"id": "DOC-A", "domaine": "affaires", "texte": "x"}] + [
        {"id": f"DOC-{i}", "domaine": "affaires", "texte": "x"} for i in range(batterie.MAX_DOCUMENTS - 1)
    ]
    batterie.valider_batterie(corpus)

    corpus = _mini()
    corpus["questions"] = [
        {
            "id": f"Q-{i}",
            "texte": "question",
            "affaire_id": "A-FICTIF-1",
            "types_evenement": ["m1.lead_qualifie"],
            "attendus": ["F-A"],
        }
        for i in range(batterie.MAX_QUESTIONS)
    ]
    batterie.valider_batterie(corpus)

    corpus = _mini()
    corpus["faits"] = [
        {
            "id": "F-A" if i == 0 else f"F-{i}",
            "affaire_id": "A-FICTIF-1",
            "type_evenement": "m1.lead_qualifie",
            "identifiant": "A-FICTIF-1" if i == 0 else f"A-FICTIF-{i + 1}",
            "sources": ["DOC-A"],
        }
        for i in range(batterie.MAX_FAITS)
    ]
    batterie.valider_batterie(corpus)

    corpus = _mini()
    corpus["documents"] = [
        {"id": f"DOC-{i}", "domaine": "affaires", "texte": "x"}
        for i in range(batterie.MAX_SOURCES_PAR_FAIT)
    ]
    corpus["faits"][0]["sources"] = [f"DOC-{i}" for i in range(batterie.MAX_SOURCES_PAR_FAIT)]
    batterie.valider_batterie(corpus)

    corpus = _mini()
    corpus["faits"][0]["sources"] = []
    _refus(corpus, "REJ-BATTERIE-FORME")


def test_les_entrees_non_textuelles_ou_non_iterables_sont_refusees():
    with pytest.raises(batterie.BatterieInvalide) as erreur:
        batterie.evaluer_batterie(_mini(), [], [], {1})
    assert erreur.value.code == "REJ-BATTERIE-FORME"

    with pytest.raises(batterie.BatterieInvalide) as erreur:
        batterie.evaluer_batterie(_mini(), "pas une sequence", [])
    assert erreur.value.code == "REJ-BATTERIE-FORME"

    with pytest.raises(batterie.BatterieInvalide) as erreur:
        batterie.evaluer_batterie(_mini(), [], "pas une sequence")
    assert erreur.value.code == "REJ-BATTERIE-FORME"


def test_une_question_dupliquee_ou_un_fait_interdit_hors_scope_sont_refuses():
    corpus = _mini()
    corpus["questions"].append(copy.deepcopy(corpus["questions"][0]))
    _refus(corpus, "REJ-BATTERIE-DOUBLON")

    corpus = _mini()
    corpus["faits"].append(
        {
            "id": "F-B",
            "affaire_id": "A-FICTIF-1",
            "type_evenement": "m4.travaux_termines",
            "identifiant": "WCT-FICTIF-9",
            "sources": ["DOC-A"],
        }
    )
    corpus["questions"][0]["interdits"] = ["F-B"]
    _refus(corpus, "REJ-BATTERIE-QUESTION-INCOHERENTE")


def test_les_bornes_publiques_sont_les_valeurs_documentees_et_les_champs_non_textuels_sont_refuses():
    assert (
        batterie.MAX_DOCUMENTS,
        batterie.MAX_FAITS,
        batterie.MAX_QUESTIONS,
        batterie.MAX_SOURCES_PAR_FAIT,
        batterie.MAX_TEXTE_DOCUMENT,
        batterie.MAX_TEXTE_QUESTION,
        batterie.MAX_VERSION,
        batterie.MAX_AUTEUR,
        batterie.MAX_ENTREPRISE,
        batterie.MAX_DESCRIPTION,
    ) == (200, 500, 100, 10, 2000, 1000, 64, 160, 200, 1000)

    for champ, valeur in [("version", 3), ("auteur", None), ("entreprise", [])]:
        corpus = _mini()
        corpus[champ] = valeur
        _refus(corpus, "REJ-BATTERIE-FORME")
    for champ in ("version", "auteur", "entreprise"):
        corpus = _mini()
        corpus[champ] = "   "
        _refus(corpus, "REJ-BATTERIE-FORME")
    corpus = _mini()
    corpus["questions"][0]["texte"] = 3
    _refus(corpus, "REJ-BATTERIE-FORME")
    corpus = _mini()
    corpus["questions"][0]["texte"] = "   "
    _refus(corpus, "REJ-BATTERIE-FORME")
    corpus = _mini()
    corpus["documents"][0]["texte"] = "   "
    _refus(corpus, "REJ-BATTERIE-FORME")
    corpus = _mini()
    corpus["faits"][0]["id"] = 3
    _refus(corpus, "REJ-BATTERIE-FORME")


def test_l_empreinte_est_canonique_et_ne_depend_pas_de_l_ordre_des_cles():
    corpus = _mini()
    inverse = dict(reversed(list(corpus.items())))
    assert batterie.empreinte_batterie(corpus) == batterie.empreinte_batterie(inverse)
    # empreinte de référence : le JSON canonique trie les clés et garde l'accent de « qualifié ».
    assert batterie.empreinte_batterie(corpus) == (
        "3b4805ed2f9bdb7c1f42d6e90b7e90ffde2b7010a4f9f84b24d9693769bd995e"
    )


def test_un_document_disponible_textuel_est_refuse():
    with pytest.raises(batterie.BatterieInvalide) as erreur:
        batterie.evaluer_batterie(_mini(), [], [], "DOC-A")
    assert erreur.value.code == "REJ-BATTERIE-FORME"


def test_un_evenement_de_la_portee_sans_fait_declare_est_dit_non_reference():
    corpus = _mini()
    corpus["questions"][0]["types_evenement"] = ["m1.lead_qualifie", "m2.client_associe"]
    evenements = registre.Registre()
    _lead(evenements, "A-FICTIF-1")
    resultat, verdict = amont.memoriser(
        "m2.client_associe",
        {
            "lead_id": "A-FICTIF-1",
            "client_id": "CLI-FICTIF-1",
            "horodatage_association": "2026-11-02T11:00:00-05:00",
        },
        evenements,
    )
    assert verdict is None and resultat is not None
    rapport = batterie.evaluer_batterie(corpus, evenements.lire(), [], _inventaire(corpus))
    q = rapport["par_question"][0]
    assert q["retournes"] == 2
    assert q["retournes_non_references"] == ["m2.client_associe:A-FICTIF-1"]
    assert q["precision"]["numerateur"] == 1 and q["precision"]["denominateur"] == 2


def test_les_metriques_d_une_question_non_evaluable_sont_toutes_non_evaluables_et_le_rapport_reste_fictif():
    corpus = _mini()
    corpus["questions"].append(
        {
            "id": "Q-VIDE",
            "texte": "Question sans fait attendu.",
            "affaire_id": "A-FICTIF-1",
            "types_evenement": ["m1.lead_qualifie"],
            "attendus": [],
        }
    )
    rapport = batterie.evaluer_batterie(corpus, [], [], _inventaire(corpus))
    assert rapport["fictif"] is True
    q_vide = next(q for q in rapport["par_question"] if q["id"] == "Q-VIDE")
    assert q_vide["evaluable"] is False
    assert q_vide["rappel"] == {"evaluable": False, "raison": batterie.RAISON_AUCUN_FAIT_ATTENDU}
    assert q_vide["precision"] == {"evaluable": False, "raison": batterie.RAISON_AUCUN_FAIT_ATTENDU}
    assert q_vide["couverture_sources"] == {"evaluable": False, "raison": batterie.RAISON_AUCUN_FAIT_ATTENDU}


def test_les_valeurs_sont_arrondies_a_quatre_decimales_et_a_un_dixieme_de_pourcent():
    mesure = batterie._mesure(1, 3, non_evaluable="JAMAIS")
    assert mesure == {
        "evaluable": True,
        "numerateur": 1,
        "denominateur": 3,
        "valeur": 0.3333,
        "valeur_pct": 33.3,
    }
