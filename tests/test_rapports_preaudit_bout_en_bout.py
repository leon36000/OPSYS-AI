"""Rapports financiers et pré-audit de M5 de BOUT EN BOUT (M5-RAPPORTS-1, M5-PRE-AUDIT) : un exercice FICTIF de trois
mois
(août à octobre 2026) sur le VRAI socle : les dix départements, le vrai bus, le vrai sas d'approbation (N3, N4, N5),
le vrai
planificateur durable à horloge INJECTÉE, les vrais outils de M5, M8 réel. Rien n'est publié à la main.

L'exercice : deux contrats facturés par JALONS (10 000,00 $ en 30/40/30 ; 6 000,00 $ en 50/50), des dépenses de
carburant,
d'outils et de matériaux, les taxes du moteur fiscal versionné ; puis TROIS anomalies injectées :
  - une facture sans paiement (le solde du second contrat, émis le 9 octobre, échu le 8 novembre) ;
  - une dépense sans reçu (une facture de carburant du 15 octobre) ;
  - un doublon (la facture de matériaux du 14 septembre saisie deux fois sous deux numéros).
Prouvé : les états en brouillon aux soldes exacts (calculés à la main ci-dessous) et recoupés par le grand livre, le
budget
contre réel, le pré-audit qui sort EXACTEMENT les trois anomalies (aucune fausse alerte), les données déclarées absentes
(budget, comptes de coûts directs, seuils, dimension service/ville) en fail-closed, le constat planifié vers M8 (ombre =
« aurait », actif = un événement, idempotence par créneau), les reçus rejouables.

Chiffres à la main (TPS 5 %, TVQ 9,975 %, arrondi au cent vers le haut) — produits HT : août 3 000,00 ; septembre 4
000 + 3 000 =
7 000,00 ; octobre 3 000 + 3 000 = 6 000,00 ; total 16 000,00. Charges HT : août 200,00 ; septembre 1 500 + 1 500 = 3
000,00 ;
octobre 800 + 250 = 1 050,00 ; total 4 250,00. Résultat : 2 800,00 ; 4 000,00 ; 4 950,00 ; total 11 750,00.
Bilan au 31 octobre : encaisse 4 paiements = 3 449,25 × 3 + 4 599,00 = 14 946,75 ; clients 3 449,25 ; CTI 212,50 ;
RTI 423,95 ->
actif 19 032,45 ; fournisseurs 4 886,45 ; TPS à percevoir 800,00 ; TVQ à percevoir 1 596,00 -> passif 7 282,45 ; +
résultat
cumulé 11 750,00 = 19 032,45.
Limites dites : SQLite seulement, horloge injectée, aucun service externe, aucune validation d'un CPA.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import planif_m8_monde as pm
import pytest
import yaml
from m5_financecore import outils as m5_outils
from m5_financecore import recu_calcul

from opsys import approbations, contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.connecteurs_planification import journal
from opsys.outils import executer_atomique

FICTIF = True
D = Decimal
M5 = pm.M5
COMPTABLE = contexte.IdentiteAppelante(personne="comptable", role="admin")
RACINE = Path(__file__).resolve().parents[1]
ENTREPRISE = {
    "raison_sociale": "Entreprise Fictive Inc.",
    "adresse": ["123, rue Exemple", "Québec (Québec) A1A 1A1"],
    "numero_tps": "123456789 RT0001",
    "numero_tvq": "1234567890 TQ0001",
}
CONFIGURATION = {
    "operations": {"relances": {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]}},
    "facturation": {
        "numerotation": {"prefixe": "F-", "premier_numero": 1000, "largeur": 5},
        "conditions_paiement": {"delai_jours": 30},
        "entreprise": ENTREPRISE,
    },
    "categories_depense_sans_po": ["carburant", "outils", "materiaux"],
}
ra = pm._charger("reglages_aide_m5", RACINE / "tests" / "reglages_aide.py")
ATTESTATION = {"nom": "Alex Comptable (fictif)", "profession": "CPA", "reference_document": "DEPOT-4521-fictif"}
PLAN_D1 = [
    {"libelle": "Acompte", "declencheur": "acceptation", "pourcentage": "30", "delai_paiement_jours": 30},
    {"libelle": "Mi-chantier", "declencheur": "chantier", "pourcentage": "40"},
    {"libelle": "Solde", "declencheur": "fin_travaux", "pourcentage": "30"},
]
PLAN_D2 = [
    {"libelle": "Acompte", "declencheur": "acceptation", "pourcentage": "50", "delai_paiement_jours": 30},
    {"libelle": "Solde", "declencheur": "fin_travaux", "pourcentage": "50"},
]
H = "2026-10-31T17:00:00-04:00"


# ======================================================================================================= le monde
@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    reel = yaml.safe_load((RACINE / "departments/m05-financecore/department.yaml").read_text(encoding="utf-8"))
    reel["configuration"] = copy.deepcopy(CONFIGURATION)
    manifeste = tmp_path / "department-m5-exercice.yaml"
    manifeste.write_text(yaml.safe_dump(reel, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    m.manifeste = manifeste
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234", ["finance", "admin"]
        )
        identite.creer_personne(
            cnx, ra.PROPRIETAIRE, "Propriétaire fictif", "mot-de-passe-proprio-1234", ["nathan_owner", "admin"]
        )
    m.dep5 = m.bus.departements[M5]
    m.par_nom = {o.nom: o for o in m5_outils.outils()}
    yield m
    pm.demonter()


def _utile(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def appeler(monde, nom, arguments, identite=None):
    if identite is None:
        return executer_atomique(monde.par_nom[nom], arguments)
    with contexte.appele_par_appareil(identite):
        return executer_atomique(monde.par_nom[nom], arguments)


def decider(monde, nom, arguments, *, par="comptable", attestation=None):
    """Un agent PROPOSE (sas du socle) ; une personne DÉCIDE."""
    capacites = Capacites({M5: monde.dep5}, stockage.transaction)
    demande = capacites.appeler(nom, arguments)
    assert demande["statut"] == "en_attente_approbation", demande
    disponibles = outils_executables({M5: monde.dep5}, stockage.transaction)
    options = {"attestation": attestation} if attestation is not None else {}
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, demande["demande_id"], True, par, disponibles, {M5: monde.dep5}, **options)


def _executee(decision):
    assert decision["statut"] == "executee", decision
    corps = decision["reponse"]["resultat"]
    assert corps["accepte"] is True, corps
    return corps["resultat"]


def registre(nom):
    with stockage.transaction():
        return list(stockage.maillons(M5, nom))


def devis_et_travaux(devis_id, prix, *, ville=None, service=None, termine=None):
    charge = {
        "devis_id": devis_id,
        "lead_id": "lead-" + devis_id,
        "chantier_id": "CH-" + devis_id,
        "lignes": [
            {
                "reference_ligne": devis_id + "-L0",
                "description": "Travaux (fictif)",
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": prix,
                "prix_ligne": prix,
                "reference_besoin_materiau": None,
            }
        ],
        "cout_total": "1000.00",
        "prix_total": prix,
        "taux_marge": "0.30",
        "duree_estimee_minutes": "100",
        "horodatage_acceptation": "2026-07-20T09:00:00-04:00",
    }
    with stockage.transaction():
        m5_outils._recevoir_devis_accepte(charge)
    if termine is not None:
        wct = {
            "wct_id": "wct-" + devis_id,
            "intervention_id": "int-" + devis_id,
            "lead_id": "lead-" + devis_id,
            "technicien_id": "tech-fictif-a",
            "horodatage_completion": termine,
            "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
            "duree_reelle_minutes": 120,
            "ecart_signale": False,
            "revue_id": None,
            "hash_maillon": "deadbeef",
            "consommateurs_cibles": ["M8"],
            "devis_id": devis_id,
            "statut": "completed_verified",
        }
        if ville:
            wct["ville"] = ville
        if service:
            wct["service"] = service
        with stockage.transaction():
            m5_outils._recevoir_travaux_termines(wct)


def facturer(monde, devis_id, rang, envoi, paye=None):
    """Brouillon du jalon, émission (N4, humain), paiement total (N5, propriétaire + attestation) : rend l'id."""
    _utile(appeler(monde, "m5_creer_facture_jalon", {"devis_id": devis_id, "rang": rang, "horodatage": envoi}))
    plan = next(m for m in registre("plans_facturation") if m["devis_id"] == devis_id)
    fid = f"fac-{plan['plan_id']}-J{rang}"
    assert decider(monde, "m5_envoyer_facture", {"facture_id": fid, "horodatage": envoi})["statut"] == "executee"
    if paye is not None:
        total = next(e for e in _etats_factures() if e["facture_id"] == fid)["montant_apres_taxes"]
        paiement = decider(
            monde,
            "m5_enregistrer_paiement_facture",
            {
                "facture_id": fid,
                "montant_paye": format(D(str(total)), "f"),
                "approbateur": "Nathan (fictif)",
                "horodatage": paye,
            },
            par="nathan",
            attestation=ATTESTATION,
        )
        assert paiement["statut"] == "executee", paiement
    return fid


