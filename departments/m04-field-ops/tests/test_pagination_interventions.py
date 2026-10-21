"""PLAN T4.27-a : `pagination_interventions.py`, pur, sur des lignes de liste FICTIVES (`fictif: true`).

Ce que la pagination doit prouver, sans base ni réseau :

  * l'ordre est stable et total (identifiant croissant), le curseur est l'identifiant de la dernière ligne lue : toutes
    les lignes, une seule fois, quelle que soit la taille de page ; une ligne qui naît entre deux pages ne fait ni
    sauter ni répéter une ligne déjà lue ;
  * une page ne dépasse jamais la borne que l'appelant mesure (la plus grande qui tient), a au moins une ligne, et dit
    qu'elle a été raccourcie (`borne_atteinte`) ; si même une ligne ne tient pas : refus nommé, jamais une page vide ;
  * la réponse dit ce qui reste (`reste`, `curseur_suivant` nul à la fin) ; un curseur au-delà de la fin donne une page
    vide qui le dit ;
  * un curseur ou une taille mal formés sont refusés avec ce qu'il faut corriger, rien n'est corrigé en silence ;
  * les lignes rendues sont celles de la liste v1, telles quelles (aucune clé ajoutée, retirée ni renommée).

Le scénario par les vrais outils, la base et la porte d'appareil : `test_lister_interventions_pages.py` et
`tests/e2e/test_lectures_admin_m4_appareil.py`.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from m4_field_ops import pagination_interventions as pages
from m4_field_ops import verdicts

FICTIF = True
_SRC = Path(pages.__file__).resolve()
CLES_LIGNE = ("intervention_id", "statut", "lead_id", "service", "devis_id", "technicien_assigne", "fenetre_planifiee")


def _id(numero: int) -> str:
    return f"{numero:064x}"


def _ligne(numero: int) -> dict:
    return {
        "intervention_id": _id(numero),
        "statut": "planifiee",
        "lead_id": f"LEAD-{numero:03d}-fictif",
        "service": "gouttieres",
        "devis_id": f"DEVIS-{numero:03d}-fictif",
        "technicien_assigne": "eq-a",
        "fenetre_planifiee": None,
    }


def _liste(nombre: int) -> list[dict]:
    return [_ligne(numero) for numero in range(1, nombre + 1)]


def _toujours(_page) -> bool:
    return True


def _taille(page) -> int:
    return len(json.dumps({"ok": True, "resultat": page}, ensure_ascii=False))


def _lire_tout(lignes, taille_page=None, tient=_toujours, maximum=200):
    """Comme l'app : première page sans curseur, puis `curseur_suivant` tant qu'il n'est pas nul."""
    pages_lues, curseur = [], None
    for _ in range(maximum):
        page, verdict = pages.paginer(lignes, curseur, taille_page, tient)
        assert verdict is None, verdict
        pages_lues.append(page)
        curseur = page["page"]["curseur_suivant"]
        if curseur is None:
            return pages_lues
    raise AssertionError("la lecture ne progresse pas")


def _code(verdict) -> str:
    assert verdict is not None
    return verdict["code"]


# =========================================================================================
# 1. L'ordre et la couverture : toutes les lignes, une seule fois
# =========================================================================================
@pytest.mark.parametrize("taille", [None, 1, 2, 3, 7, 10, 24, 25, 26, 50])
def test_toutes_les_lignes_une_seule_fois_dans_l_ordre_quelle_que_soit_la_taille_de_page(taille):
    lignes = _liste(25)
    lues = _lire_tout(lignes, taille)
    ids = [ligne["intervention_id"] for page in lues for ligne in page["interventions"]]
    assert ids == [_id(numero) for numero in range(1, 26)]
    assert len(set(ids)) == 25


