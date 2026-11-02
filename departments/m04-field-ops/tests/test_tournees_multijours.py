"""Chantiers de PLUSIEURS VISITES dans le solveur de tournées (P4-02), repli exact.

Tout est fictif (`fictif: true`) : sites de Repentigny à Joliette aux coordonnées approximatives, équipes, quarts et
fenêtres inventés. Le moteur testé est le repli exact (programmation dynamique) : PyVRP n'est pas installé sur cette
machine et ne résout de toute façon pas ces chantiers (refus nommé, testé). La preuve d'optimalité vient d'un ORACLE
indépendant écrit dans ce fichier : une énumération exhaustive de toutes les affectations et de tous les ordres.
"""

from __future__ import annotations

import copy
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from m4_field_ops import distances, encodage, tournees

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tournees_repentigny_joliette.json"
FIXTURE = json.loads(_FIXTURE.read_text(encoding="utf-8"))
SITES = {site["id"]: site for site in FIXTURE["sites"]}
PARAMS_DISTANCE = FIXTURE["parametres_distance"]
PARAMS = {"graine": 7, "iterations": 500, "cout_non_cedule_m": 60000}
JOURS = (0, 1, 2, 3)


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------
def _matrice(identifiants):
    points = [
        {"id": i, "latitude_microdeg": SITES[i]["latitude_microdeg"],
         "longitude_microdeg": SITES[i]["longitude_microdeg"]}
        for i in sorted(identifiants)
    ]
    matrice, verdict = distances.matrice_palier0(points, PARAMS_DISTANCE)
    assert verdict is None
    return matrice


def _equipe(identifiant, jours=JOURS, competences=(), depot="depot-repentigny", debut=480, fin=1020):
    return {
        "id": identifiant, "competences": list(competences), "depot": depot,
        "quarts": [{"jour": jour, "debut_min": debut, "fin_min": fin} for jour in jours],
    }


def _simple(identifiant, duree=90, jours=JOURS, debut=480, fin=1020, competences=(), urgence=0, fige=None):
    return {
        "id": identifiant, "duree_min": duree,
        "fenetre": {"jours": list(jours), "debut_min": debut, "fin_min": fin},
        "competences_requises": list(competences), "urgence": urgence, "creneau_fige": fige,
    }


def _multi(identifiant, visites, consecutifs=False, jours=JOURS, debut=480, fin=1020, competences=(), urgence=0):
    return {
        "id": identifiant, "duree_min": sum(visites), "visites": list(visites),
        "continuite": {"equipe": "unique", "jours_consecutifs": consecutifs},
        "fenetre": {"jours": list(jours), "debut_min": debut, "fin_min": fin},
        "competences_requises": list(competences), "urgence": urgence, "creneau_fige": None,
    }


def _entree(equipes, chantiers, parametres=None):
    identifiants = {e["depot"] for e in equipes} | {c["id"] for c in chantiers}
    return {
        "version": tournees.VERSION_ENTREE, "equipes": copy.deepcopy(equipes), "chantiers": copy.deepcopy(chantiers),
        "matrice": _matrice(identifiants), "parametres": dict(PARAMS if parametres is None else parametres),
    }


def _resoudre(entree, moteur="dp"):
    sortie, verdict = tournees.resoudre(entree, moteur)
    assert verdict is None, verdict
    return sortie


def _accepte(entree, sortie):
    ok, violations = tournees.verifier_plan(entree, sortie)
    assert ok, violations


def _resigner(sortie):
    sortie["meta"].pop("empreinte_sortie", None)
    sortie["meta"]["empreinte_sortie"] = encodage.empreinte(sortie)
    return sortie


def _refuse(entree, sortie, morceau):
    ok, violations = tournees.verifier_plan(entree, sortie)
    assert not ok
    assert any(morceau in violation for violation in violations), violations


def _visites_de(sortie, chantier):
    """``[(équipe, jour, début, fin, rang)]`` des visites d'un chantier, dans l'ordre des visites."""
    trouvees = []
    for route in sortie["plan"]:
        for visite in route["visites"]:
            if visite["chantier"] == chantier:
                trouvees.append((route["equipe"], route["jour"], visite["debut_min"], visite["fin_min"],
                                 visite.get("visite")))
    return sorted(trouvees, key=lambda t: (t[4] or 0, t[1]))


