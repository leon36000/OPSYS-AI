"""C2 — plus de DOUBLE approbation : quand M1 a constaté l'envoi du courriel d'un PO, M6 en prend acte.

Avant : l'envoi était approuvé une première fois par une personne au sas de M1 (N3, empreinte exacte), puis M6 exigeait
une seconde approbation (`m6_marquer_po_envoye`, N4) alors que `m1.commande_courriel_envoyee` constatait déjà l'envoi.

Maintenant : sur ce constat, et SEULEMENT si le courriel envoyé est celui du PO (même empreinte que `courriel.empreinte`
du PO, brouillon non modifié depuis sa préparation) et que le PO est encore `email_ready`, M6 passe le PO à
`sent_to_supplier` en rangeant le constat. Aucun chemin d'envoi n'est ouvert : l'envoi lui-même reste approuvé par une
personne au sas de M1 ; ceci ne fait que recopier un fait. Tout autre cas (empreinte différente, brouillon modifié,
                                                                           vieux
constat sans empreinte, PO pas au bon statut) laisse l'attente N4 « marquer le PO envoyé » à une personne.

Vrais outils, vraie base SQLite ; M1 est joué par la charge de son événement.
"""

from __future__ import annotations

import pytest
from m6_material_control import bons_commande, commande_courriel_outils
from m6_material_control import outils as outils_mod
from m6_material_control.outils import outils

from opsys import stockage
from opsys.outils import executer_atomique

FICTIF = True
HORO = "2026-11-02T10:00:00-05:00"
DEPT = "m06-material-control"
BROUILLON = "brouillon-fictif-1"
EMPREINTE_BROUILLON = "b" * 64


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


def _po_pret(m6, po_id="PO-ENVOI-1", jusqu_a="email_ready", materiau="REV-FICTIF"):
    """Un PO commandable amené au statut voulu, par les outils (l'approbation N3 est simulée par l'appel direct)."""
    _ok(executer_atomique(m6["m6_enregistrer_fournisseur"], {
        "fournisseur_id": "f-envoi", "nom": "Fournisseur fictif", "horodatage": HORO,
        "courriel_commande": "commandes@fournisseur.exemple-fictif.test"}))
    _ok(executer_atomique(m6["m6_enregistrer_besoins_prevus"], {
        "chantier_id": f"CH-{po_id}", "devis_id": f"D-{po_id}",
        "lignes": [{"materiau_id": materiau, "quantite_estimee": 10.0, "unite": "feuille"}]}))
    _ok(executer_atomique(m6["m6_enregistrer_prix"], {
        "materiau_id": materiau, "fournisseur_id": "f-envoi", "prix_unitaire": 5.0, "devise": "CAD",
        "date_effet": "2026-10-01", "unite": "feuille"}))
    _ok(executer_atomique(m6["m6_creer_po_brouillon"], {
        "po_id": po_id, "devis_id": f"D-{po_id}", "fournisseur_id": "f-envoi", "horodatage": HORO,
        "date_requise": "2026-11-10", "mode_livraison": "ramassage"}))
    if jusqu_a == "draft":
        return
    _ok(executer_atomique(m6["m6_approuver_po"], {"po_id": po_id, "horodatage": HORO}))
    if jusqu_a == "approved":
        return
    _ok(executer_atomique(m6["m6_generer_courriel_po"], {"po_id": po_id, "horodatage": HORO,
                                                         "nom_entreprise": "Atelier"}))


def _po(po_id="PO-ENVOI-1"):
    with stockage.transaction():
        return bons_commande.lire(stockage.maillons(DEPT, "bons_commande"), po_id)


def _constat(po_id="PO-ENVOI-1", **plus):
    charge = {"po_id": po_id, "brouillon_id": BROUILLON, "empreinte": EMPREINTE_BROUILLON, "envoye_le": HORO,
              "empreinte_courriel_po": _po(po_id)["courriel"]["empreinte"] if _po(po_id).get("courriel") else "c" * 64,
              "contenu_identique": True}
    charge.update(plus)
    return {k: v for k, v in charge.items() if v is not ...}


def _recevoir(charge):
    with stockage.transaction():
        return commande_courriel_outils.recevoir_commande_envoyee(charge)


def _attentes_envoi():
    with stockage.transaction():
        return [a for a in outils_mod.attentes() if a["type"] == "po_envoye_a_marquer"]


