"""PLAN T1.4-k : qui a le droit de déclarer les matériaux utilisés, et pour quel chantier.

`m6_declarer_materiaux_utilises` relit le WCT à la source (T1.4-i) ; depuis T1.4-k il le confronte
aussi à la personne AUTHENTIFIÉE de l'appel d'appareil (`opsys.contexte.appele_par_appareil`) et à
son propre formulaire :

  - un `employee` ne déclare que pour un WCT dont le technicien est lui (`REJ-INTERVENTION-NON-ASSIGNEE`) ;
  - `intervention_id` du formulaire = celle du WCT, pour tous les appelants
    (`REJ-FORMULAIRE-MATERIAUX-INTERVENTION-INCOHERENTE`) ;
  - `chantier_id` du formulaire = celui que la source impose : le prévu du devis du WCT s'il le connaît
    (tous les appelants), sinon l'intervention du WCT pour un employé
    (`REJ-FORMULAIRE-MATERIAUX-CHANTIER-INCOHERENT`) ;
  - l'identité du jeton est relue en base (`REJ-IDENTITE-APPAREIL-INVALIDE`) ; l'admin déclare pour tous ;
    un appel sans identité d'appareil (agent) garde son comportement.

Tous les tests passent par les VRAIS outils sur une base SQLite migrée, avec de vraies personnes, et
prouvent à chaque refus que RIEN n'a été écrit (registre de stock, événements). Le WCT est publié au
bus comme M4 le fait à la complétion. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import contextlib

import pytest
from m6_material_control import outils as outils_mod
from m6_material_control.outils import consommateurs, outils
from sqlalchemy import func, select

from opsys import contexte, evenements, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True

MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
LEA = contexte.IdentiteAppelante(personne="lea.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")

CODE_NON_ASSIGNEE = "REJ-INTERVENTION-NON-ASSIGNEE"
CODE_INTERVENTION = "REJ-FORMULAIRE-MATERIAUX-INTERVENTION-INCOHERENTE"
CODE_CHANTIER = "REJ-FORMULAIRE-MATERIAUX-CHANTIER-INCOHERENT"
CODE_IDENTITE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"

# WCT de Marc (le technicien du dernier pointage de départ) : son intervention et celle de Léa.
INT_MARC, INT_LEA = "int-marc-fictif", "int-lea-fictif"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])


@pytest.fixture
def m6(personnes):
    return {o.nom: o for o in outils()}


# -- aides ----------------------------------------------------------------------------------------------
def _publier_wct(wct_id, intervention_id, technicien_id, devis_id="DEVIS-FICTIF"):
    """Ce que M4 publie à la complétion (`evenement_id = wct_id`) : M6 le relit là, jamais chez l'appelant."""
    charge = {
        "wct_id": wct_id, "intervention_id": intervention_id, "lead_id": "lead-fictif",
        "technicien_id": technicien_id, "horodatage_completion": "2026-01-01T10:00:00-05:00",
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5}, "duree_reelle_minutes": 120,
        "ecart_signale": True, "revue_id": None, "hash_maillon": "a" * 16, "consommateurs_cibles": ["M6"],
        "devis_id": devis_id, "statut": "completed_pending_review",
    }
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=wct_id)


