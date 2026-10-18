"""Lecture stratégique des preuves de M8 (PLAN T1.5-d) : module pur, sans base.

M9 lit les alertes de mesure de chantier de M8 et les CITE (identifiant de métrique, version de sa
définition, chantier, valeur, seuil, événement) : gabarit déterministe, aucun chiffre recalculé,
aucune décision prise — elle revient au propriétaire.
"""

from __future__ import annotations

import json
import re

import pytest
from m9_strategic_intelligence import lecture_strategique

_MAINTENANT = "2026-09-28T07:00:00-04:00"  # jour = 2026-09-28
_BUDGET = 5900


def _franchie(numero: int = 0, metric_id: str = "m8_ecart_duree_pct", wct_id: str | None = None, **surcharges):
    wct_id = wct_id or f"wct-fictif-{numero}"
    base = {
        "evenement_id": f"m8-alerte-{metric_id}-MESURE-SEUIL-FRANCHI-{numero:04d}",
        "metric_id": metric_id, "type_alerte": "MESURE-SEUIL-FRANCHI",
        "quoi": f"Écart de durée d'un chantier : 100.00 % sur le chantier {wct_id}.", "a_qui": "m04-field-ops",
        "pourquoi": "valeur 100.00 % atteint ou dépasse le seuil configuré 50.00 %.",
        "preuve": {"metric_id": metric_id, "wct_id": wct_id, "valeur": "100.00", "unite": "pourcentage",
                   "sens": "au_dessus", "seuil": "50.00", "version_definition": "ab" * 32},
        "action_proposee": f"Revoir le chantier {wct_id} avec m04-field-ops.",
        "source": "M4 m4.travaux_termines ; M3 m3.devis_accepte",
        "horodatage_reference": "2026-09-27T15:00:00-04:00",
    }
    base.update(surcharges)
    return base


def _rappel(metric_id: str = "m8_ecart_marge_pct"):
    return {
        "evenement_id": f"m8-alerte-{metric_id}-MESURE-SEUIL-A-CONFIGURER-2026-09-27", "metric_id": metric_id,
        "type_alerte": "MESURE-SEUIL-A-CONFIGURER", "quoi": "Aucun seuil valide.", "a_qui": "m08-analytics",
        "pourquoi": "absent.", "preuve": {"metric_id": metric_id, "manque": "seuil"}, "source": "department.yaml",
        "action_proposee": "Définir le seuil.", "horodatage_reference": "2026-09-27T15:00:00-04:00",
    }


def _qualite():
    return {
        "evenement_id": "m8-alerte-m4_duree_reelle_minutes-REJ-QUALITE-DONNEE-PERIMEE-2026-09-28T06:00:00Z",
        "metric_id": "m4_duree_reelle_minutes", "type_alerte": "REJ-QUALITE-DONNEE-PERIMEE",
        "quoi": "Valeur périmée.", "a_qui": "m04-field-ops", "pourquoi": "âge 10 jours > 2 jours.",
        "preuve": {"metric_id": "m4_duree_reelle_minutes", "fraicheur_jours": 10.0, "fraicheur_attendue_jours": 2},
        "source": "Module M4 — WCT", "horodatage_reference": "2026-09-28T06:00:00Z",
    }


def _lire(alertes, **options):
    return lecture_strategique.assembler_lecture_strategique(_MAINTENANT, alertes, fenetre_alertes_jours=3, **options)


def _taille(objet) -> int:
    return len(json.dumps(objet, ensure_ascii=False))


# ---------------------------------------------------------------------------
# La lecture cite ses preuves et ne décide rien
# ---------------------------------------------------------------------------
def test_chaque_lecture_cite_les_preuves_de_m8_telles_quelles():
    lecture = _lire([_franchie(1)])

    [item] = lecture["lectures"]
    assert item == {
        "metric_id": "m8_ecart_duree_pct", "version_definition": "ab" * 32,
        "evenement_id": "m8-alerte-m8_ecart_duree_pct-MESURE-SEUIL-FRANCHI-0001", "chantier": "wct-fictif-1",
        "valeur": "100.00", "unite": "pourcentage", "sens": "au_dessus", "seuil": "50.00",
        "regle": "valeur 100.00 % atteint ou dépasse le seuil configuré 50.00 %.", "a_qui": "m04-field-ops",
        "action_proposee_par_m8": "Revoir le chantier wct-fictif-1 avec m04-field-ops.",
        "source": "M4 m4.travaux_termines ; M3 m3.devis_accepte", "statut_decision": "en_attente_du_proprietaire",
    }
    assert lecture["preuves_m8"] == ["m8_ecart_duree_pct"]
    assert isinstance(item["valeur"], str) and isinstance(item["seuil"], str)  # rien de recalculé ni converti


