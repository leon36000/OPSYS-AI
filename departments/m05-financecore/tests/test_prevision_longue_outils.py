"""M5-PREV-2 sur le VRAI socle : `m5_prevoir_tresorerie_longue` et `m5_rejouer_prevision_longue`.

Base SQLite temporaire migrée, vrais registres durables (mouvements, grand livre, budgets déclarés, échéanciers de
contrats), vrai manifeste de M5 pour les niveaux et le vrai sas N3/N4. Données, personnes et montants FICTIFS
(AGENTS.md) ; aucune valeur d'affaires réelle n'est écrite ici.

Le cas de référence est calculé à la main dans `test_le_cas_fictif_de_bout_en_bout` : solde 20 000,00 $, historique de
six mois à 1 000,00 $ de produits et 800,00 $ de charges, budget d'octobre 1 200,00 $ / 900,00 $, échéance
contractuelle de 1 149,75 $ en novembre. Les soldes attendus sont au cent.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import outils_prevision_longue as outil_previsions
from m5_financecore import prevision_longue, rapports_financiers, recu_calcul, registre
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
    assert {"mouvements", "grand_livre", "budgets_declares", "echeanciers_contrats_tresorerie",
            "devis_recus", "factures"} == noms
    assert all(source["taille"] >= 0 for source in page["sources"])
    tetes = [source["tete"] for source in page["sources"]
             if source["registre"] != "devis_recus" and source["taille"]]
    assert tetes and all(len(tete) == 8 for tete in tetes)


# ================================================================================== 2. accès et fail-closed
def test_la_portee_d_appareil_est_fermee(par_nom, cas_fictif):
    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}, ADMIN_APP))
    assert verdict["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    verdict_transport = refus(appeler(
        par_nom, "m5_prevoir_tresorerie_longue",
        {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "transport_pagine": True}, ADMIN_APP,
    ))
    assert verdict_transport["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


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
    assert page["couverture"].get("devis_sans_echeancier", 0) == 0
    assert page["couverture"]["incompletude"]
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


@pytest.mark.parametrize("aujourd_hui", ["2999-12-31", "9999-12-01"])
def test_l_outil_refuse_une_fenetre_hors_plage_avant_de_lire_l_historique(
    par_nom, cas_fictif, aujourd_hui, monkeypatch
):
    from m5_financecore import outils_prevision_longue

    appels = []
    original = outils_prevision_longue._lire_historique

    def noter_lecture(*arguments):
        appels.append(True)
        return original(*arguments)

    monkeypatch.setattr(outils_prevision_longue, "_lire_historique", noter_lecture)
    verdict = refus(appeler(
        par_nom, "m5_prevoir_tresorerie_longue", {"aujourd_hui": aujourd_hui, "horizon_mois": 6}
    ))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-DATE-INVALIDE"
    assert not appels


# ========================================================== 4. relecture M5 : moteur, provenance, reçu
def test_un_recu_compact_d_un_autre_moteur_est_refuse_par_l_outil_de_rejeu(par_nom, cas_fictif):
    """Un vrai reçu compact de `m5_etat_des_resultats` n'est pas un reçu de prévision longue : refus typé."""
    rapport = utile(appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-03-01", "fin": "2026-08-31"}))
    compact = {cle: valeur for cle, valeur in rapport["recu"].items() if cle != "entrees"}
    assert compact["moteur"] == "etat_des_resultats"

    verdict = refus(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": compact}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-RECU-INVALIDE"
    assert "moteur" in verdict["detail"] or "version" in verdict["detail"]


def test_un_recu_complet_d_un_autre_moteur_est_refuse_comme_recu_et_non_comme_rejeu(par_nom, cas_fictif):
    """Un vrai reçu complet d'un autre moteur est refusé sur son en-tête, pas exécuté puis déclaré « différent »."""
    recu = rapports_financiers.calculer_etat_des_resultats(
        {
            "debut": "2026-03-01", "fin": "2026-08-31", "comptes": [], "couts_directs": None,
            "ecritures_definitives": 1, "brouillons": 0, "periode_close": False,
            "plan_comptable_version": "1.0.0", "sources": [],
        },
        {"debut": "2026-03-01", "fin": "2026-08-31"},
    )["recu"]
    assert "entrees" in recu and recu["moteur"] == "etat_des_resultats"

    verdict = refus(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": recu}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-RECU-INVALIDE"
    assert "moteur" in verdict["detail"] or "version" in verdict["detail"]


def test_un_recu_du_meme_moteur_reempreinte_avec_un_autre_moteur_ou_version_est_refuse(par_nom, cas_fictif):
    """Les empreintes recalculées prouvent l'intégrité, jamais l'appartenance au moteur : l'outil refuse l'en-tête."""
    complet = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "recu_complet": True}))
    recu = complet["recu"]
    for moteur, version in (("autre_moteur", prevision_longue.VERSION),
                            (prevision_longue.MOTEUR, "9.9.9")):
        faux = prevision_longue.recu_calcul.construire(
            moteur=moteur, version_moteur=version, methode=recu["methode"], precision=recu["precision"],
            parametres=recu["parametres"], entrees=recu["entrees"], resultat=recu["resultat"],
            avertissements=recu["avertissements"],
        )
        assert prevision_longue.recu_calcul.verifier(faux) == (True, "")
        verdict = refus(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": faux}))
        assert verdict["code"] == "REJ-PREVISION-LONGUE-RECU-INVALIDE"
        assert "moteur" in verdict["detail"] or "version" in verdict["detail"]


def test_un_recu_compact_du_meme_moteur_reste_verifiable_sans_etre_rejoue(par_nom, cas_fictif):
    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base"}))
    compact = page["recu"]
    assert "entrees" not in compact
    verification = utile(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": compact}))
    assert verification["recu_valide"] is True
    assert verification["rejoue"] is False
    assert verification["note"]
    assert "état courant" in verification["portee"]


def test_un_recu_ne_revalide_pas_l_etat_courant_des_registres(par_nom, cas_fictif):
    """Le reçu atteste le calcul de ses entrées normalisées. Une facture active créée ensuite bloque le contrat
    dans une NOUVELLE projection, sans invalider le reçu déjà émis : la portée le dit explicitement."""
    complet = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "recu_complet": True}))
    recu = complet["recu"]
    facture = utile(appeler(par_nom, "m5_creer_facture_brouillon", {
        "facture_id": "FAC-APRES-RECU-1", "chantier_id": "CHANTIER-1", "devis_id": "DEVIS-PREV-LONGUE",
        "client_id": "LEAD-1",
        "lignes": [{"description": "acompte fictif", "quantite": "1", "unite": "u",
                    "prix_unitaire": "1000.00", "reference_ligne_devis": "L-1"}],
        "horodatage": H,
    }))
    assert facture["facture_id"] == "FAC-APRES-RECU-1"

    verification = utile(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": recu}))
    assert verification["recu_valide"] is True and verification["rejoue"] is True
    assert "état courant" in verification["portee"]

    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base"}))
    assert page["couverture"]["carnet_incomplet"] is True
    assert "REJ-CONTRAT-FACTURE-EXISTANTE" in page["couverture"]["contrats_bloques"]


def test_un_devis_recus_altere_avec_un_echeancier_actif_est_refuse(par_nom, cas_fictif):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == DEPARTEMENT,
            REGISTRES.c.registre == "devis_recus",
            REGISTRES.c.rang == 0,
        )).one()
        devis = codec.decoder(ligne.maillon)
        devis["devis_id"] = ["liste-non-hashable"]
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == DEPARTEMENT,
            REGISTRES.c.registre == "devis_recus",
            REGISTRES.c.rang == 0,
        ).values(maillon=codec.encoder(devis)))

    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-CARNET-INVALIDE"
    assert "devis" in verdict["detail"]