def test_l_ordre_ne_depend_pas_de_l_ordre_d_entree():
    lignes = _liste(12)
    melangees = [lignes[index] for index in (7, 2, 11, 0, 5, 9, 1, 10, 3, 8, 4, 6)]
    page, verdict = pages.paginer(melangees, None, 5, _toujours)
    assert verdict is None
    assert [ligne["intervention_id"] for ligne in page["interventions"]] == [_id(n) for n in range(1, 6)]
    assert page["page"]["curseur_suivant"] == _id(5)


def test_l_ordre_est_celui_de_l_identifiant_en_texte_pas_du_rang_de_creation():
    lignes = [_ligne(numero) for numero in (0xF0, 0x0A, 0xB1)]
    page, _ = pages.paginer(lignes, None, None, _toujours)
    assert [ligne["intervention_id"] for ligne in page["interventions"]] == sorted(_id(n) for n in (0xF0, 0x0A, 0xB1))
    assert pages.ORDRE == "intervention_id croissant"
    assert page["page"]["ordre"] == pages.ORDRE


def test_les_lignes_rendues_sont_celles_de_la_liste_v1_telles_quelles_et_en_copie():
    lignes = _liste(3)
    avant = copy.deepcopy(lignes)
    page, _ = pages.paginer(lignes, None, None, _toujours)
    assert page["interventions"] == avant
    assert all(set(ligne) == set(CLES_LIGNE) for ligne in page["interventions"])
    page["interventions"][0]["statut"] = "modifiee"
    assert lignes == avant, "la page est une copie : la liste d'entrée n'est jamais touchée"


def test_une_ligne_de_lead_v1_garde_type_travaux_sans_service():
    ligne = _ligne(1)
    del ligne["service"]
    ligne["type_travaux"] = "renovation_totale"
    page, _ = pages.paginer([ligne], None, None, _toujours)
    assert page["interventions"] == [ligne] and "service" not in page["interventions"][0]


def test_deux_lectures_donnent_les_memes_pages():
    lignes = _liste(17)
    assert _lire_tout(lignes, 4) == _lire_tout(copy.deepcopy(lignes), 4)


# =========================================================================================
# 2. La réponse dit ce qui reste
# =========================================================================================
def test_la_page_dit_ou_l_on_en_est():
    lignes = _liste(10)
    page, verdict = pages.paginer(lignes, None, 4, _toujours)
    assert verdict is None
    assert page["page"] == {
        "ordre": "intervention_id croissant",
        "curseur": None,
        "taille_demandee": 4,
        "taille": 4,
        "total": 10,
        "reste": 6,
        "curseur_suivant": _id(4),
        "borne_atteinte": False,
    }
    suivante, _ = pages.paginer(lignes, _id(4), 4, _toujours)
    assert suivante["page"]["curseur"] == _id(4) and suivante["page"]["total"] == 10
    assert suivante["page"]["taille"] == 4 and suivante["page"]["reste"] == 2
    assert suivante["page"]["curseur_suivant"] == _id(8)
    derniere, _ = pages.paginer(lignes, _id(8), 4, _toujours)
    assert (derniere["page"]["taille"], derniere["page"]["reste"]) == (2, 0)
    assert derniere["page"]["curseur_suivant"] is None, "nul à la fin : rien à lire de plus"


def test_une_liste_qui_tient_en_une_page_ne_donne_pas_de_curseur_suivant():
    page, _ = pages.paginer(_liste(3), None, None, _toujours)
    assert page["page"]["reste"] == 0 and page["page"]["curseur_suivant"] is None
    assert page["page"]["taille"] == page["page"]["total"] == 3 and page["page"]["borne_atteinte"] is False


def test_une_liste_vide_donne_une_page_vide_qui_le_dit():
    page, verdict = pages.paginer([], None, None, _toujours)
    assert verdict is None and page["interventions"] == []
    assert (page["page"]["taille"], page["page"]["total"], page["page"]["reste"]) == (0, 0, 0)
    assert page["page"]["curseur_suivant"] is None and page["page"]["borne_atteinte"] is False


