"""PLAN T4.15-c : corriger, annuler, et saisir une facture sans PO, sur le VRAI socle.

`m5_corriger_facture_fournisseur` et `m5_annuler_facture_fournisseur` sont N4 (engagement, ADR-0009 §4) ;
`m5_saisir_facture_sans_po` est N3 comme la saisie d'une facture de PO. Aucun des trois n'agit pour un agent seul :
l'OUTIL exige un humain, par l'une de deux voies (jeton d'appareil confirmé en base, ou demande approuvée dans la file,
dont le SOCLE dit qui l'a approuvée : `approbations.approbateur_en_cours`).

Base SQLite temporaire migrée, vrai manifeste de M5 (mode `ombre`), vraies approbations, vrai répartiteur. Le cas de
référence est celui de `test_correction_facture.py` (PO de 320.00 $, 300.00 $ reçus, facture F-1001 de 300.00 $ :
344.93 $). Personnes, identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import comptes_a_payer, facturation, registre, taux_fiscaux
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION
from sqlalchemy import select, update

from opsys import approbations as opsys_approbations
from opsys import contexte, evenements, idempotence, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import Niveau, executer_atomique
from opsys.stockage.schema import APPROBATIONS, META

FICTIF = True
D = Decimal
_RACINE_M5 = Path(__file__).resolve().parents[1]
DEPARTEMENT = "m05-financecore"
LIVRAISON = "2026-09-29T09:15:00-04:00"
SAISIE = "2026-10-08T10:00:00-04:00"
CORRECTION = "2026-10-09T10:00:00-04:00"
ANNULATION = "2026-10-10T10:00:00-04:00"

# Trois personnes qui portent un jeton d'appareil `admin` : le propriétaire, une comptable qui a aussi `admin`, et une
# gestionnaire qui n'est NI l'un NI l'autre (un rôle `admin` ne dit pas qui est le propriétaire).
NATHAN = contexte.IdentiteAppelante(personne="nathan", role="admin")
COMPTABLE = contexte.IdentiteAppelante(personne="comptable", role="admin")
GESTION = contexte.IdentiteAppelante(personne="gestion", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
FANTOME = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")

CATEGORIES = {"categories_depense_sans_po": ["carburant", "outils"]}


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-correction.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234",
                                ["finance", "admin"])
        identite.creer_personne(cnx, "gestion", "Une Gestionnaire (fictive)", "mot-de-passe-gestion-123",
                                ["manager", "admin"])
        identite.creer_personne(cnx, "financeuse", "Finance sans appareil (fictive)", "mot-de-passe-finance-1234",
                                ["finance"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
    yield url
    stockage.liberer()


@pytest.fixture
def dep():
    return lire_manifeste(_RACINE_M5)


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


@pytest.fixture
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    return dictionnaire


@pytest.fixture
def declare(tmp_path, monkeypatch):
    """Le manifeste de test : ce que le propriétaire a écrit sous `configuration`, relu à chaque appel."""
    def _declarer(configuration):
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    return _declarer


# ------------------------------------------------------------------------------------------ petits outils
def _charge(evenement_id="evt-1", po_id="PO-1", quantite="60"):
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": LIVRAISON, "verdict_reception": "RECEPTION_INFERIEURE",
        "statut_po": "partially_received", "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": "60", "quantite_recue": quantite,
                    "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE",
                    "ecart_prix_critique": None}],
    }


def _recevoir(dep, **kwargs):
    charge = _charge(**kwargs)
    with stockage.transaction():
        evenements.publier("m6.reception_enregistree", "m06-material-control", charge,
                           evenement_id=charge["evenement_id"])
    resume = evenements.repartir({DEPARTEMENT: dep}, maintenant="2026-09-29T12:00:00+00:00")
    assert resume["traites"] >= 1 and resume["echecs"] == 0, resume


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _facture_args(**surcharges):
    args = {"po_id": "PO-1", "fournisseur_id": "gentek", "numero_facture": "F-1001", "date_facture": "2026-10-01",
            "montant_avant_taxes": "300.00", "total_facture": None, "horodatage": SAISIE}
    args.update(surcharges)
    return args


def _revision_lue(ident):
    """La révision que la personne lit AU MOMENT DE PROPOSER, comme la ligne des comptes à payer la montre : son champ
    `corrections`, absent d'une facture jamais touchée (statut SAISIE : révision 0). Une facture absente du registre
    n'a pas de révision lue : `KeyError`, jamais un 0 inventé."""
    vue = comptes_a_payer.vue_facture(comptes_a_payer._etats_factures(_registre_ap())[ident])
    if "corrections" not in vue:
        assert vue["statut"] == "SAISIE", vue
        return 0
    return vue["corrections"]


def _corriger_args(ident, **surcharges):
    """Sans `revision_attendue` en surcharge : celle lue sur la facture à cet instant (`_revision_lue`)."""
    args = {"facture_fournisseur_id": ident, "motif": "Faute de frappe sur le montant (fictif)",
            "numero_facture": None, "date_facture": None, "montant_avant_taxes": "310.00", "total_facture": None,
            "horodatage": CORRECTION}
    if "revision_attendue" not in surcharges:
        args["revision_attendue"] = _revision_lue(ident)
    args.update(surcharges)
    return args