def _etats_factures():
    from m5_financecore import facturation

    with stockage.transaction():
        return facturation.etats_des_factures(m5_outils._registre_factures(None))


def deposer_piece(nom, contenu):
    dossier = stockage.dossier_opsys() / "imports" / "pieces"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / nom).write_bytes(contenu.encode("utf-8"))


def depenser(monde, fournisseur, categorie, numero, jour, montant, *, recu=True):
    reponse = _utile(
        appeler(
            monde,
            "m5_saisir_facture_sans_po",
            {
                "fournisseur_id": fournisseur,
                "categorie": categorie,
                "numero_facture": numero,
                "date_facture": jour,
                "montant_avant_taxes": montant,
                "total_facture": None,
                "horodatage": jour + "T10:00:00-04:00",
            },
            COMPTABLE,
        )
    )
    ident = reponse["facture"]["facture_fournisseur_id"]
    if recu:
        deposer_piece(f"{numero}.pdf", f"%PDF recu fictif {numero}")
        _utile(
            appeler(
                monde,
                "m5_lier_piece_justificative",
                {"cible_type": "facture_fournisseur", "cible_id": ident, "fichier": f"{numero}.pdf", "horodatage": H},
            )
        )
    return ident


def comptabiliser(monde):
    """Les brouillons du cycle comptable, puis leur validation par la finance (N4) : le grand livre définitif."""
    crees = 0
    while True:
        genere = _utile(appeler(monde, "m5_generer_brouillons_comptables", {"horodatage": H, "limite": 20}))
        crees += len(genere["brouillons_crees"])
        assert genere["refuses"] == [] and genere["sources_ignorees"] == [], genere
        if genere["reste"] == 0:
            break
    assert crees == 14, crees  # 5 émissions + 4 paiements + 5 factures fournisseurs
    from m5_financecore import grand_livre

    with stockage.transaction():
        etat = grand_livre.etat_grand_livre(m5_outils._registre_grand_livre().lire())
    for ident, ecriture in etat["ecritures"].items():
        if ecriture["statut"] == "BROUILLON":
            assert (
                decider(monde, "m5_valider_ecriture_comptable", {"ecriture_id": ident, "horodatage": H})["statut"]
                == "executee"
            )


def exercice(monde):
    """Août à octobre 2026 : deux contrats par jalons, quatre dépenses saines, puis les trois anomalies."""
    devis_et_travaux("D-1", "10000.00")
    devis_et_travaux("D-2", "6000.00")
    for devis, jalons in (("D-1", PLAN_D1), ("D-2", PLAN_D2)):
        assert (
            decider(
                monde,
                "m5_etablir_plan_facturation",
                {
                    "devis_id": devis,
                    "jalons": jalons,
                    "chantier_id": "CH-" + devis,
                    "horodatage": "2026-07-21T09:00:00-04:00",
                },
            )["statut"]
            == "executee"
        )
    # -- août
    facturer(monde, "D-1", 1, "2026-08-05T09:00:00-04:00", paye="2026-08-20T09:00:00-04:00")
    depenser(monde, "four-a", "carburant", "N-100", "2026-08-12", "200.00")
    # -- septembre
    facturer(monde, "D-2", 1, "2026-09-01T09:00:00-04:00", paye="2026-09-15T09:00:00-04:00")
    facturer(monde, "D-1", 2, "2026-09-10T09:00:00-04:00", paye="2026-09-25T09:00:00-04:00")
    depenser(monde, "four-b", "materiaux", "N-200", "2026-09-14", "1500.00")
    # (3) le DOUBLON : la même facture saisie sous un autre numéro
    depenser(monde, "four-b", "materiaux", "N-200B", "2026-09-14", "1500.00")
    # -- octobre : fin des travaux (dimensions publiées par M4), jalons de solde
    devis_et_travaux("D-1", "10000.00", ville="Lévis", service="gouttieres", termine="2026-10-05T16:00:00-04:00")
    devis_et_travaux("D-2", "6000.00", ville="Québec", service="gouttieres", termine="2026-10-08T16:00:00-04:00")
    facturer(monde, "D-1", 3, "2026-10-06T09:00:00-04:00", paye="2026-10-20T09:00:00-04:00")
    depenser(monde, "four-c", "outils", "N-300", "2026-10-03", "800.00")
    # (1) la FACTURE SANS PAIEMENT : émise le 9 octobre, échue le 8 novembre, jamais payée
    sans_paiement = facturer(monde, "D-2", 2, "2026-10-09T09:00:00-04:00")
    # (2) la DÉPENSE SANS REÇU
    sans_recu = depenser(monde, "four-a", "carburant", "N-101", "2026-10-15", "250.00", recu=False)
    comptabiliser(monde)
    return {"sans_paiement": sans_paiement, "sans_recu": sans_recu}


def balance(monde, au):
    page = _utile(appeler(monde, "m5_lire_balance_verification", {"au": au, "limite": 20}))
    assert page["prochain_depart"] is None and page["equilibree"] is True
    return {c["compte"]: (D(c["total_debits"]), D(c["total_credits"])) for c in page["comptes"]}


