"""Briefing du matin BORNÉ (PLAN T1.5-d) : module pur, sans base.

Constat de l'E2E : au-delà d'environ 22 décisions en attente, la réponse dépassait les 6 000
caractères de `Capacites` et était tronquée — illisible pour l'app. La taille est maintenant
calculée par le code : ce qui ne tient pas est compté (« N autres éléments non affichés ») et se
lit par pages, jamais une troncature silencieuse. Le passage par `Capacites` lui-même est prouvé
dans `test_briefing_capacites.py`.
"""

from __future__ import annotations

import json

import pytest
from m9_strategic_intelligence import briefing_matin

_MAINTENANT = "2026-09-28T07:00:00-04:00"  # jour = 2026-09-28, veille = 2026-09-27
_BUDGET = 5900  # la limite de sortie du socle (6 000) moins la réserve d'enveloppe de outils.py


def _decision(numero: int, **surcharges):
    base = {
        "type": "approbation", "id": f"dem-{numero:04d}", "resume": "m6_creer_bon_commande (m06-material-control)",
        "niveau": "N4", "depuis": f"2026-09-{1 + numero // 100:02d}T{numero % 24:02d}:{numero % 60:02d}:00+00:00",
        "action_proposee": "approuver ou refuser", "departement": "m06-material-control",
    }
    base.update(surcharges)
    return base


def _decisions(n: int):
    return [_decision(numero) for numero in range(n)]


def _alerte(numero: int = 0, **surcharges):
    base = {
        "evenement_id": f"m8-alerte-m8_ecart_duree_pct-MESURE-SEUIL-FRANCHI-{numero:04d}",
        "metric_id": "m8_ecart_duree_pct", "type_alerte": "MESURE-SEUIL-FRANCHI",
        "quoi": "Écart de durée d'un chantier : 100.00 % sur le chantier wct-fictif.", "a_qui": "m04-field-ops",
        "pourquoi": "valeur 100.00 % atteint ou dépasse le seuil configuré 50.00 %.",
        "preuve": {"metric_id": "m8_ecart_duree_pct", "wct_id": "wct-fictif", "valeur": "100.00",
                   "unite": "pourcentage", "sens": "au_dessus", "seuil": "50.00", "version_definition": "a" * 64},
        "source": "M4 m4.travaux_termines ; M3 m3.devis_accepte", "horodatage_reference": "2026-09-28T06:00:00Z",
    }
    base.update(surcharges)
    return base


def _fait(numero: int = 0, **surcharges):
    base = {
        "index": numero, "module_source": "m04-field-ops", "horodatage": f"2026-09-27T{numero % 24:02d}:00:00Z",
        "valeurs": {"m4_wct_id": f"wct-{numero}", "m4_duree_reelle_minutes": "245"},
    }
    base.update(surcharges)
    return base


def _taille(objet) -> int:
    return len(json.dumps(objet, ensure_ascii=False))  # la mesure exacte de `Capacites._tronquer`


def _ids(section) -> list[str]:
    return [item["id"] for item in section["items"]]


# ---------------------------------------------------------------------------
# Sans borne : tout est affiché (comportement d'avant), et le dit
# ---------------------------------------------------------------------------
def test_sans_borne_tout_est_affiche_et_l_affichage_dit_complet():
    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, _decisions(60), [_alerte()], [_fait()])

    assert len(briefing["sections"]["decisions_en_attente"]["items"]) == 60
    affichage = briefing["affichage"]
    assert affichage["complet"] is True and affichage["n_non_affiches"] == 0
    assert affichage["message"] is None and affichage["lire_la_suite"] == []
    assert affichage["borne_caracteres"] is None
    assert affichage["taille_caracteres"] == _taille(briefing)


def test_sous_la_borne_rien_n_est_masque():
    briefing = briefing_matin.assembler_briefing_matin(
        _MAINTENANT, _decisions(3), [_alerte()], [_fait()], budget_caracteres=_BUDGET,
    )
    assert len(briefing["sections"]["decisions_en_attente"]["items"]) == 3
    assert briefing["affichage"]["complet"] is True and briefing["affichage"]["message"] is None


