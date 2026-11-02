"""Athéna → M10 : la mémoire des faits stratégiques (`m9.fait_strategique`), décisions de la direction, résultats
mesurés
et leçons. Liste blanche et formes fermées ; FINANCIAL ; idempotence ; une leçon proposée n'est jamais « validée » par
M10
(fictif, vrai bus, vraie base migrée)."""

from __future__ import annotations

import copy

import pytest
from m10_memoire import outils, registre, strategique

from opsys import evenements, stockage
from opsys.departements import charger_departements

FICTIF = True
EMPREINTE = "c" * 64


def _charge(numero=1, genre="decision", **surcharges):
    base = {
        "evenement_id": "m9-strat-" + f"{numero:064x}",
        "genre": "decision",
        "decision_id": "dem-fictive-1",
        "lecon_id": None,
        "statut": "declaree_par_la_direction",
        "texte": "Relancer tous les devis sans réponse chaque semaine.",
        "attendus": [{"metric_id": "m8_taux_acceptation_pct", "sens": "hausse"}],
        "observations": [],
        "concordance": None,
        "decide_role": "nathan_owner",
        "enregistre_le": "2026-10-20T15:00:00Z",
        "source_empreinte": EMPREINTE,
        "mention": "Les leçons ne sont ni des causes ni des avis comptables ; À valider auprès d'un CPA.",
    }
    if genre == "resultat_observe":
        base.update(
            genre=genre, statut="observe_par_mesure", texte=None, attendus=[], concordance="CONCORDE", decide_role=None,
            observations=[{"metric_id": "m8_taux_acceptation_pct", "sens_attendu": "hausse", "sens_observe": "hausse",
                           "valeur_avant": "40.00", "valeur_apres": "55.00", "concordance": "CONCORDE"}],
        )  # fmt: skip
    elif genre == "lecon":
        base.update(genre=genre, statut="proposee_non_validee", lecon_id="lecon-" + "a" * 24, attendus=[],
                    concordance="CONCORDE", decide_role=None, texte="Concordance CONCORDE. Aucune cause n'est "
                                                                    "établie.")  # fmt: skip
    base.update(surcharges)
    return base


def test_la_charge_valide_est_gardee_par_liste_blanche_et_posee_financiere():
    charge = _charge(confidentialite="PUBLIC_INTERNAL", producteur="m99", type_entree="evenement_memorise", lead_id="x")
    with pytest.raises(strategique.ChampRefuse):  # une clé de plus est refusée, pas ignorée
        strategique.extraire(charge)
    entree = strategique.entree(strategique.extraire(_charge()))
    assert entree["type_entree"] == "fait_strategique" and entree["producteur"] == "m09-strategic-intelligence"
    assert entree["confidentialite"] == "FINANCIAL" and entree["horodatage"] == "2026-10-20T15:00:00Z"


@pytest.mark.parametrize(
    ("mutation", "champ"),
    [
        (lambda c: c.pop("texte"), "texte"),
        (lambda c: c.update({"evenement_id": "m9-strat-xyz"}), "evenement_id"),
        (lambda c: c.update({"genre": "conclusion"}), "genre/statut"),
        # une décision n'est pas une leçon validée
        (lambda c: c.update({"statut": "validee_par_la_direction"}), "genre/statut"),
        (lambda c: c.update({"enregistre_le": "hier"}), "enregistre_le"),
        (lambda c: c.update({"source_empreinte": "Z" * 64}), "source_empreinte"),
        (lambda c: c.update({"decision_id": "a b"}), "decision_id"),
        (lambda c: c.update({"attendus": []}), "decision : énoncé et attendus requis"),
        (lambda c: c.update({"texte": None}), "decision : énoncé et attendus requis"),
        (lambda c: c.update({"texte": "x" * 1201}), "texte"),
        (lambda c: c["attendus"][0].update({"sens": "explose"}), "attendus[0]"),
        (lambda c: c["attendus"][0].update({"metric_id": "taux"}), "attendus[0].metric_id"),
        (lambda c: c["attendus"][0].update({"nom_du_client": "x"}), "attendus[0]"),
        (lambda c: c.update({"decide_role": "seller"}), "decide_role"),
        (lambda c: c.update({"concordance": "PEUT-ETRE"}), "concordance"),
        (lambda c: c.update({"mention": ""}), "mention"),
        (lambda c: c.update({"attendus": [c["attendus"][0]] * 9}), "attendus/observations"),
    ],
)
def test_un_champ_hors_de_sa_forme_est_refuse_et_le_detail_nomme_le_champ(mutation, champ):
    charge = _charge()
    mutation(charge)
    with pytest.raises(strategique.ChampRefuse) as exc:
        strategique.extraire(charge)
    assert exc.value.detail == champ


