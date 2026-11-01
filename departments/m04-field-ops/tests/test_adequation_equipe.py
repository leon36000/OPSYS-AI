"""Indice d'adéquation équipe/intervention (M4.11) : transparent, déterministe, équitable. Module pur. Données fictives.

Les chiffres attendus sont calculés À LA MAIN en fractions exactes (voir chaque test), jamais copiés de la sortie du
code.
"""

from __future__ import annotations

import ast
import copy
import itertools
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m4_field_ops import adequation_equipe as ae  # noqa: E402
from m4_field_ops import verdicts  # noqa: E402

FICTIF = True
PARAMETRES_BRUTS = {
    "poids": {"capacite": "1", "charge": "1", "distance": "1", "qualite": "1"},
    "distance_reference_km": 50,
    "historique_minimum": 5,
}


def _parametres(**plus):
    brut = {**PARAMETRES_BRUTS, **plus}
    parametres, verdict = ae.lire_parametres(brut)
    assert verdict is None, verdict
    return parametres


def _equipe(
    identifiant, competences=("c1",), membres=2, disponibles=2400, planifiees=600, distance=10000, historique=(10, 1)
):
    e = {"equipe_id": identifiant, "competences": list(competences), "membres_declares": membres}
    if disponibles is not None:
        e["capacite"] = {"minutes_disponibles": disponibles, "minutes_planifiees": planifiees}
    if distance is not None:
        e["distance_m"] = distance
    if historique is not None:
        e["historique"] = {"terminees": historique[0], "avec_ecart": historique[1]}
    return e


def _entrees(equipes, duree=120, competences=("c1",)):
    return {
        "intervention": {
            "intervention_id": "int-1",
            "service": "service_a",
            "date": "2030-06-04",
            "duree_min": duree,
            "competences_requises": list(competences),
        },
        "equipes": equipes,
    }


def _ordre(entrees, parametres=None):
    ordre, verdict = ae.ordonner(entrees, parametres or _parametres())
    assert verdict is None, verdict
    return ordre


# ------------------------------------------------------------------------------------------ chiffres calculés à la main
def test_l_indice_est_la_moyenne_ponderee_exacte_des_sous_indices_calcules_a_la_main():
    a = _equipe("eq-a", ("c1", "c2"), membres=3, disponibles=2400, planifiees=600, distance=10000, historique=(10, 1))
    b = _equipe("eq-b", ("c1",), membres=2, disponibles=2400, planifiees=1800, distance=40000, historique=(5, 0))
    ordre = _ordre(_entrees([b, a]))
    # A : capacité (1800-120)/1800 = 14/15 ; charge 1-600/2400 = 3/4 ; distance 1-10/50 = 4/5 ; qualité 1-1/10 = 9/10
    # (56 + 45 + 48 + 54)/60 / 4 = 203/240 = 0,845833... B : capacité (600-120)/600 = 4/5 ; charge 1-1800/2400 = 1/4 ;
    # distance 1-40/50 = 1/5 ; qualité 1  -> 2,25/4 = 0,5625
    assert [x["equipe_id"] for x in ordre["ordre"]] == ["eq-a", "eq-b"]
    assert [x["adequation"] for x in ordre["ordre"]] == ["0.8458", "0.5625"]
    assert [x["rang"] for x in ordre["ordre"]] == [1, 2] and ordre["criteres_actifs"] == list(ae.CRITERES)
    detail = {c["critere"]: c for c in ordre["ordre"][0]["criteres"]}
    assert detail["capacite"]["sous_indice"] == "0.9333" and detail["charge"]["sous_indice"] == "0.7500"
    assert detail["distance"]["sous_indice"] == "0.8000" and detail["qualite"]["sous_indice"] == "0.9000"
    assert all(c["poids_effectif"] == "0.2500" and c["actif"] for c in detail.values())
    assert sum(Decimal(c["contribution"]) for c in detail.values()) - Decimal("0.8458") < Decimal("0.0002")


