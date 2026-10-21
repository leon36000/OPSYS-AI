"""M5 côté bus d'événements (ADR-0009 §3, PLAN T1.2-d, suite : facture brouillon).

`consommateurs()["m3.devis_accepte"]` (`_recevoir_devis_accepte`) et
`consommateurs()["m4.travaux_termines"]` (`_recevoir_travaux_termines`) gardent chacun leur pièce
dans un registre durable dédié (`devis_recus.py`, `wct_recus.py`) puis délèguent à
`_essayer_facture_brouillon`, la fonction UNIQUE qui tente la facture BROUILLON — quel que soit
l'ordre d'arrivée entre les deux événements (le flux réel, R12, ne garantit aucun ordre entre deux
TYPES d'événements différents, même patron que M6 `_evaluer_et_publier_variance`, PLAN T1.2-b).

Fail-closed : devis inconnu, complétion inconnue, chantier_id absent du devis ou WCT sans
devis_id donnent un statut d'attente nommé (`m5_lister_attentes_facturation`, T0), jamais une
facture inventée. Une incohérence interne (ex. prix_total du devis qui ne concorde pas avec la
somme recalculée des lignes) LÈVE : le répartiteur réessaie puis met en quarantaine.

Utilise le VRAI bus (`evenements.repartir` + `opsys.departements.charger_departements()`, sur les
manifestes réels de `departments/` — patron de `m02-revenue-crm/tests/test_evenements.py`), sur
une base SQLite temporaire migrée. Seul M5 est routé (`_deps_bus`) : les comptes de `repartir()`
restent ceux de M5, jamais les comptes globaux du bus. Identifiants et montants fictifs
(DEFINITION-PRODUIT §1), jamais des données réelles.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import m5_financecore.outils as outils_mod  # noqa: E402
import pytest
from m5_financecore import facturation  # noqa: E402

from opsys import evenements, stockage  # noqa: E402
from opsys.departements import charger_departements  # noqa: E402
from opsys.outils import executer  # noqa: E402

_DEPARTEMENT = "m05-financecore"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée (patron `test_outils_agent.py::_base_durable_m5`)."""
    url = f"sqlite:///{tmp_path / 'opsys-m5-evenements.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils_mod.utiliser_stockage_durable()
    yield url
    stockage.liberer()


def _deps_bus():
    """Seul M5 reçoit les événements de ces tests (M3/M4 ne consomment ni l'un ni l'autre type
    ici) : les comptes de `repartir()` restent scopés à M5, jamais globaux au bus."""
    tous = charger_departements()
    return {"m05-financecore": tous["m05-financecore"]}


def _devis_accepte(devis_id="DEVIS-1", chantier_id="CHANTIER-1", prix_total="600.00", **overrides):
    """Devis fictif à deux lignes : 40 pi de gouttière à 10.00$ + main d'oeuvre 200.00$ = 600.00$
    avant taxes (mêmes chiffres que `test_taxes.py`/`test_facturation.py` : TPS 30.00$, TVQ
    59.85$, total taxes 89.85$, montant après taxes 689.85$ — réutilisés tels quels, vérifiés)."""
    base = {
        "devis_id": devis_id,
        "lead_id": "LEAD-1",
        "chantier_id": chantier_id,
        "lignes": [
            {
                "reference_ligne": f"{devis_id}-L0",
                "description": "Gouttières 5po aluminium",
                "quantite": "40",
                "unite": "pi",
                "prix_unitaire": "10.00",
                "prix_ligne": "400.00",
                "reference_besoin_materiau": "gouttiere_5po_alu",
            },
            {
                "reference_ligne": f"{devis_id}-L1",
                "description": "Main d'oeuvre installation",
                "quantite": "1",
                "unite": "forfait",
                "prix_unitaire": "200.00",
                "prix_ligne": "200.00",
                "reference_besoin_materiau": None,
            },
        ],
        "cout_total": "450.00",
        "prix_total": prix_total,
        "taux_marge": "0.20",
        "horodatage_acceptation": "2026-09-20T10:00:00-04:00",
    }
    base.update(overrides)
    return base


def _client_associe(
    lead_id="LEAD-1", client_id="CLIENT-1-fictif", horodatage_association="2026-09-15T08:00:00-04:00", **overrides
):
    base = {"lead_id": lead_id, "client_id": client_id, "horodatage_association": horodatage_association}
    base.update(overrides)
    return base


