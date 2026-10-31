"""M9.15 — playbooks gouvernés : déclencheurs réels, étapes sensibles validées par un humain, critères lus (fictif)."""

import re

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import conseil, risques
from m9_strategic_intelligence import playbooks as pb

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"


def _enveloppe(contenu):
    return {"ok": True, "resultat": {"accepte": True, "resultat": contenu}}


def _disponibilite(statut):
    lignes = (
        [] if statut is None else [{"devis_id": "D1", "chantier_id": "C1", "statut": statut, "lignes_manquantes": []}]
    )
    return _enveloppe({"articles": [{"materiau_id": "M1"}], "tronque": False, "reservations_actives": lignes})


def _tresorerie(statut="ALERTE", calculable=True):
    return _enveloppe(
        {
            "calculable": calculable,
            "alerte": {"statut": statut},
            "premiere_semaine_en_deficit": None,
            "prochain_depart": None,
        }
    )


def _retards(incidents=(), reports=()):
    return _enveloppe(
        {"reports": {"liste": list(reports), "reste": 0}, "incidents": {"liste": list(incidents), "reste": 0}}
    )


def _chaine(*specs):
    chaine, precedent = [], cs.HASH_INITIAL
    for index, (lecture, reponse, recu) in enumerate(specs):
        capture = cs.construire(
            cat.obtenir(lecture), {}, [reponse], recu_a=recu, reference=None, index=index, hash_precedent=precedent
        )
        chaine.append(capture)
        precedent = capture["hash_maillon"]
    return chaine


def _plan(playbook, chaine, **kwargs):
    radar = risques.evaluer(chaine, connaissance=CONNAISSANCE)
    return pb.instancier(playbook, radar, connaissance=CONNAISSANCE, **kwargs), radar


SIX_D_ORIGINE = {"cash", "baisse_leads", "surcharge", "meteo", "rupture", "hausse_prix"}
ONZE_NOUVEAUX = {
    "trop_de_leads",
    "risque_plaintes",
    "conversion_devis_faible",
    "roi_marketing_faible",
    "debut_de_saison",
    "reserve_fin_de_saison",
    "embauche",
    "achat_equipement",
    "expansion_ville",
    "nouveau_service",
    "relance_avis_clients",
}


def test_les_dix_sept_gabarits_existent_et_leurs_etapes_sensibles_sont_connues_du_conseil():
    assert set(pb.CATALOGUE) == SIX_D_ORIGINE | ONZE_NOUVEAUX and len(pb.CATALOGUE) == 17
    for id_, gabarit in pb.CATALOGUE.items():
        sensibles = [e for e in gabarit["etapes"] if e["type"] == "action_sensible"]
        if id_ in SIX_D_ORIGINE:
            assert sensibles, "chaque playbook d'origine dit où une validation humaine est requise"
        assert all(e["genre"] in conseil.ACTIONS_SENSIBLES for e in sensibles)
        assert gabarit["succes"] and gabarit["arret"] and gabarit["limites"]


def test_champs_obligatoires_de_chaque_gabarit():
    for id_, gabarit in pb.CATALOGUE.items():
        assert set(pb.CHAMPS) | {"approbation_requise"} <= set(gabarit), id_
        assert gabarit["donnees_requises"] and set(gabarit["donnees_requises"]) <= set(cat.PAR_ID), id_
        assert gabarit["departements"] == sorted(set(gabarit["departements"]))
        assert all(re.fullmatch(r"m(0[1-9]|10)", d) for d in gabarit["departements"]), id_
        assert gabarit["risques"] and all(isinstance(r, str) and r for r in gabarit["risques"]), id_
        assert isinstance(gabarit["plan_retour"], str) and len(gabarit["plan_retour"]) > 20, id_
        for critere in [*gabarit["succes"], *gabarit["arret"]]:
            assert critere["lecture"] in gabarit["donnees_requises"], f"{id_}.{critere['id']} hors données requises"
        for etape in gabarit["etapes"]:
            if etape["qui"] != "m9":
                assert etape["qui"][:3] in gabarit["departements"], f"{id_}.{etape['id']} : département non déclaré"


