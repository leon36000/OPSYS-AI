"""M5 branché sur les approbations du socle (PLAN T1.3-c, points 1/2/3/6).

`m5_envoyer_facture` (N4) et `m5_enregistrer_paiement_facture` (N5) ne s'exécutent JAMAIS par un
appel direct de l'agent : `opsys.capacites.Capacites._distribuer` intercepte l'appel et crée une
demande `en_attente_approbation` ; seule `opsys.approbations.decider`, appelée par une personne
dont un rôle figure dans `department.yaml/approbations` pour le niveau N de la demande, exécute
réellement la transition (BROUILLON -> ENVOYEE, ENVOYEE -> PAYEE). Utilise le VRAI socle
(`opsys.capacites`, `opsys.approbations`, `opsys.identite`) sur le VRAI manifeste de M5, sur une
base SQLite temporaire migrée — même patron que `tests/test_approbations_identite.py` (socle) et
`departments/m05-financecore/tests/test_evenements_m5.py` (base durable de département).

Identifiants et montants fictifs (DEFINITION-PRODUIT §1).
"""

from __future__ import annotations

from pathlib import Path

import m5_financecore.outils as m5_outils  # noqa: E402
import pytest
from m5_financecore import facturation  # noqa: E402

from opsys import approbations as opsys_approbations  # noqa: E402
from opsys import identite, stockage  # noqa: E402
from opsys.capacites import Capacites, outils_executables  # noqa: E402
from opsys.departements import lire_manifeste  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402

_RACINE_M5 = Path(__file__).resolve().parents[1]
HORODATAGE = "2026-08-03T12:00:00+00:00"

_LIGNES_FACTURE = [
    {
        "description": "Gouttières 5po aluminium", "quantite": "40", "unite": "pi",
        "prix_unitaire": "8.50", "reference_ligne_devis": "L1",
    },
    {
        "description": "Main d'oeuvre installation", "quantite": "1", "unite": "forfait",
        "prix_unitaire": "260.00", "reference_ligne_devis": "L2",
    },
]
MONTANT_DU = "689.85"  # 600.00 avant taxes -> TPS 30.00 + TVQ 59.85 (mêmes chiffres que test_facturation.py)

ATTESTATION_VALIDE = {
    "nom": "Alex Comptable (fictif)", "profession": "CPA", "reference_document": "DEPOT-BANCAIRE-4521-fictif",
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-approbations-socle.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    yield url
    stockage.liberer()


@pytest.fixture
def dep(base_durable):
    return lire_manifeste(_RACINE_M5)


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe1", "Un Employé (fictif)", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur1", "Un Vendeur (fictif)", "mot-de-passe-vendeur-1234", ["seller"])
        identite.creer_personne(cnx, "financeuse", "Une Comptable (fictif)", "mot-de-passe-finance-1234",
                                ["finance"])
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner"])
    return {"employe": "employe1", "vendeur": "vendeur1", "finance": "financeuse", "nathan": "nathan"}


def _creer_facture_brouillon(facture_id="FACT-SOCLE", devis_id="DEVIS-SOCLE"):
    """Setup hors périmètre du test (créer une facture BROUILLON n'est pas le sujet ici) : appel
    direct de l'outil, sans passer par l'approbation — même esprit que
    `tests/test_cascade_travaux_termines.py` pour ses étapes non testées par un scénario donné."""
    outil = next(o for o in m5_outils.outils() if o.nom == "m5_creer_facture_brouillon")
    reponse = executer_atomique(outil, {
        "facture_id": facture_id, "chantier_id": "CHANTIER-SOCLE-fictif", "devis_id": devis_id,
        "client_id": "CLIENT-SOCLE-fictif", "lignes": _LIGNES_FACTURE, "horodatage": HORODATAGE,
    })
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse
    return facture_id


def _envoyer_facture_directement(facture_id):
    """Setup hors périmètre du test (l'envoi n'est pas le sujet pour un test de PAIEMENT)."""
    outil = next(o for o in m5_outils.outils() if o.nom == "m5_envoyer_facture")
    reponse = executer_atomique(outil, {"facture_id": facture_id, "horodatage": HORODATAGE})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _statut_facture(facture_id):
    with stockage.transaction():
        return facturation._etat_facture(m5_outils._registre_factures(None), facture_id)["statut"]


def _demandes_en_attente(outil_nom):
    with stockage.transaction() as cnx:
        return [d for d in opsys_approbations.lister(cnx, "en_attente") if d["outil"] == outil_nom]


# -- m5_envoyer_facture (N4) : jamais exécuté hors d'une décision signée ------------------------


