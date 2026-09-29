"""Solveur de tournées et validateur de plan (PLAN T4.1-c, R15 §1 et §4).

Tout est fictif (`fictif: true`) : sites de Repentigny à Joliette aux coordonnées APPROXIMATIVES (centres de
municipalités, sans adresse), durées, fenêtres, compétences et quarts inventés (`fixtures/
tournees_repentigny_joliette.json`). Le DP exact est toujours testé ; les tests qui exigent PyVRP sont sautés
proprement s'il manque (extra `tournees`).
"""

from __future__ import annotations

import ast
import copy
import importlib
import itertools
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest
from m4_field_ops import digest, distances, encodage, tournees, verdicts

_SRC = Path(tournees.__file__).resolve().parent
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tournees_repentigny_joliette.json"

FIXTURE = json.loads(_FIXTURE.read_text(encoding="utf-8"))
SITES = {site["id"]: site for site in FIXTURE["sites"]}
INSTANCES = {instance["nom"]: instance for instance in FIXTURE["instances"]}
PARAMS_DISTANCE = FIXTURE["parametres_distance"]
PARAMS = {"graine": 7, "iterations": 500, "cout_non_cedule_m": 60000}
MOTEURS_TEST = ["dp", "pyvrp"]
PHRASE_COORDONNEES = "coordonnées manquantes : à confirmer"


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------
def _matrice(identifiants):
    points = [
        {
            "id": i,
            "latitude_microdeg": SITES[i]["latitude_microdeg"],
            "longitude_microdeg": SITES[i]["longitude_microdeg"],
        }
        for i in sorted(identifiants)
    ]
    matrice, verdict = distances.matrice_palier0(points, PARAMS_DISTANCE)
    assert verdict is None
    return matrice


def _equipe(identifiant, competences=(), depot="depot-repentigny", jours=(0,), debut=480, fin=1020):
    return {
        "id": identifiant, "competences": list(competences), "depot": depot,
        "quarts": [{"jour": jour, "debut_min": debut, "fin_min": fin} for jour in jours],
    }


def _chantier(identifiant, duree=90, jours=(0,), debut=480, fin=1020, competences=(), urgence=0, fige=None):
    return {
        "id": identifiant, "duree_min": duree,
        "fenetre": {"jours": list(jours), "debut_min": debut, "fin_min": fin},
        "competences_requises": list(competences), "urgence": urgence, "creneau_fige": fige,
    }


def _entree(equipes, chantiers, parametres=None, ids_supplementaires=()):
    """Entrée complète ; la matrice couvre les dépôts et les chantiers qui ont des coordonnées."""
    identifiants = {e["depot"] for e in equipes} | {c["id"] for c in chantiers if c["id"] in SITES}
    return {
        "version": tournees.VERSION_ENTREE,
        "equipes": copy.deepcopy(equipes),
        "chantiers": copy.deepcopy(chantiers),
        "matrice": _matrice(identifiants | set(ids_supplementaires)),
        "parametres": dict(PARAMS if parametres is None else parametres),
    }


def _de_instance(nom):
    instance = INSTANCES[nom]
    return _entree(instance["equipes"], instance["chantiers"], instance["parametres"])


