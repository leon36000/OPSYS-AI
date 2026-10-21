"""PLAN T1.4-k2 : la vue financière d'un appel d'appareil vient de l'identité AUTHENTIFIÉE.

`m5_etat_tresorerie` prenait `role` et `autorise_couts` dans ses arguments : l'appelant choisissait ce
qu'il avait le droit de voir. Ces tests passent par les VRAIS outils (`m5_financecore.outils.outils()`,
registre durable adossé à une base SQLite migrée), appelés comme en production (`executer_atomique`),
avec de vraies personnes créées par `opsys.identite`. Ils nomment chaque refus et prouvent à chaque fois
que RIEN n'a été écrit (toutes les tables de la base comparées avant et après) ni lu (le registre des
mouvements n'est même pas ouvert). Données fictives (AGENTS.md).
"""

from __future__ import annotations

import contextlib

import pytest
from m5_financecore import acces
from m5_financecore import outils as module_outils
from m5_financecore.outils import outils
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import META

FICTIF = True
HORODATAGE = "2026-08-03T12:00:00+00:00"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")

CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"
CODE_DIFFERENTE = "REJ-IDENTITE-FOURNIE-DIFFERENTE"
CODE_ELARGI = "REJ-ROLE-ELARGI"
CODE_REQUIS = "REJ-AUTORISE-COUTS-REQUIS"


# -- installation ------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys-m5-acces.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    module_outils.utiliser_stockage_durable()
    yield url
    stockage.liberer()


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in outils()}


@pytest.fixture
def registre_garni(par_nom):
    """Solde 500.00, provisions 80.00 : argent disponible 420.00 (registre de PRODUCTION)."""
    for montant, type_mouvement in (("500.00", "ENCAISSEMENT"), ("80.00", "PROVISION")):
        reponse = executer_atomique(par_nom["m5_enregistrer_mouvement"], {
            "montant": montant, "type_mouvement": type_mouvement, "horodatage": HORODATAGE,
            "classe_retention": "STANDARD", "source": "test-fictif",
        })
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


# -- aides --------------------------------------------------------------------------------------------
@contextlib.contextmanager
def _appareil(identite_appelante):
    """Ce que `serveur_mcp.appeler_outil` et `Capacites.appeler` posent pour un appel d'appareil ; sans
    identité : un appel d'agent."""
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _etat(par_nom, arguments, identite_appelante=None):
    return _appeler(par_nom, "m5_etat_tresorerie", arguments, identite_appelante)


def _code_refus(reponse):
    """Code du verdict d'un refus : `ok` reste vrai (l'outil a répondu), `accepte` est faux."""
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _etat_accorde(reponse):
    assert reponse["ok"] is True and "verdict" not in reponse["resultat"], reponse
    return reponse["resultat"]


def _instantane_base():
    """Le contenu de TOUTES les tables de la base : un refus qui écrirait quoi que ce soit (registre,
    trace d'approbation, journal, idempotence, clé de chiffrement...) changerait cet instantané."""
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


@pytest.fixture
def registre_interdit(monkeypatch):
    """Le registre des mouvements ne doit même pas être OUVERT : un refus se rend avant toute lecture."""
    def _interdit(*_args, **_kwargs):
        raise AssertionError("le registre des mouvements a été ouvert avant le refus")

    monkeypatch.setattr(module_outils, "_registre_mouvements", _interdit)


# =========================================================================================
# 1. L'admin authentifié : la vue vient de son rôle, pas de ses arguments
# =========================================================================================
def test_l_admin_authentifie_voit_les_montants_sans_rien_fournir(par_nom, registre_garni):
    etat = _etat_accorde(_etat(par_nom, {}, ADMIN))

    assert etat["solde"] == "500.00" and etat["argent_disponible"] == "420.00"
    assert etat["role"] == "admin"  # celui du jeton, pas une étiquette de l'appelant
    # Le contrat gelé de l'état financier (ETAT_FINANCIER v1) n'a pas bougé : mêmes clés, même empreinte. T4.16 n'y
    # ajoute que des clés SŒURS : le cash libre et sa note, la mention obligatoire des analyses.
    assert set(etat) == {"type", "role", "solde", "argent_disponible", "taux_utilises", "etat_id",
                         "cash_libre", "argent_disponible_note", "mention"}