@pytest.mark.parametrize("numero", [25, 26, 1000])
def test_un_curseur_au_dela_de_la_derniere_ligne_donne_une_page_vide_jamais_une_erreur(numero):
    page, verdict = pages.paginer(_liste(25), _id(numero), 5, _toujours)
    assert verdict is None and page["interventions"] == []
    assert page["page"]["reste"] == 0 and page["page"]["curseur_suivant"] is None
    assert page["page"]["total"] == 25, "le total compte toute la liste, curseur ou non"
    assert page["page"]["curseur"] == _id(numero)


def test_le_total_ne_depend_pas_du_curseur_et_le_reste_ne_compte_que_ce_qui_suit_la_page():
    lignes = _liste(20)
    for curseur, reste in ((None, 15), (_id(5), 10), (_id(12), 3), (_id(20), 0)):
        page, _ = pages.paginer(lignes, curseur, 5, _toujours)
        assert page["page"]["total"] == 20
        assert page["page"]["reste"] == reste, curseur


def test_le_curseur_n_a_pas_besoin_d_etre_celui_d_une_ligne_qui_existe_encore():
    """Une ligne disparue (ou jamais vue) ne casse pas la lecture : le curseur n'est qu'une borne inférieure."""
    lignes = [_ligne(numero) for numero in (2, 4, 6, 8)]
    page, verdict = pages.paginer(lignes, _id(5), 10, _toujours)
    assert verdict is None
    assert [ligne["intervention_id"] for ligne in page["interventions"]] == [_id(6), _id(8)]


# =========================================================================================
# 3. Une ligne qui naît entre deux pages ne fait ni sauter ni répéter une ligne déjà lue
# =========================================================================================
def test_une_ligne_qui_nait_avant_le_curseur_ne_repete_rien_et_se_lit_a_la_relecture():
    lignes = [_ligne(numero) for numero in (10, 20, 30, 40, 50, 60)]
    premiere, _ = pages.paginer(lignes, None, 3, _toujours)
    assert [ligne["intervention_id"] for ligne in premiere["interventions"]] == [_id(10), _id(20), _id(30)]
    lignes.append(_ligne(15))  # naît « avant » le curseur : la lecture en cours ne la voit pas, sans rien répéter
    seconde, _ = pages.paginer(lignes, premiere["page"]["curseur_suivant"], 3, _toujours)
    assert [ligne["intervention_id"] for ligne in seconde["interventions"]] == [_id(40), _id(50), _id(60)]
    assert seconde["page"]["total"] == 7 != premiere["page"]["total"], "le signal : le total a changé, relire"
    relue = [ligne["intervention_id"] for page in _lire_tout(lignes, 3) for ligne in page["interventions"]]
    assert relue == sorted(_id(n) for n in (10, 15, 20, 30, 40, 50, 60))


def test_une_ligne_qui_nait_apres_le_curseur_vient_dans_une_page_suivante_sans_rien_sauter():
    lignes = [_ligne(numero) for numero in (10, 20, 30, 40)]
    premiere, _ = pages.paginer(lignes, None, 2, _toujours)
    lignes.append(_ligne(35))
    seconde, _ = pages.paginer(lignes, premiere["page"]["curseur_suivant"], 2, _toujours)
    assert [ligne["intervention_id"] for ligne in seconde["interventions"]] == [_id(30), _id(35)]
    troisieme, _ = pages.paginer(lignes, seconde["page"]["curseur_suivant"], 2, _toujours)
    assert [ligne["intervention_id"] for ligne in troisieme["interventions"]] == [_id(40)]


def test_une_ligne_qui_disparait_entre_deux_pages_ne_fait_rien_sauter():
    lignes = _liste(9)
    premiere, _ = pages.paginer(lignes, None, 3, _toujours)
    restantes = [ligne for ligne in lignes if ligne["intervention_id"] != _id(2)]
    seconde, _ = pages.paginer(restantes, premiere["page"]["curseur_suivant"], 3, _toujours)
    assert [ligne["intervention_id"] for ligne in seconde["interventions"]] == [_id(4), _id(5), _id(6)]


