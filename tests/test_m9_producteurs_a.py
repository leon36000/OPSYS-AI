"""Captures M9 des producteurs M4, M6 et M3 : vraies données (outils et bus des départements), port privé réel.

Chaque lecture du catalogue M9 pour M4 (interventions, cédule de la semaine, retards et incidents, météo d'une
intervention), M6 (disponibilité) et M3 (écarts estimé-réel) est alimentée par les outils publics du département, puis
capturée par `m9_capturer_producteur` sous l'identité admin console, avec le dispatcher filtré {M9, producteur}.

Le catalogue actuel ne déclare, pour ces lectures, aucun chemin d'instant, de révision ni de pagination : la première
série de constats dit ce que la capture donne AUJOURD'HUI. `PROPOSITIONS` est la proposition de chemins DÉCLARÉS PAR LES
PRODUCTEURS, vérifiée ici sur leurs vraies réponses ; la fixture `proposees` l'applique au catalogue le temps d'un test
(`monkeypatch`, aucun fichier du catalogue n'est touché) pour prouver ce que la capture rendrait une fois adoptée.

Les limites que M9 ne peut pas voir sont vérifiées chez le producteur (signal `reste`, `tronque`, `curseur_suivant` dans
la réponse capturée) sans prétendre que la capture les signale : c'est dit dans chaque test.
Données fictives (`fictif: true`) : personnes, chantiers, stocks, devis et prévisions portent « fictif ».
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat

from opsys import contexte, lecteurs_m9, stockage
from opsys.departements import charger_departements

_SPEC = importlib.util.spec_from_file_location("m9_producteurs_a", Path(__file__).with_name("m9_producteurs_a.py"))
h = importlib.util.module_from_spec(_SPEC)
sys.modules["m9_producteurs_a"] = h
_SPEC.loader.exec_module(h)

FICTIF = True
RACINE = "resultat.resultat"  # la réponse du dispatcher est {"ok": true, "resultat": <réponse de l'outil>}

# Chemins PROPOSÉS : seulement des champs que le producteur déclare dans sa réponse (voir les tests de chaque lecture).
PROPOSITIONS = {
    "m4.cedule_semaine": {
        "instants_metier": (f"{RACINE}.interventions[*].confirme_le",),
        "revisions": (f"{RACINE}.interventions[*].revision", f"{RACINE}.interventions[*].source_ligne_id"),
    },
    "m4.retards_incidents": {
        "instants_metier": (f"{RACINE}.reports.liste[*].depuis", f"{RACINE}.incidents.liste[*].depuis"),
    },
    "m4.meteo_intervention": {"instants_metier": (f"{RACINE}.creneaux[*].prevision.emise_le",)},
    "m6.disponibilite": {},
    "m3.ecarts": {"instants_metier": ("resultat.resultat[*].horodatage_completion",)},
}
AGENT = None  # un appel d'agent : aucune identité d'appareil


# -- installation ------------------------------------------------------------------------------------------------
@pytest.fixture
def base(tmp_path, monkeypatch):
    h.installer_base(tmp_path, monkeypatch)
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def horloge():
    """Instants de réception strictement croissants (M9 n'a pas d'horloge : la console les fournit)."""
    depart = dt.datetime(2026, 10, 27, 10, 0, 0, tzinfo=dt.UTC)
    compteur = {"n": 0}

    def prochain() -> str:
        compteur["n"] += 1
        return (depart + dt.timedelta(seconds=compteur["n"])).strftime("%Y-%m-%dT%H:%M:%SZ")

    return prochain


@pytest.fixture
def proposees(monkeypatch):
    """Applique `PROPOSITIONS` au catalogue le temps du test, sans toucher au fichier du catalogue."""
    for lecture_id, proposition in PROPOSITIONS.items():
        monkeypatch.setitem(cat.PAR_ID, lecture_id, dataclasses.replace(cat.PAR_ID[lecture_id], **proposition))


def _capture(capacites, horloge, lecture_id, arguments, identite=h.ADMIN_CONSOLE) -> dict:
    """La capture ACCEPTÉE par l'outil (ok vrai, accepte vrai) ; sa page 0 se relit par `h.lire_capture`."""
    reponse = h.capturer(capacites, lecture_id, arguments, horloge(), identite)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["capture"]


def _chaine() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(h.M9, "captures_strategiques"))


def _m9(capacites, outil, arguments=None) -> dict:
    with contexte.appele_par_appareil(h.ADMIN_CONSOLE):
        reponse = capacites.appeler(outil, arguments or {})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _valeurs(page, chemin) -> list:
    return cs.extraire(page, chemin)


def _refusee(reponse) -> bool:
    return reponse["ok"] is False or reponse["resultat"].get("accepte") is False