def test_un_maillon_devis_qui_n_est_pas_un_objet_est_refuse(par_nom, cas_fictif):
    with stockage.transaction():
        stockage.maillons(DEPARTEMENT, "devis_recus").append("pas-un-objet")
    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-CARNET-INVALIDE"
    assert "structure" in verdict["detail"]


def test_un_devis_contradictoire_lie_a_un_echeancier_actif_est_refuse(par_nom, cas_fictif):
    """Deux événements pour le même devis, dont un prix total contradictoire, alors qu'un contrat actif le référence."""
    with stockage.transaction():
        stockage.maillons(DEPARTEMENT, "devis_recus").append({
            "devis_id": "DEVIS-PREV-LONGUE", "lead_id": "LEAD-1", "chantier_id": "CHANTIER-1",
            "lignes": [], "prix_total": "9999.00",
            "horodatage_acceptation": "2026-09-21T12:00:00-04:00",
        })

    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                            {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-CARNET-INVALIDE"
    assert "plusieurs" in verdict["detail"]


def test_un_devis_sans_echeancier_est_dit_sans_etre_confondu_avec_un_contrat_bloque(par_nom, cas_fictif):
    with stockage.transaction():
        m5_outils._recevoir_devis_accepte({
            "devis_id": "DEVIS-SANS-CONTRAT-FICTIF", "lead_id": "LEAD-2", "chantier_id": "CHANTIER-2",
            "lignes": [{"description": "travaux fictifs", "quantite": "1", "unite": "u",
                        "prix_unitaire": "1000.00", "reference_ligne": "L-2"}],
            "prix_total": "1000.00", "horodatage_acceptation": "2026-09-20T12:00:00-04:00",
        })

    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6}))
    couverture = page["couverture"]
    assert couverture["carnet_incomplet"] is True
    assert couverture["devis_sans_echeancier"] == 1
    assert couverture.get("contrats_bloques", []) == []
    assert couverture["incompletude"] and "sans échéancier" in couverture["incompletude"][0]
    # Aucun identifiant de devis ni texte libre dans la couverture.
    assert "DEVIS-SANS-CONTRAT-FICTIF" not in json.dumps(couverture, ensure_ascii=False)


