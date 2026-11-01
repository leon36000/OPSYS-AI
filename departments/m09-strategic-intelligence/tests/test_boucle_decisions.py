"""Athéna : la boucle « décision → résultat mesuré → leçon ». La direction décide ; le code compare ; la leçon reste une
proposition tant que la direction ne l'a pas validée ; rien n'est appliqué (fictif)."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
from m9_strategic_intelligence import boucle_decisions as bd
from m9_strategic_intelligence import capture_strategique as cs


def _aide():
    spec = importlib.util.spec_from_file_location("pages_athena", Path(__file__).with_name("pages_athena.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


P = _aide()
FICTIF = True
TAUX = "m8_taux_acceptation_pct"
DELAI = "m8_delai_lead_acceptation_jours"
DECIDE_LE = "2026-10-20T15:00:00Z"
MAINTENANT = "2026-11-20T12:00:00Z"


def lecture(chaine, recu_a, **valeurs):
    """Une lecture de la synthèse M8 reçue à `recu_a` ; `valeurs` : metric_id → dict d'options de `P.mesure`."""
    mesures = [P.mesure(m, **{"unite": "x", **options}) for m, options in valeurs.items()]
    page = P.page_m8(mesures=mesures)
    page["resultat"]["maintenant"] = recu_a
    return P.capturer(chaine, "m8.synthese_direction", page, recu_a, arguments={"maintenant": recu_a})


def captures_base():
    chaine: list = []
    lecture(chaine, "2026-10-19T12:00:00Z", **{TAUX: {"valeur": "40.00"}, DELAI: {"valeur": "10.00"}})
    return chaine


def declarer(chaine_boucle, captures, **kw):
    arguments = {
        "decision_id": "dem-1", "enonce": "Relancer tous les devis sans réponse chaque semaine.",
        "attendus": [{"metric_id": TAUX, "sens": "hausse", "hypothese": "Plus de relances, plus d'acceptations."}],
        "captures": captures, "decide_par": "proprio.fictif", "decide_role": "nathan_owner", "decide_le": DECIDE_LE,
    }  # fmt: skip
    arguments.update(kw)
    return bd.declarer(chaine_boucle, **arguments)


def boucle_apres_decision(captures=None):
    captures = captures if captures is not None else captures_base()
    chaine: list = []
    chaine.append(declarer(chaine, captures))
    return chaine, captures


# ============================================================================================ déclaration
def test_la_decision_garde_la_base_de_comparaison_lue_a_l_instant_de_la_decision():
    chaine, captures = boucle_apres_decision()
    decision = chaine[0]
    (attendu,) = decision["attendus"]
    assert attendu["base"]["valeur"] == "40.00" and attendu["base"]["fraicheur"] == "a_jour"
    assert attendu["base"]["adresse"].startswith("m8.synthese_direction#0:p0.resultat.mesures[0].valeur")
    assert decision["capture_de_base"]["hash_maillon"] == captures[0]["hash_maillon"]
    assert bd.valider_chaine(chaine) == (True, "")


def test_sans_lecture_connue_a_la_decision_la_base_est_inconnue_jamais_reconstituee():
    chaine: list = []
    maillon = declarer(chaine, [])
    assert maillon["capture_de_base"] is None and maillon["attendus"][0]["base"] == {"presente": False}


def test_une_lecture_recue_apres_la_decision_n_est_pas_la_base():
    captures = captures_base()
    lecture(captures, "2026-10-25T12:00:00Z", **{TAUX: {"valeur": "99.00"}})
    maillon = declarer([], captures)
    assert maillon["attendus"][0]["base"]["valeur"] == "40.00"


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"decision_id": "a b"}, "IDENTIFIANT"),
        ({"enonce": "  "}, "ENONCE"),
        ({"enonce": "x" * 601}, "ENONCE"),
        ({"decide_le": "demain"}, "TEMPS"),
        ({"decide_role": "seller"}, "SIGNATAIRE"),
        ({"decide_par": ""}, "SIGNATAIRE"),
        ({"attendus": []}, "ATTENDUS"),
        ({"attendus": [{"metric_id": TAUX, "sens": "explose", "hypothese": "x"}]}, "ATTENDUS"),
        ({"attendus": [{"metric_id": "taux", "sens": "hausse", "hypothese": "x"}]}, "ATTENDUS"),
        ({"attendus": [{"metric_id": TAUX, "sens": "hausse"}]}, "ATTENDUS"),
        ({"attendus": [{"metric_id": TAUX, "sens": "hausse", "hypothese": "x"}] * 2}, "ATTENDUS"),
        ({"suivi_id": "inconnu", "suivis_connus": ["autre"]}, "SUIVI-INCONNU"),
        ({"suivi_id": "inconnu"}, "SUIVI-INCONNU"),
    ],
)
def test_une_decision_hors_forme_est_refusee_nommement(kw, code):
    with pytest.raises(ValueError, match=f"REJ-BOUCLE-{code}"):
        declarer([], captures_base(), **kw)