def _non_cedulees(sortie):
    return {ligne["chantier"]: ligne for ligne in sortie["non_cedulees"]}


# ---------------------------------------------------------------------------
# Oracle : énumération exhaustive, indépendante du solveur
# ---------------------------------------------------------------------------
def _oracle(entree):
    """Coût total minimal (mètres + coût de non-cédule) par énumération de TOUTES les affectations possibles."""
    matrice = entree["matrice"]
    place = {identifiant: rang for rang, identifiant in enumerate(matrice["ids"])}
    trajet = [[-(-secondes // 60) for secondes in ligne] for ligne in matrice["secondes"]]
    metres = matrice["metres"]
    cout_param = entree["parametres"]["cout_non_cedule_m"]
    vehicules = sorted(
        (equipe["id"], quart["jour"], quart["debut_min"], quart["fin_min"], place[equipe["depot"]],
         frozenset(equipe["competences"]))
        for equipe in entree["equipes"] for quart in equipe["quarts"]
    )
    jours_activite = sorted({v[1] for v in vehicules})
    unites = {}   # identifiant d'unité -> (lieu, durée, fenêtre, compétences)
    elements = []  # ("s", id) ou ("g", id, [unités], consécutifs)
    for chantier in entree["chantiers"]:
        fenetre = chantier["fenetre"]
        competences = frozenset(chantier["competences_requises"])
        if "visites" in chantier:
            noms = []
            for rang, duree in enumerate(chantier["visites"]):
                nom = f"{chantier['id']}@{rang}"
                unites[nom] = (place[chantier["id"]], duree, fenetre, competences)
                noms.append(nom)
            elements.append(("g", chantier["id"], noms, chantier["continuite"]["jours_consecutifs"],
                             cout_param * (1 + chantier["urgence"])))
        else:
            unites[chantier["id"]] = (place[chantier["id"]], chantier["duree_min"], fenetre, competences)
            elements.append(("s", chantier["id"], [chantier["id"]], False, cout_param * (1 + chantier["urgence"])))
    memo = {}

    def cout_route(k, ordre):
        _equipe_id, _jour, debut_quart, fin_quart, depot, _comp = vehicules[k]
        libre, position, total = debut_quart, depot, 0
        for nom in ordre:
            lieu, duree, fenetre, _c = unites[nom]
            debut = max(libre + trajet[position][lieu], fenetre["debut_min"])
            if debut > fenetre["fin_min"] - duree:
                return None
            total += metres[position][lieu]
            libre, position = debut + duree, lieu
        if libre + trajet[position][depot] > fin_quart:
            return None
        return total + metres[position][depot]

    def meilleure_route(k, ensemble):
        cle = (k, ensemble)
        if cle not in memo:
            meilleur = None
            for ordre in itertools.permutations(sorted(ensemble)):
                cout = cout_route(k, ordre)
                if cout is not None and (meilleur is None or cout < meilleur):
                    meilleur = cout
            memo[cle] = meilleur
        return memo[cle]

    def admissible(k, nom):
        _e, jour, _d, _f, _dep, comp = vehicules[k]
        _lieu, _duree, fenetre, requises = unites[nom]
        return jour in fenetre["jours"] and requises <= comp

    def options(element):
        genre, _id, noms, consecutifs, _cout = element
        if genre == "s":
            return [None] + [(k,) for k in range(len(vehicules)) if admissible(k, noms[0])]
        resultats = [None]
        for equipe in sorted({v[0] for v in vehicules}):
            ks = [k for k, v in enumerate(vehicules) if v[0] == equipe]
            for combinaison in itertools.combinations(sorted(ks, key=lambda k: vehicules[k][1]), len(noms)):
                if not all(admissible(k, nom) for k, nom in zip(combinaison, noms, strict=True)):
                    continue
                jours = [vehicules[k][1] for k in combinaison]
                if consecutifs and any(
                    jours_activite.index(b) != jours_activite.index(a) + 1
                    for a, b in zip(jours, jours[1:], strict=False)
                ):
                    continue
                resultats.append(combinaison)
        return resultats

    meilleur = None
    for choix in itertools.product(*[options(element) for element in elements]):
        par_vehicule = {}
        cout_absents = 0
        for element, placement in zip(elements, choix, strict=True):
            if placement is None:
                cout_absents += element[4]
                continue
            for nom, k in zip(element[2], placement, strict=True):
                par_vehicule.setdefault(k, set()).add(nom)
        total = cout_absents
        faisable = True
        for k, ensemble in par_vehicule.items():
            cout = meilleure_route(k, frozenset(ensemble))
            if cout is None:
                faisable = False
                break
            total += cout
        if faisable and (meilleur is None or total < meilleur):
            meilleur = total
    return meilleur


# ---------------------------------------------------------------------------
# 1. Un chantier de plusieurs visites : même équipe, jours distincts et croissants
# ---------------------------------------------------------------------------
def test_un_chantier_de_trois_visites_tient_sur_trois_journees_de_la_meme_equipe():
    entree = _entree([_equipe("eq-a"), _equipe("eq-b")], [_multi("ch-01", [420, 420, 300]), _simple("ch-02", 60)])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    visites = _visites_de(sortie, "ch-01")
    assert [v[4] for v in visites] == [1, 2, 3]
    assert len({v[0] for v in visites}) == 1                      # une seule équipe
    jours = [v[1] for v in visites]
    assert jours == sorted(set(jours)) and len(jours) == 3        # jours distincts et croissants
    assert [v[3] - v[2] for v in visites] == [420, 420, 300]      # chaque visite garde sa durée, jamais arrondie
    assert all(visite["visites_total"] == 3 for route in sortie["plan"] for visite in route["visites"]
               if visite["chantier"] == "ch-01")
    assert "ch-01" not in _non_cedulees(sortie)
    assert sortie["totaux"]["chantiers_cedules"] == 2


def test_la_somme_des_visites_est_la_duree_du_chantier():
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [400, 300])])
    sortie = _resoudre(entree)
    assert sum(v[3] - v[2] for v in _visites_de(sortie, "ch-01")) == 700