def test_appel_direct_de_l_agent_ne_s_execute_jamais_cree_une_demande(dep, personnes):
    """Point 1 du mandat : la transition BROUILLON -> ENVOYEE ne dépend plus de la forme d'un
    maillon F4 — elle dépend de la SEULE interception du socle (mode `ombre`, seuil N3 <= N4)."""
    facture_id = _creer_facture_brouillon()
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)

    reponse = capacites.appeler("m5_envoyer_facture", {"facture_id": facture_id, "horodatage": HORODATAGE})

    assert reponse["ok"] is True
    assert reponse["statut"] == "en_attente_approbation"
    assert "demande_id" in reponse
    assert _statut_facture(facture_id) == "BROUILLON", "rien n'a exécuté la transition"
    [demande] = _demandes_en_attente("m5_envoyer_facture")
    assert demande["niveau"] == "N4"
    assert demande["departement"] == "m05-financecore"


def test_employe_ne_peut_pas_decider_l_envoi(dep, personnes):
    facture_id = _creer_facture_brouillon()
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    ident = capacites.appeler(
        "m5_envoyer_facture", {"facture_id": facture_id, "horodatage": HORODATAGE}
    )["demande_id"]
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)

    with stockage.transaction() as cnx, pytest.raises(ValueError, match="aucun rôle autorisé"):
        opsys_approbations.decider(cnx, ident, True, personnes["employe"], outils_dispo, {"m05-financecore": dep})

    assert _statut_facture(facture_id) == "BROUILLON"
    assert len(_demandes_en_attente("m5_envoyer_facture")) == 1


def test_vendeur_ne_peut_pas_decider_l_envoi(dep, personnes):
    """SOUL.md/mandat : un employé OU un vendeur ne peut ni envoyer ni enregistrer un paiement."""
    facture_id = _creer_facture_brouillon()
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    ident = capacites.appeler(
        "m5_envoyer_facture", {"facture_id": facture_id, "horodatage": HORODATAGE}
    )["demande_id"]
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)

    with stockage.transaction() as cnx, pytest.raises(ValueError, match="aucun rôle autorisé"):
        opsys_approbations.decider(cnx, ident, True, personnes["vendeur"], outils_dispo, {"m05-financecore": dep})

    assert _statut_facture(facture_id) == "BROUILLON"


@pytest.mark.parametrize("role_cle", ["finance", "nathan"])
def test_finance_ou_nathan_owner_decident_l_envoi_facture_transitionne(dep, personnes, role_cle):
    """`department.yaml/approbations.n4` : finance ET nathan_owner sont tous deux autorisés."""
    facture_id = _creer_facture_brouillon(facture_id=f"FACT-ENVOI-{role_cle}", devis_id=f"DEVIS-ENVOI-{role_cle}")
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    ident = capacites.appeler(
        "m5_envoyer_facture", {"facture_id": facture_id, "horodatage": HORODATAGE}
    )["demande_id"]
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)

    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, ident, True, personnes[role_cle], outils_dispo, {"m05-financecore": dep}
        )

    assert decision["statut"] == "executee"
    assert decision["reponse"]["resultat"]["accepte"] is True
    assert _statut_facture(facture_id) == "ENVOYEE"


# -- m5_enregistrer_paiement_facture (N5) : nathan_owner ET attestation, montant comparé --------


def test_appel_direct_de_l_agent_pour_le_paiement_cree_une_demande_n5(dep, personnes):
    facture_id = _creer_facture_brouillon(facture_id="FACT-N5-DEMANDE", devis_id="DEVIS-N5-DEMANDE")
    _envoyer_facture_directement(facture_id)
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)

    reponse = capacites.appeler("m5_enregistrer_paiement_facture", {
        "facture_id": facture_id, "montant_paye": MONTANT_DU, "approbateur": "Nathan (fictif)",
        "horodatage": HORODATAGE,
    })

    assert reponse["statut"] == "en_attente_approbation"
    [demande] = _demandes_en_attente("m5_enregistrer_paiement_facture")
    assert demande["niveau"] == "N5"
    assert _statut_facture(facture_id) == "ENVOYEE"


@pytest.mark.parametrize("role_cle", ["employe", "vendeur", "finance"])
def test_seul_nathan_owner_peut_decider_le_paiement_meme_finance_ne_peut_pas(dep, personnes, role_cle):
    """N5 est une frontière FIXE de l'ADR (§5) : `department.yaml` ne peut jamais l'élargir, même
    à `finance` — seul `nathan_owner` décide (en plus de l'attestation)."""
    facture_id = _creer_facture_brouillon(facture_id=f"FACT-N5-{role_cle}", devis_id=f"DEVIS-N5-{role_cle}")
    _envoyer_facture_directement(facture_id)
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    ident = capacites.appeler("m5_enregistrer_paiement_facture", {
        "facture_id": facture_id, "montant_paye": MONTANT_DU, "approbateur": "Nathan (fictif)",
        "horodatage": HORODATAGE,
    })["demande_id"]
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)

    with stockage.transaction() as cnx, pytest.raises(ValueError, match="aucun rôle autorisé"):
        opsys_approbations.decider(
            cnx, ident, True, personnes[role_cle], outils_dispo, {"m05-financecore": dep},
            attestation=ATTESTATION_VALIDE,
        )

    assert _statut_facture(facture_id) == "ENVOYEE"