# ---------------------------------------------------------------------------
# 23 et 200 décisions : sous la borne, N autres éléments non affichés, jamais silencieux
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("total", [23, 200])
def test_avec_23_ou_200_decisions_le_briefing_tient_sous_la_borne_et_compte_ce_qu_il_ne_montre_pas(total):
    briefing = briefing_matin.assembler_briefing_matin(
        _MAINTENANT, _decisions(total), [], [], budget_caracteres=_BUDGET,
    )
    decisions = briefing["sections"]["decisions_en_attente"]
    affichees = len(decisions["items"])
    cachees = total - affichees

    assert 0 < affichees < total  # une troncature réelle, mais pas un briefing vide
    assert _taille(briefing) <= _BUDGET < 6000  # la sortie de Capacites n'est plus tronquée
    assert briefing["affichage"]["taille_caracteres"] == _taille(briefing)  # taille calculée, exacte
    assert briefing["affichage"]["complet"] is False
    assert briefing["affichage"]["n_non_affiches"] == cachees
    assert briefing["affichage"]["non_affiches"] == {
        "decisions_en_attente": cachees, "alertes_m8": 0, "faits_veille": 0,
    }
    assert briefing["affichage"]["message"].startswith(f"{cachees} autres éléments non affichés")
    assert decisions["vide"] is False  # des décisions existent, même si peu sont affichées


def test_la_troncature_dit_comment_lire_la_suite_avec_les_bons_arguments():
    briefing = briefing_matin.assembler_briefing_matin(
        _MAINTENANT, _decisions(200), [], [], budget_caracteres=_BUDGET,
    )
    affichees = len(briefing["sections"]["decisions_en_attente"]["items"])

    assert "m9_lire_suite_briefing" in briefing["affichage"]["message"]
    assert briefing["affichage"]["lire_la_suite"] == [{
        "section": "decisions_en_attente", "reste": 200 - affichees, "outil": "m9_lire_suite_briefing",
        "arguments": {"maintenant": _MAINTENANT, "section": "decisions_en_attente", "depart": affichees},
    }]


def test_un_seul_element_cache_se_dit_au_singulier():
    """Des décisions à gros résumé : 5 tiennent, la 6e non (le message coûte plus qu'un élément quand
    les éléments sont petits, d'où ce choix de gros éléments pour tomber pile sur un seul caché)."""
    decisions = [_decision(numero, resume="r" * 700) for numero in range(6)]

    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, decisions, [], [], budget_caracteres=_BUDGET)

    assert len(briefing["sections"]["decisions_en_attente"]["items"]) == 5
    assert briefing["affichage"]["n_non_affiches"] == 1
    assert briefing["affichage"]["message"].startswith("1 autre élément non affiché (decisions_en_attente : 1)")


def test_les_decisions_affichees_sont_les_plus_anciennes_dans_l_ordre_jamais_un_element_saute():
    tous = _decisions(200)
    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, tous, [], [], budget_caracteres=_BUDGET)
    attendu = [d["id"] for d in sorted(tous, key=lambda d: (d["depuis"], d["id"]))]
    affiches = _ids(briefing["sections"]["decisions_en_attente"])
    assert affiches == attendu[:len(affiches)]


# ---------------------------------------------------------------------------
# Équité : une pile de décisions ne noie ni les alertes ni les faits
# ---------------------------------------------------------------------------
def test_une_pile_de_decisions_ne_noie_ni_les_alertes_ni_les_faits():
    alertes = [_alerte(numero) for numero in range(3)]
    faits = [_fait(numero) for numero in range(2)]

    briefing = briefing_matin.assembler_briefing_matin(
        _MAINTENANT, _decisions(200), alertes, faits, budget_caracteres=_BUDGET,
    )

    assert len(briefing["sections"]["alertes_m8"]["items"]) == 3
    assert len(briefing["sections"]["faits_veille"]["items"]) == 2
    assert len(briefing["sections"]["decisions_en_attente"]["items"]) > 0
    assert briefing["affichage"]["non_affiches"]["alertes_m8"] == 0
    assert _taille(briefing) <= _BUDGET