# =====================================================================================================
# 0. Les chemins proposés sont des chemins valides du catalogue, et le catalogue actuel n'en déclare aucun
# =====================================================================================================
def test_le_catalogue_declare_les_chemins_constates_chez_les_producteurs(proposees):
    """Les chemins constatés sur les vraies réponses sont ADOPTÉS par le catalogue (la fixture `proposees` n'y change
    plus rien) ; M4 interventions pagine par curseur ; cédule, retards et disponibilité déclarent leur troncature."""
    for lecture_id, proposition in PROPOSITIONS.items():
        lecture = cat.PAR_ID[lecture_id]
        assert lecture.instants_metier == proposition.get("instants_metier", ())
        assert lecture.revisions == proposition.get("revisions", ())
        assert lecture.pagination == proposition.get("pagination")
    assert {m.chemin for m in cat.PAR_ID["m4.cedule_semaine"].incomplets} == {f"{RACINE}.tronque"}
    assert {m.chemin for m in cat.PAR_ID["m6.disponibilite"].incomplets} == {f"{RACINE}.tronque"}
    assert {m.chemin for m in cat.PAR_ID["m4.retards_incidents"].incomplets} == {
        f"{RACINE}.reports.reste", f"{RACINE}.incidents.reste"}  # fmt: skip


# =====================================================================================================
# 1. M4 : m4.interventions (m4_lister_interventions)
# =====================================================================================================
def test_m4_interventions_capture_de_vraies_interventions(base, horloge):
    m4 = h.outils_departement(h.M4)
    ids = h.m4_alimenter_interventions(m4, 5)
    c = h.capacites_m9(h.M4)
    capture = _capture(c, horloge, "m4.interventions", {})
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is True and capture["pages"] == 1
    page = h.lire_capture(c, capture["index"])
    # sans clé de pagination, la réponse est la liste v1 ENTIÈRE : la racine de la réponse est une liste
    assert isinstance(page["resultat"], list)
    assert sorted(_valeurs(page, "resultat[*].intervention_id")) == sorted(ids)
    assert set(_valeurs(page, "resultat[*].statut")) == {"planifiee"}
    assert set(_valeurs(page, "resultat[*].technicien_assigne")) == {"marc.fictif", "lea.fictif"}
    # aucun instant : le producteur déclare `fenetre_planifiee` toujours nul, jamais un horodatage
    assert _valeurs(page, "resultat[*].fenetre_planifiee") == [None] * 5
    assert capture["instants_metier"] == {"declares": False, "nombre": 0, "invalides": 0, "min": None, "max": None}
    assert capture["revisions"] == []
    assert [m["hash_maillon"] for m in _chaine()] == [capture["hash_maillon"]]
    assert _m9(c, "m9_verifier_captures")["valide"] is True


def test_m4_interventions_filtre_par_statut(base, horloge):
    m4 = h.outils_departement(h.M4)
    ids = h.m4_alimenter_interventions(m4, 4)
    h.geste(m4, "m4_signaler_report", {"intervention_id": ids[1], "motif": "meteo", "horodatage": h.HORODATAGE_PLAN})
    c = h.capacites_m9(h.M4)
    reportee = _capture(c, horloge, "m4.interventions", {"statut": "reportee"})
    page = h.lire_capture(c, reportee["index"])
    assert _valeurs(page, "resultat[*].intervention_id") == [ids[1]]
    assert _valeurs(page, "resultat[*].statut") == ["reportee"]
    planifiees = h.lire_capture(c, _capture(c, horloge, "m4.interventions", {"statut": "planifiee"})["index"])
    assert sorted(_valeurs(planifiees, "resultat[*].intervention_id")) == sorted(set(ids) - {ids[1]})


def test_m4_interventions_pagination_le_suivant_est_dans_page_curseur_suivant(base, horloge):
    m4 = h.outils_departement(h.M4)
    ids = h.m4_alimenter_interventions(m4, 12)
    c = h.capacites_m9(h.M4)
    # Le catalogue suit `resultat.page.curseur_suivant` (le chemin que M4 déclare) jusqu'à la dernière page.
    complete = _capture(c, horloge, "m4.interventions", {"taille_page": 5})
    assert complete["pages"] == 3 and complete["complete"] is True and complete["verdict"] == "ACCEPTEE"
    lues = [h.lire_capture(c, complete["index"], page) for page in range(3)]
    tout = [i for page in lues for i in _valeurs(page, "resultat.interventions[*].intervention_id")]
    assert sorted(tout) == sorted(ids) and len(set(tout)) == 12, "chaque intervention exactement une fois"
    assert [_valeurs(p, "resultat.page.curseur_suivant")[0] is None for p in lues] == [False, False, True]
    assert _valeurs(lues[-1], "resultat.page.reste") == [0]


