"""PLAN T4.12 (M4.3) : `admissibilite.py`, pur. Une équipe est admissible pour un service si elle détient TOUTES ses
compétences ET a un quart assez long pour sa durée ; le profil est un dict, aucune base, aucun `opsys`.

Fixture FICTIVE (`fictif: true`) : `fixtures/equipes_repentigny_joliette.json`.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from m4_field_ops import admissibilite, verdicts

_SRC = Path(admissibilite.__file__).resolve()
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "equipes_repentigny_joliette.json").read_text("utf-8"))


def profil():
    assert FIXTURE["fictif"] is True
    return copy.deepcopy(FIXTURE["profil"])


def _profil_de_deux_equipes():
    """eq-a : gouttières et revêtement, un quart de 540 minutes ; eq-b : gouttières seulement, un quart de 200."""
    base = profil()
    base["liste"][1]["competences"] = ["gouttieres"]
    base["liste"][1]["quarts"] = [{"jour": 0, "debut_min": 480, "fin_min": 680}]
    return base


class TestAdmissibilite:
    def test_une_equipe_qui_a_toutes_les_competences_et_un_quart_assez_long_est_admissible(self):
        resultat, verdict = admissibilite.equipes_admissibles(profil(), "ravalement")
        assert verdict is None
        assert resultat == {
            "service": "ravalement", "duree_min": 120, "competences_requises": ["revetement"],
            "admissibles": ["eq-a", "eq-b"], "ecartees": [],
        }

    def test_une_competence_manquante_ecarte_l_equipe_et_dit_laquelle(self):
        resultat, _ = admissibilite.equipes_admissibles(_profil_de_deux_equipes(), "ravalement")
        assert resultat["admissibles"] == ["eq-a"]
        assert resultat["ecartees"] == [{
            "equipe": "eq-b", "code": admissibilite.CODE_COMPETENCE_MANQUANTE,
            "detail": "compétence manquante : revetement",
        }]

    def test_toutes_les_competences_sont_exigees_pas_une_seule(self):
        brut = profil()
        brut["services"]["ravalement"]["competences"] = ["gouttieres", "revetement", "echafaudage"]
        brut["liste"][1]["competences"] = ["gouttieres", "revetement", "echafaudage"]
        resultat, _ = admissibilite.equipes_admissibles(brut, "ravalement")
        assert resultat["admissibles"] == ["eq-b"]
        assert resultat["ecartees"][0]["detail"] == "compétence manquante : echafaudage"

    def test_plusieurs_competences_manquantes_sont_toutes_nommees_dans_l_ordre(self):
        brut = profil()
        brut["services"]["ravalement"]["competences"] = ["zinc", "acrobatie", "revetement"]
        resultat, _ = admissibilite.equipes_admissibles(brut, "ravalement")
        assert resultat["admissibles"] == []
        assert {e["detail"] for e in resultat["ecartees"]} == {"compétence manquante : acrobatie, zinc"}

    def test_un_service_sans_competence_requise_est_ouvert_a_toute_equipe(self):
        resultat, _ = admissibilite.equipes_admissibles(profil(), "extension")
        assert resultat["competences_requises"] == [] and resultat["admissibles"] == ["eq-a", "eq-b"]

    def test_un_quart_trop_court_ecarte_l_equipe_et_dit_le_plus_long(self):
        brut = _profil_de_deux_equipes()
        brut["liste"][1]["competences"] = ["gouttieres", "revetement"]  # eq-b a la compétence, mais un quart de 200
        resultat, _ = admissibilite.equipes_admissibles(brut, "ravalement")  # ravalement : 120 <= 200
        assert resultat["admissibles"] == ["eq-a", "eq-b"]
        resultat, _ = admissibilite.equipes_admissibles(brut, "extension")  # extension : 150 <= 200
        assert resultat["admissibles"] == ["eq-a", "eq-b"]
        resultat, _ = admissibilite.equipes_admissibles(brut, "renovation_totale")  # 180 <= 200
        assert resultat["admissibles"] == ["eq-a", "eq-b"]
        brut["services"]["renovation_totale"]["duree_min"] = 201
        resultat, _ = admissibilite.equipes_admissibles(brut, "renovation_totale")
        assert resultat["admissibles"] == ["eq-a"]
        assert resultat["ecartees"] == [{
            "equipe": "eq-b", "code": admissibilite.CODE_AUCUN_QUART_ASSEZ_LONG,
            "detail": "aucun quart d'au moins 201 minutes (le plus long : 200 minutes)",
        }]

    def test_une_duree_egale_a_la_longueur_du_quart_passe_une_minute_de_plus_ne_passe_pas(self):
        brut = profil()
        brut["services"]["autre"]["duree_min"] = 540  # le quart de 480 à 1020 fait 540 minutes
        assert admissibilite.equipes_admissibles(brut, "autre")[0]["admissibles"] == ["eq-a", "eq-b"]
        brut["services"]["autre"]["duree_min"] = 541
        resultat, _ = admissibilite.equipes_admissibles(brut, "autre")
        assert resultat["admissibles"] == [] and len(resultat["ecartees"]) == 2

    def test_seul_le_plus_long_des_quarts_compte(self):
        brut = profil()
        brut["liste"][0]["quarts"] = [
            {"jour": 0, "debut_min": 480, "fin_min": 500}, {"jour": 1, "debut_min": 480, "fin_min": 1000},
        ]
        assert "eq-a" in admissibilite.equipes_admissibles(brut, "ravalement")[0]["admissibles"]
        brut["services"]["ravalement"]["duree_min"] = 521
        assert "eq-a" not in admissibilite.equipes_admissibles(brut, "ravalement")[0]["admissibles"]

    def test_la_competence_est_examinee_avant_le_quart(self):
        brut = _profil_de_deux_equipes()
        brut["services"]["ravalement"]["duree_min"] = 900  # aucun des deux quarts n'y suffit
        resultat, _ = admissibilite.equipes_admissibles(brut, "ravalement")
        codes = {e["equipe"]: e["code"] for e in resultat["ecartees"]}
        assert codes == {
            "eq-a": admissibilite.CODE_AUCUN_QUART_ASSEZ_LONG, "eq-b": admissibilite.CODE_COMPETENCE_MANQUANTE,
        }

    def test_le_resultat_est_trie_et_ne_depend_pas_de_l_ordre_du_profil(self):
        brut = profil()
        renverse = copy.deepcopy(brut)
        renverse["liste"].reverse()
        assert admissibilite.equipes_admissibles(brut, "autre") == admissibilite.equipes_admissibles(renverse, "autre")
        assert admissibilite.equipes_admissibles(brut, "autre")[0]["admissibles"] == ["eq-a", "eq-b"]

    def test_le_profil_n_est_pas_modifie(self):
        brut = profil()
        avant = json.dumps(brut, sort_keys=True)
        admissibilite.equipes_admissibles(brut, "ravalement")
        admissibilite.exigences_du_service(brut, "ravalement")
        assert json.dumps(brut, sort_keys=True) == avant

    def test_le_resultat_ne_porte_aucune_note_ni_classement_ni_membre(self):
        resultat, _ = admissibilite.equipes_admissibles(_profil_de_deux_equipes(), "ravalement")
        texte = json.dumps(resultat, ensure_ascii=False)
        for interdit in ("score", "note", "classement", "rang", "performance", "fiabilite", "luc.fictif", "membres"):
            assert interdit not in texte, interdit


class TestSansSource:
    @pytest.mark.parametrize("profil_vide", [None, {}, {"liste": []}, {"services": {}}, "profil", []])
    def test_sans_durees_ni_competences_par_service_c_est_un_verdict_qui_dit_quoi_declarer(self, profil_vide):
        resultat, verdict = admissibilite.equipes_admissibles(profil_vide, "ravalement")
        assert resultat is None and verdict["code"] == "REJ-CHAMP-MANQUANT"
        assert "durée et compétences par service non déclarées" in verdict["detail"]
        assert "opsys-metier equipes declarer" in verdict["detail"]

    def test_un_service_absent_du_profil_est_nomme_jamais_devine(self):
        resultat, verdict = admissibilite.equipes_admissibles(profil(), "soffite_fascia")
        assert resultat is None and verdict["code"] == "REJ-CHAMP-MANQUANT"
        assert "'soffite_fascia'" in verdict["detail"] and "opsys-metier equipes declarer" in verdict["detail"]

    def test_sans_equipe_declaree_c_est_un_verdict_pas_une_liste_vide(self):
        brut = profil()
        del brut["liste"]
        resultat, verdict = admissibilite.equipes_admissibles(brut, "ravalement")
        assert resultat is None and verdict["code"] == "REJ-CHAMP-MANQUANT"
        assert "aucune équipe déclarée" in verdict["detail"]
        brut["liste"] = []
        assert admissibilite.equipes_admissibles(brut, "ravalement")[0] is None

    def test_exigences_du_service(self):
        exigences, verdict = admissibilite.exigences_du_service(profil(), "ravalement")
        assert verdict is None and exigences == {"duree_min": 120, "competences": ["revetement"]}
        assert admissibilite.exigences_du_service(profil(), "inconnu")[0] is None


# ---------------------------------------------------------------------------------------------
# Garde par analyse du code : pur (aucun opsys, aucune horloge, aucun aléa, aucun réseau)
# ---------------------------------------------------------------------------------------------
def _arbre():
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_le_module_est_pur_sans_opsys_ni_horloge_ni_alea():
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Import):
            assert all(alias.name == "__future__" for alias in noeud.names), noeud.names
        if isinstance(noeud, ast.ImportFrom):
            assert noeud.module == "__future__" or noeud.level == 1, (noeud.module, noeud.level)
            if noeud.level == 1:
                assert {a.name for a in noeud.names} == {"verdicts"}
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"now", "utcnow", "today", "time", "random", "urandom", "monotonic"}
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"random", "time", "datetime", "socket", "float"}


def test_aucun_stub_ni_todo_dans_le_module():
    texte = _SRC.read_text(encoding="utf-8")
    assert "TODO" not in texte and "FIXME" not in texte and "NotImplementedError" not in texte
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.FunctionDef):
            corps = [n for n in noeud.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            assert corps and not all(isinstance(n, ast.Pass) for n in corps), noeud.name


def test_les_verdicts_du_module_sont_tous_au_catalogue():
    codes = {
        n.value for n in ast.walk(_arbre())
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("REJ-")
    }
    assert codes == {"REJ-CHAMP-MANQUANT"} and codes <= verdicts.CODES_M4