def test_m9_ne_decide_jamais_seul_la_decision_revient_au_proprietaire():
    lecture = _lire([_franchie(1)])
    assert lecture["decision"] == {"prise_par_m9": False, "a_prendre_par": "nathan_owner", "requise": True}
    assert "Aucune décision n'est prise par M9" in lecture["resume"] and "nathan_owner" in lecture["resume"]
    assert all(item["statut_decision"] == "en_attente_du_proprietaire" for item in lecture["lectures"])


def test_l_action_est_celle_que_m8_propose_relayee_jamais_inventee():
    sans_action = _franchie(1)
    del sans_action["action_proposee"]
    [item] = _lire([sans_action])["lectures"]
    assert item["action_proposee_par_m8"] is None  # M9 n'en fabrique pas une


def test_plusieurs_alertes_sont_triees_comptees_par_metrique_et_les_metriques_citees():
    alertes = [
        _franchie(3, "m8_ecart_materiaux_max_pct", "wct-a"),
        _franchie(1, "m8_ecart_duree_pct", "wct-a"),
        _franchie(2, "m8_ecart_duree_pct", "wct-b"),
        _franchie(4, "m8_ecart_duree_pct", "wct-b", evenement_id="m8-alerte-autre-0004"),
    ]

    lecture = _lire(alertes)

    assert [(i["metric_id"], i["evenement_id"]) for i in lecture["lectures"]] == sorted(
        (a["metric_id"], a["evenement_id"]) for a in alertes)
    assert lecture["preuves_m8"] == ["m8_ecart_duree_pct", "m8_ecart_materiaux_max_pct"]
    assert lecture["par_metrique"] == [
        {"metric_id": "m8_ecart_duree_pct", "nb_alertes": 3, "nb_chantiers": 2, "a_qui": ["m04-field-ops"]},
        {"metric_id": "m8_ecart_materiaux_max_pct", "nb_alertes": 1, "nb_chantiers": 1, "a_qui": ["m04-field-ops"]},
    ]
    assert lecture["resume"].startswith("4 alerte(s) de mesure proposée(s) par M8 sur 2 chantier(s), 2 métrique(s) : ")
    assert "m8_ecart_duree_pct, m8_ecart_materiaux_max_pct" in lecture["resume"]


def test_la_lecture_est_deterministe_quel_que_soit_l_ordre_d_entree():
    alertes = [_franchie(n) for n in range(5)]
    assert _lire(alertes) == _lire(list(reversed(alertes)))


def test_aucune_cle_de_cause_ou_de_responsable_ni_de_technicien_dans_la_lecture():
    texte = json.dumps(_lire([_franchie(1), _rappel()]), ensure_ascii=False).lower()
    for interdit in ("cause", "responsable", "coupable", "technicien"):
        assert interdit not in texte


# ---------------------------------------------------------------------------
# Ce qui n'est pas un risque : rien à lire, manques, qualité
# ---------------------------------------------------------------------------
def test_sans_alerte_de_mesure_aucune_decision_n_est_requise_et_le_resume_reste_borne_aux_alertes_recues():
    lecture = _lire([])
    assert lecture["lectures"] == [] and lecture["preuves_m8"] == [] and lecture["par_metrique"] == []
    assert lecture["decision"] == {"prise_par_m9": False, "a_prendre_par": "nathan_owner", "requise": False}
    resume = lecture["resume"]
    assert "rien à lire" not in resume.lower()  # zéro alerte reçue n'est pas une absence globale
    assert "reçu" in resume and "franchi" in resume  # portée dite : seuils franchis reçus par M9