def test_les_sources_incluent_toutes_les_sources_decisives_sans_donnees_personnelles(par_nom, cas_fictif):
    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base"}))
    sources = page["sources"]
    assert {source["registre"] for source in sources} == {
        "mouvements", "grand_livre", "budgets_declares", "echeanciers_contrats_tresorerie",
        "devis_recus", "factures",
    }
    rendu = json.dumps(sources, ensure_ascii=False)
    for interdit in ("DEVIS-PREV-LONGUE", "LEAD-1", "CHANTIER-1", "Pièce contractuelle"):
        assert interdit not in rendu
    assert all(source["taille"] >= 0 for source in sources)


def test_un_recu_complet_avec_scenario_inconnu_est_refuse_par_l_outil_public(par_nom, cas_fictif):
    verdict = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
        "aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "scenario_inexistant",
        "recu_complet": True,
    }))
    assert verdict["code"] == "REJ-PREVISION-LONGUE-SCENARIO-INCONNU"


def test_un_recu_complet_avec_scenario_valide_rend_le_meme_recu(par_nom, cas_fictif):
    """Contrat existant explicité : en mode reçu complet, un scénario VALIDE ne change pas le reçu (il n'y a pas de
    lignes à filtrer) ; il est seulement validé. Un scénario inconnu est refusé, jamais ignoré."""
    sans = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue",
                         {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "recu_complet": True}))
    avec = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
        "aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base", "recu_complet": True,
    }))
    assert avec["recu"] == sans["recu"]
    assert avec["recu"]["moteur"] == "prevision_longue"
    assert avec["recu"]["version_moteur"] == prevision_longue.VERSION