# ==================================================================================================== les états
def test_etat_des_resultats_par_mois_aux_soldes_exacts_recoupes_par_le_grand_livre(monde):
    exercice(monde)
    attendu = {
        "2026-08": ("3000.00", "200.00", "2800.00"),
        "2026-09": ("7000.00", "3000.00", "4000.00"),
        "2026-10": ("6000.00", "1050.00", "4950.00"),
    }
    for mois, (produits, charges, net) in attendu.items():
        fin = {"2026-08": "2026-08-31", "2026-09": "2026-09-30", "2026-10": "2026-10-31"}[mois]
        etat = _utile(appeler(monde, "m5_etat_des_resultats", {"debut": mois + "-01", "fin": fin}))
        assert (etat["total_produits"], etat["total_charges"], etat["resultat_avant_impots"]) == (
            produits,
            charges,
            net,
        ), mois
        assert etat["statut"] == "BROUILLON" and "Brouillon préparatoire" in etat["mention_brouillon"]
        assert etat["mention_comptable"].startswith("À valider auprès d'un comptable (CPA)")
        assert etat["completude"]["brouillons_non_comptabilises"] == 0
    trimestre = _utile(appeler(monde, "m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-10-31"}))
    assert (trimestre["total_produits"], trimestre["total_charges"], trimestre["resultat_avant_impots"]) == (
        "16000.00",
        "4250.00",
        "11750.00",
    )
    par_compte = {x["compte"]: x["montant"] for x in trimestre["lignes"]}
    assert par_compte == {"4100": "16000.00", "5100": "3000.00", "5400": "450.00", "5500": "800.00"}

    # recoupement par une AUTRE voie : la balance de vérification du grand livre (crédits − débits des produits, etc.)
    b = balance(monde, "2026-10-31")
    assert b["4100"][1] - b["4100"][0] == D("16000.00")
    assert sum(b[c][0] - b[c][1] for c in ("5100", "5400", "5500")) == D("4250.00")
    # et par le grand livre d'un compte, ligne à ligne
    compte = _utile(
        appeler(
            monde,
            "m5_lire_grand_livre_compte",
            {"compte": "4100", "debut": "2026-08-01", "fin": "2026-10-31", "limite": 10},
        )
    )
    assert compte["total_credits"] == "16000.00" and compte["lignes_total"] == 5


def test_bilan_brouillon_aux_soldes_exacts_et_il_s_equilibre(monde):
    exercice(monde)
    bilan = _utile(appeler(monde, "m5_bilan_brouillon", {"au": "2026-10-31", "limite": 40}))
    assert (bilan["total_actif"], bilan["total_passif"], bilan["resultat_cumule_non_clos"]) == (
        "19032.45",
        "7282.45",
        "11750.00",
    )
    assert (
        bilan["total_passif_et_capitaux"] == "19032.45"
        and bilan["equilibre"] is True
        and bilan["ecart_equilibre"] == "0.00"
    )
    montants = {x["compte"]: x["montant"] for x in bilan["lignes"]}
    assert montants == {
        "1010": "14946.75",
        "1100": "3449.25",
        "1400": "212.50",
        "1410": "423.95",
        "2100": "4886.45",
        "2300": "800.00",
        "2310": "1596.00",
    }
    b = balance(monde, "2026-10-31")
    for compte, solde in (("1010", D("14946.75")), ("1100", D("3449.25")), ("2100", D("4886.45"))):
        debits, credits = b[compte]
        assert abs(debits - credits) == solde, compte
    # à la fin d'août, l'avenir n'est pas là : encaisse 3 449,25 ; clients 0 ; résultat 2 800,00
    aout = _utile(appeler(monde, "m5_bilan_brouillon", {"au": "2026-08-31", "limite": 40}))
    assert aout["resultat_cumule_non_clos"] == "2800.00" and aout["equilibre"] is True
    assert {x["compte"]: x["montant"] for x in aout["lignes"]}["1010"] == "3449.25"


def test_les_recus_se_rejouent_a_l_identique_et_sur_les_memes_registres(monde):
    exercice(monde)
    etat = _utile(appeler(monde, "m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-10-31"}))
    recu = etat["recu"]
    assert recu["moteur"] == "etat_des_resultats" and recu_calcul.verifier(recu) == (True, "")
    rejeu = _utile(appeler(monde, "m5_rejouer_rapport_financier", {"recu": recu}))
    assert rejeu["recu_valide"] is True and rejeu["rejoue"] is True
    # le même appel sur les mêmes registres redonne la MÊME empreinte ; un jour de plus dans la période en donne une
    # autre
    encore = _utile(appeler(monde, "m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-10-31"}))
    assert encore["recu"]["empreinte"] == recu["empreinte"]
    # un chiffre retouché est refusé
    retouche = copy.deepcopy(recu)
    retouche["resultat"]["total_produits"] = "17000.00"
    assert (
        _refus(appeler(monde, "m5_rejouer_rapport_financier", {"recu": retouche}))["code"]
        == "REJ-RAPPORT-RECU-INVALIDE"
    )
    retouche = copy.deepcopy(recu)
    produit = next(c for c in retouche["entrees"]["comptes"] if c["compte"] == "4100")
    produit["credit"] = "1.00"
    # entrées retouchées sans refaire les empreintes : refusé ; avec les empreintes refaites : le rejeu diffère
    assert (
        _refus(appeler(monde, "m5_rejouer_rapport_financier", {"recu": retouche}))["code"]
        == "REJ-RAPPORT-RECU-INVALIDE"
    )
    bilan = _utile(appeler(monde, "m5_bilan_brouillon", {"au": "2026-10-31", "limite": 40}))
    assert _utile(appeler(monde, "m5_rejouer_rapport_financier", {"recu": bilan["recu"]}))["rejoue"] is True


def tete_du_grand_livre():
    with stockage.transaction():
        registre_gl = m5_outils._registre_grand_livre()
        return {"registre": "grand_livre", "taille": registre_gl.taille(), "tete": registre_gl.tete()}