def _annuler_args(ident, **surcharges):
    args = {"facture_fournisseur_id": ident, "motif": "Saisie sous le mauvais PO (fictif)", "horodatage": ANNULATION}
    if "revision_attendue" not in surcharges:
        args["revision_attendue"] = _revision_lue(ident)
    args.update(surcharges)
    return args


def _sans_po_args(**surcharges):
    args = {"fournisseur_id": "Pétro-Nord (fictif)", "categorie": "carburant", "numero_facture": "C-4001",
            "date_facture": "2026-10-01", "montant_avant_taxes": "100.00", "total_facture": None,
            "horodatage": SAISIE}
    args.update(surcharges)
    return args


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _registre_ap():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, "comptes_a_payer"))


def _instantane_base():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


def _liste(par_nom, arguments=None, identite_appelante=NATHAN):
    return _accepte(_appeler(par_nom, "m5_lister_comptes_a_payer", arguments or {}, identite_appelante))


def _le_po(par_nom):
    (ligne,) = _liste(par_nom, {"po_id": "PO-1"})["comptes"]
    return ligne


@pytest.fixture
def facture(dep, par_nom):
    """PO-1 reçu (300.00 $) et la facture F-1001 saisie par l'admin sur son téléphone : son identifiant."""
    _recevoir(dep)
    resultat = _accepte(_appeler(par_nom, "m5_saisir_facture_fournisseur", _facture_args(), COMPTABLE))
    return resultat["facture"]["facture_fournisseur_id"]


def _demande_puis_decision(dep, nom, arguments, decideur, *, approuver=True, role=None, mode=None):
    """L'agent (sans jeton d'appareil) PROPOSE, un humain décide dans la file : rend (réponse de la file, décision)."""
    departement = dataclasses.replace(dep, mode=mode) if mode is not None else dep
    capacites = Capacites({DEPARTEMENT: departement}, stockage.transaction)
    demande = capacites.appeler(nom, arguments)
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, demande["demande_id"], approuver, decideur,
            outils_executables({DEPARTEMENT: departement}, stockage.transaction), {DEPARTEMENT: departement},
            role=role)
    return demande, decision


# ============================================================================================= le contrat
def test_les_trois_outils_ont_leur_niveau_leur_portee_et_des_arguments_tous_requis(par_nom):
    sans_po, corriger, annuler = (par_nom[n] for n in (
        "m5_saisir_facture_sans_po", "m5_corriger_facture_fournisseur", "m5_annuler_facture_fournisseur"))

    assert sans_po.autonomie.value == "T1" and sans_po.niveau_effectif is Niveau.N3
    for outil in (corriger, annuler):
        assert outil.autonomie.value == "T2" and outil.niveau_effectif is Niveau.N4, outil.nom
        assert outil.niveau is Niveau.N4, "le niveau est déclaré, pas déduit"
    for outil in (sans_po, corriger, annuler):
        assert outil.roles_appareil == frozenset({"admin"}) and outil.frontiere_humaine is False, outil.nom
        schema = outil.parametres
        # Le lien N4 à la révision vue est requis lui aussi (test_revision_facture_fournisseur.py).
        assert set(schema["properties"]) - set(schema["required"]) == set(), outil.nom
        assert schema["additionalProperties"] is False
    assert corriger.parametres["properties"]["numero_facture"]["type"] == ["string", "null"]
    assert corriger.parametres["properties"]["montant_avant_taxes"]["type"] == ["string", "null"]
    assert annuler.parametres["properties"].keys() == {"facture_fournisseur_id", "motif", "horodatage",
                                                       "revision_attendue"}
    assert m5_outils.NIVEAU_CORRECTION_FACTURE_FOURNISSEUR is Niveau.N4


def test_aucun_montant_calcule_ni_identite_ne_se_passe_en_argument(par_nom, facture):
    for argument in ({"taxes": []}, {"total_taxes": "46.42"}, {"montant_apres_taxes": "356.42"}, {"statut": "ANNULEE"},
                     {"corrige_par": "nathan"}, {"voie": "appareil"}, {"role": "nathan_owner"}):
        reponse = _appeler(par_nom, "m5_corriger_facture_fournisseur", {**_corriger_args(facture), **argument}, NATHAN)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", argument
    for argument in ({"annule_par": "nathan"}, {"voie": "appareil"}, {"statut": "ANNULEE"}):
        reponse = _appeler(par_nom, "m5_annuler_facture_fournisseur", {**_annuler_args(facture), **argument}, NATHAN)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", argument
    for argument in ({"taxes": []}, {"po_id": "PO-1"}, {"saisi_par": "nathan"}, {"total_taxes": "14.98"}):
        reponse = _appeler(par_nom, "m5_saisir_facture_sans_po", {**_sans_po_args(), **argument}, NATHAN)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", argument


def test_les_roles_n4_du_code_sont_ceux_du_manifeste_la_voie_directe_n_est_jamais_plus_large_que_la_file(dep):
    assert m5_outils._ROLES_APPROBATEURS_N4 == dep.roles_autorises(Niveau.N4) == frozenset({"finance", "nathan_owner"})
    assert dep.roles_autorises(Niveau.N3) | {"admin"} == m5_outils._ROLES_APPROBATEURS_SAISIE


