"""PLAN T4.11, E2E « estimation risquée » (DEFINITION-PRODUIT §7 M3, preuve de complétion ; M3.11 et M3.12).

Le VRAI socle (`Capacites`, approbations, bus, identité) sur le VRAI manifeste de M3 (mode `ombre`), base SQLite
temporaire migrée, outils réels. Le cas : une estimation RISQUÉE. Une seule photo, sans objet d'échelle (mesure à bornes
larges) ; un coût unitaire qui varie du simple au quadruple (40 à 160 $ le pi²), tiré en PERT parce que le barème donne
son mode (70 $) ; un plancher de rentabilité au-dessus de la borne basse de l'intervalle. On prouve, de bout en bout :

- l'estimation reste `EstimationV1` (douze clés) et porte, à côté, P50 et P80 du coût, la loi de chaque poste, le
  facteur dominant et trois scénarios de prix, avec un taux de la configuration (prudent) et deux de l'appel ;
- le scénario agressif passe sous le minimum rentable : alerte rouge et motif de revue ; les deux autres non ;
- la revue N4 de T4.7 dit la MÊME chose que le scénario, pour chacun des trois : on crée un devis au prix de chaque
  scénario (au cent près, par la même formule de prix) et la revue lève le motif rouge du minimum si et seulement si le
  scénario l'avait levé, avec le même motif ;
- le vendeur demande l'envoi du devis agressif : la file du propriétaire porte l'alerte rouge, le propriétaire décide,
  le devis passe `envoye` avec la trace de ce qui a été regardé ;
- sans minimum rentable déclaré, les DEUX côtés disent « non évaluable » et quoi déclarer, jamais « pas d'alerte ».

Données fictives (`fictif: true`). Peu de tests, chacun racontant un scénario : chaque test qui touche la base migre un
SQLite neuf, et les outils de mutation de M3 rejouent toute la suite du département à chaque mutant.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from m2_preparation_estimation import marqueur_m2
from sqlalchemy import func, select

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, hierarchie_echelle, revue_devis, scenarios  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import (  # noqa: E402
    approbations,
    approbations_appareil,
    contexte,
    idempotence,
    identite,
    liaison_cibles,
    stockage,
)
from opsys.capacites import Capacites  # noqa: E402
from opsys.departements import lire_manifeste  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402
from opsys.stockage.schema import EVENEMENTS_SORTANTS  # noqa: E402

FICTIF = True
_RACINE_M3 = Path(__file__).resolve().parents[1]
_HORODATAGE = "2026-09-29T14:00:00-04:00"
_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
DEP = "m03-estimation"
NOM_ENVOI = "m3_demander_envoi_devis"
APPAREIL = "tel-fictif-estimation-risquee"
LEAD = "lead-risque-001"
MINIMUM_RENTABLE = 2500  # dollars canadiens : la décision (fictive) du propriétaire

VENDEUR = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
PROPRIO = contexte.IdentiteAppelante(personne="proprio", role="admin")

# Le barème de l'estimation risquée : du simple au quadruple, avec un mode. 25 pi² : coûts de 1 000 à 4 000 $.
BAREME_RISQUE = {
    "version": "fictif-2026-risque",
    "unite": "pi2",
    "postes": {"ravalement": {"cout_unitaire_min": 40.0, "cout_unitaire_max": 160.0, "cout_unitaire_mode": 70.0}},
}
QUANTITE = 25
PLANCHER_RENTABLE = 1500  # au-dessus de la borne basse de l'intervalle (~1 070 $) : l'alerte de plancher lève
GRAINE = 20260929
TAUX_DE_L_APPEL = {"normal": "0.30", "agressif": "0.05"}  # le taux prudent vient de la configuration
CONFIGURATION = {
    "revue_devis": {
        "minimum_rentable_cad": MINIMUM_RENTABLE, "confiance_minimale": hierarchie_echelle.NIVEAUX_CONFIANCE[1]},
    "scenarios_prix": {"taux_marge": {"prudent": 0.40, "normal": None, "agressif": None}},
}


# -- installation ---------------------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m3-risque.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def departements(base_durable):
    return {DEP: lire_manifeste(_RACINE_M3)}


@pytest.fixture
def capacites(departements):
    return Capacites(departements, stockage.transaction, appelant=DEP, memoire=False)


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un (fictif)", _MOT_DE_PASSE, ["seller"])
        identite.creer_personne(cnx, "proprio", "Propriétaire (fictif)", _MOT_DE_PASSE, ["admin", "nathan_owner"])


@pytest.fixture
def proprietaire_a_declare(tmp_path, monkeypatch):
    """Le propriétaire a fixé son minimum rentable et le taux prudent : un manifeste jetable (le vrai est vide)."""
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(json.dumps({"configuration": CONFIGURATION}), encoding="utf-8")
    monkeypatch.setattr(outils_m3, "_MANIFESTE", manifeste)


def _outil(nom):
    return next(o for o in outils_m3.outils() if o.nom == nom)


def _estimer(**surcharges):
    """L'estimation risquée par l'outil réel (`executer_atomique`, comme les tests de T4.7 pour `m3_creer_devis`)."""
    contrat_estimation = {
        "lead_id": LEAD,
        "conversation_id": "conv-risque-001",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }
    arguments = {
        "contrat": contrat_estimation,
        "marqueur": marqueur_m2(LEAD, contrat=contrat_estimation),
        # UNE photo, sans objet d'échelle : `MONO_VUE_BORNES_LARGES`, l'incertitude de mesure la plus haute
        "photos": [{
            "photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
            "angle": "face", "reference_echelle": None,
        }],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": BAREME_RISQUE,
        "quantite": QUANTITE,
        "plancher_rentable": PLANCHER_RENTABLE,
        "graine": GRAINE,
        "taux_marge_scenarios": TAUX_DE_L_APPEL,
    }
    arguments.update(surcharges)
    reponse = executer_atomique(_outil("m3_estimer_projet"), arguments)
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _creer_devis_au_prix_du_scenario(devis_id, scenario):
    """Un devis d'un seul forfait dont le coût est celui du scénario et le taux, le sien : son prix total est calculé
    par le code, par la même formule que le scénario."""
    reponse = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": devis_id, "lead_id": LEAD, "chantier_id": None,
        "lignes": [{"description": "Ravalement, estimation risquée (fictif)", "quantite": "1", "unite": "forfait",
                    "cout_unitaire": scenario["cout"], "reference_besoin_materiau": None}],
        "taux_marge": scenario["taux_marge"], "horodatage": _HORODATAGE,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    _assurer_lead_m2_et_liaison(LEAD)


def _assurer_lead_m2_et_liaison(lead_id):
    """Prépare les registres canoniques M2/M10 nécessaires à un ticket privé M3."""
    from m2_revenue_crm import ingestion, statuts
    from m2_revenue_crm import registre as registre_m2
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    with stockage.transaction():
        reg_m2 = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
        if statuts.statut_courant(reg_m2, lead_id) is None:
            contrat = {
                "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
                "contact": {"nom": f"Client {lead_id}", "telephone": "555-0101"},
                "type_travaux": "renovation_totale", "ville": "Québec",
                "urgence_declaree": False, "canal": "telephone",
            }
            nouveau = registre_m2.Registre()
            _, verdict = ingestion.ingerer(contrat, nouveau, _HORODATAGE)
            assert verdict is None
            stockage.maillons("m02-revenue-crm", "principal").extend(nouveau.lire())

    cle_session = f"agent:{DEP}:tests:{lead_id}"
    with stockage.transaction():
        reg_m10 = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        active = liaison_m10.liaison_courante(cle_session, reg_m10)
        if active is None:
            _, refus = liaison_m10.lier_session_affaire(
                cle_session, lead_id, "proprio", "admin", "appareil", "liaison M3 de fixture fictive",
                _HORODATAGE, reg_m10,
            )
            assert refus is None
        else:
            assert active["affaire_id"] == lead_id
    return cle_session


def _etat_du_devis(devis_id):
    with stockage.transaction():
        etat, verdict = outils_m3.devis_durable.lire_devis(outils_m3.registre_devis_production(), devis_id)
    assert verdict is None, verdict
    return etat


def _contexte_revue(resultat):
    """Ce que l'agent recopie de la réponse de l'estimation dans la demande d'envoi (SKILL, étape 7)."""
    return {
        "niveau_confiance_hierarchie": resultat["niveau_confiance_hierarchie"],
        "verdict_estimation": resultat["estimation"]["verdict_estimation"],
        "alerte_plancher": resultat["estimation"]["alerte_plancher"],
    }