def test_chaque_rapport_cite_ses_sources_avec_la_taille_et_la_tete_des_registres_lus(monde):
    exercice(monde)
    gl = tete_du_grand_livre()
    assert gl["taille"] > 14 and gl["tete"]
    for nom, arguments in (
        ("m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-10-31"}),
        ("m5_bilan_brouillon", {"au": "2026-10-31"}),
    ):
        rapport = _utile(appeler(monde, nom, arguments))
        assert rapport["sources"] == [gl], nom
    # le pré-audit cite les cinq registres qu'il a lus
    controle = _utile(appeler(monde, "m5_controler_preaudit", {"aujourd_hui": "2026-11-12"}))
    sources = {x["registre"]: x for x in controle["sources"]}
    assert set(sources) == {
        "grand_livre",
        "factures",
        "comptes_a_payer",
        "operations_comptables",
        "numerotation_factures",
    }
    assert sources["grand_livre"] == gl and all(x["taille"] > 0 and x["tete"] for x in sources.values())
    # la rentabilité cite ses deux registres ; le budget le sien
    rentabilite = _utile(appeler(monde, "m5_rentabilite_par_axe", {"axe": "ville"}))
    assert {x["registre"] for x in rentabilite["sources"]} == {"rentabilite", "wct_recus"}
    assert all(x["taille"] >= 1 for x in rentabilite["sources"])
    decider(
        monde,
        "m5_etablir_budget",
        {"libelle": "B", "lignes": BUDGET, "motif": None, "version_attendue": 0, "horodatage": H},
        par="nathan",
    )
    budget = _utile(appeler(monde, "m5_budget_contre_reel", {"periode_debut": "2026-08", "periode_fin": "2026-10"}))
    assert {x["registre"] for x in budget["sources"]} == {"grand_livre", "budgets_declares"}
    # une écriture de plus change la tête citée, donc l'empreinte du reçu : le reçu dit sur QUELLES données il porte
    avant = _utile(appeler(monde, "m5_bilan_brouillon", {"au": "2026-10-31"}))
    _utile(
        appeler(
            monde,
            "m5_proposer_ecriture_comptable",
            {
                "date_effet": "2026-10-31",
                "libelle": "Brouillon (fictif)",
                "piece_type": "manuelle",
                "piece_reference": "B-9",
                "lignes": [
                    {"compte": "5990", "debit": "1.00", "credit": None},
                    {"compte": "1010", "debit": None, "credit": "1.00"},
                ],
                "horodatage": H,
            },
        )
    )
    apres = _utile(appeler(monde, "m5_bilan_brouillon", {"au": "2026-10-31"}))
    assert (
        apres["sources"][0]["tete"] != avant["sources"][0]["tete"]
        and apres["recu"]["empreinte"] != avant["recu"]["empreinte"]
    )
    assert apres["total_actif"] == avant["total_actif"]  # le brouillon n'est pas additionné, mais la source a changé


# ================================================================================== données déclarées absentes
def test_donnees_declarees_absentes_budget_couts_directs_dimension_et_seuils_disent_quoi_declarer_jamais_zero(monde):
    exercice(monde)
    # budget : aucun déclaré
    verdict = _refus(appeler(monde, "m5_budget_contre_reel", {"periode_debut": "2026-08", "periode_fin": "2026-10"}))
    assert verdict["code"] == "REJ-BUDGET-A-DECLARER" and "m5_etablir_budget" in verdict["detail"]
    assert _refus(appeler(monde, "m5_lire_budget", {}))["code"] == "REJ-BUDGET-A-DECLARER"
    # marge brute : comptes de coûts directs non déclarés
    etat = _utile(appeler(monde, "m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-10-31"}))
    assert (
        etat["marge_brute"]["statut"] == "NON_CALCULABLE" and "comptes_couts_directs" in etat["marge_brute"]["manque"]
    )
    assert "montant" not in etat["marge_brute"]
    # rentabilité : les chantiers sont à coût PARTIEL (ni matériaux de M6 ni taux horaire déclaré) -> rien n'est
    # regroupé
    for axe in ("service", "ville"):
        r = _utile(appeler(monde, "m5_rentabilite_par_axe", {"axe": axe}))
        assert r["statut"] == "NON_CALCULABLE" and r["groupes"] == [] and "total" not in r
        assert r["exclus_cout_partiel"] >= 1 or "aucune rentabilité" in r["manque"]
    # pré-audit : sans seuil déclaré, deux règles ne sont pas évaluées et une l'est en partie, et le disent
    controle = _utile(appeler(monde, "m5_controler_preaudit", {"aujourd_hui": "2026-11-12"}))
    non_evaluees = {r["regle"]: r["manque"] for r in controle["regles_non_evaluees"]}
    assert set(non_evaluees) == {"TRANSACTION_HORS_NORME", "CHANGEMENT_COMPTE_INHABITUEL"}
    assert (
        controle["par_regle"]["TRANSACTION_HORS_NORME"] is None
        and controle["par_regle"]["CHANGEMENT_COMPTE_INHABITUEL"] is None
    )
    assert [r["regle"] for r in controle["regles_partielles"]] == ["DOUBLON_PROBABLE"]


def test_la_marge_brute_se_calcule_des_que_les_comptes_de_couts_directs_sont_declares(monde):
    exercice(monde)
    declaration = yaml.safe_load(monde.manifeste.read_text(encoding="utf-8"))
    declaration["configuration"]["rapports"] = {"comptes_couts_directs": ["5100", "5500"]}
    monde.manifeste.write_text(yaml.safe_dump(declaration, allow_unicode=True), encoding="utf-8")
    etat = _utile(appeler(monde, "m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-10-31"}))
    # produits 16 000,00 − (3 000 + 800) = 12 200,00 -> 76,25 %
    assert etat["marge_brute"] == {
        "statut": "CALCULEE",
        "montant": "12200.00",
        "pourcentage_des_produits": "76.25",
        "comptes_couts_directs": ["5100", "5500"],
    }
    for mauvais in (["4100"], ["9999"], "5100", [], ["5100", "5100"]):
        declaration["configuration"]["rapports"] = {"comptes_couts_directs": mauvais}
        monde.manifeste.write_text(yaml.safe_dump(declaration, allow_unicode=True), encoding="utf-8")
        assert (
            _refus(appeler(monde, "m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-10-31"}))["code"]
            == "REJ-RAPPORT-COUTS-DIRECTS-INVALIDES"
        ), mauvais


# ======================================================================================================== budget
BUDGET = [
    *(
        {"compte": "4100", "mois": m, "montant": v}
        for m, v in (("2026-08", "3000.00"), ("2026-09", "6000.00"), ("2026-10", "7500.00"))
    ),
    {"compte": "5100", "mois": "2026-09", "montant": "1500.00"},
    {"compte": "5400", "mois": "2026-08", "montant": "200.00"},
    {"compte": "5400", "mois": "2026-10", "montant": "200.00"},
    {"compte": "5500", "mois": "2026-10", "montant": "1000.00"},
]