def _receptionner(m6, chantier_id, quantite=20.0, materiau_id="MAT-1"):
    """Préalable du coût unitaire (`REJ-COUT-UNITAIRE-INTROUVABLE` sinon) : une réception antérieure."""
    reponse = executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {"po_id": f"PO-{chantier_id}", "chantier_id": chantier_id,
                        "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": quantite}],
                        "horodatage": "2025-12-01T00:00:00Z"},
        "reception_po": {"po_id": f"PO-{chantier_id}", "chantier_id": chantier_id,
                         "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}],
                         "horodatage": "2025-12-02T00:00:00Z"},
        "catalogue_materiaux": {"version": "v1", "unite_monetaire": "CAD",
                                "postes": {materiau_id: {"cout_unitaire": 5.0, "libelle": materiau_id}}},
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _prevu(m6, chantier_id, devis_id="DEVIS-FICTIF"):
    reponse = executer_atomique(m6["m6_enregistrer_besoins_prevus"], {
        "chantier_id": chantier_id, "devis_id": devis_id,
        "lignes": [{"materiau_id": "MAT-1", "quantite_estimee": 10.0, "unite": "boite"}],
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _prevu_sans_chantier(devis_id="DEVIS-FICTIF"):
    """Devis accepté avant que M4 planifie : `m3.devis_accepte.chantier_id` est null (jamais deviné)."""
    charge = {
        "devis_id": devis_id, "lead_id": "lead-fictif", "chantier_id": None,
        "lignes": [{"reference_ligne": f"{devis_id}-L1", "description": "ligne de test", "quantite": "10",
                    "unite": "boite", "prix_unitaire": "10.00", "prix_ligne": "100.00",
                    "reference_besoin_materiau": "MAT-1"}],
        "cout_total": "100.00", "prix_total": "135.00", "taux_marge": "0.35",
        "horodatage_acceptation": "2026-01-01T09:00:00-05:00",
    }
    with stockage.transaction():
        assert consommateurs()["m3.devis_accepte"](charge)["accepte"] is True


def _formulaire(wct_id, intervention_id, chantier_id, quantite=10.0):
    return {
        "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": chantier_id,
        "lignes_materiaux": [{"type_ligne": "prevu", "materiau_id": "MAT-1", "quantite": quantite,
                              "unite": "boite", "quantite_estimee": quantite}],
    }


def _declarer(m6, wct_id, formulaire, identite_appelante=None):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        return executer_atomique(m6["m6_declarer_materiaux_utilises"], {"wct_id": wct_id, "formulaire": formulaire})


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _mouvements():
    with stockage.transaction():
        return list(stockage.maillons("m06-material-control", "principal"))


def _compte_sortants():
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one()


def _etat():
    return _mouvements(), _compte_sortants()


def _consommations(wct_id):
    return [(m["type_mouvement"], m["chantier_id"], m["quantite"]) for m in _mouvements() if m.get("wct_id") == wct_id]


# =========================================================================================
# 1. Qui déclare : l'employé pour SON WCT, l'admin pour tous, l'agent comme avant
# =========================================================================================
def test_employe_declare_pour_son_propre_wct(m6):
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _receptionner(m6, INT_MARC)

    reponse = _declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, INT_MARC), MARC)

    _accepte(reponse)
    assert _consommations("wct-marc") == [("CONSOMMATION", INT_MARC, -10.0)]


def test_employe_ne_declare_pas_pour_le_wct_d_un_collegue(m6):
    _publier_wct("wct-lea", INT_LEA, "lea.fictif")
    _receptionner(m6, INT_LEA)
    avant = _etat()

    reponse = _declarer(m6, "wct-lea", _formulaire("wct-lea", INT_LEA, INT_LEA), MARC)

    assert _code_refus(reponse) == CODE_NON_ASSIGNEE
    assert _etat() == avant, "aucun mouvement de stock, aucun événement publié"


def test_le_wct_d_un_technicien_qui_n_est_pas_une_personne_n_est_a_aucun_employe(m6):
    """Une ancienne valeur de cédule (« T1 ») ne correspond à aucune personne : fail-closed."""
    _publier_wct("wct-ancien", "int-ancienne", "T1")
    _receptionner(m6, "int-ancienne")
    avant = _etat()

    reponse = _declarer(m6, "wct-ancien", _formulaire("wct-ancien", "int-ancienne", "int-ancienne"), MARC)
    assert _code_refus(reponse) == CODE_NON_ASSIGNEE

    assert _etat() == avant