# ====================================================== la voie de l'appareil (un humain, propriétaire ou finance)
def test_le_proprietaire_corrige_depuis_son_appareil_et_la_piece_porte_son_nom(par_nom, facture):
    reponse = _appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture), NATHAN)

    resultat = _accepte(reponse)
    assert resultat["mention"] == MENTION
    assert resultat["facture"]["statut"] == "CORRIGEE" and resultat["facture"]["montant_apres_taxes"] == "356.42"
    assert resultat["facture"]["derniere_modification"]["par"] == "nathan"
    rapprochement = resultat["rapprochement"]
    assert rapprochement["verdict"] == "ECART" and rapprochement["facture_moins_recu"] == "10.00"
    piece = _registre_ap()[-1]
    assert (piece["corrige_par"], piece["role"], piece["voie"]) == ("nathan", "admin", "appareil")
    assert piece["motif"] == "Faute de frappe sur le montant (fictif)"
    assert piece["avant"]["montant_avant_taxes"] == D("300.00")


def test_la_finance_avec_un_appareil_admin_corrige_et_annule_elle_aussi(par_nom, facture):
    _accepte(_appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture), COMPTABLE))
    annulee = _accepte(_appeler(par_nom, "m5_annuler_facture_fournisseur", _annuler_args(facture), COMPTABLE))

    assert annulee["facture"]["statut"] == "ANNULEE"
    assert [m["type_entree"] for m in _registre_ap()[-2:]] == [
        "correction_facture_fournisseur", "annulation_facture_fournisseur"]
    assert _registre_ap()[-1]["annule_par"] == "comptable"


@pytest.mark.parametrize("outil, arguments", [
    ("m5_corriger_facture_fournisseur", lambda ident: _corriger_args(ident)),
    ("m5_annuler_facture_fournisseur", lambda ident: _annuler_args(ident)),
], ids=["corriger", "annuler"])
def test_un_admin_qui_n_est_ni_proprietaire_ni_finance_ne_fait_rien_meme_par_la_voie_directe(
        par_nom, facture, outil, arguments):
    """Le rôle `admin` du jeton ne dit pas qui est le propriétaire : la PERSONNE doit porter `nathan_owner` ou
    `finance`. Sinon, en mode `autonome` où un N4 s'exécute sans file, une gestionnaire corrigerait seule."""
    avant = _instantane_base()

    reponse = _appeler(par_nom, outil, arguments(facture), GESTION)

    assert _code(reponse) == "REJ-AP-APPROBATEUR-REQUIS"
    detail = reponse["resultat"]["verdict"]["detail"]
    assert "propriétaire" in detail and "file OPSYS" in detail
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
@pytest.mark.parametrize("outil, arguments", [
    ("m5_corriger_facture_fournisseur", lambda ident: _corriger_args(ident)),
    ("m5_annuler_facture_fournisseur", lambda ident: _annuler_args(ident)),
    ("m5_saisir_facture_sans_po", lambda _ident: _sans_po_args()),
], ids=["corriger", "annuler", "sans_po"])
def test_un_employe_ou_un_vendeur_ne_fait_rien_et_le_registre_n_est_meme_pas_ouvert(
        par_nom, facture, monkeypatch, appelante, outil, arguments):
    avant = _instantane_base()

    def _interdit(*_args, **_kwargs):
        raise AssertionError("le registre des comptes à payer a été ouvert avant le refus")

    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5_outils, "_registre_comptes_a_payer", _interdit)
        reponse = _appeler(par_nom, outil, arguments(facture), appelante)

    assert _code(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [
    FANTOME, contexte.IdentiteAppelante(personne="nathan", role="employee"),
    contexte.IdentiteAppelante(personne="marc.fictif", role="admin")],
    ids=["inconnue", "role_que_la_personne_n_a_pas", "employe_qui_se_dit_admin"])
