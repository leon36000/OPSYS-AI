"""Contrat successeur M8 → M9.3 : preuve de définition propre à chaque observation (historiques fictifs).

Le producteur est SIMULÉ ici (pages construites par le test) : le candidat M8 privé n'est ni intégré ni lu par M9.
"""

import copy

import pytest
from m9_strategic_intelligence import preuves_definition as pd

FICTIF = True
A, B, C = "a" * 64, "b" * 64, "c" * 64


def _cle_dico(famille="finance", module="m05", ident="marge_reelle"):
    return {"famille": famille, "module": module, "id": ident}


def _pages(publications, registre="dictionnaire", taille=None, **surcharge):
    """Découpe un historique en pages cohérentes (vue = empreinte de la liste complète)."""
    vue = pd.vue_de(registre, publications)
    taille = taille or max(1, len(publications))
    pages = []
    for depart in range(0, max(1, len(publications)), taille):
        morceau = publications[depart : depart + taille]
        suivant = depart + len(morceau)
        pages.append({
            "registre": registre, "vue": vue, "total": len(publications), "depart": depart,
            "prochain_depart": suivant if suivant < len(publications) else None, "publications": morceau,
        })  # fmt: skip
    for cle, valeur in surcharge.items():
        pages[-1][cle] = valeur
    return pages


def _aba():
    cle = _cle_dico()
    return [
        {"cle": cle, "revision": 1, "empreinte": A},
        {"cle": cle, "revision": 2, "empreinte": B},
        {"cle": cle, "revision": 3, "empreinte": A},
    ]


def _obs(empreinte, revision=None, cle=None, registre="dictionnaire", metric_id="marge_reelle"):
    observation = {"metric_id": metric_id, "valeur": "114.00", "version_definition": empreinte}
    if revision is not None:
        observation["preuve_definition"] = {
            "registre": registre, "cle": cle or _cle_dico(), "revision": revision, "empreinte": empreinte,
        }  # fmt: skip
    return observation


def test_aba_une_meme_empreinte_a_deux_revisions_est_legitime_et_jamais_arbitree():
    historique = pd.assembler_historique(_pages(_aba(), taille=2))
    assert historique["cles"]["dictionnaire:finance/m05/marge_reelle"] == {1: A, 2: B, 3: A}
    courante = pd.verifier_preuve(_obs(A, 3), historique)
    assert courante["statut"] == "COMPATIBLE" and courante["revision"] == 3 and courante["valeur_verifiee"] is False
    ancienne = pd.verifier_preuve(_obs(A, 1), historique)  # même contenu que la courante, autre publication
    assert ancienne["statut"] == "VERSION_PERIMEE" and ancienne["meme_contenu_que_la_courante"] is True
    intermediaire = pd.verifier_preuve(_obs(B, 2), historique)
    assert intermediaire["statut"] == "VERSION_PERIMEE" and intermediaire["meme_contenu_que_la_courante"] is False


def test_historique_sans_preuve_propre_de_meme_empreinte_reste_non_comparable():
    historique = pd.assembler_historique(_pages(_aba()))
    sans_preuve = pd.verifier_preuve(_obs(A), historique)  # même empreinte que la courante, aucune preuve propre
    assert sans_preuve["statut"] == "VERSION_NON_COMPARABLE" and sans_preuve["raison"] == "PREUVE_PROPRE_ABSENTE"
    assert pd.verifier_preuve(_obs(A, 3), None)["raison"] == "HISTORIQUE_ABSENT"


def test_recalcul_explicitement_lie_a_la_revision_courante_est_seul_compatible():
    historique = pd.assembler_historique(_pages(_aba()))
    recalculee = _obs(A, 3)
    assert pd.verifier_preuve(recalculee, historique)["statut"] == "COMPATIBLE"
    menteuse = _obs(A, 2)  # prétend la révision 2, qui porte B
    verdict = pd.verifier_preuve(menteuse, historique)
    assert verdict["raison"] == "EMPREINTE_DIFFERENTE_A_CETTE_REVISION"
    incoherente = _obs(A, 3)
    incoherente["preuve_definition"]["empreinte"] = B  # preuve d'une autre empreinte que l'observation
    assert pd.verifier_preuve(incoherente, historique)["raison"] == "PREUVE_INCOHERENTE"
    autre_metrique = _obs(A, 3, metric_id="autre")
    assert pd.verifier_preuve(autre_metrique, historique)["raison"] == "PREUVE_INCOHERENTE"


def test_collision_d_identifiants_entre_familles_et_modules_ne_confond_jamais_deux_cles():
    publications = [
        {"cle": _cle_dico("finance", "m05", "marge"), "revision": 1, "empreinte": A},
        {"cle": _cle_dico("terrain", "m04", "marge"), "revision": 1, "empreinte": B},
        {"cle": _cle_dico("terrain", "m04", "marge"), "revision": 2, "empreinte": C},
    ]
    historique = pd.assembler_historique(_pages(publications))
    assert len(historique["cles"]) == 2
    finance = pd.verifier_preuve(_obs(A, 1, _cle_dico("finance", "m05", "marge"), metric_id="marge"), historique)
    assert finance["statut"] == "COMPATIBLE"  # révision 1 est la courante de SA clé, pas celle de l'autre module
    croisee = pd.verifier_preuve(_obs(A, 1, _cle_dico("terrain", "m04", "marge"), metric_id="marge"), historique)
    assert croisee["raison"] == "EMPREINTE_DIFFERENTE_A_CETTE_REVISION"
    inconnue = pd.verifier_preuve(_obs(A, 1, _cle_dico("finance", "m99", "marge"), metric_id="marge"), historique)
    assert inconnue["raison"] == "CLE_INCONNUE"
    sans_module = _obs(A, 1, {"famille": "finance", "id": "marge"}, metric_id="marge")
    assert pd.verifier_preuve(sans_module, historique)["raison"] == "PREUVE_MAL_FORMEE"


