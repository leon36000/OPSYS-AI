"""Auditeur de citations textuelles FICTIVES : source T1 approuvée et SQL natifs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from m9_strategic_intelligence import contrats, rapport_strategique
from sqlalchemy import event

from opsys import contexte, identite, stockage
from opsys.stockage.schema import REGISTRES


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

base = _charger("_audit_affirmations_fixtures", Path(__file__).with_name("test_rapport_activite_periode.py"))
installation = base.installation
NOM = "m9_auditer_affirmations_conseil"
QUESTION = "Quelles valeurs fictives sont fidèlement citées, sans vérité financière attestée ?"
MODULES = ["M5-fictif"]


def _preparer(installation):
    cap = base.w.b._capacites(installation)
    base.o._ajouter_t1(cap, {"module_source": "M5-fictif", "horodatage": "2026-10-19T00:00:00Z",
                            "valeurs": {"chantier_fictif": "100.00"}}, "source-audit-fictive-approuvee")
    with contexte.appele_par_appareil(base.w.b.PROPRIO):
        reponse = cap.appeler("m9_preparer_dossier_direction", {"question": QUESTION, "modules_attendus": MODULES})
    assert reponse["ok"] is True, reponse
    dossier = reponse["resultat"]
    fait = dossier["faits_selectionnes"]["M5-fictif"]
    assert fait["valeurs"]["chantier_fictif"] == "100.00" and dossier["preuves"] == [fait]
    claim = {"id": "citation-fictive-exacte", "nature": "observation_source", "reference": {
        "module_source": "M5-fictif", "index": fait["index"], "hash_maillon": fait["hash_maillon"],
        "cle": "chantier_fictif"}, "valeur": "100.00"}
    return cap, dossier, claim


def _appeler(cap, dossier, affirmations, **arguments):
    with contexte.appele_par_appareil(base.w.b.PROPRIO):
        return cap.appeler(NOM, {"question": QUESTION, "modules_attendus": MODULES,
            "dossier_attendu": dossier["dossier_id"], "affirmations": affirmations} | arguments)


def test_auditeur_requis_apres_source_native100_et_rapport15cles_avec1000(installation):
    cap, dossier, claim = _preparer(installation)
    structure = {cle: [] for cle in contrats.CHAMPS_RAPPORT_STRATEGIQUE}
    structure["preuves"] = {"valeur_financiere_fictive_inventee": "1000.00"}
    assert rapport_strategique.valider_rapport_strategique(structure) == (True, None)
    assert NOM in cap.index, "M9_AUDITEUR_ABSENT_APRES_SOURCE100_ET_RAPPORT15CLES1000"
    avant = base.w.b._tables()
    exact = _appeler(cap, dossier, [claim])
    assert exact["ok"] is True and exact["resultat"]["dossier"] == dossier, exact
    assert "SOURCE_CONCORDANTE" in str(exact["resultat"]["audit"])
    faux = claim | {"id": "citation-fictive-inventee", "valeur": "1000.00"}
    refuse = _appeler(cap, dossier, [claim, faux])
    assert refuse["ok"] is False and "resultat" not in refuse, refuse
    assert base.w.b._tables() == avant



def _pur(dossier, affirmations, **args):
    from importlib import import_module
    module = import_module("m9_strategic_intelligence.audit_affirmations")
    return module.auditer_affirmations(dossier, args.pop("dossier_attendu", dossier["dossier_id"]),
                                     affirmations, budget_caracteres=args.pop("budget_caracteres", 5900), **args)


def _dossier(cap, **args):
    return base.w.b._lire(cap, "m9_preparer_dossier_direction",
                         {"question": QUESTION, "modules_attendus": MODULES} | args)


def _refus(cap, dossier, affirmations, **args):
    avant = base.w.b._tables()
    reponse = _appeler(cap, dossier, affirmations, **args)
    assert reponse["ok"] is False and "resultat" not in reponse and "tronque" not in reponse, reponse
    assert base.w.b._tables() == avant
    return reponse


def _ajouter(cap, valeurs, instant="2026-10-20T00:00:00Z", cle="audit-source-suivante"):
    base.o._ajouter_t1(cap, {"module_source": "M5-fictif", "horodatage": instant,
                           "valeurs": valeurs}, cle)


@pytest.mark.parametrize("valeur", ["", " 100.00 "])
def test_texte_original_exact_vide_ou_espaces_sans_normalisation(installation, valeur):
    cap, _, _ = _preparer(installation)
    _ajouter(cap, {"chantier_fictif": valeur})
    dossier = _dossier(cap)
    fait = dossier["faits_selectionnes"]["M5-fictif"]
    claim = {"id": "texte-original-fictif", "nature": "observation_source", "reference": {
        "module_source": fait["module_source"], "index": fait["index"],
        "hash_maillon": fait["hash_maillon"], "cle": "chantier_fictif"}, "valeur": valeur}
    avant = base.w.b._tables()
    reponse = _appeler(cap, dossier, [claim])
    assert reponse["ok"] is True and reponse["resultat"]["dossier"] == dossier, reponse
    assert "SOURCE_CONCORDANTE" in json.dumps(reponse["resultat"]["audit"])
    assert base.w.b._tables() == avant


@pytest.mark.parametrize("valeur", [100, True, None])
def test_valeurs_non_textuelles_refusees_sans_coercition(installation, valeur):
    cap, dossier, claim = _preparer(installation)
    mauvais = claim | {"valeur": valeur}
    _refus(cap, dossier, [mauvais])
    with pytest.raises(ValueError):
        _pur(dossier, [mauvais])


@pytest.mark.parametrize("cause", [
    "index_bool", "index_absent", "module_absent", "hash_faux", "cle_absente",
    "reference_extra", "affirmation_extra", "reference_absente",
])
def test_references_et_cles_exactes_refus_du_lot_entier(installation, cause):
    cap, dossier, claim = _preparer(installation)
    mauvaise = deepcopy(claim)
    mauvaise["id"] = "deuxieme-citation-invalide"
    reference = mauvaise["reference"]
    if cause == "index_bool":
        reference["index"] = False  # index réel 0 : False == 0 ne suffit pas
    elif cause == "index_absent":
        reference["index"] = 999
    elif cause == "module_absent":
        reference["module_source"] = "M5-autre-fictif"
    elif cause == "hash_faux":
        reference["hash_maillon"] = "f" * 64
    elif cause == "cle_absente":
        reference["cle"] = "valeur_inexistante"
    elif cause == "reference_extra":
        reference["jsonpath"] = "$.valeurs.chantier_fictif"
    elif cause == "affirmation_extra":
        mauvaise["enonce"] = "SECRET_FICTIF : cette valeur prouve une marge réelle"
    else:
        del mauvaise["reference"]
    _refus(cap, dossier, [claim, mauvaise])
    with pytest.raises(ValueError):
        _pur(dossier, [claim, mauvaise])


@pytest.mark.parametrize("valeur", ["100.0"])
def test_egalite_textuelle_stricte_pas_egalite_numerique(installation, valeur):
    cap, dossier, claim = _preparer(installation)
    _refus(cap, dossier, [claim | {"valeur": valeur}])


@pytest.mark.parametrize("cause", ["identifiants_dupliques", "lot_vide", "dix_sept", "hypothese_extra"])
def test_schema_du_lot_et_hypothese_sans_source(installation, cause):
    cap, dossier, claim = _preparer(installation)
    if cause == "identifiants_dupliques":
        affirmations = [claim, deepcopy(claim)]
    elif cause == "lot_vide":
        affirmations = []
    elif cause == "dix_sept":
        affirmations = [claim | {"id": str(i)} for i in range(17)]
    else:
        affirmations = [claim, {"id": "hypothese-fictive", "nature": "hypothese",
            "enonce": "Hypothèse fictive non vérifiée", "reference": claim["reference"]}]
    _refus(cap, dossier, affirmations)
    with pytest.raises(ValueError):
        _pur(dossier, affirmations)


def test_hypothese_declaree_ne_devient_pas_observation_et_manques_visibles(installation):
    cap, _, _ = _preparer(installation)
    modules = MODULES + ["M6-fictif-manquant"]
    dossier = _dossier(cap, modules_attendus=modules)
    hypothese = {"id": "hypothese-fictive", "nature": "hypothese",
                 "enonce": "Hypothèse non vérifiée : une équipe pourrait être disponible."}
    avant = base.w.b._tables()
    reponse = _appeler(cap, dossier, [hypothese], modules_attendus=modules)
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["dossier"] == dossier and dossier["modules_manquants"] == [modules[-1]]
    texte = json.dumps(resultat["audit"], ensure_ascii=False)
    assert "HYPOTHESE_DECLAREE" in texte and "SOURCE_CONCORDANTE" not in texte
    assert hypothese["enonce"] in texte and base.w.b._tables() == avant


@pytest.mark.parametrize("selectionnee", [True, False])
def test_contradiction_refuse_variante_selectionnee_ou_autre(installation, selectionnee):
    cap, _, _ = _preparer(installation)
    _ajouter(cap, {"chantier_fictif": "1000.00"}, instant="2026-10-18T20:00:00-04:00")
    dossier = _dossier(cap)
    assert len(dossier["contradictions"]) == 1 and len(dossier["preuves"]) == 2
    selection = dossier["faits_selectionnes"]["M5-fictif"]
    variante = next(p for p in dossier["preuves"] if (p == selection) == selectionnee)
    claim = {"id": "variante-fictive", "nature": "observation_source", "reference": {
        "module_source": variante["module_source"], "index": variante["index"],
        "hash_maillon": variante["hash_maillon"], "cle": "chantier_fictif"},
        "valeur": variante["valeurs"]["chantier_fictif"]}
    reponse = _refus(cap, dossier, [claim])
    if selectionnee:
        assert "REJ-AUDIT-SOURCE-CONTRADICTOIRE" in json.dumps(reponse)
    hypothese = {"id": "hypothese-sur-conflit", "nature": "hypothese", "enonce": "Conflit non arbitré fictif."}
    admis = _appeler(cap, dossier, [hypothese])
    assert admis["ok"] is True and admis["resultat"]["dossier"]["contradictions"] == dossier["contradictions"]


@pytest.mark.parametrize("cause", ["source_selectionnee", "question", "modules"])
def test_dossier_attendu_perime_avant_admission(installation, cause):
    cap, dossier, claim = _preparer(installation)
    args = {}
    if cause == "source_selectionnee":
        _ajouter(cap, {"chantier_fictif": "1000.00"})
    elif cause == "question":
        args["question"] = "Autre question fictive ?"
    else:
        args["modules_attendus"] = MODULES + ["M6-fictif-manquant"]
    reponse = _refus(cap, dossier, [claim], **args)
    assert "REJ-AUDIT-DOSSIER-PERIME" in json.dumps(reponse)


def test_append_ancien_non_selectionne_ne_perime_pas_dossier(installation):
    cap, dossier, claim = _preparer(installation)
    _ajouter(cap, {"chantier_fictif": "ancienne observation fictive"}, instant="2026-10-01T00:00:00Z")
    assert _dossier(cap) == dossier
    avant = base.w.b._tables()
    reponse = _appeler(cap, dossier, [claim])
    assert reponse["ok"] is True and reponse["resultat"]["dossier"] == dossier, reponse
    assert base.w.b._tables() == avant


def test_capture_unique_source_changeante_apres_capture(installation):
    _, dossier, claim = _preparer(installation)
    from m9_strategic_intelligence import outils

    from opsys.outils import executer_atomique
    class SourceChangeante:
        lectures = 0
        lignes = deepcopy(dossier["preuves"])
        def lire(self):
            self.lectures += 1
            assert self.lectures == 1, "La source serveur ne doit être capturée qu'une fois"
            capture = deepcopy(self.lignes)
            self.lignes[0]["valeurs"]["chantier_fictif"] = "1000.00"
            return capture
    source = SourceChangeante()
    outil = next(o for o in outils.outils(registre_cible=source, alertes_cible=[]) if o.nom == NOM)
    with stockage.transaction(), contexte.appele_par_appareil(base.w.b.PROPRIO):
        avant = base.w.b._tables()
        reponse = executer_atomique(outil, {"question": QUESTION, "modules_attendus": MODULES,
            "dossier_attendu": dossier["dossier_id"], "affirmations": [claim]})
        assert reponse["ok"] is True and reponse["resultat"]["dossier"] == dossier, reponse
        assert source.lectures == 1 and base.w.b._tables() == avant


@pytest.mark.parametrize("cause", ["employee", "admin_revoque", "inactif"])
def test_role_sql_courant_avant_toute_source(installation, monkeypatch, cause):
    cap, dossier, claim = _preparer(installation)
    with stockage.transaction() as cnx:
        if cause == "admin_revoque":
            identite.retirer_role(cnx, base.w.b.PROPRIO.personne, "admin")
        elif cause == "inactif":
            identite.activer(cnx, base.w.b.PROPRIO.personne, False)
    appelante = (contexte.IdentiteAppelante(personne=base.w.b.RESPONSABLE, role="employee")
                 if cause == "employee" else base.w.b.PROPRIO)
    def interdit(*args, **kwargs):
        pytest.fail("Lecture de source avant contrôle du rôle SQL courant")
    monkeypatch.setattr(stockage, "maillons", interdit)
    avant = base.w.b._tables()
    def sql_interdit(cnx, curseur, instruction, parametres, ctx, plusieurs):
        if instruction.lstrip().lower().startswith("select") and REGISTRES.name.lower() in instruction.lower():
            pytest.fail("SQL des snapshots avant garde admin")
    moteur = stockage.moteur()
    event.listen(moteur, "before_cursor_execute", sql_interdit)
    try:
        with contexte.appele_par_appareil(appelante):
            reponse = cap.appeler(NOM, {"question": QUESTION, "modules_attendus": MODULES,
                "dossier_attendu": dossier["dossier_id"], "affirmations": [claim]})
    finally:
        event.remove(moteur, "before_cursor_execute", sql_interdit)
    assert reponse["ok"] is False and "resultat" not in reponse
    assert base.w.b._tables() == avant


@pytest.mark.parametrize("cause", ["sortie_entiere", "entree_entiere"])
def test_budget_json_entier_sans_troncature_ni_admission_partielle(installation, cause):
    cap, dossier, claim = _preparer(installation)
    if cause == "sortie_entiere":
        reference = _pur(dossier, [claim])
        budget = len(json.dumps(reference, ensure_ascii=False, allow_nan=False)) - 1
        with pytest.raises(ValueError, match="REJ-AUDIT-"):
            _pur(dossier, [claim], budget_caracteres=budget)
    else:
        hypotheses = [{"id": str(i), "nature": "hypothese", "enonce": "Hypothèse fictive " + "x" * 500}
                      for i in range(16)]
        assert len(json.dumps(hypotheses, ensure_ascii=False)) > 5900
        _refus(cap, dossier, hypotheses)


def test_copies_profondes_empreinte_audit_et_absence_de_validation_metier(installation):
    _, dossier, claim = _preparer(installation)
    avant = deepcopy((dossier, claim))
    resultat = _pur(dossier, [claim])
    assert (dossier, claim) == avant and resultat["dossier"] == dossier
    audit = resultat["audit"]
    assert audit["type"] == "AUDIT_AFFIRMATIONS_CONSEIL"
    assert audit["dossier_id"] == dossier["dossier_id"] and audit["etat_id"] == dossier["etat_id"]
    assert audit["admissible_a_la_revue"] is True
    assert audit["validation_metier"] == "NON_PROUVEE" and audit["actualite_metier"] == "NON_EVALUEE"
    assert audit["decision_validee"] is audit["conseil_execute"] is audit["modele_execute"] is False
    assert audit["limites"]
    contenu = {k: v for k, v in audit.items() if k != "audit_id"}
    assert audit["audit_id"] == hashlib.sha256(json.dumps(
        contenu, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert len(json.dumps(resultat, ensure_ascii=False, allow_nan=False)) <= 5900
    resultat["dossier"]["preuves"][0]["valeurs"]["chantier_fictif"] = "1000.00"
    audit["affirmations"][0]["id"] = "id-modifie-fictif"
    assert (dossier, claim) == avant


def test_cle_litterale_avec_point_sans_interpretation_jsonpath(installation):
    cap, _, _ = _preparer(installation)
    _ajouter(cap, {"chantier.fictif": "100.00", "chantier_fictif": "200.00"})
    dossier = _dossier(cap)
    fait = dossier["faits_selectionnes"]["M5-fictif"]
    claim = {"id": "cle-litterale-fictive", "nature": "observation_source", "reference": {
        "module_source": "M5-fictif", "index": fait["index"], "hash_maillon": fait["hash_maillon"],
        "cle": "chantier.fictif"}, "valeur": "100.00"}
    reponse = _appeler(cap, dossier, [claim])
    assert reponse["ok"] is True, reponse
    _refus(cap, dossier, [claim | {"valeur": "200.00"}])



def test_source_pure_non_textuelle_refusee_meme_avec_dossier_et_hashes_coherents():
    # Oracle pur négatif seulement : cette valeur booléenne n'est PAS une ingestion native admise.
    from m9_strategic_intelligence.dossier_direction import construire_dossier
    from m9_strategic_intelligence.registre import RegistreSnapshots
    source = RegistreSnapshots()
    source.ajouter({"module_source": "M5-fictif", "horodatage": "2026-10-19T00:00:00Z",
                   "valeurs": {"chantier_fictif": True}})
    assert source.valider_chaine() == (True, "")
    dossier = construire_dossier(source, QUESTION, MODULES, budget_caracteres=5900)
    fait = dossier["faits_selectionnes"]["M5-fictif"]
    claim = {"id": "coercition-source-interdite", "nature": "observation_source", "reference": {
        "module_source": "M5-fictif", "index": fait["index"], "hash_maillon": fait["hash_maillon"],
        "cle": "chantier_fictif"}, "valeur": "True"}
    avant = deepcopy((dossier, claim))
    with pytest.raises(ValueError):
        _pur(dossier, [claim])
    assert (dossier, claim) == avant