def test_les_observations_et_les_lecons_ont_leur_propre_forme():
    resultat = _charge(genre="resultat_observe")
    for mutation, champ in (
        (lambda c: c["observations"][0].update({"valeur_avant": "40,00"}), "observations[0].valeur_avant"),
        (lambda c: c["observations"][0].update({"sens_observe": None}), "observations[0].sens_observe"),
        (lambda c: c["observations"][0].update({"concordance": "NON_MESURABLE"}), "observations[0].sens_observe"),
        (lambda c: c.update({"observations": []}), "resultat_observe : observations et concordance requises"),
        (lambda c: c.update({"concordance": None}), "resultat_observe : observations et concordance requises"),
    ):
        charge = copy.deepcopy(resultat)
        mutation(charge)
        with pytest.raises(strategique.ChampRefuse) as exc:
            strategique.extraire(charge)
        assert exc.value.detail == champ
    sans_id = _charge(genre="lecon", lecon_id=None)
    with pytest.raises(strategique.ChampRefuse, match="lecon"):
        strategique.extraire(sans_id)
    assert strategique.extraire(_charge(genre="lecon"))["statut"] == "proposee_non_validee"
    non_mesurable = _charge(genre="resultat_observe", concordance="NON_MESURABLE")
    non_mesurable["observations"][0].update(sens_observe=None, valeur_apres=None, concordance="NON_MESURABLE")
    assert strategique.extraire(non_mesurable)["observations"][0]["sens_observe"] is None


def _charge_risque(numero=7, **surcharges):
    base = _charge(numero, decision_id="avis-" + "d" * 24, statut="signale_par_le_radar",
                   texte="Risque critique (cash) : le cash libre constaté par M5 est négatif. Aucune cause établie.",
                   attendus=[], decide_role=None)
    base["genre"] = "risque"
    base.update(surcharges)
    return base


def test_un_risque_critique_du_radar_de_m9_est_memorise_sans_lecon_sans_attendus_sans_signataire():
    cible = registre.Registre()
    resultat, verdict = strategique.memoriser(_charge_risque(), cible)
    assert verdict is None and resultat["maillon"]["genre"] == "risque"
    assert resultat["maillon"]["statut"] == "signale_par_le_radar"
    assert resultat["maillon"]["confidentialite"] == "FINANCIAL"
    rejoue, _ = strategique.memoriser(_charge_risque(), cible)
    assert rejoue["deja_memorise"] is True and len(cible.lire()) == 1
    page = strategique.lister(cible, 8, 0)
    assert page["faits"][0]["genre"] == "risque" and page["faits"][0]["fiabilite_du_texte"] == "donnee_non_fiable"


@pytest.mark.parametrize(
    ("surcharge", "champ"),
    [
        ({"texte": None}, "risque : texte seul (ni leçon, ni attendus, ni signataire)"),
        ({"lecon_id": "lecon-" + "a" * 24}, "risque : texte seul (ni leçon, ni attendus, ni signataire)"),
        ({"attendus": [{"metric_id": "m8_taux_acceptation_pct", "sens": "hausse"}]},
         "risque : texte seul (ni leçon, ni attendus, ni signataire)"),
        ({"decide_role": "nathan_owner"}, "risque : texte seul (ni leçon, ni attendus, ni signataire)"),
        ({"concordance": "CONCORDE"}, "risque : texte seul (ni leçon, ni attendus, ni signataire)"),
        ({"statut": "declaree_par_la_direction"}, "genre/statut"),
        ({"statut": "validee_par_la_direction"}, "genre/statut"),
    ],
)
def test_un_risque_hors_de_sa_forme_est_refuse(surcharge, champ):
    with pytest.raises(strategique.ChampRefuse) as exc:
        strategique.extraire(_charge_risque(**surcharge))
    assert exc.value.detail == champ


def test_un_statut_de_risque_sur_un_autre_genre_est_refuse():
    with pytest.raises(strategique.ChampRefuse) as exc:
        strategique.extraire(_charge(statut="signale_par_le_radar"))
    assert exc.value.detail == "genre/statut"


def test_le_refus_ne_recopie_jamais_la_valeur_fautive():
    valeur = "jean.tremblay@example.test"
    charge = _charge()
    charge["decision_id"] = valeur
    with pytest.raises(strategique.ChampRefuse) as exc:
        strategique.extraire(charge)
    assert valeur not in str(exc.value) and valeur not in repr(exc.value.verdict())