def test_les_poids_declares_inegaux_pesent_exactement_comme_declare():
    a = _equipe("eq-a", disponibles=2400, planifiees=600, distance=10000)
    parametres = _parametres(poids={"capacite": "1", "charge": "3", "distance": "0", "qualite": "0"})
    ordre = _ordre(_entrees([a]), parametres)
    # (1 x 14/15 + 3 x 3/4) / 4 = (56/60 + 135/60) / 4 = 191/240 = 0,795833
    assert ordre["ordre"][0]["adequation"] == "0.7958"
    assert ordre["criteres_actifs"] == ["capacite", "charge"]
    assert {e["critere"] for e in ordre["criteres_ecartes"]} == {"distance", "qualite"}


def test_chaque_critere_ecarte_pour_donnee_manquante_l_est_pour_toutes_les_equipes():
    a = _equipe("eq-a", historique=(10, 1))
    b = _equipe("eq-b", historique=None)  # pas d'historique : la qualité n'est comparable pour personne
    ordre = _ordre(_entrees([a, b]))
    assert "qualite" not in ordre["criteres_actifs"]
    assert any(e["critere"] == "qualite" and "eq-b" in e["raison"] for e in ordre["criteres_ecartes"])
    for ligne in ordre["ordre"]:
        actifs = {c["critere"]: c["poids_effectif"] for c in ligne["criteres"] if c["actif"]}
        assert set(actifs) == {"capacite", "charge", "distance"} and set(actifs.values()) == {"0.3333"}


def test_un_historique_trop_court_ou_une_equipe_d_une_seule_personne_n_est_jamais_notee():
    seule = _equipe("eq-a", membres=1, historique=(50, 25))  # moitié d'écarts : ne doit rien changer
    autre = _equipe("eq-b", membres=4, historique=(50, 0))
    ordre = _ordre(_entrees([seule, autre]))
    assert "qualite" not in ordre["criteres_actifs"]
    courte = _equipe("eq-c", historique=(4, 4))  # sous historique_minimum (5)
    ordre = _ordre(_entrees([courte, _equipe("eq-d", historique=(50, 0))]))
    assert "qualite" not in ordre["criteres_actifs"]
    detail = next(c for c in ordre["ordre"][0]["criteres"] if c["critere"] == "qualite")
    assert detail["sous_indice"] is None and detail["valeur"] == "non utilisable"


# ------------------------------------------------------------------------------------------ contraintes
def test_competence_manquante_capacite_insuffisante_et_inconnue_sont_dites_pas_classees():
    bonne = _equipe("eq-ok")
    sans_comp = _equipe("eq-c", competences=("c9",))
    pleine = _equipe("eq-e", disponibles=300, planifiees=240)  # 60 min libres pour 120
    inconnue = _equipe("eq-d", disponibles=None)
    ordre = _ordre(_entrees([bonne, sans_comp, pleine, inconnue]))
    assert [x["equipe_id"] for x in ordre["ordre"]] == ["eq-ok"]
    par_id = {x["equipe_id"]: x for x in ordre["exclues"]}
    assert par_id["eq-c"]["motifs"] == ["competence_manquante"] and "c1" in par_id["eq-c"]["detail"]
    assert par_id["eq-e"]["motifs"] == ["capacite_insuffisante"] and "60 min libres" in par_id["eq-e"]["detail"]
    assert ordre["non_evaluables"][0]["equipe_id"] == "eq-d" and "inconnue" in ordre["non_evaluables"][0]["detail"]


def test_aucune_equipe_admissible_rend_un_ordre_vide_qui_le_dit_sans_inventer():
    ordre = _ordre(_entrees([_equipe("eq-c", competences=("c9",))]))
    assert ordre["ordre"] == [] and ordre["motif_vide"] == "aucune équipe admissible" and ordre["decision"] == "humain"