def _demander(capacites, devis_id, contexte_revue, cle="cle-risque-1"):
    arguments = {"devis_id": devis_id, "contexte_revue": contexte_revue}
    cache = getattr(capacites, "_tickets_fixture_m3", None)
    if cache is None:
        cache = {}
        capacites._tickets_fixture_m3 = cache
    cle_cache = (cle, idempotence.empreinte_arguments(arguments))
    if cle_cache not in cache:
        devis, verdict = outils_m3.devis_durable.lire_devis(
            outils_m3.registre_devis_production(), devis_id
        )
        assert verdict is None and devis is not None
        cle_session = _assurer_lead_m2_et_liaison(devis["lead_id"])
        with stockage.transaction() as cnx:
            ticket = liaison_cibles.emettre_ticket(
                cnx, departement=DEP, agent_id=DEP, cle_session=cle_session,
                affaire_id=devis["lead_id"], origine_affaire="session",
                outil=NOM_ENVOI, arguments=arguments,
            )
        cache[cle_cache] = ticket["ticket"]
    return capacites.appeler(
        NOM_ENVOI, arguments, ticket_cible=liaison_cibles.TicketMeta(cache[cle_cache])
    )


def _file(departements):
    with stockage.transaction() as cnx:
        return approbations.file_proprietaire(cnx, departements)