def test_approbation_requise_est_derivee_des_etapes_sensibles():
    for id_, gabarit in pb.CATALOGUE.items():
        attendu = any(e["type"] == "action_sensible" for e in gabarit["etapes"])
        assert gabarit["approbation_requise"] is attendu, id_
    assert pb.CATALOGUE["relance_avis_clients"]["approbation_requise"] is False, "l'envoi reste à la file M7"
    assert pb.CATALOGUE["embauche"]["approbation_requise"] is True
    menteur = {"cash": {**pb.CATALOGUE["cash"], "approbation_requise": False}}
    with pytest.raises(ValueError, match="REJ-PLAYBOOK-GABARIT"):
        pb.verifier_catalogue(menteur)


@pytest.mark.parametrize(
    "alteration",
    [
        lambda g: {k: v for k, v in g.items() if k != "plan_retour"},
        lambda g: {**g, "plan_retour": "  "},
        lambda g: {k: v for k, v in g.items() if k != "donnees_requises"},
        lambda g: {**g, "donnees_requises": ["m2.leads", "m99.inventee"]},
        lambda g: {**g, "donnees_requises": []},
        lambda g: {**g, "departements": ["m11"]},
        lambda g: {**g, "departements": ["m05"]},  # m09 (étape sensible orchestrée par M9) non déclaré
        lambda g: {**g, "risques": []},
        lambda g: {**g, "declenche_par": ["regle_inventee"]},
        lambda g: {**g, "donnees_requises": ["m5.comptes_a_recevoir"]},  # critère sur une lecture non requise
    ],
)
def test_gabarit_incomplet_ou_incoherent_refuse_au_chargement(alteration):
    with pytest.raises(ValueError, match="REJ-PLAYBOOK-GABARIT"):
        pb.verifier_catalogue({"cash": alteration(dict(pb.CATALOGUE["cash"]))})
    assert pb.verifier_catalogue({"cash": pb.CATALOGUE["cash"]})["cash"]["approbation_requise"] is True


@pytest.mark.parametrize("playbook", sorted(ONZE_NOUVEAUX))
def test_nouveaux_gabarits_instancies_sans_effet_et_a_declarer(playbook):
    plan, _ = _plan(playbook, [])
    assert plan["declenchement"]["statut"] == "A_DECLARER", "aucun producteur ne mesure ces signaux"
    for etape in plan["etapes"]:
        assert etape["effet_autorise"] is False
        if etape["type"] == "action_sensible":
            assert etape["statut"] == "VALIDATION_HUMAINE_REQUISE"
            assert etape["proprietaire_decision"] == conseil.ACTIONS_SENSIBLES[etape["genre"]]
        else:
            assert etape["statut"] == "PROPOSABLE"
    gabarit = pb.CATALOGUE[playbook]
    for champ in ("donnees_requises", "departements", "risques", "approbation_requise", "plan_retour"):
        assert plan[champ] == gabarit[champ]
    for critere in [*plan["succes"], *plan["arret"]]:
        if critere["cible_a_lier"]:
            assert critere["cible"] is None and critere["cible_declaree_par_la_personne"] is False
    # Sans capture, aucun critère n'est réputé satisfait ; une cible non liée reste inconnue.
    evaluation = pb.evaluer_criteres(plan, [], connaissance=CONNAISSANCE)
    assert evaluation["verdict"] in {"INCONNU", "EN_COURS"}
    assert all(c["statut"] != "SATISFAIT" for c in [*evaluation["succes"], *evaluation["arret"]])


def test_aucune_etape_d_aucun_gabarit_n_autorise_d_effet():
    for playbook in pb.CATALOGUE:
        plan = pb.instancier(playbook, None, connaissance=CONNAISSANCE, declare_par_la_personne=True)
        assert all(e["effet_autorise"] is False for e in plan["etapes"])
        assert plan["approbation_requise"] is any(e["statut"] == "VALIDATION_HUMAINE_REQUISE" for e in plan["etapes"])


def test_cible_de_la_personne_liee_sur_un_nouveau_gabarit():
    lecture = _enveloppe({"total": 12, "leads": [{"lead_id": "L1"}]})
    chaine = _chaine(("m2.leads", lecture, "2026-10-27T12:00:00Z"))
    sans_cible, _ = _plan("trop_de_leads", chaine, declare_par_la_personne=True)
    ev = pb.evaluer_criteres(sans_cible, chaine, connaissance=CONNAISSANCE)
    assert ev["succes"][0]["statut"] == "INCONNU", "sans cible de la personne : jamais de valeur par défaut"
    lie, _ = _plan("trop_de_leads", chaine, declare_par_la_personne=True, liaisons={"leads_resorbes": "15"})
    assert pb.evaluer_criteres(lie, chaine, connaissance=CONNAISSANCE)["succes"][0]["statut"] == "SATISFAIT"
    serre, _ = _plan("trop_de_leads", chaine, declare_par_la_personne=True, liaisons={"leads_resorbes": "10"})
    assert pb.evaluer_criteres(serre, chaine, connaissance=CONNAISSANCE)["succes"][0]["statut"] == "NON_SATISFAIT"