def test_m4_interventions_page_non_lue_rend_la_capture_partielle(base):
    m4 = h.outils_departement(h.M4)
    h.m4_alimenter_interventions(m4, 7)
    lecture = cat.PAR_ID["m4.interventions"]
    lire = lecteurs_m9.construire_lecteur(charger_departements(), stockage.transaction)
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(h.ADMIN_CONSOLE),
        contexte.appeler_en_tant_que(h.M9, origine=h.M9),
    ):
        premiere = lire(h.M4, "m4_lister_interventions", {"taille_page": 3})
    assert premiere["ok"] is True and premiere["resultat"]["page"]["reste"] == 4
    capture = cs.construire(
        lecture,
        {"taille_page": 3},
        [premiere],
        recu_a="2026-10-27T10:00:00Z",
        reference=None,
        index=0,
        hash_precedent=cs.HASH_INITIAL,
    )
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is False
    assert capture["raison_incomplete"] == "page suivante non lue"


def test_m4_interventions_refus_d_identites_non_admin_et_producteur_absent(base, horloge):
    m4 = h.outils_departement(h.M4)
    h.m4_alimenter_interventions(m4, 2)
    _refus_non_admin_et_absent(h.M4, "m4.interventions", {}, "L-M9-I", horloge)


# =====================================================================================================
# 2. M4 : m4.cedule_semaine (m4_lire_cedule_semaine)
# =====================================================================================================
def test_m4_cedule_semaine_capture_une_semaine_datee_et_revisee(base, horloge, proposees):
    m4 = h.outils_departement(h.M4)
    monde = h.m4_alimenter_cedule(m4)
    c = h.capacites_m9(h.M4)
    capture = _capture(c, horloge, "m4.cedule_semaine", {"debut_semaine": h.LUNDI})
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is True and capture["pages"] == 1
    page = h.lire_capture(c, capture["index"])
    assert _valeurs(page, f"{RACINE}.debut_semaine") == [h.LUNDI]
    assert _valeurs(page, f"{RACINE}.total_interventions") == [3] and _valeurs(page, f"{RACINE}.tronque") == [False]
    assert sorted(_valeurs(page, f"{RACINE}.interventions[*].intervention_id")) == sorted(
        monde["interventions"].values()
    )
    assert set(_valeurs(page, f"{RACINE}.interventions[*].validite")) == {"date_confirmee"}
    assert _valeurs(page, f"{RACINE}.interventions[*].plan_id") == [monde["plan_id"]] * 3
    for chemin in ("debut", "fin", "equipe_id", "lead_id", "source_application_id"):
        assert len(_valeurs(page, f"{RACINE}.interventions[*].{chemin}")) == 3, chemin
    # chemins proposés : l'instant du fait (la confirmation reçue par le serveur) et la révision de la cédule
    assert _valeurs(page, f"{RACINE}.interventions[*].confirme_le") == [h.RECU_LE.isoformat()] * 3
    assert capture["instants_metier"] == {
        "declares": True,
        "nombre": 3,
        "invalides": 0,
        "min": "2026-10-26T14:00:00Z",
        "max": "2026-10-26T14:00:00Z",
    }
    assert capture["revisions"] == sorted(["1", monde["confirmation"]["ligne_id"]])
    # `debut` et `fin` sont des instants PLANIFIÉS (futurs) : ils ne sont pas proposés comme instants de fait
    assert {cs.instant(v) for v in _valeurs(page, f"{RACINE}.interventions[*].debut")} <= {
        cs.instant("2026-11-02T08:12:00-05:00"),
        cs.instant("2026-11-02T08:14:00-05:00"),
        cs.instant("2026-11-02T09:57:00-05:00"),
    }


def test_m4_cedule_semaine_instants_et_revisions_declares_par_le_catalogue(base, horloge):
    m4 = h.outils_departement(h.M4)
    h.m4_alimenter_cedule(m4)
    c = h.capacites_m9(h.M4)
    capture = _capture(c, horloge, "m4.cedule_semaine", {"debut_semaine": h.LUNDI})
    assert capture["instants_metier"]["declares"] is True and capture["instants_metier"]["nombre"] >= 1
    assert capture["revisions"] and capture["complete"] is True
    couverture = _m9(
        c, "m9_couverture_strategique", {"reference": "2026-10-28T00:00:00Z", "attendues": ["m4.cedule_semaine"]}
    )
    assert couverture["lectures"][0]["statut"] == "PRESENTE"