def test_une_identite_d_appareil_inconnue_ou_sans_le_role_est_refusee(par_nom, facture, appelante):
    avant = _instantane_base()

    for outil, arguments in (("m5_corriger_facture_fournisseur", _corriger_args(facture)),
                             ("m5_annuler_facture_fournisseur", _annuler_args(facture))):
        assert _code(_appeler(par_nom, outil, arguments, appelante)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _instantane_base() == avant


def test_une_personne_desactivee_depuis_l_appairage_ne_corrige_rien(par_nom, facture):
    with stockage.transaction() as cnx:
        identite.activer(cnx, "nathan", False)
    avant = _instantane_base()

    reponse = _appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture), NATHAN)

    assert _code(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE" and _instantane_base() == avant


# ================================================================================ l'agent ne fait jamais seul
@pytest.mark.parametrize("outil, arguments, phrase", [
    ("m5_corriger_facture_fournisseur", lambda ident: _corriger_args(ident), "ne le présente pas comme fait"),
    ("m5_annuler_facture_fournisseur", lambda ident: _annuler_args(ident), "ne le présente pas comme fait"),
    ("m5_saisir_facture_sans_po", lambda _ident: _sans_po_args(), "ne la présente pas comme saisie"),
], ids=["corriger", "annuler", "sans_po"])
def test_un_agent_sans_identite_ni_approbation_est_refuse_par_l_outil_lui_meme(
        par_nom, facture, declare, outil, arguments, phrase):
    declare(CATEGORIES)
    avant = _instantane_base()

    reponse = _appeler(par_nom, outil, arguments(facture), None)

    assert _code(reponse) == "REJ-AP-HUMAIN-REQUIS" and phrase in reponse["resultat"]["verdict"]["detail"]
    assert _instantane_base() == avant


def test_en_mode_autonome_un_n4_s_execute_sans_file_et_l_outil_refuse_l_agent(dep, facture):
    """ADR-0009 fait exécuter un N4 en mode `autonome` : c'est l'outil, pas la file, qui exige l'humain."""
    autonome = dataclasses.replace(dep, mode="autonome")
    capacites = Capacites({DEPARTEMENT: autonome}, stockage.transaction)
    avant = _instantane_base()

    corriger = capacites.appeler("m5_corriger_facture_fournisseur", _corriger_args(facture))
    annuler = capacites.appeler("m5_annuler_facture_fournisseur", _annuler_args(facture))

    for reponse in (corriger, annuler):
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
        assert reponse["resultat"]["verdict"]["code"] == "REJ-AP-HUMAIN-REQUIS"
    assert _instantane_base() == avant


@pytest.mark.parametrize("mode", ["ombre", "supervise"])
def test_en_mode_ombre_ou_supervise_l_agent_propose_un_n4_qui_attend_sans_rien_ecrire(dep, facture, mode):
    departement = dataclasses.replace(dep, mode=mode)
    capacites = Capacites({DEPARTEMENT: departement}, stockage.transaction)
    avant = _registre_ap()

    demande = capacites.appeler("m5_corriger_facture_fournisseur", _corriger_args(facture))

    assert demande["statut"] == "en_attente_approbation" and _registre_ap() == avant
    with stockage.transaction() as cnx:
        (ligne,) = cnx.execute(select(APPROBATIONS.c.niveau, APPROBATIONS.c.statut, APPROBATIONS.c.arguments).where(
            APPROBATIONS.c.id == demande["demande_id"])).all()
    assert ligne[:2] == ("N4", "en_attente") and json.loads(ligne[2])["motif"].startswith("Faute de frappe")


def test_une_demande_seulement_en_attente_n_autorise_rien(dep, par_nom, facture):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    demande = capacites.appeler("m5_corriger_facture_fournisseur", _corriger_args(facture))
    assert demande["statut"] == "en_attente_approbation"
    avant = _instantane_base()

    reponse = _appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture), None)

    assert _code(reponse) == "REJ-AP-HUMAIN-REQUIS" and _instantane_base() == avant


def test_une_ligne_en_cours_ecrite_a_la_main_ne_donne_pas_le_droit_de_corriger(dep, par_nom, facture):
    """Ce que la lecture de table d'avant acceptait (une demande `en_cours` aux mêmes arguments, de rôle humain) ne
    vaut plus rien : seul `decider`, en train d'exécuter, dit qui a approuvé."""
    arguments = _corriger_args(facture)
    with stockage.transaction() as cnx:
        ident = opsys_approbations.creer_demande(cnx, DEPARTEMENT, "m5_corriger_facture_fournisseur", arguments,
                                                 niveau=Niveau.N4)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut="en_cours", decide_par="nathan", decide_role="nathan_owner"))
    avant = _instantane_base()

    reponse = _appeler(par_nom, "m5_corriger_facture_fournisseur", arguments, None)

    assert _code(reponse) == "REJ-AP-HUMAIN-REQUIS" and _instantane_base() == avant


# ===================================================================== la voie de l'approbation (la file du N4)
def test_l_agent_propose_la_finance_approuve_et_la_correction_porte_son_nom(dep, par_nom, facture):
    demande, decision = _demande_puis_decision(dep, "m5_corriger_facture_fournisseur", _corriger_args(facture),
                                               "financeuse")

    assert decision["statut"] == "executee", decision
    assert decision["reponse"]["resultat"]["accepte"] is True
    piece = _registre_ap()[-1]
    assert piece["type_entree"] == "correction_facture_fournisseur"
    assert (piece["corrige_par"], piece["role"], piece["voie"]) == ("financeuse", "finance", "approbation")
    assert _le_po(par_nom)["factures"]["apres_taxes"] == "356.42"
    with stockage.transaction() as cnx:
        (motif,) = cnx.execute(select(APPROBATIONS.c.arguments).where(APPROBATIONS.c.id == demande["demande_id"])).one()
    assert json.loads(motif)["facture_fournisseur_id"] == facture, "les arguments enregistrés sont ceux rejoués"


@pytest.mark.parametrize("decideur, role", [("nathan", "nathan_owner"), ("comptable", "finance")],
                         ids=["proprietaire", "finance_avec_appareil"])
def test_le_proprietaire_ou_la_finance_annule_apres_une_demande(dep, par_nom, facture, decideur, role):
    _demande_puis_decision(dep, "m5_annuler_facture_fournisseur", _annuler_args(facture), decideur, role=role)

    piece = _registre_ap()[-1]
    assert piece["type_entree"] == "annulation_facture_fournisseur"
    assert (piece["annule_par"], piece["role"], piece["voie"]) == (decideur, role, "approbation")
    assert _le_po(par_nom)["rapprochement"]["verdict"] == "SANS_FACTURE"


def test_un_refus_de_la_file_ne_change_rien(dep, facture):
    avant = _registre_ap()

    _demande, decision = _demande_puis_decision(
        dep, "m5_annuler_facture_fournisseur", _annuler_args(facture), "nathan", approuver=False)

    assert decision["statut"] == "refusee" and _registre_ap() == avant