def _octets(sortie):
    return json.dumps(sortie, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _exiger(moteur):
    if moteur == "pyvrp":
        pytest.importorskip("pyvrp")
        installe, raison = tournees.pyvrp_installe()
        if not installe:
            pytest.skip(raison)
    return moteur


def _resoudre(entree, moteur="dp"):
    sortie, verdict = tournees.resoudre(entree, moteur)
    assert verdict is None, verdict
    return sortie


def _resigner(sortie):
    """Recalcule ``meta.empreinte_sortie`` : seule la vérification des contraintes peut alors refuser."""
    sortie["meta"].pop("empreinte_sortie", None)
    sortie["meta"]["empreinte_sortie"] = encodage.empreinte(sortie)
    return sortie


def _accepte(entree, sortie):
    ok, violations = tournees.verifier_plan(entree, sortie)
    assert ok, violations


def _refuse(entree, sortie, morceau):
    ok, violations = tournees.verifier_plan(entree, sortie)
    assert not ok
    assert any(morceau in violation for violation in violations), violations


def _route(sortie, equipe, jour=0):
    return next(r for r in sortie["plan"] if r["equipe"] == equipe and r["jour"] == jour)


def _visites(sortie):
    return {v["chantier"]: (r["equipe"], r["jour"], v["debut_min"]) for r in sortie["plan"] for v in r["visites"]}


def _non_cedulees(sortie):
    return {ligne["chantier"]: ligne for ligne in sortie["non_cedulees"]}


def _supprimer(entree, chemin):
    """Retire la clé désignée par ``chemin`` (entiers pour les listes, chaînes pour les objets)."""
    cible = entree
    for etape in chemin[:-1]:
        cible = cible[etape]
    del cible[chemin[-1]]
    return entree


# ---------------------------------------------------------------------------
# 1. Entrée : fail-closed, jamais de valeur par défaut
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nom", sorted(INSTANCES))
def test_chaque_instance_fictive_donne_un_plan_que_le_validateur_accepte(nom):
    entree = _de_instance(nom)
    sortie = _resoudre(entree, "dp")
    assert sortie["meta"]["solveur"] == "dp-exact"
    assert sortie["plan"]
    _accepte(entree, sortie)


@pytest.mark.parametrize("chemin", [
    ("version",), ("equipes",), ("chantiers",), ("matrice",), ("parametres",),
    ("equipes", 0, "id"), ("equipes", 0, "competences"), ("equipes", 0, "depot"), ("equipes", 0, "quarts"),
    ("chantiers", 0, "id"), ("chantiers", 0, "duree_min"), ("chantiers", 0, "fenetre"),
    ("chantiers", 0, "fenetre", "jours"), ("chantiers", 0, "fenetre", "debut_min"),
    ("chantiers", 0, "fenetre", "fin_min"), ("chantiers", 0, "competences_requises"),
    ("chantiers", 0, "urgence"), ("chantiers", 0, "creneau_fige"),
    ("parametres", "graine"), ("parametres", "iterations"), ("parametres", "cout_non_cedule_m"),
])
def test_une_donnee_absente_donne_un_verdict_qui_dit_quoi_fournir(chemin):
    entree = _supprimer(_de_instance("journee-8-competence-rare"), chemin)
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    assert chemin[-1] in verdict["detail"]


def test_une_valeur_nulle_vaut_une_donnee_absente_sauf_pour_le_creneau_fige():
    entree = _de_instance("journee-8-competence-rare")
    entree["chantiers"][0]["duree_min"] = None
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    assert "duree_min" in verdict["detail"]
    entree = _de_instance("journee-8-competence-rare")
    assert entree["chantiers"][0]["creneau_fige"] is None
    assert tournees.resoudre(entree, "dp")[1] is None


@pytest.mark.parametrize("modification, morceau", [
    (lambda e: e["chantiers"][0]["fenetre"].__setitem__("jours", []), "jours manquants"),
    (lambda e: e["equipes"][0].__setitem__("quarts", []), "quarts manquants"),
])
def test_une_liste_vide_qui_devrait_porter_une_donnee_vaut_une_donnee_absente(modification, morceau):
    entree = _de_instance("journee-8-competence-rare")
    modification(entree)
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    assert morceau in verdict["detail"]


def test_le_verdict_liste_tout_ce_qu_il_faut_fournir_en_une_fois():
    entree = _de_instance("journee-8-competence-rare")
    del entree["chantiers"][0]["duree_min"]
    del entree["chantiers"][3]["fenetre"]
    del entree["equipes"][1]["competences"]
    del entree["parametres"]["graine"]
    verdict = tournees.resoudre(entree, "dp")[1]
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    for attendu in ("ch-01", "duree_min", "ch-04", "fenetre", "eq-b", "competences", "graine"):
        assert attendu in verdict["detail"]


@pytest.mark.parametrize("modification, morceau", [
    (lambda e: e["chantiers"][0].__setitem__("duree_min", 90.0), "duree_min"),
    (lambda e: e["chantiers"][0].__setitem__("duree_min", True), "duree_min"),
    (lambda e: e["chantiers"][0].__setitem__("duree_min", 0), "duree_min"),
    (lambda e: e["chantiers"][0].__setitem__("urgence", 4), "urgence"),
    (lambda e: e["chantiers"][0]["fenetre"].__setitem__("fin_min", 480), "debut_min doit précéder fin_min"),
    (lambda e: e["chantiers"][0]["fenetre"].__setitem__("fin_min", 1441), "fin_min"),
    (lambda e: e["chantiers"][0].__setitem__("competences_requises", "gouttieres"), "competences_requises"),
    (lambda e: e["chantiers"][0].__setitem__("surprise", 1), "clés inconnues"),
    (lambda e: e["chantiers"][1].__setitem__("id", "ch-01"), "identifiant de chantier en double"),
    (lambda e: e["equipes"][1].__setitem__("id", "eq-a"), "identifiant d'équipe en double"),
    (lambda e: e["equipes"][0]["quarts"].append({"jour": 0, "debut_min": 480, "fin_min": 900}), "deux quarts"),
    (lambda e: e["equipes"][0]["quarts"][0].__setitem__("fin_min", 480), "debut_min doit précéder fin_min"),
    (lambda e: e["equipes"][0].__setitem__("depot", "depot-inconnu"), "absent de la matrice"),
    (lambda e: e["chantiers"][0].__setitem__("id", "depot-repentigny"), "déjà utilisé par un dépôt"),
    (lambda e: e["parametres"].__setitem__("iterations", 0), "iterations"),
    (lambda e: e["parametres"].__setitem__("iterations", 10**6), "iterations"),
    (lambda e: e["parametres"].__setitem__("graine", -1), "graine"),
    (lambda e: e["parametres"].__setitem__("graine", 2**32), "graine"),
    (lambda e: e["parametres"].__setitem__("cout_non_cedule_m", 0), "cout_non_cedule_m"),
    (lambda e: e["parametres"].__setitem__("cout_non_cedule_m", 1.5), "cout_non_cedule_m"),
    (lambda e: e["parametres"].__setitem__("inconnu", 1), "clés inconnues"),
    (lambda e: e.__setitem__("version", "tournees-entree-v0"), "version"),
    (lambda e: e.__setitem__("surprise", 1), "clés inconnues"),
    (lambda e: e["matrice"]["metres"][0].__setitem__(1, e["matrice"]["metres"][0][1] + 1), "matrice"),
])
def test_une_entree_invalide_est_refusee_avec_un_verdict_precis(modification, morceau):
    entree = _de_instance("journee-8-competence-rare")
    modification(entree)
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert morceau in verdict["detail"]


def test_aucun_chantier_donne_champ_vide_et_une_entree_illisible_un_contrat_invalide():
    entree = _de_instance("journee-8-competence-rare")
    entree["chantiers"] = []
    assert tournees.resoudre(entree, "dp")[1]["code"] == "REJ-CHAMP-VIDE"
    for illisible in (None, [], "texte", 3):
        sortie, verdict = tournees.resoudre(illisible, "dp")
        assert sortie is None
        assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_un_moteur_inconnu_est_refuse():
    sortie, verdict = tournees.resoudre(_de_instance("journee-8-competence-rare"), "ortools")
    assert sortie is None
    assert verdict["code"] == "REJ-ENUM-INVALIDE"


def test_resoudre_ne_modifie_pas_l_entree_et_ignore_l_ordre_des_listes():
    entree = _de_instance("deux-jours-9")
    avant = copy.deepcopy(entree)
    sortie = _resoudre(entree, "dp")
    assert entree == avant
    melangee = copy.deepcopy(entree)
    melangee["equipes"].reverse()
    melangee["chantiers"].reverse()
    for equipe in melangee["equipes"]:
        equipe["quarts"].reverse()
        equipe["competences"].reverse()
    for chantier in melangee["chantiers"]:
        chantier["fenetre"]["jours"].reverse()
        chantier["competences_requises"].reverse()
    assert _octets(_resoudre(melangee, "dp")) == _octets(sortie)


def test_les_verdicts_de_tournees_ont_la_forme_des_verdicts_m4_et_restent_hors_du_catalogue_gele():
    assert tournees.verdict_tournees(tournees.CODE_PLAN_INVALIDE, "x") == {
        "code": tournees.CODE_PLAN_INVALIDE, "statut": "", "detail": "x",
    }
    with pytest.raises(verdicts.CodeVerdictInconnu):
        tournees.verdict_tournees("REJ-INVENTE")
    for code in tournees.CODES_TOURNEES:
        assert not verdicts.est_verdict(code)  # T4.1-d les y inscrira


# ---------------------------------------------------------------------------
# 2. Coordonnées manquantes : le chantier n'entre pas au solveur
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_un_chantier_sans_coordonnees_sort_en_non_cedulee_et_n_entre_pas_au_solveur(moteur, monkeypatch):
    _exiger(moteur)
    entree = _entree(
        INSTANCES["journee-8-competence-rare"]["equipes"],
        [*INSTANCES["journee-8-competence-rare"]["chantiers"], _chantier("ch-zz-sans-coordonnees", urgence=1)],
    )
    assert "ch-zz-sans-coordonnees" not in entree["matrice"]["ids"]
    recus = []
    moteurs = {"dp": "_resoudre_dp", "pyvrp": "_resoudre_pyvrp"}
    original = getattr(tournees, moteurs[moteur])

    def espion(problem, solveur_ids, *args):
        recus.append(list(solveur_ids))
        return original(problem, solveur_ids, *args)

    monkeypatch.setattr(tournees, moteurs[moteur], espion)
    sortie = _resoudre(entree, moteur)
    assert recus and "ch-zz-sans-coordonnees" not in recus[0]
    ligne = _non_cedulees(sortie)["ch-zz-sans-coordonnees"]
    assert ligne["code"] == tournees.RAISON_COORDONNEES
    assert ligne["raison"] == PHRASE_COORDONNEES
    assert "ch-zz-sans-coordonnees" not in _visites(sortie)
    _accepte(entree, sortie)


def test_sans_aucune_coordonnee_le_plan_est_vide_et_aucun_moteur_n_est_requis():
    entree = _entree([_equipe("eq-a")], [_chantier("ch-x"), _chantier("ch-y")], ids_supplementaires=())
    sortie, verdict = tournees.resoudre(entree, "auto")
    assert verdict is None
    assert sortie["plan"] == []
    assert [ligne["code"] for ligne in sortie["non_cedulees"]] == [tournees.RAISON_COORDONNEES] * 2
    assert all(ligne["raison"] == PHRASE_COORDONNEES for ligne in sortie["non_cedulees"])
    assert sortie["totaux"]["distance_m"] == 0
    assert sortie["totaux"]["cout_non_cedule_m"] == 2 * PARAMS["cout_non_cedule_m"]
    _accepte(entree, sortie)


# ---------------------------------------------------------------------------
# 3. Raisons de non-cédule : calculées par notre code
# ---------------------------------------------------------------------------
def _une_equipe():
    return [_equipe("eq-a", ["gouttieres"])]


def test_raison_competence_indisponible():
    entree = _entree(_une_equipe(), [_chantier("ch-01", competences=["toiture"]), _chantier("ch-02")])
    sortie = _resoudre(entree)
    ligne = _non_cedulees(sortie)["ch-01"]
    assert ligne["code"] == tournees.RAISON_COMPETENCE
    assert "toiture" in ligne["raison"]
    assert "ch-02" in _visites(sortie)
    _accepte(entree, sortie)


def test_raison_duree_trop_longue_pour_la_fenetre_ou_pour_le_quart():
    entree = _entree(_une_equipe(), [
        _chantier("ch-01", duree=180, debut=480, fin=600),
        _chantier("ch-02", duree=600, debut=0, fin=1440),
        _chantier("ch-03", duree=60),
    ])
    sortie = _resoudre(entree)
    lignes = _non_cedulees(sortie)
    assert lignes["ch-01"]["code"] == tournees.RAISON_DUREE
    assert "fenêtre du client (120 min)" in lignes["ch-01"]["raison"]
    assert lignes["ch-02"]["code"] == tournees.RAISON_DUREE
    assert "tout quart admissible (540 min)" in lignes["ch-02"]["raison"]
    assert set(_visites(sortie)) == {"ch-03"}
    _accepte(entree, sortie)


def test_raison_fenetre_inatteignable_jour_sans_quart_ou_trajet_trop_long():
    entree = _entree(_une_equipe(), [
        _chantier("ch-01", jours=[3]),
        _chantier("ch-14", duree=30, debut=480, fin=520),
        _chantier("ch-02"),
    ])
    sortie = _resoudre(entree)
    lignes = _non_cedulees(sortie)
    assert lignes["ch-01"]["code"] == tournees.RAISON_FENETRE
    assert "un des jours permis" in lignes["ch-01"]["raison"]
    assert lignes["ch-14"]["code"] == tournees.RAISON_FENETRE
    assert "inatteignable depuis le dépôt" in lignes["ch-14"]["raison"]
    _accepte(entree, sortie)


def test_raison_journees_pleines_quand_aucune_insertion_valide_ne_reste():
    entree = _entree(_une_equipe(), [_chantier("ch-01", duree=300), _chantier("ch-02", duree=300)])
    sortie = _resoudre(entree)
    assert len(_visites(sortie)) == 1
    (perdu,) = [cid for cid in ("ch-01", "ch-02") if cid not in _visites(sortie)]
    ligne = _non_cedulees(sortie)[perdu]
    assert ligne["code"] == tournees.RAISON_JOURNEES_PLEINES
    assert "journées pleines" in ligne["raison"]
    _accepte(entree, sortie)


def test_raison_cout_superieur_donne_le_supplement_exact_en_metres():
    chantiers = [_chantier("ch-01"), _chantier("ch-14")]
    peu_cher = _entree(_une_equipe(), chantiers, {**PARAMS, "cout_non_cedule_m": 30000})
    cher = _entree(_une_equipe(), chantiers, {**PARAMS, "cout_non_cedule_m": 10**6})
    sans = _resoudre(peu_cher)
    avec = _resoudre(cher)
    assert set(_visites(sans)) == {"ch-01"}
    assert set(_visites(avec)) == {"ch-01", "ch-14"}
    supplement = avec["totaux"]["distance_m"] - sans["totaux"]["distance_m"]
    ligne = _non_cedulees(sans)["ch-14"]
    assert ligne["code"] == tournees.RAISON_COUT
    assert f"+{supplement} m" in ligne["raison"]
    assert "(30000 m)" in ligne["raison"]
    _accepte(peu_cher, sans)


def test_l_urgence_rend_un_chantier_plus_couteux_a_laisser_de_cote():
    equipes = [_equipe("eq-a")]
    proche = _chantier("ch-01", duree=300)  # Repentigny, près du dépôt
    loin = _chantier("ch-06", duree=300)  # Lavaltrie
    sans_urgence = _resoudre(_entree(equipes, [proche, loin]))
    assert set(_visites(sans_urgence)) == {"ch-01"}
    urgent = _chantier("ch-06", duree=300, urgence=3)
    avec_urgence = _resoudre(_entree(equipes, [proche, urgent]))
    assert set(_visites(avec_urgence)) == {"ch-06"}
    assert avec_urgence["totaux"]["cout_non_cedule_m"] == PARAMS["cout_non_cedule_m"]


def test_les_raisons_ne_viennent_jamais_du_solveur(monkeypatch):
    """Un moteur qui laisse tout de côté n'impose aucune raison : c'est notre diagnostic qui parle."""
    entree = _de_instance("journee-8-competence-rare")
    monkeypatch.setattr(tournees, "_resoudre_dp", lambda problem, solveur_ids: {})
    sortie = _resoudre(entree, "dp")
    assert sortie["plan"] == []
    lignes = _non_cedulees(sortie)
    assert {ligne["code"] for ligne in lignes.values()} == {tournees.RAISON_INSERTION, tournees.RAISON_COUT}
    assert "non retenue par le solveur" in lignes["ch-01"]["raison"]  # près du dépôt : moins cher que le coût
    assert lignes["ch-01"]["code"] == tournees.RAISON_INSERTION
    assert lignes["ch-14"]["code"] == tournees.RAISON_COUT  # Lanoraie : plus cher que le coût de non-cédule
    _accepte(entree, sortie)


# ---------------------------------------------------------------------------
# 4. DP exact : comparé à une énumération exhaustive indépendante
# ---------------------------------------------------------------------------
def _cout_minimal_par_enumeration(entree):
    """Optimum par énumération de toutes les affectations et de tous les ordres (n petit)."""
    matrice = entree["matrice"]
    position = {identifiant: rang for rang, identifiant in enumerate(matrice["ids"])}

    def minutes(a, b):
        return -(-matrice["secondes"][position[a]][position[b]] // 60)

    def metres(a, b):
        return matrice["metres"][position[a]][position[b]]

    vehicules = [(e, q) for e in entree["equipes"] for q in e["quarts"]]
    chantiers = {c["id"]: c for c in entree["chantiers"]}
    ids = sorted(chantiers)
    base = entree["parametres"]["cout_non_cedule_m"]

    def meilleure_route(numero, groupe):
        equipe, quart = vehicules[numero]
        meilleur = None
        for ordre in itertools.permutations(groupe):
            lieu, libre, total, faisable = equipe["depot"], quart["debut_min"], 0, True
            for cid in ordre:
                c = chantiers[cid]
                debut = max(libre + minutes(lieu, cid), c["fenetre"]["debut_min"])
                if debut + c["duree_min"] > c["fenetre"]["fin_min"]:
                    faisable = False
                    break
                total += metres(lieu, cid)
                lieu, libre = cid, debut + c["duree_min"]
            if faisable and libre + minutes(lieu, equipe["depot"]) <= quart["fin_min"]:
                total += metres(lieu, equipe["depot"])
                meilleur = total if meilleur is None else min(meilleur, total)
        return meilleur

    admissibles = {
        cid: [
            n for n, (equipe, quart) in enumerate(vehicules)
            if set(chantiers[cid]["competences_requises"]) <= set(equipe["competences"])
            and quart["jour"] in chantiers[cid]["fenetre"]["jours"]
        ]
        for cid in ids
    }
    meilleur_total = None
    for choix in itertools.product(*[[None, *admissibles[cid]] for cid in ids]):
        total = sum(base * (1 + chantiers[cid]["urgence"]) for cid, n in zip(ids, choix, strict=True) if n is None)
        for numero in range(len(vehicules)):
            groupe = [cid for cid, n in zip(ids, choix, strict=True) if n == numero]
            if groupe:
                cout = meilleure_route(numero, groupe)
                if cout is None:
                    total = None
                    break
                total += cout
        if total is not None and (meilleur_total is None or total < meilleur_total):
            meilleur_total = total
    return meilleur_total


def _instance_aleatoire(graine):
    hasard = random.Random(graine)
    nombre = hasard.choice([5, 6])
    sites = hasard.sample(sorted(s for s in SITES if s.startswith("ch-")), nombre)
    jours = hasard.choice([(0,), (0, 1)])
    equipes = [
        _equipe("eq-a", hasard.choice([["gouttieres"], ["gouttieres", "toiture"]]), "depot-repentigny", jours),
        _equipe("eq-b", hasard.choice([["gouttieres", "revetement"], ["toiture"]]),
                hasard.choice(["depot-repentigny", "depot-joliette"]), jours),
    ]
    chantiers = []
    for site in sites:
        debut = hasard.choice([480, 540, 600])
        chantiers.append(_chantier(
            site,
            duree=hasard.choice([60, 90, 120, 180, 240]),
            jours=hasard.sample(list(jours), hasard.randint(1, len(jours))),
            debut=debut,
            fin=hasard.choice([780, 900, 1020]),
            competences=hasard.choice([[], [], ["gouttieres"], ["toiture"]]),
            urgence=hasard.choice([0, 0, 1, 3]),
        ))
    chantiers = [c for c in chantiers if c["fenetre"]["fin_min"] - c["fenetre"]["debut_min"] > 0]
    return _entree(equipes, chantiers, {**PARAMS, "cout_non_cedule_m": hasard.choice([20000, 60000, 150000])})


def test_le_dp_egale_l_enumeration_exhaustive_sur_des_instances_aleatoires():
    routes_vues = non_cedulees_vues = 0
    for graine in range(12):
        entree = _instance_aleatoire(graine)
        sortie = _resoudre(entree, "dp")
        assert sortie["totaux"]["cout_total_m"] == _cout_minimal_par_enumeration(entree), graine
        _accepte(entree, sortie)
        routes_vues += len(sortie["plan"])
        non_cedulees_vues += len(sortie["non_cedulees"])
    assert routes_vues >= 12  # les instances ne sont pas triviales : plusieurs routes,
    assert non_cedulees_vues >= 3  # et des chantiers laissés de côté


def test_le_dp_tient_les_creneaux_figes_comme_l_enumeration_les_admet():
    entree = _de_instance("journee-8-competence-rare")
    figee = copy.deepcopy(entree)
    figee["chantiers"] = [c for c in figee["chantiers"] if c["id"] in {"ch-01", "ch-02", "ch-03", "ch-04", "ch-06"}]
    libre = _resoudre(figee, "dp")
    route = _route(libre, "eq-b")
    visite = route["visites"][0]
    for chantier in figee["chantiers"]:
        if chantier["id"] == visite["chantier"]:
            chantier["creneau_fige"] = {"equipe": "eq-b", "jour": 0, "debut_min": visite["debut_min"]}
    contraint = _resoudre(figee, "dp")
    assert _visites(contraint)[visite["chantier"]] == ("eq-b", 0, visite["debut_min"])
    assert contraint["totaux"]["cout_total_m"] >= libre["totaux"]["cout_total_m"]
    _accepte(figee, contraint)


# ---------------------------------------------------------------------------
# 5. Créneaux figés
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_un_creneau_fige_est_tenu_meme_s_il_ne_serait_pas_cedule_sans_lui(moteur):
    _exiger(moteur)
    entree = _de_instance("journee-8-competence-rare")
    libre = _resoudre(entree, moteur)
    assert "ch-10" in _non_cedulees(libre)  # 240 min de toiture : journées pleines
    for chantier in entree["chantiers"]:
        if chantier["id"] == "ch-10":
            chantier["creneau_fige"] = {"equipe": "eq-b", "jour": 0, "debut_min": 600}
    sortie = _resoudre(entree, moteur)
    assert _visites(sortie)["ch-10"] == ("eq-b", 0, 600)
    _accepte(entree, sortie)
    if moteur == "pyvrp":
        assert sortie["totaux"]["cout_total_m"] == _resoudre(entree, "dp")["totaux"]["cout_total_m"]


@pytest.mark.parametrize("figer, code, morceau", [
    ({"equipe": "eq-z", "jour": 0, "debut_min": 600}, tournees.CODE_CRENEAU_FIGE, "eq-z"),
    ({"equipe": "eq-b", "jour": 5, "debut_min": 600}, tournees.CODE_CRENEAU_FIGE, "pas de quart le jour 5"),
    ({"equipe": "eq-a", "jour": 0, "debut_min": 600}, tournees.CODE_CRENEAU_FIGE, "compétences"),
    ({"equipe": "eq-b", "jour": 0, "debut_min": 1000}, tournees.CODE_CRENEAU_FIGE, "sort de la fenêtre"),
    ({"equipe": "eq-b", "jour": 0, "debut_min": 780}, tournees.CODE_CRENEAU_FIGE, "ne tient pas dans le quart"),
])
def test_un_creneau_fige_intenable_refuse_l_entree(figer, code, morceau):
    entree = _de_instance("journee-8-competence-rare")
    for chantier in entree["chantiers"]:
        if chantier["id"] == "ch-10":  # toiture, 240 min, fenêtre 480-1020
            chantier["creneau_fige"] = figer
            if figer["debut_min"] == 1000:
                chantier["fenetre"]["fin_min"] = 900
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == code
    assert morceau in verdict["detail"]


def test_un_jour_non_permis_et_deux_creneaux_incompatibles_refusent_l_entree():
    entree = _de_instance("deux-jours-9")
    for chantier in entree["chantiers"]:
        if chantier["id"] == "ch-01":  # jours permis : [0]
            chantier["creneau_fige"] = {"equipe": "eq-a", "jour": 1, "debut_min": 600}
    verdict = tournees.resoudre(entree, "dp")[1]
    assert verdict["code"] == tournees.CODE_CRENEAU_FIGE
    assert "jour 1 n'est pas permis" in verdict["detail"]

    entree = _de_instance("deux-jours-9")
    for chantier in entree["chantiers"]:
        if chantier["id"] in {"ch-01", "ch-07"}:
            chantier["creneau_fige"] = {"equipe": "eq-a", "jour": 0, "debut_min": 600}
    verdict = tournees.resoudre(entree, "dp")[1]
    assert verdict["code"] == tournees.CODE_CRENEAU_FIGE
    assert "incompatibles entre eux" in verdict["detail"]


def test_un_creneau_fige_sans_coordonnees_refuse_l_entree():
    entree = _entree(_une_equipe(), [
        _chantier("ch-zz", fige={"equipe": "eq-a", "jour": 0, "debut_min": 600}), _chantier("ch-01"),
    ])
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    assert "ch-zz" in verdict["detail"]
    assert "coordonnées" in verdict["detail"]


# ---------------------------------------------------------------------------
# 6. Validateur : indépendant du solveur, refuse tout plan qui viole une contrainte
# ---------------------------------------------------------------------------
@pytest.fixture
def cas():
    """Entrée de deux jours et son plan exact : ch-03 (toiture) chez eq-b, plusieurs visites par route."""
    entree = _de_instance("deux-jours-9")
    return entree, _resoudre(entree, "dp")


def _visite(sortie, chantier):
    for route in sortie["plan"]:
        for visite in route["visites"]:
            if visite["chantier"] == chantier:
                return route, visite
    raise AssertionError(chantier)


def test_le_validateur_accepte_un_plan_intact_et_ne_leve_jamais_sur_des_ordures(cas):
    entree, sortie = cas
    assert tournees.verifier_plan(entree, sortie) == (True, [])
    for ordure in (None, [], "plan", {}, {"version": 1}, {**sortie, "plan": "x"}, {**sortie, "meta": None}):
        ok, violations = tournees.verifier_plan(entree, ordure)
        assert ok is False
        assert violations
    ok, violations = tournees.verifier_plan({"version": "x"}, sortie)
    assert ok is False
    assert violations[0].startswith("entrée invalide")


def test_le_validateur_refuse_un_plan_hors_fenetre(cas):
    entree, sortie = cas
    avant = copy.deepcopy(sortie)
    _route_, visite = _visite(sortie, "ch-10")  # fenêtre 540-1020, toiture
    visite["debut_min"] = 500
    visite["fin_min"] = 500 + 180
    _resigner(sortie)
    _refuse(entree, sortie, "avant l'ouverture de la fenêtre du client (540 min)")

    apres = copy.deepcopy(avant)
    route, visite = _visite(apres, "ch-10")
    visite["debut_min"] += 400
    visite["fin_min"] += 400
    _resigner(apres)
    _refuse(entree, apres, "après la fermeture de la fenêtre du client (1020 min)")


def test_le_validateur_refuse_un_retour_apres_la_fin_du_quart(cas):
    entree, sortie = cas
    route = _route(sortie, "eq-b", 1)
    route["retour_min"] = 1021
    _resigner(sortie)
    _refuse(entree, sortie, "après la fin du quart (1020 min)")


def test_le_validateur_refuse_un_depart_avant_le_quart_et_des_trajets_trop_courts(cas):
    entree, sortie = cas
    route = _route(sortie, "eq-b", 1)
    copie = copy.deepcopy(sortie)
    _route(copie, "eq-b", 1)["depart_min"] = 400
    _resigner(copie)
    _refuse(entree, copie, "avant le début du quart (480 min)")

    copie = copy.deepcopy(sortie)
    _route(copie, "eq-b", 1)["visites"][0]["arrivee_min"] = route["depart_min"]
    _resigner(copie)
    _refuse(entree, copie, "trajet trop court")

    copie = copy.deepcopy(sortie)
    _route(copie, "eq-b", 1)["retour_min"] = route["visites"][-1]["fin_min"]
    _resigner(copie)
    _refuse(entree, copie, "trajet de retour trop court")


def test_le_validateur_refuse_une_equipe_sans_les_competences(cas):
    entree, sortie = cas
    route_a = _route(sortie, "eq-a", 1)
    route_b, visite = _visite(sortie, "ch-10")  # toiture : eq-b seulement
    assert route_b["equipe"] == "eq-b"
    route_b["visites"].remove(visite)
    route_a["visites"].append(visite)
    _resigner(sortie)
    _refuse(entree, sortie, "n'a pas toutes les compétences requises")


def test_le_validateur_refuse_un_jour_non_permis_ou_sans_quart(cas):
    entree, sortie = cas
    copie = copy.deepcopy(sortie)
    _, visite = _visite(copie, "ch-01")  # jours permis : [0]
    route_1 = _route(copie, "eq-a", 1)
    route_0 = next(r for r in copie["plan"] if any(v["chantier"] == "ch-01" for v in r["visites"]))
    route_0["visites"].remove(visite)
    route_1["visites"].append(visite)
    _resigner(copie)
    _refuse(entree, copie, "n'est pas permis par la fenêtre du client")

    copie = copy.deepcopy(sortie)
    _route(copie, "eq-a", 1)["jour"] = 7
    _resigner(copie)
    _refuse(entree, copie, "n'a pas de quart le jour 7")

    copie = copy.deepcopy(sortie)
    _route(copie, "eq-a", 1)["equipe"] = "eq-z"
    _resigner(copie)
    _refuse(entree, copie, "équipe 'eq-z' inconnue")


def test_le_validateur_refuse_un_creneau_fige_deplace_ou_perdu():
    entree = _de_instance("journee-8-competence-rare")
    for chantier in entree["chantiers"]:
        if chantier["id"] == "ch-10":
            chantier["creneau_fige"] = {"equipe": "eq-b", "jour": 0, "debut_min": 600}
    sortie = _resoudre(entree, "dp")
    _accepte(entree, sortie)

    decale = copy.deepcopy(sortie)
    route, visite = _visite(decale, "ch-10")
    visite["debut_min"] += 15  # toujours faisable, mais promis à 10 h 00
    visite["fin_min"] += 15
    route["retour_min"] = min(route["retour_min"] + 15, 1020)
    _resigner(decale)
    _refuse(entree, decale, "créneau figé non respecté")

    perdu = copy.deepcopy(sortie)
    route, visite = _visite(perdu, "ch-10")
    route["visites"].remove(visite)
    perdu["non_cedulees"].append({"chantier": "ch-10", "code": "x", "raison": "x", "action": "x"})
    _resigner(perdu)
    _refuse(entree, perdu, "créneau figé perdu")


def test_le_validateur_refuse_un_chantier_visite_deux_fois_invente_ou_oublie(cas):
    entree, sortie = cas
    double = copy.deepcopy(sortie)
    _route_, visite = _visite(double, "ch-01")
    autre = next(r for r in double["plan"] if all(v["chantier"] != "ch-01" for v in r["visites"]))
    autre["visites"].append(copy.deepcopy(visite))
    _resigner(double)
    _refuse(entree, double, "visité deux fois")

    invente = copy.deepcopy(sortie)
    _route(invente, "eq-a", 1)["visites"].append(
        {"chantier": "ch-99", "arrivee_min": 900, "debut_min": 900, "fin_min": 990},
    )
    _resigner(invente)
    _refuse(entree, invente, "chantier inconnu de l'entrée")

    fantome = copy.deepcopy(sortie)
    fantome["non_cedulees"].append({"chantier": "ch-99", "code": "x", "raison": "x", "action": "x"})
    _resigner(fantome)
    _refuse(entree, fantome, "chantier 'ch-99' inconnu de l'entrée")

    oublie = copy.deepcopy(sortie)
    route, visite = _visite(oublie, "ch-01")
    route["visites"].remove(visite)
    _resigner(oublie)
    _refuse(entree, oublie, "chantier 'ch-01' absent du plan et des non-cédulées")

    aussi = copy.deepcopy(sortie)
    aussi["non_cedulees"].append({"chantier": "ch-01", "code": "x", "raison": "x", "action": "x"})
    _resigner(aussi)
    _refuse(entree, aussi, "aussi présent au plan")


def test_le_validateur_refuse_un_chantier_sans_coordonnees_au_plan():
    entree = _entree(_une_equipe(), [_chantier("ch-01"), _chantier("ch-zz")])
    sortie = _resoudre(entree)
    route = _route(sortie, "eq-a")
    route["visites"].append({"chantier": "ch-zz", "arrivee_min": 900, "debut_min": 900, "fin_min": 990})
    sortie["non_cedulees"] = [ligne for ligne in sortie["non_cedulees"] if ligne["chantier"] != "ch-zz"]
    _resigner(sortie)
    _refuse(entree, sortie, "coordonnées manquantes, le chantier ne peut pas être cédulé")


def test_le_validateur_refuse_distance_totaux_et_raisons_falsifies(cas, monkeypatch):
    entree, sortie = cas
    copie = copy.deepcopy(sortie)
    _route(copie, "eq-a", 1)["distance_m"] -= 1
    _resigner(copie)
    _refuse(entree, copie, "distance_m")

    copie = copy.deepcopy(sortie)
    copie["totaux"]["cout_total_m"] -= 1
    _resigner(copie)
    _refuse(entree, copie, "totaux")

    entree_pleine = _de_instance("journee-8-competence-rare")
    pleine = _resoudre(entree_pleine, "dp")
    assert pleine["non_cedulees"]
    copie = copy.deepcopy(pleine)
    copie["non_cedulees"][0]["code"] = tournees.RAISON_COMPETENCE
    _resigner(copie)
    _refuse(entree_pleine, copie, "raison recalculée")

    # Une raison plausible mais fausse : la place existait (l'insertion était valide), pas de « journées pleines ».
    equipe_seule = _entree(_une_equipe(), [_chantier("ch-01"), _chantier("ch-02")])
    monkeypatch.setattr(tournees, "_resoudre_dp", lambda problem, solveur_ids: {0: ["ch-01"]})
    incomplet = _resoudre(equipe_seule)
    assert _non_cedulees(incomplet)["ch-02"]["code"] == tournees.RAISON_INSERTION
    _accepte(equipe_seule, incomplet)
    faux = copy.deepcopy(incomplet)
    faux["non_cedulees"][0]["code"] = tournees.RAISON_JOURNEES_PLEINES
    _resigner(faux)
    _refuse(equipe_seule, faux, f"raison recalculée {tournees.RAISON_INSERTION!r}")


def test_le_validateur_refuse_une_sortie_modifiee_apres_le_calcul_ou_mal_formee(cas):
    entree, sortie = cas
    copie = copy.deepcopy(sortie)
    visite = _route(copie, "eq-a", 1)["visites"][0]
    visite["debut_min"] += 1  # sans recalculer l'empreinte
    visite["fin_min"] += 1
    _refuse(entree, copie, "empreinte_sortie")

    copie = copy.deepcopy(sortie)
    copie["meta"]["empreinte_entree"] = "0" * 64
    _resigner(copie)
    _refuse(entree, copie, "empreinte_entree")

    copie = copy.deepcopy(sortie)
    copie["meta"]["mode_bride"] = False
    _resigner(copie)
    _refuse(entree, copie, "mode_distance ou mode_bride")

    copie = copy.deepcopy(sortie)
    _route(copie, "eq-a", 1)["distance_m"] = float(_route(copie, "eq-a", 1)["distance_m"])
    _refuse(entree, copie, "aucun flottant")

    copie = copy.deepcopy(sortie)
    copie["surprise"] = 1
    _refuse(entree, copie, "sortie : clés attendues")

    copie = copy.deepcopy(sortie)
    del _route(copie, "eq-a", 1)["visites"][0]["fin_min"]
    _refuse(entree, copie, "clés attendues")

    copie = copy.deepcopy(sortie)
    copie["meta"]["solveur"] = "inconnu"
    _resigner(copie)
    _refuse(entree, copie, "meta.solveur")


def test_le_validateur_verifie_une_route_aux_horaires_manuels_mais_valides(cas):
    """Un humain peut retarder une visite : les contraintes seules jugent, pas l'égalité avec le solveur."""
    entree, sortie = cas
    copie = copy.deepcopy(sortie)
    route = _route(copie, "eq-b", 1)
    dernier = route["visites"][-1]
    marge = 1020 - route["retour_min"]
    assert marge > 0
    dernier["debut_min"] += 1
    dernier["fin_min"] += 1
    route["retour_min"] += 1
    _resigner(copie)
    _accepte(entree, copie)


# ---------------------------------------------------------------------------
# 6 bis. Entrées et sorties mutées : jamais d'exception, jamais de plan altéré accepté
# ---------------------------------------------------------------------------
_BOUE = [None, 1.5, "x", "", [], {}, True, False, -1, 0, 10**12, [1], ["a"], {"a": 1}, float("nan"), 2**64, "ch-01"]


def _chemins(objet, base=()):
    if base:
        yield base
    if isinstance(objet, dict):
        for cle, valeur in objet.items():
            yield from _chemins(valeur, (*base, cle))
    elif isinstance(objet, list):
        for rang, valeur in enumerate(objet):
            yield from _chemins(valeur, (*base, rang))


def _muter(objet, hasard):
    copie = copy.deepcopy(objet)
    chemin = hasard.choice(list(_chemins(copie)))
    cible = copie
    for etape in chemin[:-1]:
        cible = cible[etape]
    if isinstance(cible, dict) and hasard.random() < 0.3:
        del cible[chemin[-1]]
    elif isinstance(cible, list) and hasard.random() < 0.2:
        cible.pop(chemin[-1])
    else:
        cible[chemin[-1]] = hasard.choice(_BOUE)
    return copie


def test_des_entrees_mutees_ne_levent_jamais_et_leur_plan_passe_le_validateur():
    entree = _de_instance("deux-jours-9")
    hasard = random.Random(20260929)
    refusees = acceptees = 0
    for _ in range(400):
        mutee = _muter(entree, hasard)
        sortie, verdict = tournees.resoudre(mutee, "dp")
        assert (sortie is None) != (verdict is None)
        if sortie is None:
            refusees += 1
            assert verdict["code"].startswith("REJ-")
        else:
            acceptees += 1
            _accepte(mutee, sortie)
    assert refusees > 100
    assert acceptees > 5


def test_toute_sortie_mutee_sans_etre_rescellee_est_refusee_sans_exception():
    entree = _de_instance("deux-jours-9")
    sortie = _resoudre(entree, "dp")
    hasard = random.Random(20260929)
    for _ in range(400):
        mutee = _muter(sortie, hasard)
        ok, violations = tournees.verifier_plan(entree, mutee)
        assert isinstance(violations, list)
        if mutee != sortie:
            assert ok is False
            assert violations


# ---------------------------------------------------------------------------
# 7. Moteurs absents, version épinglée, défaillances d'un moteur
# ---------------------------------------------------------------------------
def _entree_de_taille(nombre, sans_coordonnees=0):
    identifiants = [f"ch-{i:02d}" for i in range(1, 15)][:nombre]
    chantiers = [_chantier(cid, duree=60, competences=["gouttieres"]) for cid in identifiants]
    chantiers.extend(_chantier(f"ch-zz-{i}") for i in range(sans_coordonnees))
    equipes = [_equipe("eq-a", ["gouttieres"], jours=(0, 1)), _equipe("eq-b", ["gouttieres"], jours=(0, 1))]
    for chantier in chantiers:
        chantier["fenetre"]["jours"] = [0, 1]
    return _entree(equipes, chantiers)


@pytest.fixture
def sans_pyvrp(monkeypatch):
    monkeypatch.setattr(tournees, "_version_pyvrp", lambda: (None, "pyvrp absent"))


def test_sans_pyvrp_le_dp_prend_le_relais_jusqu_a_douze_chantiers(sans_pyvrp):
    entree = _entree_de_taille(12)
    sortie, verdict = tournees.resoudre(entree)
    assert verdict is None
    assert sortie["meta"]["solveur"] == "dp-exact"
    assert sortie["meta"]["version_solveur"] == tournees.VERSION_DP
    assert (sortie["meta"]["graine"], sortie["meta"]["iterations"]) == (None, None)
    _accepte(entree, sortie)


def test_sans_pyvrp_treize_chantiers_donnent_le_verdict_d_installation(sans_pyvrp):
    entree = _entree_de_taille(13)
    sortie, verdict = tournees.resoudre(entree)
    assert sortie is None
    assert verdict["code"] == tournees.CODE_SOLVEUR_ABSENT
    assert tournees.TEXTE_SOLVEUR_ABSENT in verdict["detail"]
    assert tournees.TEXTE_SOLVEUR_ABSENT == "solveur de tournées non installé : installer l'extra tournees"
    sortie, verdict = tournees.resoudre(entree, "pyvrp")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_SOLVEUR_ABSENT


def test_le_repli_exact_refuse_de_lui_meme_plus_de_douze_chantiers():
    sortie, verdict = tournees.resoudre(_entree_de_taille(13), "dp")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_TAILLE_DP
    assert "13 chantiers" in verdict["detail"]


def test_seuls_les_chantiers_entres_au_solveur_comptent_pour_la_limite_du_dp(sans_pyvrp):
    entree = _entree_de_taille(12, sans_coordonnees=3)  # 15 chantiers, 12 avec coordonnées
    sortie = _resoudre(entree, "auto")
    assert sortie["meta"]["solveur"] == "dp-exact"
    assert sum(1 for ligne in sortie["non_cedulees"] if ligne["code"] == tournees.RAISON_COORDONNEES) == 3


def test_pyvrp_hors_de_la_version_epinglee_est_traite_comme_absent(monkeypatch):
    monkeypatch.setattr(tournees.metadata, "version", lambda nom: "0.15.0")
    assert tournees.pyvrp_installe() == (False, "pyvrp 0.15.0 trouvé, 0.14.0 exigé")
    sortie, verdict = tournees.resoudre(_entree_de_taille(13))
    assert sortie is None
    assert verdict["code"] == tournees.CODE_SOLVEUR_ABSENT
    assert "0.15.0" in verdict["detail"]


def test_pyvrp_absent_du_systeme_est_detecte_sans_exception(monkeypatch):
    def introuvable(nom):
        raise tournees.metadata.PackageNotFoundError(nom)

    monkeypatch.setattr(tournees.metadata, "version", introuvable)
    assert tournees.pyvrp_installe() == (False, "pyvrp absent")


def test_une_exception_du_solveur_tiers_devient_un_verdict_sans_son_message(monkeypatch):
    def casse(*args):
        raise RuntimeError("adresse secrète 123 rue Exemple")

    monkeypatch.setattr(tournees, "pyvrp_installe", lambda: (True, tournees.VERSION_PYVRP))
    monkeypatch.setattr(tournees, "_resoudre_pyvrp", casse)
    sortie, verdict = tournees.resoudre(_de_instance("journee-8-competence-rare"), "pyvrp")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_SOLVEUR_ECHEC
    assert "RuntimeError" in verdict["detail"]
    assert "secrète" not in verdict["detail"]


@pytest.mark.parametrize("routes, morceau", [
    ({0: ["ch-03", "ch-01"]}, "hors de ses quarts admissibles"),  # ch-03 exige la toiture, eq-a n'en a pas
    ({1: ["ch-01", "ch-01"]}, "hors de ses quarts admissibles"),
    ({0: ["ch-01"], 1: ["ch-01"]}, "hors de ses quarts admissibles"),
    ({1: ["ch-03", "ch-10", "ch-14", "ch-01", "ch-04"]}, "viole un horaire"),
])
def test_un_moteur_qui_propose_un_plan_inacceptable_est_refuse(monkeypatch, routes, morceau):
    entree = _de_instance("journee-8-competence-rare")
    monkeypatch.setattr(tournees, "_resoudre_dp", lambda problem, solveur_ids: routes)
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_SOLVEUR_ECHEC
    assert morceau in verdict["detail"]


def test_un_moteur_qui_perd_un_creneau_fige_est_refuse(monkeypatch):
    entree = _de_instance("journee-8-competence-rare")
    for chantier in entree["chantiers"]:
        if chantier["id"] == "ch-01":
            chantier["creneau_fige"] = {"equipe": "eq-a", "jour": 0, "debut_min": 600}
    monkeypatch.setattr(tournees, "_resoudre_dp", lambda problem, solveur_ids: {1: ["ch-06"]})
    sortie, verdict = tournees.resoudre(entree, "dp")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_SOLVEUR_ECHEC
    assert "créneau figé" in verdict["detail"]


def test_un_plan_qui_echoue_au_validateur_n_est_jamais_rendu(monkeypatch):
    monkeypatch.setattr(tournees, "_verifier", lambda problem, sortie: ["violation simulée"])
    sortie, verdict = tournees.resoudre(_de_instance("journee-8-competence-rare"), "dp")
    assert sortie is None
    assert verdict["code"] == tournees.CODE_PLAN_INVALIDE
    assert "violation simulée" in verdict["detail"]


# ---------------------------------------------------------------------------
# 8. Sortie canonique et meta
# ---------------------------------------------------------------------------
def _sans_flottant(valeur):
    if isinstance(valeur, dict):
        return all(isinstance(cle, str) and _sans_flottant(v) for cle, v in valeur.items())
    if isinstance(valeur, list):
        return all(_sans_flottant(v) for v in valeur)
    return valeur is None or type(valeur) in (str, int, bool)


@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_la_sortie_est_canonique_triee_entiere_et_scellee(moteur):
    _exiger(moteur)
    entree = _de_instance("deux-jours-9")
    sortie = _resoudre(entree, moteur)
    assert _sans_flottant(sortie)
    assert json.loads(json.dumps(sortie)) == sortie
    cles = [(route["equipe"], route["jour"]) for route in sortie["plan"]]
    assert cles == sorted(cles)
    for route in sortie["plan"]:
        debuts = [v["debut_min"] for v in route["visites"]]
        assert debuts == sorted(debuts)
    ids_non_cedulees = [ligne["chantier"] for ligne in sortie["non_cedulees"]]
    assert ids_non_cedulees == sorted(ids_non_cedulees)
    meta = sortie["meta"]
    assert sorted(meta) == sorted(tournees._CLES_META)
    assert meta["empreinte_entree"] == tournees._preparer(entree)[0]["empreinte_entree"]
    sans_empreinte = {**sortie, "meta": {c: v for c, v in meta.items() if c != "empreinte_sortie"}}
    assert meta["empreinte_sortie"] == encodage.empreinte(sans_empreinte)
    assert meta["mode_distance"] == "haversine_detour"
    assert meta["mode_bride"] is True
    assert meta["empreinte_matrice"] == entree["matrice"]["empreinte"]
    assert sortie["totaux"]["chantiers_cedules"] + sortie["totaux"]["chantiers_non_cedules"] == 9


@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_les_totaux_et_les_horaires_se_recalculent_a_la_main(moteur):
    _exiger(moteur)
    entree = _de_instance("journee-8-competence-rare")
    sortie = _resoudre(entree, moteur)
    matrice = entree["matrice"]
    rang = {identifiant: k for k, identifiant in enumerate(matrice["ids"])}
    distance_totale = 0
    for route in sortie["plan"]:
        lieu, distance = route["depot"], 0
        for visite in route["visites"]:
            distance += matrice["metres"][rang[lieu]][rang[visite["chantier"]]]
            lieu = visite["chantier"]
        distance += matrice["metres"][rang[lieu]][rang[route["depot"]]]
        assert route["distance_m"] == distance
        distance_totale += distance
    assert sortie["totaux"]["distance_m"] == distance_totale
    cout = sum(60000 * (1 + c["urgence"]) for c in entree["chantiers"] if c["id"] in _non_cedulees(sortie))
    assert sortie["totaux"]["cout_non_cedule_m"] == cout
    assert sortie["totaux"]["cout_total_m"] == distance_totale + cout


def test_le_mode_distance_de_la_matrice_passe_dans_meta_mode_routier_compris():
    ids = ["ch-01", "ch-02", "depot-repentigny"]
    points = [
        {
            "id": i,
            "latitude_microdeg": SITES[i]["latitude_microdeg"],
            "longitude_microdeg": SITES[i]["longitude_microdeg"],
        }
        for i in ids
    ]
    base = distances.matrice_palier0(points, PARAMS_DISTANCE)[0]
    marge = PARAMS_DISTANCE["marge_par_trajet_secondes"]

    class FournisseurFictif:
        def descripteur(self):
            return {"mode_distance": "routier_fictif", "version_donnees": "fictif"}

        def trajets(self, pts):
            n = len(pts)
            return {
                "metres": base["metres"],
                "secondes": [[0 if i == j else base["secondes"][i][j] - marge for j in range(n)] for i in range(n)],
            }, None

    matrice, verdict = distances.obtenir_matrice(points, PARAMS_DISTANCE, FournisseurFictif())
    assert verdict is None
    assert matrice["mode_distance"] == "routier_fictif"
    entree = _entree(_une_equipe(), [_chantier("ch-01"), _chantier("ch-02")])
    entree["matrice"] = matrice
    sortie = _resoudre(entree)
    assert sortie["meta"]["mode_distance"] == "routier_fictif"
    assert sortie["meta"]["mode_bride"] is False
    _accepte(entree, sortie)


# ---------------------------------------------------------------------------
# 9. Déterminisme : mêmes octets, dans le processus et entre interpréteurs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_deux_executions_donnent_les_memes_octets(moteur):
    _exiger(moteur)
    for nom in sorted(INSTANCES):
        premiere = _octets(_resoudre(_de_instance(nom), moteur))
        seconde = _octets(_resoudre(_de_instance(nom), moteur))
        assert premiere == seconde, nom


_PROGRAMME = """
import hashlib, importlib.util, sys
spec = importlib.util.spec_from_file_location("aide_tournees", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
empreinte = hashlib.sha256()
for nom in sorted(module.INSTANCES):
    for moteur in sys.argv[2:]:
        sortie, verdict = module.tournees.resoudre(module._de_instance(nom), moteur)
        assert verdict is None, verdict
        empreinte.update(module._octets(sortie))
print(empreinte.hexdigest())
"""


@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_memes_octets_dans_des_interpreteurs_aux_graines_de_hachage_differentes(moteur):
    """PYTHONHASHSEED 1, 2, 3 (R15 §1) : même sortie octet pour octet, et même que dans ce processus."""
    _exiger(moteur)
    attendu = __import__("hashlib").sha256()
    for nom in sorted(INSTANCES):
        attendu.update(_octets(_resoudre(_de_instance(nom), moteur)))
    empreintes = set()
    for graine in ("1", "2", "3", "4242"):
        environnement = {**os.environ, "PYTHONHASHSEED": graine, "PYTHONPATH": os.pathsep.join(sys.path)}
        resultat = subprocess.run(
            [sys.executable, "-c", _PROGRAMME, str(Path(__file__).resolve()), moteur],
            capture_output=True, text=True, env=environnement, check=True,
        )
        empreintes.add(resultat.stdout.strip())
    assert empreintes == {attendu.hexdigest()}


def test_importer_le_module_n_importe_pas_pyvrp():
    programme = "import sys; import m4_field_ops.tournees; print('pyvrp' in sys.modules)"
    resultat = subprocess.run(
        [sys.executable, "-c", programme], capture_output=True, text=True, check=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert resultat.stdout.strip() == "False"


def test_le_dp_seul_ne_charge_jamais_pyvrp():
    programme = (
        "import sys, json; from m4_field_ops import tournees;"
        "import importlib.util;"
        "spec = importlib.util.spec_from_file_location('aide', sys.argv[1]);"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "s, v = tournees.resoudre(m._de_instance('deux-jours-9'), 'dp');"
        "assert v is None; print('pyvrp' in sys.modules)"
    )
    resultat = subprocess.run(
        [sys.executable, "-c", programme, str(Path(__file__).resolve())], capture_output=True, text=True,
        check=True, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert resultat.stdout.strip() == "False"


# ---------------------------------------------------------------------------
# 10. PyVRP : écart 0 avec le DP exact, compétences, graine, arrêt
# ---------------------------------------------------------------------------
def test_les_instances_fictives_couvrent_de_huit_a_douze_chantiers():
    tailles = sorted(len(instance["chantiers"]) for instance in INSTANCES.values())
    assert len(tailles) >= 5
    assert min(tailles) == 8
    assert max(tailles) == 12
    assert all(instance["fictif"] is True for instance in INSTANCES.values())
    assert FIXTURE["fictif"] is True
    assert all(site["coordonnees_approximatives"] is True for site in FIXTURE["sites"])


@pytest.mark.parametrize("nom", sorted(INSTANCES))
def test_pyvrp_egale_l_optimum_exact_du_dp_avec_un_ecart_de_zero(nom):
    _exiger("pyvrp")
    entree = _de_instance(nom)
    exact = _resoudre(entree, "dp")
    heuristique = _resoudre(entree, "pyvrp")
    assert heuristique["totaux"]["cout_total_m"] - exact["totaux"]["cout_total_m"] == 0
    _accepte(entree, exact)
    _accepte(entree, heuristique)
    assert heuristique["meta"]["solveur"] == "pyvrp"
    assert heuristique["meta"]["version_solveur"] == "0.14.0"


def test_auto_choisit_pyvrp_quand_il_est_installe_et_le_dp_sinon(monkeypatch):
    _exiger("pyvrp")
    entree = _de_instance("journee-8-competence-rare")
    assert _resoudre(entree, "auto")["meta"]["solveur"] == "pyvrp"
    monkeypatch.setattr(tournees, "_version_pyvrp", lambda: (None, "pyvrp absent"))
    assert _resoudre(entree, "auto")["meta"]["solveur"] == "dp-exact"


def test_pyvrp_resout_aussi_au_dela_de_la_limite_du_dp():
    _exiger("pyvrp")
    entree = _entree_de_taille(14)
    sortie = _resoudre(entree, "auto")
    assert sortie["meta"]["solveur"] == "pyvrp"
    assert sortie["totaux"]["chantiers_cedules"] >= 12
    _accepte(entree, sortie)


def test_pyvrp_tient_un_creneau_fige_et_une_urgence_comme_le_dp():
    _exiger("pyvrp")
    entree = _de_instance("fenetres-serrees-12")
    for chantier in entree["chantiers"]:
        if chantier["id"] == "ch-13":
            chantier["creneau_fige"] = {"equipe": "eq-c", "jour": 0, "debut_min": 900}
    exact = _resoudre(entree, "dp")
    heuristique = _resoudre(entree, "pyvrp")
    assert _visites(heuristique)["ch-13"] == ("eq-c", 0, 900)
    assert heuristique["totaux"]["cout_total_m"] == exact["totaux"]["cout_total_m"]
    _accepte(entree, heuristique)


@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_une_competence_rare_n_est_jamais_donnee_a_une_equipe_non_admissible(moteur):
    """eq-a (dépôt de Repentigny) n'a pas la toiture ; la donner à eq-b (dépôt de Joliette) coûte plus cher."""
    _exiger(moteur)
    instance = INSTANCES["competence-rare-10"]
    rares = {c["id"] for c in instance["chantiers"] if "toiture" in c["competences_requises"]}
    assert rares == {"ch-01", "ch-03", "ch-13"}
    servis = 0
    for graine in range(12):  # la graine change l'empreinte, donc la graine dérivée : autant de recherches
        entree = _entree(
            instance["equipes"], instance["chantiers"],
            {**instance["parametres"], "graine": graine, "cout_non_cedule_m": 10**6},
        )
        sortie = _resoudre(entree, moteur)
        _accepte(entree, sortie)
        for route in sortie["plan"]:
            for visite in route["visites"]:
                if visite["chantier"] in rares:
                    assert route["equipe"] == "eq-b", (graine, route["equipe"], visite["chantier"])
                    servis += 1
    assert servis >= 12  # le test n'est pas vide : les chantiers rares sont bien cédulés


@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_la_tentation_est_reelle_sans_la_contrainte_de_competence(moteur):
    """Sans la contrainte, le chantier de toiture de Repentigny irait à l'équipe voisine de son dépôt."""
    _exiger(moteur)
    chantiers = [_chantier("ch-01", competences=["toiture"]), _chantier("ch-02")]
    parametres = {**PARAMS, "cout_non_cedule_m": 10**6}
    tentees = [_equipe("eq-a", ["toiture"]), _equipe("eq-b", ["toiture"], "depot-joliette")]
    assert _visites(_resoudre(_entree(tentees, chantiers, parametres), moteur))["ch-01"][0] == "eq-a"
    contraintes = [_equipe("eq-a"), _equipe("eq-b", ["toiture"], "depot-joliette")]
    assert _visites(_resoudre(_entree(contraintes, chantiers, parametres), moteur))["ch-01"][0] == "eq-b"


def test_pyvrp_est_appele_avec_max_iterations_et_la_graine_derivee_de_l_entree(monkeypatch):
    _exiger("pyvrp")
    pyvrp = importlib.import_module("pyvrp")
    appels = []
    original = pyvrp.Model.solve

    def espion(self, stop, seed=0, *args, **kwargs):
        appels.append((type(stop).__name__, seed, stop._max_iters))
        return original(self, stop, seed, *args, **kwargs)

    monkeypatch.setattr(pyvrp.Model, "solve", espion)
    entree = _de_instance("journee-8-competence-rare")
    sortie = _resoudre(entree, "pyvrp")
    meta = sortie["meta"]
    assert appels == [("MaxIterations", int(meta["empreinte_entree"][:8], 16), entree["parametres"]["iterations"])]
    assert meta["graine"] == appels[0][1]
    assert meta["iterations"] == entree["parametres"]["iterations"]
    autre = copy.deepcopy(entree)
    autre["parametres"]["graine"] += 1
    assert _resoudre(autre, "pyvrp")["meta"]["graine"] != meta["graine"]


@pytest.mark.parametrize("moteur", MOTEURS_TEST)
def test_huit_chantiers_en_moins_d_une_seconde(moteur):
    _exiger(moteur)
    entree = _de_instance("journee-8-competence-rare")
    assert len(entree["chantiers"]) == 8
    _resoudre(entree, moteur)  # échauffement : premier import de PyVRP et de numpy
    debut = time.perf_counter()
    sortie = _resoudre(entree, moteur)
    duree = time.perf_counter() - debut
    assert duree < 1.0, f"{moteur} : {duree:.2f} s"
    assert sortie["plan"]


def test_huit_chantiers_en_moins_d_une_seconde_meme_au_premier_appel_pyvrp():
    """Interpréteur neuf : l'import paresseux de PyVRP (et de numpy) est compris dans la seconde."""
    _exiger("pyvrp")
    programme = (
        "import importlib.util, sys, time;"
        "spec = importlib.util.spec_from_file_location('aide', sys.argv[1]);"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "entree = m._de_instance('journee-8-competence-rare');"
        "t = time.perf_counter();"
        "s, v = m.tournees.resoudre(entree, 'pyvrp');"
        "print(v is None, time.perf_counter() - t)"
    )
    resultat = subprocess.run(
        [sys.executable, "-c", programme, str(Path(__file__).resolve())], capture_output=True, text=True,
        check=True, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    valide, duree = resultat.stdout.split()
    assert valide == "True"
    assert float(duree) < 1.0, resultat.stdout


# ---------------------------------------------------------------------------
# 11. Gardes de code : module pur, ni horloge ni aléa, PyVRP en import paresseux
# ---------------------------------------------------------------------------
def _arbre():
    return ast.parse((_SRC / "tournees.py").read_text(encoding="utf-8"))


def test_tournees_n_importe_que_la_stdlib_pure_et_pyvrp_n_est_charge_que_paresseusement():
    arbre = _arbre()
    modules = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0:
            modules.add((noeud.module or "").split(".")[0])
    assert modules == {"__future__", "importlib"}  # ni time, ni datetime, ni random, ni os, ni réseau
    paresseux = {
        noeud.args[0].value for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name) and noeud.func.id == "import_module"
        and noeud.args and isinstance(noeud.args[0], ast.Constant)
    }
    assert {"pyvrp", "pyvrp.stop", "pyvrp.constants"} <= paresseux
    for noeud in arbre.body:  # aucun import de pyvrp au niveau du module
        assert not isinstance(noeud, (ast.Import, ast.ImportFrom)) or "pyvrp" not in ast.dump(noeud)


def test_tournees_n_a_ni_horloge_ni_alea_ni_flottant():
    arbre = _arbre()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Constant):
            assert not isinstance(noeud.value, float), noeud.lineno
        if isinstance(noeud, (ast.BinOp, ast.AugAssign)):
            assert not isinstance(noeud.op, ast.Div), noeud.lineno
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"float", "round", "random", "time", "datetime"}, (noeud.id, noeud.lineno)
        if isinstance(noeud, ast.Call):
            nom = noeud.func.attr if isinstance(noeud.func, ast.Attribute) else getattr(noeud.func, "id", None)
            assert nom not in digest.FONCTIONS_HORLOGE_INTERDITES, (nom, noeud.lineno)
    texte = (_SRC / "tournees.py").read_text(encoding="utf-8")
    for interdit in ("MaxRuntime", "NoImprovement", "MultipleCriteria", "FirstFeasible", "random."):
        assert interdit not in texte, interdit
    assert "MaxIterations" in texte


def test_les_gardes_du_paquet_passent_avec_le_nouveau_module():
    assert digest.garde_absence_horloge() == (True, "")
    assert digest.garde_conformite_r020() == (True, "")