def test_m4_cedule_semaine_une_correction_ajoute_une_revision_sans_contradiction(base, horloge, proposees):
    m4 = h.outils_departement(h.M4)
    monde = h.m4_alimenter_cedule(m4)
    c = h.capacites_m9(h.M4)
    avant = _capture(c, horloge, "m4.cedule_semaine", {"debut_semaine": h.LUNDI})
    apres_recu = dt.datetime(2026, 10, 27, 9, 0, 0, tzinfo=dt.UTC)
    correction = h.m4_reconfirmer_dates(m4, monde["plan_id"], 1, "2026-11-03", recu_le=apres_recu)
    assert correction["revision"] == 2
    # la semaine du 2 novembre contient toujours le mardi 3 : même lundi demandé, nouvelle révision déclarée
    apres = _capture(c, horloge, "m4.cedule_semaine", {"debut_semaine": h.LUNDI})
    assert avant["revisions"] != apres["revisions"] and "2" in apres["revisions"]
    assert correction["ligne_id"] in apres["revisions"] and monde["confirmation"]["ligne_id"] not in apres["revisions"]
    assert apres["instants_metier"]["max"] == "2026-10-27T09:00:00Z" > avant["instants_metier"]["max"]
    chaine = _chaine()
    assert [m["index"] for m in chaine] == [0, 1] and cs.valider_chaine(chaine) == (True, "")
    assert cs.contradictions(chaine) == [], "une correction de source s'ajoute, ce n'est pas une contradiction"
    page = h.lire_capture(c, apres["index"])
    assert set(_valeurs(page, f"{RACINE}.interventions[*].revision")) == {2}
    assert {v[:10] for v in _valeurs(page, f"{RACINE}.interventions[*].debut")} == {"2026-11-03"}


def test_m4_cedule_semaine_troncature_du_producteur_visible_dans_la_reponse_capturee(base, horloge, proposees):
    """Au-delà de 50 jobs non datés, le producteur coupe (`tronque`) et n'offre aucun curseur : `debut_semaine` est le
    seul argument libre. M9 ne peut donc pas lire la suite ; la capture conserve le signal dans la réponse."""
    m4 = h.outils_departement(h.M4)
    for rang in range(52):
        h.m4_planifier(m4, f"L-M9-SD{rang:02d}", techniciens=("marc.fictif",))
    c = h.capacites_m9(h.M4)
    capture = _capture(c, horloge, "m4.cedule_semaine", {"debut_semaine": h.LUNDI})
    page = h.lire_capture(c, capture["index"])
    assert _valeurs(page, f"{RACINE}.total_sans_date") == [52] and _valeurs(page, f"{RACINE}.tronque") == [True]
    assert len(_valeurs(page, f"{RACINE}.sans_date[*].intervention_id")) == 50
    assert set(_valeurs(page, f"{RACINE}.sans_date[*].raison")) == {"aucune_date_civile_confirmee"}
    assert capture["verdict"] == "ACCEPTEE"
    assert capture["instants_metier"]["nombre"] == 0, "aucune confirmation de date : aucun instant déclaré"


def test_m4_cedule_semaine_refus_du_producteur_conserve_et_identites(base, horloge):
    m4 = h.outils_departement(h.M4)
    h.m4_alimenter_cedule(m4)
    c = h.capacites_m9(h.M4)
    reponse = h.capturer(c, "m4.cedule_semaine", {"debut_semaine": "2026-11-03"}, horloge())  # un mardi
    capture = reponse["resultat"]["capture"]
    assert reponse["ok"] is True and capture["verdict"] == "REFUSEE" and capture["code"] == "REJ-CONTRAT-INVALIDE"
    assert capture["complete"] is False and "aucun fait reçu" in capture["raison_incomplete"]
    assert h.lire_capture(c, capture["index"])["resultat"]["accepte"] is False
    _refus_non_admin_et_absent(h.M4, "m4.cedule_semaine", {"debut_semaine": h.LUNDI}, "L-M9-0", horloge)


# =====================================================================================================
# 3. M4 : m4.retards_incidents (m4_lire_retards_incidents)
# =====================================================================================================
def test_m4_retards_incidents_capture_reports_et_incident_avec_leurs_instants(base, horloge, proposees):
    m4 = h.outils_departement(h.M4)
    monde = h.m4_alimenter_retards(m4)
    c = h.capacites_m9(h.M4)
    capture = _capture(c, horloge, "m4.retards_incidents", {"horodatage_reference": "2026-10-26T09:30:00Z"})
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is True
    assert capture["reference"] == "2026-10-26T09:30:00Z", "la référence demandée est conservée à part des faits"
    page = h.lire_capture(c, capture["index"])
    assert _valeurs(page, f"{RACINE}.type") == ["RETARDS_INCIDENTS"]
    assert _valeurs(page, f"{RACINE}.reports.liste[*].intervention_id") == [monde["a"], monde["c"]]
    assert _valeurs(page, f"{RACINE}.reports.liste[*].motif") == ["client_absent", "decision_admin"]
    assert _valeurs(page, f"{RACINE}.reports.liste[*].heures_ecoulees") == [49, 26]
    assert _valeurs(page, f"{RACINE}.incidents.liste[*].demande_id") == [monde["demande"]]
    assert _valeurs(page, f"{RACINE}.incidents.liste[*].bloquee") == [False]
    assert set(
        _valeurs(page, f"{RACINE}.reports.liste[*].origine_heure")
        + _valeurs(page, f"{RACINE}.incidents.liste[*].origine_heure")
    ) == {"serveur"}
    assert _valeurs(page, f"{RACINE}.retard_sur_cedule.statut") == ["non_mesurable"]
    # chemins proposés : `depuis` des reports et des incidents (l'heure que le registre a gardée du fait)
    assert capture["instants_metier"] == {
        "declares": True,
        "nombre": 3,
        "invalides": 0,
        "min": "2026-10-24T08:00:00Z",
        "max": "2026-10-25T12:00:00Z",
    }
    assert capture["revisions"] == [], "aucun champ de révision n'est déclaré par ce producteur"
    couverture = _m9(
        c,
        "m9_couverture_strategique",
        {
            "reference": "2026-10-26T09:30:00Z",
            "connaissance": "2026-10-28T00:00:00Z",
            "attendues": ["m4.retards_incidents"],
        },
    )
    entree = couverture["lectures"][0]
    assert entree["statut"] == "PRESENTE" and entree["age_s"] == 77_400 and entree["fraicheur"] == "NON_EVALUEE"