def test_un_chantier_sans_visites_donne_les_memes_octets_qu_avant():
    entree = _entree([_equipe("eq-a")], [_simple("ch-01", 120), _simple("ch-02", 90)])
    sortie = _resoudre(entree)
    assert all("visite" not in v for r in sortie["plan"] for v in r["visites"])
    assert set(sortie["totaux"]) == {
        "distance_m", "cout_non_cedule_m", "cout_total_m", "chantiers_cedules", "chantiers_non_cedules"}


# ---------------------------------------------------------------------------
# 2. Optimalité : égalité avec l'énumération exhaustive
# ---------------------------------------------------------------------------
CONFIGURATIONS = {
    "base": ([_equipe("eq-a"), _equipe("eq-b")],
             [_multi("ch-01", [420, 420, 300]), _simple("ch-02", 120), _simple("ch-03", 90), _simple("ch-04", 60)]),
    "deux_groupes": ([_equipe("eq-a"), _equipe("eq-b")],
                     [_multi("ch-01", [400, 400]), _multi("ch-04", [300, 300]), _simple("ch-03", 90)]),
    "absence_equipe_a_le_jour_1": ([_equipe("eq-a", jours=(0, 2, 3)), _equipe("eq-b")],
                                   [_multi("ch-01", [420, 420, 300], consecutifs=True), _simple("ch-02", 200)]),
    "ferie_jour_2_consecutifs": ([_equipe("eq-a", jours=(0, 1, 3)), _equipe("eq-b", jours=(0, 1, 3))],
                                 [_multi("ch-01", [420, 420, 300], consecutifs=True), _simple("ch-02", 200)]),
    "journees_serrees": ([_equipe("eq-a", jours=(0, 1))],
                         [_multi("ch-01", [450, 450]), _simple("ch-02", 400), _simple("ch-03", 300)]),
    "competence_rare": ([_equipe("eq-a", competences=["toiture"]), _equipe("eq-b")],
                        [_multi("ch-01", [420, 420], competences=["toiture"]), _simple("ch-02", 200),
                         _simple("ch-03", 120)]),
    "urgence": ([_equipe("eq-a", jours=(0, 1))],
                [_multi("ch-01", [450, 450], urgence=3), _simple("ch-14", 450), _simple("ch-02", 100)]),
    "figé": ([_equipe("eq-a", jours=(0, 1, 2)), _equipe("eq-b", jours=(0, 1, 2))],
             [_multi("ch-01", [420, 420]),
              _simple("ch-02", 120, fige={"equipe": "eq-a", "jour": 0, "debut_min": 600}), _simple("ch-03", 90)]),
}