def test_beaucoup_d_alertes_et_de_faits_sont_bornes_eux_aussi_et_se_lisent_par_section():
    alertes = [_alerte(numero) for numero in range(40)]
    faits = [_fait(numero) for numero in range(60)]

    briefing = briefing_matin.assembler_briefing_matin(
        _MAINTENANT, _decisions(50), alertes, faits, budget_caracteres=_BUDGET,
    )

    assert _taille(briefing) <= _BUDGET
    non_affiches = briefing["affichage"]["non_affiches"]
    assert all(non_affiches[s] > 0 for s in ("decisions_en_attente", "alertes_m8", "faits_veille"))
    assert {e["section"] for e in briefing["affichage"]["lire_la_suite"]} == set(non_affiches)
    # Chaque section montre au moins un élément : aucune n'est sacrifiée en entier.
    assert all(len(briefing["sections"][s]["items"]) >= 1 for s in non_affiches)


# ---------------------------------------------------------------------------
# Lire la suite : page après page, sans rien perdre ni répéter
# ---------------------------------------------------------------------------
def _lire_toutes_les_pages(section, premiers_affiches, decisions, alertes=(), faits=()):
    lus = []
    depart = premiers_affiches
    pages = 0
    while depart is not None:
        page = briefing_matin.lire_suite_section(
            _MAINTENANT, section, depart, decisions, list(alertes), list(faits), budget_caracteres=_BUDGET,
        )
        assert _taille(page) <= _BUDGET
        assert page["section"] == section and page["depart"] == depart
        assert page["affiches"] == len(page["items"]) > 0
        lus.extend(page["items"])
        depart = page["prochain_depart"]
        pages += 1
        assert pages < 100
    return lus


def test_lire_la_suite_rend_exactement_le_reste_dans_l_ordre():
    tous = _decisions(200)
    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, tous, [], [], budget_caracteres=_BUDGET)
    premiers = briefing["sections"]["decisions_en_attente"]["items"]

    suite = _lire_toutes_les_pages("decisions_en_attente", len(premiers), tous)

    ids = [d["id"] for d in premiers] + [d["id"] for d in suite]
    attendu = [d["id"] for d in sorted(tous, key=lambda d: (d["depuis"], d["id"]))]
    assert ids == attendu  # les 200, une fois chacune, dans l'ordre


def test_la_derniere_page_n_a_plus_de_prochain_depart_ni_de_message():
    tous = _decisions(30)
    page = briefing_matin.lire_suite_section(
        _MAINTENANT, "decisions_en_attente", 25, tous, [], [], budget_caracteres=_BUDGET,
    )
    assert page["affiches"] == 5 and page["reste"] == 0
    assert page["prochain_depart"] is None and page["message"] is None


def test_une_page_intermediaire_dit_combien_il_reste_et_ou_reprendre():
    page = briefing_matin.lire_suite_section(
        _MAINTENANT, "decisions_en_attente", 0, _decisions(200), [], [], budget_caracteres=_BUDGET,
    )
    assert page["reste"] == 200 - page["affiches"] > 1
    assert page["message"] == (
        f"{page['reste']} autres éléments non affichés dans cette section : poursuivre avec "
        f"depart={page['prochain_depart']}."
    )


def test_lire_la_suite_des_alertes_et_des_faits_a_les_memes_filtres_que_le_briefing():
    alertes = [_alerte(numero) for numero in range(40)] + [
        _alerte(99, horodatage_reference="2026-08-01T00:00:00Z"),  # hors fenêtre : jamais lue
    ]
    lues = _lire_toutes_les_pages("alertes_m8", 0, [], alertes)
    assert [a["evenement_id"] for a in lues] == sorted(f"m8-alerte-m8_ecart_duree_pct-MESURE-SEUIL-FRANCHI-{n:04d}"
                                                       for n in range(40))

    faits = [_fait(n) for n in range(60)] + [_fait(99, horodatage="2026-09-20T10:00:00Z")]
    assert len(_lire_toutes_les_pages("faits_veille", 0, [], [], faits)) == 60