def test_capacite_exactement_egale_a_la_duree_est_admise_et_une_minute_de_moins_exclue():
    juste = _ordre(_entrees([_equipe("eq-a", disponibles=720, planifiees=600)]))  # 120 libres pour 120
    assert [x["equipe_id"] for x in juste["ordre"]] == ["eq-a"]
    detail = next(c for c in juste["ordre"][0]["criteres"] if c["critere"] == "capacite")
    assert detail["sous_indice"] == "0.0000"  # plus aucune marge
    moins = _ordre(_entrees([_equipe("eq-a", disponibles=719, planifiees=600)]))
    assert moins["ordre"] == [] and moins["exclues"][0]["motifs"] == ["capacite_insuffisante"]


def test_la_distance_au_dela_de_la_reference_vaut_zero_et_a_zero_metre_vaut_un():
    ordre = _ordre(
        _entrees([_equipe("eq-loin", distance=900000), _equipe("eq-pres", distance=0)]),
        _parametres(poids={"distance": "1"}),
    )
    sous = {
        x["equipe_id"]: next(c for c in x["criteres"] if c["critere"] == "distance")["sous_indice"]
        for x in ordre["ordre"]
    }
    assert sous == {"eq-loin": "0.0000", "eq-pres": "1.0000"}


# ------------------------------------------------------------------------------------------ déterminisme, équité
def test_l_ordre_d_entree_et_les_noms_d_equipes_ne_changent_aucun_indice():
    equipes = [
        _equipe("eq-a", distance=5000),
        _equipe("eq-b", distance=20000, planifiees=1200),
        _equipe("eq-c", distance=30000, planifiees=100, historique=(8, 2)),
    ]
    reference = {x["equipe_id"]: x["adequation"] for x in _ordre(_entrees(equipes))["ordre"]}
    for permutation in itertools.permutations(equipes):
        obtenu = {x["equipe_id"]: x["adequation"] for x in _ordre(_entrees(list(permutation)))["ordre"]}
        assert obtenu == reference
    renommees = [{**e, "equipe_id": f"zz-{i}"} for i, e in enumerate(equipes)]
    nouveau = [x["adequation"] for x in _ordre(_entrees(renommees))["ordre"]]
    assert sorted(nouveau) == sorted(reference.values())  # mêmes indices, quel que soit le nom


def test_resultat_identique_a_chaque_appel_et_aucune_mutation_des_entrees():
    entrees = _entrees([_equipe("eq-a"), _equipe("eq-b", planifiees=900)])
    avant = copy.deepcopy(entrees)
    premier, second = _ordre(entrees), _ordre(entrees)
    assert premier == second and entrees == avant and len(premier["empreinte"]) == 64


def test_les_ex_aequo_sont_signales_et_departages_seulement_par_l_identifiant():
    ordre = _ordre(_entrees([_equipe("eq-b"), _equipe("eq-a"), _equipe("eq-c", planifiees=1200)]))
    lignes = ordre["ordre"]
    assert [x["equipe_id"] for x in lignes] == ["eq-a", "eq-b", "eq-c"]
    assert [(x["rang"], x["ex_aequo"]) for x in lignes] == [(1, True), (1, True), (3, False)]
    assert "sans signification" in ordre["departage"]


PROTEGES = [
    "age",
    "age_moyen",
    "sexe",
    "genre",
    "identite_de_genre",
    "orientation_sexuelle",
    "origine_ethnique",
    "race",
    "couleur",
    "religion",
    "langue_maternelle",
    "etat_civil",
    "grossesse",
    "handicap",
    "etat_de_sante",
    "sante",
    "convictions_politiques",
    "appartenance_syndicale",
    "casier_judiciaire",
    "situation_familiale",
    "enfants",
    "salaire",
    "nationalite",
    "date_de_naissance",
    "photo",
    "nom",
    "prenom",
    "membres",
    "nom_employe",
    "technicien_id",
    "ÂGE",
    "Origine-Ethnique",
]


