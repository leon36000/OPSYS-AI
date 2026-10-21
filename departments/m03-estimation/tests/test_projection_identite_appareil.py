"""Projection par l'identité AUTHENTIFIÉE du jeton d'appareil (PLAN T1.4-c4).

Depuis T1.4-c4, `opsys.contexte.identite_appelante()` porte la personne et le rôle d'un appel
d'appareil, VÉRIFIÉS par OPSYS-CORE (jeton d'appareil) — jamais un paramètre fourni par
l'appelant. Ces tests prouvent que M3 s'y adapte enfin (relevé du PLAN, `m3_lire_devis(role=...)`
laissait l'APPELANT choisir sa vue) : pendant un appel d'appareil, la vue découle du rôle
authentifié, REVÉRIFIÉ contre `opsys.identite.personne_active` (personne encore active, portant
encore ce rôle) ; le paramètre `role` ne peut que RESTREINDRE cette vue, jamais l'élargir ; hors
appel d'appareil, le comportement historique (l'appelant choisit) est inchangé.

Même patron que `test_devis_durable_stockage.py`/`test_estimation_stockage.py` : base SQLite
temporaire migrée, appels par les outils RÉELS (`executer_atomique`, comme OPSYS-CORE via
`Capacites.appeler` — la SEULE voie qui ouvre la transaction dont `_vue_projection_effective` a
besoin pour revérifier `personne_active`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from m2_preparation_estimation import marqueur_m2

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation.outils import outils  # noqa: E402

from opsys import contexte, evenements, identite, stockage  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402

_HORODATAGE = "2026-09-28T14:00:00-04:00"
_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1",
    "unite": "pi2",
    "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}},
}


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def _appeler(nom, arguments):
    return executer_atomique(_outil(nom), arguments)


def _appeler_en_tant_quappareil(personne, role, nom, arguments):
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne=personne, role=role)):
        return _appeler(nom, arguments)


def _ligne(**surcharges):
    ligne = {
        "description": "Gouttière alu 5 po",
        "quantite": "30",
        "unite": "pi_lin",
        "cout_unitaire": "10.00",
        "reference_besoin_materiau": "besoin-goutt-001",
    }
    ligne.update(surcharges)
    return ligne


def _creer_devis(devis_id, **surcharges):
    arguments = {
        "devis_id": devis_id,
        "lead_id": "lead-001",
        "chantier_id": None,
        "lignes": [_ligne()],
        "taux_marge": "0.20",
        "horodatage": _HORODATAGE,
    }
    arguments.update(surcharges)
    reponse = _appeler("m3_creer_devis", arguments)
    assert reponse["ok"] is True, reponse
    return reponse


def _lead_assigne(lead_id="lead-001", proprietaire="vendeur.un"):
    """M2 a qualifié `lead_id` avec ce propriétaire (PLAN T1.4-k2) : le fait que M3 relit à la source du
    bus pour ne rendre à un vendeur que les devis de SES leads (`m2.lead_assigne`)."""
    with stockage.transaction():
        evenements.publier(
            "m2.lead_assigne", "m02-revenue-crm",
            {"lead_id": lead_id, "proprietaire": proprietaire, "horodatage_assignation": _HORODATAGE},
            evenement_id=f"m2-lead-assigne-{lead_id}",
        )


def _contrat(**surcharges):
    contrat = {
        "lead_id": "lead-identite-001",
        "conversation_id": "conv-identite-001",
        "type_travaux": "ravalement",
        "ville": "Quebec",
        "canal": "formulaire_web",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }
    contrat.update(surcharges)
    return contrat


def _marqueur(**surcharges):
    marqueur = marqueur_m2("lead-identite-001")
    marqueur.update(surcharges)
    return marqueur


def _photo_reference():
    return {
        "photo_id": "p1",
        "resolution_largeur": 3000,
        "resolution_hauteur": 2000,
        "eclairage": 7,
        "angle": "face",
        "reference_echelle": {"type": "porte", "dimensions_connues": True},
    }


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def personnes(base_durable):
    """Une personne par rôle d'appareil mobile (opsys.appareils.ROLES_APPAREIL), plus une
    personne SANS le rôle qu'un jeton prétendra lui attribuer (preuve de revérification)."""
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe.un", "Employé Un", _MOT_DE_PASSE, roles=["employee"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", _MOT_DE_PASSE, roles=["seller"])
        identite.creer_personne(cnx, "admin.un", "Admin Un", _MOT_DE_PASSE, roles=["admin"])
        identite.creer_personne(
            cnx, "inactif.un", "Inactif Un", _MOT_DE_PASSE, roles=["employee"], actif=False
        )
        identite.creer_personne(cnx, "sansrole.un", "Sans Rôle Un", _MOT_DE_PASSE, roles=["seller"])
    return None