def test_une_decision_ne_se_rejoue_pas_la_demande_deja_traitee_est_refusee_sans_effet(dep, facture):
    demande, decision = _demande_puis_decision(
        dep, "m5_corriger_facture_fournisseur", _corriger_args(facture), "nathan")
    assert decision["statut"] == "executee"
    apres = _registre_ap()

    with stockage.transaction() as cnx, pytest.raises(ValueError, match="déjà traitée"):
        opsys_approbations.decider(
            cnx, demande["demande_id"], True, "nathan", outils_executables({DEPARTEMENT: dep}, stockage.transaction),
            {DEPARTEMENT: dep})

    assert _registre_ap() == apres, "une seule pièce"


def test_le_role_d_une_gestionnaire_admise_par_le_departement_ne_suffit_pas_a_l_outil(dep, facture):
    """Le département autoriserait `manager` à décider un N4 : `decider` l'accepte, mais l'outil n'accepte que la
    finance et le propriétaire (il peut être plus strict que la politique)."""
    permissif = dataclasses.replace(dep, politique_approbation=dataclasses.replace(
        dep.politique_approbation, roles={**dep.politique_approbation.roles, Niveau.N4: frozenset({"manager"})}))
    avant = _registre_ap()

    _demande, decision = _demande_puis_decision(
        permissif, "m5_corriger_facture_fournisseur", _corriger_args(facture), "gestion", role="manager")

    assert decision["statut"] == "echec", "la commande refusée ne compte pas comme exécutée"
    assert decision["reponse"]["ok"] is True
    assert decision["reponse"]["resultat"]["accepte"] is False
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-AP-HUMAIN-REQUIS"
    assert _registre_ap() == avant


def test_la_saisie_d_une_facture_de_po_par_la_finance_passe_toujours_par_le_socle(dep, par_nom):
    """Non-régression T4.15 : la voie de l'approbation de `m5_saisir_facture_fournisseur` lit maintenant le socle."""
    _recevoir(dep)

    _demande, decision = _demande_puis_decision(dep, "m5_saisir_facture_fournisseur", _facture_args(), "financeuse")

    assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"] is True
    assert (_registre_ap()[-1]["saisi_par"], _registre_ap()[-1]["voie"]) == ("financeuse", "approbation")


# ========================================================================= les refus de l'outil, rien n'est écrit
def test_les_refus_de_l_outil_ne_laissent_aucune_trace(par_nom, facture):
    _accepte(_appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture), NATHAN))
    apres = _instantane_base()

    # Le même geste reproposé sur la révision relue (1) : rien ne change. Les arguments exacts d'avant (révision 0)
    # sont PERIMEE (test_revision_facture_fournisseur.py).
    rejeu = _appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture), NATHAN)
    # Une facture inconnue n'a pas de révision lue : un jeton plausible, seulement pour atteindre le refus.
    inconnue = _appeler(par_nom, "m5_annuler_facture_fournisseur", _annuler_args("apf-inconnue", revision_attendue=0),
                        NATHAN)
    sans_motif = _appeler(par_nom, "m5_annuler_facture_fournisseur", _annuler_args(facture, motif="  "), NATHAN)
    incoherent = _appeler(
        par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture, montant_avant_taxes="320.00",
                                                                     total_facture="1.00"), NATHAN)

    assert _code(rejeu) == "REJ-AP-CORRECTION-SANS-CHANGEMENT", "un rejeu n'a aucun effet"
    assert _code(inconnue) == "REJ-AP-FACTURE-INCONNUE"
    assert _code(sans_motif) == "REJ-AP-MOTIF-REQUIS"
    assert _code(incoherent) == "REJ-AP-FACTURE-TOTAL-INCOHERENT"
    assert _instantane_base() == apres


def test_l_annulation_rejouee_est_refusee_sans_effet_et_une_annulee_ne_se_corrige_plus(par_nom, facture):
    _accepte(_appeler(par_nom, "m5_annuler_facture_fournisseur", _annuler_args(facture), NATHAN))
    apres = _instantane_base()

    assert _code(_appeler(par_nom, "m5_annuler_facture_fournisseur", _annuler_args(facture), NATHAN)) == (
        "REJ-AP-FACTURE-DEJA-ANNULEE")
    assert _code(_appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture), NATHAN)) == (
        "REJ-AP-FACTURE-ANNULEE")
    assert _instantane_base() == apres


@pytest.mark.parametrize("outil, arguments", [
    ("m5_corriger_facture_fournisseur", lambda ident: _corriger_args(ident, horodatage="2020-01-01T00:00:00+00:00")),
    ("m5_annuler_facture_fournisseur", lambda ident: _annuler_args(ident, horodatage="2020-01-01T00:00:00+00:00")),
    ("m5_saisir_facture_sans_po", lambda _ident: _sans_po_args(horodatage="2020-01-01T00:00:00+00:00")),
], ids=["corriger", "annuler", "sans_po"])
def test_pendant_un_appel_d_appareil_l_heure_de_reception_du_serveur_fait_foi(
        par_nom, facture, declare, outil, arguments):
    declare(CATEGORIES)
    recu_le = dt.datetime(2026, 10, 12, 12, 0, 0, tzinfo=dt.UTC)
    reception = contexte.HorodatageAppareil(
        appareil="appareil-fictif", horodatage_appareil=dt.datetime(2020, 1, 1, tzinfo=dt.UTC), recu_le=recu_le)

    with contexte.receptionne_de(reception):
        _accepte(_appeler(par_nom, outil, arguments(facture), NATHAN))

    assert _registre_ap()[-1]["horodatage"] == recu_le.isoformat(), "jamais l'horloge de l'appareil ni l'argument"