def _decider_app(departements, demande_id, identite_appelante):
    with stockage.transaction() as cnx:
        return approbations_appareil.decider_demande(
            cnx, departements, identite_appelante, demande_id, "approuver", "", appareil="tel-decision-risque")


def _evenements_envoye(devis_id):
    with stockage.transaction() as cnx:
        return cnx.execute(
            select(func.count()).select_from(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_envoye",
                   EVENEMENTS_SORTANTS.c.evenement_id == f"m3-devis-envoye-{devis_id}")
        ).scalar_one()


def _revue_du_devis(devis_id, contexte_revue):
    revue, verdict = revue_devis.evaluer_revue(_etat_du_devis(devis_id), contexte_revue, outils_m3._seuils_revue())
    assert verdict is None, verdict
    return revue


# =========================================================================================
# 1. L'estimation risquée : EstimationV1 gelé, et à côté P50, P80, facteur dominant, trois scénarios
# =========================================================================================
def test_l_estimation_risquee_dit_son_incertitude_et_trois_prix_dont_un_sous_le_minimum(
    base_durable, proprietaire_a_declare
):
    resultat = _estimer()

    # EstimationV1 : gelé, douze clés ; le risque se lit dans le verdict, la confiance et l'alerte de plancher.
    estimation = resultat["estimation"]
    assert set(estimation) == set(contrats.CHAMPS_ESTIMATION_V1)
    assert estimation["prix_bloque"] is False
    assert estimation["niveau_confiance"] == 0.99  # bornes les plus larges demandées à la simulation
    assert estimation["verdict_estimation"] == contrats.VERDICT_REFERENCE_ECHELLE_ABSENTE
    assert estimation["alerte_plancher"] is True
    assert resultat["niveau_confiance_hierarchie"] == hierarchie_echelle.NIVEAUX_CONFIANCE[2]  # MONO_VUE_BORNES_LARGES
    assert not set(scenarios.CHAMPS_SOEURS_ESTIMATION) & set(estimation)

    # P50 et P80 : lus sur les MÊMES tirages que l'intervalle, dans la loi que le barème annonce (PERT, mode fourni).
    distribution = resultat["distribution_cout"]
    p50, p80 = Decimal(distribution["p50"]), Decimal(distribution["p80"])
    intervalle = estimation["intervalle_confiance"]
    assert Decimal(str(intervalle["borne_basse"])) <= p50 <= p80 <= Decimal(str(intervalle["borne_haute"]))
    assert distribution["graine"] == estimation["graine_monte_carlo"] == GRAINE
    assert distribution["postes"] == [{
        "poste": "ravalement", "loi": "PERT", "mode": "70.00",
        "raison": "cout_unitaire_mode fourni par le barème : tirage PERT"}]
    assert resultat["facteurs_dominants"] == [
        {"rang": 1, "poste": "ravalement", "amplitude": "3000.00", "part_variance": "1.0000"}]

    # Les trois scénarios : le taux prudent vient de la configuration, les deux autres de l'appel.
    section = resultat["scenarios_prix"]
    par_nom = {s["scenario"]: s for s in section["scenarios"]}
    assert [s["scenario"] for s in section["scenarios"]] == ["prudent", "normal", "agressif"]
    # (le YAML écrit 0.40, un nombre : lu tel qu'écrit, il vaut 0.4 ; le prix est le même)
    assert {nom: (s["taux_marge"], s["source_taux"]) for nom, s in par_nom.items()} == {
        "prudent": ("0.4", "configuration"), "normal": ("0.30", "appel"), "agressif": ("0.05", "appel")}
    assert par_nom["prudent"]["cout"] == distribution["p80"]
    assert par_nom["normal"]["cout"] == par_nom["agressif"]["cout"] == distribution["p50"]
    prix = {nom: Decimal(s["prix"]) for nom, s in par_nom.items()}
    # Étalonnage de la fixture : si ces bornes tombaient, il faudrait recaler le minimum (2 500 $), pas le code.
    assert prix["agressif"] < MINIMUM_RENTABLE <= prix["normal"] < prix["prudent"], prix

    # Jamais sous le minimum rentable sans alerte rouge et motif de revue.
    assert {nom: s["alerte_rouge"] for nom, s in par_nom.items()} == {
        "prudent": False, "normal": False, "agressif": True}
    assert section["alerte_rouge"] is True and section["non_evaluables"] == []
    [motif] = par_nom["agressif"]["motifs"]
    assert motif["code"] == "PRIX_SOUS_MINIMUM_RENTABLE" and motif["gravite"] == "rouge"
    assert motif["donnee"]["valeur"] == par_nom["agressif"]["prix"]
    assert motif["seuil"] == {"nom": "minimum_rentable_cad", "valeur": str(MINIMUM_RENTABLE), "source": "configuration"}
    assert par_nom["normal"]["motifs"] == par_nom["prudent"]["motifs"] == []

    # L'estimation elle-même n'a ni coût ni taux de scénario dans le registre : un maillon, chaîne valide.
    [maillon] = outils_m3.registre_production().lire()
    assert not set(scenarios.CHAMPS_SOEURS_ESTIMATION) & set(maillon["charge"])
    assert outils_m3.registre_production().valider_chaine() == (True, "")