def test_admin_declare_pour_le_wct_d_un_autre(m6):
    _publier_wct("wct-lea", INT_LEA, "lea.fictif")
    _receptionner(m6, INT_LEA)

    _accepte(_declarer(m6, "wct-lea", _formulaire("wct-lea", INT_LEA, INT_LEA), ADMIN))

    assert _consommations("wct-lea") == [("CONSOMMATION", INT_LEA, -10.0)]


def test_appel_sans_identite_d_appareil_garde_le_comportement_actuel(m6):
    """Agent ou console : aucun contrôle de personne (documenté, ROLES.md « Voie des agents »)."""
    _publier_wct("wct-lea", INT_LEA, "lea.fictif")
    _receptionner(m6, INT_LEA)

    _accepte(_declarer(m6, "wct-lea", _formulaire("wct-lea", INT_LEA, INT_LEA), None))

    assert _consommations("wct-lea") == [("CONSOMMATION", INT_LEA, -10.0)]


def test_wct_inconnu_reste_wct_inconnu_pour_l_employe(m6):
    _receptionner(m6, INT_MARC)
    avant = _etat()

    reponse = _declarer(m6, "wct-fabrique", _formulaire("wct-fabrique", INT_MARC, INT_MARC), MARC)

    assert reponse["resultat"] == {"accepte": False, "verdict": {"code": "REJ-WCT-INCONNU"}}
    assert _etat() == avant


def _consommer_legacy(m6, wct, formulaire):
    return executer_atomique(
        m6["m6_consommer_materiaux"],
        {"wct": wct, "formulaire": formulaire},
    )


def _formulaire_legacy(wct_id, intervention_id, chantier_id, quantite=3.0):
    return {
        "wct_id": wct_id,
        "intervention_id": intervention_id,
        "chantier_id": chantier_id,
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": quantite}],
    }


def _wct_legacy(wct_id="wct-marc", intervention_id=INT_MARC):
    return {
        "wct_id": wct_id, "intervention_id": intervention_id, "lead_id": "lead-fictif",
        "technicien_id": "marc.fictif", "horodatage_completion": "2026-01-01T10:00:00-05:00",
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5}, "duree_reelle_minutes": 120,
        "ecart_signale": True, "revue_id": None, "hash_maillon": "a" * 16,
        "consommateurs_cibles": ["M6"], "devis_id": "DEVIS-FICTIF",
    }


def test_ancien_outil_refuse_wct_non_publie_sans_modifier_le_stock(m6):
    _receptionner(m6, INT_MARC)
    avant = _mouvements()
    wct_forge = {
        "wct_id": "wct-fabrique", "intervention_id": INT_MARC, "lead_id": "lead-fictif",
        "technicien_id": "marc.fictif", "horodatage_completion": "2026-01-01T10:00:00-05:00",
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5}, "duree_reelle_minutes": 120,
        "ecart_signale": True, "revue_id": None, "hash_maillon": "a" * 16,
        "consommateurs_cibles": ["M6"], "devis_id": "DEVIS-FICTIF",
    }

    reponse = _consommer_legacy(
        m6, wct_forge, _formulaire_legacy("wct-fabrique", INT_MARC, INT_MARC)
    )

    assert _code_refus(reponse) == "REJ-WCT-INCONNU"
    assert _mouvements() == avant


def test_ancien_outil_refuse_intervention_divergente_sans_modifier_le_stock(m6):
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _receptionner(m6, INT_MARC)
    avant = _mouvements()
    wct = _wct_legacy()

    reponse = _consommer_legacy(
        m6, wct, _formulaire_legacy("wct-marc", INT_LEA, INT_MARC)
    )

    assert _code_refus(reponse) == "REJ-FORMULAIRE-MATERIAUX-INTERVENTION-INCOHERENTE"
    assert _mouvements() == avant


