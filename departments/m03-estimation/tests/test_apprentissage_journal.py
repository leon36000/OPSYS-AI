"""Cycle de vie des versions d'apprentissage (journal pur, liste en mémoire) : candidate, activation auto/humaine,
version périmée, retour arrière en une opération, altération détectée. Données FICTIVES, horloge injectée."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import apprentissage_durees as ad  # noqa: E402
from m3_estimation import apprentissage_journal as aj  # noqa: E402

FICTIF = True
T0 = "2026-09-01T12:00:00Z"
COHORTE = {"type_service": "gouttieres", "unite_quantite": "pi_lin"}
POL = "a" * 64


def rapport(decision="auto_applicable", appris="34.2857", baseline="30.0000", n=12, **plus):
    base = {
        "cohorte": dict(COHORTE), "taux_baseline": baseline, "taux_appris": appris, "facteur": "1.1429",
        "intervalle": {"bas": "33.9000", "haut": "34.6000", "niveau": "0.90"}, "n_chantiers": n,
        "n_observations": n, "decision": decision, "raisons": ["x"], "derive": {"detectee": False},
        "regime_depuis_utc": None, "observations_sha256": "b" * 64, "exclues": {},
    }
    base.update(plus)
    return base


def inscrire(journal, **plus):
    r = aj.enregistrer_calcul(journal, rapport(**plus), politique_sha256=POL, maintenant_utc=T0, mode="supervise")
    assert r["statut"] in ("inscrite", "existante"), r
    return r["version"]


def test_calcul_idempotent_et_identite_independante_de_l_horloge():
    j = []
    v1 = inscrire(j)
    r2 = aj.enregistrer_calcul(j, rapport(), politique_sha256=POL, maintenant_utc="2026-09-02T00:00:00Z", mode="ombre")
    assert r2["statut"] == "existante" and r2["version"]["version_id"] == v1["version_id"] and len(j) == 1
    assert inscrire(j, appris="35.0000")["version_id"] != v1["version_id"] and len(j) == 2


def test_activation_auto_seulement_si_auto_applicable_et_autorise_et_sans_personne():
    j = []
    v = inscrire(j)
    assert aj.activer(j, v["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0,
                      auto_autorise=False)["raisons"] == ["auto_non_autorise_dans_ce_mode"]
    assert aj.activer(j, v["version_id"], mode_activation="auto", approbateur="p-1", maintenant_utc=T0,
                      auto_autorise=True)["raisons"] == ["approbateur_interdit_en_auto"]
    gros = inscrire(j, decision="approbation_requise", appris="45.0000")
    assert aj.activer(j, gros["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0,
                      auto_autorise=True)["raisons"] == ["decision_non_auto_applicable"]
    assert len(j) == 2  # rien d'écrit par les refus
    ok = aj.activer(j, v["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0, auto_autorise=True)
    assert ok["accepte"] is True and ok["deja_active"] is False
    again = aj.activer(j, v["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0,
                       auto_autorise=True)
    assert again["accepte"] and again["deja_active"] is True and len(j) == 3
    actif, raison = aj.version_active(j, **COHORTE)
    assert raison is None and actif["taux_applique"] == "34.2857" and actif["mode_activation"] == "auto"


@pytest.mark.parametrize("decision", ["insuffisante", "stable", "refusee_hors_bornes"])
def test_aucune_activation_pour_une_decision_non_activable_meme_par_un_humain(decision):
    j = []
    v = inscrire(j, decision=decision)
    r = aj.activer(j, v["version_id"], mode_activation="humain", approbateur="p-1", maintenant_utc=T0,
                   auto_autorise=True)
    assert r == {"accepte": False, "raisons": ["decision_non_activable"]}


def test_activation_humaine_exige_une_personne_nommee():
    j = []
    v = inscrire(j, decision="approbation_requise")
    for personne in (None, "", "  ", "x" * 200):
        assert aj.activer(j, v["version_id"], mode_activation="humain", approbateur=personne, maintenant_utc=T0,
                          auto_autorise=False)["raisons"] == ["approbateur_humain_requis"]
    ok = aj.activer(j, v["version_id"], mode_activation="humain", approbateur="proprio-fictif", maintenant_utc=T0,
                    auto_autorise=False)
    assert ok["accepte"] and aj.version_active(j, **COHORTE)[0]["approbateur"] == "proprio-fictif"


def test_candidate_perimee_ne_s_active_pas():
    j = []
    v1 = inscrire(j)
    v1b = inscrire(j, appris="35.5000")   # calculée alors qu'aucune version n'était en vigueur
    assert aj.activer(j, v1["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0,
                      auto_autorise=True)["accepte"]
    assert aj.activer(j, v1b["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0,
                      auto_autorise=True)["raisons"] == ["version_perimee"]
    assert aj.activer(j, "f" * 64, mode_activation="auto", approbateur=None, maintenant_utc=T0,
                      auto_autorise=True)["raisons"] == ["version_inconnue"]
    assert aj.activer(j, "pas-un-hash", mode_activation="auto", approbateur=None, maintenant_utc=T0,
                      auto_autorise=True)["raisons"] == ["version_inconnue"]
    assert aj.activer(j, v1["version_id"], mode_activation="magique", approbateur=None, maintenant_utc=T0,
                      auto_autorise=True)["raisons"] == ["mode_activation_invalide"]


def test_chaine_de_versions_et_retour_arriere_en_une_operation_restaure_la_precedente():
    j = []
    v1 = inscrire(j)
    aj.activer(j, v1["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0, auto_autorise=True)
    v2 = inscrire(j, appris="36.0000")
    assert v2["parent_version_id"] == v1["version_id"]
    aj.activer(j, v2["version_id"], mode_activation="humain", approbateur="p-1", maintenant_utc=T0, auto_autorise=False)
    assert aj.version_active(j, **COHORTE)[0]["taux_applique"] == "36.0000"
    refus = aj.retirer(j, COHORTE, version_attendue=v1["version_id"], par="p-1", raison="erreur", maintenant_utc=T0)
    assert refus["raisons"] == ["version_en_vigueur_differente"]
    r = aj.retirer(j, COHORTE, version_attendue=v2["version_id"], par="p-1", raison="chiffre douteux",
                   maintenant_utc=T0)
    assert r["accepte"] and r["version_retablie"] == v1["version_id"]
    assert aj.version_active(j, **COHORTE)[0]["taux_applique"] == "34.2857"
    r2 = aj.retirer(j, COHORTE, version_attendue=v1["version_id"], par="p-1", raison="retour au barème",
                    maintenant_utc=T0)
    assert r2["accepte"] and r2["version_retablie"] is None
    assert aj.version_active(j, **COHORTE) == (None, None)
    assert aj.retirer(j, COHORTE, version_attendue=v1["version_id"], par="p-1", raison="encore",
                      maintenant_utc=T0)["raisons"] == ["aucune_version_en_vigueur"]
    # Le journal n'a rien effacé : 2 calculs, 2 activations, 2 retraits.
    assert [m["type_entree"] for m in j] == ["version_calculee", "version_activee", "version_calculee",
                                            "version_activee", "version_retiree", "version_retiree"]


def test_retrait_exige_une_personne_et_une_raison():
    j = []
    v = inscrire(j)
    aj.activer(j, v["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0, auto_autorise=True)
    for par, raison in ((None, "x"), ("p-1", ""), ("p-1", "   "), ("p-1", "r" * 301)):
        assert aj.retirer(j, COHORTE, version_attendue=v["version_id"], par=par, raison=raison,
                          maintenant_utc=T0)["raisons"] == ["personne_et_raison_requises"]


def test_journal_altere_est_refuse_en_entier():
    j = []
    v = inscrire(j)
    aj.activer(j, v["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0, auto_autorise=True)
    for mutation in (
        lambda m: m[0]["charge"].__setitem__("taux_applique", "99.0000"),
        lambda m: m[1]["charge"].__setitem__("approbateur", "intrus"),
        lambda m: m[1].__setitem__("hash_precedent", "0" * 64),
        lambda m: m.reverse(),
        lambda m: m[1].__setitem__("type_entree", "version_retiree"),
        lambda m: m[0].__setitem__("rang", 5),
        lambda m: m[0].__setitem__("extra", 1),
        lambda m: m[1]["charge"].__setitem__("active_le", "2030-01-01T00:00:00Z"),   # forme valide, hachage rompu
        lambda m: m[0]["charge"].__setitem__("decision", "auto_applicable_quand_meme"),
    ):
        copie = copy.deepcopy(j)
        mutation(copie)
        assert aj.evenements(copie)[0] is None
        assert aj.version_active(copie, **COHORTE)[0] is None
        assert aj.enregistrer_calcul(copie, rapport(), politique_sha256=POL, maintenant_utc=T0,
                                     mode="x")["statut"] == "refuse"


def test_cohortes_independantes():
    j = []
    v = inscrire(j)
    aj.activer(j, v["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0, auto_autorise=True)
    autre = {"type_service": "revetement", "unite_quantite": "pi_lin"}
    assert aj.version_active(j, **autre) == (None, None)
    assert aj.retirer(j, autre, version_attendue=v["version_id"], par="p", raison="x",
                      maintenant_utc=T0)["raisons"] == ["aucune_version_en_vigueur"]


def test_complexite_declaree_dans_l_echelle_seulement_et_sans_exposer_le_chantier():
    j = []
    echelle = ["standard", "difficile"]
    ok = aj.declarer_complexite(j, chantier_id="CHANTIER-FICTIF-1", complexite="difficile", par="p-1",
                                maintenant_utc=T0, echelle=echelle)
    assert ok["accepte"] and "CHANTIER-FICTIF-1" not in repr(j)
    assert aj.declarer_complexite(j, chantier_id="CHANTIER-FICTIF-1", complexite="difficile", par="p-1",
                                  maintenant_utc=T0, echelle=echelle)["deja_declaree"] is True
    assert aj.declarer_complexite(j, chantier_id="C", complexite="extreme", par="p-1", maintenant_utc=T0,
                                  echelle=echelle)["raisons"] == ["complexite_hors_echelle"]
    assert aj.declarer_complexite(j, chantier_id="", complexite="standard", par="p", maintenant_utc=T0,
                                  echelle=echelle)["raisons"] == ["chantier_id_invalide"]
    assert aj.declarer_complexite(j, chantier_id="C", complexite="standard", par="", maintenant_utc=T0,
                                  echelle=echelle)["raisons"] == ["declarant_requis"]
    aj.declarer_complexite(j, chantier_id="CHANTIER-FICTIF-1", complexite="standard", par="p-2", maintenant_utc=T0,
                           echelle=echelle)
    assert aj.etat(j)[0]["complexites"][aj.empreinte_chantier_id("CHANTIER-FICTIF-1")] == "standard"


def test_instantane_de_performance_idempotent():
    j = []
    r = {"equipes": [{"equipe_ref": "eq-a", "type_service": "gouttieres", "evaluable": False}], "strates": []}
    assert aj.enregistrer_performance(j, r, politique_sha256=POL, maintenant_utc=T0)["statut"] == "inscrite"
    assert aj.enregistrer_performance(j, r, politique_sha256=POL, maintenant_utc=T0)["statut"] == "existante"
    assert aj.derniere_performance(j)[0]["equipes"] == r["equipes"]
    r2 = {**r, "strates": [{"type_service": "gouttieres"}]}
    assert aj.enregistrer_performance(j, r2, politique_sha256=POL, maintenant_utc=T0)["statut"] == "inscrite"
    assert len(j) == 2


def test_rapport_invalide_refuse_et_politique_de_decisions_connue():
    j = []
    assert aj.enregistrer_calcul(j, {"cohorte": {"x": 1}, "decision": "stable"}, politique_sha256=POL,
                                 maintenant_utc=T0, mode="ombre")["statut"] == "refuse"
    assert aj.enregistrer_calcul(j, rapport(decision="oui"), politique_sha256=POL, maintenant_utc=T0,
                                 mode="ombre")["statut"] == "refuse"
    assert set(ad.decisions()) == {"insuffisante", "stable", "refusee_hors_bornes", "approbation_requise",
                                 "auto_applicable"}


def test_apres_un_retrait_humain_la_machine_ne_remet_rien_en_vigueur_jusqu_a_une_approbation():
    j = []
    v1 = inscrire(j)
    aj.activer(j, v1["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0, auto_autorise=True)
    aj.retirer(j, COHORTE, version_attendue=v1["version_id"], par="p-1", raison="doute", maintenant_utc=T0)
    v2 = inscrire(j, appris="35.0000")
    gel = aj.activer(j, v2["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0,
                     auto_autorise=True)
    assert gel == {"accepte": False, "raisons": ["gel_apres_retrait_humain"]}
    assert aj.version_active(j, **COHORTE) == (None, None)
    # Une personne peut approuver ; le gel tombe ensuite pour les candidates suivantes.
    assert aj.activer(j, v2["version_id"], mode_activation="humain", approbateur="p-1", maintenant_utc=T0,
                      auto_autorise=False)["accepte"]
    v3 = inscrire(j, appris="35.2000")
    assert aj.activer(j, v3["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0,
                      auto_autorise=True)["accepte"]


def test_journal_reecrit_de_facon_coherente_avec_une_version_falsifiee_est_refuse():
    """Un faussaire qui recalcule toute la chaîne de hachage ne peut pas changer le contenu d'une version sans changer
    son identité (``version_id`` = empreinte du contenu)."""
    j = []
    v = inscrire(j)
    aj.activer(j, v["version_id"], mode_activation="auto", approbateur=None, maintenant_utc=T0, auto_autorise=True)
    forge = copy.deepcopy(j)
    forge[0]["charge"]["taux_applique"] = "99.0000"
    precedent = "0" * 64
    for rang, maillon in enumerate(forge):
        maillon["rang"], maillon["hash_precedent"] = rang, precedent
        corps = {k: maillon[k] for k in ("rang", "type_entree", "charge", "hash_precedent")}
        maillon["hash_maillon"] = ad.empreinte(corps)
        precedent = maillon["hash_maillon"]
    assert aj.evenements(forge) == (None, "journal_charge_invalide")
    assert aj.evenements(j)[1] is None