def test_un_suivi_existant_peut_etre_reference_et_un_doublon_est_refuse():
    chaine, captures = boucle_apres_decision()
    ok = declarer([], captures, suivi_id="suivi-1", suivis_connus=["suivi-1"])
    assert ok["suivi_id"] == "suivi-1"
    with pytest.raises(ValueError, match="REJ-BOUCLE-DOUBLON"):
        declarer(chaine, captures)


# ============================================================================================ mesure
def test_une_hausse_attendue_et_observee_concorde_sans_aucune_difference_calculee():
    chaine, captures = boucle_apres_decision()
    lecture(captures, "2026-11-19T12:00:00Z", **{TAUX: {"valeur": "55.00"}, DELAI: {"valeur": "9.00"}})
    ajouts = bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT)
    assert [a["type"] for a in ajouts] == ["RESULTAT", "LECON"]
    (obs,) = ajouts[0]["observations"]
    assert (obs["sens_observe"], obs["concordance"], obs["valeur_avant"], obs["valeur_apres"]) == (
        "hausse", "CONCORDE", "40.00", "55.00")  # fmt: skip
    assert ajouts[0]["concordance"] == "CONCORDE"
    assert "variation" not in str(ajouts) and "ecart" not in str(ajouts)
    lecon = ajouts[1]
    assert lecon["statut"] == bd.STATUT_LECON and lecon["lecon_id"].startswith("lecon-")
    assert "Aucune cause n'est établie" in lecon["texte"] and "40.00 → 55.00" in lecon["texte"]
    assert bd.valider_chaine([*chaine, *ajouts]) == (True, "")


def test_une_baisse_alors_qu_une_hausse_etait_attendue_ne_concorde_pas_et_la_lecon_le_dit():
    chaine, captures = boucle_apres_decision()
    lecture(captures, "2026-11-19T12:00:00Z", **{TAUX: {"valeur": "31.50"}})
    ajouts = bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT)
    assert ajouts[0]["concordance"] == "NE_CONCORDE_PAS" and ajouts[0]["observations"][0]["sens_observe"] == "baisse"
    assert "attendu hausse, observé baisse" in ajouts[1]["texte"]


def test_stable_est_un_sens_et_l_egalite_decimale_ne_depend_pas_de_l_ecriture():
    chaine, captures = boucle_apres_decision()
    lecture(captures, "2026-11-19T12:00:00Z", **{TAUX: {"valeur": "40.0"}})
    ajouts = bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT)
    assert ajouts[0]["observations"][0]["sens_observe"] == "stable"


@pytest.mark.parametrize(
    ("options", "raison"),
    [
        ({"valeur": "55.00", "fraicheur": "perime", "age": 999999}, "mesure_perimee_ou_inconnue"),
        ({"valeur": None, "fraicheur": "manquant"}, "mesure_non_calculable"),
    ],
)
def test_une_mesure_perimee_ou_non_calculable_est_non_mesurable_et_aucune_lecon_n_est_proposee(options, raison):
    chaine, captures = boucle_apres_decision()
    lecture(captures, "2026-11-19T12:00:00Z", **{TAUX: options})
    ajouts = bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT)
    assert [a["type"] for a in ajouts] == ["RESULTAT"], "non mesurable n'est pas une leçon"
    obs = ajouts[0]["observations"][0]
    assert (obs["concordance"], obs["raison"], obs["sens_observe"]) == ("NON_MESURABLE", raison, None)
    assert ajouts[0]["concordance"] == "NON_MESURABLE"


def test_sans_lecture_posterieure_la_mesure_est_non_mesurable():
    chaine, captures = boucle_apres_decision()
    ajouts = bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT)
    assert ajouts[0]["observations"][0]["raison"] == "aucune_lecture_posterieure"
    assert ajouts[0]["capture_apres"]["hash_maillon"] == captures[0]["hash_maillon"]


