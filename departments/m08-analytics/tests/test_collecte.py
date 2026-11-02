"""« Pourquoi cette mesure est vide ? » (chantier C2 de l'analyse M8) : le diagnostic PUR de la collecte.

Pur : aucune base, aucune horloge, aucun registre. Les mesures et l'état des constats planifiés sont fabriqués ici
(données fictives) ; ce que le planificateur et le moteur de mesures disent en vrai est prouvé par
`tests/test_etat_collecte_m8.py`. Prouvé : une cause fermée par mesure, dans l'ordre documenté ; l'action nomme le
constat ; le « non calculable » du producteur n'est jamais pris pour un défaut technique ; aucune valeur de mesure ne
sort ; la liste de contrôle suit l'état lu ; déterminisme."""

from __future__ import annotations

import copy
import json

import pytest
from m8_analytics import collecte

FICTIF = True


def mesure(metric_id="m8_cash_libre_cad", *, statut="calculee", fraicheur="a_jour",
           dernier_fait_le="2026-11-12T00:00:00+00:00", manque=(), valeur="27861.98", proprietaire="m05-financecore",
           qualite=None):
    return {
        "metric_id": metric_id, "nom": f"Mesure {metric_id}", "proprietaire": proprietaire, "statut": statut,
        "valeur": valeur if statut == "calculee" else None, "dernier_fait_le": dernier_fait_le,
        "manque": [{"champ": m} for m in manque], "fraicheur": {"statut": fraicheur},
        **({"qualite": {"statut": qualite}} if qualite is not None else {}),
    }


def constat(executeur="m5.constat.cash-libre", mesures=("m8_cash_libre_cad",), *, mode="actif", expire=False,
            dernier_statut="ok", dernier_code=None, dernier_passage=1_800_000_000, echecs=0):
    return {
        "executeur": executeur, "departement": "m05-financecore", "outil": "m5_constater_cash_libre_planifie",
        "mesures": list(mesures), "mode": mode, "mode_demande": mode, "expire": expire, "intervalle_s": 43200,
        "dernier_passage": dernier_passage, "dernier_statut": dernier_statut, "dernier_code": dernier_code,
        "echecs_24h": echecs,
    }


def une(mesures, constats, *, autorise=True):
    return collecte.diagnostiquer(mesures, constats, planificateur_autorise=autorise)


def la_mesure(diagnostic, metric_id="m8_cash_libre_cad"):
    return next(m for m in diagnostic["mesures"] if m["metric_id"] == metric_id)


# ============================================================================================ chaque cause, une à une
def test_une_mesure_calculee_et_a_jour_n_a_rien_a_corriger():
    ligne = la_mesure(une([mesure()], [constat()]))
    assert (ligne["etat_collecte"], ligne["action"]) == ("a_jour", None)
    assert ligne["constats"] == ["m5.constat.cash-libre"]


def test_une_mesure_terminale_non_applicable_est_a_jour():
    assert la_mesure(une([mesure(fraicheur="non_applicable")], []))["etat_collecte"] == "a_jour"


@pytest.mark.parametrize(("constat_mode", "cause", "morceaux"), [
    (dict(mode="inactif"), "constat_inactif", ("n'a jamais été activé", "en ombre", "m5.constat.cash-libre")),
    (dict(mode="inactif", expire=True), "constat_expire",
     ("90 jours est échue", "Renouveler", "m5.constat.cash-libre")),
    (dict(mode="ombre"), "constat_en_ombre", ("ne publie rien", "de l'ombre à l'actif", "m5.constat.cash-libre")),
], ids=["inactif", "expire", "ombre"])
def test_un_constat_qui_n_est_pas_actif_est_la_cause_et_l_action_le_nomme(constat_mode, cause, morceaux):
    vide = mesure(statut="non_calculable", fraicheur="manquant", dernier_fait_le=None)

    ligne = la_mesure(une([vide], [constat(**constat_mode)]))

    assert ligne["etat_collecte"] == cause
    for morceau in morceaux:
        assert morceau in ligne["phrase"] + " " + ligne["action"], morceau