def test_la_reponse_de_l_admin_est_celle_qu_un_agent_obtient_pour_le_meme_role(par_nom, registre_garni):
    """Aucune forme nouvelle : mêmes clés, même empreinte `etat_id` que l'appel d'agent explicite."""
    appareil = _etat_accorde(_etat(par_nom, {}, ADMIN))
    agent = _etat_accorde(_etat(par_nom, {"role": "admin", "autorise_couts": True}))

    assert appareil == agent


@pytest.mark.parametrize("arguments", [
    pytest.param({"autorise_couts": True}, id="autorise_couts_vrai"),
    pytest.param({"role": "admin"}, id="role_egal_au_jeton"),
    pytest.param({"role": None, "autorise_couts": None}, id="nuls"),
    pytest.param({"role": "admin", "autorise_couts": True}, id="les_deux_concordants"),
])
def test_un_argument_qui_concorde_avec_l_identite_ne_change_rien(par_nom, registre_garni, arguments):
    etat = _etat_accorde(_etat(par_nom, arguments, ADMIN))

    assert (etat["role"], etat["solde"], etat["argent_disponible"]) == ("admin", "500.00", "420.00")


def test_un_argument_qui_restreint_la_vue_est_honore(par_nom, registre_garni):
    """Même règle que `m3_lire_devis` : un argument ne peut que RESTREINDRE. L'admin qui demande une
    vue sans montants (aperçu, écran partagé) l'obtient ; elle porte son rôle, pas un autre."""
    etat = _etat_accorde(_etat(par_nom, {"autorise_couts": False}, ADMIN))

    assert etat["role"] == "admin"
    assert etat["solde"] is None and etat["argent_disponible"] is None and etat["taux_utilises"] == []


def test_les_taux_fournis_ne_sortent_que_si_la_vue_est_autorisee(par_nom, registre_garni):
    taux = [{"identifiant": "TPS-FICTIF"}]

    complet = _etat_accorde(_etat(par_nom, {"taux_utilises": taux}, ADMIN))
    restreint = _etat_accorde(_etat(par_nom, {"taux_utilises": taux, "autorise_couts": False}, ADMIN))

    assert complet["taux_utilises"] == taux
    assert restreint["taux_utilises"] == []


# =========================================================================================
# 2. Un rôle ou une étiquette que le jeton ne porte pas : refusé, jamais remplacé en silence
# =========================================================================================
@pytest.mark.parametrize("role", ["gestionnaire", "employee", "seller", "employe", "nathan_owner", "ADMIN", ""])
def test_un_role_different_de_celui_du_jeton_est_refuse_sans_lecture_ni_ecriture(
        par_nom, registre_garni, registre_interdit, role):
    avant = _instantane_base()

    reponse = _etat(par_nom, {"role": role, "autorise_couts": True}, ADMIN)
    seul = _etat(par_nom, {"role": role}, ADMIN)

    assert _code_refus(reponse) == CODE_DIFFERENTE
    assert _code_refus(seul) == CODE_DIFFERENTE
    assert "500.00" not in str(reponse) and "420.00" not in str(reponse)
    assert _instantane_base() == avant


def test_un_role_non_textuel_ne_passe_pas_par_le_schema_ni_par_la_fonction(par_nom, registre_garni):
    assert _etat(par_nom, {"role": 7}, ADMIN)["erreur"] == "arguments_invalides"
    with _appareil(ADMIN), stockage.transaction():
        assert module_outils.etat_tresorerie(role=7)["verdict"]["code"] == CODE_DIFFERENTE