def test_ancien_outil_ne_debite_pas_deux_fois_le_meme_wct_sous_une_autre_cle(m6):
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _receptionner(m6, INT_MARC)
    wct = _wct_legacy()
    formulaire = _formulaire_legacy("wct-marc", INT_MARC, INT_MARC)
    premiere = _consommer_legacy(m6, wct, formulaire)
    apres_premiere = _mouvements()

    seconde = _consommer_legacy(m6, wct, formulaire)

    assert _accepte(premiere)
    assert _code_refus(seconde) == "REJ-DECLARATION-DEJA-SOUMISE"
    assert _mouvements() == apres_premiere
    assert _consommations("wct-marc") == [("CONSOMMATION", INT_MARC, -3.0)]


def test_une_seconde_declaration_du_meme_wct_reste_refusee_pour_l_employe(m6):
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _receptionner(m6, INT_MARC, quantite=40.0)
    _accepte(_declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, INT_MARC), MARC))
    avant = _etat()

    reponse = _declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, INT_MARC), MARC)

    assert _code_refus(reponse) == "REJ-DECLARATION-DEJA-SOUMISE"
    assert _etat() == avant


# =========================================================================================
# 2. L'intervention du formulaire est celle du WCT (tous les appelants)
# =========================================================================================
@pytest.mark.parametrize("appelant", [MARC, ADMIN, None], ids=["employe", "admin", "agent"])
def test_intervention_du_formulaire_differente_de_celle_du_wct_est_refusee(m6, appelant):
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _receptionner(m6, INT_MARC)
    avant = _etat()

    reponse = _declarer(m6, "wct-marc", _formulaire("wct-marc", INT_LEA, INT_MARC), appelant)

    assert _code_refus(reponse) == CODE_INTERVENTION
    assert _etat() == avant


def test_le_refus_d_assignation_precede_la_concordance_du_formulaire(m6):
    """Un employé qui vise le WCT d'un autre avec un formulaire incohérent apprend « non assignée »."""
    _publier_wct("wct-lea", INT_LEA, "lea.fictif")

    assert _code_refus(_declarer(m6, "wct-lea", _formulaire("wct-lea", "autre", "autre"), MARC)) == CODE_NON_ASSIGNEE


# =========================================================================================
# 3. Le chantier du formulaire est confronté à la source
# =========================================================================================
@pytest.mark.parametrize("appelant", [MARC, ADMIN, None], ids=["employe", "admin", "agent"])
def test_chantier_du_formulaire_different_du_prevu_du_devis_est_refuse(m6, appelant):
    """Le prévu du devis du WCT connaît son chantier : le formulaire doit le porter, pour tous."""
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _prevu(m6, "CH-DU-DEVIS")
    _receptionner(m6, "CH-DU-DEVIS")
    _receptionner(m6, "CH-AUTRE")
    avant = _etat()

    reponse = _declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, "CH-AUTRE"), appelant)

    assert _code_refus(reponse) == CODE_CHANTIER
    assert "CH-DU-DEVIS" not in str(reponse), "le refus ne révèle pas le chantier attendu"
    assert _etat() == avant


@pytest.mark.parametrize("appelant", [MARC, ADMIN, None], ids=["employe", "admin", "agent"])
def test_chantier_du_formulaire_egal_a_celui_du_prevu_est_accepte(m6, appelant):
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _prevu(m6, "CH-DU-DEVIS")
    _receptionner(m6, "CH-DU-DEVIS")

    _accepte(_declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, "CH-DU-DEVIS"), appelant))
    assert _consommations("wct-marc") == [("CONSOMMATION", "CH-DU-DEVIS", -10.0)]


