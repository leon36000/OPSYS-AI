"""M5-PREV-2 sur le VRAI socle : `m5_prevoir_tresorerie_longue` et `m5_rejouer_prevision_longue`.

Base SQLite temporaire migrée, vrais registres durables (mouvements, grand livre, budgets déclarés, échéanciers de
contrats), vrai manifeste de M5 pour les niveaux et le vrai sas N3/N4. Données, personnes et montants FICTIFS
(AGENTS.md) ; aucune valeur d'affaires réelle n'est écrite ici.

Le cas de référence est calculé à la main dans `test_le_cas_fictif_de_bout_en_bout` : solde 20 000,00 $, historique de
six mois à 1 000,00 $ de produits et 800,00 $ de charges, budget d'octobre 1 200,00 $ / 900,00 $, échéance
contractuelle de 1 149,75 $ en novembre. Les soldes attendus sont au cent.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import registre
from sqlalchemy import select, update

from opsys import approbations, contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

FICTIF = True
DEPARTEMENT = "m05-financecore"
_RACINE_M5 = Path(__file__).resolve().parents[1]
AUJOURD_HUI = "2026-09-30"
H = "2026-09-30T17:00:00-04:00"
OWNER = contexte.IdentiteAppelante(personne="nathan.fictif", role="nathan_owner", source="console")
ADMIN_APP = contexte.IdentiteAppelante(personne="admin.fictif", role="admin", source="appareil")

SCENARIO_BASE = {
    "nom": "base",
    "croissance_revenus_mensuelle": "0",
    "croissance_charges_mensuelle": "0",
    "saisonnalite": ["1"] * 12,
    "delai_encaissement_jours": 0,
    "delai_paiement_jours": 0,
}
CONFIGURATION = {
    "prevision_longue": {
        "mois_historique": 6,
        "scenarios": [
            SCENARIO_BASE,
            {
                **SCENARIO_BASE,
                "nom": "prudent",
                "croissance_revenus_mensuelle": "-0.05",
                "delai_encaissement_jours": 45,
            },
        ],
    }
}
MOIS_HISTORIQUE = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-prevision-longue.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan.fictif", "Nathan Fictif", "mot-de-passe-nathan-1234",
                                ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "comptable.fictive", "Comptable Fictive", "mot-de-passe-compta-1234",
                                ["finance", "admin"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
    yield url
    stockage.liberer()


@pytest.fixture
def dep():
    return lire_manifeste(_RACINE_M5)


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


@pytest.fixture
def declare(tmp_path, monkeypatch):
    def _declarer(configuration):
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)

    _declarer(CONFIGURATION)
    return _declarer


def appeler(par_nom, nom, arguments, identite_appelante=None):
    outil = par_nom[nom]
    if identite_appelante is None:
        return executer_atomique(outil, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(outil, arguments)


def utile(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def decider(dep, nom, arguments, *, par="nathan.fictif"):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    reponse = capacites.appeler(nom, arguments)
    assert reponse["statut"] == "en_attente_approbation", reponse
    disponibles = outils_executables({DEPARTEMENT: dep}, stockage.transaction)
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, reponse["demande_id"], True, par, disponibles, {DEPARTEMENT: dep})


def registre_durable(nom):
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, nom))


def altérer(nom_registre, modification):
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == nom_registre)
    with stockage.transaction() as cnx:
        ligne = codec.decoder(
            cnx.execute(select(REGISTRES.c.maillon).where(filtre).order_by(REGISTRES.c.rang.desc())).scalars().first()
        )
        modification(ligne)
        cnx.execute(
            update(REGISTRES)
            .where(filtre & (REGISTRES.c.rang == len(registre_durable(nom_registre)) - 1))
            .values(maillon=codec.encoder(ligne))
        )


def ecriture(par_nom, dep, ref, jour, lignes):
    """Une écriture manuelle (brouillon N1) puis sa validation par la finance (N4)."""
    proposee = utile(
        appeler(
            par_nom,
            "m5_proposer_ecriture_comptable",
            {
                "date_effet": jour,
                "libelle": f"Écriture {ref} (fictive)",
                "piece_type": "manuelle",
                "piece_reference": ref,
                "lignes": lignes,
                "horodatage": H,
            },
        )
    )
    ident = proposee["ecriture"]["ecriture_id"]
    decision = decider(dep, "m5_valider_ecriture_comptable", {"ecriture_id": ident, "horodatage": H},
                       par="comptable.fictive")
    assert decision["statut"] == "executee", decision
    return ident


def _peupler_mouvement(montant="20000.00"):
    with stockage.transaction():
        registre.enregistrer_mouvement({
            "montant": Decimal(montant), "type_mouvement": "ENCAISSEMENT",
            "horodatage": "2026-09-30T12:00:00-04:00", "classe_retention": "STANDARD",
            "source": "solde initial fictif",
        }, m5_outils._registre_mouvements(None))


def _peupler_historique(par_nom, dep, produits="1000.00", charges="800.00"):
    for mois in MOIS_HISTORIQUE:
        ecriture(
            par_nom, dep, f"HIST-{mois}", f"{mois}-15",
            [
                {"compte": "1010", "debit": produits, "credit": None},
                {"compte": "4100", "debit": None, "credit": produits},
                {"compte": "5100", "debit": charges, "credit": None},
                {"compte": "1010", "debit": None, "credit": charges},
            ],
        )


def _declarer_budget(dep):
    decision = decider(
        dep,
        "m5_etablir_budget",
        {
            "libelle": "Budget fictif 2026-10",
            "lignes": [
                {"compte": "4100", "mois": "2026-10", "montant": "1200.00"},
                {"compte": "5100", "mois": "2026-10", "montant": "900.00"},
            ],
            "motif": None,
            "version_attendue": 0,
            "horodatage": H,
        },
    )
    assert decision["statut"] == "executee", decision


def _devis():
    with stockage.transaction():
        resultat = m5_outils._recevoir_devis_accepte({
            "devis_id": "DEVIS-PREV-LONGUE",
            "lead_id": "LEAD-1",
            "chantier_id": "CHANTIER-1",
            "lignes": [{"description": "travaux fictifs", "quantite": "1", "unite": "u",
                        "prix_unitaire": "1000.00", "reference_ligne": "L-1"}],
            "prix_total": "1000.00",
            "horodatage_acceptation": "2026-09-20T12:00:00-04:00",
        })
        assert resultat["statut"] == "en_attente_travaux_termines", resultat


def _contrat(par_nom):
    _devis()
    reponse = appeler(
        par_nom,
        "m5_enregistrer_echeancier_contrat",
        {
            "contrat_id": "CTR-PREV-LONGUE",
            "devis_id": "DEVIS-PREV-LONGUE",
            "prix_ht": "1000.00",
            "prix_ttc": "1149.75",
            "devise": "CAD",
            "source_humaine": "Pièce contractuelle fictive C-PREV",
            "date_source": "2026-09-21",
            "couverture_jusquau": "2027-03-31",
            "echeances": [{"date": "2026-11-15", "montant_ttc": "1149.75"}],
            "revision_attendue": 0,
            "ligne_id_attendue": "",
            "motif": "Saisie humaine fictive",
        },
        OWNER,
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


@pytest.fixture
def cas_fictif(par_nom, dep, declare):
    _peupler_mouvement()
    _peupler_historique(par_nom, dep)
    _declarer_budget(dep)
    _contrat(par_nom)


# ================================================================================== 1. le parcours de bout en bout
def test_le_cas_fictif_de_bout_en_bout(par_nom, cas_fictif):
    """Octobre 1200-900=300 ; novembre 1149,75-800=349,75 ; décembre à mars 200 chacun.

    20 000 + 300 = 20 300 ; + 349,75 = 20 649,75 ; puis 4 × 200 = 21 449,75.
    """
    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base"}))

    assert page["type"] == "PREVISION_LONGUE" and page["statut"] == "BROUILLON"
    assert page["solde_initial"] == "20000.00"
    assert page["premier_mois"] == "2026-10" and page["dernier_mois"] == "2027-03"
    assert [ligne["solde_projete"] for ligne in page["scenario"]["lignes"]] == [
        "20300.00", "20649.75", "20849.75", "21049.75", "21249.75", "21449.75"
    ]
    octobre, novembre = page["scenario"]["lignes"][0], page["scenario"]["lignes"][1]
    assert octobre["sources_produits"] == ["budget"]
    assert novembre["sources_produits"] == ["carnet"]
    assert page["couverture"]["budget_produits_ignores_montant"] == "0.00"
    assert "comptable (CPA)" in page["mention_comptable"]
    assert page["scenario"]["hypotheses"]["nom"] == "base"
    assert len(page["scenario"]["lignes"]) == 6


def test_le_resume_des_scenarios_est_compact_et_le_detail_est_pagine(par_nom, cas_fictif):
    resume = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                           {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}))
    assert "scenario" not in resume
    assert [s["nom"] for s in resume["scenarios"]] == ["base", "prudent"]
    assert resume["scenarios"][0]["solde_final"] == "21449.75"
    assert all("lignes" not in s for s in resume["scenarios"])

    detail = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                           {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base",
                            "depart": 2, "limite": 2}))
    assert [ligne["mois"] for ligne in detail["scenario"]["lignes"]] == ["2026-12", "2027-01"]
    assert detail["scenario"]["lignes_total"] == 6
    assert detail["scenario"]["prochain_depart"] == 4


def test_le_recu_complet_se_rejoue_par_l_outil_et_une_retouche_est_refusee(par_nom, cas_fictif):
    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base"}))
    assert "entrees" not in page["recu"] and page["entrees_omises"]
    compact = utile(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": page["recu"]}))
    assert compact["recu_valide"] is True and compact["rejoue"] is False and compact["note"]

    complet = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base",
                             "recu_complet": True}))
    recu = complet["recu"]
    verification = utile(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": recu}))
    assert verification["recu_valide"] is True and verification["rejoue"] is True

    retouche = {**recu, "resultat": {**recu["resultat"], "solde_final": "999999.99"}}
    assert refus(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": retouche}))["code"] == (
        "REJ-PREVISION-LONGUE-RECU-INVALIDE"
    )


def test_les_sources_citees_sont_les_vrais_registres_lus(par_nom, cas_fictif):
    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base"}))
    noms = {source["registre"] for source in page["sources"]}
    assert {"mouvements", "grand_livre", "budgets_declares", "echeanciers_contrats_tresorerie"} <= noms
    assert all(source["taille"] >= 1 and source["tete"] for source in page["sources"])


# ================================================================================== 2. accès et fail-closed
def test_la_portee_d_appareil_est_fermee(par_nom, cas_fictif):
    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}, ADMIN_APP))
    assert verdict["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_sans_configuration_l_outil_dit_quoi_declarer(par_nom, cas_fictif, declare):
    declare({})
    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-A-DECLARER"
    assert "configuration.prevision_longue" in verdict["detail"]


def test_un_scenario_inconnu_ou_un_horizon_interdit_est_refuse(par_nom, cas_fictif):
    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "optimiste"}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-SCENARIO-INCONNU"

    reponse = appeler(par_nom, "m5_prevoir_tresorerie_longue",
                      {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 7})
    assert reponse["ok"] is False and "horizon_mois" in " ".join(reponse["details"])


def test_un_grand_livre_altere_est_refuse(par_nom, cas_fictif):
    altérer("grand_livre", lambda ligne: ligne.update(libelle="Libellé retouché à la main"))
    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-CHAINE-INVALIDE"


def test_un_budget_altere_est_refuse(par_nom, cas_fictif):
    altérer("budgets_declares", lambda ligne: ligne["lignes"][0].update(montant="99999.00"))
    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-CHAINE-INVALIDE"


def test_un_contrat_sans_couverture_complete_est_exclu_et_dit(par_nom, cas_fictif):
    """La couverture du contrat s'arrête avant l'horizon : il est bloqué, jamais tronqué ni supposé complet."""
    ligne_id = registre_durable("echeanciers_contrats_tresorerie")[-1]["ligne_id"]
    revision = appeler(
        par_nom,
        "m5_enregistrer_echeancier_contrat",
        {
            "contrat_id": "CTR-PREV-LONGUE", "devis_id": "DEVIS-PREV-LONGUE", "prix_ht": "1000.00",
            "prix_ttc": "1149.75", "devise": "CAD", "source_humaine": "Pièce contractuelle fictive C-PREV",
            "date_source": "2026-09-21", "couverture_jusquau": "2026-12-31",
            "echeances": [{"date": "2026-11-15", "montant_ttc": "1149.75"}],
            "revision_attendue": 1, "ligne_id_attendue": ligne_id, "motif": "Révision fictive de couverture",
        },
        OWNER,
    )
    assert revision["ok"] is True and revision["resultat"]["accepte"] is True, revision
    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base"}))
    assert page["couverture"]["carnet_incomplet"] is True
    assert page["couverture"]["contrats_bloques"] == ["REJ-CONTRAT-COUVERTURE-INCOMPLETE"]
    assert page["scenario"]["lignes"][1]["contrats"] == "0.00"


def test_les_outils_sont_declares_t0_sans_appareil_et_en_sortie_d_analyse(par_nom):
    from m5_financecore import analyse

    for nom in ("m5_prevoir_tresorerie_longue", "m5_rejouer_prevision_longue"):
        outil = par_nom[nom]
        assert outil.autonomie is Autonomie.T0
        assert outil.niveau is None or outil.niveau is Niveau.N0
        assert outil.roles_appareil == frozenset()
        assert nom in analyse.SORTIES_PREVISION_LONGUE


def test_les_modules_sont_couverts_par_la_garde_anti_decaissement():
    from m5_financecore import conformite

    racine = _RACINE_M5 / "src" / "m5_financecore"
    assert "prevision_longue" in conformite._SURVEILLE_SANS_DECAISSEMENT
    assert "verdicts_prevision_longue" in conformite._SURVEILLE_SANS_DECAISSEMENT
    assert "outils_prevision_longue" in conformite._SURVEILLE_EN_LECTURE_SEULE
    assert conformite.verifier_aucun_decaissement(racine) == (True, "")