def test_une_definition_changee_ou_une_base_inconnue_interdit_de_conclure():
    chaine, captures = boucle_apres_decision()
    page = P.page_m8(mesures=[P.mesure(TAUX, valeur="55.00", unite="x")])
    page["resultat"]["mesures"][0]["version_definition"] = "ffffffffffffffff"
    page["resultat"]["maintenant"] = "2026-11-19T12:00:00Z"
    P.capturer(captures, "m8.synthese_direction", page, "2026-11-19T12:00:00Z",
        arguments={"maintenant": "2026-11-19T12:00:00Z"})
    ajouts = bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT)
    assert ajouts[0]["observations"][0]["raison"] == "definition_changee"
    sans_base: list = []
    sans_base.append(declarer(sans_base, []))
    lecture(captures, "2026-11-20T11:00:00Z", **{TAUX: {"valeur": "60.00"}})
    ajouts2 = bd.mesurer(sans_base, "dem-1", captures=captures, maintenant=MAINTENANT)
    assert ajouts2[0]["observations"][0]["raison"] == "base_inconnue" and len(ajouts2) == 1


def test_une_capture_refusee_ou_contradictoire_n_est_jamais_la_lecture_posterieure():
    chaine, captures = boucle_apres_decision()
    P.capturer(captures, "m8.synthese_direction", {"ok": False, "erreur": "indisponible"}, "2026-11-19T12:00:00Z",
               arguments={"maintenant": "2026-11-19T12:00:00Z"})  # fmt: skip
    ajouts = bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT)
    assert ajouts[0]["capture_apres"] is None
    assert ajouts[0]["observations"][0]["raison"] == "aucune_lecture_posterieure"


def test_plusieurs_attendus_donnent_une_concordance_mixte_ou_non_mesurable_sans_moyenne():
    captures = captures_base()
    attendus = [{"metric_id": TAUX, "sens": "hausse", "hypothese": "a"}, {"metric_id": DELAI, "sens": "baisse",
        "hypothese": "b"}]
    chaine: list = []
    chaine.append(declarer(chaine, captures, attendus=attendus))
    lecture(captures, "2026-11-19T12:00:00Z", **{TAUX: {"valeur": "55.00"}, DELAI: {"valeur": "12.00"}})
    resultat = bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT)[0]
    assert resultat["concordance"] == "MIXTE"
    assert [o["concordance"] for o in resultat["observations"]] == ["CONCORDE", "NE_CONCORDE_PAS"]
    assert bd.concordance_globale([]) == "NON_MESURABLE"
    assert bd.concordance_globale([{"concordance": "CONCORDE"}, {"concordance": "NON_MESURABLE"}]) == "MIXTE"


def test_mesurer_deux_fois_la_meme_chose_ne_cree_rien_et_une_nouvelle_lecture_cree_une_nouvelle_mesure():
    chaine, captures = boucle_apres_decision()
    lecture(captures, "2026-11-19T12:00:00Z", **{TAUX: {"valeur": "55.00"}})
    chaine.extend(bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT))
    assert bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT) == []
    assert bd.mesurer(chaine, "dem-1", captures=captures, maintenant="2026-11-21T12:00:00Z") == []
    lecture(captures, "2026-11-22T12:00:00Z", **{TAUX: {"valeur": "30.00"}})
    nouveaux = bd.mesurer(chaine, "dem-1", captures=captures, maintenant="2026-11-23T12:00:00Z")
    assert [a["type"] for a in nouveaux] == ["RESULTAT", "LECON"]


def test_mesure_refusee_pour_decision_inconnue_ou_instant_invalide_ou_anterieur():
    chaine, captures = boucle_apres_decision()
    with pytest.raises(ValueError, match="REJ-BOUCLE-INCONNUE"):
        bd.mesurer(chaine, "autre", captures=captures, maintenant=MAINTENANT)
    with pytest.raises(ValueError, match="REJ-BOUCLE-TEMPS"):
        bd.mesurer(chaine, "dem-1", captures=captures, maintenant="demain")
    with pytest.raises(ValueError, match="REJ-BOUCLE-TEMPS"):
        bd.mesurer(chaine, "dem-1", captures=captures, maintenant="2026-10-01T00:00:00Z")


# ============================================================================================ leçon et mémoire
def chaine_avec_lecon():
    chaine, captures = boucle_apres_decision()
    lecture(captures, "2026-11-19T12:00:00Z", **{TAUX: {"valeur": "55.00"}})
    chaine.extend(bd.mesurer(chaine, "dem-1", captures=captures, maintenant=MAINTENANT))
    lecon_id = next(e["lecon_id"] for e in chaine if e["type"] == "LECON")
    return chaine, lecon_id


def valider(chaine, lecon_id, statut="validee", **kw):
    options = {"decide_par": "proprio.fictif", "decide_role": "nathan_owner", "decide_le": "2026-11-21T09:00:00Z", **kw}
    return bd.valider_lecon(chaine, lecon_id, statut, **options)