def test_lire_la_suite_refuse_ce_qui_ne_ferait_pas_progresser_la_lecture():
    tous = _decisions(10)
    for section, depart in (("manques_pour_conclure", 0), ("inconnue", 0), ("decisions_en_attente", -1),
                            ("decisions_en_attente", True), ("decisions_en_attente", "0"),
                            ("decisions_en_attente", 11)):
        with pytest.raises(ValueError):
            briefing_matin.lire_suite_section(
                _MAINTENANT, section, depart, tous, [], [], budget_caracteres=_BUDGET,
            )
    # depart == total : la fin, une page vide qui le dit, pas une erreur
    fin = briefing_matin.lire_suite_section(
        _MAINTENANT, "decisions_en_attente", 10, tous, [], [], budget_caracteres=_BUDGET,
    )
    assert fin["items"] == [] and fin["prochain_depart"] is None


def test_un_element_plus_gros_que_la_borne_est_un_refus_pas_une_page_vide_sans_fin():
    enorme = _decision(1, resume="x" * 500)
    with pytest.raises(ValueError, match="dépasse la borne"):
        briefing_matin.lire_suite_section(
            _MAINTENANT, "decisions_en_attente", 0, [enorme], [], [], budget_caracteres=300,
        )


# ---------------------------------------------------------------------------
# Bornes et paramètres : fail-closed
# ---------------------------------------------------------------------------
def test_une_borne_trop_petite_pour_le_squelette_est_un_refus_nomme():
    with pytest.raises(ValueError, match="squelette"):
        briefing_matin.assembler_briefing_matin(_MAINTENANT, _decisions(3), [], [], budget_caracteres=100)


@pytest.mark.parametrize("budget", [0, -5, True, "6000", 1.5])
def test_un_budget_invalide_est_refuse(budget):
    with pytest.raises(ValueError, match="budget_caracteres"):
        briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [], budget_caracteres=budget)


@pytest.mark.parametrize("fenetre", [-1, True, "3", 2.5])
def test_une_fenetre_invalide_est_refusee(fenetre):
    with pytest.raises(ValueError, match="fenetre_alertes_jours"):
        briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [], fenetre_alertes_jours=fenetre)


def test_le_briefing_borne_est_deterministe_et_son_id_suit_ce_qui_est_masque():
    args = (_MAINTENANT, _decisions(100), [_alerte()], [_fait()])
    premier = briefing_matin.assembler_briefing_matin(*args, budget_caracteres=_BUDGET)
    second = briefing_matin.assembler_briefing_matin(*args, budget_caracteres=_BUDGET)
    assert premier == second

    plus_de_decisions = briefing_matin.assembler_briefing_matin(
        _MAINTENANT, _decisions(101), [_alerte()], [_fait()], budget_caracteres=_BUDGET,
    )
    assert plus_de_decisions["briefing_id"] != premier["briefing_id"]  # un élément de plus, même caché
    assert plus_de_decisions["sections"] == premier["sections"]  # les mêmes éléments affichés


def test_les_caracteres_accentues_comptent_comme_la_mesure_du_socle():
    """`Capacites` mesure `json.dumps(..., ensure_ascii=False)` : « é » vaut 1, pas 6 (`\\u00e9`)."""
    accentuees = [_decision(n, resume="Écart critique à réviser — chantier terminé") for n in range(80)]
    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, accentuees, [], [], budget_caracteres=_BUDGET)
    assert _taille(briefing) <= _BUDGET
    assert len(json.dumps(briefing)) > _taille(briefing)  # échappés en ASCII, ces caractères pèseraient plus