@pytest.mark.parametrize("nom", sorted(CONFIGURATIONS))
def test_le_solveur_egale_l_enumeration_exhaustive(nom):
    equipes, chantiers = CONFIGURATIONS[nom]
    entree = _entree(equipes, chantiers)
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    optimum = _oracle(entree)
    assert optimum is not None
    assert sortie["totaux"]["cout_total_m"] == optimum


def test_le_solveur_egale_l_oracle_sur_des_cas_aux_quarts_et_fenetres_varies():
    """Quelques variantes de plus : fenêtre du client plus étroite, quarts courts, durées inégales."""
    cas = [
        ([_equipe("eq-a", fin=900), _equipe("eq-b", jours=(1, 2, 3))],
         [_multi("ch-01", [300, 400], jours=(0, 1, 2)), _simple("ch-05", 100, jours=(1, 2)), _simple("ch-02", 80)]),
        ([_equipe("eq-a", jours=(0, 1, 2, 3)), _equipe("eq-b", jours=(2, 3))],
         [_multi("ch-01", [200, 200, 200], consecutifs=True, jours=(1, 2, 3)), _simple("ch-02", 250),
          _simple("ch-03", 250)]),
        ([_equipe("eq-a", jours=(0, 1, 2)), _equipe("eq-b", jours=(0, 1, 2))],
         [_multi("ch-01", [500, 500], jours=(0, 1)), _multi("ch-04", [500, 500], jours=(0, 1)),
          _multi("ch-07", [500, 500], jours=(0, 1))]),
    ]
    for equipes, chantiers in cas:
        entree = _entree(equipes, chantiers)
        sortie = _resoudre(entree)
        _accepte(entree, sortie)
        assert sortie["totaux"]["cout_total_m"] == _oracle(entree)


# ---------------------------------------------------------------------------
# 3. Capacité, horaires, absences : ce que les règles déjà dans M4 imposent
# ---------------------------------------------------------------------------
def test_l_absence_de_l_equipe_un_jour_est_respectee_et_la_meme_equipe_garde_toutes_les_visites():
    """eq-a n'a pas de quart le jour 1 (absence) : jamais de visite ce jour-là pour elle, ni de mélange d'équipes."""
    entree = _entree([_equipe("eq-a", jours=(0, 2, 3)), _equipe("eq-b", jours=(0, 1, 2, 3))],
                     [_multi("ch-01", [420, 420, 300])])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    visites = _visites_de(sortie, "ch-01")
    assert len({v[0] for v in visites}) == 1
    for equipe, jour, *_ in visites:
        assert not (equipe == "eq-a" and jour == 1)
    assert not any(route["equipe"] == "eq-a" and route["jour"] == 1 for route in sortie["plan"])


def test_jours_consecutifs_une_absence_oblige_a_prendre_l_autre_equipe_en_entier():
    """Journées consécutives exigées, eq-a absente le jour 1 : ses jours 0 et 2 ne sont plus consécutifs (le jour 1
    reste un jour d'activité de l'entreprise grâce à eq-b) ; le chantier va en entier chez eq-b."""
    entree = _entree([_equipe("eq-a", jours=(0, 2)), _equipe("eq-b", jours=(1, 2, 3))],
                     [_multi("ch-01", [400, 400], consecutifs=True, jours=(0, 1, 2, 3))])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    visites = _visites_de(sortie, "ch-01")
    assert {v[0] for v in visites} == {"eq-b"}
    assert [v[1] for v in visites] in ([1, 2], [2, 3])