@pytest.mark.parametrize("cle", PROTEGES)
def test_un_attribut_personnel_protege_ou_une_personne_est_refuse_avant_tout_calcul(cle):
    for place in ("equipe", "capacite", "historique", "intervention", "racine"):
        entrees = _entrees([_equipe("eq-a"), _equipe("eq-b")])
        if place == "equipe":
            entrees["equipes"][0][cle] = "valeur"
        elif place == "capacite":
            entrees["equipes"][0]["capacite"][cle] = 1
        elif place == "historique":
            entrees["equipes"][0]["historique"][cle] = 1
        elif place == "intervention":
            entrees["intervention"][cle] = "x"
        else:
            entrees["equipes"].append({cle: [1]})
        ordre, verdict = ae.ordonner(entrees, _parametres())
        assert ordre is None and verdict["code"] == "REJ-ADEQUATION-ATTRIBUT-INTERDIT", (cle, place)
        assert verdicts.est_verdict(verdict["code"])


def test_un_champ_inconnu_non_protege_est_refuse_par_la_liste_fermee():
    entrees = _entrees([_equipe("eq-a")])
    entrees["equipes"][0]["couleur_du_camion_preferee"] = 1
    # « couleur » est un jeton protégé
    assert ae.ordonner(entrees, _parametres())[1]["code"] == "REJ-ADEQUATION-ATTRIBUT-INTERDIT"
    entrees = _entrees([_equipe("eq-a")])
    entrees["equipes"][0]["camion_prefere"] = 1
    assert ae.ordonner(entrees, _parametres())[1]["code"] == "REJ-ADEQUATION-ENTREE-INVALIDE"


def test_pas_de_faux_positif_sur_les_champs_legitimes_et_les_mots_proches():
    entrees = _entrees([_equipe("eq-a")])
    ae_ = ae._chercher_interdit
    assert ae_(entrees) is None
    for cle in ("page", "image", "message", "manage", "membres_declares", "distance_m", "competences", "historique"):
        assert ae_({cle: 1}) is None, cle


def test_la_sortie_ne_contient_aucun_nom_de_membre_ni_attribut_personnel():
    ordre = _ordre(_entrees([_equipe("eq-a", membres=7)]))
    texte = str(ordre).lower()
    for mot in ("sexe", "âge", "religion", "origine", "handicap", "santé"):
        assert mot not in texte, mot
    assert "membre" not in texte and "7 membres" not in texte  # le nombre de membres déclarés ne sort pas


def test_la_mise_en_garde_dit_que_ce_n_est_pas_une_note_de_personne():
    ordre = _ordre(_entrees([_equipe("eq-a")]))
    assert "ne note aucune personne" in ordre["mise_en_garde"] and "sanction" in ordre["mise_en_garde"]
    assert ordre["decision"] == "humain" and "L'humain affecte" in ordre["mise_en_garde"]


# ------------------------------------------------------------------------------------------ explication
def test_l_explication_est_une_phrase_fixe_construite_des_chiffres_du_calcul():
    ordre = _ordre(_entrees([_equipe("eq-a", ("c1", "c2"), 3, 2400, 600, 10000, (10, 1))]))
    phrase = ordre["ordre"][0]["explication"]
    assert phrase.startswith("Équipe eq-a : adéquation 0.8458 pour cette intervention ; ")
    assert "1680 min libres après le chantier sur 1800" in phrase
    assert "600 min planifiées sur 2400" in phrase and "10000 m du dépôt (référence 50000 m)" in phrase
    assert "1 écart(s) sur 10 chantiers terminés" in phrase and phrase.endswith(".")