def _wct(wct_id="WCT-1", devis_id="DEVIS-1", horodatage_completion="2026-09-25T16:30:00-04:00", **overrides):
    base = {
        "wct_id": wct_id,
        "intervention_id": f"INT-{wct_id}",
        "lead_id": "LEAD-1",
        "technicien_id": "TECH-1",
        "horodatage_completion": horodatage_completion,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 180,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": f"hash-{wct_id}",
        "consommateurs_cibles": ["M5"],
        "devis_id": devis_id,
        "statut": "completed_verified",
    }
    base.update(overrides)
    return base


def _facture_active(devis_id):
    with stockage.transaction():
        registre_cible = outils_mod._registre_factures(None)
        return facturation.facture_active_pour_devis(registre_cible, devis_id)


def _compte_factures_creees():
    with stockage.transaction():
        return sum(
            1
            for maillon in stockage.maillons(_DEPARTEMENT, "factures")
            if maillon.get("type_entree") == "facture_creee"
        )


def _attentes():
    with stockage.transaction():
        return outils_mod.lister_attentes_facturation()


def _quarantaine_m5():
    return [ligne for ligne in evenements.etat()["quarantaine"] if ligne["consommateur"] == _DEPARTEMENT]


# -- déclaration du module / du manifeste --------------------------------------------------------


def test_declaration_module_consommateurs():
    assert set(outils_mod.consommateurs()) == {
        "m2.client_associe",
        "m3.devis_accepte",
        "m4.travaux_termines",
        "m6.variance_chantier",
        "m6.reception_enregistree",  # PLAN T4.15
    }


def test_m5_declare_consommer_devis_accepte_et_travaux_termines():
    dep = charger_departements()["m05-financecore"]
    assert dep.evenements_consomme == (
        "m2.client_associe", "m3.devis_accepte", "m4.travaux_termines", "m6.variance_chantier",
        "m6.reception_enregistree",  # PLAN T4.15
    )
    fonctions = dep.charger_consommateurs()
    assert "m2.client_associe" in fonctions
    assert "m3.devis_accepte" in fonctions
    assert "m4.travaux_termines" in fonctions
    assert "m6.variance_chantier" in fonctions


# -- nominal : quel que soit l'ordre d'arrivée ----------------------------------------------------


def test_devis_puis_completion_cree_la_facture_brouillon_exacte(base_durable):
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    resume1 = evenements.repartir(deps, maintenant="2026-09-20T10:05:00-04:00")
    assert resume1["echecs"] == 0 and resume1["quarantaines"] == 0, resume1
    assert _facture_active("DEVIS-1") is None, "le WCT manque encore : pas de facture"
    assert _attentes()["attentes_devis"] == [{"devis_id": "DEVIS-1", "statut": "en_attente_travaux_termines"}]

    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume2 = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume2["echecs"] == 0 and resume2["quarantaines"] == 0, resume2

    facture = _facture_active("DEVIS-1")
    assert facture is not None
    assert facture["facture_id"] == "fac-DEVIS-1"
    assert facture["devis_id"] == "DEVIS-1"
    assert facture["chantier_id"] == "CHANTIER-1"
    assert facture["client_id"] == "LEAD-1"
    assert facture["statut"] == "BROUILLON"
    assert facture["horodatage"] == "2026-09-25T16:30:00-04:00", "horodatage = celui du WCT, jamais une horloge"

    assert len(facture["lignes"]) == 2
    assert facture["lignes"][0]["reference_ligne_devis"] == "DEVIS-1-L0"
    assert facture["lignes"][0]["montant"] == Decimal("400.00")
    assert facture["lignes"][1]["reference_ligne_devis"] == "DEVIS-1-L1"
    assert facture["lignes"][1]["montant"] == Decimal("200.00")
    somme_lignes = sum((ligne["montant"] for ligne in facture["lignes"]), Decimal("0"))
    assert somme_lignes == Decimal("600.00") == facture["montant_avant_taxes"], (
        "Σ lignes == prix_total du devis (montant_avant_taxes_fourni accepté, aucun écart)"
    )

    assert [t["id"] for t in facture["taxes"]] == ["tps_federale", "tvq_quebec"]
    assert facture["taxes"][0]["montant"] == Decimal("30.00")
    assert facture["taxes"][1]["montant"] == Decimal("59.85")
    assert facture["total_taxes"] == Decimal("89.85")
    assert facture["montant_apres_taxes"] == Decimal("689.85")

    assert _attentes() == {"attentes_devis": [], "attentes_wct_sans_devis_id": []}, "plus rien en attente"