def test_les_rappels_seuil_a_configurer_sont_des_manques_pas_des_risques():
    lecture = _lire([_rappel("m8_ecart_marge_pct"), _rappel("m8_ecart_duree_pct")])
    assert lecture["lectures"] == []
    assert lecture["decision"]["requise"] is False
    assert lecture["manques"]["seuils_a_configurer"] == ["m8_ecart_duree_pct", "m8_ecart_marge_pct"]


def test_les_alertes_de_qualite_sont_comptees_pas_relues_ici():
    lecture = _lire([_qualite(), _franchie(1)])
    assert lecture["manques"]["alertes_de_qualite_non_relues"] == 1
    assert [i["metric_id"] for i in lecture["lectures"]] == ["m8_ecart_duree_pct"]


def test_la_fenetre_borne_la_periode_lue_et_la_dit():
    vieille = _franchie(1, horodatage_reference="2026-09-20T10:00:00-04:00")
    recente = _franchie(2, horodatage_reference="2026-09-25T10:00:00-04:00")
    avenir = _franchie(3, horodatage_reference="2026-09-29T10:00:00-04:00")

    lecture = _lire([vieille, recente, avenir])

    assert lecture["periode"] == {"du": "2026-09-25", "au": "2026-09-28"}
    assert [i["evenement_id"] for i in lecture["lectures"]] == [recente["evenement_id"]]
    du_jour = lecture_strategique.assembler_lecture_strategique(_MAINTENANT, [recente])
    assert du_jour["lectures"] == [] and du_jour["periode"] == {"du": "2026-09-28", "au": "2026-09-28"}


# ---------------------------------------------------------------------------
# Le résumé est borné aux alertes REÇUES par M9 : il ne dit pas « rien à lire » et compte les manques
# (design-M1/CONCEPTION-MINIMALE-r1.md §1-3 ; DIAGNOSTIC-r1.md : zéro reçu n'est pas une absence globale).
# Seuils : métriques DISTINCTES après filtre de période ; qualité : alertes comptées, jamais relues.
# ---------------------------------------------------------------------------
_METRIQUES = ("m8_ecart_marge_pct", "m8_ecart_materiaux_max_pct", "m8_ecart_duree_pct")
_MOTS_INTERDITS = ("cause", "responsable", "coupable", "technicien")
_CLES_DTO = {
    "type", "jour", "periode", "source", "resume", "decision", "preuves_m8", "par_metrique", "manques",
    "lectures", "affichage",
}
_CLES_AFFICHAGE = {
    "borne_caracteres", "taille_caracteres", "n_lectures", "depart", "affichees", "reste", "prochain_depart",
    "message",
}


def _rappel_du(metric_id: str, jour: str):
    """Rappel « seuil à configurer » canonique (comme _rappel) daté d'un autre jour : autre evenement_id."""
    rappel = _rappel(metric_id)
    rappel["evenement_id"] = f"m8-alerte-{metric_id}-MESURE-SEUIL-A-CONFIGURER-{jour}"
    rappel["horodatage_reference"] = f"{jour}T15:00:00-04:00"
    return rappel


def _qualite_du(numero: int, **surcharges):
    """Autre alerte de qualité canonique (comme _qualite) : autre evenement_id, même type."""
    alerte = _qualite()
    alerte["evenement_id"] = f"m8-alerte-m4_duree_reelle_minutes-REJ-QUALITE-DONNEE-PERIMEE-{numero:04d}"
    alerte.update(surcharges)
    return alerte


def _nb_seuils_dans(resume: str) -> int:
    trouve = re.search(r"(\d+) métrique\(s\)[^.]*configurer", resume)
    return int(trouve.group(1)) if trouve else 0


def _nb_qualite_dans(resume: str) -> int:
    trouve = re.search(r"(\d+) alerte\(s\) de qualité[^.]*non relue", resume)
    return int(trouve.group(1)) if trouve else 0