# ------------------------------------------------------------------------------------------ paramètres
@pytest.mark.parametrize(
    "brut",
    [
        None,
        {},
        {"poids": {}, "distance_reference_km": 50, "historique_minimum": 5},
        {"poids": {"capacite": "0"}, "distance_reference_km": 50, "historique_minimum": 5},
        {"poids": {"capacite": "1"}, "distance_reference_km": 0, "historique_minimum": 5},
        {"poids": {"capacite": "1"}, "distance_reference_km": 50, "historique_minimum": 0},
        {"poids": {"capacite": 1}, "distance_reference_km": 50, "historique_minimum": 5},
        {"poids": {"capacite": "-1"}, "distance_reference_km": 50, "historique_minimum": 5},
        {"poids": {"capacite": "1", "inconnu": "1"}, "distance_reference_km": 50, "historique_minimum": 5},
        {"poids": {"capacite": "1"}, "distance_reference_km": 50, "historique_minimum": 5, "intrus": 1},
        {"poids": {"capacite": "1"}, "distance_reference_km": "50", "historique_minimum": 5},
        {"poids": {"capacite": None}, "distance_reference_km": 50, "historique_minimum": 5},
    ],
)
def test_sans_parametres_declares_ou_invalides_aucun_ordre_n_est_donne(brut):
    parametres, verdict = ae.lire_parametres(brut)
    assert parametres is None and verdict["code"] == "REJ-ADEQUATION-PARAMETRES-ABSENTS"
    assert "poids" in verdict["detail"] or "paramètres" in verdict["detail"]


def test_aucun_critere_pondere_avec_donnee_complete_est_un_refus_qui_dit_pourquoi():
    parametres = _parametres(poids={"qualite": "1"})
    ordre, verdict = ae.ordonner(_entrees([_equipe("eq-a", historique=None), _equipe("eq-b")]), parametres)
    assert ordre is None and verdict["code"] == "REJ-ADEQUATION-PARAMETRES-ABSENTS" and "qualite" in verdict["detail"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e["intervention"].update(duree_min=0),
        lambda e: e["intervention"].update(date="2030-6-4"),
        lambda e: e["intervention"].update(service="Service A"),
        lambda e: e["intervention"].pop("service"),
        lambda e: e["equipes"].clear(),
        lambda e: e["equipes"].append(copy.deepcopy(e["equipes"][0])),  # identifiant répété
        lambda e: e["equipes"][0].update(membres_declares=-1),
        lambda e: e["equipes"][0].update(membres_declares=True),
        lambda e: e["equipes"][0].update(distance_m=-5),
        lambda e: e["equipes"][0].update(distance_m=1.5),
        lambda e: e["equipes"][0]["capacite"].update(minutes_disponibles=-1),
        lambda e: e["equipes"][0]["historique"].update(avec_ecart=99),
        lambda e: e["equipes"][0].update(competences="c1"),
        lambda e: e.update(extra=1),
        lambda e: e.pop("equipes"),
    ],
)
def test_entrees_malformees_refusees_sans_exception(mutation):
    entrees = _entrees([_equipe("eq-a")])
    mutation(entrees)
    ordre, verdict = ae.ordonner(entrees, _parametres())
    assert ordre is None and verdict["code"] in ("REJ-ADEQUATION-ENTREE-INVALIDE", "REJ-ADEQUATION-ATTRIBUT-INTERDIT")


def test_les_entrees_non_objet_sont_refusees():
    for entrees in (None, "x", [], 5):
        assert ae.ordonner(entrees, _parametres())[1]["code"] == "REJ-ADEQUATION-ENTREE-INVALIDE"


# ------------------------------------------------------------------------------------------ calibration
def _cas(choix, equipes, fictif=True):
    return {"fictif": fictif, "entrees": _entrees(equipes), "choix_humain": choix}


def _equipes_a_choix_par_distance():
    # Même capacité et charge : seule la distance les distingue.
    return [_equipe("eq-a", distance=5000), _equipe("eq-b", distance=30000), _equipe("eq-c", distance=45000)]