# =========================================================================================
# 2. La revue N4 de T4.7 dit la même chose que le scénario, puis le propriétaire décide
# =========================================================================================
def test_la_revue_n4_d_un_devis_a_chaque_prix_dit_ce_que_disait_le_scenario_puis_le_proprietaire_decide(
    capacites, departements, personnes, proprietaire_a_declare
):
    resultat = _estimer()
    contexte_revue = _contexte_revue(resultat)
    par_nom = {s["scenario"]: s for s in resultat["scenarios_prix"]["scenarios"]}

    for nom, scenario in par_nom.items():
        devis_id = f"M3-DEVIS-risque-{nom}"
        _creer_devis_au_prix_du_scenario(devis_id, scenario)
        # le devis a le prix du scénario, au cent près : la même formule, sans seconde version
        assert str(_etat_du_devis(devis_id)["prix_total"]) == scenario["prix"], nom

        revue = _revue_du_devis(devis_id, contexte_revue)
        motifs_du_minimum = [m for m in revue["motifs"] if m["code"] == "PRIX_SOUS_MINIMUM_RENTABLE"]
        assert bool(motifs_du_minimum) is scenario["alerte_rouge"], nom  # la même alerte des deux côtés
        assert motifs_du_minimum == scenario["motifs"], nom  # et le même motif, mot pour mot
        # l'alerte de plancher de l'estimation, elle, est celle de l'estimation : rouge pour les trois devis
        assert any(m["code"] == "PLANCHER_ESTIMATION_FRANCHI" and m["gravite"] == "rouge" for m in revue["motifs"])

    # Le vendeur demande l'envoi du devis agressif ; la demande attend, le devis reste brouillon.
    reponse = _demander(capacites, "M3-DEVIS-risque-agressif", contexte_revue)
    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation", reponse
    assert _etat_du_devis("M3-DEVIS-risque-agressif")["statut"] == "brouillon"

    # La file du propriétaire porte l'alerte rouge d'abord, avec le prix et le minimum du scénario.
    [attente] = [i for i in _file(departements) if i["type"] == "revue_envoi_devis"]
    prix_agressif = par_nom["agressif"]["prix"]
    assert attente["resume"].startswith(
        f"Envoi du devis M3-DEVIS-risque-agressif à approuver : ALERTE ROUGE : prix {prix_agressif} $ sous le minimum "
        f"rentable {MINIMUM_RENTABLE} $ ; plancher de rentabilité franchi (alerte de l'estimation)")
    assert len(attente["resume"]) <= approbations_appareil.LIMITE_RESUME_ATTENTE

    # Le propriétaire l'a lue, et décide : le devis passe `envoye` UNE fois, avec ce qui a été regardé.
    resultat_decision, verdict = _decider_app(departements, reponse["demande_id"], PROPRIO)
    assert verdict is None and resultat_decision["statut"] == "executee"
    devis = _etat_du_devis("M3-DEVIS-risque-agressif")
    assert devis["statut"] == "envoye" and devis["envoi_approuve_par"] == "proprio"
    assert devis["revue_envoi"]["alerte_rouge"] is True
    assert devis["revue_envoi"]["motifs"][:2] == ["PRIX_SOUS_MINIMUM_RENTABLE", "PLANCHER_ESTIMATION_FRANCHI"]
    assert _evenements_envoye("M3-DEVIS-risque-agressif") == 1
    # Les deux autres devis n'ont pas bougé : aucune demande, aucun envoi.
    assert {_etat_du_devis(f"M3-DEVIS-risque-{nom}")["statut"] for nom in ("prudent", "normal")} == {"brouillon"}


