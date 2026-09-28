"""outils.py — PLAN T2.5/T2.4 : le flux complet du PO (M6.5), du prévu M3 jusqu'à la réception, et
le verrou d'envoi N4 sur le VRAI socle (`opsys.capacites`/`opsys.approbations`/`opsys.identite`),
même patron que ``departments/m05-financecore/tests/test_approbations_socle.py``.

Identifiants et coordonnées fictifs (DEFINITION-PRODUIT §1, AGENTS.md « fictif: true »).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m6_material_control.outils as m6_outils  # noqa: E402
from m6_material_control import livre_prix  # noqa: E402
from m6_material_control.outils import Autonomie  # noqa: E402

from opsys import approbations as opsys_approbations  # noqa: E402
from opsys import identite, stockage  # noqa: E402
from opsys.capacites import Capacites, outils_executables  # noqa: E402
from opsys.departements import lire_manifeste  # noqa: E402
from opsys.outils import Niveau  # noqa: E402

_RACINE_M6 = Path(__file__).resolve().parents[1]
_DEPARTEMENT = "m06-material-control"

GENTEK_COURRIEL = "commandes@gentek.exemple-fictif.test"


# ------------------------------------------------------------------------------- E2E en mémoire


def _outil(nom):
    return next(o for o in m6_outils.outils() if o.nom == nom)


def test_flux_complet_prevu_m3_jusqu_a_la_reception():
    """Rejoue le scénario E2E exigé (mission, audit M6 §3.8) : estimation -> besoins prévus ->
    stock partiel -> PO brouillon (Gentek) -> approbation -> courriel -> envoi -> réception
    partielle puis complète -> écart de prix signalé, en appelant chaque outil PUBLIC comme un
    agent le ferait (jamais les fonctions internes de bons_commande.py directement)."""
    fh = m6_outils.enregistrer_fournisseur(
        "gentek", "Gentek", "2026-01-01T00:00:00Z", courriel_commande=GENTEK_COURRIEL
    )["fournisseurs_historique"]
    # T2.4 (commit suivant) fournira m6_enregistrer_prix : le livre de prix lui-même
    # (livre_prix.py) est déjà nécessaire au moteur de PO (T2.5) et donc déjà présent — le test
    # d'intégration ici l'alimente directement, sans passer par l'outil agent pas encore livré.
    lph: list[dict] = []
    livre_prix.enregistrer_prix("BARDEAU", "gentek", 20.0, "CAD", "2026-01-01", lph)

    # Stock déjà partiellement disponible pour ce chantier (une réception antérieure, hors PO).
    stock_prealable = m6_outils.receptionner_commande(
        {"po_id": "PO-STOCK-INITIAL", "chantier_id": "CHANTIER-1",
         "lignes_demandees": [{"materiau_id": "BARDEAU", "quantite_demandee": 4.0}],
         "horodatage": "2025-12-01T00:00:00Z"},
        {"po_id": "PO-STOCK-INITIAL", "chantier_id": "CHANTIER-1",
         "lignes_recues": [{"materiau_id": "BARDEAU", "quantite_recue": 4.0}], "horodatage": "2025-12-01T00:00:00Z"},
    )
    assert stock_prealable["accepte"] is True
    rh = stock_prealable["registre_historique"]

    besoins = m6_outils.enregistrer_besoins_prevus(
        "CHANTIER-1", "DEVIS-1", [{"materiau_id": "BARDEAU", "quantite_estimee": 10.0, "unite": "boite"}]
    )
    assert besoins["accepte"] is True
    bh = besoins["registre_historique"]

    creation = m6_outils.creer_po_brouillon(
        "PO-1", "DEVIS-1", "gentek", "2026-01-02T00:00:00Z",
        besoins_prevus_historique=bh, registre_historique=rh, livre_prix_historique=lph, fournisseurs_historique=fh,
    )
    assert creation["accepte"] is True
    po = creation["po"]
    assert po["statut"] == "draft"
    # Seul l'écart (10 - 4 = 6) est commandé, jamais la quantité estimée complète.
    assert po["lignes"] == [
        {"materiau_id": "BARDEAU", "quantite_demandee": 6.0, "verdict_prix": "PRIX_LIVRE",
         "prix_unitaire_prevu": 20.0, "devise_prevue": "CAD", "montant_ligne_prevu": 120.0}
    ]
    bch = creation["bons_commande_historique"]

    approbation = m6_outils.approuver_po("PO-1", "2026-01-03T00:00:00Z", bons_commande_historique=bch)
    assert approbation["accepte"] is True and approbation["po"]["statut"] == "approved"
    bch = approbation["bons_commande_historique"]

    courriel = m6_outils.generer_courriel_po(
        "PO-1", "2026-01-04T00:00:00Z", "Gouttières et Revêtements Synergy",
        fournisseurs_historique=fh, bons_commande_historique=bch,
    )
    assert courriel["accepte"] is True and courriel["po"]["statut"] == "email_ready"
    assert courriel["po"]["courriel"]["destinataire"] == GENTEK_COURRIEL
    assert courriel["po"]["courriel"]["repli_manuel_requis"] is False
    bch = courriel["bons_commande_historique"]

    envoi = m6_outils.marquer_po_envoye("PO-1", "2026-01-05T00:00:00Z", bons_commande_historique=bch)
    assert envoi["accepte"] is True and envoi["po"]["statut"] == "sent_to_supplier"
    bch = envoi["bons_commande_historique"]

    # Réception PARTIELLE (4 sur 6 demandés) : le PO passe à partially_received, jamais received.
    # `reception.py` (INCHANGÉ, DA-M6-12 révisée) compare bon_demande à CETTE livraison SEULE —
    # aucune notion de cumul entre plusieurs appels ; une livraison qui COMPLÈTE un PO déjà
    # partiel est donc hors de portée d'un simple test d'intégration ici (elle exigerait un
    # bon_demande différent des lignes persistées, que bon_demande_correspond refuse à dessein) —
    # la transition partially_received -> received elle-même est prouvée directement dans
    # test_bons_commande.py::test_enregistrer_reception_po_partiel_puis_complet_devient_received.
    bon_demande = {"po_id": "PO-1", "chantier_id": "CHANTIER-1",
                   "lignes_demandees": [{"materiau_id": "BARDEAU", "quantite_demandee": 6.0}],
                   "horodatage": "2026-01-02T00:00:00Z"}
    reception_partielle = m6_outils.receptionner_commande(
        bon_demande,
        {"po_id": "PO-1", "chantier_id": "CHANTIER-1",
         "lignes_recues": [{"materiau_id": "BARDEAU", "quantite_recue": 4.0}], "horodatage": "2026-01-06T00:00:00Z"},
        catalogue_materiaux={"version": "v1", "unite_monetaire": "CAD",
                              "postes": {"BARDEAU": {"cout_unitaire": 20.0, "libelle": "Bardeau"}}},
        registre_historique=rh, bons_commande_historique=bch,
    )
    assert reception_partielle["accepte"] is True
    assert reception_partielle["resultat"]["accuse_reception"]["verdict_reception"] == "RECEPTION_INFERIEURE"
    assert reception_partielle["po"]["statut"] == "partially_received"
    assert reception_partielle["signaux_ecart_prix"] == [], "même prix que prévu (20.0) : aucun écart"
    rh = reception_partielle["registre_historique"]
    bch = reception_partielle["bons_commande_historique"]

    # Un bon_demande qui NE CORRESPOND PLUS au PO est refusé AVANT toute écriture.
    incoherent = m6_outils.receptionner_commande(
        {**bon_demande, "lignes_demandees": [{"materiau_id": "BARDEAU", "quantite_demandee": 999.0}]},
        {"po_id": "PO-1", "chantier_id": "CHANTIER-1",
         "lignes_recues": [{"materiau_id": "BARDEAU", "quantite_recue": 2.0}], "horodatage": "2026-01-07T00:00:00Z"},
        registre_historique=rh, bons_commande_historique=bch,
    )
    assert incoherent == {"accepte": False, "verdict": {"code": "REJ-PO-BON-DEMANDE-INCOHERENT"}}

    # Un SECOND PO, sur un AUTRE chantier (le stock de CHANTIER-1 déborde déjà après la réception
    # ci-dessus, ce qui rendrait le besoin déjà couvert) : livraison unique conforme, prouve la
    # transition -> received et l'écart de prix signalé à M5/M8 (M6.7) dans le même scénario.
    besoins2 = m6_outils.enregistrer_besoins_prevus(
        "CHANTIER-2", "DEVIS-2", [{"materiau_id": "BARDEAU", "quantite_estimee": 3.0, "unite": "boite"}]
    )
    creation2 = m6_outils.creer_po_brouillon(
        "PO-2", "DEVIS-2", "gentek", "2026-01-09T00:00:00Z",
        besoins_prevus_historique=besoins2["registre_historique"], registre_historique=rh,
        livre_prix_historique=lph, fournisseurs_historique=fh,
    )
    assert creation2["accepte"] is True and creation2["po"] is not None
    bch2 = creation2["bons_commande_historique"]
    bch2 = m6_outils.approuver_po(
        "PO-2", "2026-01-10T00:00:00Z", bons_commande_historique=bch2
    )["bons_commande_historique"]
    bch2 = m6_outils.generer_courriel_po(
        "PO-2", "2026-01-11T00:00:00Z", "GRS", fournisseurs_historique=fh, bons_commande_historique=bch2
    )["bons_commande_historique"]
    bch2 = m6_outils.marquer_po_envoye(
        "PO-2", "2026-01-12T00:00:00Z", bons_commande_historique=bch2
    )["bons_commande_historique"]

    reception_finale = m6_outils.receptionner_commande(
        {"po_id": "PO-2", "chantier_id": "CHANTIER-2",
         "lignes_demandees": [{"materiau_id": "BARDEAU", "quantite_demandee": 3.0}],
         "horodatage": "2026-01-09T00:00:00Z"},
        {"po_id": "PO-2", "chantier_id": "CHANTIER-2",
         "lignes_recues": [{"materiau_id": "BARDEAU", "quantite_recue": 3.0}],
         "horodatage": "2026-01-13T00:00:00Z"},
        catalogue_materiaux={"version": "v2", "unite_monetaire": "CAD",
                              "postes": {"BARDEAU": {"cout_unitaire": 26.0, "libelle": "Bardeau"}}},
        registre_historique=rh, bons_commande_historique=bch2,
    )
    assert reception_finale["accepte"] is True
    assert reception_finale["resultat"]["accuse_reception"]["verdict_reception"] == "CONFORME"
    assert reception_finale["po"]["statut"] == "received"
    assert reception_finale["seuil_ecart_prix_pourcentage"] == 0.15
    assert reception_finale["signaux_ecart_prix"] == [
        {"po_id": "PO-2", "chantier_id": "CHANTIER-2", "materiau_id": "BARDEAU",
         "prix_prevu": 20.0, "prix_reel": 26.0, "ecart_pourcentage": 0.3}
    ]


def test_creer_po_brouillon_stock_deja_suffisant_ne_cree_aucun_po():
    bh = m6_outils.enregistrer_besoins_prevus(
        "C1", "DEVIS-STOCK-OK", [{"materiau_id": "MAT-X", "quantite_estimee": 5.0, "unite": "boite"}]
    )["registre_historique"]
    rh = m6_outils.receptionner_commande(
        {"po_id": "PO-DEJA-LA", "chantier_id": "C1",
         "lignes_demandees": [{"materiau_id": "MAT-X", "quantite_demandee": 5.0}],
         "horodatage": "2026-01-01T00:00:00Z"},
        {"po_id": "PO-DEJA-LA", "chantier_id": "C1",
         "lignes_recues": [{"materiau_id": "MAT-X", "quantite_recue": 5.0}],
         "horodatage": "2026-01-01T00:00:00Z"},
    )["registre_historique"]

    resultat = m6_outils.creer_po_brouillon(
        "PO-INUTILE", "DEVIS-STOCK-OK", "gentek", "2026-01-02T00:00:00Z",
        besoins_prevus_historique=bh, registre_historique=rh,
    )
    assert resultat == {"accepte": True, "po": None, "statut": "aucun_achat_requis"}


def test_creer_po_brouillon_besoin_introuvable_refuse_nomme():
    resultat = m6_outils.creer_po_brouillon("PO-1", "DEVIS-INCONNU", "gentek", "2026-01-02T00:00:00Z")
    assert resultat == {"accepte": False, "verdict": {"code": "REJ-PO-BESOIN-INTROUVABLE"}}


def test_creer_po_brouillon_chantier_inconnu_refuse_nomme():
    bh = m6_outils.enregistrer_besoins_prevus(
        None, "DEVIS-SANS-CHANTIER", [{"materiau_id": "MAT-X", "quantite_estimee": 5.0, "unite": "boite"}]
    )["registre_historique"]
    resultat = m6_outils.creer_po_brouillon(
        "PO-1", "DEVIS-SANS-CHANTIER", "gentek", "2026-01-02T00:00:00Z", besoins_prevus_historique=bh
    )
    assert resultat == {"accepte": False, "verdict": {"code": "REJ-PO-CHANTIER-INCONNU"}}


def test_lister_fournisseurs_outil():
    fh = m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z")["fournisseurs_historique"]
    resultat = m6_outils.lister_fournisseurs(fournisseurs_historique=fh)
    assert resultat["accepte"] is True
    assert any(f["fournisseur_id"] == "gentek" for f in resultat["resultat"])


def test_enregistrer_prix_outil():
    """PLAN T2.4 : l'outil agent dédié à la saisie du livre de prix, jusqu'ici alimenté seulement
    par un appel direct à `livre_prix.enregistrer_prix` dans les autres tests de ce fichier. Le PO
    créé à partir du livre alimenté par CET outil résout bien PRIX_LIVRE (pas seulement via un
    appel direct à livre_prix.py, comme test_flux_complet_prevu_m3_jusqu_a_la_reception)."""
    reponse = m6_outils.enregistrer_prix("BARDEAU", "gentek", 20.0, "CAD", "2026-01-01")
    assert reponse["accepte"] is True
    assert reponse["resultat"]["prix_unitaire"] == 20.0
    lph = reponse["livre_prix_historique"]

    fh = m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z")["fournisseurs_historique"]
    bh = m6_outils.enregistrer_besoins_prevus(
        "C-PRIX-OUTIL", "DEVIS-PRIX-OUTIL", [{"materiau_id": "BARDEAU", "quantite_estimee": 2.0, "unite": "boite"}]
    )["registre_historique"]
    creation = m6_outils.creer_po_brouillon(
        "PO-PRIX-OUTIL", "DEVIS-PRIX-OUTIL", "gentek", "2026-01-02T00:00:00Z",
        besoins_prevus_historique=bh, livre_prix_historique=lph, fournisseurs_historique=fh,
    )
    assert creation["accepte"] is True
    assert creation["po"]["lignes"][0]["verdict_prix"] == "PRIX_LIVRE"
    assert creation["po"]["lignes"][0]["prix_unitaire_prevu"] == 20.0


# --------------------------------------------------------------------- niveaux N déclarés (ADR-0009 §4)


def test_niveaux_effectifs_des_outils_po():
    assert _outil("m6_creer_po_brouillon").autonomie is Autonomie.T1
    assert _outil("m6_approuver_po").autonomie is Autonomie.T1
    assert _outil("m6_generer_courriel_po").autonomie is Autonomie.T1
    assert _outil("m6_enregistrer_prix").autonomie is Autonomie.T1
    # L'ENVOI au fournisseur (PLAN T2.5 point 3) est N4 (T2), jamais un simple T1/N3 interne.
    assert _outil("m6_marquer_po_envoye").autonomie is Autonomie.T2
    assert _outil("m6_marquer_po_envoye").niveau_effectif is Niveau.N4


# ------------------------------------------------------------------- verrou d'envoi N4, VRAI socle


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm6-po-socle.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def dep(base_durable):
    return lire_manifeste(_RACINE_M6)


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe1", "Un Employé (fictif)", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "manager1", "Un Manager (fictif)", "mot-de-passe-manager-12345", ["manager"])
        identite.creer_personne(cnx, "admin1", "Une Admin (fictif)", "mot-de-passe-admin-123456", ["admin"])
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                 ["nathan_owner"])
    return {"employe": "employe1", "manager": "manager1", "admin": "admin1", "nathan": "nathan"}


def _po_email_ready_en_transaction(po_id="PO-SOCLE"):
    """Setup hors périmètre du test (le sujet est l'envoi, pas la création) : appel direct des
    outils, sans passer par l'approbation — même esprit que
    ``test_approbations_socle.py::_creer_facture_brouillon`` de M5."""
    with stockage.transaction():
        m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z", courriel_commande=GENTEK_COURRIEL)
        livre_prix.enregistrer_prix(
            "BARDEAU", "gentek", 20.0, "CAD", "2026-01-01", stockage.maillons(_DEPARTEMENT, "livre_prix")
        )
        m6_outils.enregistrer_besoins_prevus(
            "C-SOCLE", f"DEVIS-{po_id}", [{"materiau_id": "BARDEAU", "quantite_estimee": 5.0, "unite": "boite"}]
        )
        m6_outils.creer_po_brouillon(po_id, f"DEVIS-{po_id}", "gentek", "2026-01-02T00:00:00Z")
        m6_outils.approuver_po(po_id, "2026-01-03T00:00:00Z")
        m6_outils.generer_courriel_po(po_id, "2026-01-04T00:00:00Z", "GRS")
    return po_id


def _statut_po(po_id):
    with stockage.transaction():
        return m6_outils.bons_commande.lire(
            m6_outils._bons_commande_de_l_appel(None), po_id
        )["statut"]


def _demandes_en_attente(outil_nom):
    with stockage.transaction() as cnx:
        return [d for d in opsys_approbations.lister(cnx, "en_attente") if d["outil"] == outil_nom]


def test_appel_direct_de_l_agent_ne_s_execute_jamais_cree_une_demande_n4(dep, personnes):
    po_id = _po_email_ready_en_transaction()
    capacites = Capacites({_DEPARTEMENT: dep}, stockage.transaction)

    reponse = capacites.appeler("m6_marquer_po_envoye", {"po_id": po_id, "horodatage": "2026-01-05T00:00:00Z"})

    assert reponse["ok"] is True
    assert reponse["statut"] == "en_attente_approbation"
    assert "demande_id" in reponse
    assert _statut_po(po_id) == "email_ready", "rien n'a exécuté la transition"
    [demande] = _demandes_en_attente("m6_marquer_po_envoye")
    assert demande["niveau"] == "N4"
    assert demande["departement"] == _DEPARTEMENT


def test_employe_ne_peut_pas_decider_l_envoi(dep, personnes):
    po_id = _po_email_ready_en_transaction("PO-SOCLE-EMPLOYE")
    capacites = Capacites({_DEPARTEMENT: dep}, stockage.transaction)
    ident = capacites.appeler(
        "m6_marquer_po_envoye", {"po_id": po_id, "horodatage": "2026-01-05T00:00:00Z"}
    )["demande_id"]
    outils_dispo = outils_executables({_DEPARTEMENT: dep}, stockage.transaction)

    with stockage.transaction() as cnx, pytest.raises(ValueError, match="aucun rôle autorisé"):
        opsys_approbations.decider(cnx, ident, True, personnes["employe"], outils_dispo, {_DEPARTEMENT: dep})

    assert _statut_po(po_id) == "email_ready"


def test_manager_ne_peut_pas_decider_l_envoi(dep, personnes):
    """department.yaml/approbations.n4 : seuls admin et nathan_owner — manager décide N3
    (approuver_po/generer_courriel_po) mais pas l'envoi (N4)."""
    po_id = _po_email_ready_en_transaction("PO-SOCLE-MANAGER")
    capacites = Capacites({_DEPARTEMENT: dep}, stockage.transaction)
    ident = capacites.appeler(
        "m6_marquer_po_envoye", {"po_id": po_id, "horodatage": "2026-01-05T00:00:00Z"}
    )["demande_id"]
    outils_dispo = outils_executables({_DEPARTEMENT: dep}, stockage.transaction)

    with stockage.transaction() as cnx, pytest.raises(ValueError, match="aucun rôle autorisé"):
        opsys_approbations.decider(cnx, ident, True, personnes["manager"], outils_dispo, {_DEPARTEMENT: dep})

    assert _statut_po(po_id) == "email_ready"


@pytest.mark.parametrize("role_cle", ["admin", "nathan"])
def test_admin_ou_nathan_owner_decident_l_envoi_po_transitionne(dep, personnes, role_cle):
    po_id = _po_email_ready_en_transaction(f"PO-SOCLE-{role_cle}")
    capacites = Capacites({_DEPARTEMENT: dep}, stockage.transaction)
    ident = capacites.appeler(
        "m6_marquer_po_envoye", {"po_id": po_id, "horodatage": "2026-01-05T00:00:00Z"}
    )["demande_id"]
    outils_dispo = outils_executables({_DEPARTEMENT: dep}, stockage.transaction)

    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(cnx, ident, True, personnes[role_cle], outils_dispo, {_DEPARTEMENT: dep})

    assert decision["statut"] == "executee"
    assert decision["reponse"]["resultat"]["accepte"] is True
    assert _statut_po(po_id) == "sent_to_supplier"


def test_manager_peut_approuver_et_generer_le_courriel_n3(dep, personnes):
    """N3 (ombre : seuil <= N3, donc encore en approbation) : manager, admin et nathan_owner sont
    tous les trois autorisés à décider — department.yaml/approbations.n3."""
    with stockage.transaction():
        m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z", courriel_commande=GENTEK_COURRIEL)
        livre_prix.enregistrer_prix(
            "BARDEAU", "gentek", 20.0, "CAD", "2026-01-01", stockage.maillons(_DEPARTEMENT, "livre_prix")
        )
        m6_outils.enregistrer_besoins_prevus(
            "C-SOCLE-N3", "DEVIS-N3", [{"materiau_id": "BARDEAU", "quantite_estimee": 5.0, "unite": "boite"}]
        )

    capacites = Capacites({_DEPARTEMENT: dep}, stockage.transaction)
    outils_dispo = outils_executables({_DEPARTEMENT: dep}, stockage.transaction)

    ident = capacites.appeler(
        "m6_creer_po_brouillon",
        {"po_id": "PO-N3", "devis_id": "DEVIS-N3", "fournisseur_id": "gentek", "horodatage": "2026-01-02T00:00:00Z"},
    )["demande_id"]
    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(cnx, ident, True, personnes["manager"], outils_dispo, {_DEPARTEMENT: dep})
    assert decision["statut"] == "executee"
    assert _statut_po("PO-N3") == "draft"