def test_m4_retards_incidents_listes_bornees_a_huit_le_reste_est_dit_par_le_producteur(base, horloge, proposees):
    """Huit lignes par liste, sans curseur : M9 lit les huit plus anciennes ; `reste`/`suite` disent le reste dans la
    réponse capturée, mais la capture ne se marque pas partielle (aucune pagination déclarable)."""
    m4 = h.outils_departement(h.M4)
    h.m4_alimenter_reports(m4, 10)
    c = h.capacites_m9(h.M4)
    capture = _capture(c, horloge, "m4.retards_incidents", {"horodatage_reference": "2026-10-26T09:30:00Z"})
    page = h.lire_capture(c, capture["index"])
    assert _valeurs(page, f"{RACINE}.reports.total") == [10] and _valeurs(page, f"{RACINE}.reports.affiches") == [8]
    assert _valeurs(page, f"{RACINE}.reports.reste") == [2]
    assert "m4_lister_interventions (statut reportee)" in _valeurs(page, f"{RACINE}.reports.suite")[0]
    assert capture["instants_metier"]["nombre"] == 8 and capture["instants_metier"]["min"] == "2026-10-24T06:00:00Z"
    assert capture["instants_metier"]["max"] == "2026-10-24T13:00:00Z", "les deux reports les plus récents manquent"


def test_m4_retards_incidents_reference_illisible_refusee_par_m9_sans_rien_ecrire_et_identites(base, horloge):
    """La référence de lecture est aussi l'instant de référence de la capture : illisible, M9 refuse avant d'écrire
    (REJ-CAPTURE-TEMPS) ; le refus du producteur (REJ-HORODATAGE-INVALIDE) n'est donc jamais conservé comme manque."""
    m4 = h.outils_departement(h.M4)
    h.m4_alimenter_retards(m4)
    c = h.capacites_m9(h.M4)
    for illisible in ("hier matin", "2026-10-26T09:30:00"):
        reponse = h.capturer(c, "m4.retards_incidents", {"horodatage_reference": illisible}, horloge())
        assert reponse["ok"] is False and "REJ-CAPTURE-TEMPS" in json.dumps(reponse), reponse
    assert _chaine() == []
    _refus_non_admin_et_absent(
        h.M4, "m4.retards_incidents", {"horodatage_reference": "2026-10-26T09:30:00Z"}, "L-M9-R", horloge
    )


# =====================================================================================================
# 4. M4 : m4.meteo_intervention (m4_lire_meteo_intervention)
# =====================================================================================================
def _monde_meteo(base):
    m4 = h.outils_departement(h.M4)
    h.declarer_meteo(base)
    monde = h.m4_alimenter_cedule(m4, base)
    return m4, monde, monde["interventions"]["L-M9-01"]


