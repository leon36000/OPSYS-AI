"""C4 — le cycle de vie du PO sans double validation : l'envoi CONSTATÉ par M1 suffit à `sent_to_supplier` (aucun
second clic N4) ; un rapprochement M5 CONCORDANT PROPOSE `invoiced` à une personne ; `closed` et `disputed` restent des
outils N3 avec motif.

Ce fichier est le ROUGE-AVANT de C4 : avant ce chantier, un rapprochement M5 CONCORDANT ne produisait aucune attente
et `invoiced` ne se déduisait pas de M5 (geste de personne sans proposition).

Vrais outils, vraie base SQLite, vrai bus pour l'envoi constaté et le rapprochement reçu ; données fictives.
"""

from __future__ import annotations

import pytest
from m6_material_control import bons_commande, commande_courriel_outils
from m6_material_control import outils as outils_mod
from m6_material_control.outils import outils

from opsys import stockage
from opsys.outils import executer_atomique

FICTIF = True
HORO = "2026-11-03T10:00:00-05:00"
DEPT = "m06-material-control"
BROUILLON = "brouillon-c4-fictif"
EMPREINTE_COURRIEL = "b" * 64


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def m6(base_durable):
    return {o.nom: o for o in outils()}


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _po(po_id="PO-C4-1"):
    with stockage.transaction():
        return bons_commande.lire(stockage.maillons(DEPT, "bons_commande"), po_id)


def _registre():
    with stockage.transaction():
        return list(stockage.maillons(DEPT, "bons_commande"))


def _fournisseur(m6, identifiant="f-c4", nom="Fournisseur C4 (fictif)"):
    _ok(executer_atomique(m6["m6_enregistrer_fournisseur"], {
        "fournisseur_id": identifiant, "nom": nom, "horodatage": HORO,
        "courriel_commande": f"{identifiant}@exemple-fictif.test"}))


def _po_pret(m6, po_id="PO-C4-1", materiau="REV-C4-FICTIF", quantite=10.0, prix=5.0):
    """Un PO commandable, approuvé, dont le courriel est prêt (statut `email_ready`)."""
    _fournisseur(m6)
    _ok(executer_atomique(m6["m6_enregistrer_besoins_prevus"], {
        "chantier_id": f"CH-{po_id}", "devis_id": f"D-{po_id}",
        "lignes": [{"materiau_id": materiau, "quantite_estimee": quantite, "unite": "feuille"}]}))
    _ok(executer_atomique(m6["m6_enregistrer_prix"], {
        "materiau_id": materiau, "fournisseur_id": "f-c4", "prix_unitaire": prix, "devise": "CAD",
        "date_effet": "2026-10-01", "unite": "feuille"}))
    _ok(executer_atomique(m6["m6_creer_po_brouillon"], {
        "po_id": po_id, "devis_id": f"D-{po_id}", "fournisseur_id": "f-c4", "horodatage": HORO,
        "date_requise": "2026-11-10", "mode_livraison": "ramassage"}))
    _ok(executer_atomique(m6["m6_approuver_po"], {"po_id": po_id, "horodatage": HORO}))
    _ok(executer_atomique(m6["m6_generer_courriel_po"], {
        "po_id": po_id, "horodatage": HORO, "nom_entreprise": "Entreprise fictive"}))
    return materiau, quantite


def _constat(po_id="PO-C4-1", **plus):
    po = _po(po_id)
    charge = {"po_id": po_id, "brouillon_id": f"{BROUILLON}-{po_id}", "empreinte": EMPREINTE_COURRIEL,
              "envoye_le": HORO,
              "empreinte_courriel_po": po["courriel"]["empreinte"], "contenu_identique": True}
    charge.update(plus)
    return charge


def _recevoir_envoi(charge):
    with stockage.transaction():
        return commande_courriel_outils.recevoir_commande_envoyee(charge)