def test_l_envoi_constate_du_courriel_du_po_le_passe_a_envoye_sans_seconde_approbation(m6):
    _po_pret(m6)

    resultat = _recevoir(_constat())

    po = _po()
    assert po["statut"] == "sent_to_supplier" and resultat["po_marque_envoye"] is True
    constat = [m for m in _registre() if m.get("po_id") == "PO-ENVOI-1" and "envoi_constate" in m][0]["envoi_constate"]
    assert constat == {"source": "m1.commande_courriel_envoyee", "brouillon_id": BROUILLON,
                       "empreinte_courriel_po": po["courriel"]["empreinte"], "envoye_le": HORO}
    assert _attentes_envoi() == [], "plus d'attente N4 : il n'y a rien à marquer"


def _registre():
    with stockage.transaction():
        return list(stockage.maillons(DEPT, "bons_commande"))


def test_rejouer_le_constat_ne_change_rien_et_ne_transitionne_pas_deux_fois(m6):
    _po_pret(m6)
    _recevoir(_constat())
    avant = _registre()

    deuxieme = _recevoir(_constat())

    assert deuxieme == {"deja_constate": True}
    assert _registre() == avant


@pytest.mark.parametrize("plus", [
    {"empreinte_courriel_po": "d" * 64},          # un autre courriel que celui du PO
    {"contenu_identique": False},                  # brouillon modifié dans le sas : ce n'est plus le courriel du PO
    {"empreinte_courriel_po": ...},                # vieux constat de M1, sans empreinte du courriel du PO
    {"contenu_identique": ...},
])
def test_un_constat_qui_n_est_pas_celui_du_po_laisse_l_attente_n4_a_une_personne(m6, plus):
    _po_pret(m6)

    resultat = _recevoir(_constat(**plus))

    assert _po()["statut"] == "email_ready" and resultat["po_marque_envoye"] is False
    (attente,) = _attentes_envoi()
    assert attente["niveau"] == "N4" and attente["id"] == "PO-ENVOI-1"


@pytest.mark.parametrize("jusqu_a", ["draft", "approved"])
def test_un_constat_pour_un_po_qui_n_est_pas_email_ready_ne_le_change_pas(m6, jusqu_a):
    _po_pret(m6, jusqu_a=jusqu_a)

    resultat = _recevoir(_constat(empreinte_courriel_po="c" * 64))

    assert _po()["statut"] == jusqu_a and resultat["po_marque_envoye"] is False


def test_un_po_annule_n_est_pas_ressuscite_par_un_constat(m6):
    _po_pret(m6)
    _ok(executer_atomique(m6["m6_annuler_po"], {"po_id": "PO-ENVOI-1", "motif": "annulé par l'admin",
                                                "horodatage": HORO}))
    empreinte = _po()["courriel"]["empreinte"]

    _recevoir(_constat(empreinte_courriel_po=empreinte))

    assert _po()["statut"] == "cancelled"


def test_le_constat_d_un_po_ne_marque_jamais_un_autre_po(m6):
    _po_pret(m6, "PO-ENVOI-1")
    _po_pret(m6, "PO-ENVOI-2")
    empreinte_un = _po("PO-ENVOI-1")["courriel"]["empreinte"]

    _recevoir(_constat("PO-ENVOI-2", empreinte_courriel_po=empreinte_un))  # l'empreinte du PO-1 sur le PO-2

    assert _po("PO-ENVOI-2")["statut"] == "email_ready" and _po("PO-ENVOI-1")["statut"] == "email_ready"


def test_un_po_inconnu_est_constate_sans_erreur_et_sans_effet(m6):
    resultat = _recevoir({"po_id": "PO-INCONNU", "brouillon_id": BROUILLON, "empreinte": EMPREINTE_BROUILLON,
                          "envoye_le": HORO, "empreinte_courriel_po": "c" * 64, "contenu_identique": True})

    assert resultat["po_trouve"] is False and resultat["po_marque_envoye"] is False


def test_apres_la_prise_d_acte_marquer_envoye_a_la_main_est_une_transition_illegale(m6):
    _po_pret(m6)
    _recevoir(_constat())

    refus = executer_atomique(m6["m6_marquer_po_envoye"], {"po_id": "PO-ENVOI-1", "horodatage": HORO})

    assert refus["resultat"]["accepte"] is False
    assert refus["resultat"]["verdict"]["code"] == "REJ-PO-TRANSITION-ILLEGALE"


def test_marquer_a_la_main_reste_possible_pour_un_envoi_hors_m1(m6):
    """Téléphone, portail du fournisseur : aucun constat de M1, la décision N4 d'une personne reste le seul chemin."""
    _po_pret(m6)

    po = _ok(executer_atomique(m6["m6_marquer_po_envoye"], {"po_id": "PO-ENVOI-1", "horodatage": HORO}))["po"]

    assert po["statut"] == "sent_to_supplier" and "envoi_constate" not in {k for m in _registre() for k in m}