def test_un_constat_actif_dont_le_dernier_passage_a_echoue_dit_son_code():
    vide = mesure(statut="non_calculable", fraicheur="manquant", dernier_fait_le=None)

    ligne = la_mesure(une([vide], [constat(dernier_statut="erreur", dernier_code="REJ-PLAN-DEFAUT-EXECUTEUR")]))

    assert ligne["etat_collecte"] == "constat_en_erreur" and "REJ-PLAN-DEFAUT-EXECUTEUR" in ligne["phrase"]
    assert "REJ-PLAN-DEFAUT-EXECUTEUR" in ligne["action"]


@pytest.mark.parametrize("statut", ["erreur", "refus", "plafond", "attente_transport"])
def test_chaque_statut_d_echec_du_planificateur_est_une_erreur_de_constat(statut):
    vide = mesure(statut="non_calculable", fraicheur="manquant", dernier_fait_le=None)
    assert la_mesure(une([vide], [constat(dernier_statut=statut)]))["etat_collecte"] == "constat_en_erreur"


def test_un_constat_actif_et_sain_sans_aucun_fait_recu_est_jamais_recue():
    vide = mesure(statut="non_calculable", fraicheur="manquant", dernier_fait_le=None)

    ligne = la_mesure(une([vide], [constat()]))

    assert ligne["etat_collecte"] == "jamais_recue" and "aucun fait n'a été reçu" in ligne["phrase"]
    assert "bus" in ligne["action"]


def test_le_non_calculable_du_producteur_n_est_pas_un_defaut_technique_et_dit_ce_qui_manque():
    """Le constat passe, M5 répond « non calculable, manque X » : il faut une déclaration, pas un geste technique."""
    vide = mesure(statut="non_calculable", fraicheur="manquant", manque=["solde", "paies"])

    ligne = la_mesure(une([vide], [constat()]))

    assert ligne["etat_collecte"] == "producteur_non_calculable"
    assert "solde, paies" in ligne["phrase"] and "constat n'y peut rien" in ligne["action"]


def test_une_mesure_recue_mais_perimee_malgre_un_constat_actif_et_sain_est_source_perimee():
    ligne = la_mesure(une([mesure(fraicheur="perime")], [constat()]))

    assert ligne["etat_collecte"] == "source_perimee"
    assert "plus vieux que la fenêtre" in ligne["phrase"] and "fraicheur_mesures_s" in ligne["action"]


def test_une_fraicheur_inconnue_est_dite_et_jamais_prise_pour_a_jour():
    ligne = la_mesure(une([mesure(fraicheur="inconnu")], [constat()]))
    assert ligne["etat_collecte"] == "fraicheur_inconnue" and ligne["action"]


def test_une_mesure_sans_constat_planifie_le_dit_au_lieu_de_promettre_un_rafraichissement():
    vide = mesure("m8_taux_acceptation_pct", statut="non_calculable", fraicheur="manquant", dernier_fait_le=None,
                  proprietaire="m03-estimation")

    ligne = la_mesure(une([vide], [constat()]), "m8_taux_acceptation_pct")

    assert ligne["etat_collecte"] == "sans_constat_planifie" and ligne["constats"] == []
    assert "m03-estimation" in ligne["phrase"] and "aucun constat n'est à activer" in ligne["action"]


def test_une_mesure_perimee_sans_constat_planifie_est_une_source_perimee_sans_constat_a_activer():
    ligne = la_mesure(une([mesure(fraicheur="perime")], []))
    assert ligne["etat_collecte"] == "source_perimee" and "aucun constat planifié" in ligne["phrase"]


def test_le_coupe_circuit_l_emporte_sur_tout_le_reste():
    vide = mesure(statut="non_calculable", fraicheur="manquant", dernier_fait_le=None)

    diagnostic = une([vide], [constat(mode="actif", dernier_statut="erreur")], autorise=False)

    assert la_mesure(diagnostic)["etat_collecte"] == "planificateur_coupe"
    assert "OPSYS_PLANIFICATEUR_CONNECTEURS" in la_mesure(diagnostic)["action"]
    assert diagnostic["planificateur_autorise"] is False
    assert diagnostic["liste_de_controle"][0] == {
        "etape": "planificateur_autorise", "constat": None, "fait": False,
        "action": la_mesure(diagnostic)["action"]}