def test_un_ferie_sans_quart_ne_casse_pas_une_suite_de_journees_consecutives():
    """Aucun quart le jour 2 (férié) : les jours d'activité sont 0, 1, 3, 4 ; (1, 3, 4) est une suite consécutive."""
    entree = _entree([_equipe("eq-a", jours=(0, 1, 3, 4))],
                     [_multi("ch-01", [420, 420, 300], consecutifs=True, jours=(1, 3, 4))])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    assert [v[1] for v in _visites_de(sortie, "ch-01")] == [1, 3, 4]


def test_sans_exigence_de_jours_consecutifs_un_trou_est_permis_mais_pas_un_melange_d_equipes():
    entree = _entree([_equipe("eq-a", jours=(0, 2, 3)), _equipe("eq-b", jours=(1,))],
                     [_multi("ch-01", [420, 420], consecutifs=False, jours=(0, 1, 2, 3))])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    assert {v[0] for v in _visites_de(sortie, "ch-01")} == {"eq-a"}


def test_continuite_impossible_est_dite_avec_sa_raison_et_rien_n_est_a_moitie_cedule():
    entree = _entree([_equipe("eq-a", jours=(0,)), _equipe("eq-b", jours=(1,))],
                     [_multi("ch-01", [420, 420], jours=(0, 1))])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    assert _visites_de(sortie, "ch-01") == []
    ligne = _non_cedulees(sortie)["ch-01"]
    assert ligne["code"] == tournees.RAISON_CONTINUITE
    assert "2 journées distinctes" in ligne["raison"]
    assert sortie["totaux"]["chantiers_non_cedules"] == 1


def test_continuite_impossible_precise_quand_les_jours_consecutifs_sont_exiges():
    entree = _entree([_equipe("eq-a", jours=(0, 2)), _equipe("eq-b", jours=(1,))],
                     [_multi("ch-01", [420, 420], consecutifs=True, jours=(0, 1, 2))])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    ligne = _non_cedulees(sortie)["ch-01"]
    assert ligne["code"] == tournees.RAISON_CONTINUITE
    assert "consécutives" in ligne["raison"]


def test_tout_ou_rien_une_visite_qui_ne_tient_pas_retire_tout_le_chantier():
    """La deuxième visite (600 min) dépasse tout quart : le chantier n'est pas cédulé, pas même sa première visite."""
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 600]), _simple("ch-02", 60)])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    assert _visites_de(sortie, "ch-01") == []
    ligne = _non_cedulees(sortie)["ch-01"]
    assert ligne["code"] == tournees.RAISON_DUREE
    assert "visite 2/2" in ligne["raison"]
    assert _visites_de(sortie, "ch-02")


def test_la_fenetre_du_client_limite_les_jours_de_chaque_visite():
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 300], jours=(1, 3))])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    assert [v[1] for v in _visites_de(sortie, "ch-01")] == [1, 3]


def test_une_competence_manquante_empeche_le_chantier_entier():
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 300], competences=["toiture"])])
    sortie = _resoudre(entree)
    ligne = _non_cedulees(sortie)["ch-01"]
    assert ligne["code"] == tournees.RAISON_COMPETENCE
    assert "toiture" in ligne["raison"]
    assert "visite 1/2" in ligne["raison"]


def test_les_coordonnees_manquantes_sont_dites_pour_un_chantier_de_plusieurs_visites():
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 300])])
    # retire le site de la matrice : « coordonnées manquantes : à confirmer »
    entree["matrice"] = _matrice({"depot-repentigny"})
    sortie = _resoudre(entree)
    ligne = _non_cedulees(sortie)["ch-01"]
    assert ligne["code"] == tournees.RAISON_COORDONNEES
    _accepte(entree, sortie)


def test_le_cout_de_non_cedule_d_un_chantier_de_plusieurs_visites_est_celui_d_un_seul_chantier():
    entree = _entree([_equipe("eq-a", jours=(0,))], [_multi("ch-01", [300, 300], urgence=1)])
    sortie = _resoudre(entree)
    assert sortie["totaux"]["cout_non_cedule_m"] == PARAMS["cout_non_cedule_m"] * 2   # un chantier urgent, pas deux