def test_budget_declare_par_une_personne_puis_compare_au_reel(monde):
    exercice(monde)
    arguments = {
        "libelle": "Budget d'été 2026",
        "lignes": BUDGET,
        "motif": None,
        "version_attendue": 0,
        "horodatage": H,
    }
    # un agent seul ne déclare rien ; la demande attend une personne (N3)
    capacites = Capacites({M5: monde.dep5}, stockage.transaction)
    assert capacites.appeler("m5_etablir_budget", arguments)["statut"] == "en_attente_approbation"
    assert registre("budgets_declares") == []
    assert _refus(appeler(monde, "m5_etablir_budget", arguments))["code"] == "REJ-BUDGET-HUMAIN-REQUIS"
    declare = _executee(decider(monde, "m5_etablir_budget", arguments, par="nathan"))
    assert declare["statut"] == "ecrit" and declare["version"] == 1 and declare["mois_debut"] == "2026-08"
    assert declare["declare_par"]["role"] in ("nathan_owner", "admin") and len(registre("budgets_declares")) == 1

    r = _utile(appeler(monde, "m5_budget_contre_reel", {"periode_debut": "2026-08", "periode_fin": "2026-10"}))
    par = {x["compte"]: x for x in r["lignes"]}
    assert (par["4100"]["budget"], par["4100"]["reel"], par["4100"]["ecart"], par["4100"]["sens"]) == (
        "16500.00",
        "16000.00",
        "-500.00",
        "DEFAVORABLE",
    )
    assert par["4100"]["ecart_pct_du_budget"] == "-3.03"
    # le doublon pèse sur les matériaux : budget 1 500,00, réel 3 000,00
    assert (par["5100"]["budget"], par["5100"]["reel"], par["5100"]["ecart"], par["5100"]["sens"]) == (
        "1500.00",
        "3000.00",
        "1500.00",
        "DEFAVORABLE",
    )
    assert par["5100"]["ecart_pct_du_budget"] == "100.00"
    assert (par["5400"]["budget"], par["5400"]["reel"], par["5400"]["ecart"]) == ("400.00", "450.00", "50.00")
    assert (par["5500"]["reel"], par["5500"]["ecart"], par["5500"]["sens"]) == ("800.00", "-200.00", "FAVORABLE")
    assert (
        r["totaux"]["resultat_budgete"] == "13600.00"
        and r["totaux"]["resultat_reel_des_comptes_budgetes"] == "11750.00"
    )
    assert r["totaux"]["ecart_resultat"] == "-1850.00" and r["non_budgetes"] == [] and r["mois_sans_budget"] == []
    assert r["statut"] == "CALCULEE" and r["budget"]["version"] == 1
    # un mois hors du budget est nommé, jamais comparé à zéro
    hors = _utile(appeler(monde, "m5_budget_contre_reel", {"periode_debut": "2026-08", "periode_fin": "2026-11"}))
    assert hors["mois_sans_budget"] == ["2026-11"] and hors["mois_compares"] == ["2026-08", "2026-09", "2026-10"]
    assert (
        _utile(appeler(monde, "m5_budget_contre_reel", {"periode_debut": "2026-11", "periode_fin": "2026-11"}))[
            "statut"
        ]
        == "NON_CALCULABLE"
    )
    # redéclarer le même contenu ne crée rien ; une version révisée exige un motif ; le passé reste lisible
    assert (
        _executee(decider(monde, "m5_etablir_budget", {**arguments, "version_attendue": 1}, par="nathan"))["statut"]
        == "deja"
    )
    assert len(registre("budgets_declares")) == 1
    revise = [*BUDGET, {"compte": "5990", "mois": "2026-10", "montant": "100.00"}]
    sans_motif = decider(
        monde, "m5_etablir_budget", {**arguments, "lignes": revise, "version_attendue": 1}, par="nathan"
    )
    assert sans_motif["statut"] == "echec" or sans_motif["reponse"]["resultat"]["accepte"] is False
    assert len(registre("budgets_declares")) == 1
    v2 = _executee(
        decider(
            monde,
            "m5_etablir_budget",
            {**arguments, "lignes": revise, "motif": "Frais divers ajoutés", "version_attendue": 1},
            par="nathan",
        )
    )
    assert v2["version"] == 2 and len(registre("budgets_declares")) == 2
    lecture = _utile(appeler(monde, "m5_lire_budget", {"limite": 3}))
    assert [v["version"] for v in lecture["versions"]] == [1, 2] and lecture["lignes_total"] == 8
    # une déclaration concurrente (version attendue périmée) est refusée
    perimee = decider(
        monde, "m5_etablir_budget", {**arguments, "lignes": revise, "motif": "x", "version_attendue": 1}, par="nathan"
    )
    assert perimee["reponse"]["resultat"]["verdict"]["code"] == "REJ-BUDGET-VERSION-ATTENDUE"


def test_un_budget_mal_forme_est_refuse_et_n_ecrit_rien(monde):
    exercice(monde)
    base = {"libelle": "B", "motif": None, "version_attendue": 0, "horodatage": H}
    for lignes, code in (
        ([{"compte": "1010", "mois": "2026-08", "montant": "10.00"}], "REJ-BUDGET-COMPTE-INVALIDE"),
        ([{"compte": "4100", "mois": "2026-08", "montant": "10.001"}], "REJ-BUDGET-MONTANT-INVALIDE"),
        ([{"compte": "4100", "mois": "2026-08", "montant": "-5"}], "REJ-BUDGET-MONTANT-INVALIDE"),
        ([{"compte": "4100", "mois": "2026-13", "montant": "5.00"}], "REJ-BUDGET-MOIS-INVALIDE"),
        ([{"compte": "4100", "mois": "2026-08", "montant": "5.00"}] * 2, "REJ-BUDGET-LIGNE-DOUBLE"),
    ):
        decision = decider(monde, "m5_etablir_budget", {**base, "lignes": lignes}, par="nathan")
        assert decision["reponse"]["resultat"]["verdict"]["code"] == code, (lignes, decision)
    assert registre("budgets_declares") == []


# ==================================================================================================== pré-audit
def constats_attendus(monde, ids):
    return {
        ("DOUBLON_PROBABLE", "four-b"),
        ("DEPENSE_SANS_RECU", ids["sans_recu"]),
        ("FACTURE_SANS_PAIEMENT", ids["sans_paiement"]),
    }


def lire_controle(monde, jour="2026-11-12"):
    """Le contrôle, page par page (la réponse d'un outil reste sous la limite du socle), recollé."""
    depart, constats, premiere = 0, [], None
    while depart is not None:
        page = _utile(appeler(monde, "m5_controler_preaudit", {"aujourd_hui": jour, "depart": depart}))
        premiere = premiere or page
        constats += page["constats"]
        depart = page["prochain_depart"]
    return {**premiere, "constats": constats}