def test_rupture_declenchee_par_une_reservation_partielle_et_etapes_gouvernees():
    chaine = _chaine(("m6.disponibilite", _disponibilite("partiel"), "2026-10-27T12:00:00Z"))
    plan, radar = _plan("rupture", chaine)
    assert plan["declenchement"]["statut"] == "DECLENCHE" and plan["declenchement"]["risques"]
    par_id = {e["id"]: e for e in plan["etapes"]}
    assert (
        par_id["commander"]["statut"] == "VALIDATION_HUMAINE_REQUISE"
        and par_id["commander"]["proprietaire_decision"] == "Nathan"
    )
    assert (
        par_id["identifier"]["statut"] == "PROPOSABLE"
        and par_id["identifier"]["proprietaire_decision"] == "m06-material-control"
    )
    assert all(e["effet_autorise"] is False for e in plan["etapes"])
    assert len(plan["playbook_instance_id"]) == 64 and radar["radar_id"]


def test_sans_signal_non_declenche_et_lecture_absente_inconnu():
    ok = _chaine(("m6.disponibilite", _disponibilite(None), "2026-10-27T12:00:00Z"))
    assert _plan("rupture", ok)[0]["declenchement"]["statut"] == "NON_DECLENCHE"
    assert _plan("rupture", [])[0]["declenchement"]["statut"] == "INCONNU"
    perime = _chaine(("m6.disponibilite", _disponibilite("partiel"), "2026-09-01T12:00:00Z"))
    radar = risques.evaluer(perime, connaissance=CONNAISSANCE, perime_apres_jours=7)
    assert pb.instancier("rupture", radar, connaissance=CONNAISSANCE)["declenchement"]["statut"] == "INCONNU"


def test_playbooks_sans_mesure_automatique_se_declarent_et_le_disent():
    plan, _ = _plan("baisse_leads", [])
    assert plan["declenchement"]["statut"] == "A_DECLARER"
    declare, _ = _plan("hausse_prix", [], declare_par_la_personne=True)
    assert (
        declare["declenchement"]["statut"] == "DECLENCHE"
        and declare["declenchement"]["declare_par_la_personne"] is True
    )
    assert any("déclar" in limite for limite in declare["limites"])


def test_criteres_succes_arret_et_cible_non_liee():
    avant = _chaine(("m6.disponibilite", _disponibilite("partiel"), "2026-10-26T12:00:00Z"))
    plan, _ = _plan("rupture", avant)
    assert pb.evaluer_criteres(plan, avant, connaissance=CONNAISSANCE)["verdict"] == "EN_COURS"
    apres = _chaine(
        ("m6.disponibilite", _disponibilite("partiel"), "2026-10-26T12:00:00Z"),
        ("m6.disponibilite", _disponibilite("pret"), "2026-10-27T12:00:00Z"),
    )
    evalue = pb.evaluer_criteres(plan, apres, connaissance=CONNAISSANCE)
    assert evalue["verdict"] == "SUCCES" and evalue["succes"][0]["source"]["capture"] == 1
    # Connaissance antérieure à la seconde lecture : le succès n'était pas connu.
    assert pb.evaluer_criteres(plan, apres, connaissance="2026-10-26T18:00:00Z")["verdict"] == "EN_COURS"
    sans_article = _enveloppe({"articles": [], "tronque": False, "reservations_actives": []})
    arret = _chaine(("m6.disponibilite", sans_article, "2026-10-27T12:00:00Z"))
    assert pb.evaluer_criteres(plan, arret, connaissance=CONNAISSANCE)["verdict"] == "ARRET"
    # Une lecture tronquée est PARTIELLE : ni succès ni arrêt ne se lisent dessus, le verdict reste inconnu.
    tronque = _enveloppe({"articles": [], "tronque": True, "reservations_actives": []})
    partielle = _chaine(("m6.disponibilite", tronque, "2026-10-27T12:00:00Z"))
    assert pb.evaluer_criteres(plan, partielle, connaissance=CONNAISSANCE)["verdict"] == "INCONNU"
    # cible de la personne absente : INCONNU ; liée : évaluée en nombre.
    sans_cible, _ = _plan("hausse_prix", [], declare_par_la_personne=True)
    assert pb.evaluer_criteres(sans_cible, [], connaissance=CONNAISSANCE)["verdict"] == "INCONNU"
    mesures = {
        "ok": True,
        "resultat": {"trouve": True, "mesures": [{"metric_id": "m8_marge_reelle_cad", "valeur": "114.00"}]},
    }
    chaine = _chaine(("m8.mesures_chantier", mesures, "2026-10-27T12:00:00Z"))
    lie, _ = _plan("hausse_prix", chaine, declare_par_la_personne=True, liaisons={"marge_retablie": "100"})
    ev = pb.evaluer_criteres(lie, chaine, connaissance=CONNAISSANCE)
    assert ev["succes"][0]["statut"] == "SATISFAIT" and ev["succes"][0]["cible"] == "100"
    haut, _ = _plan("hausse_prix", chaine, declare_par_la_personne=True, liaisons={"marge_retablie": "200"})
    assert pb.evaluer_criteres(haut, chaine, connaissance=CONNAISSANCE)["succes"][0]["statut"] == "NON_SATISFAIT"