def test_un_creneau_fige_n_est_jamais_deplace_par_un_chantier_de_plusieurs_visites():
    equipes, chantiers = CONFIGURATIONS["figé"]
    entree = _entree(equipes, chantiers)
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    assert _visites_de(sortie, "ch-02")[0][:3] == ("eq-a", 0, 600)


def test_la_priorite_d_urgence_prime_sur_un_chantier_plus_leger():
    equipes, chantiers = CONFIGURATIONS["urgence"]
    entree = _entree(equipes, chantiers)
    sortie = _resoudre(entree)
    assert _visites_de(sortie, "ch-01")      # le chantier urgent de deux jours est cédulé
    assert "ch-01" not in _non_cedulees(sortie)


# ---------------------------------------------------------------------------
# 4. Moteurs : seul le repli exact, dit sans détour
# ---------------------------------------------------------------------------
def test_exiger_pyvrp_pour_un_chantier_de_plusieurs_visites_est_un_refus_nomme():
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 300])])
    sortie, verdict = tournees.resoudre(entree, "pyvrp")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_MULTIJOURS_MOTEUR
    assert "repli exact" in verdict["detail"]


def test_en_automatique_meme_avec_pyvrp_installe_le_repli_exact_resout(monkeypatch):
    monkeypatch.setattr(tournees, "pyvrp_installe", lambda: (True, tournees.VERSION_PYVRP))
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 300])])
    sortie = _resoudre(entree, "auto")
    assert sortie["meta"]["solveur"] == tournees.SOLVEUR_DP
    _accepte(entree, sortie)


def test_au_dela_de_douze_visites_le_repli_exact_refuse_et_le_dit():
    chantiers = [_multi("ch-01", [100] * 9, jours=range(10)), _simple("ch-02", 60), _simple("ch-03", 60),
                 _simple("ch-04", 60), _simple("ch-05", 60)]
    entree = _entree([_equipe("eq-a", jours=range(10))], chantiers)
    sortie, verdict = tournees.resoudre(entree, "auto")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_TAILLE_DP
    assert "PyVRP ne résout pas" in verdict["detail"]


def test_trop_de_combinaisons_de_journees_est_un_refus_nomme(monkeypatch):
    monkeypatch.setattr(tournees, "MAX_COMBINAISONS_MULTIJOURS", 5)
    entree = _entree([_equipe("eq-a"), _equipe("eq-b")], [_multi("ch-01", [200, 200, 200])])
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_TAILLE_DP
    assert "combinaisons de journées" in verdict["detail"]


# ---------------------------------------------------------------------------
# 5. Entrée : fail-closed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("modification, morceau", [
    (lambda c: c.pop("continuite"), "visites et continuite vont ensemble"),
    (lambda c: c.pop("visites"), "visites et continuite vont ensemble"),
    (lambda c: c.__setitem__("visites", [700]), "visites"),
    (lambda c: c.__setitem__("visites", [300] * 11), "visites"),
    (lambda c: c.__setitem__("visites", [300, 0]), "visites"),
    (lambda c: c.__setitem__("visites", [300, 1441]), "visites"),
    (lambda c: c.__setitem__("visites", [300, 300.5]), "visites"),
    (lambda c: c.__setitem__("visites", "300,300"), "visites"),
    (lambda c: c.__setitem__("duree_min", 599), "somme des visites"),
    (lambda c: c["continuite"].__setitem__("equipe", "libre"), "'unique' attendu"),
    (lambda c: c["continuite"].__setitem__("jours_consecutifs", "oui"), "booléen explicite"),
    (lambda c: c["continuite"].pop("jours_consecutifs"), "jours_consecutifs"),
    (lambda c: c["continuite"].__setitem__("surprise", 1), "clés inconnues"),
    (lambda c: c.__setitem__("creneau_fige", {"equipe": "eq-a", "jour": 0, "debut_min": 480}), "creneau_fige"),
])
def test_une_declaration_de_visites_invalide_est_refusee(modification, morceau):
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 300])])
    modification(entree["chantiers"][0])
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] in ("REJ-CONTRAT-INVALIDE", "REJ-CHAMP-MANQUANT")
    assert morceau in verdict["detail"]


