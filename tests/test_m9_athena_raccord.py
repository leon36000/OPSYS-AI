"""Athéna (M9) → nouveaux producteurs : santé M8, pipeline et prévision M2, échéances et revue fiscale M5, faits M10.

Chaque lecture est capturée par le VRAI port privé (`lecteurs_m9`), sur de VRAIES données fictives produites par les
outils des départements (aide `m9_producteurs_b.py`). Ce fichier prouve : la capture et son contrat (la charge est
rejouée par `charges_athena` avant d'être conservée), le tableau de direction (statuts de certitude, « indéterminé »
plutôt qu'estimé), ce qui exige la direction, ce qui a changé depuis hier et le rafraîchissement par lot.

Tout est fictif (`FICTIF = True`) ; aucun appel réseau.
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import outils as m2_outils
from m8_analytics import catalogue_mesures, jeux_fictifs
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import certitude as ct
from m9_strategic_intelligence import tableau_direction

from opsys import contexte, stockage
from opsys.contexte import IdentiteAppelante
from opsys.outils import executer_atomique


def _charger_aide():
    spec = importlib.util.spec_from_file_location("m9_producteurs_b", Path(__file__).with_name("m9_producteurs_b.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


H = _charger_aide()
FICTIF = True
M2 = "m02-revenue-crm"
MAINTENANT = "2026-09-30T12:00:00-04:00"
BORNES = jeux_fictifs.BORNES_SANTE_FICTIVES
METRIQUES_SANTE = tuple(BORNES)


def recu(n: int = 0, jour: str = "2026-09-30") -> str:
    return f"{jour}T12:00:{n:02d}-04:00"


@pytest.fixture
def base(tmp_path, monkeypatch):
    H.installer_base(tmp_path, monkeypatch)
    H.declarer_m5(tmp_path, monkeypatch)
    m2_outils.utiliser_stockage_durable()  # l'état de M2 est global au processus : on ne dépend pas d'un autre test
    yield tmp_path
    m2_outils.reinitialiser_registre()
    H.desinstaller_base()


@pytest.fixture
def m8(base):
    H.alimenter_m8()
    return base


def _declarer_sante(base, monkeypatch, *, validee: bool, fenetre_s: int = 365 * 86400) -> None:
    """Bornes d'affaires et fenêtres de fraîcheur de la DIRECTION (fictives), comme la configuration de M8 les porte."""
    configuration = {
        "sante": {"bornes": dict(BORNES)},
        "fraicheur_mesures_s": {m["metric_id"]: fenetre_s for m in catalogue_mesures.charger()["mesures"]},
    }
    if validee:
        configuration["sante"]["ponderations_validees_par"] = "Nathan (fictif)"
    H.declarer_configuration(H.m8_outils, base, monkeypatch, configuration, "m8-sante.yaml")


def _capacites():
    return H.capacites(H.M8, H.M5, M2, H.M10, "m04-field-ops")


def _capturer(cap, lecture, arguments, n=1, jour="2026-09-30"):
    reponse = H.capturer(cap, H.ADMIN, lecture, arguments, recu(n, jour))
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["capture"]


def _chaine():
    return H.captures_stockees()


def _tableau(maintenant="2026-09-30T13:00:00-04:00", **kw):
    return tableau_direction.composer(_chaine(), maintenant=maintenant, **kw)


# ============================================================================================ M8 : santé et mesures
def test_la_synthese_m8_est_capturee_et_la_sante_est_indeterminee_sans_bornes(m8):
    cap = _capacites()
    capture = _capturer(cap, "m8.synthese_direction", {"maintenant": MAINTENANT})
    assert (capture["verdict"], capture["code"], capture["complete"]) == ("ACCEPTEE", None, True)
    assert capture["revisions"] and capture["instants_metier"]["declares"] is True
    sante = _tableau()["sections"]["sante"]
    assert sante["certitude"] == ct.INDETERMINE and sante["certain"] is False
    assert tableau_direction.PHRASE_SANTE_INDETERMINEE in sante["message"]
    assert any("Bornes" in texte for texte in sante["a_faire_par_la_direction"])
    assert all(ligne["valeur"] is None for ligne in sante["lignes"]), "aucun score de composante n'est inventé"
    assert "CPA" in sante["mention"]