def test_le_preaudit_sort_exactement_les_trois_anomalies_injectees_sans_fausse_alerte(monde):
    ids = exercice(monde)
    controle = lire_controle(monde)
    assert controle["statut"] == "CONTROLE" and controle["total"] == 3
    assert controle["par_regle"]["DOUBLON_PROBABLE"] == 1 and controle["par_regle"]["DEPENSE_SANS_RECU"] == 1
    assert controle["par_regle"]["FACTURE_SANS_PAIEMENT"] == 1
    # toutes les AUTRES règles évaluées donnent zéro (un vrai zéro : elles sont évaluées)
    zero = {
        r: n
        for r, n in controle["par_regle"].items()
        if r not in ("DOUBLON_PROBABLE", "DEPENSE_SANS_RECU", "FACTURE_SANS_PAIEMENT")
    }
    assert {r for r, n in zero.items() if n == 0} == {
        "PAIEMENT_SANS_FACTURE",
        "TAXE_INCOHERENTE",
        "FACTURE_MODIFIEE",
        "PISTE_AUDIT_INCOMPLETE",
        "DOCUMENT_MANQUANT",
    }
    # le doublon : les DEUX factures de matériaux du 14 septembre
    doublon = next(k for k in controle["constats"] if k["regle"] == "DOUBLON_PROBABLE")
    assert len(doublon["sources"]) == 2 and doublon["montant_cad"] == "1500.00" and doublon["gravite"] == "haute"
    assert "N-200" in doublon["raison"] and "N-200B" in doublon["raison"]
    sans_recu = next(k for k in controle["constats"] if k["regle"] == "DEPENSE_SANS_RECU")
    assert sans_recu["sources"] == [{"registre": "comptes_a_payer", "reference": ids["sans_recu"]}]
    assert sans_recu["montant_cad"] == "250.00" and "N-101" in sans_recu["raison"]
    impayee = next(k for k in controle["constats"] if k["regle"] == "FACTURE_SANS_PAIEMENT")
    assert impayee["sources"] == [{"registre": "factures", "reference": ids["sans_paiement"]}]
    assert (
        impayee["montant_cad"] == "3449.25" and "4 jour(s)" in impayee["raison"] and "2026-11-08" in impayee["raison"]
    )
    # jamais exécuté : chaque constat propose une action et dit qu'elle n'a pas été faite
    assert all(k["action_executee"] is False and k["action_proposee"] for k in controle["constats"])
    # aucune écriture, aucune relance, aucune annulation n'a été faite par le contrôle
    assert registre("operations_comptables") != [] and not any(
        m["type_entree"] == "op_relance_preparee" for m in registre("operations_comptables")
    )
    assert not any(m["type_entree"] == "annulation_facture_fournisseur" for m in registre("comptes_a_payer"))


def test_le_preaudit_ne_voit_rien_avant_l_echeance_et_le_jour_meme(monde):
    ids = exercice(monde)
    assert (
        lire_controle(monde, "2026-11-08")["par_regle"]["FACTURE_SANS_PAIEMENT"] == 0
    )  # le jour de l'échéance : pas en retard
    assert lire_controle(monde, "2026-11-09")["par_regle"]["FACTURE_SANS_PAIEMENT"] == 1
    assert ids


def test_le_preaudit_apres_declaration_des_seuils_par_la_direction_reste_exactement_trois(monde):
    ids = exercice(monde)
    avant = lire_controle(monde)
    deps = monde.bus.departements
    with stockage.transaction() as cnx:
        for cle, valeur in (
            ("m5.seuil_transaction_hors_norme_cad", "10000"),
            ("m5.jours_fenetre_doublon", 3),
            ("m5.historique_changement_compte", 2),
        ):
            assert ra.resultat(ra.adopter(cnx, deps, cle, valeur))
    apres = lire_controle(monde)
    assert apres["regles_non_evaluees"] == [] and apres["regles_partielles"] == [] and apres["total"] == 3
    assert all(n is not None for n in apres["par_regle"].values())
    assert {
        (k["regle"], k["sources"][0]["reference"]) for k in apres["constats"] if k["regle"] != "DOUBLON_PROBABLE"
    } == {("DEPENSE_SANS_RECU", ids["sans_recu"]), ("FACTURE_SANS_PAIEMENT", ids["sans_paiement"])}
    assert avant["total"] == apres["total"] == 3
    # un seuil plus bas fait paraître les transactions qu'il vise, et seulement elles (4 599,00 $ : la facture de 4
    # 000 $ HT)
    with stockage.transaction() as cnx:
        assert ra.resultat(ra.adopter(cnx, deps, "m5.seuil_transaction_hors_norme_cad", "4000"))
    bas = lire_controle(monde)
    hors = [k for k in bas["constats"] if k["regle"] == "TRANSACTION_HORS_NORME"]
    assert bas["par_regle"]["TRANSACTION_HORS_NORME"] == len(hors) == 1 and hors[0]["montant_cad"] == "4599.00"
    assert hors[0]["gravite"] == "faible" and bas["total"] == 4
    # le retour arrière de la direction remet la règle « non évaluée » : jamais une règle évaluée à zéro
    with stockage.transaction() as cnx:
        assert ra.resultat(ra.revenir(cnx, deps, "m5.seuil_transaction_hors_norme_cad"))
        assert ra.resultat(ra.revenir(cnx, deps, "m5.seuil_transaction_hors_norme_cad"))
    assert lire_controle(monde)["par_regle"]["TRANSACTION_HORS_NORME"] is None


def test_les_anomalies_se_levent_quand_la_cause_est_corrigee(monde):
    ids = exercice(monde)
    # on joint le reçu, on annule le doublon (N4, humain), on paie la facture : le contrôle ne dit plus rien
    deposer_piece("N-101.pdf", "%PDF recu fictif N-101")
    _utile(
        appeler(
            monde,
            "m5_lier_piece_justificative",
            {
                "cible_type": "facture_fournisseur",
                "cible_id": ids["sans_recu"],
                "fichier": "N-101.pdf",
                "horodatage": H,
            },
        )
    )
    doublon = next(k for k in lire_controle(monde)["constats"] if k["regle"] == "DOUBLON_PROBABLE")
    en_trop = max(s["reference"] for s in doublon["sources"])
    annulation = decider(
        monde,
        "m5_annuler_facture_fournisseur",
        {"facture_fournisseur_id": en_trop, "motif": "Doublon (fictif)", "horodatage": H, "revision_attendue": 0},
    )
    assert annulation["statut"] == "executee", annulation
    restant = lire_controle(monde)
    # la facture annulée a encore son écriture : le contrôle le voit (FACTURE_MODIFIEE, et ses taxes sur intrants
    # n'ont plus de
    # facture vivante derrière : TAXE_INCOHERENTE) tant qu'elle n'est pas contre-passée
    assert {k["regle"] for k in restant["constats"]} == {
        "FACTURE_SANS_PAIEMENT",
        "FACTURE_MODIFIEE",
        "TAXE_INCOHERENTE",
    }
    ecriture = next(i for i, e in _etat_gl()["ecritures"].items() if e["piece"]["reference"] == en_trop)
    contre = _utile(
        appeler(
            monde,
            "m5_proposer_contre_passation",
            {"ecriture_id": ecriture, "date_effet": "2026-10-31", "motif": "Doublon annulé (fictif)", "horodatage": H},
        )
    )
    assert (
        decider(
            monde, "m5_valider_ecriture_comptable", {"ecriture_id": contre["ecriture"]["ecriture_id"], "horodatage": H}
        )["statut"]
        == "executee"
    )
    assert {k["regle"] for k in lire_controle(monde)["constats"]} == {"FACTURE_SANS_PAIEMENT"}
    # et l'état des résultats d'octobre... le doublon (1 500,00 de septembre) est sorti des charges de la
    # contre-passation
    etat = _utile(appeler(monde, "m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-10-31"}))
    assert etat["total_charges"] == "2750.00" and etat["resultat_avant_impots"] == "13250.00"


def _etat_gl():
    from m5_financecore import grand_livre

    with stockage.transaction():
        return grand_livre.etat_grand_livre(m5_outils._registre_grand_livre().lire())