def test_un_identifiant_interne_de_visite_deja_pris_est_refuse(monkeypatch):
    monkeypatch.setitem(SITES, "ch-01#1", SITES["ch-02"])
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 300]), _simple("ch-01#1", 60)])
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert "déjà utilisé" in verdict["detail"]


def test_continuite_sans_visites_est_refusee_et_visites_sans_continuite_aussi():
    entree = _entree([_equipe("eq-a")], [_simple("ch-01", 90)])
    entree["chantiers"][0]["continuite"] = {"equipe": "unique", "jours_consecutifs": False}
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert "vont ensemble" in verdict["detail"]


# ---------------------------------------------------------------------------
# 6. Le validateur indépendant refuse un plan qui viole les règles de continuité
# ---------------------------------------------------------------------------
def _plan_a_deux_equipes():
    """Un plan valide de ch-01 (3 visites) à partir duquel on fabrique des plans faux."""
    entree = _entree([_equipe("eq-a"), _equipe("eq-b")], [_multi("ch-01", [300, 300, 300])])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    return entree, sortie


def test_le_validateur_refuse_des_visites_confiees_a_deux_equipes():
    entree, sortie = _plan_a_deux_equipes()
    faux = copy.deepcopy(sortie)
    # déplace la visite 2 vers l'autre équipe, même jour (quart libre de l'autre équipe)
    route = next(r for r in faux["plan"] if any(v.get("visite") == 2 for v in r["visites"]))
    visite = next(v for v in route["visites"] if v.get("visite") == 2)
    route["visites"].remove(visite)
    autre = "eq-b" if route["equipe"] == "eq-a" else "eq-a"
    faux["plan"].append({**copy.deepcopy(route), "equipe": autre, "visites": [visite]})
    faux["plan"] = [r for r in faux["plan"] if r["visites"]]
    faux["plan"].sort(key=lambda r: (r["equipe"], r["jour"]))
    _refuse(entree, _resigner(faux), "même équipe")


def test_le_validateur_refuse_des_visites_dans_le_desordre_ou_le_meme_jour():
    entree, sortie = _plan_a_deux_equipes()
    faux = copy.deepcopy(sortie)
    for route in faux["plan"]:
        for visite in route["visites"]:
            if visite.get("visite") == 3:
                visite["visite"] = 1
            elif visite.get("visite") == 1:
                visite["visite"] = 3
    _refuse(entree, _resigner(faux), "jours distincts et croissants")


def test_le_validateur_refuse_un_chantier_a_moitie_cedule():
    entree, sortie = _plan_a_deux_equipes()
    faux = copy.deepcopy(sortie)
    faux["plan"] = [r for r in faux["plan"] if not any(v.get("visite") == 3 for v in r["visites"])]
    _refuse(entree, _resigner(faux), "tout ou rien")


def test_le_validateur_refuse_des_jours_non_consecutifs_quand_ils_sont_exiges():
    entree = _entree([_equipe("eq-a", jours=(0, 1, 2, 3))], [_multi("ch-01", [300, 300], consecutifs=True)])
    sortie = _resoudre(entree)
    _accepte(entree, sortie)
    faux = copy.deepcopy(sortie)
    faux["plan"][1]["jour"] = faux["plan"][1]["jour"] + 1       # laisse un trou d'un jour d'activité
    faux["plan"].sort(key=lambda r: (r["equipe"], r["jour"]))
    _refuse(entree, _resigner(faux), "consécutifs")


def test_le_validateur_refuse_un_nombre_de_visites_total_faux_et_une_visite_inconnue():
    entree, sortie = _plan_a_deux_equipes()
    faux = copy.deepcopy(sortie)
    faux["plan"][0]["visites"][0]["visites_total"] = 2
    _refuse(entree, _resigner(faux), "visites_total")
    faux = copy.deepcopy(sortie)
    faux["plan"][0]["visites"][0]["visite"] = 9
    _refuse(entree, _resigner(faux), "inconnu")