# --------------------------------------------------------------------------- m3_lire_devis
def test_hors_appel_dappareil_role_par_defaut_reste_interne(personnes):
    """Comportement HISTORIQUE inchangé (PLAN T2.3-a) : sans identité d'appareil, l'appelant
    choisit — role omis vaut "interne", vue complète."""
    _creer_devis("M3-DEVIS-id-001")
    lu = _appeler("m3_lire_devis", {"devis_id": "M3-DEVIS-id-001"})
    assert lu["ok"] is True, lu
    devis = lu["resultat"]["resultat"]
    assert devis["cout_total"] == "300.00"
    assert devis["prix_total"] == "360.00"


def test_appareil_employee_sans_role_demande_recoit_la_vue_employe(personnes):
    """La vue DÉCOULE du rôle authentifié quand l'appelant n'exprime aucune préférence — jamais un
    refus par défaut ni la vue "interne" historique."""
    _creer_devis("M3-DEVIS-id-002")
    lu = _appeler_en_tant_quappareil(
        "employe.un", "employee", "m3_lire_devis", {"devis_id": "M3-DEVIS-id-002"}
    )
    assert lu["ok"] is True, lu
    devis = lu["resultat"]["resultat"]
    assert "cout_total" not in devis
    assert "prix_total" not in devis
    assert "taux_marge" not in devis
    assert devis["lignes"][0]["description"] == "Gouttière alu 5 po"
    assert "cout_unitaire" not in devis["lignes"][0]
    assert "prix_ligne" not in devis["lignes"][0]


def test_appareil_employee_role_employe_explicite_est_honore(personnes):
    """Restriction explicite ÉGALE à la vue autorisée : honorée normalement."""
    _creer_devis("M3-DEVIS-id-003")
    lu = _appeler_en_tant_quappareil(
        "employe.un", "employee", "m3_lire_devis", {"devis_id": "M3-DEVIS-id-003", "role": "employe"}
    )
    assert lu["ok"] is True, lu
    assert "prix_total" not in lu["resultat"]["resultat"]


def test_appareil_employee_role_interne_demande_est_un_refus_nomme(personnes):
    """CŒUR de la règle : role ne peut jamais ÉLARGIR la vue authentifiée. Un appareil employé qui
    demande "interne" est refusé nommément — jamais élargi, jamais rabattu en silence sur
    "employe"."""
    _creer_devis("M3-DEVIS-id-004")
    lu = _appeler_en_tant_quappareil(
        "employe.un", "employee", "m3_lire_devis", {"devis_id": "M3-DEVIS-id-004", "role": "interne"}
    )
    assert lu["ok"] is True  # rejet MÉTIER (verdict), pas une exception
    assert lu["resultat"]["accepte"] is False
    assert lu["resultat"]["verdict"]["code"] == "REJ-ROLE-ELARGI"


def test_appareil_seller_sans_role_demande_recoit_la_vue_interne(personnes):
    """DEFINITION-PRODUIT.md §9.4 : le vendeur voit risques, marge et prix de sa soumission —
    aucune restriction par défaut."""
    _creer_devis("M3-DEVIS-id-005")
    _lead_assigne()  # T1.4-k2 : un vendeur ne lit que les devis des leads dont il est propriétaire
    lu = _appeler_en_tant_quappareil(
        "vendeur.un", "seller", "m3_lire_devis", {"devis_id": "M3-DEVIS-id-005"}
    )
    assert lu["ok"] is True, lu
    assert lu["resultat"]["resultat"]["prix_total"] == "360.00"


def test_appareil_seller_peut_se_restreindre_a_employe(personnes):
    """Restriction explicite plus ÉTROITE que la vue autorisée : toujours honorée, à la discrétion
    de l'appelant."""
    _creer_devis("M3-DEVIS-id-006")
    _lead_assigne()  # T1.4-k2 : un vendeur ne lit que les devis des leads dont il est propriétaire
    lu = _appeler_en_tant_quappareil(
        "vendeur.un", "seller", "m3_lire_devis", {"devis_id": "M3-DEVIS-id-006", "role": "employe"}
    )
    assert lu["ok"] is True, lu
    assert "prix_total" not in lu["resultat"]["resultat"]


def test_appareil_admin_sans_role_demande_recoit_la_vue_interne(personnes):
    """DEFINITION-PRODUIT.md §9.5 : l'admin (l'appareil du propriétaire y compris, apparié en
    role="admin") voit tout."""
    _creer_devis("M3-DEVIS-id-007")
    lu = _appeler_en_tant_quappareil(
        "admin.un", "admin", "m3_lire_devis", {"devis_id": "M3-DEVIS-id-007"}
    )
    assert lu["ok"] is True, lu
    assert lu["resultat"]["resultat"]["cout_total"] == "300.00"