def _recevoir_full(m6, po_id="PO-C4-1", materiau="REV-C4-FICTIF", quantite=10.0):
    """Le PO est envoyé (constat M1), puis reçu en totalité : `received`."""
    _recevoir_envoi(_constat(po_id))
    bon = {"po_id": po_id, "chantier_id": f"CH-{po_id}",
           "lignes_demandees": [{"materiau_id": materiau, "quantite_demandee": quantite}],
           "horodatage": "2026-11-05T09:00:00-05:00"}
    reception = {"po_id": po_id, "chantier_id": f"CH-{po_id}",
                 "lignes_recues": [{"materiau_id": materiau, "quantite_recue": quantite}],
                 "horodatage": "2026-11-06T09:00:00-05:00"}
    _ok(executer_atomique(m6["m6_receptionner_commande"], {"bon_demande": bon, "reception_po": reception}))
    assert _po(po_id)["statut"] == "received"


def _rapprochement(verdict="CONCORDANT", po_id="PO-C4-1", facture="facture-c4-fictive", **plus):
    charge = {"facture_fournisseur_id": facture, "po_id": po_id, "verdict": verdict, "sens": None,
              "facture_avant_taxes": "50.00", "recu_avant_taxes": "50.00", "ecart_avant_taxes": "0.00",
              "reserves": [], "date_reference": "2026-11-06"}
    charge.update(plus)
    with stockage.transaction():
        return outils_mod._recevoir_rapprochement_po(charge)


def _attentes():
    with stockage.transaction():
        return list(outils_mod.attentes())


def _proposition(po_id="PO-C4-1"):
    return [a for a in _attentes() if a["type"] == "po_a_facturer" and a["id"] == po_id]


def _changer(m6, statut, motif="Décision de l'admin, fictive", po_id="PO-C4-1"):
    return executer_atomique(m6["m6_changer_statut_po"], {
        "po_id": po_id, "statut_cible": statut, "motif": motif, "horodatage": HORO})


# =========================================================================================================
# 1. Envoi constaté : déjà prouvé par C2, on refige ici le parcours C4 complet (aucun second clic N4)
# =========================================================================================================
def test_l_envoi_constate_par_m1_amene_le_po_a_envoye_sans_seconde_approbation(m6):
    _po_pret(m6)

    _recevoir_envoi(_constat())

    assert _po()["statut"] == "sent_to_supplier"
    assert not [a for a in _attentes() if a["type"] == "po_envoye_a_marquer"]


# =========================================================================================================
# 2. Rapprochement CONCORDANT : proposition `invoiced`, jamais une transition automatique
# =========================================================================================================
def test_un_rapprochement_concordant_propose_invoiced_sans_jamais_transitionner_seul(m6):
    _po_pret(m6)
    _recevoir_full(m6)

    _rapprochement("CONCORDANT")

    assert _po()["statut"] == "received", "M6 ne facture pas seul : le rapprochement ne fait que proposer"
    (proposition,) = _proposition()
    assert proposition["niveau"] == "N3"
    assert proposition["action_proposee"] == "m6_changer_statut_po (statut_cible=invoiced), avec un motif"
    assert "concordant" in proposition["resume"].lower() and "facture-c4-fictive" in proposition["resume"]
    assert "50.00" not in proposition["resume"], "aucun montant dans l'attente"


def test_l_admin_applique_invoiced_par_l_outil_n3_avec_motif_et_la_proposition_disparait(m6):
    _po_pret(m6)
    _recevoir_full(m6)
    _rapprochement("CONCORDANT")

    resultat = _ok(_changer(m6, "invoiced", "Facture M5 concordante, vérifiée"))

    assert resultat["po"]["statut"] == "invoiced"
    assert _proposition() == [], "facturé : il n'y a plus rien à proposer"


def test_un_rapprochement_concordant_pour_un_po_partiel_ne_propose_pas_invoiced(m6):
    _po_pret(m6)
    _recevoir_envoi(_constat())
    bon = {"po_id": "PO-C4-1", "chantier_id": "CH-PO-C4-1",
           "lignes_demandees": [{"materiau_id": "REV-C4-FICTIF", "quantite_demandee": 10.0}],
           "horodatage": "2026-11-05T09:00:00-05:00"}
    reception = {"po_id": "PO-C4-1", "chantier_id": "CH-PO-C4-1",
                 "lignes_recues": [{"materiau_id": "REV-C4-FICTIF", "quantite_recue": 4.0}],
                 "horodatage": "2026-11-06T09:00:00-05:00"}
    _ok(executer_atomique(m6["m6_receptionner_commande"], {"bon_demande": bon, "reception_po": reception}))
    assert _po()["statut"] == "partially_received"

    _rapprochement("CONCORDANT")

    assert _proposition() == []