def test_une_sante_determinee_sans_ponderations_validees_reste_un_essai(m8, monkeypatch, base):
    _declarer_sante(base, monkeypatch, validee=False)
    cap = _capacites()
    _capturer(cap, "m8.synthese_direction", {"maintenant": MAINTENANT})
    sante = _tableau()["sections"]["sante"]
    assert sante["certitude"] == ct.ESSAI and sante["certain"] is False
    assert "ESSAI" in sante["message"] and "non validées" in sante["message"]
    score = sante["lignes"][0]
    assert score["libelle"] == "Score de santé" and score["valeur"] is not None
    assert score["certain"] is False and score["adresse"].startswith("m8.synthese_direction#")


def test_une_sante_avec_ponderations_validees_par_la_direction_est_etablie(m8, monkeypatch, base):
    _declarer_sante(base, monkeypatch, validee=True)
    _capturer(_capacites(), "m8.synthese_direction", {"maintenant": MAINTENANT})
    sante = _tableau()["sections"]["sante"]
    assert sante["certitude"] == ct.ETABLI and sante["certain"] is True
    assert sante["ponderations_validees"] is True


def test_une_mesure_perimee_n_est_jamais_presentee_comme_a_jour(m8):
    cap = _capacites()
    _capturer(cap, "m8.synthese_direction", {"maintenant": "2026-10-28T12:00:00-04:00"}, jour="2026-10-28")
    capture = _chaine()[0]
    perimees = [m for m in capture["pages"][0]["resultat"]["mesures"] if m["fraicheur"] == "perime"]
    assert perimees, "le scénario fictif doit contenir des mesures périmées"
    classes = ct.classer_faits(capture)
    for rang, mesure in enumerate(capture["pages"][0]["resultat"]["mesures"]):
        if mesure["fraicheur"] == "perime":
            assert ct.statut_du_fait(classes, f"resultat.mesures[{rang}].valeur") == ct.PERIME
        if mesure["fraicheur"] == "manquant":
            assert ct.statut_du_fait(classes, f"resultat.mesures[{rang}].valeur") == ct.INDETERMINE


def test_une_charge_m8_alteree_est_refusee_et_conservee_comme_manque(m8):
    """Une synthèse qui prétend un score alors que le producteur dit « indéterminé » viole le contrat : refus
    conservé."""
    vraie = H.lire_par_le_port(H.M8, "m8_lire_synthese_direction", {"maintenant": MAINTENANT})
    assert vraie["ok"] is True and vraie["resultat"]["sante"]["statut"] == "indetermine"
    truquee = copy.deepcopy(vraie)
    truquee["resultat"]["sante"]["score"] = "88.00"
    lecture = cat.PAR_ID["m8.synthese_direction"]
    capture = cs.construire(
        lecture, {"maintenant": MAINTENANT}, [truquee], recu_a=recu(1), reference=MAINTENANT, index=0,
        hash_precedent=cs.HASH_INITIAL,
    )  # fmt: skip
    assert (capture["verdict"], capture["code"], capture["complete"]) == ("REFUSEE", "charge_invalide", False)
    assert "score" in capture["raison_incomplete"] and "88.00" not in capture["raison_incomplete"]


# ============================================================================================ M5 : échéances et revue
def test_le_calendrier_m5_reste_a_valider_par_le_cpa_et_les_taxes_partielles_ne_sont_pas_certaines(m8):
    cap = _capacites()
    _capturer(cap, "m5.calendrier_obligations", {"aujourd_hui": "2026-09-29"})
    section = _tableau()["sections"]["echeances"]
    assert section["certain"] is False and section["certitude"] in (ct.ESSAI, ct.INDETERMINE)
    taxes = [ligne for ligne in section["lignes"] if ligne.get("obligation") == "tps_tvq"]
    assert taxes, "les échéances TPS/TVQ doivent figurer"
    for ligne in taxes:
        assert ligne["certain"] is False
        if ligne["valeur"] is not None:
            assert "non confirmé" in ligne["note"] and ligne["certitude"] == ct.ESSAI
    assert section["validation_cpa"] and set(section["validation_cpa"].values()) == {"A_VALIDER"}
    assert "CPA" in section["mention"]
    attendues = _tableau()["declarations_attendues"]
    assert any(d["id"] == "calendrier-fiscal" for d in attendues)