def test_parcours_cfo_durable_devis_accepte_facture_paiement_reserves_et_camion(base_durable, monkeypatch):
    """Parcours SQLite complet; l'acquisition reste une demande d'approbation, jamais un achat."""
    configuration = {
        "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12,
                   "taxes_remises_jusqu_au": "2026-06-30"},
        "obligations_declarees": {
            cle: {"montant": "0.00", "source": "registre vérifié", "au": "2026-09-28"}
            for cle in ("paies", "das", "dettes")
        },
    }
    monkeypatch.setattr(outils_mod, "_configuration_manifeste", lambda: configuration)
    outils_mod.enregistrer_mouvement(
        "200000.00", "ENCAISSEMENT", "2026-09-18T09:00:00-04:00", "STANDARD", "solde bancaire vérifié")
    evenements.publier("m2.client_associe", "m02-revenue-crm", _client_associe())
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume = evenements.repartir(_deps_bus(), maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    facture = _facture_active("DEVIS-1")
    assert facture["statut"] == "BROUILLON" and facture["client_id"] == "CLIENT-1-fictif"

    reponse = executer(next(o for o in outils_mod.outils() if o.nom == "m5_envoyer_facture"),
                       {"facture_id": facture["facture_id"], "horodatage": "2026-09-25T17:00:00-04:00"})
    assert reponse["resultat"]["accepte"] is True
    reponse = executer(next(o for o in outils_mod.outils() if o.nom == "m5_enregistrer_paiement_facture"), {
        "facture_id": facture["facture_id"], "montant_paye": "689.85", "approbateur": "Nathan",
        "horodatage": "2026-09-27T12:00:00-04:00"})
    assert reponse["resultat"]["accepte"] is True
    # Le paiement bancaire est une pièce distincte : le changement d'état AR ne crée pas d'encaissement fictif.
    outils_mod.enregistrer_mouvement(
        "689.85", "ENCAISSEMENT", "2026-09-27T12:00:00-04:00", "STANDARD", "dépôt vérifié facture fac-DEVIS-1")
    outils_mod.enregistrer_mouvement(
        "20000.00", "PROVISION", "2026-09-27T12:05:00-04:00", "STANDARD", "réserve équipement décidée par Nathan")

    decision = outils_mod.preparer_decision_capital(
        "Camion de service", "95000.00", "Soumission concessionnaire C-95 valide jusqu'au 2026-10-30",
        "2026-10-30",
        "2026-09-30",
        {"source": "Offre de prêt P-95", "mise_de_fonds": "5000.00", "paiement_mensuel": "1600.00", "mois": 60},
        {"source": "Offre de location L-95", "mise_de_fonds": "3000.00", "paiement_mensuel": "1800.00", "mois": 48},
        autorise_couts=True,
    )
    assert decision["accepte"] is True, decision
    contenu = decision["resultat"]
    assert contenu["cash_libre_actuel"] == "180600.00"
    assert contenu["scenarios"]["achat_comptant"]["cash_libre_apres"] == "85600.00"
    assert contenu["scenarios"]["financement"]["source_offre"] == "Offre de prêt P-95"
    assert contenu["scenarios"]["location"]["source_offre"] == "Offre de location L-95"
    assert contenu["action_proposee"] == "DEMANDER_APPROBATION_HUMAINE"
    contexte = contenu["contexte_financier"]
    assert contexte["cash_libre"]["calculable"] is True
    assert {c["id"] for c in contexte["cash_libre"]["composantes"]} == {
        "taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves",
    }
    assert contexte["cash_libre"]["composantes"][-1]["montant"] == "20000.00"
    assert contexte["devis_acceptes"]["nombre"] == 1
    assert contexte["devis_acceptes"]["valeur_cad"] == "600.00"
    assert contexte["termes_contractuels_signes"]["statut"] == "NON_DISPONIBLE"
    assert contexte["provenance_des_offres"]["statut"] == "REFERENCE_MANUELLE_NON_VERIFIEE"

    equipement = outils_mod.preparer_decision_capital(
        "Équipement", "50000.00", "Soumission équipement E-50 valide au 2026-10-30",
        "2026-10-30", "2026-09-30",
        {"source": "Offre de prêt P-50", "mise_de_fonds": "8000.00", "paiement_mensuel": "950.00", "mois": 60},
        {"source": "Offre de location L-50", "mise_de_fonds": "2500.00", "paiement_mensuel": "1100.00", "mois": 48},
        autorise_couts=True,
    )
    assert equipement["accepte"] is True, equipement
    assert equipement["resultat"]["scenarios"]["achat_comptant"]["cash_libre_apres"] == "130600.00"
    assert equipement["resultat"]["scenarios"]["financement"]["total_paiements_cites"] == "65000.00"
    assert equipement["resultat"]["scenarios"]["location"]["total_paiements_cites"] == "55300.00"


def test_completion_puis_devis_produit_la_meme_facture(base_durable):
    """Symétrique du test précédent : le WCT arrive AVANT le devis accepté — le cas le plus
    fréquent en pratique (R12 §4/§9.7, la complétion terrain devance souvent l'acceptation)."""
    deps = _deps_bus()
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume1 = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume1["echecs"] == 0 and resume1["quarantaines"] == 0, resume1
    assert _facture_active("DEVIS-1") is None, "le devis manque encore : pas de facture"
    assert _attentes()["attentes_devis"] == [{"devis_id": "DEVIS-1", "statut": "en_attente_devis_accepte"}]

    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    resume2 = evenements.repartir(deps, maintenant="2026-09-25T16:36:00-04:00")
    assert resume2["echecs"] == 0 and resume2["quarantaines"] == 0, resume2

    facture = _facture_active("DEVIS-1")
    assert facture is not None
    assert facture["facture_id"] == "fac-DEVIS-1"
    assert facture["montant_avant_taxes"] == Decimal("600.00")
    assert facture["total_taxes"] == Decimal("89.85")
    assert facture["montant_apres_taxes"] == Decimal("689.85")
    assert facture["statut"] == "BROUILLON"


# -- Client 360 (PLAN T2.2) : client_id RÉEL quand connu, repli historique sinon ------------------


def test_client_associe_connu_avant_la_facture_donne_le_vrai_client_id(base_durable):
    """m2.client_associe arrive normalement en PREMIER dans le flux réel (publié à l'ingestion du
    lead, bien avant qu'un devis existe) : la facture porte alors le VRAI client_id du Client 360
    M2, jamais lead_id."""
    deps = _deps_bus()
    evenements.publier("m2.client_associe", "m02-revenue-crm", _client_associe())
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    facture = _facture_active("DEVIS-1")
    assert facture is not None
    assert facture["client_id"] == "CLIENT-1-fictif", "le vrai client_id du Client 360, jamais lead_id"


def test_client_associe_absent_replie_sur_lead_id_jamais_bloquant(base_durable):
    """Sans m2.client_associe (ordre inhabituel, ou lead antérieur à PLAN T2.2) : la facture se
    crée quand même, avec le repli historique documenté — jamais un blocage, jamais une valeur
    fabriquée (lead_id est une donnée réelle)."""
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    facture = _facture_active("DEVIS-1")
    assert facture is not None
    assert facture["client_id"] == "LEAD-1", "repli sur lead_id, comportement historique inchangé"


def test_client_associe_arrivant_apres_coup_ne_corrige_pas_la_facture_deja_creee(base_durable):
    """Immuabilité des écritures financières : m2.client_associe reçu APRÈS la création de la
    facture (repliée sur lead_id) ne la modifie jamais rétroactivement."""
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    facture_avant = _facture_active("DEVIS-1")
    assert facture_avant["client_id"] == "LEAD-1"

    evenements.publier("m2.client_associe", "m02-revenue-crm", _client_associe())
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:40:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    facture_apres = _facture_active("DEVIS-1")
    assert facture_apres["client_id"] == "LEAD-1", "aucune correction rétroactive"
    assert _compte_factures_creees() == 1, "toujours une seule facture, pas une seconde"


# -- fail-closed : attentes nommées, jamais une facture inventée ---------------------------------


def test_wct_sans_devis_id_est_une_attente_nommee_jamais_une_facture(base_durable):
    deps = _deps_bus()
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(wct_id="WCT-SANS-DEVIS", devis_id=None))
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    assert _compte_factures_creees() == 0
    attentes = _attentes()
    assert attentes["attentes_devis"] == []
    assert attentes["attentes_wct_sans_devis_id"] == [
        {"wct_id": "WCT-SANS-DEVIS", "intervention_id": "INT-WCT-SANS-DEVIS", "statut": "wct_sans_devis_id"}
    ]