# =========================================================================================
# 4. La borne : la plus grande page qui tient, au moins une ligne, jamais une page coupée
# =========================================================================================
def test_la_page_est_la_plus_grande_qui_tient_dans_la_borne_mesuree():
    lignes = _liste(30)
    # la taille exacte d'une page de six lignes, sans taille demandée
    six, _ = pages.paginer(lignes, None, None, lambda p: p["page"]["taille"] <= 6)
    assert six["page"]["taille"] == 6
    borne = _taille(six)
    page, verdict = pages.paginer(lignes, None, None, lambda p: _taille(p) <= borne)
    assert verdict is None
    assert page["page"]["taille"] == 6 and _taille(page) <= borne
    assert page["page"]["borne_atteinte"] is True
    sept, _ = pages.paginer(lignes, None, None, lambda p: p["page"]["taille"] <= 7)
    assert _taille(sept) > borne, "sept lignes n'auraient pas tenu : la page en a exactement six"


def test_avec_taille_page_plus_petite_que_la_borne_la_borne_n_est_pas_atteinte():
    lignes = _liste(30)
    page, _ = pages.paginer(lignes, None, 4, lambda p: _taille(p) <= 5500)
    assert page["page"]["taille"] == 4 and page["page"]["borne_atteinte"] is False


def test_avec_taille_page_plus_grande_que_la_borne_la_page_est_raccourcie_et_le_dit():
    lignes = _liste(50)
    page, _ = pages.paginer(lignes, None, 50, lambda p: _taille(p) <= 3000)
    assert 1 <= page["page"]["taille"] < 50 and _taille(page) <= 3000
    assert page["page"]["taille_demandee"] == 50 and page["page"]["borne_atteinte"] is True
    assert page["page"]["reste"] == 50 - page["page"]["taille"]
    assert page["page"]["curseur_suivant"] == page["interventions"][-1]["intervention_id"]


def test_la_derniere_page_n_est_pas_raccourcie_par_la_borne_meme_si_elle_est_petite():
    lignes = _liste(10)
    page, _ = pages.paginer(lignes, _id(7), None, lambda p: _taille(p) <= 5500)
    assert page["page"]["taille"] == 3 and page["page"]["borne_atteinte"] is False and page["page"]["reste"] == 0


def test_toutes_les_pages_tiennent_et_couvrent_tout_meme_avec_une_borne_serree():
    lignes = _liste(40)
    lues = _lire_tout(lignes, None, lambda p: _taille(p) <= 2500)
    assert len(lues) > 3 and all(_taille(page) <= 2500 for page in lues)
    ids = [ligne["intervention_id"] for page in lues for ligne in page["interventions"]]
    assert ids == [_id(n) for n in range(1, 41)]
    assert [page["page"]["borne_atteinte"] for page in lues][:-1] == [True] * (len(lues) - 1)
    assert lues[-1]["page"]["borne_atteinte"] is False


def test_une_page_a_toujours_au_moins_une_ligne_sinon_refus_nomme_jamais_une_page_vide():
    page, verdict = pages.paginer(_liste(5), None, None, lambda p: False)
    assert page is None
    assert _code(verdict) == "REJ-CONTRAT-INVALIDE" and _id(1) in verdict["detail"]
    assert "à elle seule" in verdict["detail"]


def test_la_borne_est_mesuree_sur_la_page_complete_pas_estimee():
    vues = []

    def tient(page):
        vues.append(page["page"]["taille"])
        return page["page"]["taille"] <= 3

    page, _ = pages.paginer(_liste(10), None, None, tient)
    assert page["page"]["taille"] == 3
    assert vues == [1, 2, 3, 4], "chaque page candidate est mesurée telle qu'elle serait rendue, la première d'abord"