# ===================================================================================== le constat planifié vers M8
CONSTAT = "m5.constat.preaudit"
TYPE = "m5.preaudit_constate"


def test_le_constat_planifie_inactif_par_defaut_ombre_aurait_actif_publie_une_fois_par_creneau_et_m8_le_montre(monde):
    ids = exercice(monde)
    # -- inactif par défaut : rien ne part
    assert monde.tour(1)[CONSTAT] == {"statut": "inactif"}
    assert monde.publies(TYPE) == []
    # -- ombre : le journal dit « aurait », rien n'est publié, aucun contrôle n'est lancé
    monde.activer("ombre", noms=(CONSTAT,))
    resume = monde.tour(1)[CONSTAT]
    assert resume["statut"] == "ombre"
    with stockage.transaction() as cnx:
        aurait = [j for j in journal.lire(cnx, CONSTAT, limite=100) if j["evenement"] == "aurait"]
    assert len(aurait) == 1 and aurait[0]["details"] == {"aurait": 1} and monde.publies(TYPE) == []
    monde.propager()
    assert monde.mesures()["m8_constats_preaudit"]["statut"] == "non_calculable"
    # -- actif : UN événement avec les comptes seulement
    monde.activer("actif", noms=(CONSTAT,))
    resume = monde.tour(1)[CONSTAT]
    assert (resume["statut"], resume["erreurs"]) == ("ok", 0), resume
    (publie,) = monde.publies(TYPE)
    charge = publie["charge"]
    assert publie["producteur"] == M5 and charge["date_reference"] == "2026-11-12"
    assert charge["constats_total"] == 3 and charge["constats_par_gravite"] == {"haute": 1, "moyenne": 2, "faible": 0}
    assert (
        charge["constats_par_regle"]["DOUBLON_PROBABLE"] == 1
        and charge["constats_par_regle"]["TRANSACTION_HORS_NORME"] is None
    )
    assert charge["regles_non_evaluees"] == ["TRANSACTION_HORS_NORME", "CHANGEMENT_COMPTE_INHABITUEL"]
    assert charge["regles_partielles"] == ["DOUBLON_PROBABLE"]
    texte = json.dumps(charge, ensure_ascii=False)
    for interdit in (
        *ids.values(),
        "four-",
        "N-100",
        "N-200",
        "N-101",
        "fac-",
        "1500",
        "3449",
        "250.00",
        "gle-",
        "Lévis",
        "raison",
        "action",
    ):
        assert interdit not in texte, interdit
    # -- le même créneau : aucun nouvel événement (idempotence par créneau) ; le suivant en publie un autre
    assert monde.tour(0)[CONSTAT]["statut"] == "pas_echu"
    assert len(monde.publies(TYPE)) == 1
    livraison = monde.propager()
    assert livraison["echecs"] == 0 and livraison["quarantaines"] == 0, livraison
    assert monde.bus.quarantaines() == [] and monde.bus.ecritures_hors_propriete() == []
    # -- M8 : la mesure, la valeur exacte, la couverture partielle dite (2 règles non évaluées, 1 partielle), la
    # provenance
    mesure = monde.mesures()["m8_constats_preaudit"]
    assert mesure["statut"] == "calculee" and mesure["valeur"] == "3"
    assert mesure["couverture"] == "partielle" and mesure["a_jour"] is True and mesure["fraicheur"] == "a_jour"
    assert mesure["proprietaire"] == M5 and mesure["unite"] == "constats"
    # -- les seuils sont déclarés : le constat suivant (créneau suivant) est complet, même total
    with stockage.transaction() as cnx:
        for cle, valeur in (
            ("m5.seuil_transaction_hors_norme_cad", "10000"),
            ("m5.jours_fenetre_doublon", 3),
            ("m5.historique_changement_compte", 2),
        ):
            ra.adopter(cnx, monde.bus.departements, cle, valeur)
    monde.tour(43200)
    assert len(monde.publies(TYPE)) == 2
    monde.propager()
    complet = monde.mesures()["m8_constats_preaudit"]
    assert complet["valeur"] == "3" and complet["couverture"] == "complete"
    # -- et ni montant ni identifiant dans le journal du planificateur
    with stockage.transaction() as cnx:
        journal_texte = json.dumps(journal.lire(cnx, CONSTAT, limite=500), ensure_ascii=False)
    for interdit in (*ids.values(), "1500", "3449", "four-"):
        assert interdit not in journal_texte


def test_une_panne_du_controle_est_comptee_et_n_arrete_pas_le_tour(monde, monkeypatch):
    exercice(monde)

    def panne(*args, **kwargs):
        raise RuntimeError("panne fictive du contrôle")

    monkeypatch.setattr(m5_outils, "_registre_grand_livre", panne)
    monde.activer("actif", noms=(CONSTAT,))
    resume = monde.tour(1)[CONSTAT]
    assert resume["statut"] == "erreur" and resume["code"] == "REJ-PLAN-DEFAUT-EXECUTEUR"
    assert monde.publies(TYPE) == []