def test_par_la_file_l_horodatage_enregistre_avec_la_demande_sert(dep, facture):
    """Aucun appel d'appareil à l'exécution d'une demande approuvée : l'argument `horodatage` de la demande fait foi."""
    _demande_puis_decision(dep, "m5_annuler_facture_fournisseur", _annuler_args(facture, horodatage=ANNULATION),
                           "nathan")

    assert _registre_ap()[-1]["horodatage"] == ANNULATION


# =============================================== le rapprochement, les totaux et le cash libre lisent l'état courant
def test_le_rapprochement_et_les_totaux_lisent_l_etat_courant_a_chaque_geste(par_nom, facture):
    assert _le_po(par_nom)["a_payer_apres_taxes"] == "344.93"

    _accepte(_appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(facture), NATHAN))
    corrigee = _le_po(par_nom)
    assert corrigee["a_payer_apres_taxes"] == "356.42" and corrigee["rapprochement"]["verdict"] == "ECART"
    assert corrigee["factures_saisies"][0]["statut"] == "CORRIGEE"
    assert _liste(par_nom)["totaux"]["a_payer_apres_taxes"] == "356.42"

    _accepte(_appeler(par_nom, "m5_annuler_facture_fournisseur", _annuler_args(facture), NATHAN))
    annulee = _le_po(par_nom)
    assert annulee["a_payer_apres_taxes"] == "344.93" and annulee["rapprochement"]["verdict"] == "SANS_FACTURE"
    assert annulee["factures_annulees"] == 1
    assert [f["statut"] for f in annulee["factures_saisies"]] == ["ANNULEE"]
    assert _liste(par_nom)["totaux"]["facture_apres_taxes"] == "0.00"


def _preparer_le_cash_libre(taux, declare):
    """Solde 20000.00, une facture cliente envoyée de 5000.00 (TPS 250.00, TVQ 498.75), rien d'autre à retrancher que
    ce que la PO et les factures fournisseur y mettent."""
    declare({
        "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12,
                   "taxes_remises_jusqu_au": "2026-06-30"},
        "obligations_declarees": {n: {"montant": "0.00", "source": "aucune (fictif)", "au": "2026-09-25"}
                                  for n in ("paies", "das", "dettes", "reserves")},
        **CATEGORIES,
    })
    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        registre.enregistrer_mouvement({
            "montant": D("20000.00"), "type_mouvement": "ENCAISSEMENT", "horodatage": "2026-08-01T12:00:00-04:00",
            "classe_retention": "STANDARD", "source": "test-fictif"}, reg)
        factures = m5_outils._registre_factures(None)
        _, verdict = facturation.creer_facture_brouillon(
            "F-CL-1", "CH-9", "D-9", "C-9",
            [{"description": "travaux (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": "5000.00",
              "reference_ligne_devis": "L-1"}], "2026-08-10T09:00:00-04:00", taux, factures)
        assert verdict is None, verdict
        assert facturation.envoyer_facture("F-CL-1", "2026-08-10T09:30:00-04:00", factures)[1] is None


def _cash(par_nom):
    reponse = _appeler(par_nom, "m5_etat_tresorerie", {}, NATHAN)
    assert reponse["ok"] is True, reponse
    etat = reponse["resultat"]["cash_libre"]
    composantes = {c["id"]: c for c in etat["composantes"]}
    taxes, a_payer = composantes["taxes_a_remettre"]["montant"], composantes["comptes_a_payer"]["montant"]
    return etat["cash_libre"], taxes, a_payer, etat


def test_le_cash_libre_lit_l_etat_courant_correction_annulation_et_facture_sans_po(dep, par_nom, taux, declare):
    _preparer_le_cash_libre(taux, declare)
    _recevoir(dep)

    # PO-1 reçu (300.00), rien de facturé : 344.93 à payer, aucun crédit de taxes
    assert _cash(par_nom)[:3] == ("18906.32", "748.75", "344.93")

    resultat = _accepte(_appeler(par_nom, "m5_saisir_facture_fournisseur", _facture_args(), NATHAN))
    ident = resultat["facture"]["facture_fournisseur_id"]
    assert _cash(par_nom)[:3] == ("18951.25", "703.82", "344.93"), "crédits 15.00 + 29.93 : les taxes baissent de 44.93"

    _accepte(_appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(ident), NATHAN))
    assert _cash(par_nom)[:3] == ("18941.25", "702.33", "356.42"), "crédits 15.50 + 30.92, facturé 356.42"

    _accepte(_appeler(par_nom, "m5_annuler_facture_fournisseur", _annuler_args(ident), NATHAN))
    assert _cash(par_nom)[:3] == ("18906.32", "748.75", "344.93"), "l'annulée ne donne aucun crédit ni aucune dette"

    _accepte(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN))
    cash, taxes, a_payer, etat = _cash(par_nom)
    assert (cash, taxes, a_payer) == ("18806.32", "733.77", "459.91"), "114.98 sans PO ; crédits 5.00 + 9.98"
    comptes = next(c for c in etat["composantes"] if c["id"] == "comptes_a_payer")
    assert comptes["detail"]["factures_sans_po"] == {"nombre": 1, "apres_taxes": "114.98"}