@pytest.mark.parametrize("verdict", ["ECART", "INCOMPLET", "SANS_FACTURE"])
def test_un_rapprochement_non_concordant_ne_propose_jamais_invoiced(m6, verdict):
    _po_pret(m6)
    _recevoir_full(m6)

    _rapprochement(verdict, sens="FACTURE_SUPERIEURE_AU_RECU" if verdict == "ECART" else None,
                   ecart_avant_taxes="5.00" if verdict == "ECART" else "0.00")

    assert _po()["statut"] == "received" and _proposition() == []
    if verdict in ("ECART", "INCOMPLET"):
        assert [a for a in _attentes() if a["type"] == "rapprochement_po_a_voir"]


def test_rejouer_le_meme_rapprochement_ne_cree_pas_une_seconde_proposition(m6):
    _po_pret(m6)
    _recevoir_full(m6)
    _rapprochement("CONCORDANT")
    avant = list(_attentes())

    _rapprochement("CONCORDANT")

    assert _proposition() == [a for a in avant if a["type"] == "po_a_facturer"]
    assert len(_proposition()) == 1


def test_un_rapprochement_pour_un_po_inconnu_ne_propose_rien_et_n_ecrit_aucune_transition(m6):
    _rapprochement("CONCORDANT", po_id="PO-INCONNU", facture="facture-inconnue-fictive")

    assert _proposition("PO-INCONNU") == []


# =========================================================================================================
# 3. closed / disputed : outils N3 avec motif, transitions légales seulement
# =========================================================================================================
def test_closed_et_disputed_sont_des_gestes_n3_avec_motif(m6):
    _po_pret(m6, "PO-C4-1")
    _recevoir_full(m6)
    _rapprochement("CONCORDANT")
    _ok(_changer(m6, "invoiced", "Facture concordante"))

    ferme = _ok(_changer(m6, "closed", "Facture réglée, dossier clos"))

    assert ferme["po"]["statut"] == "closed"
    assert [t["motif_statut"] for t in _registre() if t.get("statut") == "closed"] == [
        "Facture réglée, dossier clos"]

    _po_pret(m6, "PO-C4-2")
    _recevoir_full(m6, "PO-C4-2")
    litige = _ok(_changer(m6, "disputed", "Prix du bon de livraison contesté", "PO-C4-2"))
    assert litige["po"]["statut"] == "disputed"


def test_un_motif_vide_est_refuse_et_ne_change_rien(m6):
    _po_pret(m6)
    _recevoir_full(m6)

    refus = _changer(m6, "invoiced", "   ")

    assert refus["resultat"]["accepte"] is False
    assert refus["resultat"]["verdict"]["code"] == "REJ-PO-MOTIF-VIDE"
    assert _po()["statut"] == "received"


def test_une_transition_illegale_est_refusee_nommee(m6):
    _po_pret(m6)  # email_ready

    refus = _changer(m6, "closed", "Tentative de fermer un PO jamais envoyé")

    assert refus["resultat"]["accepte"] is False
    assert refus["resultat"]["verdict"]["code"] == "REJ-PO-TRANSITION-ILLEGALE"
    assert _po()["statut"] == "email_ready"


def test_fermer_un_po_deja_ferme_est_refuse_sans_reecrire_le_registre(m6):
    _po_pret(m6)
    _recevoir_full(m6)
    _ok(_changer(m6, "disputed", "Litige ouvert"))
    _ok(_changer(m6, "closed", "Litige réglé"))
    avant = _registre()

    refus = _changer(m6, "closed", "Deuxième clôture")

    assert refus["resultat"]["accepte"] is False
    assert refus["resultat"]["verdict"]["code"] == "REJ-PO-TRANSITION-ILLEGALE"
    assert _registre() == avant
