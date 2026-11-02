"""M9-C1 et M9-C2 de bout en bout : un MOIS fictif aux symptômes variés, les VRAIS outils de M9, M1, M2, M4, M5, M7 et
M8, le
vrai bus, une horloge injectée (rien ne tourne seul : chaque capture, chaque radar, chaque escalade est un geste daté).

Le mois (vendredi 17 h de l'Est, T1 à T4) :

* T1 — tout est sain : le radar ne sort AUCUN risque et dit ce qu'il n'évalue pas (M3 et M6 ne sont pas branchés ici) ;
* T2 — des plaintes (dont une de sécurité) : exactement deux risques, avec raison, mesure, seuil et source ;
* T3 — les plaintes sont LEVÉES (le signal a disparu de la lecture plus récente) ; une équipe est surchargée, un lead
chaud
  n'est pas contacté, la trésorerie de M5 est en alerte, un report dure depuis six jours, la baisse de leads se voit à
  l'intervalle de M2, et la lecture de M7 n'a pas été rafraîchie depuis quatorze jours ;
* T4 — plaintes en rafale (critique), cash libre négatif (critique), report de treize jours (critique), dépense
marketing
  au-dessus du plafond : l'escalade crée un avis interne, une tâche et une trace de mémoire par risque critique, et rien
  d'externe.

Puis les scénarios chiffrés par les moteurs des propriétaires (Monte-Carlo de M5, projection de capacité de M4,
intervalle
de M2), leurs reçus rejoués, et le « non chiffré » quand un moteur manque ou refuse. Données fictives uniquement.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from opsys import contexte, stockage
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS


def _charger(nom: str):
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(f"{nom}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


W = _charger("m9_radar_monde")
B, A = W.B, W.A
FICTIF = True
TZ = dt.timezone(dt.timedelta(hours=-5))
PREVISION = {
    "serie": "leads_ingeres",
    "methode": "moyenne_mobile",
    "horizon": 1,
    "niveau": 80,
    "fenetre": 3,
    "graine": 5,
}
OPTIONS_PIPELINE = {k: v for k, v in PREVISION.items() if k != "graine"}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = W.Monde(tmp_path, monkeypatch)
    yield m
    m.fermer()


# ----------------------------------------------------------------------------------------------------------- aides
def _radar(m, connaissance: str, **plus) -> dict:
    """Le radar COMPLET par le vrai outil : toutes les pages (la sortie d'un outil est bornée à 6 000 caractères)."""
    risques, regles, depart, entete = [], [], 0, None
    while depart is not None:
        reponse = m.appeler_m9("m9_radar_risques", {"connaissance": connaissance, "depart": depart, **plus})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
        page = reponse["resultat"]
        entete = entete or page
        risques += page["risques"]
        regles += page["regles_non_evaluees"]
        depart = page["prochain_depart"]
    assert len(risques) == entete["total_risques"] and len(regles) == entete["total_regles_non_evaluees"]
    return {**entete, "risques": risques, "regles_non_evaluees": regles}


def _vue(radar: dict, *, statut: str = "ACTIF") -> dict[tuple[str, str], tuple[str, str]]:
    return {(r["regle"], r["sujet"]): (r["gravite"], r["domaine"]) for r in radar["risques"] if r["statut"] == statut}


def _semaine(m, k: int, *, avec_m7: bool = False) -> str:
    """Les lectures de la semaine ``k`` (reçues à l'instant T[k], une seconde chacune) ; rend l'instant du radar."""
    instant, jour = W.T[k], W.JOUR[k]
    m.constater_cash_libre(jour)
    lectures = [
        ("m1.plaintes_structurees", {"date_reference": jour, "jours": 7}),
        ("m4.capacite_equipe", {"debut_semaine": W.SEMAINE_CEDULE}),
        ("m5.prevision_tresorerie", {"aujourd_hui": jour}),
        ("m8.vue_executive", {"aujourd_hui": jour}),
        ("m2.sla_filet", {"horodatage": instant}),
        ("m2.prevision_pipeline", {"horodatage": instant, **PREVISION}),
        ("m4.retards_incidents", {"horodatage_reference": instant}),
    ]
    for rang, (lecture, arguments) in enumerate(lectures):
        m.capturer(lecture, arguments, instant.replace("21:00:00", f"21:00:{rang + 1:02d}"))
    return instant.replace("21:00:00", "22:00:00")


def _etat_externe() -> dict:
    """Tout ce qui pourrait sortir de l'entreprise ou demander à une personne : approbations et évènements sortants."""
    with stockage.transaction() as cnx:
        return {
            "approbations": len(cnx.execute(select(APPROBATIONS)).fetchall()),
            "evenements": {
                ligne.evenement_id: ligne.type_evenement
                for ligne in cnx.execute(select(EVENEMENTS_SORTANTS)).fetchall()
            },
        }


# ============================================================================================ le mois, semaine après se
def _mois(m, *, seuils: dict | None = None) -> dict:
    """Monte le mois (symptômes de T1 à T4) et rend les radars de chaque semaine (les tests, eux, assertent)."""
    sortie: dict = {}
    m.vocabulaire_plaintes()
    m.cedule()
    m.mouvements()
    m.factures()
    m.historique_de_leads([3, 4, 2, 5, 3, 4, 3, 2, 4, 5, 3, 4, 3], W.T[1])
    m.depenses("900.00", "300.00", "2026-09", "2026-09-30", "2026-10-02T12:00:00Z")
    m.demande_normale(W.DEBUT_VEILLE, "+15145550101")
    m.declarer_seuils(seuils if seuils is not None else {**W.SEUILS_DIRECTION, "leads_plancher_par_semaine": 3})
    # T1 : tout est sain
    instant = _semaine(m, 1)
    m.capturer(
        "m7.depenses_marketing", {"debut": "2026-09-01", "fin": "2026-09-30"}, W.T[1].replace("21:00:00", "21:00:09")
    )
    sortie["r1"] = _radar(m, instant)
    # T2 : des plaintes (dont une de sécurité)
    m.plaintes(3, jour=dt.datetime(2026, 11, 3, 9, tzinfo=TZ), sensible=True)
    m.historique_de_leads([1], W.T[2], "sem")  # un lead dans le bloc de sept jours qui finit à T2
    sortie["r2"] = _radar(m, _semaine(m, 2))
    # T3 : surcharge, SLA, alerte de trésorerie, report durable, baisse de leads
    m.profil_etendu(fin_min_eq_a=720)  # l'équipe eq-a ne déclare plus que 4 h de quart : la même cédule la surcharge
    m.seuil_m5("16000.00")  # M5 relève SON seuil d'alerte de trésorerie
    m.lead("urgent-1", "2026-11-12T10:00:00Z", urgent=True)
    m.historique_de_leads([1], W.T[3], "x3")  # deux leads dans le bloc de sept jours qui finit à T3
    sortie["intervention"] = A.m4_planifier(m.m4, "L-M9-R-A", techniciens=("marc.fictif",))
    m.report(sortie["intervention"], "2026-11-07T10:00:00Z")
    sortie["r3"] = _radar(m, _semaine(m, 3))
    # T4 : la rafale de plaintes, le déficit, le retard durable, la dépense marketing
    m.plaintes(5, jour=dt.datetime(2026, 11, 16, 9, tzinfo=TZ))
    m.declarer_m5_obligations("30000.00")
    m.depenses("1500.00", "400.00", "2026-10", "2026-10-31", "2026-11-01T12:00:00Z")
    sortie["instant4"] = _semaine(m, 4)
    m.capturer(
        "m7.depenses_marketing", {"debut": "2026-10-01", "fin": "2026-10-31"}, W.T[4].replace("21:00:00", "21:00:09")
    )
    sortie["r4"] = _radar(m, sortie["instant4"])
    return sortie


def test_un_mois_fictif_le_radar_sort_exactement_les_risques_attendus_et_aucun_sur_les_indicateurs_sains(monde):
    mois = _mois(monde)
    intervention = mois["intervention"]

    # ------------------------------------------------------------------------------------------------ T1 : tout est sai
    r1 = mois["r1"]
    assert r1["risques"] == [], "les indicateurs sains ne sortent AUCUN risque"
    assert set(r1["regles_evaluees"]) >= {
        "plaintes_afflux",
        "plaintes_sensibles_ouvertes",
        "capacite_surcharge_cedule",
        "depense_marketing_plafond",
        "leads_sous_plancher",
        "chantier_retard_prolonge",
        "cash_libre_deficit",
        "cash_libre_sous_plancher",
        "filet_sla_violation",
        "donnees_perimees",
        "cash_alerte_seuil",
    }
    absentes = {n["regle"] for n in r1["regles_non_evaluees"] if n["raison"] == "ABSENTE"}
    assert absentes == {
        "materiaux_reservation_incomplete",
        "qualite_ecart_marge_negatif",
        "estimation_ecart_main_doeuvre",
        "materiaux_variance_critique",
        "materiaux_disponible_negatif",
    }, "M3, M6, M8 chantier : non lus, dit"
    amont = {n["regle"] for n in r1["regles_non_evaluees"] if n["raison"] == "NON_EVALUEE_PAR_LE_PROPRIETAIRE"}
    assert amont == {
        f"filet_sla_violation:{r}"
        for r in ("photos_non_recues", "soumission_non_relancee", "plainte_non_escaladee", "tache_en_retard")
    }
    assert r1["seuils_declares"]["m9.plaintes_seuil_nombre"] == "3" and r1["perime_origine"] == "reglage"

    # ------------------------------------------------------------------------------- T2 : des plaintes (dont sécurité)
    r2 = mois["r2"]
    assert {(regle, v) for (regle, _), v in _vue(r2).items()} == {
        ("plaintes_afflux", ("ELEVE", "plaintes")),
        ("plaintes_sensibles_ouvertes", ("ELEVE", "reputation")),
    }
    afflux = next(r for r in r2["risques"] if r["regle"] == "plaintes_afflux")
    assert afflux["mesure"] == {"valeur": "4", "unite": "plaintes", "periode_jours": 7}
    assert afflux["seuil"] == {
        "reglage": "m9.plaintes_seuil_nombre",
        "valeur": "3",
        "unite": "plaintes",
        "critique_si_au_moins": "4.5",
    }
    assert afflux["source"]["lecture_id"] == "m1.plaintes_structurees" and afflux["origine_etablie"] is False
    assert afflux["raison"] and afflux["preuves"][0].startswith("m1.plaintes_structurees#")

    # ------------------------------------------------------------------------------------- T3 : surcharge, SLA, alerte…
    r3 = mois["r3"]
    actifs3 = _vue(r3)
    assert actifs3 == {  # exactement ces risques, ni plus ni moins
        ("capacite_surcharge_cedule", "equipe:eq-a"): ("ELEVE", "capacite"),
        ("filet_sla_violation", "sla:lead_chaud_non_contacte"): ("ELEVE", "ventes"),
        ("cash_alerte_seuil", "tresorerie"): ("MOYEN", "cash"),
        ("chantier_retard_prolonge", f"retard:{intervention}"): ("ELEVE", "chantiers"),
        ("capacite_report_en_cours", f"report:{intervention}"): ("FAIBLE", "capacite"),
        ("donnees_perimees", "lecture:m7.depenses_marketing"): ("MOYEN", "donnees"),
    }
    assert {regle for regle, _ in _vue(r3, statut="LEVE")} == {"plaintes_afflux", "plaintes_sensibles_ouvertes"}, (
        "le signal a disparu de la lecture plus récente : LEVÉ, pas oublié"
    )
    surcharge = next(r for r in r3["risques"] if r["regle"] == "capacite_surcharge_cedule")
    assert surcharge["mesure"] == {
        "heures_planifiees": "3.50",
        "heures_disponibles": "4.00",
        "unite": "heures_declarees",
    }
    assert surcharge["seuil"]["valeur"] == "60" and surcharge["seuil"]["reglage"] == "m9.capacite_utilisation_seuil_pct"

    # ----------------------------------------------------------------------------- T4 : la rafale, le déficit, le retar
    r4 = mois["r4"]
    actifs4 = _vue(r4)
    assert actifs4 == {
        ("plaintes_afflux", "plaintes_periode"): ("CRITIQUE", "plaintes"),
        ("cash_libre_deficit", "cash_libre"): ("CRITIQUE", "cash"),
        ("chantier_retard_prolonge", f"retard:{intervention}"): ("CRITIQUE", "chantiers"),
        ("depense_marketing_plafond", "depense_marketing_periode"): ("ELEVE", "marketing"),
        ("cash_alerte_seuil", "tresorerie"): ("ELEVE", "cash"),  # déficit annoncé par M5
        ("capacite_surcharge_cedule", "equipe:eq-a"): ("ELEVE", "capacite"),
        ("filet_sla_violation", "sla:lead_chaud_non_contacte"): ("ELEVE", "ventes"),
        ("capacite_report_en_cours", f"report:{intervention}"): ("FAIBLE", "capacite"),
        ("leads_sous_plancher", "periode:1"): ("MOYEN", "ventes"),
    }
    baisse = next(r for r in r4["risques"] if r["regle"] == "leads_sous_plancher")
    assert (baisse["domaine"], baisse["gravite"], baisse["seuil"]["valeur"]) == ("ventes", "MOYEN", "3")
    assert float(baisse["mesure"]["borne_haute"]) < 3 and baisse["mesure"]["niveau_intervalle"] == "déclaré par M2"
    deficit = next(r for r in r4["risques"] if r["regle"] == "cash_libre_deficit")
    assert deficit["mesure"]["valeur"].startswith("-") and deficit["seuil"] is None, "fait structurel de M5, sans seuil"
    assert ("donnees_perimees", "lecture:m7.depenses_marketing") not in actifs4, "la lecture de M7 est fraîche"
    assert all(r["domaine"] == r["domaine"] and r["origine_etablie"] is False and r["raison"] for r in r4["risques"])


def test_un_risque_critique_cree_un_avis_une_tache_et_une_memoire_et_rien_d_externe(monde):
    m = monde
    mois = _mois(m)
    instant4 = mois["instant4"]
    avant = _etat_externe()
    reponse = m.appeler_m9("m9_escalader_risques_critiques", {"connaissance": instant4})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    res = reponse["resultat"]
    assert res["critiques_trouves"] == 3 and res["externe"] is False and len(res["escalades"]) == 3
    assert {e["regle"] for e in res["escalades"]} == {
        "plaintes_afflux",
        "cash_libre_deficit",
        "chantier_retard_prolonge",
    }
    assert all(e["avis_nouveau"] and e["tache_nouvelle"] and e["memoire"]["nouveau"] for e in res["escalades"])
    assert res["canaux"] == [
        "avis interne (registre avis_risques)",
        "tâche interne (plan M9)",
        "mémoire M10 (m9.fait_strategique)",
    ]
    # -- l'avis interne
    avis = m.appeler_m9("m9_lire_avis_risques", {})["resultat"]
    assert avis["total"] == 3 and all(a["externe"] is False and a["canal"] == "interne" for a in avis["avis"])
    assert all(a["gravite"] == "CRITIQUE" and "Aucune cause établie" in a["texte"] for a in avis["avis"])
    assert all("aucun message externe" in a["texte"] for a in avis["avis"])
    # -- la tâche : un plan M9 pour la direction, échéance le jour de l'escalade, résultat clé manuel
    plans = m.appeler_m9("m9_lire_plans", {"connaissance": instant4, "jour": W.JOUR[4]})["resultat"]
    taches = {e["tache_id"] for e in res["escalades"]}
    ouverts = [p for p in plans["plans"] if p["plan_id"] in taches]
    assert len(ouverts) == 3 and all(p["porteur"].startswith("direction") for p in ouverts)
    assert all(p["echeance"] == W.JOUR[4] for p in ouverts)
    # -- la mémoire : M10 range le fait stratégique (genre risque), jamais dans un contexte
    B.livrer((B.M10,))
    cap10 = B.capacites(B.M10)
    with contexte.appele_par_appareil(W.ADMIN):
        faits = cap10.appeler("m10_lire_faits_strategiques", {"limite": 8})
    assert faits["ok"] is True, faits
    liste = [f for f in faits["resultat"]["faits"] if f["genre"] == "risque"]
    assert len(liste) == 3 and all(f["statut"] == "signale_par_le_radar" for f in liste)
    assert faits["resultat"]["confidentialite"] == "FINANCIAL"
    assert all(f["fiabilite_du_texte"] == "donnee_non_fiable" and f["concordance"] is None for f in liste)
    # -- rien d'externe : aucune approbation créée ; les seuls évènements nés de l'escalade sont les faits de mémoire
    apres = _etat_externe()
    assert apres["approbations"] == avant["approbations"]
    nouveaux = {i: t for i, t in apres["evenements"].items() if i not in avant["evenements"]}
    assert sorted(nouveaux.values()) == ["m9.fait_strategique"] * 3
    # -- rejouer le même jour n'ajoute rien
    rejeu = m.appeler_m9("m9_escalader_risques_critiques", {"connaissance": instant4})["resultat"]
    assert [(e["avis_nouveau"], e["tache_nouvelle"], e["memoire"]["nouveau"]) for e in rejeu["escalades"]] == [
        (False, False, False)
    ] * 3
    assert m.appeler_m9("m9_lire_avis_risques", {})["resultat"]["total"] == 3
    assert _etat_externe() == apres
    # -- le lendemain, le risque dure : un nouvel avis par risque, mais la tâche ouverte n'est pas doublée
    lendemain = m.appeler_m9("m9_escalader_risques_critiques", {"connaissance": "2026-11-21T14:00:00Z"})["resultat"]
    assert len(lendemain["escalades"]) == 3 and all(
        e["avis_nouveau"] and not e["tache_nouvelle"] for e in lendemain["escalades"]
    )
    assert {e["tache_id"] for e in lendemain["escalades"]} == taches
    assert m.appeler_m9("m9_lire_avis_risques", {})["resultat"]["total"] == 6


def test_l_escalade_n_est_pas_un_geste_d_agent_ni_d_appareil_et_ne_voit_que_des_critiques_actifs(monde):
    m = monde
    mois = _mois(monde)
    avant = _etat_externe()
    for identite in (
        None,
        contexte.IdentiteAppelante("vendeur.fictif", "seller", source="console"),
        contexte.IdentiteAppelante("admin.fictif", "admin", source="appareil"),
    ):
        reponse = m.appeler_m9("m9_escalader_risques_critiques", {"connaissance": mois["instant4"]}, identite)
        assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False, reponse
    assert _etat_externe() == avant
    # à T3, aucun risque n'est critique : rien n'est escaladé
    vide = m.appeler_m9("m9_escalader_risques_critiques", {"connaissance": W.T[3].replace("21:00:00", "22:00:00")})
    assert vide["resultat"]["critiques_trouves"] == 0 and vide["resultat"]["escalades"] == []


# ===================================================================================== sans seuils déclarés : on le dit
def test_seuils_non_declares_les_regles_ne_sont_pas_evaluees_et_disent_quoi_declarer_jamais_aucun_risque(monde):
    m = monde
    mois = _mois(m, seuils={})  # la direction n'a encore rien déclaré
    r4 = mois["r4"]
    cles = {
        "m9.plaintes_seuil_nombre",
        "m9.capacite_utilisation_seuil_pct",
        "m9.depense_marketing_plafond_cad",
        "m9.leads_plancher_par_semaine",
        "m9.retard_chantier_jours",
        "m9.donnees_perimees_jours",
        "m9.cash_libre_plancher_cad",
        "m9.multiple_seuil_critique",
    }
    assert cles <= set(r4["reglages_a_declarer"]) and r4["seuils_declares"] == {}
    non_evaluees = {n["regle"]: n for n in r4["regles_non_evaluees"]}
    for regle in (
        "plaintes_afflux",
        "capacite_surcharge_cedule",
        "depense_marketing_plafond",
        "leads_sous_plancher",
        "chantier_retard_prolonge",
        "cash_libre_sous_plancher",
        "donnees_perimees",
    ):
        assert non_evaluees[regle]["raison"] == "SEUIL_NON_DECLARE" and non_evaluees[regle]["a_declarer"], regle
    # ce qui n'exige AUCUN seuil de la direction reste évalué (faits structurels des propriétaires)
    actifs = _vue(r4)
    assert ("cash_libre_deficit", "cash_libre") in actifs and ("plaintes_afflux", "plaintes_periode") not in actifs
    assert not [
        r
        for r in r4["risques"]
        if r["regle"] in non_evaluees
        and r["regle"] not in ("filet_sla_violation",)
        and non_evaluees[r["regle"]]["raison"] == "SEUIL_NON_DECLARE"
    ]
    # sans multiple déclaré, rien n'est dit critique par dépassement : seul le fait structurel de M5 l'est
    assert {r["regle"] for r in r4["risques"] if r["gravite"] == "CRITIQUE"} == {"cash_libre_deficit"}
    assert r4["escalade"]["multiple_declare"] is None
    escalade = m.appeler_m9("m9_escalader_risques_critiques", {"connaissance": mois["instant4"]})["resultat"]
    assert [e["regle"] for e in escalade["escalades"]] == ["cash_libre_deficit"]