def test_m4_meteo_intervention_sans_fournisseur_le_creneau_est_place_et_le_statut_inconnu(base, horloge, proposees):
    _, monde, iid = _monde_meteo(base)
    c = h.capacites_m9(h.M4)
    capture = _capture(c, horloge, "m4.meteo_intervention", {"intervention_id": iid, "date": h.LUNDI})
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is True
    page = h.lire_capture(c, capture["index"])
    assert _valeurs(page, f"{RACINE}.intervention_id") == [iid] and _valeurs(page, f"{RACINE}.plan_id") == [
        monde["plan_id"]
    ]
    assert _valeurs(page, f"{RACINE}.statut_intervention") == ["planifiee"]
    (creneau,) = _valeurs(page, f"{RACINE}.creneaux[*]")
    assert (creneau["date"], creneau["jour"], creneau["service"]) == (h.LUNDI, 0, "ravalement")
    assert creneau["equipe"] in {"eq-a", "eq-b"}
    assert isinstance(creneau["debut_min"], int) and creneau["fin_min"] > creneau["debut_min"]
    # `inconnu` n'est jamais `ok` : aucun fournisseur ouvert et `previsions_saisies` n'est pas un argument libre
    assert _valeurs(page, f"{RACINE}.statut") == ["inconnu"] and creneau["statut"] == "inconnu"
    assert creneau["prevision"] is None and creneau["regles"] == []
    assert creneau["cause"]["code"] == "REJ-METEO-FOURNISSEUR-FERME"
    # donc aucun instant de prévision à capturer par le port dans ce contexte
    assert capture["instants_metier"] == {"declares": True, "nombre": 0, "invalides": 0, "min": None, "max": None}
    assert capture["revisions"] == []
    couverture = _m9(
        c, "m9_couverture_strategique", {"reference": "2026-10-28T00:00:00Z", "attendues": ["m4.meteo_intervention"]}
    )
    assert couverture["lectures"][0]["statut"] == "TEMPS_METIER_NON_DECLARE"


def test_m4_meteo_intervention_chemin_d_instant_verifie_sur_une_vraie_prevision(base):
    """Une prévision saisie est refusée par le port (argument non libre) mais la lecture existe chez le producteur :
    on y vérifie que `creneaux[*].prevision.emise_le` est bien l'instant de la prévision citée, avec fuseau."""
    m4, monde, iid = _monde_meteo(base)
    points = [
        {
            "heure": f"{h.LUNDI}T{heure:02d}:00",
            "temperature_c": 12,
            "vent_kmh": 55,
            "rafales_kmh": 70,
            "precipitation_mm_h": 0,
            "probabilite_precipitation_pct": 10,
            "verglas": False,
        }
        for heure in range(6, 21)
    ]
    saisie = {
        "saisi_par": "admin.fictif",
        "source": "Bulletin fictif du 1er novembre",
        "points": points,
        "emise_le": "2026-11-01T18:00:00-04:00",
    }
    resultat = h.lire_outil(
        m4, "m4_lire_meteo_intervention", {"intervention_id": iid, "date": h.LUNDI, "previsions_saisies": saisie}
    )
    document = {"ok": True, "resultat": resultat}
    assert resultat["accepte"] is True and _valeurs(document, f"{RACINE}.statut") == ["bloquant"]
    (emise,) = _valeurs(document, PROPOSITIONS["m4.meteo_intervention"]["instants_metier"][0])
    assert emise == "2026-11-01T18:00:00-04:00" and cs.instant(emise) == cs.instant("2026-11-01T22:00:00Z")
    # et le port, lui, refuse d'injecter cette donnée : l'argument n'est pas dans `libres`
    c = h.capacites_m9(h.M4)
    refus = h.capturer(
        c,
        "m4.meteo_intervention",
        {"intervention_id": iid, "date": h.LUNDI, "previsions_saisies": saisie},
        "2026-10-27T10:00:00Z",
    )
    assert refus["ok"] is False and _chaine() == []


def test_m4_meteo_intervention_refus_du_producteur_conserve_et_identites(base, horloge):
    _, _, iid = _monde_meteo(base)
    c = h.capacites_m9(h.M4)
    reponse = h.capturer(c, "m4.meteo_intervention", {"intervention_id": "inconnue", "date": h.LUNDI}, horloge())
    capture = reponse["resultat"]["capture"]
    assert capture["verdict"] == "REFUSEE" and capture["code"] == "REJ-TRANSITION-ILLEGALE"
    _refus_non_admin_et_absent(
        h.M4, "m4.meteo_intervention", {"intervention_id": iid, "date": h.LUNDI}, "ravalement", horloge
    )


# =====================================================================================================
# 5. M6 : m6.disponibilite (m6_lire_disponibilite)
# =====================================================================================================
def test_m6_disponibilite_capture_stock_reserve_et_hors_main(base, horloge):
    m6 = h.outils_departement(h.M6)
    h.m6_alimenter_stock(m6)
    c = h.capacites_m9(h.M6)
    capture = _capture(c, horloge, "m6.disponibilite", {})
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is True and capture["pages"] == 1
    page = h.lire_capture(c, capture["index"])
    articles = {a["materiau_id"]: a for a in _valeurs(page, f"{RACINE}.articles[*]")}
    assert sorted(articles) == [h.GOUTTIERE, h.VIS]
    gouttiere = articles[h.GOUTTIERE]
    assert (
        gouttiere["stock_theorique"],
        gouttiere["hors_main"],
        gouttiere["en_main"],
        gouttiere["reserve"],
        gouttiere["disponible"],
    ) == ("150", "10", "140", "100", "40")
    assert gouttiere["par_emplacement"] == {"inconnu": "140", "rebut": "10"}
    vis = articles[h.VIS]
    assert (vis["stock_theorique"], vis["reserve"], vis["disponible"]) == ("25", "20", "5")
    assert _valeurs(page, f"{RACINE}.reservations_actives[*].devis_id") == ["DEVIS-M9-1"]
    assert _valeurs(page, f"{RACINE}.reservations_actives[*].statut") == ["pret"]
    assert _valeurs(page, f"{RACINE}.tronque") == [False] and _valeurs(page, f"{RACINE}.reservations_tronquees") == [
        False
    ]
    # aucun instant ni révision déclarés : des quantités à l'instant de la lecture, sans horodatage de fait
    assert capture["instants_metier"]["declares"] is False and capture["revisions"] == []
    assert "horodatage" not in json.dumps(page)
    couverture = _m9(
        c, "m9_couverture_strategique", {"reference": "2026-10-28T00:00:00Z", "attendues": ["m6.disponibilite"]}
    )
    assert couverture["lectures"][0]["statut"] == "TEMPS_METIER_NON_DECLARE"