def _verifier_resume(lecture, n_seuils: int, n_qualite: int) -> None:
    """Le résumé compte les manques du corpus retenu, comme `manques` ; rien d'autre n'est affirmé."""
    resume = lecture["resume"]
    bas = resume.lower()
    total = lecture["affichage"]["n_lectures"]
    assert "rien à lire" not in bas
    assert all(interdit not in bas for interdit in _MOTS_INTERDITS)
    assert _nb_seuils_dans(resume) == n_seuils
    assert _nb_qualite_dans(resume) == n_qualite
    assert ("configurer" in bas) == (n_seuils > 0)  # compteur 0 : aucun suffixe
    assert ("non relue" in bas) == (n_qualite > 0)
    assert ("qualité" in bas) == (n_qualite > 0)
    if total == 0:  # aucun seuil franchi reçu : la portée du zéro est dite
        assert "reçu" in bas and "franchi" in bas
    manques = lecture["manques"]
    assert len(manques["seuils_a_configurer"]) == n_seuils
    assert manques["alertes_de_qualite_non_relues"] == n_qualite
    assert lecture["decision"] == {"prise_par_m9": False, "a_prendre_par": "nathan_owner", "requise": total > 0}


def test_resume_seuil_a_configurer_seul_compte_la_metrique_et_ne_dit_pas_rien_a_lire():
    lecture = _lire([_rappel("m8_ecart_marge_pct")])
    assert lecture["lectures"] == [] and lecture["decision"]["requise"] is False
    assert lecture["manques"]["seuils_a_configurer"] == ["m8_ecart_marge_pct"]
    _verifier_resume(lecture, n_seuils=1, n_qualite=0)


def test_resume_qualite_seule_compte_l_alerte_non_relue_et_ne_dit_pas_rien_a_lire():
    lecture = _lire([_qualite()])
    assert lecture["lectures"] == [] and lecture["decision"]["requise"] is False
    _verifier_resume(lecture, n_seuils=0, n_qualite=1)


def test_resume_mixte_seuil_et_qualite_sans_seuil_franchi():
    lecture = _lire([_rappel("m8_ecart_marge_pct"), _qualite()])
    assert lecture["lectures"] == [] and lecture["decision"]["requise"] is False
    _verifier_resume(lecture, n_seuils=1, n_qualite=1)


def test_la_branche_positive_garde_son_gabarit_et_recoit_les_memes_manques():
    gabarit = (
        "1 alerte(s) de mesure proposée(s) par M8 sur 1 chantier(s), 1 métrique(s) : m8_ecart_duree_pct. "
        "Aucune décision n'est prise par M9 : elle revient au propriétaire (nathan_owner)."
    )
    assert _lire([_franchie(1)])["resume"] == gabarit  # sans manque : inchangé, aucun suffixe
    lecture = _lire([_franchie(1), _rappel("m8_ecart_marge_pct"), _qualite()])
    assert lecture["resume"].startswith("1 alerte(s) de mesure proposée(s) par M8 sur 1 chantier(s), 1 métrique(s) : ")
    assert "Aucune décision n'est prise par M9" in lecture["resume"] and "nathan_owner" in lecture["resume"]
    _verifier_resume(lecture, n_seuils=1, n_qualite=1)


def test_les_seuils_a_configurer_comptent_des_metriques_distinctes_pas_des_evenements():
    meme_metrique = [_rappel_du("m8_ecart_marge_pct", "2026-09-27"), _rappel_du("m8_ecart_marge_pct", "2026-09-26")]
    assert meme_metrique[0]["evenement_id"] != meme_metrique[1]["evenement_id"]
    lecture = _lire(meme_metrique)
    assert lecture["manques"]["seuils_a_configurer"] == ["m8_ecart_marge_pct"]
    _verifier_resume(lecture, n_seuils=1, n_qualite=0)  # deux événements, une seule métrique
    deux_metriques = [_rappel_du("m8_ecart_marge_pct", "2026-09-27"), _rappel_du("m8_ecart_duree_pct", "2026-09-27")]
    lecture = _lire(deux_metriques)
    assert lecture["manques"]["seuils_a_configurer"] == ["m8_ecart_duree_pct", "m8_ecart_marge_pct"]
    _verifier_resume(lecture, n_seuils=2, n_qualite=0)