@pytest.mark.parametrize("appelant", [MARC, ADMIN, None], ids=["employe", "admin", "agent"])
@pytest.mark.parametrize("type_ligne", ["prevu", "non_prevu", "retour", "perte", "bris", "achat_terrain"])
def test_unite_connue_incoherente_refuse_tout_le_lot_pour_tous_les_appelants(m6, appelant, type_ligne):
    """WCT publié par fixture ici ; la verticale HTTP couvre séparément sa naissance native.

    Le premier article valide ne doit pas être écrit avant de découvrir le conflit
    d'unité sur le second. Aucun rôle ou type de mouvement ne contourne la source connue.
    """
    _publier_wct("wct-unite-fictif", INT_MARC, "marc.fictif")
    _prevu(m6, INT_MARC)  # unité canonique : boite
    _receptionner(m6, INT_MARC)
    formulaire = _formulaire("wct-unite-fictif", INT_MARC, INT_MARC, quantite=1.0)
    ligne_incoherente = {"type_ligne": type_ligne, "materiau_id": "MAT-1", "quantite": 2.0, "unite": "pi"}
    if type_ligne == "prevu":
        ligne_incoherente["quantite_estimee"] = 10.0
    if type_ligne == "achat_terrain":
        ligne_incoherente.update(photo_fournie=True, recu_fourni=False)  # justificatif fictif
    formulaire["lignes_materiaux"].append(ligne_incoherente)
    avant = _etat()

    reponse = _declarer(m6, "wct-unite-fictif", formulaire, appelant)

    assert _code_refus(reponse) == "REJ-FORMULAIRE-MATERIAUX-UNITE-INCOHERENTE"
    assert _etat() == avant and _consommations("wct-unite-fictif") == []

def test_le_prevu_l_emporte_sur_l_intervention_meme_pour_l_employe(m6):
    """Le prévu connaît le chantier : l'employé qui envoie l'identifiant de son intervention (ce que
    l'app envoie) est refusé si le chantier du devis est un autre. Pas de repli sur l'intervention."""
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _prevu(m6, "CH-DU-DEVIS")
    _receptionner(m6, INT_MARC)
    avant = _etat()

    assert _code_refus(_declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, INT_MARC), MARC)) == CODE_CHANTIER
    assert _etat() == avant


def test_sans_prevu_l_employe_ne_declare_que_pour_le_chantier_de_son_intervention(m6):
    """Aucun prévu : la source ne connaît pour lui que son intervention (un chantier de M4 EST une
    intervention). Ce que l'app envoie passe ; un autre chantier, non."""
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _receptionner(m6, INT_MARC)
    _receptionner(m6, "CH-D-UN-AUTRE-CHANTIER")
    avant = _etat()

    autre_chantier = _formulaire("wct-marc", INT_MARC, "CH-D-UN-AUTRE-CHANTIER")
    assert _code_refus(_declarer(m6, "wct-marc", autre_chantier, MARC)) == CODE_CHANTIER
    assert _etat() == avant

    _accepte(_declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, INT_MARC), MARC))
    assert _consommations("wct-marc") == [("CONSOMMATION", INT_MARC, -10.0)]


def test_prevu_sans_chantier_meme_regle_pour_l_employe_jamais_un_chantier_devine(m6):
    """Devis accepté avant que M4 planifie (`chantier_id` null) : rien n'est deviné, l'employé retombe
    sur son intervention."""
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _prevu_sans_chantier()
    _receptionner(m6, INT_MARC)
    _receptionner(m6, "CH-AUTRE")

    assert _code_refus(_declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, "CH-AUTRE"), MARC)) == CODE_CHANTIER
    _accepte(_declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, INT_MARC), MARC))


@pytest.mark.parametrize("appelant", [ADMIN, None], ids=["admin", "agent"])
def test_sans_prevu_admin_et_agent_declarent_pour_le_chantier_qu_ils_connaissent(m6, appelant):
    """Le chantier d'un bon de commande, qu'un admin ou un agent connaît légitimement, n'est pas
    l'intervention : la source ne dit rien, rien n'est refusé ni deviné (documenté dans ROLES.md)."""
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _receptionner(m6, "CH-BON-DE-COMMANDE")

    _accepte(_declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, "CH-BON-DE-COMMANDE"), appelant))

    assert _consommations("wct-marc") == [("CONSOMMATION", "CH-BON-DE-COMMANDE", -10.0)]