def test_memoriser_est_idempotent_et_un_refus_n_ecrit_rien():
    cible = registre.Registre()
    premier, verdict = strategique.memoriser(_charge(1), cible)
    assert verdict is None and premier["deja_memorise"] is False
    rejoue, _ = strategique.memoriser(copy.deepcopy(_charge(1)), cible)
    assert rejoue["deja_memorise"] is True and len(cible.lire()) == 1
    invalide = _charge(2)
    invalide["genre"] = "inconnu"
    resultat, verdict = strategique.memoriser(invalide, cible)
    assert resultat is None and verdict["code"] == strategique.REJ_STRATEGIQUE_CHAMP_INVALIDE and len(cible.lire()) == 1
    assert cible.valider_chaine() == (True, "")


def test_lister_filtre_par_decision_et_rend_le_texte_comme_donnee_non_fiable():
    cible = registre.Registre()
    strategique.memoriser(_charge(1), cible)
    strategique.memoriser(_charge(2, genre="resultat_observe"), cible)
    strategique.memoriser(_charge(3, decision_id="dem-fictive-2"), cible)
    page = strategique.lister(cible, 2, 0)
    assert page["total"] == 3 and len(page["faits"]) == 2 and page["suivant"] == 2
    assert all(f["fiabilite_du_texte"] == "donnee_non_fiable" for f in page["faits"])
    assert page["confidentialite"] == "FINANCIAL" and "n'établit aucune cause" in page["regle"]
    seule = strategique.lister(cible, 8, 0, decision_id="dem-fictive-1")
    assert seule["total"] == 2 and {f["genre"] for f in seule["faits"]} == {"decision", "resultat_observe"}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _livrer(*charges):
    for charge in charges:
        evenements.publier("m9.fait_strategique", "m09-strategic-intelligence", charge,
            evenement_id=charge["evenement_id"])
    evenements.repartir({"m10-memoire": charger_departements()["m10-memoire"]}, maintenant="2026-10-30T21:00:00-04:00")


def _faits():
    return stockage.maillons("m10-memoire", "faits_strategiques")


def test_le_bus_livre_chaque_fait_une_seule_fois_dans_son_propre_registre(base_durable):
    _livrer(_charge(1))
    _livrer(_charge(1))
    assert len(_faits()) == 1 and _faits()[0]["producteur"] == "m09-strategic-intelligence"
    _livrer(_charge(2, genre="resultat_observe"), _charge(3, genre="lecon"))
    assert len(_faits()) == 3
    for autre in ("evenements", "affaires", "faits_analytiques"):
        assert not [m for m in stockage.maillons("m10-memoire", autre) if m.get("type_entree") == "fait_strategique"]


def test_le_catalogue_du_socle_refuse_avant_m10_une_charge_avec_un_champ_de_trop(base_durable):
    charge = _charge(1)
    charge["nom_du_client"] = "Jean"
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("m9.fait_strategique", "m09-strategic-intelligence", charge,
            evenement_id=charge["evenement_id"])
    charge = _charge(2)
    charge["statut"] = "appliquee"
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("m9.fait_strategique", "m09-strategic-intelligence", charge,
            evenement_id=charge["evenement_id"])


def test_la_lecture_admin_pagine_filtre_et_refuse_les_arguments_invalides(base_durable):
    _livrer(_charge(1), _charge(2, genre="resultat_observe"))
    lecture = outils.lire_faits_strategiques(limite=1, decalage=0)
    assert lecture["total"] == 2 and len(lecture["faits"]) == 1 and lecture["suivant"] == 1
    assert outils.lire_faits_strategiques(decision_id="autre")["total"] == 0
    for args in ({"limite": 0}, {"limite": 9}, {"limite": "1"}, {"decalage": -1}):
        assert outils.lire_faits_strategiques(**args)["verdict"]["code"] == "REJ-STRATEGIQUE-PAGINATION-INVALIDE"
    for decision in ("", "x" * 129, 12):
        verdict = outils.lire_faits_strategiques(decision_id=decision)["verdict"]
        assert verdict["code"] == "REJ-STRATEGIQUE-DECISION-INVALIDE"


def test_l_outil_de_lecture_est_n0_ferme_aux_appareils_et_le_consommateur_est_declare():
    outil = next(o for o in outils.outils() if o.nom == "m10_lire_faits_strategiques")
    assert outil.niveau_effectif.value == "N0" and outil.roles_appareil == frozenset()
    assert outils.consommateurs()["m9.fait_strategique"] is outils._recevoir_faits_strategiques