_CAS_COMPTEURS = [
    pytest.param(
        avec_franchie, n_seuils, n_qualite, id=f"franchie{int(avec_franchie)}-seuils{n_seuils}-qualite{n_qualite}")
    for avec_franchie in (False, True)
    for n_seuils, n_qualite in ((0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (0, 3), (3, 2))
]


@pytest.mark.parametrize("avec_franchie,n_seuils,n_qualite", _CAS_COMPTEURS)
def test_les_compteurs_du_resume_suivent_les_manques_du_corpus_pluriels_et_zero(avec_franchie, n_seuils, n_qualite):
    alertes = [_franchie(1)] if avec_franchie else []
    alertes += [_rappel_du(metric_id, "2026-09-27") for metric_id in _METRIQUES[:n_seuils]]
    alertes += [_qualite_du(numero) for numero in range(n_qualite)]
    lecture = _lire(alertes, budget_caracteres=_BUDGET)
    assert lecture["affichage"]["n_lectures"] == (1 if avec_franchie else 0)
    _verifier_resume(lecture, n_seuils, n_qualite)


def _hors_periode():
    """Rappels et alertes de qualité canoniques hors de la fenêtre 2026-09-25..2026-09-28 (3 jours)."""
    return [
        _rappel_du("m8_ecart_duree_pct", "2026-09-20"), _rappel_du("m8_ecart_materiaux_max_pct", "2026-09-29"),
        _qualite_du(2, horodatage_reference="2026-09-20T10:00:00-04:00"),
        _qualite_du(3, horodatage_reference="2026-09-29T10:00:00-04:00"),
    ]


def test_les_manques_hors_periode_ne_sont_pas_comptes_dans_le_resume_comme_dans_manques():
    dans = [_rappel_du("m8_ecart_marge_pct", "2026-09-27"), _qualite_du(1)]
    lecture = _lire([*_hors_periode(), *dans])
    assert lecture["manques"] == {"seuils_a_configurer": ["m8_ecart_marge_pct"], "alertes_de_qualite_non_relues": 1}
    _verifier_resume(lecture, n_seuils=1, n_qualite=1)


def test_un_corpus_entierement_hors_periode_ne_laisse_aucun_manque_et_ne_dit_pas_rien_a_lire():
    lecture = _lire(_hors_periode())
    assert lecture["manques"] == {"seuils_a_configurer": [], "alertes_de_qualite_non_relues": 0}
    _verifier_resume(lecture, n_seuils=0, n_qualite=0)


def test_sur_une_page_suivante_le_resume_et_les_manques_restent_globaux_au_corpus():
    alertes = [_franchie(n) for n in range(60)]
    alertes += [_rappel_du("m8_ecart_marge_pct", "2026-09-27"), _rappel_du("m8_ecart_materiaux_max_pct", "2026-09-27")]
    alertes += [_qualite()]
    premiere = _lire(alertes, budget_caracteres=_BUDGET)
    pages, depart = [premiere], premiere["affichage"]["prochain_depart"]
    assert depart is not None and 0 < depart < 60
    while depart is not None:
        page = _lire(alertes, depart=depart, budget_caracteres=_BUDGET)
        pages.append(page)
        depart = page["affichage"]["prochain_depart"]
        assert len(pages) < 50
    assert len(pages) > 1 and pages[-1]["affichage"]["depart"] > 0
    assert premiere["resume"].startswith("60 alerte(s) de mesure")
    _verifier_resume(premiere, n_seuils=2, n_qualite=1)
    for page in pages:
        assert page["resume"] == premiere["resume"] and page["manques"] == premiere["manques"]
        assert page["affichage"]["n_lectures"] == 60 and _taille(page) <= _BUDGET
        assert page["affichage"]["taille_caracteres"] == _taille(page)
    assert sum(len(page["lectures"]) for page in pages) == 60


_CORPUS_INVARIANTS = (
    ("vide", [], 0, [], 0),
    ("seuil_seul", [_rappel("m8_ecart_marge_pct")], 0, ["m8_ecart_marge_pct"], 0),
    ("qualite_seule", [_qualite()], 0, [], 1),
    ("mixte", [_rappel("m8_ecart_marge_pct"), _qualite()], 0, ["m8_ecart_marge_pct"], 1),
    ("positif_et_manques", [_franchie(1), _franchie(2), _rappel("m8_ecart_marge_pct"), _qualite()], 2,
     ["m8_ecart_marge_pct"], 1),
)
_CAS_INVARIANTS = [
    pytest.param(alertes, n_franchies, seuils, n_qualite, budget, id=f"{nom}-{libelle}")
    for nom, alertes, n_franchies, seuils, n_qualite in _CORPUS_INVARIANTS
    for libelle, budget in (("sans_borne", None), ("borne_5900", _BUDGET))
]


@pytest.mark.parametrize("alertes,n_franchies,seuils,n_qualite,budget", _CAS_INVARIANTS)
def test_le_dto_les_manques_et_la_decision_restent_inchanges_avec_ou_sans_borne(
        alertes, n_franchies, seuils, n_qualite, budget):
    page = _lire(alertes, budget_caracteres=budget)
    assert set(page) == _CLES_DTO and len(page) == 11
    assert set(page["affichage"]) == _CLES_AFFICHAGE
    assert page["decision"] == {"prise_par_m9": False, "a_prendre_par": "nathan_owner", "requise": n_franchies > 0}
    assert page["manques"] == {"seuils_a_configurer": seuils, "alertes_de_qualite_non_relues": n_qualite}
    assert page["affichage"]["borne_caracteres"] == budget and page["affichage"]["n_lectures"] == n_franchies
    assert page["affichage"]["taille_caracteres"] == _taille(page)
    assert budget is None or _taille(page) <= budget


@pytest.mark.parametrize(
    "base", [[], [_franchie(1), _franchie(2, "m8_ecart_materiaux_max_pct")]], ids=["vide", "deux_franchies"])
def test_ajouter_des_manques_ne_change_que_resume_manques_et_taille(base):
    sans = _lire(base, budget_caracteres=_BUDGET)
    avec = _lire([*base, _rappel("m8_ecart_marge_pct"), _qualite()], budget_caracteres=_BUDGET)
    for cle in ("type", "jour", "periode", "source", "decision", "preuves_m8", "par_metrique", "lectures"):
        assert avec[cle] == sans[cle]
    affichage_sans = {cle: valeur for cle, valeur in sans["affichage"].items() if cle != "taille_caracteres"}
    affichage_avec = {cle: valeur for cle, valeur in avec["affichage"].items() if cle != "taille_caracteres"}
    assert affichage_avec == affichage_sans
    assert avec["manques"] != sans["manques"]


def test_la_borne_inclut_le_resume_complet_et_refuse_un_squelette_trop_gros_meme_avec_manques():
    alertes = [_rappel("m8_ecart_marge_pct"), _qualite()]
    taille = _lire(alertes)["affichage"]["taille_caracteres"]
    assert _taille(_lire(alertes, budget_caracteres=taille + 50)) <= taille + 50
    with pytest.raises(ValueError, match="borne"):
        _lire(alertes, budget_caracteres=taille - 50)


# ---------------------------------------------------------------------------
# Bornée comme le briefing : ce qui ne tient pas est compté et se lit à la suite
# ---------------------------------------------------------------------------
def test_sans_borne_toutes_les_lectures_sont_rendues():
    lecture = _lire([_franchie(n) for n in range(30)])
    assert len(lecture["lectures"]) == 30
    assert lecture["affichage"]["reste"] == 0 and lecture["affichage"]["message"] is None
    assert lecture["affichage"]["taille_caracteres"] == _taille(lecture)


def test_avec_borne_la_page_tient_et_dit_combien_de_lectures_restent():
    alertes = [_franchie(n) for n in range(60)]

    page = _lire(alertes, budget_caracteres=_BUDGET)

    affichees = len(page["lectures"])
    assert 0 < affichees < 60
    assert _taille(page) <= _BUDGET
    assert page["affichage"]["taille_caracteres"] == _taille(page)
    assert page["affichage"]["reste"] == 60 - affichees and page["affichage"]["prochain_depart"] == affichees
    assert page["affichage"]["message"] == (
        f"{60 - affichees} autres lectures non affichées : poursuivre avec depart={affichees}."
    )
    assert page["affichage"]["n_lectures"] == 60
    # Le résumé, lui, porte sur TOUTES les alertes : jamais réduit à la page.
    assert page["resume"].startswith("60 alerte(s) de mesure")
    assert page["decision"]["requise"] is True


def test_les_pages_successives_rendent_chaque_lecture_une_fois_dans_l_ordre():
    alertes = [_franchie(n) for n in range(60)]
    lus, depart, pages = [], 0, 0
    while depart is not None:
        page = _lire(alertes, depart=depart, budget_caracteres=_BUDGET)
        assert _taille(page) <= _BUDGET
        lus.extend(i["evenement_id"] for i in page["lectures"])
        depart = page["affichage"]["prochain_depart"]
        pages += 1
        assert pages < 50
    assert lus == sorted(a["evenement_id"] for a in alertes)
    assert pages > 1


def test_le_singulier_quand_une_seule_lecture_reste():
    alertes = [_franchie(n) for n in range(60)]
    departs = [d for d in range(60) if _lire(alertes, depart=d, budget_caracteres=_BUDGET)["affichage"]["reste"] == 1]
    assert departs  # au moins un point de départ laisse exactement une lecture

    page = _lire(alertes, depart=departs[0], budget_caracteres=_BUDGET)

    fin = departs[0] + len(page["lectures"])
    assert page["affichage"]["message"] == f"1 autre lecture non affichée : poursuivre avec depart={fin}."


def test_la_derniere_page_n_annonce_plus_rien():
    alertes = [_franchie(n) for n in range(60)]
    seule = _lire(alertes, depart=59)
    assert len(seule["lectures"]) == 1
    assert seule["affichage"]["reste"] == 0 and seule["affichage"]["prochain_depart"] is None
    assert seule["affichage"]["message"] is None


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("options", [
    {"depart": -1}, {"depart": True}, {"depart": "0"}, {"depart": 99},
    {"budget_caracteres": 0}, {"budget_caracteres": True}, {"budget_caracteres": "5900"},
    {"fenetre_alertes_jours": -1}, {"fenetre_alertes_jours": True}, {"fenetre_alertes_jours": 1.5},
])
def test_des_parametres_invalides_sont_refuses(options):
    reglages = {"fenetre_alertes_jours": 3, **options}
    with pytest.raises(ValueError):
        lecture_strategique.assembler_lecture_strategique(_MAINTENANT, [_franchie(1)], **reglages)


def test_une_alerte_sans_ses_champs_ou_avec_une_preuve_incomplete_est_un_refus_nomme():
    sans_pourquoi = _franchie(1)
    del sans_pourquoi["pourquoi"]
    with pytest.raises(ValueError, match="pourquoi"):
        _lire([sans_pourquoi])

    preuve_incomplete = _franchie(2, preuve={"metric_id": "m8_ecart_duree_pct", "wct_id": "w", "valeur": "1.00"})
    with pytest.raises(ValueError, match="preuve incomplète"):
        _lire([preuve_incomplete])

    with pytest.raises(ValueError, match="dict attendu"):
        _lire(["pas-un-dict"])


def test_une_lecture_plus_grosse_que_la_borne_est_un_refus_pas_une_page_vide_sans_fin():
    with pytest.raises(ValueError, match="borne"):
        _lire([_franchie(1)], budget_caracteres=200)


@pytest.mark.parametrize("metric_id_preuve", ["m8_ecart_marge_pct", None, "", False, 7])
def test_une_lecture_refuse_une_identite_de_preuve_discordante(metric_id_preuve):
    """Les valeurs d'une marge ne peuvent jamais être présentées comme une durée."""
    alerte = _franchie(1)
    alerte["preuve"]["metric_id"] = metric_id_preuve
    avant = json.dumps(alerte, sort_keys=True)
    with pytest.raises(ValueError, match="métrique discordante"):
        _lire([alerte])
    assert json.dumps(alerte, sort_keys=True) == avant


def test_une_lecture_refuse_une_preuve_sans_identite_de_metrique():
    alerte = _franchie(1)
    del alerte["preuve"]["metric_id"]
    with pytest.raises(ValueError, match="preuve incomplète.*metric_id"):
        _lire([alerte])