def test_un_recu_complet_trop_gros_est_refuse_sans_troncature(par_nom, dep, declare):
    scenarios = [
        {**SCENARIO_BASE, "nom": f"scenario_{i}", "saisonnalite": ["1.25"] * 12}
        for i in range(1, 5)
    ]
    declare({"prevision_longue": {"mois_historique": 6, "scenarios": scenarios}})
    _peupler_mouvement()
    _peupler_historique(par_nom, dep)
    lignes_budget = []
    for annee, mois_liste in ((2026, range(10, 13)), (2027, range(1, 13)), (2028, range(1, 10))):
        for m in mois_liste:
            lignes_budget.append({"compte": "4100", "mois": f"{annee:04d}-{m:02d}", "montant": "1200.00"})
            lignes_budget.append({"compte": "5100", "mois": f"{annee:04d}-{m:02d}", "montant": "900.00"})
    assert decider(dep, "m5_etablir_budget", {
        "libelle": "Budget fictif 24 mois", "lignes": lignes_budget, "motif": None,
        "version_attendue": 0, "horodatage": H,
    })["statut"] == "executee"

    for idx in range(1, 6):
        with stockage.transaction():
            m5_outils._recevoir_devis_accepte({
                "devis_id": f"DEVIS-GROS-{idx}", "lead_id": f"LEAD-{idx}", "chantier_id": f"CHANTIER-{idx}",
                "lignes": [{"description": "travaux fictifs", "quantite": "1", "unite": "u",
                            "prix_unitaire": "8000.00", "reference_ligne": "L-1"}],
                "prix_total": "8000.00", "horodatage_acceptation": "2026-09-20T12:00:00-04:00",
            })
        enreg = appeler(par_nom, "m5_enregistrer_echeancier_contrat", {
            "contrat_id": f"CONTRAT-LONGUE-IDENTIFIANT-{idx:02d}", "devis_id": f"DEVIS-GROS-{idx}",
            "prix_ht": "8000.00", "prix_ttc": "9198.00", "devise": "CAD",
            "source_humaine": "Contrat fictif", "date_source": "2026-09-21",
            "couverture_jusquau": "2028-09-30",
            "echeances": [{"date": f"2027-0{m}-15", "montant_ttc": "1149.75"} for m in range(1, 9)],
            "revision_attendue": 0, "ligne_id_attendue": "", "motif": "Saisie fictive",
        }, OWNER)
        assert enreg["ok"] is True and enreg["resultat"]["accepte"] is True

    reponse = appeler(par_nom, "m5_prevoir_tresorerie_longue", {
        "aujourd_hui": AUJOURD_HUI, "horizon_mois": 24, "recu_complet": True,
    })
    verdict = refus(reponse)
    assert verdict["code"] == "REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE"
    assert "recu" not in reponse["resultat"]


# ================================================================================== pagination du résumé
BORNE_REPONSE = 5300
_NOMS_LEGAUX = [f"scenario_legal_{i:02d}_" + "x" * 22 for i in range(1, 5)]


def _mois_avant(aujourd_hui: str, nombre: int) -> list[str]:
    jour = date.fromisoformat(aujourd_hui)
    index = jour.year * 12 + jour.month - 1
    return [f"{(index - d) // 12:04d}-{(index - d) % 12 + 1:02d}" for d in range(nombre, 0, -1)]


def _mois_apres(aujourd_hui: str, nombre: int) -> list[str]:
    jour = date.fromisoformat(aujourd_hui)
    index = jour.year * 12 + jour.month - 1
    return [f"{(index + d) // 12:04d}-{(index + d) % 12 + 1:02d}" for d in range(1, nombre + 1)]


def _peupler_historique_mois(par_nom, dep, mois_liste):
    for mois in mois_liste:
        ecriture(
            par_nom, dep, f"HIST-{mois}", f"{mois}-15",
            [
                {"compte": "1010", "debit": "1000.00", "credit": None},
                {"compte": "4100", "debit": None, "credit": "1000.00"},
                {"compte": "5100", "debit": "800.00", "credit": None},
                {"compte": "1010", "debit": None, "credit": "800.00"},
            ],
        )


def _pages_resume(par_nom, arguments):
    page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue", dict(arguments)))
    pages = [page]
    while page["prochain_depart"] is not None:
        assert len(pages) <= 8, "la pagination du résumé doit être bornée et strictement croissante"
        page = utile(appeler(
            par_nom, "m5_prevoir_tresorerie_longue", {**arguments, "depart": page["prochain_depart"]}
        ))
        pages.append(page)
    return pages