def test_registres_jamais_transposes():
    surveillance = [{"cle": {"metric_id": "marge_reelle"}, "revision": 1, "empreinte": A}]
    historique = pd.assembler_historique(_pages(surveillance, registre="surveillance"))
    preuve_dictionnaire = _obs(A, 1)  # même empreinte, même numéro, autre registre
    assert pd.verifier_preuve(preuve_dictionnaire, historique)["raison"] == "REGISTRE_DIFFERENT"
    melange = _obs(A, 1, {"metric_id": "marge_reelle"}, registre="dictionnaire")
    assert pd.verifier_preuve(melange, historique)["raison"] == "PREUVE_MAL_FORMEE"


def test_revision_inconnue_ou_historique_troue_est_refuse():
    historique = pd.assembler_historique(_pages(_aba()))
    assert pd.verifier_preuve(_obs(A, 4), historique)["raison"] == "REVISION_INCONNUE"
    troue = [p for p in _aba() if p["revision"] != 2]
    with pytest.raises(ValueError, match="REJ-HISTORIQUE-TROU"):
        pd.assembler_historique(_pages(troue))
    sans_un = [dict(p, revision=p["revision"] + 1) for p in _aba()]  # 2, 3, 4 : la révision 1 manque
    with pytest.raises(ValueError, match="REJ-HISTORIQUE-TROU"):
        pd.assembler_historique(_pages(sans_un))


def test_corruption_detectee_vue_doublon_et_forme():
    altere = _pages(_aba())
    altere[0]["publications"][1]["empreinte"] = C  # contenu changé, vue d'origine conservée
    with pytest.raises(ValueError, match="REJ-HISTORIQUE-CORROMPU"):
        pd.assembler_historique(altere)
    doublon = [*_aba(), {"cle": _cle_dico(), "revision": 2, "empreinte": C}]
    with pytest.raises(ValueError, match="REJ-HISTORIQUE-CORROMPU"):
        pd.assembler_historique(_pages(doublon))
    for mauvaise in (
        {"cle": _cle_dico(), "revision": True, "empreinte": A},
        {"cle": _cle_dico(), "revision": 1, "empreinte": "A" * 64},
        {"cle": _cle_dico(), "revision": 1, "empreinte": A, "en_trop": 1},
        {"cle": {"famille": "f", "module": "m", "id": "x/y"}, "revision": 1, "empreinte": A},
        "texte",
    ):
        with pytest.raises(ValueError, match="REJ-HISTORIQUE-FORME"):
            pd.assembler_historique(_pages([mauvaise]))


def test_pagination_coherente_exigee():
    bonnes = _pages(_aba(), taille=1)
    assert pd.assembler_historique(bonnes)["total"] == 3
    trou = copy.deepcopy(bonnes)
    del trou[1]
    recouvrement = copy.deepcopy(bonnes)
    recouvrement[1]["depart"] = 0
    autre_vue = copy.deepcopy(bonnes)
    autre_vue[2]["vue"] = C
    non_close = copy.deepcopy(bonnes)
    non_close[2]["prochain_depart"] = 3
    total_faux = _pages(_aba(), total=4)
    for pages in (trou, recouvrement, autre_vue, non_close, total_faux):
        with pytest.raises(ValueError, match="REJ-HISTORIQUE-PAGINATION"):
            pd.assembler_historique(pages)
    for pas_pages in (None, [], "x", [{"registre": "dictionnaire"}]):
        with pytest.raises(ValueError, match="REJ-HISTORIQUE-PAGES"):
            pd.assembler_historique(pas_pages)


def test_preuve_mal_formee_jamais_une_exception():
    historique = pd.assembler_historique(_pages(_aba()))
    for preuve in (
        "texte", {"registre": "dictionnaire"}, {"registre": "x", "cle": _cle_dico(), "revision": 1, "empreinte": A},
        {"registre": "dictionnaire", "cle": _cle_dico(), "revision": 0, "empreinte": A},
        {"registre": "dictionnaire", "cle": [], "revision": 1, "empreinte": A},
    ):  # fmt: skip
        observation = {"metric_id": "marge_reelle", "valeur": "1", "version_definition": A, "preuve_definition": preuve}
        assert pd.verifier_preuve(observation, historique)["raison"] == "PREUVE_MAL_FORMEE"
    assert {v for v in pd.RAISONS} >= {"PREUVE_PROPRE_ABSENTE", "REGISTRE_DIFFERENT", "CLE_INCONNUE"}


def test_une_preuve_de_definition_ne_verifie_jamais_la_valeur():
    historique = pd.assembler_historique(_pages(_aba()))
    verdict = pd.verifier_preuve(_obs(A, 3), historique)
    assert verdict["valeur_verifiee"] is False and "valeur" not in verdict
    assert any("jamais que la valeur est vraie" in limite for limite in pd.LIMITES)