def test_l_etat_suit_la_boucle_de_declaree_a_lecon_validee():
    chaine, captures = boucle_apres_decision()
    assert bd.etat(chaine, "dem-1")["etat"] == "declaree"
    chaine, lecon_id = chaine_avec_lecon()
    etat = bd.etat(chaine, "dem-1")
    assert etat["etat"] == "lecon_proposee" and etat["lecon"]["statut"] == bd.STATUT_LECON
    chaine.append(valider(chaine, lecon_id))
    etat = bd.etat(chaine, "dem-1")
    assert etat["etat"] == "lecon_validee" and etat["lecon"]["statut"] == "VALIDEE"


def test_la_validation_est_humaine_motivee_au_rejet_et_unique():
    chaine, lecon_id = chaine_avec_lecon()
    with pytest.raises(ValueError, match="REJ-BOUCLE-MOTIF"):
        valider(chaine, lecon_id, "rejetee")
    with pytest.raises(ValueError, match="REJ-BOUCLE-STATUT"):
        valider(chaine, lecon_id, "appliquee")
    with pytest.raises(ValueError, match="REJ-BOUCLE-SIGNATAIRE"):
        valider(chaine, lecon_id, decide_role="seller")
    with pytest.raises(ValueError, match="REJ-BOUCLE-LECON-INCONNUE"):
        valider(chaine, "lecon-inconnue")
    rejet = valider(chaine, lecon_id, "rejetee", motif="Trop peu de semaines observées.")
    chaine.append(rejet)
    assert bd.etat(chaine, "dem-1")["etat"] == "lecon_rejetee"
    with pytest.raises(ValueError, match="REJ-BOUCLE-DEJA-DECIDEE"):
        valider(chaine, lecon_id)


def test_seule_une_lecon_validee_est_preparee_pour_la_memoire_de_connaissances():
    chaine, lecon_id = chaine_avec_lecon()
    with pytest.raises(ValueError, match="REJ-BOUCLE-LECON-NON-VALIDEE"):
        bd.source_connaissance(chaine, lecon_id)
    chaine.append(valider(chaine, lecon_id, "rejetee", motif="Hors sujet."))
    with pytest.raises(ValueError, match="REJ-BOUCLE-LECON-NON-VALIDEE"):
        bd.source_connaissance(chaine, lecon_id)
    chaine2, lecon2 = chaine_avec_lecon()
    chaine2.append(valider(chaine2, lecon2))
    source = bd.source_connaissance(chaine2, lecon2)
    assert source["departement"] == "m09-strategic-intelligence" and source["domaine"] == "general"
    assert source["type_autorite"] == "interne" and source["licence_reutilisation"] == "interne"
    assert source["cle"] == lecon2 and "Aucune cause" in source["contenu"] and "CPA" in source["contenu"]


def test_chaque_entree_devient_un_evenement_idempotent_sans_nom_de_personne():
    chaine, lecon_id = chaine_avec_lecon()
    chaine.append(valider(chaine, lecon_id))
    charges = [bd.evenement_fait(e, chaine) for e in chaine]
    assert [c["genre"] for c in charges] == ["decision", "resultat_observe", "lecon", "lecon"]
    assert [c["statut"] for c in charges] == [
        "declaree_par_la_direction", "observe_par_mesure", "proposee_non_validee",
            "validee_par_la_direction"]  # fmt: skip
    assert len({c["evenement_id"] for c in charges}) == 4
    assert all(c["evenement_id"] == "m9-strat-" + e["hash_maillon"] for c, e in zip(charges, chaine, strict=True))
    assert charges == [bd.evenement_fait(e, chaine) for e in chaine], "déterministe"
    assert "proprio.fictif" not in str(charges), "aucun nom de personne : seulement le rôle"
    assert charges[0]["decide_role"] == "nathan_owner" and charges[0]["attendus"] == [{"metric_id": TAUX,
        "sens": "hausse"}]
    assert all(c["enregistre_le"] for c in charges)


def test_une_chaine_alteree_est_detectee():
    chaine, _ = chaine_avec_lecon()
    assert bd.valider_chaine(chaine) == (True, "")
    truquee = copy.deepcopy(chaine)
    truquee[1]["observations"][0]["sens_observe"] = "baisse"
    assert bd.valider_chaine(truquee)[0] is False
    retiree = [chaine[0], chaine[2]]
    assert bd.valider_chaine(retiree)[0] is False
    assert cs.empreinte(chaine) == cs.empreinte(copy.deepcopy(chaine))