def test_un_producteur_non_calculable_ne_masque_pas_un_autre_constat_inactif_qui_nourrit_la_meme_mesure():
    vide = mesure(statut="non_calculable", fraicheur="manquant", manque=["solde"])
    constats = [constat("a.constat.un"), constat("b.constat.deux", mode="inactif")]

    assert la_mesure(une([vide], constats))["etat_collecte"] == "constat_inactif"


def test_l_ordre_des_causes_inactif_avant_erreur_avant_non_calculable():
    vide = mesure(statut="non_calculable", fraicheur="manquant")
    inactif_en_erreur = constat(mode="inactif", dernier_statut="erreur")
    assert la_mesure(une([vide], [inactif_en_erreur]))["etat_collecte"] == "constat_inactif"
    assert la_mesure(une([vide], [constat(dernier_statut="erreur")]))["etat_collecte"] == "constat_en_erreur"
    assert la_mesure(une([vide], [constat()]))["etat_collecte"] == "producteur_non_calculable"


# ================================================================================================ résumé et sortie
def test_le_resume_compte_chaque_mesure_une_fois_et_somme_au_total():
    mesures = [
        mesure("m8_a"), mesure("m8_b", statut="non_calculable", fraicheur="manquant", dernier_fait_le=None),
        mesure("m8_c", fraicheur="perime"), mesure("m8_d", statut="non_calculable", fraicheur="manquant"),
    ]
    constats = [constat("x.constat.a", ("m8_a", "m8_b", "m8_c"), mode="ombre"), constat("x.constat.d", ("m8_d",))]

    diagnostic = une(mesures, constats)

    assert set(diagnostic["resume"]) == set(collecte.etats_possibles())
    assert sum(diagnostic["resume"].values()) == diagnostic["n_mesures"] == 4
    # m8_a est calculée et à jour : elle l'est quel que soit le mode de son constat
    assert diagnostic["resume"]["a_jour"] == 1 and diagnostic["resume"]["constat_en_ombre"] == 2
    assert [m["etat_collecte"] for m in diagnostic["mesures"]] == ["a_jour", "constat_en_ombre", "constat_en_ombre",
                                                           "producteur_non_calculable"]


def test_aucune_valeur_de_mesure_ne_sort_du_diagnostic():
    diagnostic = une([mesure(valeur="27861.98"), mesure("m8_b", valeur="12345.67", fraicheur="perime")], [constat()])

    texte = json.dumps(diagnostic, ensure_ascii=False)

    assert "27861.98" not in texte and "12345.67" not in texte and "valeur" not in texte


def test_la_sortie_est_deterministe_et_ne_modifie_pas_ses_entrees():
    mesures = [mesure("m8_b", fraicheur="perime"), mesure("m8_a")]
    constats = [constat("z.constat", ("m8_b",)), constat("a.constat", ("m8_a",), mode="ombre")]
    avant = copy.deepcopy((mesures, constats))

    premiere, seconde = une(mesures, constats), une(mesures, list(reversed(constats)))

    assert premiere == seconde and (mesures, constats) == avant
    assert [c["executeur"] for c in premiere["constats"]] == ["a.constat", "z.constat"]  # ordre par nom


def test_l_etat_d_un_constat_compte_ses_mesures_a_jour():
    mesures = [mesure("m8_a"), mesure("m8_b", fraicheur="perime"), mesure("m8_c", statut="non_calculable")]

    (etat,) = une(mesures, [constat("x.constat", ("m8_a", "m8_b", "m8_c", "m8_hors_catalogue"))])["constats"]

    assert (etat["mesures_a_jour"], etat["mesures_total"]) == (1, 3)  # une mesure inconnue n'est pas comptée
    assert etat["etat"] == "actif" and etat["dernier_statut"] == "ok"