def test_un_agent_seul_peut_controler_mais_aucun_appareil_n_y_a_acces(monde):
    exercice(monde)
    appareil = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
    for nom, arguments in (
        ("m5_controler_preaudit", {"aujourd_hui": "2026-11-12"}),
        ("m5_etat_des_resultats", {"debut": "2026-08-01", "fin": "2026-08-31"}),
        ("m5_bilan_brouillon", {"au": "2026-08-31"}),
        ("m5_budget_contre_reel", {"periode_debut": "2026-08", "periode_fin": "2026-08"}),
        ("m5_rapport_mensuel_direction", {"periode": "2026-08"}),
    ):
        assert _refus(appeler(monde, nom, arguments, appareil))["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE", nom


# ================================================================================ rapport mensuel de direction
def rapport_complet(monde, arguments):
    """Le rapport de direction, page par page (la réponse d'un outil reste sous la limite du socle), recollé."""
    depart, sections, premiere = 0, [], None
    while depart is not None:
        page = _utile(appeler(monde, "m5_rapport_mensuel_direction", {**arguments, "depart": depart}))
        premiere = premiere or page
        sections += page["sections"]
        depart = page["prochain_depart"]
    return {**premiere, "sections": sections}


def test_le_rapport_mensuel_distingue_faits_hypotheses_et_donnees_manquantes_et_chaque_section_a_son_recu(monde):
    exercice(monde)
    rapport = rapport_complet(monde, {"periode": "2026-10", "au": "2026-11-12"})
    assert rapport["statut"] == "BROUILLON" and "Brouillon préparatoire" in rapport["mention_brouillon"]
    sections = {s["id"]: s for s in rapport["sections"]}
    assert list(sections) == ["resultats", "bilan", "budget", "rentabilite_service", "rentabilite_ville", "preaudit"]
    faits = {f["libelle"]: f for f in sections["resultats"]["faits"]}
    assert faits["Produits du mois"]["valeur_cad"] == "6000.00" and faits["Charges du mois"]["valeur_cad"] == "1050.00"
    assert faits["Résultat avant impôts du mois"]["valeur_cad"] == "4950.00"
    assert faits["Résultat avant impôts du mois précédent (2026-09)"]["valeur_cad"] == "4000.00"
    assert faits["Variation du résultat avant le mois précédent"]["valeur_cad"] == "950.00"
    assert [m["code"] for m in sections["resultats"]["donnees_manquantes"]] == ["COUTS_DIRECTS"]
    assert sections["resultats"]["statut"] == "PARTIEL" and sections["resultats"]["hypotheses"]
    assert sections["bilan"]["statut"] == "CALCULE" and {
        f["libelle"]: f["valeur"] for f in sections["bilan"]["faits"] if "valeur" in f
    } == {"Le bilan s'équilibre": True}
    # budget absent : NON_CALCULABLE avec ce qu'il faut déclarer, aucun fait
    assert sections["budget"]["statut"] == "NON_CALCULABLE" and sections["budget"]["faits"] == []
    assert "m5_etablir_budget" in sections["budget"]["donnees_manquantes"][0]["a_declarer"]
    for axe in ("service", "ville"):
        assert (
            sections[f"rentabilite_{axe}"]["statut"] == "NON_CALCULABLE"
            and sections[f"rentabilite_{axe}"]["faits"] == []
        )
    assert sections["preaudit"]["statut"] == "PARTIEL" and {
        f["libelle"]: f["valeur"] for f in sections["preaudit"]["faits"]
    } == {"Constats ouverts": 3, "Constats de gravité haute": 1}
    assert {m["code"] for m in sections["preaudit"]["donnees_manquantes"]} == {
        "TRANSACTION_HORS_NORME",
        "CHANGEMENT_COMPTE_INHABITUEL",
    }
    # chaque section chiffrée renvoie à SON reçu, et ce reçu est celui que l'outil du rapport redonne
    direct = _utile(appeler(monde, "m5_etat_des_resultats", {"debut": "2026-10-01", "fin": "2026-10-31"}))
    assert sections["resultats"]["recu_empreinte"] == direct["recu"]["empreinte"]
    assert recu_calcul.verifier(rapport["recu"]) == (True, "")
    # un budget déclaré fait passer la section en CALCULE
    decider(
        monde,
        "m5_etablir_budget",
        {"libelle": "B", "lignes": BUDGET, "motif": None, "version_attendue": 0, "horodatage": H},
        par="nathan",
    )
    avec = rapport_complet(monde, {"periode": "2026-10", "au": "2026-11-12"})
    budget = next(s for s in avec["sections"] if s["id"] == "budget")
    assert budget["statut"] == "CALCULE" and {
        f["libelle"]: f["valeur_cad"] for f in budget["faits"] if "valeur_cad" in f
    } == {
        "Résultat budgété (comptes budgétés)": "6300.00",
        "Résultat réel (comptes budgétés)": "4950.00",
        "Écart du résultat": "-1350.00",
    }


def test_la_rentabilite_par_ville_et_par_service_se_calcule_quand_les_dimensions_et_le_cout_complet_existent(monde):
    exercice(monde)
    # les dimensions publiées par M4 ont été gardées telles quelles
    wct = {m["devis_id"]: m for m in registre("wct_recus")}
    assert (wct["D-1"]["ville"], wct["D-1"]["service"]) == ("Lévis", "gouttieres")
    assert (wct["D-2"]["ville"], wct["D-2"]["service"]) == ("Québec", "gouttieres")
    # le coût réel de chaque chantier est ici PARTIEL (pas de matériaux M6 ni de taux horaire) : rien n'est regroupé
    r = _utile(appeler(monde, "m5_rentabilite_par_axe", {"axe": "ville"}))
    assert r["statut"] == "NON_CALCULABLE" and r["groupes"] == [] and r["exclus_cout_partiel"] == 2
    # des rentabilités à coût COMPLET tracées par le moteur (registre de M5) donnent les groupes, calculés à la main
    for devis, prix, cout in (("D-1", "10000.00", "7000.00"), ("D-2", "6000.00", "6600.00")):
        tracer_rentabilite(devis, prix, cout)
    par_ville = _utile(appeler(monde, "m5_rentabilite_par_axe", {"axe": "ville"}))
    groupes = {g["ville"]: g for g in par_ville["groupes"]}
    assert groupes["Lévis"]["marge_reelle"] == "3000.00" and groupes["Lévis"]["marge_pct_des_ventes"] == "30.00"
    assert groupes["Québec"]["marge_reelle"] == "-600.00" and groupes["Québec"]["marge_pct_des_ventes"] == "-10.00"
    assert par_ville["total"]["marge_reelle"] == "2400.00" and par_ville["total"]["ventes"] == "16000.00"
    par_service = _utile(appeler(monde, "m5_rentabilite_par_axe", {"axe": "service"}))
    assert [g["service"] for g in par_service["groupes"]] == ["gouttieres"] and par_service["groupes"][0][
        "chantiers"
    ] == 2
    assert (
        par_service["groupes"][0]["marge_reelle"] == "2400.00"
        and par_service["groupes"][0]["marge_pct_des_ventes"] == "15.00"
    )
    # un chantier sans dimension est compté à part, jamais attribué
    devis_et_travaux("D-3", "1000.00")
    tracer_rentabilite("D-3", "1000.00", "900.00")
    assert (
        _utile(appeler(monde, "m5_rentabilite_par_axe", {"axe": "ville"}))["sans_dimension"] == 1
    )  # D-3 sans WCT : dimension absente
    # la période filtre sur la date de fin des travaux
    octobre = _utile(
        appeler(monde, "m5_rentabilite_par_axe", {"axe": "ville", "debut": "2026-10-06", "fin": "2026-10-31"})
    )
    assert [g["ville"] for g in octobre["groupes"]] == ["Québec"]


def tracer_rentabilite(devis_id, prix, cout):
    """Une rentabilité à coût COMPLET et prix définitif, tracée comme le fait `cout_reel.construire_trace`."""
    from m5_financecore import cout_reel

    marge = D(prix) - D(cout)
    rentabilite = {
        "devis_id": devis_id,
        "chantier_id": "CH-" + devis_id,
        "wct_id": "wct-" + devis_id,
        "verdict": "CALCULEE",
        "devise": "CAD",
        "facture_id": None,
        "statut_facture": "PAYEE",
        "prix_definitif": True,
        "prix_facture": D(prix),
        "cout_reel": {"complet": True, "cout_total": D(cout), "cout_total_connu": D(cout)},
        "marge_reelle": marge,
        "version_entrees": "v" * 64,
        cout_reel.CHAMP_EMPREINTE_HORS_VENTILATION: "h" * 64,
    }
    trace = cout_reel.construire_trace(
        rentabilite, "2026-10-08T16:00:00-04:00" if devis_id == "D-2" else "2026-10-05T16:00:00-04:00"
    )
    with stockage.transaction():
        stockage.maillons(M5, "rentabilite").append(json.loads(json.dumps(trace, default=str)))
