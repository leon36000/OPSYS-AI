"""Outils du moteur de calcul M5 (tranche 1, `docs/moteur-calcul.md`) : portée fermée, mentions, reçus, lecture pure.

Chaque outil est appelé par le socle (`executer_atomique`) sur une instance SQLite jetable : sa sortie acceptée porte
les deux mentions et un reçu que `m5_verifier_recu_calcul` rejoue à l'identique ; une identité d'appareil est refusée ;
le Monte-Carlo part de la MÊME prévision que `m5_prevoir_tresorerie` (même solde de base, même `prevision_id`) et
n'écrit rien (la base entière est identique avant et après). Données fictives.
"""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import analyse, conformite, encodage, registre

from opsys import contexte, identite, stockage
from opsys.outils import Autonomie, executer_atomique

FICTIF = True
D = Decimal
ADMIN = contexte.IdentiteAppelante(personne="admin.calcul.fictif", role="admin")
OWNER_CONSOLE = contexte.IdentiteAppelante(personne="admin.calcul.fictif", role="nathan_owner", source="console")
_OUTILS_CALCUL = sorted(analyse.SORTIES_CALCUL)


def _configuration(echeance_paies="2026-10-08"):
    return {"configuration": {
        "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12,
                   "taxes_remises_jusqu_au": "2026-09-30"},
        "obligations_declarees": {
            "paies": {"montant": "4200.00", "source": "paie fictive P-1", "au": "2026-10-01"},
            "das": {"montant": "1300.00", "source": "déclaration fictive D-1", "au": "2026-10-01"},
            "dettes": {"montant": "0.00", "source": "relevé fictif D-2", "au": "2026-10-01"},
            "reserves": {"montant": "0.00", "source": "décision fictive R-1", "au": "2026-10-01"},
        },
        "prevision": {
            "horizon_semaines": 4,
            "seuil_alerte": {"montant": "2000.00", "source": "seuil fictif", "au": "2026-10-01"},
            "echeances_obligations": {"paies": echeance_paies, "das": "2026-10-15", "dettes": "2026-10-08"},
        },
    }}