def test_paiement_n5_sans_attestation_refuse_rien_execute(dep, personnes):
    facture_id = _creer_facture_brouillon(facture_id="FACT-N5-SANS-ATT", devis_id="DEVIS-N5-SANS-ATT")
    _envoyer_facture_directement(facture_id)
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    ident = capacites.appeler("m5_enregistrer_paiement_facture", {
        "facture_id": facture_id, "montant_paye": MONTANT_DU, "approbateur": "Nathan (fictif)",
        "horodatage": HORODATAGE,
    })["demande_id"]
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)

    with stockage.transaction() as cnx, pytest.raises(ValueError, match="attestation du professionnel requise"):
        opsys_approbations.decider(cnx, ident, True, personnes["nathan"], outils_dispo, {"m05-financecore": dep})

    assert _statut_facture(facture_id) == "ENVOYEE"
    assert len(_demandes_en_attente("m5_enregistrer_paiement_facture")) == 1


def test_paiement_n5_avec_attestation_montant_exact_marque_payee(dep, personnes):
    facture_id = _creer_facture_brouillon(facture_id="FACT-N5-OK", devis_id="DEVIS-N5-OK")
    _envoyer_facture_directement(facture_id)
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    ident = capacites.appeler("m5_enregistrer_paiement_facture", {
        "facture_id": facture_id, "montant_paye": MONTANT_DU, "approbateur": "Nathan (fictif)",
        "horodatage": HORODATAGE,
    })["demande_id"]
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)

    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, ident, True, personnes["nathan"], outils_dispo, {"m05-financecore": dep},
            attestation=ATTESTATION_VALIDE,
        )

    assert decision["statut"] == "executee"
    assert decision["reponse"]["resultat"]["accepte"] is True
    assert _statut_facture(facture_id) == "PAYEE"
    with stockage.transaction() as cnx:
        executees = opsys_approbations.lister(cnx, "executee")
        [traitee] = [d for d in executees if d["outil"] == "m5_enregistrer_paiement_facture"]
    assert traitee["attestation"] == ATTESTATION_VALIDE
    assert (traitee["decide_par"], traitee["decide_role"]) == ("nathan", "nathan_owner")


def test_paiement_n5_montant_qui_ne_concorde_pas_rend_un_verdict_nomme_jamais_paye(dep, personnes):
    """Point 2 du mandat : paiement partiel ou écart -> verdict nommé, JAMAIS une valeur inventée.
    La commande approuvée est en échec métier, avec réponse d'outil valide refusant le paiement.
    Aucun maillon financier n'est ajouté et la facture reste ENVOYEE."""
    facture_id = _creer_facture_brouillon(facture_id="FACT-N5-PARTIEL", devis_id="DEVIS-N5-PARTIEL")
    _envoyer_facture_directement(facture_id)
    factures_avant = m5_outils._registre_factures(None).lire()
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    ident = capacites.appeler("m5_enregistrer_paiement_facture", {
        "facture_id": facture_id, "montant_paye": "500.00", "approbateur": "Nathan (fictif)",
        "horodatage": HORODATAGE,
    })["demande_id"]
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)

    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, ident, True, personnes["nathan"], outils_dispo, {"m05-financecore": dep},
            attestation=ATTESTATION_VALIDE,
        )

    assert decision["statut"] == "echec"
    assert decision["reponse"]["ok"] is True
    assert decision["reponse"]["resultat"]["accepte"] is False
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-FACTURE-PAIEMENT-PARTIEL"
    assert _statut_facture(facture_id) == "ENVOYEE", "jamais marquée PAYEE sur un paiement partiel"
    assert m5_outils._registre_factures(None).lire() == factures_avant, "aucun paiement n'ajoute de maillon facture"


def test_refus_d_une_demande_d_envoi_ne_transitionne_rien(dep, personnes):
    facture_id = _creer_facture_brouillon(facture_id="FACT-REFUS", devis_id="DEVIS-REFUS")
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    ident = capacites.appeler(
        "m5_envoyer_facture", {"facture_id": facture_id, "horodatage": HORODATAGE}
    )["demande_id"]
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)

    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, ident, False, personnes["finance"], outils_dispo, {"m05-financecore": dep}, "prix à réviser"
        )

    assert decision == {"id": ident, "statut": "refusee"}
    assert _statut_facture(facture_id) == "BROUILLON"