# =========================================================================================
# 5. Arguments : rien n'est corrigé, borné ni deviné en silence
# =========================================================================================
@pytest.mark.parametrize(
    "curseur",
    [
        "",
        "abc",
        ("ab" * 32).upper(),
        "A" * 64,
        _id(1)[:-1],
        _id(1) + "0",
        "g" * 64,
        " " + _id(1)[1:],
        _id(1) + "\n",
        42,
        ["x"],
        {"id": _id(1)},
        True,
    ],
)
def test_un_curseur_mal_forme_est_refuse_avec_ce_qu_il_faut_donner(curseur):
    page, verdict = pages.paginer(_liste(3), curseur, None, _toujours)
    assert page is None
    assert _code(verdict) == "REJ-CONTRAT-INVALIDE" and "curseur_suivant" in verdict["detail"]
    assert pages.verifier_arguments(curseur, None) == verdict


@pytest.mark.parametrize("taille", [0, -1, 51, 1000, True, False, 1.5, "3", [3], {"n": 3}])
def test_une_taille_de_page_hors_bornes_est_refusee_sans_etre_bornee_en_silence(taille):
    page, verdict = pages.paginer(_liste(3), None, taille, _toujours)
    assert page is None
    assert _code(verdict) == "REJ-CONTRAT-INVALIDE"
    assert f"1 à {pages.TAILLE_PAGE_MAX}" in verdict["detail"] and repr(taille) in verdict["detail"]


@pytest.mark.parametrize("taille", [1, 2, 25, 49, 50])
def test_les_tailles_de_page_permises(taille):
    assert pages.verifier_arguments(None, taille) is None
    assert pages.verifier_arguments(_id(3), taille) is None


def test_le_curseur_est_valide_en_premier_puis_la_taille():
    verdict = pages.verifier_arguments("pas-un-curseur", 0)
    assert "curseur" in verdict["detail"]


def test_la_forme_du_curseur_du_schema_est_celle_que_le_code_accepte():
    import re

    forme = re.compile(pages.FORME_CURSEUR)
    minuscules = "ab" * 32
    assert forme.fullmatch(_id(7)) and forme.fullmatch(minuscules)
    assert not forme.fullmatch(minuscules.upper()) and not forme.fullmatch(_id(7)[:-1])
    # la forme du schéma (`pattern`, ancrée) accepte exactement ce que `verifier_arguments` accepte
    for texte in (_id(7), minuscules, minuscules.upper(), "x" * 64, _id(7)[:-1], ""):
        assert (forme.search(texte) is not None) == (pages.verifier_arguments(texte, None) is None)


def test_taille_page_max_est_de_cinquante_comme_les_autres_listes_de_l_app():
    assert pages.TAILLE_PAGE_MAX == 50


def test_les_verdicts_du_module_sont_au_catalogue():
    _, verdict = pages.paginer(_liste(1), "x", None, _toujours)
    assert verdicts.est_verdict(verdict["code"])


# =========================================================================================
# 6. Garde par analyse du code : pur, sans stub
# =========================================================================================
def _arbre():
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_le_module_est_pur_sans_opsys_reseau_horloge_alea_ni_flottant():
    autorises = {"__future__", "re"}
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                assert alias.name in autorises, alias.name
        if isinstance(noeud, ast.ImportFrom):
            assert noeud.module in autorises or noeud.level == 1, (noeud.module, noeud.level)
            if noeud.level == 1:
                assert {a.name for a in noeud.names} == {"verdicts"}
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"now", "utcnow", "today", "time", "random", "urandom", "monotonic", "ajouter"}
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"random", "time", "datetime", "socket", "float", "opsys", "os", "sys", "open"}


def test_aucun_stub_ni_todo_dans_le_module():
    texte = _SRC.read_text(encoding="utf-8")
    assert "TODO" not in texte and "FIXME" not in texte and "NotImplementedError" not in texte
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.FunctionDef):
            corps = [n for n in noeud.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            assert corps and not all(isinstance(n, ast.Pass) for n in corps), noeud.name


def test_les_codes_de_verdict_du_module_sont_tous_au_catalogue():
    codes = {
        n.value
        for n in ast.walk(_arbre())
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("REJ-")
    }
    assert codes and codes <= verdicts.CODES_M4, codes - verdicts.CODES_M4