# =========================================================================================
# 3. Sans minimum rentable déclaré : non évaluable des DEUX côtés, jamais « pas d'alerte »
# =========================================================================================
def test_sans_minimum_declare_le_scenario_et_la_revue_disent_non_evaluable_et_quoi_declarer(
    departements, personnes
):
    """Le vrai manifeste laisse le minimum rentable vide à dessein : le prix agressif n'est jugé ni par le scénario ni
    par la revue, et les deux nomment la même chose à déclarer."""
    resultat = _estimer(taux_marge_scenarios={"prudent": "0.40", "normal": "0.30", "agressif": "0.05"})
    section = resultat["scenarios_prix"]
    assert [s["alerte_rouge"] for s in section["scenarios"]] == [None, None, None]  # ni vrai, ni faux
    assert section["alerte_rouge"] is None
    assert all(s["prix"] is not None for s in section["scenarios"])  # les prix existent, leur confrontation manque
    [manque_du_scenario] = section["non_evaluables"]
    assert manque_du_scenario["manque"] == ["seuil à configurer : minimum_rentable_cad"]

    agressif = next(s for s in section["scenarios"] if s["scenario"] == "agressif")
    _creer_devis_au_prix_du_scenario("M3-DEVIS-risque-sans-minimum", agressif)
    revue = _revue_du_devis("M3-DEVIS-risque-sans-minimum", _contexte_revue(resultat))
    [manque_de_la_revue] = [n for n in revue["non_evaluables"] if n["code"] == "PRIX_SOUS_MINIMUM_RENTABLE"]
    assert manque_de_la_revue == manque_du_scenario
    assert not any(m["code"] == "PRIX_SOUS_MINIMUM_RENTABLE" for m in revue["motifs"])


def test_une_estimation_risquee_aux_photos_faibles_reste_bloquee_sans_p50_ni_scenario(
    base_durable, proprietaire_a_declare
):
    """La garde des photos passe avant tout : une seule photo trop petite bloque le prix, donc aucun scénario."""
    resultat = _estimer(photos=[{
        "photo_id": "p1", "resolution_largeur": 640, "resolution_hauteur": 480, "eclairage": 7, "angle": "face",
        "reference_echelle": None}])
    assert resultat["estimation"]["prix_bloque"] is True
    assert resultat["estimation"]["verdict_estimation"] == contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE
    assert {cle: resultat[cle] for cle in scenarios.CHAMPS_SOEURS_ESTIMATION} == dict.fromkeys(
        scenarios.CHAMPS_SOEURS_ESTIMATION)
    assert resultat["prix_recommande"] is None