# ==================================================================================== la facture sans PO
def test_l_admin_saisit_une_facture_sans_po_de_la_liste_configuree(par_nom, declare):
    declare(CATEGORIES)

    resultat = _accepte(_appeler(
        par_nom, "m5_saisir_facture_sans_po", _sans_po_args(total_facture="114.98"), COMPTABLE))

    facture = resultat["facture"]
    assert facture["categorie_depense"] == "carburant" and facture["po_id"] is None and facture["statut"] == "SAISIE"
    assert (facture["montant_avant_taxes"], facture["total_taxes"], facture["montant_apres_taxes"]) == (
        "100.00", "14.98", "114.98")
    assert (facture["saisi_par"], facture["voie"]) == ("comptable", "appareil")
    assert resultat["mention"] == MENTION and "rapprochement" not in resultat
    assert resultat["sans_po"] == {"nombre": 1, "avant_taxes": "100.00", "taxes": "14.98", "apres_taxes": "114.98",
                                   "par_categorie": {"carburant": {"nombre": 1, "apres_taxes": "114.98"}}}
    assert _registre_ap()[-1]["po_id"] is None


def test_sans_categorie_configuree_la_saisie_dit_categories_a_configurer(par_nom):
    """Le VRAI manifeste de M5 ne déclare aucune catégorie : rien n'est supposé."""
    avant = _instantane_base()

    reponse = _appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN)

    assert _code(reponse) == "REJ-AP-CATEGORIES-A-CONFIGURER"
    assert "catégories à configurer" in reponse["resultat"]["verdict"]["detail"]
    assert _instantane_base() == avant


@pytest.mark.parametrize("configuration, code", [
    ({"categories_depense_sans_po": []}, "REJ-AP-CATEGORIES-A-CONFIGURER"),
    ({"categories_depense_sans_po": "carburant"}, "REJ-AP-CATEGORIES-INVALIDES"),
    ({"categories_depense_sans_po": ["Carburant"]}, "REJ-AP-CATEGORIES-INVALIDES"),
    ({"categories_depense_sans_po": ["outils", "outils"]}, "REJ-AP-CATEGORIES-INVALIDES"),
    ({"autre_chose": 1}, "REJ-AP-CATEGORIES-A-CONFIGURER"),
])
def test_une_configuration_vide_ou_illisible_est_refusee_jamais_lue_a_moitie(par_nom, declare, configuration, code):
    declare(configuration)
    avant = _instantane_base()

    assert _code(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN)) == code
    assert _instantane_base() == avant


def test_un_manifeste_illisible_donne_categories_a_configurer(par_nom, tmp_path, monkeypatch):
    manifeste = tmp_path / "casse.yaml"
    manifeste.write_text("configuration: [pas: un: objet", encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)

    assert _code(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN)) == (
        "REJ-AP-CATEGORIES-A-CONFIGURER")


def test_la_configuration_est_relue_a_chaque_appel_sans_redemarrage(par_nom, declare):
    declare({"categories_depense_sans_po": ["outils"]})
    assert _code(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN)) == "REJ-AP-CATEGORIE-INCONNUE"

    declare({"categories_depense_sans_po": ["outils", "carburant"]})
    assert _accepte(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN))["facture"][
        "categorie_depense"] == "carburant"


def test_une_categorie_hors_liste_un_doublon_et_un_total_divergent_sont_refuses_sans_rien_ecrire(par_nom, declare):
    declare(CATEGORIES)
    _accepte(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN))
    avant = _instantane_base()

    hors = _appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(categorie="divertissement", numero_facture="X"),
                    NATHAN)
    doublon = _appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(date_facture="2026-10-02"), NATHAN)
    diverge = _appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(numero_facture="Y", total_facture="1.00"),
                       NATHAN)

    assert _code(hors) == "REJ-AP-CATEGORIE-INCONNUE" and "carburant, outils" in hors["resultat"]["verdict"]["detail"]
    assert _code(doublon) == "REJ-AP-FACTURE-DOUBLON" and _code(diverge) == "REJ-AP-FACTURE-TOTAL-INCOHERENT"
    assert _instantane_base() == avant


def test_la_finance_approuve_une_facture_sans_po_proposee_par_l_agent(dep, par_nom, declare):
    declare(CATEGORIES)

    _demande, decision = _demande_puis_decision(dep, "m5_saisir_facture_sans_po", _sans_po_args(), "financeuse")

    assert decision["statut"] == "executee" and decision["reponse"]["resultat"]["accepte"] is True
    assert (_registre_ap()[-1]["saisi_par"], _registre_ap()[-1]["voie"]) == ("financeuse", "approbation")