def test_le_validateur_refuse_un_chantier_de_plusieurs_visites_place_comme_une_seule():
    entree, sortie = _plan_a_deux_equipes()
    faux = copy.deepcopy(sortie)
    for route in faux["plan"]:
        for visite in route["visites"]:
            visite.pop("visite", None)
            visite.pop("visites_total", None)
    _refuse(entree, _resigner(faux), "comme une seule visite")


def test_le_validateur_refuse_une_raison_de_non_cedule_differente_du_diagnostic():
    entree = _entree([_equipe("eq-a", jours=(0,))], [_multi("ch-01", [300, 300])])
    sortie = _resoudre(entree)
    faux = copy.deepcopy(sortie)
    faux["non_cedulees"][0]["code"] = tournees.RAISON_JOURNEES_PLEINES
    _refuse(entree, _resigner(faux), "raison recalculée")


def test_le_validateur_refuse_la_duree_d_une_visite_modifiee():
    entree, sortie = _plan_a_deux_equipes()
    faux = copy.deepcopy(sortie)
    faux["plan"][0]["visites"][0]["fin_min"] -= 30
    _refuse(entree, _resigner(faux), "durée fournie")


# ---------------------------------------------------------------------------
# 7. Déterminisme
# ---------------------------------------------------------------------------
def _octets(sortie):
    return json.dumps(sortie, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def test_deux_executions_donnent_les_memes_octets():
    for nom in sorted(CONFIGURATIONS):
        equipes, chantiers = CONFIGURATIONS[nom]
        assert _octets(_resoudre(_entree(equipes, chantiers))) == _octets(_resoudre(_entree(equipes, chantiers)))


_PROGRAMME = """
import hashlib, importlib.util, sys
spec = importlib.util.spec_from_file_location("aide_multijours", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
empreinte = hashlib.sha256()
for nom in sorted(module.CONFIGURATIONS):
    equipes, chantiers = module.CONFIGURATIONS[nom]
    empreinte.update(module._octets(module._resoudre(module._entree(equipes, chantiers))))
print(empreinte.hexdigest())
"""


def test_memes_octets_dans_des_interpreteurs_aux_graines_de_hachage_differentes():
    attendu = __import__("hashlib").sha256()
    for nom in sorted(CONFIGURATIONS):
        equipes, chantiers = CONFIGURATIONS[nom]
        attendu.update(_octets(_resoudre(_entree(equipes, chantiers))))
    empreintes = set()
    for graine in ("1", "2", "3", "4242"):
        environnement = {**os.environ, "PYTHONHASHSEED": graine, "PYTHONPATH": os.pathsep.join(sys.path)}
        resultat = subprocess.run(
            [sys.executable, "-c", _PROGRAMME, str(Path(__file__).resolve())],
            capture_output=True, text=True, env=environnement, check=True,
        )
        empreintes.add(resultat.stdout.strip())
    assert empreintes == {attendu.hexdigest()}


# ---------------------------------------------------------------------------
# 8. Le diagnostic lui-même garde « tout ou rien » (indépendamment du validateur de groupe)
# ---------------------------------------------------------------------------
def test_le_diagnostic_traite_une_seule_visite_placee_comme_un_chantier_non_cedule():
    entree = _entree([_equipe("eq-a")], [_multi("ch-01", [300, 300]), _simple("ch-02", 60)])
    probleme, verdict = tournees._preparer(entree)
    assert verdict is None
    unites = probleme["groupes"]["ch-01"]["unites"]
    k = probleme["admissibles"][unites[0]][0]
    lignes = tournees._diagnostiquer(probleme, {k: [unites[0], "ch-02"]})
    assert [ligne["chantier"] for ligne in lignes] == ["ch-01"], lignes
    k0, k1 = probleme["admissibles"][unites[0]][0], probleme["admissibles"][unites[1]][1]
    complet = tournees._diagnostiquer(probleme, {k0: [unites[0]], k1: [unites[1]]})
    assert [ligne["chantier"] for ligne in complet] == ["ch-02"]