def _taille_reponse(page) -> int:
    return len(json.dumps(page, ensure_ascii=False, default=str))


def test_le_resume_de_quatre_scenarios_est_pagine_sous_la_borne(par_nom, cas_fictif, declare):
    """Quatre scénarios déclarés : le résumé sans `scenario` reste consultable, page par page, sous 5 300.

    Chaque page porte le total et la suite ; le reçu compact reste identique et contient les quatre scénarios.
    """
    noms = [f"s{i}_xxxxx" for i in range(1, 5)]
    declare({"prevision_longue": {"mois_historique": 6, "scenarios": [{**SCENARIO_BASE, "nom": nom} for nom in noms]}})

    pages = _pages_resume(par_nom, {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6})
    assert len(pages) >= 2, "quatre scénarios ne doivent pas être rendus en une seule réponse de plus de 5 300"
    assert pages[0]["scenarios_affiches"] >= 2, "la page doit être la plus grande qui tient sous la borne"

    vus = []
    recus = set()
    for page in pages:
        assert page["scenarios_total"] == 4
        assert page["scenarios_depart"] == len(vus)
        assert page["scenarios_affiches"] == len(page["scenarios"])
        assert 1 <= page["scenarios_affiches"] <= 4
        assert _taille_reponse(page) <= BORNE_REPONSE
        assert page["limites"] and page["sources"] and page["couverture"]["carnet_incomplet"] is False
        assert page["recu"]["moteur"] == "prevision_longue" and page["recu"]["version_moteur"] == "1.0.0"
        assert [s["nom"] for s in page["recu"]["resultat"]["scenarios"]] == noms
        attendu = len(vus) + len(page["scenarios"])
        assert page["prochain_depart"] == (attendu if attendu < 4 else None)
        vus.extend(s["nom"] for s in page["scenarios"])
        recus.add(json.dumps(page["recu"], sort_keys=True, ensure_ascii=False, default=str))

    assert vus == noms
    assert len(set(vus)) == 4
    assert len(recus) == 1, "le reçu ne change pas d'une page à l'autre"

    rejeu = utile(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": pages[0]["recu"]}))
    assert rejeu["recu_valide"] is True and rejeu["rejoue"] is False and rejeu["note"]

    complet = utile(appeler(
        par_nom, "m5_prevoir_tresorerie_longue",
        {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "recu_complet": True},
    ))
    assert [s["nom"] for s in complet["recu"]["resultat"]["scenarios"]] == noms
    rejeu_complet = utile(appeler(par_nom, "m5_rejouer_prevision_longue", {"recu": complet["recu"]}))
    assert rejeu_complet["recu_valide"] is True and rejeu_complet["rejoue"] is True


@pytest.mark.parametrize("nombre", [1, 2, 3, 4])
def test_le_resume_d_un_a_quatre_scenarios_avec_noms_legaux_est_complet(par_nom, cas_fictif, declare, nombre):
    """1 à 4 scénarios, noms légaux de 40 caractères, horizon 24 : toutes les pages sont complètes, sans doublon."""
    noms = _NOMS_LEGAUX[:nombre]
    assert all(len(nom) == 40 for nom in noms)
    declare({"prevision_longue": {"mois_historique": 6, "scenarios": [{**SCENARIO_BASE, "nom": nom} for nom in noms]}})

    pages = _pages_resume(par_nom, {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 24})
    vus = []
    for page in pages:
        assert page["scenarios_total"] == nombre
        assert page["scenarios_depart"] == len(vus)
        assert page["scenarios_affiches"] == len(page["scenarios"])
        assert _taille_reponse(page) <= BORNE_REPONSE
        assert page["limites"] and page["sources"]
        attendu = len(vus) + len(page["scenarios"])
        assert page["prochain_depart"] == (attendu if attendu < nombre else None)
        vus.extend(s["nom"] for s in page["scenarios"])

    assert vus == noms
    assert len(set(vus)) == nombre


def test_le_resume_avec_historique_et_horizon_maximaux_et_noms_legaux_reste_complet(par_nom, dep, declare):
    """Entrées maximales : 24 mois d'historique, horizon 24, budget 24 mois, 4 scénarios de 40 caractères."""
    noms = _NOMS_LEGAUX
    declare({"prevision_longue": {"mois_historique": 24, "scenarios": [{**SCENARIO_BASE, "nom": nom} for nom in noms]}})
    _peupler_mouvement()
    _peupler_historique_mois(par_nom, dep, _mois_avant(AUJOURD_HUI, 24))
    lignes_budget = []
    for mois in _mois_apres(AUJOURD_HUI, 24):
        lignes_budget.append({"compte": "4100", "mois": mois, "montant": "1200.00"})
        lignes_budget.append({"compte": "5100", "mois": mois, "montant": "900.00"})
    assert decider(dep, "m5_etablir_budget", {
        "libelle": "Budget fictif 24 mois (pagination du résumé)", "lignes": lignes_budget, "motif": None,
        "version_attendue": 0, "horodatage": H,
    })["statut"] == "executee"
    _contrat(par_nom)

    pages = _pages_resume(par_nom, {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 24})
    vus = []
    for page in pages:
        assert page["scenarios_total"] == 4
        assert page["scenarios_depart"] == len(vus)
        assert page["scenarios_affiches"] == len(page["scenarios"])
        assert _taille_reponse(page) <= BORNE_REPONSE
        assert page["limites"] and page["sources"]
        attendu = len(vus) + len(page["scenarios"])
        assert page["prochain_depart"] == (attendu if attendu < 4 else None)
        vus.extend(s["nom"] for s in page["scenarios"])

    assert vus == noms
    assert len(set(vus)) == 4


def test_le_resume_avec_limite_3_et_depart_hors_borne_reste_trace(par_nom, cas_fictif, declare):
    """`limite=3` réduit explicitement la page ; un `depart` hors borne rend une page vide tracée, jamais une erreur."""
    noms = [f"s{i}_xxxxx" for i in range(1, 5)]
    declare({"prevision_longue": {"mois_historique": 6, "scenarios": [{**SCENARIO_BASE, "nom": nom} for nom in noms]}})

    page = utile(appeler(
        par_nom, "m5_prevoir_tresorerie_longue",
        {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "limite": 3},
    ))
    assert page["scenarios_total"] == 4
    assert 1 <= page["scenarios_affiches"] <= 3
    assert page["scenarios_affiches"] == len(page["scenarios"])
    assert page["prochain_depart"] == (page["scenarios_affiches"] if page["scenarios_affiches"] < 4 else None)
    assert _taille_reponse(page) <= BORNE_REPONSE

    suite = utile(appeler(
        par_nom, "m5_prevoir_tresorerie_longue",
        {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "depart": page["prochain_depart"]},
    ))
    assert suite["scenarios_depart"] == page["prochain_depart"]
    assert suite["scenarios_total"] == 4
    assert _taille_reponse(suite) <= BORNE_REPONSE

    hors = utile(appeler(
        par_nom, "m5_prevoir_tresorerie_longue",
        {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "depart": 99},
    ))
    assert hors["scenarios"] == []
    assert hors["scenarios_total"] == 4
    assert hors["scenarios_depart"] == 99
    assert hors["scenarios_affiches"] == 0
    assert hors["prochain_depart"] is None
    assert hors["limites"] and hors["sources"] and "recu" in hors


def test_un_resume_impossible_est_refuse_sans_troncature(par_nom, cas_fictif, declare, monkeypatch):
    """Même un seul résumé ne tient pas (avertissement exceptionnellement long) : refus nommé, aucune page partielle."""
    noms = [f"s{i}_xxxxx" for i in range(1, 5)]
    declare({"prevision_longue": {"mois_historique": 6, "scenarios": [{**SCENARIO_BASE, "nom": nom} for nom in noms]}})
    limites_originales = prevision_longue.limites
    monkeypatch.setattr(
        prevision_longue, "limites", lambda: [*limites_originales(), "avertissement fictif " + "x" * 6000]
    )

    reponse = appeler(par_nom, "m5_prevoir_tresorerie_longue", {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6})
    verdict = refus(reponse)
    assert verdict["code"] == "REJ-PREVISION-LONGUE-REPONSE-TROP-GROSSE"
    assert set(reponse["resultat"]) == {"accepte", "verdict"}
    assert "scenarios" not in reponse["resultat"]

    arguments = {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "transport_pagine": True}
    fragments = []
    empreinte = offset = None
    for _ in range(100):
        curseur = {} if empreinte is None else {"empreinte_resultat": empreinte, "offset_transport": offset}
        page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue", {**arguments, **curseur}))
        fragments.append(page["fragment"])
        empreinte, offset = page["empreinte_resultat"], page["prochain_offset"]
        if offset is None:
            break
    else:
        pytest.fail("pagination transport sans terminaison")
    reconstitue = json.loads("".join(fragments))
    assert [s["nom"] for s in reconstitue["scenarios"]] == noms
    assert "avertissement fictif " + "x" * 6000 in reconstitue["limites"]
    assert reconstitue["sources"] and reconstitue["couverture"]
    assert recu_calcul.verifier(reconstitue["recu"])[0] is True


def test_transport_pagine_est_additif_et_reconstruit_exactement_le_recu(par_nom, cas_fictif):
    legacy = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
        "aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base", "limite": 6,
    }))
    args = {
        "aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base", "limite": 6,
        "transport_pagine": True,
    }
    pages = []
    fingerprint = None
    offset = None
    for _ in range(100):
        page = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
            **args,
            **({} if fingerprint is None else {"empreinte_resultat": fingerprint, "offset_transport": offset}),
        }))
        assert len(json.dumps(page, ensure_ascii=False, default=str)) <= 5300
        fingerprint = page["empreinte_resultat"]
        pages.append(page["fragment"])
        offset = page["prochain_offset"]
        if offset is None:
            break
    else:
        pytest.fail("pagination transport sans terminaison")
    reconstruit = "".join(pages)
    reconstruit_obj = json.loads(reconstruit)
    assert reconstruit_obj == legacy
    assert "entrees" not in reconstruit_obj["recu"]  # le mode normal garde exactement le reçu compact public
    assert recu_calcul.verifier(reconstruit_obj["recu"])[0] is True
    assert reconstruit_obj["couverture"] == legacy["couverture"]
    assert reconstruit_obj["limites"] == legacy["limites"]

    recu_complet = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
        "aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base", "recu_complet": True,
    }))
    args_recu = {
        "aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base",
        "recu_complet": True, "transport_pagine": True,
    }
    pages_recu = []
    empreinte_recu = offset_recu = None
    for _ in range(100):
        page_recu = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
            **args_recu,
            **({} if empreinte_recu is None else {
                "empreinte_resultat": empreinte_recu, "offset_transport": offset_recu,
            }),
        }))
        empreinte_recu = page_recu["empreinte_resultat"]
        pages_recu.append(page_recu["fragment"])
        offset_recu = page_recu["prochain_offset"]
        if offset_recu is None:
            break
    else:
        pytest.fail("pagination du reçu complet sans terminaison")
    assert json.loads("".join(pages_recu)) == recu_complet


