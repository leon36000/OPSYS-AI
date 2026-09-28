"""Assemblage déterministe du briefing du matin (PLAN T3.2) — module pur, aucune base montée."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m9_strategic_intelligence import briefing_matin  # noqa: E402

_MAINTENANT = "2026-09-28T07:00:00-04:00"  # jour = 2026-09-28, veille = 2026-09-27


def _decision(**overrides):
    base = {
        "type": "approbation", "id": "dem-1", "resume": "m6_creer_bon_commande (m06-material-control)",
        "niveau": "N4", "depuis": "2026-09-27T10:00:00+00:00", "action_proposee": "approuver ou refuser",
        "departement": "m06-material-control",
    }
    base.update(overrides)
    return base


def _alerte(**overrides):
    base = {
        "evenement_id": "m8-alerte-m4_duree_reelle_minutes-REJ-QUALITE-DONNEE-PERIMEE-2026-09-28T06:00:00Z",
        "metric_id": "m4_duree_reelle_minutes", "type_alerte": "REJ-QUALITE-DONNEE-PERIMEE",
        "quoi": "Valeur périmée pour m4_duree_reelle_minutes.", "a_qui": "m04-field-ops",
        "pourquoi": "âge observé 10.00 jours > fraîcheur attendue 2 jours.",
        "preuve": {"metric_id": "m4_duree_reelle_minutes", "fraicheur_jours": 10.0, "fraicheur_attendue_jours": 2},
        "source": "Module M4 — WCT", "horodatage_reference": "2026-09-28T06:00:00Z",
    }
    base.update(overrides)
    return base


def _fait(**overrides):
    base = {
        "index": 0, "module_source": "m04-field-ops", "horodatage": "2026-09-27T15:00:00Z",
        "valeurs": {"m4_wct_id": "wct-1", "m4_duree_reelle_minutes": "245"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Toutes sections vides : jamais remplies, manques nommés pour chacune
# ---------------------------------------------------------------------------
def test_toutes_sections_vides_declarees_vides_jamais_remplies():
    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [])

    assert briefing["type"] == "BRIEFING_MATIN"
    assert briefing["jour"] == "2026-09-28"
    assert briefing["veille"] == "2026-09-27"
    assert briefing["ordre_sections"] == list(briefing_matin.ORDRE_SECTIONS)
    for cle in ("decisions_en_attente", "alertes_m8", "faits_veille"):
        assert briefing["sections"][cle] == {"items": [], "vide": True}

    manques = briefing["sections"]["manques_pour_conclure"]
    assert manques["vide"] is False
    assert {m["section"] for m in manques["items"]} == {"decisions_en_attente", "alertes_m8", "faits_veille"}
    for manque in manques["items"]:
        assert manque["constat"]  # jamais une chaîne vide
        assert manque["verifie"]  # chaque manque nomme ce qui a été vérifié (source)


# ---------------------------------------------------------------------------
# Toutes sections remplies : aucun manque
# ---------------------------------------------------------------------------
def test_toutes_sections_remplies_aucun_manque():
    briefing = briefing_matin.assembler_briefing_matin(
        _MAINTENANT, [_decision()], [_alerte()], [_fait()],
    )

    assert briefing["sections"]["decisions_en_attente"]["vide"] is False
    assert briefing["sections"]["alertes_m8"]["vide"] is False
    assert briefing["sections"]["faits_veille"]["vide"] is False
    assert briefing["sections"]["manques_pour_conclure"] == {"items": [], "vide": True}


# ---------------------------------------------------------------------------
# Décisions en attente : pass-through intégral (forme mobile T1.4), triées par depuis
# ---------------------------------------------------------------------------
def test_decisions_en_attente_pass_through_et_triees_par_depuis():
    plus_recente = _decision(id="dem-recente", depuis="2026-09-28T02:00:00+00:00")
    plus_ancienne = _decision(id="dem-ancienne", depuis="2026-09-01T00:00:00+00:00")

    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [plus_recente, plus_ancienne], [], [])

    items = briefing["sections"]["decisions_en_attente"]["items"]
    assert [i["id"] for i in items] == ["dem-ancienne", "dem-recente"]
    # Forme EXACTE conservée (mobile T1.4 la consomme telle quelle) : rien de renommé/retiré.
    assert items[0] == plus_ancienne


def test_decisions_en_attente_ne_sont_jamais_filtrees_par_date():
    """La file du propriétaire n'a pas de fenêtre temporelle : une demande vieille de plusieurs
    mois reste affichée tant qu'elle est en attente."""
    vieille = _decision(id="dem-vieille", depuis="2020-01-01T00:00:00+00:00")

    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [vieille], [], [])

    assert briefing["sections"]["decisions_en_attente"]["items"] == [vieille]


# ---------------------------------------------------------------------------
# Alertes M8 : filtrées au JOUR de `maintenant`, triées par evenement_id
# ---------------------------------------------------------------------------
def test_alertes_m8_filtrees_au_jour_de_maintenant():
    du_jour = _alerte(evenement_id="evt-du-jour", horodatage_reference="2026-09-28T05:00:00Z")
    hors_jour = _alerte(evenement_id="evt-hors-jour", horodatage_reference="2026-09-27T05:00:00Z")

    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [du_jour, hors_jour], [])

    items = briefing["sections"]["alertes_m8"]["items"]
    assert [i["evenement_id"] for i in items] == ["evt-du-jour"]


