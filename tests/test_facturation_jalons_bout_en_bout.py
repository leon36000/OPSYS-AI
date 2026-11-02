"""Facturation par jalons de bout en bout (M5-FACT-1, M5-FACT-2) : le parcours entier sur le VRAI bus, le VRAI sas
d'approbation, les VRAIS outils de M5 et les VRAIS consommateurs de M2 et M8, sur une base SQLite temporaire.

devis accepté (bus) -> plan à 3 jalons déclaré par une personne (N3, somme au cent, taxes du moteur fiscal) -> facture
d'acompte BROUILLON -> approbation humaine (N4) -> numéro suivant, sans trou après une panne/reprise et sous deux
émissions simultanées -> échéance dépassée -> statut « en retard » (horloge injectée) -> relance de créance préparée
(M5 -> M2 par le bus) -> paiement partiel (refusé, la relance reste) -> paiement total (N5, la relance est levée) -> PDF
scellé et rejouable.

Seuls manquent le réseau, QuickBooks, Stripe et un serveur courriel : rien n'est envoyé, rien n'est payé pour de vrai.
Entreprise, client, personnes, identifiants et montants FICTIFS (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import io
import threading
from decimal import Decimal
from pathlib import Path

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
import yaml
from m2_revenue_crm import faits_interconnexion as fi
from m2_revenue_crm import outils as outils_m2
from m5_financecore import facturation
from m5_financecore import outils as m5_outils
from m5_financecore import registre as registre_m5
from sqlalchemy import select

from opsys import approbations, evenements, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.outils import executer_atomique
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
D = Decimal
M2, M3, M4, M5, M8 = "m02-revenue-crm", "m03-estimation", "m04-field-ops", "m05-financecore", "m08-analytics"
EMISSION_1 = "2026-11-02T10:00:00-05:00"  # acompte, payable à la réception
EMISSION_2 = "2026-11-25T09:00:00-05:00"  # jalons 2 et 3, net 30 jours
ENTREPRISE = {
    "raison_sociale": "Entreprise Fictive Inc.",
    "adresse": ["123, rue Exemple", "Québec (Québec) A1A 1A1"],
    "numero_tps": "123456789 RT0001",
    "numero_tvq": "1234567890 TQ0001",
}
CLIENT = {"nom": "Madame Cliente Fictive", "adresse": ["45, avenue Exemple", "Lévis (Québec) B2B 2B2"]}
CONFIG = {
    "operations": {"relances": {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]}},
    "facturation": {
        "numerotation": {"prefixe": "F-", "premier_numero": 1000, "largeur": 5},
        "conditions_paiement": {"delai_jours": 30},
        "entreprise": ENTREPRISE,
    },
}
JALONS = [
    {
        "libelle": "Acompte à l'acceptation",
        "declencheur": "acceptation",
        "pourcentage": "30",
        "delai_paiement_jours": 0,
    },
    {"libelle": "Mi-chantier", "declencheur": "chantier", "pourcentage": "40"},
    {"libelle": "Solde à la fin des travaux", "declencheur": "fin_travaux", "pourcentage": "30"},
]
ATTESTATION = {
    "nom": "Alex Comptable (fictif)",
    "profession": "CPA",
    "reference_document": "DEPOT-BANCAIRE-4521-fictif",
}


class _SansAmont:
    """Un département RÉEL qui ne consomme pas l'amont de ce parcours (devis accepté, travaux terminés) : M2 et M4 ont
    leurs propres preuves ; ici seuls M5, M2 (relances de créance) et M8 (factures émises) nous intéressent."""

    AMONT = frozenset({"m3.devis_accepte", "m4.travaux_termines"})

    def __init__(self, departement):
        self._departement = departement

    def __getattr__(self, nom):
        return getattr(self._departement, nom)

    @property
    def evenements_consomme(self):
        return tuple(t for t in self._departement.evenements_consomme if t not in self.AMONT)

    def charger_consommateurs(self):
        return {t: f for t, f in self._departement.charger_consommateurs().items() if t not in self.AMONT}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M2, M3, M4, M5, M8))
    m.dep_m5 = m.departements[M5]  # le vrai manifeste, pour la file d'approbation
    for ident in (M2, M3, M4, M8):
        m.departements[ident] = _SansAmont(m.departements[ident])
    m.surveiller(monkeypatch)
    manifeste = tmp_path / "department-m5.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": CONFIG}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234", ["nathan_owner", "admin"]
        )
        identite.creer_personne(
            cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234", ["finance", "admin"]
        )
    m.manifeste = manifeste
    yield m
    im.demonter()


@pytest.fixture
def m5():
    return {o.nom: o for o in m5_outils.outils()}


# ---------------------------------------------------------------------------------------------------- assistants
def _outil(m5, nom, arguments):
    reponse = executer_atomique(m5[nom], arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _utile(m5, nom, arguments):
    resultat = _outil(m5, nom, arguments)
    assert resultat["accepte"] is True, resultat
    return resultat["resultat"]


def _decider(monde, nom, arguments, *, par="comptable", attestation=None):
    """Un agent PROPOSE (sas du socle) ; une personne DÉCIDE. Rend la décision (statut, réponse de l'outil)."""
    capacites = Capacites({M5: monde.dep_m5}, stockage.transaction)
    demande = capacites.appeler(nom, arguments)
    assert demande["statut"] == "en_attente_approbation", demande
    disponibles = outils_executables({M5: monde.dep_m5}, stockage.transaction)
    with stockage.transaction() as cnx:
        options = {"attestation": attestation} if attestation is not None else {}
        return approbations.decider(cnx, demande["demande_id"], True, par, disponibles, {M5: monde.dep_m5}, **options)


def _etat(facture_id):
    with stockage.transaction():
        return facturation._etat_facture(m5_outils._registre_factures(None), facture_id)


def _registre(departement, nom):
    with stockage.transaction():
        return list(stockage.maillons(departement, nom))


def _ouvertes(monde):
    with stockage.transaction():
        return outils_m2._creances_recues()


def _publier_devis(monde, devis_id="D-1", prix="10000.00"):
    evenements.publier(
        "m3.devis_accepte",
        M3,
        ch.devis_accepte(devis_id=devis_id, prix=prix),
        evenement_id=f"m3-devis-accepte-{devis_id}",
    )
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, monde.quarantaines()


def _publier_travaux_termines(monde, devis_id="D-1"):
    evenements.publier(
        "m4.travaux_termines",
        M4,
        ch.travaux_termines(wct_id="wct-" + devis_id, devis_id=devis_id),
        evenement_id=f"m4-travaux-{devis_id}",
    )
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0


def _facture_id(plan_id, rang):
    return f"fac-{plan_id}-J{rang}"


# ============================================================================================ le parcours entier
def test_devis_accepte_a_paiement_total_de_bout_en_bout(monde, m5, tmp_path):
    # 1. devis accepté reçu par le bus (le chantier n'existe pas encore : l'acompte se facture à l'acceptation)
    _publier_devis(monde)

    # 2. plan à 3 jalons DÉCLARÉ par une personne (N3) ; la somme tombe au cent, les taxes viennent du moteur
    decision = _decider(
        monde,
        "m5_etablir_plan_facturation",
        {"devis_id": "D-1", "jalons": JALONS, "chantier_id": "CH-FICTIF-1", "horodatage": EMISSION_1},
    )
    assert decision["statut"] == "executee"
    plan = decision["reponse"]["resultat"]["resultat"]
    plan_id = plan["plan_id"]
    montants = [D(j["montant_avant_taxes"]) for j in plan["jalons"]]
    assert montants == [D("3000.00"), D("4000.00"), D("3000.00")] and sum(montants) == D("10000.00")
    assert plan["declare_par"] == {"par": "comptable", "role": "finance"}

    # 3. facture d'acompte BROUILLON : rien n'est numéroté ni envoyé, taxes TPS 5 % / TVQ 9,975 %
    brouillon = _utile(m5, "m5_creer_facture_jalon", {"devis_id": "D-1", "rang": 1, "horodatage": EMISSION_1})[
        "facture"
    ]
    assert brouillon["statut"] == "BROUILLON" and brouillon["numero_facture"] is None
    assert (brouillon["montant_avant_taxes"], brouillon["total_taxes"], brouillon["montant_apres_taxes"]) == (
        "3000.00",
        "449.25",
        "3449.25",
    )
    acompte = _facture_id(plan_id, 1)

    # 4. l'émission exige la décision d'une personne ; un appel direct de l'agent est refusé
    direct = _outil(m5, "m5_envoyer_facture", {"facture_id": acompte, "horodatage": EMISSION_1})
    assert direct["accepte"] is False and direct["verdict"]["code"] == "REJ-OPS-HUMAIN-REQUIS"
    assert _etat(acompte)["statut"] == "BROUILLON" and _registre(M5, "numerotation_factures") == []

    # 5. PANNE pendant l'émission : le numéro n'est pas consommé ; la reprise reçoit le PREMIER numéro de la suite
    original = MaillonsDurables.append

    def panne(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (M5, "factures") and maillon.get("statut") == "ENVOYEE":
            raise ConnectionError("panne simulée entre le numéro et le statut")
        return original(self, maillon, rang_attendu=rang_attendu)

    MaillonsDurables.append = panne
    try:
        echec = _decider(monde, "m5_envoyer_facture", {"facture_id": acompte, "horodatage": EMISSION_1})
    finally:
        MaillonsDurables.append = original
    assert echec["statut"] == "echec" and _registre(M5, "numerotation_factures") == []
    assert _etat(acompte)["statut"] == "BROUILLON"
    emise = _decider(monde, "m5_envoyer_facture", {"facture_id": acompte, "horodatage": EMISSION_1})
    assert emise["statut"] == "executee"
    etat = _etat(acompte)
    assert (etat["statut"], etat["numero_facture"], etat["echeance"]) == ("ENVOYEE", "F-01000", "2026-11-02")

    # 6. échéance dépassée -> « en retard » à la date INJECTÉE ; le statut enregistré ne change pas
    lecture = {"role": "admin", "autorise_couts": True}
    le_jour = _utile(m5, "m5_lire_comptes_a_recevoir", {**lecture, "aujourd_hui": "2026-11-02"})
    assert le_jour["factures"][0]["statut_effectif"] == "ENVOYEE" and le_jour["en_retard"]["nombre"] == 0
    en_retard = _utile(m5, "m5_lire_comptes_a_recevoir", {**lecture, "aujourd_hui": "2026-11-10"})
    assert (en_retard["factures"][0]["statut_effectif"], en_retard["factures"][0]["jours_de_retard"]) == (
        "EN_RETARD",
        8,
    )
    assert _etat(acompte)["statut"] == "ENVOYEE"

    # 7. relance de créance PRÉPARÉE (brouillon, rien d'envoyé) -> M2 par le bus, avec l'échéance propre de la facture
    relances = _utile(m5, "m5_preparer_relances_clients", {"aujourd_hui": "2026-11-10", "horodatage": EMISSION_1})
    assert relances["creees"] == 1 and relances["brouillons"][0]["jours_retard"] == 8
    assert "F-01000" in relances["brouillons"][0]["brouillon"]
    monde.repartir()
    assert [c["facture_id"] for c in _ouvertes(monde)] == [acompte]

    # 8. paiement PARTIEL (N5, propriétaire + attestation) : refusé, jamais PAYEE ; la relance ne se lève pas
    partiel = _decider(
        monde,
        "m5_enregistrer_paiement_facture",
        {
            "facture_id": acompte,
            "montant_paye": "1000.00",
            "approbateur": "Nathan (fictif)",
            "horodatage": "2026-11-12T09:00:00-05:00",
        },
        par="nathan",
        attestation=ATTESTATION,
    )
    assert partiel["reponse"]["resultat"]["verdict"]["code"] == "REJ-FACTURE-PAIEMENT-PARTIEL"
    assert _etat(acompte)["statut"] == "ENVOYEE"
    _utile(m5, "m5_constater_factures_emises", {"horodatage": EMISSION_1})
    monde.repartir()
    assert [c["facture_id"] for c in _ouvertes(monde)] == [acompte]
    assert monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 0

    # 9. jalon 2 et fin des travaux ; le solde ne se facture pas d'avance
    _utile(m5, "m5_creer_facture_jalon", {"devis_id": "D-1", "rang": 2, "horodatage": EMISSION_2})
    avance = _outil(m5, "m5_creer_facture_jalon", {"devis_id": "D-1", "rang": 3, "horodatage": EMISSION_2})
    assert avance["verdict"]["code"] == "REJ-PLAN-TRAVAUX-NON-TERMINES"
    _publier_travaux_termines(monde)
    assert _registre(M5, "factures")[-1]["facture_id"] == _facture_id(plan_id, 2)  # pas de facture globale automatique
    _utile(m5, "m5_creer_facture_jalon", {"devis_id": "D-1", "rang": 3, "horodatage": EMISSION_2})

    # 10. DEUX émissions SIMULTANÉES : deux numéros distincts, sans trou, quel que soit l'ordre
    capacites = Capacites({M5: monde.dep_m5}, stockage.transaction)
    demandes = [
        capacites.appeler("m5_envoyer_facture", {"facture_id": _facture_id(plan_id, r), "horodatage": EMISSION_2})
        for r in (2, 3)
    ]
    assert all(d["statut"] == "en_attente_approbation" for d in demandes)
    disponibles = outils_executables({M5: monde.dep_m5}, stockage.transaction)
    barriere, decisions, erreurs = threading.Barrier(2), [], []

    def decider_en_parallele(demande_id):
        try:
            barriere.wait(timeout=10)
            with stockage.transaction() as cnx:
                decisions.append(
                    approbations.decider(cnx, demande_id, True, "comptable", disponibles, {M5: monde.dep_m5})
                )
        except BaseException as erreur:  # noqa: BLE001
            erreurs.append(erreur)

    fils = [threading.Thread(target=decider_en_parallele, args=(d["demande_id"],)) for d in demandes]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=60)
    assert erreurs == [] and [d["statut"] for d in decisions] == ["executee", "executee"]
    stockage.liberer()
    numeros = {r: _etat(_facture_id(plan_id, r))["numero_facture"] for r in (2, 3)}
    assert sorted(numeros.values()) == ["F-01001", "F-01002"]
    suite = _registre(M5, "numerotation_factures")
    assert [m["sequence"] for m in suite] == [1000, 1001, 1002]
    verification = _utile(m5, "m5_verifier_numerotation_factures", {})
    assert verification["ok"] is True and (verification["premier"], verification["dernier"]) == (1000, 1002)
    assert registre_m5.Registre(maillons=suite).valider_chaine() == (True, "")
    assert _etat(_facture_id(plan_id, 2))["echeance"] == "2026-12-25" == _etat(_facture_id(plan_id, 3))["echeance"]

    # 11. paiement TOTAL de l'acompte (N5) : PAYEE ; le constat publié au bus lève la relance chez M2
    paye = _decider(
        monde,
        "m5_enregistrer_paiement_facture",
        {
            "facture_id": acompte,
            "montant_paye": "3449.25",
            "approbateur": "Nathan (fictif)",
            "horodatage": "2026-11-26T09:00:00-05:00",
        },
        par="nathan",
        attestation=ATTESTATION,
    )
    assert paye["statut"] == "executee" and _etat(acompte)["statut"] == "PAYEE"
    _utile(m5, "m5_constater_factures_emises", {"horodatage": EMISSION_2})
    resume = monde.repartir()
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    assert _ouvertes(monde) == [] and monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 1
    statuts_m8 = sorted(
        (f["statut"]) for f in monde.registre(M8, "faits_operations") if f["type_entree"] == "facture_emise"
    )
    # un constat par (facture, état) : l'acompte envoyé puis payé, les jalons 2 et 3 envoyés
    assert statuts_m8 == ["ENVOYEE", "ENVOYEE", "ENVOYEE", "PAYEE"]

    # 12. lecture du plan : facturé en entier, solde zéro, taxes par facture et écart d'arrondi dits
    lu = _utile(m5, "m5_lire_plan_facturation", {"devis_id": "D-1", "aujourd_hui": "2026-11-26"})
    assert lu["facture_avant_taxes"] == "10000.00" and lu["solde_a_facturer_avant_taxes"] == "0.00"
    assert [j["etat"] for j in lu["jalons"]] == ["PAYEE", "ENVOYEE", "ENVOYEE"]
    assert lu["taxes_des_jalons"] == lu["taxes_sur_le_total"] == "1497.50" and lu["a_declarer"] == []

    # 13. PDF de l'acompte approuvé : mêmes chiffres que la facture, scellé, rejouable, jamais envoyé
    pdf = _utile(
        m5,
        "m5_preparer_pdf_facture",
        {"facture_id": acompte, "langue": "fr", "destinataire": CLIENT, "horodatage": "2026-11-26T10:00:00-05:00"},
    )
    octets = (Path(stockage.dossier_opsys()) / pdf["fichier"]["chemin_relatif"]).read_bytes()
    assert hashlib.sha256(octets).hexdigest() == pdf["sha256"] and pdf["scelle"]["statut"] == "nouveau"
    pypdf = pytest.importorskip("pypdf")
    texte = " ".join(
        " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(octets)).pages).replace(" ", " ").split()
    )
    for attendu in (
        "Facture F-01000",
        "3 000,00 $",
        "150,00 $",
        "299,25 $",
        "3 449,25 $",
        "N° TPS 123456789 RT0001",
        "N° TVQ 1234567890 TQ0001",
        "Payable à la réception",
        "Jalon 1 de 3",
        "7 000,00 $",
    ):
        assert attendu in texte, attendu
    rejeu = _utile(
        m5,
        "m5_preparer_pdf_facture",
        {"facture_id": acompte, "langue": "fr", "destinataire": CLIENT, "horodatage": "2026-12-01T10:00:00-05:00"},
    )
    assert rejeu["scelle"]["statut"] == "deja" and rejeu["sha256"] == pdf["sha256"]

    # 14. rien d'irréversible ni de personnel : aucun mouvement d'argent, rien chez un autre département, rien de client
    assert [m for m in _registre(M5, "principal")] == []  # aucun encaissement écrit par la facturation
    assert monde.ecritures_hors_propriete() == []
    with stockage.transaction() as cnx:
        sortants = " ".join(str(ligne.charge) for ligne in cnx.execute(select(EVENEMENTS_SORTANTS)).all())
    for personnel in ("Cliente", "avenue Exemple", "Lévis", "123456789", "Entreprise Fictive"):
        assert personnel not in sortants, personnel


def test_un_plan_dont_la_somme_ne_tombe_pas_juste_est_refuse_et_rien_n_est_facture(monde, m5):
    _publier_devis(monde, "D-2", prix="1000.01")
    faux = [
        {
            "libelle": "Acompte",
            "declencheur": "acceptation",
            "montant_avant_taxes": "500.00",
            "delai_paiement_jours": 0,
        },
        {"libelle": "Solde", "declencheur": "fin_travaux", "montant_avant_taxes": "500.00"},
    ]
    refuse = _decider(
        monde,
        "m5_etablir_plan_facturation",
        {"devis_id": "D-2", "jalons": faux, "chantier_id": "CH-2", "horodatage": EMISSION_1},
    )
    verdict = refuse["reponse"]["resultat"]["verdict"]
    assert verdict["code"] == "REJ-PLAN-SOMME-INCORRECTE" and "écart -0.01 $" in verdict["detail"]
    assert _registre(M5, "plans_facturation") == [] and _registre(M5, "factures") == []
    # en pourcentages, la somme tombe toujours juste : le solde absorbe l'arrondi (1000.01 x 33,33 % = 333.33...)
    tiers = [
        {"libelle": "Acompte", "declencheur": "acceptation", "pourcentage": "33.33", "delai_paiement_jours": 0},
        {"libelle": "Mi-chantier", "declencheur": "chantier", "pourcentage": "33.33"},
        {"libelle": "Solde", "declencheur": "fin_travaux", "pourcentage": "33.34"},
    ]
    bon = _decider(
        monde,
        "m5_etablir_plan_facturation",
        {"devis_id": "D-2", "jalons": tiers, "chantier_id": "CH-2", "horodatage": EMISSION_1},
    )
    jalons = bon["reponse"]["resultat"]["resultat"]["jalons"]
    assert sum(D(j["montant_avant_taxes"]) for j in jalons) == D("1000.01")


def test_donnees_declarees_absentes_bloquent_lisiblement_chaque_etape(monde, m5, tmp_path, monkeypatch):
    # conditions de paiement, numérotation et profil d'entreprise : rien n'est déclaré
    monde.manifeste.write_text(
        yaml.safe_dump({"configuration": {"operations": CONFIG["operations"]}}), encoding="utf-8"
    )
    _publier_devis(monde)
    sans_delai = [{k: v for k, v in j.items() if k != "delai_paiement_jours"} for j in JALONS]
    refus = _decider(
        monde,
        "m5_etablir_plan_facturation",
        {"devis_id": "D-1", "jalons": sans_delai, "chantier_id": "CH-1", "horodatage": EMISSION_1},
    )
    verdict = refus["reponse"]["resultat"]["verdict"]
    assert verdict["code"] == "REJ-PLAN-DELAI-A-DECLARER" and "conditions_paiement.delai_jours" in verdict["detail"]
    # le délai se déclare sur chaque jalon : le plan est accepté, mais l'émission dit quoi déclarer
    avec_delai = [{**j, "delai_paiement_jours": 10} for j in JALONS]
    plan = _decider(
        monde,
        "m5_etablir_plan_facturation",
        {"devis_id": "D-1", "jalons": avec_delai, "chantier_id": "CH-1", "horodatage": EMISSION_1},
    )
    plan_id = plan["reponse"]["resultat"]["resultat"]["plan_id"]
    _utile(m5, "m5_creer_facture_jalon", {"devis_id": "D-1", "rang": 1, "horodatage": EMISSION_1})
    manques = _utile(m5, "m5_lire_plan_facturation", {"devis_id": "D-1"})["a_declarer"]
    assert {m["declaration"] for m in manques} == {
        "configuration.facturation.numerotation",
        "configuration.facturation.conditions_paiement",
        "configuration.facturation.entreprise",
    }
    emission = _decider(monde, "m5_envoyer_facture", {"facture_id": _facture_id(plan_id, 1), "horodatage": EMISSION_1})
    verdict = emission["reponse"]["resultat"]["verdict"]
    assert verdict["code"] == "REJ-NUMEROTATION-A-DECLARER" and "premier_numero" in verdict["detail"]
    assert _etat(_facture_id(plan_id, 1))["statut"] == "BROUILLON" and _registre(M5, "numerotation_factures") == []
    # numérotation déclarée, mais pas le profil d'entreprise : l'émission passe, le PDF dit quoi déclarer
    configuration = {
        "operations": CONFIG["operations"],
        "facturation": {"numerotation": CONFIG["facturation"]["numerotation"]},
    }
    monde.manifeste.write_text(yaml.safe_dump({"configuration": configuration}), encoding="utf-8")
    assert (
        _decider(monde, "m5_envoyer_facture", {"facture_id": _facture_id(plan_id, 1), "horodatage": EMISSION_1})[
            "statut"
        ]
        == "executee"
    )
    sans_profil = _outil(
        m5,
        "m5_preparer_pdf_facture",
        {"facture_id": _facture_id(plan_id, 1), "langue": "fr", "destinataire": CLIENT, "horodatage": EMISSION_1},
    )
    assert sans_profil["verdict"]["code"] == "REJ-PDF-ENTREPRISE-A-DECLARER"
    for champ in ("raison_sociale", "adresse", "numero_tps", "numero_tvq"):
        assert champ in sans_profil["verdict"]["detail"]
    assert _registre(M5, "documents_facturation") == []