def test_personne_inactive_est_un_refus_nomme_meme_vue_employe(personnes):
    """Revérification (`personne_active`) : une personne désactivée APRÈS l'émission du jeton ne
    doit plus jamais projeter, même pour la vue la plus restrictive."""
    _creer_devis("M3-DEVIS-id-008")
    lu = _appeler_en_tant_quappareil(
        "inactif.un", "employee", "m3_lire_devis", {"devis_id": "M3-DEVIS-id-008"}
    )
    assert lu["ok"] is True
    assert lu["resultat"]["accepte"] is False
    assert lu["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_personne_qui_ne_porte_plus_le_role_du_jeton_est_un_refus_nomme(personnes):
    """"sansrole.un" porte "seller", jamais "employee" : un jeton qui prétendrait "employee" pour
    elle est une identité PÉRIMÉE (rôle retiré après émission du jeton) — refus fail-closed."""
    _creer_devis("M3-DEVIS-id-009")
    lu = _appeler_en_tant_quappareil(
        "sansrole.un", "employee", "m3_lire_devis", {"devis_id": "M3-DEVIS-id-009"}
    )
    assert lu["ok"] is True
    assert lu["resultat"]["accepte"] is False
    assert lu["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_identite_perimee_refuse_avant_meme_de_reveler_si_le_devis_existe(personnes):
    """Le refus d'identité précède la lecture du registre : un devis_id INCONNU ne change rien au
    verdict — l'identité est vérifiée d'abord."""
    lu = _appeler_en_tant_quappareil(
        "inactif.un", "employee", "m3_lire_devis", {"devis_id": "M3-DEVIS-inconnu-du-tout"}
    )
    assert lu["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


# --------------------------------------------------------------------- m3_estimer_projet
def _estimer(**surcharges):
    arguments = {
        "contrat": _contrat(),
        "marqueur": _marqueur(),
        "photos": [_photo_reference()],
        "seuils": SEUILS,
        "bareme": BAREME,
        "quantite": 1200,
        "plancher_rentable": 9000,
        "taux_marge": "0.25",
    }
    arguments.update(surcharges)
    return arguments


def test_estimer_projet_appareil_employee_naffiche_ni_cout_ni_prix_recommande(personnes):
    reponse = _appeler_en_tant_quappareil(
        "employe.un", "employee", "m3_estimer_projet", _estimer()
    )
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["accepte"] is True
    assert resultat["estimation"]["intervalle_confiance"]["borne_basse"] is None
    assert resultat["estimation"]["intervalle_confiance"]["borne_haute"] is None
    assert resultat["prix_recommande"] is None
    # le reste (verdict, devis_id, ids) n'est ni un coût ni un prix : inchangé.
    assert resultat["estimation"]["verdict_estimation"] == "AUCUN_BLOCAGE"
    assert resultat["estimation"]["devis_id"].startswith("M3-DEVIS-")


def test_estimer_projet_appareil_admin_garde_cout_et_prix_recommande(personnes):
    reponse = _appeler_en_tant_quappareil(
        "admin.un", "admin", "m3_estimer_projet", _estimer()
    )
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["estimation"]["intervalle_confiance"]["borne_basse"] is not None
    assert resultat["prix_recommande"] is not None


def test_estimer_projet_hors_appel_dappareil_inchange(personnes):
    """Hors appel d'appareil (comportement historique, PLAN T2.3-b) : rien ne change."""
    reponse = _appeler("m3_estimer_projet", _estimer())
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["estimation"]["intervalle_confiance"]["borne_basse"] is not None
    assert resultat["prix_recommande"] is not None


# ------------------------------------------- P50, P80, facteurs dominants, scénarios (PLAN T4.11) : jamais à l'employé
CLES_SOEURS_DE_MONTANTS = ("distribution_cout", "facteurs_dominants", "scenarios_prix")
TAUX_DES_SCENARIOS = {"prudent": "0.40", "normal": "0.30", "agressif": "0.15"}


def test_estimer_projet_appareil_employee_ne_voit_ni_p50_ni_facteurs_ni_scenarios(personnes):
    """P50 et P80 sont des coûts, les scénarios des prix et des marges : `_projeter_estimation_employe` retire les trois
    clés sœurs en entier (DEFINITION-PRODUIT §9.2, « l'employé ne voit jamais coûts, marges ni finances »)."""
    reponse = _appeler_en_tant_quappareil(
        "employe.un", "employee", "m3_estimer_projet", _estimer(taux_marge_scenarios=TAUX_DES_SCENARIOS)
    )
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["accepte"] is True
    for cle in CLES_SOEURS_DE_MONTANTS:
        assert resultat[cle] is None, cle
    # rien d'un montant de scénario ne se cache ailleurs dans la réponse
    texte = str(resultat)
    assert "prudent" not in texte and "P80" not in texte
    # le reste (verdict, ids) n'est ni un coût ni un prix : inchangé
    assert resultat["estimation"]["verdict_estimation"] == "AUCUN_BLOCAGE"


def test_estimer_projet_appareil_admin_et_agent_gardent_p50_facteurs_et_scenarios(personnes):
    for reponse in (
        _appeler_en_tant_quappareil(
            "admin.un", "admin", "m3_estimer_projet", _estimer(taux_marge_scenarios=TAUX_DES_SCENARIOS)),
        _appeler("m3_estimer_projet", _estimer(taux_marge_scenarios=TAUX_DES_SCENARIOS)),
    ):
        assert reponse["ok"] is True, reponse
        resultat = reponse["resultat"]
        for cle in CLES_SOEURS_DE_MONTANTS:
            assert resultat[cle] is not None, cle
        assert all(s["prix"] is not None for s in resultat["scenarios_prix"]["scenarios"])