def test_la_calibration_retrouve_le_poids_qui_explique_des_choix_humains_fictifs():
    # Le répartiteur fictif choisit toujours l'équipe la plus proche, même quand une autre est moins chargée.
    cas = []
    for i in range(6):
        proche = _equipe(f"eq-p{i}", distance=3000 + 1000 * i, disponibles=2400, planifiees=1800)  # chargée mais proche
        loin = _equipe(f"eq-l{i}", distance=40000 + 500 * i, disponibles=2400, planifiees=300)  # libre mais loin
        cas.append(_cas(f"eq-p{i}", [proche, loin]))
    rapport, verdict = ae.calibrer_poids(cas, {"distance_reference_km": 50, "historique_minimum": 5}, pas=5)
    assert verdict is None and rapport["fictif"] is True
    assert rapport["accord"] == {"reussis": 6, "cas": 6, "ratio": "1.0000"}
    assert Decimal(rapport["poids"]["distance"]) > Decimal(rapport["poids"]["charge"])
    assert rapport["grille"] == {"pas": 5, "vecteurs_evalues": 56}  # compositions de 5 en 4 parts : C(8, 3)
    assert "décision de l'entreprise" in rapport["limite"]


def test_la_calibration_est_deterministe_et_prefere_les_poids_les_plus_uniformes_a_accord_egal():
    cas = [_cas("eq-a", [_equipe("eq-a"), _equipe("eq-b", planifiees=1500)])]  # eq-a meilleure sur tous les critères
    a = ae.calibrer_poids(cas, {"distance_reference_km": 50, "historique_minimum": 5}, pas=4)[0]
    b = ae.calibrer_poids(cas, {"distance_reference_km": 50, "historique_minimum": 5}, pas=4)[0]
    assert a == b and a["accord"]["reussis"] == 1
    assert a["poids"] == {"capacite": "0.25", "charge": "0.25", "distance": "0.25", "qualite": "0.25"}


def test_la_calibration_refuse_toute_donnee_non_declaree_fictive():
    cas = [_cas("eq-a", [_equipe("eq-a")], fictif=False)]
    rapport, verdict = ae.calibrer_poids(cas, {"distance_reference_km": 50, "historique_minimum": 5})
    assert rapport is None and verdict["code"] == "REJ-ADEQUATION-DONNEES-REELLES-REFUSEES"
    sans_flag = [{"entrees": _entrees([_equipe("eq-a")]), "choix_humain": "eq-a"}]
    assert (
        ae.calibrer_poids(sans_flag, {"distance_reference_km": 50, "historique_minimum": 5})[1]["code"]
        == "REJ-ADEQUATION-ENTREE-INVALIDE"
    )


@pytest.mark.parametrize(
    "cas",
    [
        [],
        "x",
        [{"fictif": True, "entrees": {}, "choix_humain": "eq-a"}],
        [{"fictif": True, "entrees": _entrees([_equipe("eq-a")]), "choix_humain": "eq-inconnue"}],
    ],
)
def test_calibration_entrees_invalides(cas):
    assert ae.calibrer_poids(cas, {"distance_reference_km": 50, "historique_minimum": 5})[1] is not None
    assert (
        ae.calibrer_poids(
            [_cas("eq-a", [_equipe("eq-a")])], {"distance_reference_km": 50, "historique_minimum": 5}, pas=0
        )[1]["code"]
        == "REJ-ADEQUATION-ENTREE-INVALIDE"
    )


def test_la_calibration_rejette_un_attribut_protege_cache_dans_un_cas():
    equipe = _equipe("eq-a")
    equipe["age_moyen"] = 40
    verdict = ae.calibrer_poids([_cas("eq-a", [equipe])], {"distance_reference_km": 50, "historique_minimum": 5})[1]
    assert verdict["code"] == "REJ-ADEQUATION-ATTRIBUT-INTERDIT"


# ------------------------------------------------------------------------------------------ pureté du module
def test_le_module_est_pur_sans_opsys_ni_horloge_ni_reseau_ni_alea():
    arbre = ast.parse((_SRC / "m4_field_ops" / "adequation_equipe.py").read_text(encoding="utf-8"))
    importes = {n.names[0].name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import)}
    importes |= {
        (n.module or "").split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.level == 0
    }
    assert not importes & {"opsys", "random", "time", "datetime", "socket", "urllib", "http", "secrets", "uuid", "os"}
