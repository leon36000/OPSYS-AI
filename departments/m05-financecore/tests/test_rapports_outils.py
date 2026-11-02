"""Rapports financiers, budget déclaré et pré-audit (M5-RAPPORTS-1, M5-PRE-AUDIT) sur le VRAI socle : niveaux, portée
d'appareil fermée, mentions, registres durables altérés, budgets hostiles, pagination, constat pour M8, dimensions de
M4.

Base SQLite temporaire migrée, vrai manifeste de M5, vraie file d'approbation. Aucun réseau. Entreprise, comptes et
montants fictifs (AGENTS.md). Le parcours entier (exercice de trois mois, planificateur, M8) est dans
`tests/test_rapports_preaudit_bout_en_bout.py`.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from jsonschema import Draft202012Validator
from m5_financecore import analyse, wct_recus
from sqlalchemy import select, update

from opsys import approbations, contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
D = Decimal
DEPARTEMENT = "m05-financecore"
_RACINE_M5 = Path(__file__).resolve().parents[1]
_RACINE = _RACINE_M5.parents[1]
H = "2026-03-31T17:00:00-04:00"
OUTILS = {
    "m5_etat_des_resultats": (Autonomie.T0, None),
    "m5_bilan_brouillon": (Autonomie.T0, None),
    "m5_budget_contre_reel": (Autonomie.T0, None),
    "m5_declarer_budget": (Autonomie.T1, Niveau.N3),
    "m5_lire_budget": (Autonomie.T0, None),
    "m5_rentabilite_par_axe": (Autonomie.T0, None),
    "m5_rapport_mensuel_direction": (Autonomie.T0, None),
    "m5_controler_preaudit": (Autonomie.T0, None),
    "m5_constater_preaudit": (Autonomie.T1, Niveau.N2),
    "m5_rejouer_rapport_financier": (Autonomie.T0, None),
}
ARGUMENTS = {
    "m5_etat_des_resultats": {"debut": "2026-01-01", "fin": "2026-03-31"},
    "m5_bilan_brouillon": {"au": "2026-03-31"},
    "m5_budget_contre_reel": {"periode_debut": "2026-01", "periode_fin": "2026-03"},
    "m5_declarer_budget": {
        "libelle": "B",
        "lignes": [{"compte": "4100", "mois": "2026-01", "montant": "1.00"}],
        "motif": None,
        "version_attendue": 0,
        "horodatage": H,
    },
    "m5_lire_budget": {},
    "m5_rentabilite_par_axe": {"axe": "ville"},
    "m5_rapport_mensuel_direction": {"periode": "2026-03"},
    "m5_controler_preaudit": {"aujourd_hui": "2026-03-31"},
    "m5_constater_preaudit": {"aujourd_hui": "2026-03-31", "horodatage": H},
    "m5_rejouer_rapport_financier": {"recu": {}},
}


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-rapports.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234", ["nathan_owner", "admin"]
        )
        identite.creer_personne(
            cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234", ["finance", "admin"]
        )
        identite.creer_personne(cnx, "employe1", "Un Employé (fictif)", "mot-de-passe-employe-1234", ["employee"])
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

    _declarer({})
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


def decider(dep, nom, arguments, *, par="nathan"):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    reponse = capacites.appeler(nom, arguments)
    assert reponse["statut"] == "en_attente_approbation", reponse
    disponibles = outils_executables({DEPARTEMENT: dep}, stockage.transaction)
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, reponse["demande_id"], True, par, disponibles, {DEPARTEMENT: dep})


def registre(nom):
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, nom))


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
    decision = decider(dep, "m5_valider_ecriture_comptable", {"ecriture_id": ident, "horodatage": H}, par="comptable")
    assert decision["statut"] == "executee", decision
    return ident


def livre_simple(par_nom, dep):
    ecriture(
        par_nom,
        dep,
        "V1",
        "2026-01-15",
        [
            {"compte": "1010", "debit": "1149.75", "credit": None},
            {"compte": "4100", "debit": None, "credit": "1000.00"},
            {"compte": "2300", "debit": None, "credit": "50.00"},
            {"compte": "2310", "debit": None, "credit": "99.75"},
        ],
    )
    ecriture(
        par_nom,
        dep,
        "C1",
        "2026-02-10",
        [{"compte": "5600", "debit": "300.00", "credit": None}, {"compte": "1010", "debit": None, "credit": "300.00"}],
    )


def altérer(nom_registre, modification):
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == nom_registre)
    with stockage.transaction() as cnx:
        ligne = codec.decoder(
            cnx.execute(select(REGISTRES.c.maillon).where(filtre).order_by(REGISTRES.c.rang.desc())).scalars().first()
        )
        modification(ligne)
        cnx.execute(
            update(REGISTRES)
            .where(filtre & (REGISTRES.c.rang == len(registre(nom_registre)) - 1))
            .values(maillon=codec.encoder(ligne))
        )


# ===================================================================================================== le contrat
def test_niveaux_autonomie_et_portee_fermee_des_dix_outils(par_nom):
    for nom, (autonomie, niveau) in OUTILS.items():
        outil = par_nom[nom]
        assert outil.autonomie is autonomie and outil.niveau == niveau, nom
        assert outil.roles_appareil == frozenset(), f"{nom} : portée d'appareil fermée"
        assert nom in analyse.SORTIES_RAPPORTS and nom in analyse.SORTIES_D_ANALYSE
    assert set(OUTILS) == analyse.SORTIES_RAPPORTS
    assert par_nom["m5_declarer_budget"].niveau_effectif is Niveau.N3  # un budget engage la direction
    assert par_nom["m5_constater_preaudit"].niveau_effectif is Niveau.N2  # le constat planifié : N2, jamais plus haut
    for nom in OUTILS:
        if nom not in ("m5_declarer_budget", "m5_constater_preaudit"):
            assert par_nom[nom].niveau_effectif is Niveau.N0, nom  # les rapports ne modifient rien


def test_aucun_outil_ne_s_ouvre_a_un_appareil(par_nom, declare):
    appelante = contexte.IdentiteAppelante(personne="comptable", role="admin")
    for nom, arguments in ARGUMENTS.items():
        verdict = refus(appeler(par_nom, nom, arguments, appelante))
        assert verdict["code"] in ("REJ-IDENTITE-APPAREIL-INVALIDE", "REJ-PREAUDIT-APPAREIL-INTERDIT"), nom


def test_la_garde_anti_decaissement_couvre_les_nouveaux_modules_et_reste_au_vert():
    from m5_financecore import conformite

    racine = _RACINE_M5 / "src" / "m5_financecore"
    assert conformite.verifier_aucun_decaissement(racine) == (True, "")
    for module in (
        "rapports_financiers",
        "budgets",
        "controleur_preaudit",
        "constat_preaudit",
        "verdicts_rapports",
        "outils_rapports",
    ):
        assert module in conformite._SURVEILLE_SANS_DECAISSEMENT, module
    assert conformite.verifier_conformite(racine)["conforme"] is True


def test_les_nouveaux_modules_ne_font_aucune_entree_sortie_ni_horloge():
    import ast

    for module in ("rapports_financiers", "budgets", "controleur_preaudit", "constat_preaudit"):
        source = (_RACINE_M5 / "src" / "m5_financecore" / f"{module}.py").read_text(encoding="utf-8")
        arbre = ast.parse(source)
        importes = {n.module or "" for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names
        }
        assert not {
            i for i in importes if i.split(".")[0] in ("opsys", "requests", "urllib", "socket", "sqlalchemy", "random")
        }, module
        assert "datetime.now" not in source and "time.time" not in source and "today()" not in source, module
        appels = {n.func.id for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert not appels & {"float", "round", "open", "print"}, module
        assert not any(isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(arbre)), module


def test_le_manifeste_declare_le_constat_les_trois_reglages_et_l_evenement(dep):
    (constat,) = [c for c in dep.constats_planifies if c.nom == "preaudit"]
    assert constat.outil == "m5_constater_preaudit" and constat.mesures == ("m8_constats_preaudit",)
    assert constat.appels == ((("aujourd_hui", "calcul", "jour"), ("horodatage", "calcul", "instant")),)
    assert "m5.preaudit_constate" in dep.evenements_publie
    reglages = {r.cle: r for r in dep.reglages}
    assert set(reglages) == {
        "m5.seuil_transaction_hors_norme_cad",
        "m5.jours_fenetre_doublon",
        "m5.historique_changement_compte",
    }
    for reglage in reglages.values():
        assert reglage.niveau is Niveau.N3 and reglage.proposition is None  # aucune valeur proposée, aucune inventée
        assert reglage.chemin[:2] == ("configuration", "preaudit") and reglage.debloque
    texte = (_RACINE_M5 / "department.yaml").read_text(encoding="utf-8")
    donnees = yaml.safe_load(texte)
    assert donnees["configuration"] == {"preaudit": {}}  # AUCUN seuil écrit au manifeste livré


# ============================================================================================= mentions et pagination
def test_chaque_sortie_acceptee_porte_les_deux_mentions_et_le_brouillon(par_nom, declare, dep):
    livre_simple(par_nom, dep)
    for nom, arguments in ARGUMENTS.items():
        if nom in (
            "m5_declarer_budget",
            "m5_lire_budget",
            "m5_budget_contre_reel",
            "m5_rejouer_rapport_financier",
            "m5_rentabilite_par_axe",
        ):
            continue
        corps = utile(appeler(par_nom, nom, arguments))
        assert corps["mention"] == analyse.MENTION_ANALYSE_PREPARATOIRE, nom
        assert corps["mention_comptable"].startswith("À valider auprès d'un comptable (CPA)"), nom
    for nom in ("m5_etat_des_resultats", "m5_bilan_brouillon", "m5_rapport_mensuel_direction"):
        assert utile(appeler(par_nom, nom, ARGUMENTS[nom]))["mention_brouillon"].startswith(
            "Brouillon préparatoire — à valider auprès d'un comptable (CPA)"
        )
    axe = utile(appeler(par_nom, "m5_rentabilite_par_axe", {"axe": "ville"}))
    assert axe["mention_comptable"] and axe["statut"] == "NON_CALCULABLE"
    decider(dep, "m5_declarer_budget", ARGUMENTS["m5_declarer_budget"])
    assert utile(appeler(par_nom, "m5_lire_budget", {}))["mention_comptable"]
    assert utile(appeler(par_nom, "m5_budget_contre_reel", ARGUMENTS["m5_budget_contre_reel"]))["mention_brouillon"]


def test_les_chiffres_de_l_outil_sont_ceux_du_grand_livre(par_nom, declare, dep):
    livre_simple(par_nom, dep)
    e = utile(appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-01-01", "fin": "2026-03-31"}))
    # produits 1 000,00 (4100) ; charges 300,00 (5600) ; résultat 700,00 — les taxes à percevoir ne sont pas des
    # produits
    assert (e["total_produits"], e["total_charges"], e["resultat_avant_impots"]) == ("1000.00", "300.00", "700.00")
    assert [(x["compte"], x["montant"]) for x in e["lignes"]] == [("4100", "1000.00"), ("5600", "300.00")]
    janvier = utile(appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-01-01", "fin": "2026-01-31"}))
    fevrier = utile(appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-02-01", "fin": "2026-02-28"}))
    assert (janvier["total_produits"], janvier["total_charges"]) == ("1000.00", "0.00")
    assert (fevrier["total_produits"], fevrier["total_charges"]) == ("0.00", "300.00")
    b = utile(appeler(par_nom, "m5_bilan_brouillon", {"au": "2026-03-31"}))
    assert (b["total_actif"], b["total_passif"], b["resultat_cumule_non_clos"], b["equilibre"]) == (
        "849.75",
        "149.75",
        "700.00",
        True,
    )
    balance = utile(appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-03-31"}))
    assert balance["total_debits"] == balance["total_credits"] == "1449.75"


def test_un_brouillon_n_entre_dans_aucun_rapport_mais_il_est_compte(par_nom, declare, dep):
    livre_simple(par_nom, dep)
    utile(
        appeler(
            par_nom,
            "m5_proposer_ecriture_comptable",
            {
                "date_effet": "2026-02-20",
                "libelle": "Brouillon (fictif)",
                "piece_type": "manuelle",
                "piece_reference": "B1",
                "lignes": [
                    {"compte": "5600", "debit": "999.00", "credit": None},
                    {"compte": "1010", "debit": None, "credit": "999.00"},
                ],
                "horodatage": H,
            },
        )
    )
    e = utile(appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-02-01", "fin": "2026-02-28"}))
    assert e["total_charges"] == "300.00" and e["completude"]["brouillons_non_comptabilises"] == 1
    assert any("brouillon" in a for a in e["recu"]["avertissements"])


def test_la_pagination_est_bornee_et_les_totaux_portent_sur_tout(par_nom, declare, dep):
    livre_simple(par_nom, dep)
    page1 = utile(appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-01-01", "fin": "2026-03-31", "limite": 1}))
    assert len(page1["lignes"]) == 1 and page1["prochain_depart"] == 1 and page1["lignes_total"] == 2
    assert (
        page1["total_produits"] == "1000.00" and page1["total_charges"] == "300.00"
    )  # les totaux ne dépendent pas de la page
    page2 = utile(
        appeler(
            par_nom, "m5_etat_des_resultats", {"debut": "2026-01-01", "fin": "2026-03-31", "limite": 1, "depart": 1}
        )
    )
    assert page2["lignes"][0]["compte"] == "5600" and page2["prochain_depart"] is None
    assert page1["recu"]["empreinte"] == page2["recu"]["empreinte"]  # le reçu couvre tout l'état, pas la page
    loin = utile(appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-01-01", "fin": "2026-03-31", "depart": 99}))
    assert loin["lignes"] == [] and loin["prochain_depart"] is None
    for mauvais in ({"limite": 0}, {"limite": 41}, {"limite": "3"}, {"depart": -1}, {"depart": 1.5}):
        reponse = appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-01-01", "fin": "2026-03-31", **mauvais})
        assert reponse["ok"] is False or reponse["resultat"]["accepte"] is False, mauvais


def test_dates_et_periodes_invalides_sont_des_refus_nommes(par_nom, declare, dep):
    cas = [
        ("m5_etat_des_resultats", {"debut": "2026-02-01", "fin": "2026-01-01"}, "REJ-RAPPORT-PERIODE-INVALIDE"),
        ("m5_etat_des_resultats", {"debut": "2026-01-01", "fin": "2028-01-01"}, "REJ-RAPPORT-PERIODE-INVALIDE"),
        ("m5_etat_des_resultats", {"debut": "2026-13-01", "fin": "2026-12-31"}, "REJ-RAPPORT-DATE-INVALIDE"),
        ("m5_bilan_brouillon", {"au": "demain"}, "REJ-RAPPORT-DATE-INVALIDE"),
        ("m5_rapport_mensuel_direction", {"periode": "2026-13"}, "REJ-RAPPORT-PERIODE-INVALIDE"),
        ("m5_controler_preaudit", {"aujourd_hui": "2026-02-30"}, "REJ-PREAUDIT-DATE-INVALIDE"),
        (
            "m5_constater_preaudit",
            {"aujourd_hui": "2026-03-31", "horodatage": "2026-03-31T12:00:00"},
            "REJ-PREAUDIT-DATE-INVALIDE",
        ),
        ("m5_constater_preaudit", {"aujourd_hui": "x", "horodatage": H}, "REJ-PREAUDIT-DATE-INVALIDE"),
        ("m5_rentabilite_par_axe", {"axe": "ville", "debut": "2026-01-01"}, "REJ-RAPPORT-DATE-INVALIDE"),
    ]
    for nom, arguments, code in cas:
        assert refus(appeler(par_nom, nom, arguments))["code"] == code, (nom, arguments)
    assert refus(appeler(par_nom, "m5_budget_contre_reel", {"periode_debut": "2026-03", "periode_fin": "2026-01"}))[
        "code"
    ] in ("REJ-RAPPORT-PERIODE-INVALIDE", "REJ-BUDGET-A-DECLARER")


# ===================================================================================== registres altérés (fail-closed)
def test_un_grand_livre_altere_fait_refuser_les_rapports_et_le_preaudit_le_dit_sans_dire_aucun_constat(
    par_nom, declare, dep
):
    livre_simple(par_nom, dep)
    avant = utile(appeler(par_nom, "m5_controler_preaudit", {"aujourd_hui": "2026-03-31"}))
    assert avant["total"] is not None
    altérer("grand_livre", lambda ligne: ligne.update(libelle="Libellé retouché à la main"))
    for nom in ("m5_etat_des_resultats", "m5_bilan_brouillon"):
        assert refus(appeler(par_nom, nom, ARGUMENTS[nom]))["code"] in (
            "REJ-GL-CHAINE-INVALIDE",
            "REJ-RAPPORT-CHAINE-INVALIDE",
        ), nom
    controle = utile(appeler(par_nom, "m5_controler_preaudit", {"aujourd_hui": "2026-03-31"}))
    non_evaluees = {r["regle"] for r in controle["regles_non_evaluees"]}
    assert {"PAIEMENT_SANS_FACTURE", "TAXE_INCOHERENTE", "FACTURE_MODIFIEE", "DOCUMENT_MANQUANT"} <= non_evaluees
    assert any(
        k["regle"] == "PISTE_AUDIT_INCOMPLETE" and k["sources"][0]["registre"] == "grand_livre"
        for k in controle["constats"]
    )
    assert all(controle["par_regle"][r] is None for r in non_evaluees)


def test_un_budget_altere_bloque_la_lecture_et_la_declaration(par_nom, declare, dep):
    decider(dep, "m5_declarer_budget", ARGUMENTS["m5_declarer_budget"])
    altérer("budgets_declares", lambda ligne: ligne["lignes"][0].update(montant="99999.00"))
    assert refus(appeler(par_nom, "m5_lire_budget", {}))["code"] == "REJ-RAPPORT-CHAINE-INVALIDE"
    assert (
        refus(appeler(par_nom, "m5_budget_contre_reel", ARGUMENTS["m5_budget_contre_reel"]))["code"]
        == "REJ-RAPPORT-CHAINE-INVALIDE"
    )
    decision = decider(
        dep,
        "m5_declarer_budget",
        {
            **ARGUMENTS["m5_declarer_budget"],
            "version_attendue": 1,
            "motif": "Révision (fictive)",
            "lignes": [{"compte": "4100", "mois": "2026-02", "montant": "5.00"}],
        },
    )
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-RAPPORT-CHAINE-INVALIDE"
    assert len(registre("budgets_declares")) == 1


# =========================================================================================================== budget
def test_declarer_un_budget_exige_une_personne_et_la_double_soumission_ne_cree_rien(par_nom, declare, dep):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    assert (
        capacites.appeler("m5_declarer_budget", ARGUMENTS["m5_declarer_budget"])["statut"] == "en_attente_approbation"
    )
    assert registre("budgets_declares") == []
    assert (
        refus(appeler(par_nom, "m5_declarer_budget", ARGUMENTS["m5_declarer_budget"]))["code"]
        == "REJ-BUDGET-HUMAIN-REQUIS"
    )
    refuse = Capacites({DEPARTEMENT: dep}, stockage.transaction).appeler(
        "m5_declarer_budget", ARGUMENTS["m5_declarer_budget"]
    )
    with stockage.transaction() as cnx:
        decision = approbations.decider(
            cnx,
            refuse["demande_id"],
            False,
            "nathan",
            outils_executables({DEPARTEMENT: dep}, stockage.transaction),
            {DEPARTEMENT: dep},
        )
    assert decision["statut"] == "refusee" and registre("budgets_declares") == []
    premiere = decider(dep, "m5_declarer_budget", ARGUMENTS["m5_declarer_budget"])
    assert premiere["reponse"]["resultat"]["resultat"]["statut"] == "ecrit"
    seconde = decider(dep, "m5_declarer_budget", {**ARGUMENTS["m5_declarer_budget"], "version_attendue": None})
    assert seconde["reponse"]["resultat"]["resultat"]["statut"] == "deja" and len(registre("budgets_declares")) == 1


def test_le_budget_ne_prend_que_du_texte_et_chaque_champ_hostile_est_refuse(par_nom, declare, dep):
    base = ARGUMENTS["m5_declarer_budget"]
    hostiles = [
        {**base, "libelle": "ligne 1\nligne 2"},
        {**base, "libelle": "x" * 81},
        {**base, "libelle": ""},
        {**base, "lignes": []},
        {**base, "lignes": [{"compte": "4100", "mois": "2026-01"}]},
        {**base, "lignes": [{"compte": "4100", "mois": "2026-01", "montant": "1.00", "note": "extra"}]},
        {**base, "lignes": [{"compte": "4100; DROP TABLE", "mois": "2026-01", "montant": "1.00"}]},
        {**base, "lignes": [{"compte": "4100", "mois": "2026-01", "montant": "1e9"}]},
        {**base, "lignes": [{"compte": "4100", "mois": "2026-01", "montant": 12.5}]},
        {**base, "lignes": [{"compte": "4100", "mois": "2026-01", "montant": "1.00"}] * 2},
    ]
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    for arguments in hostiles:
        reponse = capacites.appeler("m5_declarer_budget", arguments)
        if reponse.get("statut") == "en_attente_approbation":
            disponibles = outils_executables({DEPARTEMENT: dep}, stockage.transaction)
            with stockage.transaction() as cnx:
                decision = approbations.decider(
                    cnx, reponse["demande_id"], True, "nathan", disponibles, {DEPARTEMENT: dep}
                )
            corps = decision["reponse"].get("resultat", {})
            assert decision["statut"] == "echec" or corps.get("accepte") is False, arguments
    assert registre("budgets_declares") == []


def test_un_libelle_html_est_une_donnee_et_n_est_jamais_interprete(par_nom, declare, dep):
    arguments = {**ARGUMENTS["m5_declarer_budget"], "libelle": "<script>alert(1)</script> {{7*7}} ${x}"}
    decision = decider(dep, "m5_declarer_budget", arguments)
    assert decision["reponse"]["resultat"]["resultat"]["libelle"] == "<script>alert(1)</script> {{7*7}} ${x}"
    lecture = utile(appeler(par_nom, "m5_lire_budget", {}))
    assert lecture["libelle"] == "<script>alert(1)</script> {{7*7}} ${x}" and lecture["lignes_total"] == 1


# ======================================================================================== constat pour M8
def schema_evenement():
    return json.loads(
        (_RACINE / "src" / "opsys" / "evenements" / "catalogue" / "m5.preaudit_constate.json").read_text(
            encoding="utf-8"
        )
    )


def publies():
    with stockage.transaction() as cnx:
        lignes = (
            cnx.execute(
                select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m5.preaudit_constate")
            )
            .mappings()
            .all()
        )
    return [
        (ligne["evenement_id"], json.loads(ligne["charge"]) if isinstance(ligne["charge"], str) else ligne["charge"])
        for ligne in lignes
    ]


def test_le_catalogue_valide_la_charge_et_refuse_les_proprietes_en_trop():
    validateur = Draft202012Validator(schema_evenement())
    charge = {
        "evenement_id": "m5-preaudit-2026-03-31-abc-def",
        "date_reference": "2026-03-31",
        "constate_le": H,
        "version_donnees": "0123456789abcdef",
        "constats_par_regle": dict.fromkeys(
            [
                "FACTURE_SANS_PAIEMENT",
                "PAIEMENT_SANS_FACTURE",
                "DEPENSE_SANS_RECU",
                "TAXE_INCOHERENTE",
                "DOUBLON_PROBABLE",
                "TRANSACTION_HORS_NORME",
                "FACTURE_MODIFIEE",
                "CHANGEMENT_COMPTE_INHABITUEL",
                "PISTE_AUDIT_INCOMPLETE",
                "DOCUMENT_MANQUANT",
            ],
            0,
        ),
        "constats_total": 0,
        "constats_par_gravite": {"haute": 0, "moyenne": 0, "faible": 0},
        "regles_non_evaluees": [],
        "regles_partielles": [],
    }
    assert list(validateur.iter_errors(charge)) == []
    for mauvais in (
        {**charge, "facture_id": "F-1"},
        {**charge, "constats_total": -1},
        {**charge, "constats_total": "3"},
        {**charge, "regles_non_evaluees": ["INVENTEE"]},
        {**charge, "date_reference": "2026/03/31"},
        {**charge, "version_donnees": "XYZ"},
        {k: v for k, v in charge.items() if k != "constats_par_gravite"},
        {**charge, "constats_par_regle": {**charge["constats_par_regle"], "AUTRE": 1}},
        {
            **charge,
            "constats_par_regle": {k: v for k, v in charge["constats_par_regle"].items() if k != "DOCUMENT_MANQUANT"},
        },
    ):
        assert list(validateur.iter_errors(mauvais)), mauvais


def test_le_constat_publie_une_fois_par_instant_et_rien_de_personnel(par_nom, declare, dep, caplog):
    livre_simple(par_nom, dep)
    caplog.set_level(logging.DEBUG)
    arguments = {"aujourd_hui": "2026-03-31", "horodatage": H}
    premier = utile(appeler(par_nom, "m5_constater_preaudit", arguments))
    assert premier["publie"] is True and premier["constats_total"] is None or isinstance(premier["constats_total"], int)
    assert premier["regles_non_evaluees"] == ["TRANSACTION_HORS_NORME", "CHANGEMENT_COMPTE_INHABITUEL"]
    (evenement,) = publies()
    assert evenement[0] == premier["evenement_id"] and evenement[0].startswith("m5-preaudit-2026-03-31-")
    assert list(Draft202012Validator(schema_evenement()).iter_errors(evenement[1])) == []
    # le même constat rejoué (même horodatage) : le bus absorbe
    utile(appeler(par_nom, "m5_constater_preaudit", arguments))
    assert len(publies()) == 1
    # un autre instant, mêmes données : un autre identifiant, la MÊME version des données
    utile(appeler(par_nom, "m5_constater_preaudit", {**arguments, "horodatage": "2026-03-31T23:00:00-04:00"}))
    lues = publies()
    assert (
        len(lues) == 2 and lues[0][1]["version_donnees"] == lues[1][1]["version_donnees"] and lues[0][0] != lues[1][0]
    )
    texte = json.dumps(lues, ensure_ascii=False) + caplog.text
    for interdit in ("V1", "C1", "1149", "1000.00", "Écriture", "gle-", "comptable", "nathan"):
        assert interdit not in json.dumps(lues, ensure_ascii=False), interdit
    assert "Écriture V1" not in texte


# ======================================================================================== reçu et rejeu (outil)
def test_l_outil_de_rejeu_refuse_ce_qui_n_est_pas_un_recu_et_rejoue_un_recu_reel(par_nom, declare, dep):
    livre_simple(par_nom, dep)
    for mauvais in ({}, {"type": "RECU_CALCUL"}, {"a": 1}):
        assert (
            refus(appeler(par_nom, "m5_rejouer_rapport_financier", {"recu": mauvais}))["code"]
            == "REJ-RAPPORT-RECU-INVALIDE"
        )
    recu = utile(appeler(par_nom, "m5_etat_des_resultats", {"debut": "2026-01-01", "fin": "2026-03-31"}))["recu"]
    assert utile(appeler(par_nom, "m5_rejouer_rapport_financier", {"recu": recu}))["rejoue"] is True
    controle = utile(appeler(par_nom, "m5_controler_preaudit", {"aujourd_hui": "2026-03-31"}))["recu"]
    assert controle["moteur"] == "preaudit_controle"
    resultat = utile(appeler(par_nom, "m5_rejouer_rapport_financier", {"recu": controle}))
    assert resultat["recu_valide"] is True and resultat["moteur"] == "preaudit_controle"
    # un reçu compact se vérifie sans se rejouer hors ligne, et le dit
    compact = {k: v for k, v in recu.items() if k != "entrees"}
    r = utile(appeler(par_nom, "m5_rejouer_rapport_financier", {"recu": compact}))
    assert r["recu_valide"] is True and r["rejoue"] is False and "compact" in r["note"]
    # un chiffre retouché dans le résultat : le reçu est refusé
    retouche = json.loads(json.dumps(recu))
    retouche["resultat"]["total_charges"] = "1.00"
    assert (
        refus(appeler(par_nom, "m5_rejouer_rapport_financier", {"recu": retouche}))["code"]
        == "REJ-RAPPORT-RECU-INVALIDE"
    )


# ====================================================================================== dimensions de M4 gardées
def test_wct_recu_garde_service_et_ville_telles_quelles_ou_rien():
    plein = wct_recus.construire(
        "w", "i", "d", "2026-03-01T10:00:00-05:00", 60, "e" * 64, service="gouttieres", ville="Lévis"
    )
    assert plein["service"] == "gouttieres" and plein["ville"] == "Lévis"
    sans = wct_recus.construire("w", "i", "d", "2026-03-01T10:00:00-05:00", 60, "e" * 64)
    assert "service" not in sans and "ville" not in sans
    for mauvais in (None, "", "   ", 5, ["Lévis"], {"v": 1}, True):
        assert "ville" not in wct_recus.construire("w", "i", "d", "h", 60, None, ville=mauvais)
    long = wct_recus.construire("w", "i", "d", "h", 60, None, ville="v" * 500)
    assert len(long["ville"]) == 80
    # le rejeu d'un WCT reste décidé par l'empreinte de la CHARGE, pas par ces champs
    charge = {"wct_id": "w", "ville": "Lévis"}
    from m5_financecore import encodage

    recu = wct_recus.construire("w", "i", "d", "h", 60, encodage.empreinte(charge), ville="Lévis")
    wct_recus.verifier_rejeu(recu, charge)
    with pytest.raises(ValueError):
        wct_recus.verifier_rejeu(recu, {**charge, "ville": "Québec"})


def test_le_consommateur_de_travaux_termines_garde_les_dimensions_du_catalogue(par_nom, declare):
    charge = {
        "wct_id": "wct-9",
        "intervention_id": "int-9",
        "lead_id": "l",
        "technicien_id": "t",
        "horodatage_completion": H,
        "fix_gps_completion": {"latitude": 45.0, "longitude": -73.0},
        "duree_reelle_minutes": 60,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a",
        "consommateurs_cibles": ["M8"],
        "devis_id": None,
        "statut": "completed_verified",
        "ville": "Lévis",
        "service": "gouttieres",
    }
    with stockage.transaction():
        m5_outils._recevoir_travaux_termines(charge)
        m5_outils._recevoir_travaux_termines(charge)  # le rejeu est absorbé
    (maillon,) = registre("wct_recus")
    assert (maillon["ville"], maillon["service"]) == ("Lévis", "gouttieres")
    ancien = {k: v for k, v in charge.items() if k not in ("ville", "service")} | {"wct_id": "wct-10"}
    with stockage.transaction():
        m5_outils._recevoir_travaux_termines(ancien)
    assert "ville" not in registre("wct_recus")[1] and "service" not in registre("wct_recus")[1]


def test_les_traces_de_la_voie_console_ne_comptent_jamais_dans_la_rentabilite_par_axe(par_nom, declare):
    from m5_financecore import cout_reel

    def rentabilite(devis, marge):
        return {
            "devis_id": devis,
            "chantier_id": "c",
            "wct_id": "w-" + devis,
            "verdict": "CALCULEE",
            "devise": "CAD",
            "facture_id": None,
            "statut_facture": "PAYEE",
            "prix_definitif": True,
            "prix_facture": D("1000.00"),
            "cout_reel": {
                "complet": True,
                "cout_total": D("1000.00") - D(marge),
                "cout_total_connu": D("1000.00") - D(marge),
            },
            "marge_reelle": D(marge),
            "version_entrees": "v" * 64,
            cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION: "h" * 64,
        }

    wct = {
        "wct_id": "w-D-1",
        "intervention_id": "i",
        "lead_id": "l",
        "technicien_id": "t",
        "horodatage_completion": H,
        "fix_gps_completion": {"latitude": 45.0, "longitude": -73.0},
        "duree_reelle_minutes": 60,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a",
        "consommateurs_cibles": ["M8"],
        "devis_id": "D-1",
        "statut": "completed_verified",
        "ville": "Lévis",
        "service": "gouttieres",
    }
    with stockage.transaction():
        m5_outils._recevoir_travaux_termines(wct)
        ordinaire = cout_reel.construire_trace(rentabilite("D-1", "200.00"), H)
        console = {**cout_reel.construire_trace(rentabilite("D-1", "900.00"), H), "provenance_v3": {"x": 1}}
        stockage.maillons(DEPARTEMENT, "rentabilite").append(json.loads(json.dumps(ordinaire, default=str)))
        stockage.maillons(DEPARTEMENT, "rentabilite").append(json.loads(json.dumps(console, default=str)))
    r = utile(appeler(par_nom, "m5_rentabilite_par_axe", {"axe": "ville"}))
    assert r["groupes"][0]["marge_reelle"] == "200.00" and r["total"]["chantiers"] == 1