def test_chantier_id_nul_est_une_attente_nommee_jamais_une_facture(base_durable):
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(devis_id="DEVIS-NUL", chantier_id=None))
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(wct_id="WCT-NUL", devis_id="DEVIS-NUL"))
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    assert _compte_factures_creees() == 0
    assert _attentes()["attentes_devis"] == [{"devis_id": "DEVIS-NUL", "statut": "en_attente_chantier_id"}]


# -- idempotence : redélivrances et double publication --------------------------------------------


def test_double_publication_et_redelivrance_ne_produit_quune_seule_facture(base_durable):
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    resume = evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert _compte_factures_creees() == 1

    # Double publication : un second événement m3.devis_accepte pour le MÊME devis_id (bug
    # producteur, ou rejeu), sous un evenement_id DIFFÉRENT — le catalogue ne les confond pas.
    evenements.publier(
        "m3.devis_accepte", "m03-estimation", _devis_accepte(), evenement_id="m3-devis-accepte-DEVIS-1-bis"
    )
    resume2 = evenements.repartir(deps, maintenant="2026-09-25T17:00:00-04:00")
    assert resume2["echecs"] == 0 and resume2["quarantaines"] == 0, resume2
    assert _compte_factures_creees() == 1, "double publication du devis : toujours une seule facture"

    # Redélivrance explicite du WCT déjà traité, à evenement_id identique.
    resume3 = evenements.repartir(deps, maintenant="2026-09-25T17:05:00-04:00")
    assert resume3 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}, (
        "les deux paires sont déjà `traite` : rien à relivrer"
    )
    assert _compte_factures_creees() == 1