# =========================================================================================
# 3. Employé et vendeur : hors de la portée de l'outil, fermés à l'entrée puis dans le code
# =========================================================================================
def test_l_outil_ne_declare_que_l_admin_comme_role_d_appareil(par_nom):
    """Fermé par défaut pour `employee` et `seller` (T1.4-j) : c'est la déclaration que le core applique
    (`opsys/roles.json`) ; le socle en projette le même contenu (tests/test_acces_tresorerie.py)."""
    lectures = {"m5_etat_tresorerie", "m5_lister_attentes_facturation",
                "m5_lire_rentabilite_chantier", "m5_lire_comptes_a_recevoir",  # les deux précédents : T1.5-d
                "m5_lister_comptes_a_payer", "m5_saisir_facture_fournisseur",  # les deux précédents : T4.15
                "m5_lire_echeances_fiscales", "m5_lire_calendrier_obligations",  # calendriers : T4.16
                "m5_saisir_facture_sans_po", "m5_corriger_facture_fournisseur",  # les trois : T4.15-c
                "m5_annuler_facture_fournisseur",
                "m5_prevoir_tresorerie",  # la prévision de trésorerie : T4.16-d
                    "m5_constater_cash_libre", "m5_preparer_decision_capital",
                    "m5_preparer_dossier_decision_cfo"}  # T4.19-b, décision capital et dossier CFO préparatoires
    lectures |= {
        "m5_enregistrer_contrat_horaire", "m5_revoquer_contrat_horaire", "m5_lire_contrat_horaire",
    }  # M5.4.a : lecture privée et mutations N4 accessibles à l'admin appareil seulement
    lectures |= {
        "m5_lire_obligations_preparees_appareil", "m5_enregistrer_obligation_preparee_appareil",
    }  # Déclarations preparatoires T0/N0 et T1/N3, identité admin DEVICE courante obligatoire
    for nom in lectures:
        assert par_nom[nom].roles_appareil == frozenset({"admin"}), nom
    assert {nom for nom, o in par_nom.items() if o.roles_appareil} == lectures


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
@pytest.mark.parametrize("arguments", [
    pytest.param({}, id="rien"),
    pytest.param({"autorise_couts": True}, id="veut_les_couts"),
    pytest.param({"autorise_couts": False}, id="demande_une_vue_sans_montant"),
    pytest.param({"role": "admin", "autorise_couts": True}, id="se_dit_admin"),
])
def test_employe_et_vendeur_n_obtiennent_rien_meme_si_le_core_les_laissait_passer(
        par_nom, registre_garni, registre_interdit, appelante, arguments):
    """Défense en profondeur : le socle n'applique pas `roles_appareil` aux outils T0 hors du core."""
    avant = _instantane_base()

    reponse = _etat(par_nom, arguments, appelante)

    assert _code_refus(reponse) == CODE_INVALIDE
    assert appelante.role in reponse["resultat"]["verdict"]["detail"]
    assert _instantane_base() == avant


# =========================================================================================
# 4. La règle rôle -> droit, et « ne peut que restreindre » pour un rôle qui, un jour, y serait admis
# =========================================================================================
@pytest.mark.parametrize(("role", "droit"), [
    (acces.ROLE_ADMIN, True), (acces.ROLE_EMPLOYE, False), (acces.ROLE_VENDEUR, False),
    ("client", False), ("nathan_owner", False), ("inconnu", False), ("", False), (None, False),
])
def test_la_regle_ecrite_est_fermee_par_defaut(role, droit):
    assert acces.droit_couts(role) is droit


def _admettre(monkeypatch, role):
    """Simule, pour un test seulement, l'élargissement futur de la portée de l'outil à `role`."""
    monkeypatch.setattr(module_outils, "_ROLES_APPAREIL_FINANCE", frozenset({"admin", role}))
    return MARC if role == acces.ROLE_EMPLOYE else VENDEUR


@pytest.mark.parametrize("role", [acces.ROLE_EMPLOYE, acces.ROLE_VENDEUR])
def test_un_role_sans_droit_ne_peut_pas_elargir_sa_vue(par_nom, registre_garni, registre_interdit,
                                                        monkeypatch, role):
    """Le jour où la portée s'élargirait (ex. `seller` pour la marge d'une soumission, §9.4) :
    `autorise_couts=true` sans le droit reste un refus nommé, rendu avant toute lecture ni écriture."""
    appelante = _admettre(monkeypatch, role)
    avant = _instantane_base()

    elargi = _etat(par_nom, {"autorise_couts": True}, appelante)
    avec_role = _etat(par_nom, {"role": role, "autorise_couts": True}, appelante)

    assert _code_refus(elargi) == CODE_ELARGI and _code_refus(avec_role) == CODE_ELARGI
    assert "500.00" not in str(elargi) and "420.00" not in str(elargi)
    assert _instantane_base() == avant