def test_une_lecture_sans_mesure_le_dit():
    assert une([], [])["lecture"] == "Aucune mesure au catalogue."


# ============================================================================================ liste de contrôle
def test_la_liste_de_controle_suit_l_etat_lu_trois_etapes_par_constat():
    cas = {"inactif": constat("a.i", mode="inactif", dernier_passage=None), "ombre": constat("b.o", mode="ombre"),
           "actif": constat("c.a"), "actif_sans_passage": constat("d.p", dernier_passage=None)}

    etapes = {(e["constat"], e["etape"]): e for e in une([], list(cas.values()))["liste_de_controle"][1:]}

    def fait(nom, etape):
        return etapes[(nom, etape)]["fait"]

    assert [fait("a.i", e) for e in ("activer_en_ombre", "passer_en_actif", "premier_passage_reussi")] == [
        False, False, False]
    assert [fait("b.o", e) for e in ("activer_en_ombre", "passer_en_actif", "premier_passage_reussi")] == [
        True, False, False]
    assert [fait("c.a", e) for e in ("activer_en_ombre", "passer_en_actif", "premier_passage_reussi")] == [
        True, True, True]
    assert [fait("d.p", e) for e in ("activer_en_ombre", "passer_en_actif", "premier_passage_reussi")] == [
        True, True, False]
    assert all((e["action"] is None) == e["fait"] for e in etapes.values())
    assert "a.i" in etapes[("a.i", "activer_en_ombre")]["action"]


def test_un_passage_en_echec_ne_compte_pas_comme_un_premier_passage_reussi():
    etapes = une([], [constat("x.c", dernier_statut="erreur", dernier_code="REJ-X-Y")])["liste_de_controle"]

    assert next(e for e in etapes if e["etape"] == "premier_passage_reussi")["fait"] is False


def test_la_liste_de_controle_commence_par_l_interrupteur_general():
    premier = une([], [constat()])["liste_de_controle"][0]
    assert premier == {"etape": "planificateur_autorise", "constat": None, "fait": True, "action": None}


def test_aucun_constat_declare_une_liste_de_controle_d_une_seule_etape():
    assert len(une([mesure()], [])["liste_de_controle"]) == 1


# ======================================================================================== texte et intégrité des causes
def test_chaque_etat_a_une_phrase_et_une_action_en_francais_sauf_a_jour():
    cas = [
        (mesure(statut="non_calculable", fraicheur="manquant", dernier_fait_le=None), [constat(mode="inactif")], True),
        (mesure(statut="non_calculable", fraicheur="manquant", dernier_fait_le=None), [constat(mode="inactif",
                                                                                              expire=True)], True),
        (mesure(statut="non_calculable", fraicheur="manquant"), [constat(mode="ombre")], True),
        (mesure(statut="non_calculable", fraicheur="manquant"), [constat(dernier_statut="erreur")], True),
        (mesure(statut="non_calculable", fraicheur="manquant", dernier_fait_le=None), [constat()], True),
        (mesure(statut="non_calculable", fraicheur="manquant"), [constat()], True),
        (mesure(fraicheur="perime"), [constat()], True),
        (mesure(fraicheur="inconnu"), [constat()], True),
        (mesure(statut="non_calculable", fraicheur="manquant"), [], True),
        (mesure(fraicheur="perime"), [], True),
        (mesure(statut="non_calculable", fraicheur="manquant"), [constat()], False),
        (mesure(statut="non_calculable", fraicheur="manquant", qualite="echec"), [constat()], True),
    ]
    vues = set()
    for m, constats, autorise in cas:
        ligne = la_mesure(une([m], constats, autorise=autorise))
        vues.add(ligne["etat_collecte"])
        assert ligne["etat_collecte"] in collecte.etats_possibles() and ligne["phrase"] and ligne["action"], ligne
        assert ligne["phrase"].endswith((".", ")")) and "  " not in ligne["phrase"]
    assert vues == set(collecte.etats_possibles()) - {"a_jour"}