def test_aucune_transition_envoyee_ou_payee_la_facture_reste_brouillon(base_durable):
    """PLAN T1.2-d (suite), point 5 : ce chantier ne fait jamais franchir BROUILLON -> ENVOYEE ni
    -> PAYEE (T3, T1.3 à venir) — un seul maillon `facture_creee`, aucun `transition_facture`."""
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    evenements.repartir(deps, maintenant="2026-09-25T16:35:00-04:00")

    with stockage.transaction():
        maillons = list(stockage.maillons(_DEPARTEMENT, "factures"))
    types = [m["type_entree"] for m in maillons]
    assert types == ["facture_creee"], "aucune transition (envoi, paiement) : toujours BROUILLON"


# -- incohérence interne : jamais une facture fabriquée --------------------------------------------


def test_incoherence_prix_total_leve_puis_quarantaine_sans_facture(base_durable):
    """`prix_total` (999.99) ne concorde pas avec la somme recalculée des lignes (600.00) : une
    incohérence interne (M3 et M5 ne devraient jamais diverger — voir T2.3-b), jamais un cas
    normal. `creer_facture_brouillon` la refuse (REJ-FACTURE-MONTANT-INCOHERENT) ; un refus sur
    une entrée que M3 est censé avoir déjà validée LÈVE (réessais puis quarantaine), plutôt que de
    publier un statut d'attente inventé pour un cas qu'on n'a pas su nommer."""
    deps = _deps_bus()
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(prix_total="999.99"))
    resume1 = evenements.repartir(deps, maintenant="2026-09-20T10:05:00-04:00")
    assert resume1["echecs"] == 0 and resume1["quarantaines"] == 0, resume1
    assert _compte_factures_creees() == 0

    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct())
    t = dt.datetime(2026, 9, 25, 16, 35, tzinfo=dt.UTC)
    resume = None
    for _ in range(5):
        resume = evenements.repartir(deps, maintenant=t.isoformat())
        t += dt.timedelta(seconds=100)

    assert resume["quarantaines"] == 1, resume
    assert _compte_factures_creees() == 0, "aucune facture fabriquée sur une incohérence interne"

    lignes = _quarantaine_m5()
    assert len(lignes) == 1
    assert lignes[0]["tentatives"] == 5
    assert "REJ-FACTURE-MONTANT-INCOHERENT" in lignes[0]["derniere_erreur"]