@pytest.fixture
def instance(tmp_path, monkeypatch):
    chemin = tmp_path / "m5-calcul.db"
    url = f"sqlite:///{chemin}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.calcul.fictif", "Admin Calcul Fictif", "mot-de-passe-calcul-123",
                                ["admin", "nathan_owner"])
        registre.enregistrer_mouvement({
            "montant": D("9000.00"), "type_mouvement": "ENCAISSEMENT", "horodatage": "2026-10-01T09:00:00-04:00",
            "classe_retention": "STANDARD", "source": "relevé fictif Q-0"}, m5_outils._registre_mouvements(None))
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump(_configuration(), allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    yield {"outils": {o.nom: o for o in m5_outils.outils()}, "base": chemin, "manifeste": manifeste}
    stockage.liberer()


def _appeler(instance, nom, arguments, identite_appelante=None):
    if identite_appelante is None:
        return executer_atomique(instance["outils"][nom], arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(instance["outils"][nom], arguments)


def _accepte(reponse):
    assert reponse["ok"] is True, reponse
    corps = reponse["resultat"]
    assert corps["accepte"] is True, corps
    assert corps["resultat"]["mention"] == analyse.MENTION_ANALYSE_PREPARATOIRE
    assert corps["resultat"]["mention_comptable"] == analyse.MENTION_COMPTABLE
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 6000
    return corps["resultat"]


def _refuse(reponse):
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


_DISTRIBUTIONS = {"paies": {"montant": {"loi": "triangulaire", "min": "0.95", "mode": "1", "max": "1.2"}},
                  "das": {"montant": {"loi": "normale_tronquee", "moyenne": "1", "ecart_type": "0.05", "min": "0.9",
                                      "max": "1.1"}}}


def _arguments():
    return {
        "m5_calculer_rentabilite_investissement": {
            "objet": "vehicule", "flux": ["-68000.00", "21000.00", "21000.00", "21000.00", "21000.00", "9000.00"],
            "taux_actualisation": "0.07", "taux_financement": "0.065", "taux_reinvestissement": "0.04"},
        "m5_calculer_amortissement_pret": {
            "objet": "pret_entreprise", "montant_emprunte": "100000", "taux_annuel": "0.05",
            "frequence": "mensuelle", "convention": "canadienne_semestrielle", "amortissement_annees": 25},
        "m5_comparer_credit_bail_achat": {
            "objet": "vehicule", "taux_actualisation_annuel": "0.07", "mois": 48, "prix_achat": "60000.00",
            "frais_achat": "500.00", "valeur_residuelle": "20000.00", "paiement_mensuel": "1100.00",
            "depot_initial": "3000.00", "paiements_en_debut_de_periode": True},
        "m5_calculer_point_mort": {"frais_fixes": "120000.00", "prix_unitaire": "4500.00",
                                   "cout_variable_unitaire": "2900.00", "quantite_prevue": "90"},
        "m5_analyser_sensibilite_projet": {
            "objet": "equipement",
            "base": {"investissement_initial": "45000", "flux_annuel": "11000", "croissance_annuelle": "0.02",
                     "duree_annees": 6, "taux_actualisation": "0.08", "valeur_residuelle": "4000"},
            "variations": {"flux_annuel": {"bas": "8000", "haut": "13000"},
                           "taux_actualisation": {"bas": "0.05", "haut": "0.11"}},
            "scenarios": [{"nom": "perte-gros-client", "hypotheses": {"flux_annuel": "7000"}}]},
        "m5_simuler_tresorerie_monte_carlo": {
            "aujourd_hui": "2026-10-01", "graine": 20261031, "tirages": 400, "distributions": _DISTRIBUTIONS,
            "autorise_couts": True},
    }


def _vidage(chemin):
    with sqlite3.connect(chemin) as cnx:
        return list(cnx.iterdump())


# ------------------------------------------------------------------------------------- déclaration des outils
def test_outils_du_moteur_t0_portee_d_appareil_fermee_et_classes_en_analyse(instance):
    for nom in _OUTILS_CALCUL:
        outil = instance["outils"][nom]
        assert outil.autonomie == Autonomie.T0 and outil.roles_appareil == frozenset(), nom
        assert len(outil.description) <= 1024
    assert analyse.SORTIES_CALCUL <= analyse.SORTIES_D_ANALYSE
    assert set(_OUTILS_CALCUL) == set(_arguments()) | {"m5_verifier_recu_calcul"}


@pytest.mark.parametrize("nom", _OUTILS_CALCUL)
def test_une_identite_d_appareil_est_refusee_avant_tout_calcul(instance, nom):
    arguments = _arguments().get(nom, {"recu": {}})
    arguments = {k: v for k, v in arguments.items() if k != "autorise_couts"}
    assert _refuse(_appeler(instance, nom, arguments, ADMIN)) == "REJ-IDENTITE-APPAREIL-INVALIDE"


# ---------------------------------------------------------------------- mentions, reçus, rejeu, lecture pure
@pytest.mark.parametrize("nom", sorted(_arguments()))
def test_chaque_sortie_acceptee_porte_les_deux_mentions_et_un_recu_rejoue_identique(instance, nom):
    avant = _vidage(instance["base"])
    corps = _accepte(_appeler(instance, nom, _arguments()[nom]))
    recu = corps["recu"]
    assert recu["mention"] == analyse.MENTION_COMPTABLE and len(recu["empreinte"]) == 64
    verification = _accepte(_appeler(instance, "m5_verifier_recu_calcul", {"recu": recu}))
    assert verification["empreintes_valides"] is True
    if "entrees" in recu:
        assert verification["rejoue"] is True and verification["identique"] is True
        assert verification["empreinte_recalculee"] == recu["empreinte"]
    else:
        assert corps["entrees_omises"] and verification["rejoue"] is False
    second = _accepte(_appeler(instance, nom, _arguments()[nom]))
    assert second["recu"]["empreinte"] == recu["empreinte"], "même appel, même instantané : même empreinte"
    assert _vidage(instance["base"]) == avant, "un outil de calcul n'écrit rien"


def test_un_recu_retouche_est_refuse_par_l_outil_de_verification(instance):
    recu = _accepte(_appeler(instance, "m5_calculer_point_mort", _arguments()["m5_calculer_point_mort"]))["recu"]
    retouche = {**recu, "resultat": {**recu["resultat"], "quantite_entiere": "60"}}
    assert _refuse(_appeler(instance, "m5_verifier_recu_calcul", {"recu": retouche})) == "REJ-CALC-RECU-INVALIDE"


def test_refus_types_passent_par_l_outil(instance):
    arguments = {**_arguments()["m5_calculer_amortissement_pret"], "frequence": "trimestrielle"}
    assert _refuse(_appeler(instance, "m5_calculer_amortissement_pret", arguments)) == "REJ-CALC-FREQUENCE-INCONNUE"
    arguments = {**_arguments()["m5_calculer_rentabilite_investissement"], "objet": "actions_en_bourse"}
    assert _refuse(_appeler(instance, "m5_calculer_rentabilite_investissement", arguments)) == (
        "REJ-CALC-OBJET-HORS-PERIMETRE")
    arguments = {**_arguments()["m5_calculer_rentabilite_investissement"], "flux": []}
    assert _refuse(_appeler(instance, "m5_calculer_rentabilite_investissement", arguments)) == "REJ-CALC-FLUX-VIDES"
    arguments = {**_arguments()["m5_simuler_tresorerie_monte_carlo"], "tirages": 20000}
    assert _refuse(_appeler(instance, "m5_simuler_tresorerie_monte_carlo", arguments)) == "REJ-CALC-BORNE-DEPASSEE"


# ------------------------------------------------------------------------------------------- amortissement
def test_le_tableau_se_lit_par_pages_et_les_pages_reconstituent_l_empreinte_du_recu(instance):
    lignes, depart, recu = [], 0, None
    while depart is not None:
        corps = _accepte(_appeler(instance, "m5_calculer_amortissement_pret",
                                  {**_arguments()["m5_calculer_amortissement_pret"], "depart": depart, "limite": 60}))
        recu = recu or corps["recu"]
        assert corps["recu"]["empreinte"] == recu["empreinte"]
        lignes.extend(corps["lignes"])
        depart = corps["prochain_depart"]
    assert len(lignes) == 300 and lignes[-1]["solde"] == "0.00"
    assert encodage.empreinte("tableau_amortissement", lignes) == recu["resultat"]["empreinte_tableau"]
    assert sum(D(ligne["capital"]) for ligne in lignes) == D("100000.00")
    assert recu["resultat"]["versement"] == "581.60"
    for depart, limite in ((300, 10), (-1, 10), (0, 61), (0, 0)):
        assert _refuse(_appeler(instance, "m5_calculer_amortissement_pret", {
            **_arguments()["m5_calculer_amortissement_pret"], "depart": depart, "limite": limite})) == (
            "REJ-CALC-PAGE-INVALIDE")


# ---------------------------------------------------------------------------------------------- Monte-Carlo
def _solde_fin_prevision(instance):
    page = _accepte_prevision(_appeler(instance, "m5_prevoir_tresorerie",
                                       {"aujourd_hui": "2026-10-01", "autorise_couts": True}))
    return page, [semaine["solde_fin"] for semaine in page["semaines"]]


def _accepte_prevision(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def test_le_monte_carlo_part_de_la_prevision_existante(instance):
    page, soldes = _solde_fin_prevision(instance)
    corps = _accepte(_appeler(instance, "m5_simuler_tresorerie_monte_carlo",
                              _arguments()["m5_simuler_tresorerie_monte_carlo"]))
    recu = corps["recu"]
    colonnes = recu["resultat"]["colonnes"]
    base = [ligne[colonnes.index("solde_base")] for ligne in recu["resultat"]["semaines"]]
    assert base == soldes, "même solde de base que m5_prevoir_tresorerie, semaine par semaine"
    assert recu["entrees"]["prevision_id"] == page["prevision_id"]
    assert recu["entrees"]["solde_initial"] == "9000.00" and recu["entrees"]["seuil"] == "2000.00"
    assert {f["nature"] for f in recu["entrees"]["flux"]} == {"paies", "das"}
    assert recu["parametres"]["graine"] == 20261031 and recu["parametres"]["tirages"] == 400
    assert corps["semaines_simulees"] == 4 and corps["non_calculable_a_partir_de"] is None
    p95 = [D(ligne[colonnes.index("p95")]) for ligne in recu["resultat"]["semaines"]]
    p5 = [D(ligne[colonnes.index("p5")]) for ligne in recu["resultat"]["semaines"]]
    assert all(bas <= haut for bas, haut in zip(p5, p95, strict=True))
    assert "probabilite_au_moins_une_semaine_sous_seuil" in recu["resultat"]


def test_le_monte_carlo_suit_la_vue_des_couts_et_la_console_du_proprietaire(instance):
    arguments = {k: v for k, v in _arguments()["m5_simuler_tresorerie_monte_carlo"].items() if k != "autorise_couts"}
    assert _refuse(_appeler(instance, "m5_simuler_tresorerie_monte_carlo", arguments)) == "REJ-AUTORISE-COUTS-REQUIS"
    assert _refuse(_appeler(instance, "m5_simuler_tresorerie_monte_carlo", {**arguments, "autorise_couts": False})) == (
        "REJ-CALC-COUTS-REQUIS")
    console = _accepte(_appeler(instance, "m5_simuler_tresorerie_monte_carlo", arguments, OWNER_CONSOLE))
    agent = _accepte(_appeler(instance, "m5_simuler_tresorerie_monte_carlo", {**arguments, "autorise_couts": True}))
    assert console["recu"]["empreinte"] == agent["recu"]["empreinte"]


def test_le_monte_carlo_s_arrete_ou_la_prevision_s_arrete(instance):
    """Paies non déclarées mais datées en semaine 3 : la prévision est non calculable dès la semaine 3, la simulation
    couvre les semaines 1 et 2 seulement ; une DAS sans date bloque dès la semaine 1 : refus typé."""
    configuration = _configuration(echeance_paies="2026-10-15")
    del configuration["configuration"]["obligations_declarees"]["paies"]
    instance["manifeste"].write_text(yaml.safe_dump(configuration, allow_unicode=True), encoding="utf-8")
    corps = _accepte(_appeler(instance, "m5_simuler_tresorerie_monte_carlo",
                              _arguments()["m5_simuler_tresorerie_monte_carlo"]))
    assert corps["non_calculable_a_partir_de"] == 3 and corps["semaines_simulees"] == 2
    assert len(corps["recu"]["resultat"]["semaines"]) == 2
    configuration = _configuration()
    del configuration["configuration"]["prevision"]["echeances_obligations"]["das"]
    instance["manifeste"].write_text(yaml.safe_dump(configuration, allow_unicode=True), encoding="utf-8")
    assert _refuse(_appeler(instance, "m5_simuler_tresorerie_monte_carlo",
                            _arguments()["m5_simuler_tresorerie_monte_carlo"])) == "REJ-CALC-PREVISION-NON-CALCULABLE"


def test_vingt_six_semaines_tiennent_dans_une_reponse(instance):
    corps = _accepte(_appeler(instance, "m5_simuler_tresorerie_monte_carlo",
                              {**_arguments()["m5_simuler_tresorerie_monte_carlo"], "horizon_semaines": 26}))
    assert len(corps["recu"]["resultat"]["semaines"]) == 26


# ----------------------------------------------------------------------------------- garde anti-décaissement
def test_la_garde_anti_decaissement_couvre_le_moteur_de_calcul():
    strict = conformite._SURVEILLE_SANS_DECAISSEMENT
    for module in ("maths_financieres", "monte_carlo_tresorerie", "sensibilite", "moteur_calcul", "recu_calcul",
                   "verdicts_calcul"):
        assert strict[module] is None, module
    for fonction in ("calculer_rentabilite_investissement", "calculer_amortissement_pret",
                     "comparer_credit_bail_ou_achat", "calculer_point_mort", "analyser_sensibilite_projet",
                     "verifier_recu_calcul", "_entrees_monte_carlo", "_sortie_calcul", "_outils_calcul"):
        assert fonction in strict["outils"], fonction
    assert "simuler_tresorerie_monte_carlo" in conformite._SURVEILLE_EN_LECTURE_SEULE["outils"]
    repertoire = m5_outils.__file__.rsplit("/", 1)[0]
    assert conformite.verifier_aucun_decaissement(repertoire) == (True, "")