# ---------------------------------------------------------------------------
# Fenêtre des alertes (une alerte de mesure porte l'instant du chantier) et rappels de seuil
# ---------------------------------------------------------------------------
def test_sans_fenetre_seule_l_alerte_du_jour_est_lue_comme_avant():
    hier = _alerte(1, horodatage_reference="2026-09-27T15:00:00-04:00")
    du_jour = _alerte(2, horodatage_reference="2026-09-28T05:00:00Z")
    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [hier, du_jour], [])
    assert [a["evenement_id"] for a in briefing["sections"]["alertes_m8"]["items"]] == [du_jour["evenement_id"]]


def test_une_alerte_de_mesure_du_vendredi_parait_le_lundi_avec_une_fenetre_de_trois_jours():
    lundi = "2026-09-28T07:00:00-04:00"
    vendredi = _alerte(1, horodatage_reference="2026-09-25T15:00:00-04:00")  # chantier fini vendredi 15 h
    trop_vieille = _alerte(2, horodatage_reference="2026-09-24T15:00:00-04:00")
    future = _alerte(3, horodatage_reference="2026-09-29T09:00:00-04:00")

    briefing = briefing_matin.assembler_briefing_matin(
        lundi, [], [vendredi, trop_vieille, future], [], fenetre_alertes_jours=3,
    )

    assert [a["evenement_id"] for a in briefing["sections"]["alertes_m8"]["items"]] == [vendredi["evenement_id"]]
    sans = briefing_matin.assembler_briefing_matin(lundi, [], [vendredi], [], fenetre_alertes_jours=0)
    assert sans["sections"]["alertes_m8"]["vide"] is True


def test_le_manque_d_alertes_nomme_la_periode_quand_la_fenetre_depasse_un_jour():
    vide = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [], fenetre_alertes_jours=3)
    constat = next(m["constat"] for m in vide["sections"]["manques_pour_conclure"]["items"]
                   if m["section"] == "alertes_m8")
    assert "la période du 2026-09-25 au 2026-09-28" in constat
    du_jour = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [])
    assert "pour le 2026-09-28" in next(m["constat"] for m in du_jour["sections"]["manques_pour_conclure"]["items"]
                                        if m["section"] == "alertes_m8")


def _rappel(metric_id, numero=0):
    return _alerte(numero, metric_id=metric_id, type_alerte="MESURE-SEUIL-A-CONFIGURER",
                   evenement_id=f"m8-alerte-{metric_id}-MESURE-SEUIL-A-CONFIGURER-2026-09-28",
                   preuve={"metric_id": metric_id, "manque": "seuil"})


def test_les_rappels_seuil_a_configurer_sont_des_manques_pas_des_alertes():
    rappels = [_rappel("m8_ecart_marge_pct"), _rappel("m8_ecart_duree_pct")]

    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], rappels + [_alerte(5)], [_fait()])

    assert [a["metric_id"] for a in briefing["sections"]["alertes_m8"]["items"]] == ["m8_ecart_duree_pct"]
    assert all(a["type_alerte"] == "MESURE-SEUIL-FRANCHI" for a in briefing["sections"]["alertes_m8"]["items"])
    manques = briefing["sections"]["manques_pour_conclure"]["items"]
    [seuils] = [m for m in manques if "seuil à configurer" in m["constat"]]
    assert "2 métrique(s)" in seuils["constat"]
    assert "m8_ecart_duree_pct, m8_ecart_marge_pct" in seuils["constat"]  # triées, chacune une fois
    assert "MESURE-SEUIL-A-CONFIGURER" in seuils["verifie"]


def test_seuls_des_rappels_laissent_la_section_alertes_vide_et_le_disent_deux_fois():
    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [_rappel("m8_ecart_duree_pct")], [])
    assert briefing["sections"]["alertes_m8"] == {"items": [], "vide": True}
    constats = [m["constat"] for m in briefing["sections"]["manques_pour_conclure"]["items"]
                if m["section"] == "alertes_m8"]
    assert len(constats) == 2 and any("aucune alerte reçue" in c for c in constats)
    assert any("seuil à configurer" in c for c in constats)