def test_transport_pagine_refuse_hash_ou_offset_hors_contrat_sans_detail(par_nom, cas_fictif):
    base = {"aujourd_hui": AUJOURD_HUI, "horizon_mois": 6, "scenario": "base", "transport_pagine": True}
    refus_hash = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
        **base, "empreinte_resultat": "0" * 64, "offset_transport": 0,
    }))
    assert refus_hash["code"] == "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE"
    assert "0" * 64 not in refus_hash["detail"]
    refus_offset = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
        **base, "empreinte_resultat": "0" * 64, "offset_transport": 10**9,
    }))
    assert refus_offset["code"] == "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE"
    assert "0" * 64 not in refus_offset["detail"]
    premiere = utile(appeler(par_nom, "m5_prevoir_tresorerie_longue", base))
    refus_hors_borne = refus(appeler(par_nom, "m5_prevoir_tresorerie_longue", {
        **base,
        "empreinte_resultat": premiere["empreinte_resultat"],
        "offset_transport": premiere["longueur_caracteres"] + 1,
    }))
    assert refus_hors_borne["code"] == "REJ-PREVISION-LONGUE-TRANSPORT-INVALIDE"
    assert premiere["empreinte_resultat"] not in refus_hors_borne["detail"]


def test_transport_fragmentation_conserve_echappements_unicode_et_borne_enveloppe():
    corps = {"z_texte_fictif": ('é🙂 «guillemets \" et barre \\\\ + retour\n nul\x00 ' * 900), "a": 1}
    fragments = []
    premieres_pages = []
    fingerprint = offset = None
    for _ in range(100):
        enveloppe = outil_previsions._transport_pagine(
            corps, empreinte_resultat=fingerprint, offset=offset
        )
        assert enveloppe["accepte"] is True
        assert len(json.dumps(enveloppe, ensure_ascii=False, default=str)) <= 5300
        resultat = enveloppe["resultat"]
        premieres_pages.append(resultat)
        fingerprint = resultat["empreinte_resultat"]
        fragments.append(resultat["fragment"])
        offset = resultat["prochain_offset"]
        if offset is None:
            break
    else:
        pytest.fail("pagination de transport sans terminaison")
    reconstitue = "".join(fragments)
    assert json.loads(reconstitue) == corps
    assert reconstitue == json.dumps(corps, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(reconstitue.encode("utf-8")).hexdigest() == fingerprint
    assert len(fragments) > 1
    premiere = premieres_pages[0]
    fin = premiere["prochain_offset"]
    assert fin is not None
    trop_grande = {**premiere, "fragment": reconstitue[:fin + 1], "prochain_offset": fin + 1}
    assert len(json.dumps({"accepte": True, "resultat": trop_grande}, ensure_ascii=False)) > 5300


def test_transport_refuse_offset_egal_longueur_et_accepte_dernier_caractere():
    empreinte = hashlib.sha256(b"{}").hexdigest()
    derniere = outil_previsions._transport_pagine({}, empreinte_resultat=empreinte, offset=1)
    assert derniere["accepte"] is True
    assert derniere["resultat"]["fragment"] == "}"
    assert derniere["resultat"]["prochain_offset"] is None
    hors_borne = outil_previsions._transport_pagine({}, empreinte_resultat=empreinte, offset=2)
    assert hors_borne["accepte"] is False
    assert "offset_transport hors" in hors_borne["verdict"]["detail"]


def test_transport_utilise_pleinement_le_budget_sur_texte_ascii():
    enveloppe = outil_previsions._transport_pagine({"texte": "a" * 10000}, empreinte_resultat=None, offset=None)
    assert enveloppe["accepte"] is True
    assert len(json.dumps(enveloppe, ensure_ascii=False, default=str)) == 5300


@pytest.mark.parametrize("ecart", [-1, 1])
def test_transport_ne_saute_pas_la_plus_grande_tranche_quand_le_milieu_est_trop_grand(monkeypatch, ecart):
    corps = {"texte": "a" * 8000}
    texte = json.dumps(corps, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    milieu = (1 + len(texte)) // 2
    empreinte = hashlib.sha256(texte.encode("utf-8")).hexdigest()
    enveloppe_milieu = outil_previsions.accepte({
        "transport": "json-canonique-concat-v1", "empreinte_resultat": empreinte,
        "longueur_caracteres": len(texte), "offset_transport": 0, "fragment": texte[:milieu],
        "prochain_offset": milieu, "note_empreinte": "cohérence de fragments uniquement; aucune preuve d'authenticité",
    })
    taille_milieu = len(json.dumps(enveloppe_milieu, ensure_ascii=False, default=str))
    monkeypatch.setattr(outil_previsions, "_BUDGET", taille_milieu + ecart)
    resultat = outil_previsions._transport_pagine(corps, empreinte_resultat=None, offset=None)
    assert resultat["accepte"] is True
    assert len(resultat["resultat"]["fragment"]) == milieu + ecart