def test_les_sources_fiscales_non_approuvees_sont_un_essai_jamais_etabli(base):
    cap = _capacites()
    _capturer(cap, "m5.statut_revue_fiscale", {"aujourd_hui": "2026-09-30"}, jour="2026-09-30")
    section = _tableau()["sections"]["sources_fiscales"]
    assert section["certitude"] == ct.ESSAI and section["certain"] is False
    assert "0/62" in section["message"]
    assert any(d["id"] == "sources-fiscales" for d in _tableau()["declarations_attendues"])


# ============================================================================================ M2 : pipeline et
# prévision
def _peupler_m2(nombre: int = 80) -> None:
    """Des leads fictifs étalés sur seize semaines, par les outils publics de M2 (comme ses propres tests)."""
    m2_outils.utiliser_stockage_durable()
    fin = dt.datetime.fromisoformat("2026-09-30T08:00:00-04:00")
    debut = fin - dt.timedelta(days=111)
    action = {"description": "Appeler le client", "echeance": "2026-10-05T09:00:00-04:00"}
    with stockage.transaction():
        for k in range(nombre):
            lead_id = f"p{k:03d}"
            ingere = debut + dt.timedelta(hours=33 * k)
            contrat = {
                "lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "type_travaux": "renovation_totale",
                "contact": {"nom": f"Client {lead_id}", "telephone": f"418-{k:03d}-{(k * 7) % 10000:04d}",
                            "courriel": f"{lead_id}@example.test"},
                "ville": "Québec", "urgence_declaree": k % 7 == 0, "canal": "telephone",
            }  # fmt: skip
            assert m2_outils.ingerer_lead(contrat, ingere.isoformat())["accepte"] is True
            if k % 4 == 3:
                continue
            qualifie = ingere + dt.timedelta(days=1)
            assert m2_outils.transitionner_statut(
                lead_id, "qualifie", qualifie.isoformat(), owner="vendeur.fictif", prochaine_action=action
            )["accepte"] is True  # fmt: skip
            if k % 3 == 0:
                converti = qualifie + dt.timedelta(days=3 + k % 9)
                assert m2_outils.transitionner_statut(
                    lead_id, "converti", converti.isoformat(), reference_devis_m3=f"devis-{lead_id}"
                )["accepte"] is True  # fmt: skip
            elif k % 5 == 0:
                perdu = qualifie + dt.timedelta(days=5 + k % 4)
                assert m2_outils.transitionner_statut(
                    lead_id, "perdu", perdu.isoformat(), motif="Budget insuffisant."
                )["accepte"] is True  # fmt: skip


def test_sans_historique_m2_refuse_de_prevoir_et_le_tableau_ne_met_aucun_chiffre(base):
    cap = _capacites()
    _capturer(cap, "m2.analyse_pipeline", {"horodatage": MAINTENANT})
    refus = H.capturer(
        cap, H.ADMIN, "m2.prevision_pipeline",
        {"horodatage": MAINTENANT, "serie": "leads_ingeres", "methode": "moyenne_mobile", "fenetre": 3, "horizon": 4},
        recu(2),
    )  # fmt: skip
    capture = refus["resultat"]["capture"]
    assert (capture["verdict"], capture["code"]) == ("REFUSEE", "REJ-PREV-ECHANTILLON-INSUFFISANT")
    tableau = _tableau()["sections"]
    assert tableau["previsions"]["certitude"] == ct.INDETERMINE and tableau["previsions"]["lignes"] == []
    assert "Rien n'est estimé" in tableau["previsions"]["message"]
    pipeline = tableau["pipeline"]
    taux = next(ligne for ligne in pipeline["lignes"] if ligne["libelle"].startswith("Taux de conversion"))
    assert taux["valeur"] is None and taux["certitude"] == ct.INDETERMINE and "échantillon insuffisant" in taux["note"]
    valeur = next(ligne for ligne in pipeline["lignes"] if ligne["libelle"].startswith("Valeur pondérée"))
    assert valeur["valeur"] is None and valeur["certitude"] == ct.INDETERMINE
    assert pipeline["certain"] is False