def test_wct_sans_devis_ne_connait_aucun_prevu_donc_aucun_chantier(m6):
    _publier_wct("wct-marc", INT_MARC, "marc.fictif", devis_id=None)
    _prevu(m6, "CH-D-UN-AUTRE-DEVIS", devis_id="DEVIS-D-UN-AUTRE")
    _receptionner(m6, "CH-D-UN-AUTRE-DEVIS")

    # Le prévu d'un autre devis n'est jamais utilisé : l'employé retombe sur son intervention.
    formulaire = _formulaire("wct-marc", INT_MARC, "CH-D-UN-AUTRE-DEVIS")
    assert _code_refus(_declarer(m6, "wct-marc", formulaire, MARC)) == CODE_CHANTIER


# =========================================================================================
# 4. Identité invalide : fail-closed
# =========================================================================================
def _desactiver(cnx):
    identite.activer(cnx, "marc.fictif", False)


def _retirer_role(cnx):
    identite.retirer_role(cnx, "marc.fictif", "employee")


@pytest.mark.parametrize(("perturbation", "appelante"), [
    pytest.param(_desactiver, MARC, id="personne_desactivee"),
    pytest.param(_retirer_role, MARC, id="role_retire"),
    pytest.param(None, contexte.IdentiteAppelante("fantome.fictif", "employee"), id="personne_inconnue"),
    pytest.param(None, contexte.IdentiteAppelante("marc.fictif", "admin"), id="role_non_porte"),
    pytest.param(None, contexte.IdentiteAppelante("vendeur.fictif", "seller"), id="role_sans_portee_m6"),
])
def test_identite_non_confirmee_est_refusee_avant_toute_lecture_ou_ecriture(m6, perturbation, appelante):
    _publier_wct("wct-marc", INT_MARC, "marc.fictif")
    _receptionner(m6, INT_MARC)
    if perturbation is not None:
        with stockage.transaction() as cnx:
            perturbation(cnx)
    avant = _etat()

    reponse = _declarer(m6, "wct-marc", _formulaire("wct-marc", INT_MARC, INT_MARC), appelante)

    assert _code_refus(reponse) == CODE_IDENTITE_INVALIDE
    assert _etat() == avant


def test_identite_d_appareil_hors_transaction_est_refusee_fermee(base_durable):
    """Hors transaction rien n'est vérifiable (ni personne, ni bus) : l'identité n'est pas crue sur parole."""
    with contexte.appele_par_appareil(MARC):
        resultat = outils_mod.declarer_materiaux_utilises("wct-marc", _formulaire("wct-marc", INT_MARC, INT_MARC))

    assert resultat["accepte"] is False and resultat["verdict"]["code"] == CODE_IDENTITE_INVALIDE


def test_l_identite_vient_du_contexte_pas_des_arguments(m6):
    """Le formulaire ne porte aucun champ de personne (schéma fermé) : on ne peut pas s'en donner une."""
    _publier_wct("wct-lea", INT_LEA, "lea.fictif")
    formulaire = {**_formulaire("wct-lea", INT_LEA, INT_LEA), "technicien_id": "marc.fictif"}

    reponse = _declarer(m6, "wct-lea", formulaire, MARC)

    assert _code_refus(reponse) == CODE_NON_ASSIGNEE  # la personne authentifiée décide, avant la forme


# =========================================================================================
# 5. Portée déclarée
# =========================================================================================
def test_la_declaration_reste_ouverte_a_l_employe_et_a_l_admin_seulement():
    declaree = {o.nom: o for o in outils()}["m6_declarer_materiaux_utilises"]

    assert declaree.roles_appareil == frozenset({"employee", "admin"})