def test_m6_disponibilite_filtre_par_articles(base, horloge):
    m6 = h.outils_departement(h.M6)
    h.m6_alimenter_stock(m6)
    c = h.capacites_m9(h.M6)
    capture = _capture(c, horloge, "m6.disponibilite", {"materiau_ids": [h.VIS]})
    page = h.lire_capture(c, capture["index"])
    assert _valeurs(page, f"{RACINE}.articles[*].materiau_id") == [h.VIS]
    assert _valeurs(page, f"{RACINE}.reservations_actives[*].devis_id") == ["DEVIS-M9-1"]
    inconnu = h.lire_capture(c, _capture(c, horloge, "m6.disponibilite", {"materiau_ids": ["introuvable"]})["index"])
    assert _valeurs(inconnu, f"{RACINE}.articles[*].stock_theorique") == ["0"], "article inconnu : stock vide"


def test_m6_disponibilite_au_dela_de_quinze_articles_la_suite_se_lit_par_materiau_ids(base, horloge):
    """Quinze articles par lecture sans curseur : `tronque` le dit dans la réponse capturée (la capture reste complète
    pour M9, aucune pagination n'étant déclarable) et la suite s'obtient par l'argument libre `materiau_ids`."""
    m6 = h.outils_departement(h.M6)
    ids = h.m6_recevoir_articles(m6, 16)
    c = h.capacites_m9(h.M6)
    page = h.lire_capture(c, _capture(c, horloge, "m6.disponibilite", {})["index"])
    lus = _valeurs(page, f"{RACINE}.articles[*].materiau_id")
    assert lus == ids[:15] and _valeurs(page, f"{RACINE}.tronque") == [True]
    suite = h.lire_capture(c, _capture(c, horloge, "m6.disponibilite", {"materiau_ids": ids[15:]})["index"])
    assert _valeurs(suite, f"{RACINE}.articles[*].materiau_id") == ids[15:]
    assert _valeurs(suite, f"{RACINE}.articles[*].stock_theorique") == ["25"]
    assert _valeurs(suite, f"{RACINE}.tronque") == [False]


def test_m6_disponibilite_refus_d_identites_non_admin_et_producteur_absent(base, horloge):
    m6 = h.outils_departement(h.M6)
    h.m6_alimenter_stock(m6)
    _refus_non_admin_et_absent(h.M6, "m6.disponibilite", {}, "gouttiere", horloge)


# =====================================================================================================
# 6. M3 : m3.ecarts (m3_lire_ecarts_estime_reel)
# =====================================================================================================
def test_m3_ecarts_capture_par_devis_avec_instants_de_completion(base, horloge, proposees):
    m3 = h.outils_departement(h.M3)
    wcts = h.m3_alimenter_ecarts(m3)
    c = h.capacites_m9(h.M3)
    capture = _capture(c, horloge, "m3.ecarts", {"devis_id": h.DEVIS_M3})
    assert capture["verdict"] == "ACCEPTEE" and capture["complete"] is True and capture["pages"] == 1
    page = h.lire_capture(c, capture["index"])
    assert _valeurs(page, "resultat.resultat[*].wct_id") == wcts
    assert set(_valeurs(page, "resultat.resultat[*].devis_id")) == {h.DEVIS_M3}
    assert _valeurs(page, "resultat.resultat[*].materiaux.lignes[*].ecart_pourcentage") == ["0.0667", "0.0667"]
    assert _valeurs(page, "resultat.resultat[*].materiaux.lignes[*].critique") == [False, False]
    assert _valeurs(page, "resultat.resultat[*].main_doeuvre.duree_reelle_minutes") == ["120", "120"]
    # fail-closed du producteur : sans estimation d'origine qualifiée, pas de durée estimée ni d'écart relatif
    assert _valeurs(page, "resultat.resultat[*].main_doeuvre.ecart_relatif") == [None, None]
    verdicts = _valeurs(page, "resultat.resultat[*].main_doeuvre.verdict.code")
    assert verdicts == ["REJ-ECART-ESTIMATION-ORIGINE-ABSENTE"] * 2
    # chemin proposé : l'instant de complétion que le WCT déclare (ISO 8601 avec fuseau)
    assert capture["instants_metier"] == {
        "declares": True,
        "nombre": 2,
        "invalides": 0,
        "min": "2026-09-28T18:00:00Z",
        "max": "2026-10-05T14:30:00Z",
    }
    assert capture["revisions"] == [], "aucune révision déclarée : un état courant est fusionné sans numéro"
    couverture = _m9(c, "m9_couverture_strategique", {"reference": "2026-10-28T00:00:00Z", "attendues": ["m3.ecarts"]})
    assert couverture["lectures"][0]["statut"] == "PRESENTE" and couverture["lectures"][0]["age_s"] > 0