def test_alertes_m8_triees_par_evenement_id_reproductible():
    a = _alerte(evenement_id="evt-b", horodatage_reference="2026-09-28T01:00:00Z")
    b = _alerte(evenement_id="evt-a", horodatage_reference="2026-09-28T02:00:00Z")

    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [a, b], [])

    assert [i["evenement_id"] for i in briefing["sections"]["alertes_m8"]["items"]] == ["evt-a", "evt-b"]


# ---------------------------------------------------------------------------
# Faits de la veille : filtrés à la VEILLE de `maintenant`, jamais au jour même
# ---------------------------------------------------------------------------
def test_faits_veille_filtres_a_la_veille_de_maintenant():
    de_la_veille = _fait(module_source="m04-field-ops", horodatage="2026-09-27T20:00:00Z")
    du_jour_meme = _fait(module_source="m06-material-control", horodatage="2026-09-28T05:00:00Z")
    trop_vieux = _fait(module_source="m02-revenue-crm", horodatage="2026-09-20T00:00:00Z")

    briefing = briefing_matin.assembler_briefing_matin(
        _MAINTENANT, [], [], [de_la_veille, du_jour_meme, trop_vieux],
    )

    items = briefing["sections"]["faits_veille"]["items"]
    assert [i["module_source"] for i in items] == ["m04-field-ops"]


def test_faits_veille_conserve_les_champs_de_tracabilite_du_maillon():
    """`index`/`hash_maillon` (traçabilité, `ligne_id` de `etat_consolide.py`) ne sont jamais
    retirés : ils restent la SOURCE vérifiable de l'élément."""
    maillon = _fait(index=7, hash_maillon="abc123")

    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [maillon])

    assert briefing["sections"]["faits_veille"]["items"][0]["index"] == 7
    assert briefing["sections"]["faits_veille"]["items"][0]["hash_maillon"] == "abc123"


def test_faits_veille_gere_les_fuseaux_horaires_sans_comparaison_alphabetique():
    """Même patron que `etat_consolide.py` : un horodatage exprimé dans un fuseau différent de
    UTC doit quand même tomber dans le bon jour calendaire (23h-04:00 = 03h UTC le lendemain)."""
    tard_le_27_local = _fait(module_source="m04-field-ops", horodatage="2026-09-27T23:30:00-04:00")

    briefing = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [tard_le_27_local])

    # 2026-09-27T23:30:00-04:00 == 2026-09-28T03:30:00Z : jour calendaire LOCAL (fuseau porté par
    # l'horodatage lui-même, jamais reconverti) = 27, donc bien "la veille" de maintenant (28).
    assert briefing["sections"]["faits_veille"]["items"] == [tard_le_27_local]


# ---------------------------------------------------------------------------
# Déterminisme : même entrée -> même briefing_id ; entrée différente -> id différent
# ---------------------------------------------------------------------------
def test_meme_entree_produit_le_meme_briefing_id():
    args = (_MAINTENANT, [_decision()], [_alerte()], [_fait()])

    premier = briefing_matin.assembler_briefing_matin(*args)
    second = briefing_matin.assembler_briefing_matin(*args)

    assert premier["briefing_id"] == second["briefing_id"]


def test_entree_differente_produit_un_briefing_id_different():
    sans_rien = briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [])
    avec_decision = briefing_matin.assembler_briefing_matin(_MAINTENANT, [_decision()], [], [])

    assert sans_rien["briefing_id"] != avec_decision["briefing_id"]


def test_ordre_d_entree_des_decisions_ne_change_pas_le_briefing_id():
    """Déterminisme : l'appelant peut fournir les candidats dans n'importe quel ordre, le
    briefing assemblé (donc son empreinte) est toujours le même."""
    a, b = _decision(id="dem-a", depuis="2026-09-01T00:00:00Z"), _decision(id="dem-b", depuis="2026-09-02T00:00:00Z")

    ordre_1 = briefing_matin.assembler_briefing_matin(_MAINTENANT, [a, b], [], [])
    ordre_2 = briefing_matin.assembler_briefing_matin(_MAINTENANT, [b, a], [], [])

    assert ordre_1["briefing_id"] == ordre_2["briefing_id"]


# ---------------------------------------------------------------------------
# Fail-closed : un candidat structurellement incomplet est un refus nommé
# ---------------------------------------------------------------------------
def test_decision_sans_champ_requis_leve_une_erreur_nommee():
    incomplete = _decision()
    del incomplete["niveau"]

    with pytest.raises(ValueError, match="niveau"):
        briefing_matin.assembler_briefing_matin(_MAINTENANT, [incomplete], [], [])


def test_alerte_sans_champ_requis_leve_une_erreur_nommee():
    incomplete = _alerte()
    del incomplete["preuve"]

    with pytest.raises(ValueError, match="preuve"):
        briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [incomplete], [])


def test_fait_sans_champ_requis_leve_une_erreur_nommee():
    incomplet = _fait()
    del incomplet["valeurs"]

    with pytest.raises(ValueError, match="valeurs"):
        briefing_matin.assembler_briefing_matin(_MAINTENANT, [], [], [incomplet])


def test_candidat_qui_n_est_pas_un_dict_leve_une_erreur_nommee():
    with pytest.raises(ValueError, match="dict attendu"):
        briefing_matin.assembler_briefing_matin(_MAINTENANT, ["pas-un-dict"], [], [])