def test_les_factures_sans_po_se_lisent_avec_leur_identifiant_puis_se_corrigent_et_s_annulent(par_nom, declare):
    declare(CATEGORIES)
    _accepte(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN))
    _accepte(_appeler(par_nom, "m5_saisir_facture_sans_po",
                      _sans_po_args(numero_facture="O-1", categorie="outils", montant_avant_taxes="84.50"), NATHAN))

    page = _liste(par_nom, {"sans_po": True})

    assert page["type"] == "COMPTES_A_PAYER_SANS_PO" and page["role"] == "admin" and page["total"] == 2
    premiere = page["factures"][0]
    assert premiere["categorie_depense"] == "carburant" and premiere["apres_taxes"] == "114.98"
    corrigee = _accepte(_appeler(par_nom, "m5_corriger_facture_fournisseur", _corriger_args(
        premiere["facture_fournisseur_id"], montant_avant_taxes="200.00"), NATHAN))
    assert corrigee["sans_po"]["apres_taxes"] == "327.11", "229.95 + 97.16"
    assert corrigee["facture"]["po_id"] is None and corrigee["facture"]["categorie_depense"] == "carburant"
    annulee = _accepte(_appeler(par_nom, "m5_annuler_facture_fournisseur", _annuler_args(
        premiere["facture_fournisseur_id"]), NATHAN))
    assert annulee["sans_po"]["nombre"] == 1 and annulee["sans_po"]["apres_taxes"] == "97.16"
    apres = _liste(par_nom, {"sans_po": True})
    assert [f["statut"] for f in apres["factures"]] == ["ANNULEE", "SAISIE"]
    assert apres["totaux"]["apres_taxes"] == "97.16"


# ==================================================================================== la lecture, sans_po
def test_la_lecture_sans_po_suit_la_meme_regle_d_acces_que_les_autres_lectures(dep, par_nom, declare, monkeypatch):
    declare(CATEGORIES)
    _accepte(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(), NATHAN))

    masquee = _liste(par_nom, {"sans_po": True, "autorise_couts": False})
    assert masquee == {"role": "admin", "nombre_factures_sans_po": 1, "montants_masques": True, "mention": MENTION}
    assert "114.98" not in json.dumps(masquee)
    elargie = _appeler(par_nom, "m5_lister_comptes_a_payer", {"sans_po": True, "role": "employee"}, NATHAN)
    assert _code(elargie) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    sans_appareil = _appeler(par_nom, "m5_lister_comptes_a_payer", {"sans_po": True}, None)
    assert _code(sans_appareil) == "REJ-AUTORISE-COUTS-REQUIS"
    agent = _accepte(_appeler(par_nom, "m5_lister_comptes_a_payer", {"sans_po": True, "autorise_couts": True}, None))
    assert agent["total"] == 1

    def _interdit(*_args, **_kwargs):
        raise AssertionError("le registre a été ouvert avant le refus")

    for appelante in (MARC, VENDEUR):
        with monkeypatch.context() as remplacement:
            remplacement.setattr(m5_outils, "_registre_comptes_a_payer", _interdit)
            refuse = _appeler(par_nom, "m5_lister_comptes_a_payer", {"sans_po": True}, appelante)
        assert _code(refuse) == "REJ-IDENTITE-APPAREIL-INVALIDE" and "114.98" not in json.dumps(refuse)


def test_sans_po_et_po_id_ne_vont_pas_ensemble_et_sans_po_doit_etre_un_booleen(par_nom):
    with stockage.transaction(), contexte.appele_par_appareil(NATHAN):
        ensemble = m5_outils.lister_comptes_a_payer(po_id="PO-1", sans_po=True)
        texte = m5_outils.lister_comptes_a_payer(sans_po="oui")
        faux = m5_outils.lister_comptes_a_payer(sans_po=False)

    assert ensemble["accepte"] is False and ensemble["verdict"]["code"] == "REJ-AP-LISTE-FILTRE-INVALIDE"
    assert texte["accepte"] is False and texte["verdict"]["code"] == "REJ-AP-LISTE-FILTRE-INVALIDE"
    assert faux["accepte"] is True and faux["resultat"]["type"] == "COMPTES_A_PAYER", "faux : la liste des PO"


def test_la_lecture_sans_po_pagine_et_refuse_un_depart_invalide(par_nom, declare):
    declare(CATEGORIES)
    for numero in range(1, 4):
        _accepte(_appeler(par_nom, "m5_saisir_facture_sans_po", _sans_po_args(numero_facture=f"C-{numero}"), NATHAN))

    page = _liste(par_nom, {"sans_po": True, "depart": 2})
    assert page["depart"] == 2 and len(page["factures"]) == 1 and page["prochain_depart"] is None
    refus = _appeler(par_nom, "m5_lister_comptes_a_payer", {"sans_po": True, "depart": 9}, NATHAN)
    assert _code(refus) == "REJ-AP-LISTE-DEPART-INVALIDE"


# ===================================================================== la file et le socle : la même trace
def test_la_demande_d_un_n4_depuis_un_appareil_attend_le_proprietaire_l_appareil_n_execute_pas(dep, facture):
    """Le socle (`_valider_au_depart`) ne valide au départ que N3 au plus : un N4 lancé depuis l'appareil attend la
    décision du propriétaire, comme celui d'un agent. La correction ne se fait qu'une fois approuvée."""
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    meta = idempotence.Meta(cle="cle-1", appareil="tel-admin-fictif", horodatage_appareil="2026-10-09T10:00:00-04:00")
    avant = _registre_ap()

    with contexte.appele_par_appareil(NATHAN):
        reponse = capacites.appeler("m5_corriger_facture_fournisseur", _corriger_args(facture), meta)

    assert reponse["statut"] == "en_attente_approbation" and _registre_ap() == avant
    with stockage.transaction() as cnx:
        opsys_approbations.decider(
            cnx, reponse["demande_id"], True, "nathan", outils_executables({DEPARTEMENT: dep}, stockage.transaction),
            {DEPARTEMENT: dep}, role="nathan_owner")
    piece = _registre_ap()[-1]
    assert (piece["corrige_par"], piece["role"], piece["voie"]) == ("nathan", "nathan_owner", "approbation")