def test_m3_ecarts_par_periode_semi_ouverte_et_fenetre_vide(base, horloge, proposees):
    m3 = h.outils_departement(h.M3)
    h.m3_alimenter_ecarts(m3)
    c = h.capacites_m9(h.M3)
    septembre = _capture(
        c, horloge, "m3.ecarts", {"depuis": "2026-09-01T00:00:00-04:00", "jusqua": "2026-10-01T00:00:00-04:00"}
    )
    page = h.lire_capture(c, septembre["index"])
    assert _valeurs(page, "resultat.resultat[*].wct_id") == ["wct-m9-001"]
    assert septembre["instants_metier"]["nombre"] == 1 and septembre["instants_metier"]["max"] == "2026-09-28T18:00:00Z"
    # borne haute exclue : une fenêtre qui se termine exactement à la complétion ne la contient pas
    exclue = _capture(
        c, horloge, "m3.ecarts", {"depuis": "2026-09-01T00:00:00-04:00", "jusqua": "2026-09-28T14:00:00-04:00"}
    )
    assert _valeurs(h.lire_capture(c, exclue["index"]), "resultat.resultat[*]") == []
    assert exclue["verdict"] == "ACCEPTEE" and exclue["instants_metier"]["nombre"] == 0


def test_m3_ecarts_refus_du_producteur_conserve_et_identites(base, horloge):
    m3 = h.outils_departement(h.M3)
    h.m3_alimenter_ecarts(m3)
    c = h.capacites_m9(h.M3)
    sans_filtre = h.capturer(c, "m3.ecarts", {}, horloge())["resultat"]["capture"]
    assert sans_filtre["verdict"] == "REFUSEE" and sans_filtre["code"] == "REJ-ECART-FILTRE-ABSENT"
    incomplete = h.capturer(c, "m3.ecarts", {"depuis": "2026-09-01T00:00:00-04:00"}, horloge())["resultat"]["capture"]
    assert incomplete["verdict"] == "REFUSEE" and incomplete["code"] == "REJ-ECART-PERIODE-INCOMPLETE"
    assert [m["verdict"] for m in _chaine()] == ["REFUSEE", "REFUSEE"], "un refus est un manque conservé"
    _refus_non_admin_et_absent(h.M3, "m3.ecarts", {"devis_id": h.DEVIS_M3}, "wct-m9", horloge)


# =====================================================================================================
# Refus communs : identités non admin refusées avant toute lecture ; producteur absent = ERREUR conservée
# =====================================================================================================
def _refus_non_admin_et_absent(producteur, lecture_id, arguments, indice_donnee, horloge):
    """Vendeur, employé et agent sont refusés SANS écriture ni fuite ; un producteur non installé est une ERREUR
    conservée (`producteur_indisponible`), jamais une exception ni un registre vide silencieux."""
    c = h.capacites_m9(producteur)
    avant = _chaine()
    for identite in (h.VENDEUR_CONSOLE, h.EMPLOYE_CONSOLE, h.MARC, AGENT):
        reponse = h.capturer(c, lecture_id, arguments, horloge(), identite)
        assert _refusee(reponse), (identite, reponse)
        assert indice_donnee not in json.dumps(reponse)
    assert _chaine() == avant, "aucune capture écrite par un appelant refusé"
    sans = {k: v for k, v in charger_departements().items() if k != producteur}
    c_sans = h.capacites_m9(producteur, departements=sans)
    reponse = h.capturer(c_sans, lecture_id, arguments, horloge())
    capture = reponse["resultat"]["capture"]
    assert reponse["ok"] is True and capture["verdict"] == "ERREUR" and capture["code"] == "producteur_indisponible"
    assert capture["complete"] is False and capture["instants_metier"]["nombre"] == 0
    chaine = _chaine()
    assert len(chaine) == len(avant) + 1 and chaine[-1]["verdict"] == "ERREUR" and cs.valider_chaine(chaine)[0]
    assert indice_donnee not in json.dumps(chaine[-1])