@pytest.mark.parametrize("role", [acces.ROLE_EMPLOYE, acces.ROLE_VENDEUR])
def test_un_role_sans_droit_admis_un_jour_n_obtient_que_la_vue_sans_montant(par_nom, registre_garni,
                                                                            monkeypatch, role):
    appelante = _admettre(monkeypatch, role)

    defaut = _etat_accorde(_etat(par_nom, {}, appelante))
    explicite = _etat_accorde(_etat(par_nom, {"autorise_couts": False, "role": role}, appelante))

    for etat in (defaut, explicite):
        assert etat["role"] == role
        assert etat["solde"] is None and etat["argent_disponible"] is None and etat["taux_utilises"] == []


@pytest.mark.parametrize("valeur", ["false", "true", "", "non", 0, 1, [], {}, 0.0])
def test_autorise_couts_n_est_jamais_interprete_par_sa_verite(par_nom, registre_garni, registre_interdit, valeur):
    """La fonction peut être appelée sans passer par le schéma : la chaîne « false » est vraie en Python."""
    avant = _instantane_base()

    with _appareil(ADMIN), stockage.transaction():
        appareil = module_outils.etat_tresorerie(autorise_couts=valeur)
    with stockage.transaction():
        agent = module_outils.etat_tresorerie(role=None, autorise_couts=valeur)

    assert appareil["verdict"]["code"] == CODE_REQUIS and agent["verdict"]["code"] == CODE_REQUIS
    assert _instantane_base() == avant


# =========================================================================================
# 5. Identité non confirmée en base : refus fermé, avant toute lecture
# =========================================================================================
def _desactiver(cnx):
    identite.activer(cnx, "admin.fictif", False)


def _retirer_role(cnx):
    identite.retirer_role(cnx, "admin.fictif", "admin")


@pytest.mark.parametrize(("perturbation", "appelante"), [
    pytest.param(_desactiver, ADMIN, id="personne_desactivee"),
    pytest.param(_retirer_role, ADMIN, id="role_retire"),
    pytest.param(None, contexte.IdentiteAppelante("fantome.fictif", "admin"), id="personne_inconnue"),
    # Le jeton déclare `admin` mais la personne ne porte que `employee` : identité périmée ou falsifiée.
    pytest.param(None, contexte.IdentiteAppelante("marc.fictif", "admin"), id="role_non_porte"),
    pytest.param(None, contexte.IdentiteAppelante("admin.fictif", "role-invente"), id="role_inconnu"),
])
@pytest.mark.parametrize("arguments", [{}, {"autorise_couts": True}, {"role": "admin", "autorise_couts": True}])
def test_identite_non_confirmee_est_refusee_sans_lecture_ni_ecriture(
        par_nom, registre_garni, registre_interdit, perturbation, appelante, arguments):
    if perturbation is not None:
        with stockage.transaction() as cnx:
            perturbation(cnx)
    avant = _instantane_base()

    reponse = _etat(par_nom, arguments, appelante)

    assert _code_refus(reponse) == CODE_INVALIDE
    assert "500.00" not in str(reponse) and "420.00" not in str(reponse)
    assert _instantane_base() == avant


def test_identite_d_appareil_sans_transaction_est_refusee_fermee(registre_garni):
    """Hors transaction (aucune base jointe), l'identité n'est pas vérifiable : elle n'est pas crue sur
    parole, même si elle se dit admin."""
    with contexte.appele_par_appareil(ADMIN):
        reponse = module_outils.etat_tresorerie(role="admin", autorise_couts=True)

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == CODE_INVALIDE