def test_avec_historique_la_prevision_m2_porte_toujours_son_intervalle_et_son_recu(base):
    _peupler_m2()
    cap = _capacites()
    args = {"horodatage": MAINTENANT, "serie": "leads_ingeres", "methode": "moyenne_mobile", "fenetre": 3, "horizon": 4}
    _capturer(cap, "m2.prevision_pipeline", args)
    _capturer(cap, "m2.analyse_pipeline", {"horodatage": MAINTENANT}, n=2)
    sections = _tableau()["sections"]
    prevision = sections["previsions"]
    assert prevision["certitude"] == ct.PREVISION and prevision["certain"] is False
    for ligne in prevision["lignes"]:
        intervalle = ligne["intervalle"]
        assert set(intervalle) == {"niveau", "bas", "haut", "adresses"} and ligne["certain"] is False
    assert prevision["recu"]["empreinte"] and prevision["recu"]["verification"] == "m2_rejouer_recu_commercial"
    taux = next(ligne for ligne in sections["pipeline"]["lignes"] if ligne["libelle"].startswith("Taux de conversion"))
    assert taux["valeur"] is not None and taux["certitude"] == ct.ETABLI
    pondere = next(ligne for ligne in sections["pipeline"]["lignes"] if ligne["libelle"].startswith("Valeur pondérée"))
    assert pondere["valeur"] is None, "aucune valeur déclarée sur les leads : indéterminée, jamais estimée"


# ============================================================================================ M10 : faits analytiques
def test_les_faits_analytiques_m10_sont_captures_avec_leurs_consolidations(m8):
    cap = _capacites()
    outil = next(o for o in H.m8_outils.outils() if o.nom == "m8_publier_faits_consolides")
    reponse = executer_atomique(outil, {"maintenant": MAINTENANT})  # outil d'agent : aucune identité d'appareil
    assert reponse["ok"] is True, reponse
    H.livrer((H.M10,))
    capture = _capturer(cap, "m10.faits_analytiques", {})
    assert capture["complete"] is True and len(capture["revisions"]) == 1
    page = _chaine()[0]["pages"][0]["resultat"]
    assert page["total"] == 1 and page["confidentialite"] == "FINANCIAL"


# ============================================================================================ rafraîchissement par lot
def test_le_rafraichissement_par_lot_capture_le_plan_et_conserve_les_refus(m8):
    cap = _capacites()
    with contexte.appele_par_appareil(H.ADMIN):
        reponse = cap.appeler("m9_rafraichir_lectures_direction", {"maintenant": MAINTENANT})
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    lectures = {ligne["lecture_id"]: ligne for ligne in resultat["lectures"]}
    assert lectures["m8.synthese_direction"]["verdict"] == "ACCEPTEE"
    assert lectures["m2.prevision_pipeline"]["code"] == "REJ-PREV-ECHANTILLON-INSUFFISANT"
    assert resultat["non_demandees"] == ["m4.capacite_equipe : debut_semaine non fourni"]
    ok, raison = cs.valider_chaine(_chaine())
    assert ok, raison
    assert len(_chaine()) == len(resultat["lectures"])