def test_surcharge_et_cash_lisent_leurs_captures():
    incident = {"demande_id": "R1", "bloquee": True, "depuis": "2026-10-27T10:00:00Z"}
    chaine = _chaine(
        ("m4.retards_incidents", _retards(incidents=[incident]), "2026-10-27T12:00:00Z"),
        ("m5.prevision_tresorerie", _tresorerie("ALERTE"), "2026-10-27T12:00:01Z"),
    )
    surcharge, _ = _plan("surcharge", chaine)
    assert surcharge["declenchement"]["statut"] == "DECLENCHE"
    ev = pb.evaluer_criteres(surcharge, chaine, connaissance=CONNAISSANCE)
    assert ev["succes"][0]["statut"] == "NON_SATISFAIT" and ev["arret"][0]["statut"] == "A_JUGER_PAR_LA_PERSONNE"
    assert ev["verdict"] == "EN_COURS", "un critère à juger par la personne ne ferme jamais le playbook"
    cash, _ = _plan("cash", chaine)
    assert cash["declenchement"]["statut"] == "DECLENCHE"
    non_calculable = _chaine(
        ("m5.prevision_tresorerie", _tresorerie("NON_EVALUEE", calculable=False), "2026-10-27T12:00:00Z")
    )
    plan, _ = _plan("cash", non_calculable)
    assert pb.evaluer_criteres(plan, non_calculable, connaissance=CONNAISSANCE)["verdict"] == "ARRET"


def test_meteo_ne_se_declenche_que_sur_un_report_meteo():
    meteo = {"intervention_id": "I1", "motif": "meteo", "depuis": "2026-10-27T10:00:00Z"}
    autre = {"intervention_id": "I2", "motif": "client_absent", "depuis": "2026-10-27T10:00:00Z"}
    chaine = _chaine(("m4.retards_incidents", _retards(reports=[meteo, autre]), "2026-10-27T12:00:00Z"))
    assert _plan("meteo", chaine)[0]["declenchement"]["statut"] == "DECLENCHE"
    seul = _chaine(("m4.retards_incidents", _retards(reports=[autre]), "2026-10-27T12:00:00Z"))
    assert _plan("meteo", seul)[0]["declenchement"]["statut"] == "NON_DECLENCHE"


@pytest.mark.parametrize(
    "arguments, code",
    [
        ({"playbook_id": "inconnu"}, "REJ-PLAYBOOK-INCONNU"),
        ({"playbook_id": "cash", "liaisons": {"critere_inconnu": "1"}}, "REJ-PLAYBOOK-LIAISON"),
        ({"playbook_id": "cash", "liaisons": {"alerte_levee": "abc"}}, "REJ-PLAYBOOK-LIAISON"),
    ],
)
def test_refus_nommes(arguments, code):
    playbook_id = arguments.pop("playbook_id")
    with pytest.raises(ValueError, match=code):
        pb.instancier(playbook_id, None, connaissance=CONNAISSANCE, **arguments)


def test_identifiant_d_instance_lie_au_contenu():
    a, _ = _plan("hausse_prix", [], declare_par_la_personne=True, liaisons={"marge_retablie": "100"})
    b, _ = _plan("hausse_prix", [], declare_par_la_personne=True, liaisons={"marge_retablie": "101"})
    assert a["playbook_instance_id"] != b["playbook_instance_id"]