def test_la_desactivation_prend_effet_a_l_appel_suivant_sans_regenerer_de_jeton(par_nom, registre_garni):
    assert _etat_accorde(_etat(par_nom, {}, ADMIN))["solde"] == "500.00"
    with stockage.transaction() as cnx:
        identite.activer(cnx, "admin.fictif", False)

    assert _code_refus(_etat(par_nom, {}, ADMIN)) == CODE_INVALIDE
    with stockage.transaction() as cnx:
        identite.activer(cnx, "admin.fictif", True)
    assert _etat_accorde(_etat(par_nom, {}, ADMIN))["solde"] == "500.00"


# =========================================================================================
# 6. Sans identité d'appareil (agent, console) : comportement d'avant, documenté
# =========================================================================================
def test_un_agent_choisit_encore_role_et_autorise_couts(par_nom, registre_garni):
    """La voie des agents (secret partagé de la passerelle) garde l'accès complet, sans contrôle de
    personne : ROLES.md, « Voie des agents »."""
    complet = _etat_accorde(_etat(par_nom, {"role": "gestionnaire", "autorise_couts": True}))
    sans_montant = _etat_accorde(_etat(par_nom, {"role": "employe", "autorise_couts": False}))
    sans_role = _etat_accorde(_etat(par_nom, {"autorise_couts": True}))

    assert (complet["role"], complet["solde"], complet["argent_disponible"]) == ("gestionnaire", "500.00", "420.00")
    assert (sans_montant["role"], sans_montant["solde"], sans_montant["argent_disponible"]) == ("employe", None, None)
    assert (sans_role["role"], sans_role["solde"]) == (None, "500.00")


def test_un_agent_doit_toujours_dire_explicitement_autorise_couts(par_nom, registre_garni, registre_interdit):
    avant = _instantane_base()

    for arguments in ({}, {"role": "gestionnaire"}, {"autorise_couts": None}):
        assert _code_refus(_etat(par_nom, arguments)) == CODE_REQUIS, arguments
    assert _instantane_base() == avant


def test_l_appel_direct_de_la_fonction_garde_sa_signature_d_avant(registre_garni):
    with stockage.transaction():
        etat = module_outils.etat_tresorerie(role="gestionnaire", autorise_couts=True)
        positionnel = module_outils.etat_tresorerie("gestionnaire", False)

    assert str(etat["solde"]) == "500.00" and str(etat["argent_disponible"]) == "420.00"
    assert positionnel["solde"] is None


# =========================================================================================
# 7. m5_lister_attentes_facturation : la même identité confirmée pour un appel d'appareil
# =========================================================================================
def _attentes(par_nom, identite_appelante=None):
    return _appeler(par_nom, "m5_lister_attentes_facturation", {}, identite_appelante)


def test_les_attentes_de_facturation_sont_lues_par_l_admin_confirme_et_par_un_agent(par_nom):
    for appelante in (ADMIN, None):
        reponse = _attentes(par_nom, appelante)
        assert reponse["ok"] is True, reponse
        assert reponse["resultat"] == {"attentes_devis": [], "attentes_wct_sans_devis_id": []}


@pytest.mark.parametrize(("perturbation", "appelante"), [
    pytest.param(_desactiver, ADMIN, id="personne_desactivee"),
    pytest.param(_retirer_role, ADMIN, id="role_retire"),
    pytest.param(None, MARC, id="employe"),
    pytest.param(None, VENDEUR, id="vendeur"),
    pytest.param(None, contexte.IdentiteAppelante("fantome.fictif", "admin"), id="personne_inconnue"),
])
def test_les_attentes_de_facturation_refusent_une_identite_non_confirmee_ou_hors_portee(
        par_nom, perturbation, appelante):
    if perturbation is not None:
        with stockage.transaction() as cnx:
            perturbation(cnx)
    avant = _instantane_base()

    assert _code_refus(_attentes(par_nom, appelante)) == CODE_INVALIDE
    assert _instantane_base() == avant


def test_la_file_du_proprietaire_ne_depend_pas_de_l_identite_d_appareil(personnes):
    """`attentes()` (file de la console) appelle la liste directement : le contrôle d'identité est celui de
    l'OUTIL, pas de la fonction métier."""
    with stockage.transaction(), contexte.appele_par_appareil(MARC):
        assert module_outils.attentes() == []