def test_le_rafraichissement_est_refuse_a_un_agent_et_a_un_non_admin(m8):
    cap = _capacites()
    refus = cap.appeler("m9_rafraichir_lectures_direction", {"maintenant": MAINTENANT})
    assert refus["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in refus["details"]
    with contexte.appele_par_appareil(IdentiteAppelante("vendeur.fictif", "seller", source="console")):
        refus = cap.appeler("m9_rafraichir_lectures_direction", {"maintenant": MAINTENANT})
    assert refus["ok"] is False and H.captures_stockees() == []


# ============================================================================================ tableau par l'outil
def test_le_tableau_par_l_outil_est_borne_et_ne_pretend_rien(m8):
    cap = _capacites()
    with contexte.appele_par_appareil(H.ADMIN):
        assert cap.appeler("m9_rafraichir_lectures_direction", {"maintenant": MAINTENANT})["ok"] is True
        sommaire = cap.appeler("m9_tableau_direction", {"maintenant": MAINTENANT})
    assert sommaire["ok"] is True, sommaire
    corps = sommaire["resultat"]
    ids = [s["id"] for s in corps["sections"]]
    assert ids == list(tableau_direction.SECTIONS)
    assert all(s["certain"] is (s["certitude"] == "ETABLI") for s in corps["sections"])
    with contexte.appele_par_appareil(H.ADMIN):
        detail = cap.appeler("m9_tableau_direction", {"maintenant": MAINTENANT, "section": "sante"})
    assert detail["ok"] is True and detail["resultat"]["section"]["id"] == "sante"
    with contexte.appele_par_appareil(H.ADMIN):
        inconnue = cap.appeler("m9_tableau_direction", {"maintenant": MAINTENANT, "section": "inexistante"})
    assert inconnue["ok"] is False


def test_les_lectures_non_capturees_sont_dites_non_lues_jamais_remplies(base):
    tableau = _tableau()
    for section in tableau["sections"].values():
        if section["id"] == "alertes_m8":
            continue
        assert section["certain"] is False
        assert section["lignes"] == [] or section["id"] == "chantiers"
    assert tableau["sections"]["sante"]["certitude"] == ct.ABSENT
    assert "non lue" in tableau["sections"]["sante"]["message"]


# ============================================================================================ ce qui exige la direction
def test_exige_la_direction_classe_les_vraies_demandes_en_attente_par_niveau_puis_par_age(m8, monkeypatch):
    from opsys import approbations

    cap = _capacites()
    instants = iter(("2026-09-25T09:00:00+00:00", "2026-09-27T09:00:00+00:00", "2026-09-29T09:00:00+00:00"))
    monkeypatch.setattr(approbations, "_maintenant", lambda: next(instants))
    attendus = [{"metric_id": "m8_taux_acceptation_pct", "sens": "hausse", "hypothese": "Plus de relances."}]
    ancienne_n3 = cap.appeler("m9_consigner_decision_direction", {"enonce": "Décision ancienne.", "attendus": attendus})
    n4 = cap.appeler("m5_clore_periode_comptable", {"periode": "2026-08", "horodatage": "2026-09-27T09:00:00-04:00"})
    recente_n3 = cap.appeler("m9_consigner_decision_direction", {"enonce": "Décision récente.", "attendus": attendus})
    for proposition in (ancienne_n3, n4, recente_n3):
        assert proposition["statut"] == "en_attente_approbation", proposition
    with contexte.appele_par_appareil(H.ADMIN):
        reponse = cap.appeler("m9_exige_la_direction", {"maintenant": "2026-09-30T09:00:00+00:00"})
    assert reponse["ok"] is True, reponse
    corps = reponse["resultat"]
    ordre = [e["id"] for e in corps["elements"]]
    assert ordre == [n4["demande_id"], ancienne_n3["demande_id"], recente_n3["demande_id"]]
    assert [e["niveau"] for e in corps["elements"]] == ["N4", "N3", "N3"]
    assert corps["par_niveau"]["N3"]["nombre"] == 2 and corps["par_niveau"]["N3"]["plus_ancien_texte"] == "5 j 0 h"
    assert corps["elements"][0]["raison"] == "N4 ; en attente depuis 3 j 0 h"
    assert corps["total"] == 3 and corps["prochain_depart"] is None
    assert "niveau le plus élevé d'abord" in corps["regle"]
    with contexte.appele_par_appareil(H.ADMIN):
        briefing = cap.appeler("m9_briefing_direction", {"maintenant": "2026-09-30T09:00:00+00:00"})
    premiers = briefing["resultat"]["exige_la_direction"]["premiers"]
    assert [p["id"] for p in premiers] == ordre
    assert briefing["resultat"]["briefing_du_matin"]["decisions_en_attente"] == 3


# ============================================================================================ recommandation gouvernée
def test_le_conseil_gouverne_verifie_un_vrai_recu_de_m5_et_refuse_un_recu_retouche(m8):
    from m5_financecore import moteur_calcul

    cap = _capacites()
    _capturer(cap, "m5.statut_revue_fiscale", {"aujourd_hui": "2026-09-30"})
    sortie, verdict = moteur_calcul.calculer_point_mort(
        {"frais_fixes": "120000", "prix_unitaire": "4500", "cout_variable_unitaire": "2900", "quantite_prevue": "100"}
    )
    assert verdict is None
    recu = sortie["recu"]
    quantite = recu["resultat"]["quantite_entiere"]
    adresse = next(a for a in _faits_athena() if a.endswith("base.parametres_renseignes"))
    reco = {
        "schema": "opsys.m9.recommandation/v1",
        "question": "Faut-il fixer un seuil de ventes avant d'acheter un camion ?",
        "domaines": ["financement"],
        "hypotheses": [],
        "chiffres": [
            {"id": "c1", "libelle": "Point mort en unités", "valeur": quantite, "unite": "unités",
             "source": {"genre": "recu_m5", "empreinte": recu["empreinte"], "chemin": "quantite_entiere"},
             "certitude": "ETABLI"},
            {"id": "c2", "libelle": "Valeurs fiscales renseignées", "valeur": _faits_athena()[adresse],
                "unite": "valeurs",
             "source": {"genre": "fait", "adresse": adresse}, "certitude": "ETABLI"},
        ],  # fmt: skip
        "options": [
            {"id": "o1", "titre": "Fixer le seuil", "description": "Exiger le point mort avant l'achat.",
             "chiffres": ["c1"], "risques": ["r1"]},
            {"id": "o2", "titre": "Attendre", "description": "Reporter l'achat.", "chiffres": ["c2"], "risques": []},
        ],  # fmt: skip
        "risques": [{"id": "r1", "enonce": "Le seuil dépend d'hypothèses de prix.", "refs": ["c1"]}],
        "donnees_manquantes": [],
        "recommandation": {"option_id": "o1", "texte": "Fixer le seuil : la décision reste à la direction.",
                           "abstention_raison": None},  # fmt: skip
        "statut": "PROPOSITION_NON_DECIDEE",
        "decision_prise_par_m9": False,
        "validation_requise": ["direction", "comptable_cpa"],
        "mention_professionnelle": "À valider auprès d'un comptable (CPA) / professionnel qualifié",
    }  # fmt: skip
    connaissance = "2026-09-30T13:00:00-04:00"

    def controler(reco_, recus):
        with contexte.appele_par_appareil(H.ADMIN):
            return cap.appeler(
                "m9_controler_recommandation", {"recommandation": reco_, "connaissance": connaissance, "recus": recus}
            )

    accepte = controler(reco, [recu])
    assert accepte["ok"] is True, accepte
    assert accepte["resultat"]["valide"] is True and accepte["resultat"]["recus_verifies"] == [recu["empreinte"]]
    assert accepte["resultat"]["decision_prise_par_m9"] is False
    retouche = copy.deepcopy(recu)
    retouche["resultat"]["quantite_entiere"] = "1"  # chiffre retouché : l'empreinte ne correspond plus
    refus = controler(reco, [retouche])
    assert refus["ok"] is False and "REJ-RECO-CHIFFRE-RECU" in refus["details"]
    sans_recu = controler(reco, [])
    assert sans_recu["ok"] is False and "REJ-RECO-CHIFFRE-RECU" in sans_recu["details"]
    estime = copy.deepcopy(reco)
    estime["chiffres"][0]["source"] = {"genre": "estimation"}
    assert "REJ-RECO-CHIFFRE-SANS-SOURCE" in controler(estime, [recu])["details"]
    en_clair = copy.deepcopy(reco)
    en_clair["recommandation"]["texte"] = "Fixer le seuil à 2 500 unités, la décision reste à la direction."
    assert "REJ-CONSEIL-CHIFFRE-LIBRE" in controler(en_clair, [recu])["details"]
    sans_mention = copy.deepcopy(reco)
    sans_mention["mention_professionnelle"] = None
    assert "REJ-RECO-MENTION" in controler(sans_mention, [recu])["details"]
    agent = cap.appeler("m9_controler_recommandation", {"recommandation": reco, "connaissance": connaissance})
    assert agent["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in agent["details"]


def _faits_athena():
    from m9_strategic_intelligence import dossier_strategique

    faits, _ = dossier_strategique.faits_citables(_chaine(), max_faits=10**6)
    return faits


# ============================================================================================ abus et refus d'identité
OUTILS_ATHENA_LECTURE = {
    "m9_briefing_direction": {"maintenant": MAINTENANT},
    "m9_tableau_direction": {"maintenant": MAINTENANT},
    "m9_exige_la_direction": {"maintenant": MAINTENANT},
    "m9_changements_depuis": {"maintenant": MAINTENANT},
    "m9_verifier_recu_changements": {"recu": {}},
    "m9_controler_recommandation": {"recommandation": {}, "connaissance": MAINTENANT},
    "m9_rafraichir_lectures_direction": {"maintenant": MAINTENANT},
}
IDENTITES_REFUSEES = {
    "agent_sans_identite": None,
    "vendeur": IdentiteAppelante("vendeur.fictif", "seller", source="console"),
    "employe": IdentiteAppelante("employe.fictif", "employee", source="console"),
    "admin_desactive": IdentiteAppelante("ancien.admin", "admin", source="console"),
    "personne_inconnue": IdentiteAppelante("inconnu.fictif", "admin", source="console"),
    "source_inconnue": IdentiteAppelante("admin.fictif", "admin", source="jeton-inconnu"),
    "role_usurpe": IdentiteAppelante("employe.fictif", "admin", source="console"),
}


@pytest.mark.parametrize("nom", sorted(OUTILS_ATHENA_LECTURE))
@pytest.mark.parametrize("qui", sorted(IDENTITES_REFUSEES))
def test_chaque_outil_d_athena_refuse_tout_ce_qui_n_est_pas_l_admin_authentifie(m8, nom, qui):
    cap = _capacites()
    avant = H.captures_stockees()
    identite_appelante = IDENTITES_REFUSEES[qui]
    if identite_appelante is None:
        reponse = cap.appeler(nom, OUTILS_ATHENA_LECTURE[nom])
    else:
        with contexte.appele_par_appareil(identite_appelante):
            reponse = cap.appeler(nom, OUTILS_ATHENA_LECTURE[nom])
    assert reponse["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in reponse["details"], reponse
    assert H.captures_stockees() == avant, "un refus d'identité n'écrit rien"


def test_une_chaine_de_captures_alteree_arrete_tous_les_outils_de_lecture(m8):
    from sqlalchemy import update

    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    cap = _capacites()
    with contexte.appele_par_appareil(H.ADMIN):
        assert cap.appeler("m9_rafraichir_lectures_direction", {"maintenant": MAINTENANT})["ok"] is True
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            REGISTRES.select().where((REGISTRES.c.registre == "captures_strategiques") & (REGISTRES.c.rang == 0))
        ).mappings().one()  # fmt: skip
        maillon = codec.decoder(ligne["maillon"])
        maillon["reponse_sha256"] = "00" * 32
        cnx.execute(
            update(REGISTRES).where(
                (REGISTRES.c.registre == "captures_strategiques") & (REGISTRES.c.rang == 0)
            ).values(maillon=codec.encoder(maillon))
        )  # fmt: skip
    for nom in ("m9_tableau_direction", "m9_briefing_direction", "m9_changements_depuis"):
        with contexte.appele_par_appareil(H.ADMIN):
            reponse = cap.appeler(nom, {"maintenant": "2026-09-30T13:00:00-04:00"})
        assert reponse["ok"] is False and "REJ-CAPTURE-CHAINE-INVALIDE" in reponse["details"], nom


def test_le_tableau_reste_borne_meme_avec_des_centaines_d_alertes_et_dit_ce_qui_n_est_pas_affiche(m8):
    """Quota : la sortie reste sous la limite du socle et ne coupe rien en silence (pagination ou refus nommé)."""
    cap = _capacites()
    with contexte.appele_par_appareil(H.ADMIN):
        assert cap.appeler("m9_rafraichir_lectures_direction", {"maintenant": MAINTENANT})["ok"] is True
    for numero in range(150):
        with stockage.transaction():
            stockage.maillons("m09-strategic-intelligence", "alertes_m8").append({
                "evenement_id": f"e{numero:04d}", "metric_id": "m8_ecart_duree_pct",
                    "type_alerte": "MESURE-SEUIL-FRANCHI",
                "quoi": "seuil franchi " + "x" * 200, "a_qui": "direction", "pourquoi": "fictif", "preuve": {},
                "source": "m8", "horodatage_reference": "2026-09-30T08:00:00-04:00",
            })  # fmt: skip
    with contexte.appele_par_appareil(H.ADMIN):
        section = cap.appeler("m9_tableau_direction", {"maintenant": "2026-09-30T13:00:00-04:00",
            "section": "alertes_m8"})
        sommaire = cap.appeler("m9_tableau_direction", {"maintenant": "2026-09-30T13:00:00-04:00"})
    assert section["ok"] is True and sommaire["ok"] is True, (section, sommaire)
    corps = section["resultat"]
    assert corps["section"]["lignes"][0]["valeur"] == "150", "le compte est exact"
    assert len(json.dumps(section, ensure_ascii=False)) < 6000
    assert len(json.dumps(sommaire, ensure_ascii=False)) < 6000
    assert corps["total_lignes"] == 7, "deux comptes et cinq alertes nommées au plus"
    assert corps["prochain_depart"] is None
