"""Athéna : la boucle « décision → résultat mesuré → leçon → mémoire » sur les VRAIS départements (M8, M9, M10), la
vraie
file d'approbation, le vrai bus (fictif).

Prouve : la décision de la direction n'est écrite que sous SA demande approuvée par un propriétaire actif ; la base de
comparaison vient d'une capture réelle de M8 ; le résultat est comparé par le code ; la leçon reste PROPOSÉE jusqu'à la
validation humaine ; les entrées passent par le bus vers M10 (une fois chacune) ; rien n'est écrit dans la base de
connaissances.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m8_analytics import catalogue_mesures
from m9_strategic_intelligence import boucle_decisions as bd

from opsys import approbations, contexte, idempotence, identite, stockage
from opsys.contexte import IdentiteAppelante


def _charger_aide():
    spec = importlib.util.spec_from_file_location("m9_producteurs_b", Path(__file__).with_name("m9_producteurs_b.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


H = _charger_aide()
FICTIF = True
M9 = "m09-strategic-intelligence"
PROPRIO = IdentiteAppelante("proprio.fictif", "admin")
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
CONSIGNER = "m9_consigner_decision_direction"
VALIDER = "m9_valider_lecon_decision"
TAUX = "m8_taux_acceptation_pct"
DECISION_LE = "2026-10-05T10:00:00+00:00"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    H.installer_base(tmp_path, monkeypatch)
    H.declarer_m5(tmp_path, monkeypatch)
    mesures = catalogue_mesures.charger()["mesures"]
    configuration = {"fraicheur_mesures_s": {m["metric_id"]: 365 * 86400 for m in mesures}}
    H.declarer_configuration(H.m8_outils, tmp_path, monkeypatch, configuration, "m8-fenetres.yaml")
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, PROPRIO.personne, "Propriétaire fictif", "mot-de-passe-proprio-12345",
                                ["admin", "nathan_owner"])  # fmt: skip
    monkeypatch.setattr(approbations, "_maintenant", lambda: DECISION_LE)
    H.alimenter_m8()
    yield H.capacites(H.M8, H.M10)
    H.desinstaller_base()


def _lire(cap, nom, arguments, ident=ADMIN):
    with contexte.appele_par_appareil(ident):
        return cap.appeler(nom, arguments)


def _capturer_m8(cap, instant: str) -> None:
    reponse = H.capturer(cap, H.ADMIN, "m8.synthese_direction", {"maintenant": instant}, instant)
    assert reponse["ok"] is True and reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE", reponse


def _decider(cap, demande_id, cle, decision="approuver", ident=PROPRIO):
    with contexte.appele_par_appareil(ident):
        return cap.appeler(
            "m9_decider_demande_approbation", {"demande_id": demande_id, "decision": decision},
            idempotence.Meta(cle=cle, appareil="tel-fictif", horodatage_appareil="2026-10-05T06:00:00-04:00"),
        )  # fmt: skip


def _boucle():
    with stockage.transaction():
        return list(stockage.maillons(M9, "decisions_direction"))


ARGUMENTS_DECISION = {
    "enonce": "Relancer chaque semaine les devis restés sans réponse.",
    "attendus": [{"metric_id": TAUX, "sens": "hausse", "hypothese": "Plus de relances, plus d'acceptations."}],
}


def _consigner(cap):
    proposition = cap.appeler(CONSIGNER, ARGUMENTS_DECISION)
    assert proposition["statut"] == "en_attente_approbation", proposition
    return proposition["demande_id"]


def test_la_decision_n_est_ecrite_que_sous_sa_demande_approuvee_par_un_proprietaire_actif(monde):
    cap = monde
    _capturer_m8(cap, "2026-10-01T12:00:00-04:00")
    avant = _boucle()
    demande_id = _consigner(cap)
    assert _boucle() == avant, "une proposition n'écrit rien"
    refus = _decider(cap, demande_id, "cle-refus", decision="refuser")
    assert refus["ok"] is True and _boucle() == avant, "un refus n'écrit rien non plus"
    demande_id = _consigner(cap)
    reponse = _decider(cap, demande_id, "cle-ok")
    assert reponse["ok"] is True, reponse
    (decision,) = _boucle()
    assert decision["type"] == "DECISION" and decision["decision_id"] == demande_id
    assert decision["decide_role"] in ("admin", "nathan_owner") and decision["decide_le"] == DECISION_LE
    (attendu,) = decision["attendus"]
    assert attendu["base"]["presente"] is True and attendu["base"]["valeur"] == "50.00"
    assert attendu["base"]["fraicheur"] == "a_jour", "la base est une lecture réelle de M8, établie"
    assert bd.valider_chaine(_boucle()) == (True, "")


def test_un_appel_direct_sans_demande_approuvee_n_ecrit_rien_et_dit_pourquoi(monde):
    cap = monde
    with contexte.appele_par_appareil(ADMIN):
        reponse = cap.appeler(CONSIGNER, ARGUMENTS_DECISION)
    assert reponse.get("statut") == "en_attente_approbation" or reponse["ok"] is False
    assert _boucle() == []
    from m9_strategic_intelligence import adaptateur_boucle  # l'exécution directe de la fonction : aucun mandat

    outil = next(o for o in __import__("m9_strategic_intelligence.outils",
        fromlist=["x"]).outils() if o.nom == CONSIGNER)
    with stockage.transaction():
        verdict = outil.fonction(**ARGUMENTS_DECISION)
    assert verdict["accepte"] is False and verdict["verdict"]["code"] == "REJ-BOUCLE-APPROBATION"
    assert adaptateur_boucle.REGISTRE_BOUCLE == "decisions_direction" and _boucle() == []


def test_une_base_absente_est_dite_inconnue_et_aucune_mesure_ne_conclut(monde):
    cap = monde
    demande_id = _consigner(cap)  # aucune capture de M8 connue : la base ne se reconstitue pas
    assert _decider(cap, demande_id, "cle-sans-base")["ok"] is True
    (decision,) = _boucle()
    assert decision["capture_de_base"] is None and decision["attendus"][0]["base"] == {"presente": False}
    _capturer_m8(cap, "2026-10-10T12:00:00-04:00")
    mesure = _lire(cap, "m9_mesurer_resultat_decision", {"decision_id": demande_id,
        "maintenant": "2026-10-11T12:00:00-04:00"})
    assert mesure["ok"] is True
    etat = mesure["resultat"]["etat"]
    assert etat["resultat"]["concordance"] == "NON_MESURABLE"
    assert etat["resultat"]["observations"][0]["raison"] == "base_inconnue"
    assert etat["lecon"] is None, "non mesurable n'est pas une leçon"


def test_la_boucle_complete_jusqu_a_la_memoire_de_m10_sans_rien_appliquer(monde):
    cap = monde
    _capturer_m8(cap, "2026-10-01T12:00:00-04:00")
    demande_id = _consigner(cap)
    assert _decider(cap, demande_id, "cle-decision")["ok"] is True
    # Le monde change : trois devis de plus sont envoyés sans réponse, le taux d'acceptation BAISSE.
    H.devis_sans_reponse_en_plus(("DEVIS-X1", "DEVIS-X2", "DEVIS-X3"))
    _capturer_m8(cap, "2026-10-20T12:00:00-04:00")
    mesure = _lire(cap, "m9_mesurer_resultat_decision", {"decision_id": demande_id,
        "maintenant": "2026-10-21T12:00:00-04:00"})
    assert mesure["ok"] is True, mesure
    resultat = mesure["resultat"]
    assert resultat["entrees_ajoutees"] == ["RESULTAT", "LECON"]
    observation = resultat["etat"]["resultat"]["observations"][0]
    assert (observation["sens_attendu"], observation["sens_observe"], observation["concordance"]) == ("hausse",
        "baisse", "NE_CONCORDE_PAS")
    assert (observation["valeur_avant"], observation["valeur_apres"]) == ("50.00", "20.00")
    lecon = resultat["etat"]["lecon"]
    assert lecon["statut"] == "PROPOSEE_NON_VALIDEE" and "Aucune cause" in lecon["texte"]
    # Rejouer ne crée rien.
    rejeu = _lire(cap, "m9_mesurer_resultat_decision", {"decision_id": demande_id,
        "maintenant": "2026-10-21T12:00:00-04:00"})
    assert rejeu["resultat"]["rejeu"] is True and len(_boucle()) == 3
    # Publication vers M10 : une fois chaque entrée, et M10 la mémorise (FINANCIAL), pas dans la base de connaissances.
    publication = _lire(cap, "m9_publier_faits_strategiques", {"decision_id": demande_id})
    assert publication["ok"] is True and publication["resultat"]["nouveaux"] == 3
    assert publication["resultat"]["memoire_a_proposer"] == [], "une leçon non validée n'est jamais préparée"
    deuxieme = _lire(cap, "m9_publier_faits_strategiques", {"decision_id": demande_id})
    assert deuxieme["resultat"]["nouveaux"] == 0, "double soumission : le bus rejoue la première enveloppe"
    H.livrer((H.M10,))
    lus = _lire(cap, "m10_lire_faits_strategiques", {"decision_id": demande_id})
    assert lus["ok"] is True
    faits = lus["resultat"]
    assert faits["total"] == 3 and faits["confidentialite"] == "FINANCIAL"
    assert {f["genre"] for f in faits["faits"]} == {"decision", "resultat_observe", "lecon"}
    assert {f["statut"] for f in faits["faits"] if f["genre"] == "lecon"} == {"proposee_non_validee"}
    assert all(f["fiabilite_du_texte"] == "donnee_non_fiable" for f in faits["faits"])
    # La direction valide la leçon (geste N3 sous sa propre demande).
    proposition = cap.appeler(VALIDER, {"lecon_id": lecon["lecon_id"], "statut": "validee"})
    assert proposition["statut"] == "en_attente_approbation"
    assert _decider(cap, proposition["demande_id"], "cle-lecon")["ok"] is True
    assert bd.etat(_boucle(), demande_id)["etat"] == "lecon_validee"
    republication = _lire(cap, "m9_publier_faits_strategiques", {"decision_id": demande_id})["resultat"]
    assert republication["nouveaux"] == 1, "seule la validation est nouvelle"
    (source,) = republication["memoire_a_proposer"]
    assert source["outil"] == "m10_ingerer_source_connaissance" and source["arguments"]["cle"] == lecon["lecon_id"]
    assert republication["ecrit_dans_la_memoire_de_connaissances"] is False
    H.livrer((H.M10,))
    assert _lire(cap, "m10_lire_faits_strategiques", {"decision_id": demande_id})["resultat"]["total"] == 4
    with stockage.transaction():
        assert list(stockage.maillons("m10-memoire", "faits_strategiques"))
    assert json.dumps(republication).count("proprio.fictif") == 0, "aucun nom de personne ne voyage"


def test_la_validation_d_une_lecon_exige_sa_propre_demande_approuvee_et_une_lecon_existante(monde):
    cap = monde
    _capturer_m8(cap, "2026-10-01T12:00:00-04:00")
    demande_id = _consigner(cap)
    assert _decider(cap, demande_id, "cle-decision")["ok"] is True
    proposition = cap.appeler(VALIDER, {"lecon_id": "lecon-" + "0" * 24, "statut": "validee"})
    assert proposition["statut"] == "en_attente_approbation"
    reponse = _decider(cap, proposition["demande_id"], "cle-fantome")
    assert reponse["ok"] is True
    assert [e["type"] for e in _boucle()] == ["DECISION"], "une leçon inconnue n'est jamais validée"
    sans_mandat = next(o for o in __import__("m9_strategic_intelligence.outils",
        fromlist=["x"]).outils() if o.nom == VALIDER)
    with stockage.transaction():
        verdict = sans_mandat.fonction(lecon_id="lecon-x", statut="validee")
    assert verdict["verdict"]["code"] == "REJ-BOUCLE-APPROBATION"


def test_les_gestes_internes_exigent_l_admin_authentifie(monde):
    cap = monde
    for nom, arguments in (
        ("m9_mesurer_resultat_decision", {"decision_id": "x", "maintenant": "2026-10-21T12:00:00-04:00"}),
        ("m9_publier_faits_strategiques", {"decision_id": "x"}),
        ("m9_lire_boucle_decisions", {}),
    ):
        agent = cap.appeler(nom, arguments)
        assert agent["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in agent["details"], nom
        vendeur = _lire(cap, nom, arguments, IdentiteAppelante("vendeur.fictif", "seller", source="console"))
        assert vendeur["ok"] is False, nom
    inconnue = _lire(cap, "m9_mesurer_resultat_decision", {"decision_id": "x",
        "maintenant": "2026-10-21T12:00:00-04:00"})
    assert inconnue["ok"] is False and "REJ-BOUCLE-INCONNUE" in inconnue["details"]


def test_la_lecture_liste_les_decisions_et_aucun_outil_de_la_boucle_n_ouvre_un_droit_d_appareil(monde):
    cap = monde
    _capturer_m8(cap, "2026-10-01T12:00:00-04:00")
    demande_id = _consigner(cap)
    assert _decider(cap, demande_id, "cle-decision")["ok"] is True
    liste = _lire(cap, "m9_lire_boucle_decisions", {})["resultat"]
    assert liste["total"] == 1 and liste["decisions"][0]["etat"] == "declaree" and liste["prochain_depart"] is None
    detail = _lire(cap, "m9_lire_boucle_decisions", {"decision_id": demande_id})["resultat"]
    assert detail["etat"] == "declaree" and detail["attendus"] == [{"metric_id": TAUX, "sens": "hausse"}]
    import m9_strategic_intelligence.outils as m9_outils

    nouveaux = {CONSIGNER, VALIDER, "m9_mesurer_resultat_decision", "m9_lire_boucle_decisions",
        "m9_publier_faits_strategiques"}
    for outil in m9_outils.outils():
        if outil.nom in nouveaux:
            assert outil.roles_appareil == frozenset(), outil.nom
