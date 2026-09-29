"""PLAN T4.15 : les comptes à payer sur le VRAI socle : le consommateur de `m6.reception_enregistree` sur le vrai
bus, la saisie d'une facture fournisseur par un HUMAIN (jeton d'appareil confirmé en base, ou demande approuvée dans
la file, jamais un agent seul), et la lecture par pages sous la limite de sortie de `Capacites`.

Base SQLite temporaire migrée, vrai manifeste de M5 (mode `ombre`), vraies approbations, vrai répartiteur. Le cas de
référence est celui de `test_comptes_a_payer.py` (PO de 320.00 $, reçu en deux livraisons de 300.00 $ et 20.00 $).
Identifiants, personnes et montants fictifs (AGENTS.md).
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
from sqlalchemy import select, update

from opsys import approbations as opsys_approbations
from opsys import contexte, evenements, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements, lire_manifeste
from opsys.outils import Niveau, executer_atomique
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_RECUS, META

FICTIF = True
_RACINE_M5 = Path(__file__).resolve().parents[1]
DEPARTEMENT = "m05-financecore"
TYPE = "m6.reception_enregistree"
LIVRAISON_1 = "2026-09-29T09:15:00-04:00"
LIVRAISON_2 = "2026-10-06T14:30:00-04:00"
SAISIE = "2026-10-08T10:00:00-04:00"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
FANTOME = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-comptes-a-payer.db'}"
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
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
        identite.creer_personne(cnx, "financeuse", "Une Comptable (fictif)", "mot-de-passe-finance-1234", ["finance"])
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner"])
        identite.creer_personne(cnx, "ancien.fictif", "Ancien Fictif", "mot-de-passe-ancien-1234", ["admin"])
        identite.activer(cnx, "ancien.fictif", False)


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in m5_outils.outils()}


# ------------------------------------------------------------------------------------------ petits outils
def _ligne(materiau, demandee, recue, prix, reception=None):
    return {
        "materiau_id": materiau, "quantite_demandee": demandee, "quantite_recue": recue, "prix_unitaire_prevu": prix,
        "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE", "prix_unitaire_reception": reception,
        "verdict_prix_reception": "PRIX_CATALOGUE" if reception else "INDETERMINE",
        "ecart_prix_critique": False if reception else None,
    }


def _charge(evenement_id="evt-1", po_id="PO-1", gouttiere="60", vis="0", horodatage=LIVRAISON_1, fournisseur="gentek"):
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": fournisseur, "chantier_id": "CH-1",
        "horodatage_reception": horodatage, "verdict_reception": "RECEPTION_INFERIEURE",
        "statut_po": "partially_received", "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [_ligne("gouttiere-5po", "60", gouttiere, "5.00", "5.00"), _ligne("vis-inox", "40", vis, "0.50")],
    }


def _publier(charge):
    with stockage.transaction():
        evenements.publier(TYPE, "m06-material-control", charge, evenement_id=charge["evenement_id"])


def _drainer(dep, heure="2026-09-29T12:00:00+00:00"):
    return evenements.repartir({DEPARTEMENT: dep}, maintenant=heure)


def _recevoir(dep, **kwargs):
    _publier(_charge(**kwargs))
    resume = _drainer(dep)
    assert resume["traites"] >= 1 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


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


def _saisir(par_nom, identite_appelante=ADMIN, **surcharges):
    return _appeler(par_nom, "m5_saisir_facture_fournisseur", _facture_args(**surcharges), identite_appelante)


def _saisie_acceptee(par_nom, **surcharges):
    reponse = _saisir(par_nom, **surcharges)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _liste(par_nom, arguments=None, identite_appelante=ADMIN):
    reponse = _appeler(par_nom, "m5_lister_comptes_a_payer", arguments or {}, identite_appelante)
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


def _ecrire_demande(cnx, arguments, decide_par, decide_role, *, departement=DEPARTEMENT,
                    outil="m5_saisir_facture_fournisseur", statut="en_cours"):
    ident = opsys_approbations.creer_demande(cnx, departement, outil, arguments, niveau=Niveau.N3)
    cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident)
                .values(statut=statut, decide_par=decide_par, decide_role=decide_role))
    return ident


# ===================================================================== le consommateur, sur le vrai bus
def test_m5_livre_la_reception_de_m6_au_registre_des_comptes_a_payer(dep, par_nom):
    _recevoir(dep)

    (maillon,) = _registre_ap()
    assert maillon["type_entree"] == "reception_recue" and maillon["evenement_id"] == "evt-1"
    assert (maillon["po_id"], maillon["fournisseur_id"], maillon["chantier_id"]) == ("PO-1", "gentek", "CH-1")
    ligne = _liste(par_nom)["comptes"][0]
    assert ligne["attendu"] == {"avant_taxes": "300.00", "taxes": "44.93", "apres_taxes": "344.93"}
    assert ligne["a_payer_apres_taxes"] == "344.93"


def test_une_redelivrance_du_meme_evenement_ne_double_rien(dep, par_nom):
    charge = _charge()
    _publier(charge)
    _drainer(dep)
    _publier(charge)  # le bus : publier deux fois le même id est un no-op
    resume = _drainer(dep, heure="2026-09-29T13:00:00+00:00")

    assert resume["livres"] == 0 and len(_registre_ap()) == 1
    with stockage.transaction():
        rejoue = m5_outils._recevoir_reception_enregistree(charge)  # un appel direct, comme une concurrence
    assert rejoue["statut"] == "deja_recue" and len(_registre_ap()) == 1
    assert _liste(par_nom)["comptes"][0]["attendu"]["avant_taxes"] == "300.00"


def test_deux_livraisons_du_meme_po_se_cumulent_par_le_bus(dep, par_nom):
    _recevoir(dep, evenement_id="evt-1", gouttiere="60", vis="0", horodatage=LIVRAISON_1)
    _recevoir(dep, evenement_id="evt-2", gouttiere="0", vis="40", horodatage=LIVRAISON_2)

    ligne = _liste(par_nom, {"po_id": "PO-1"})["comptes"][0]

    assert ligne["receptions"] == 2 and ligne["attendu"]["avant_taxes"] == "320.00"
    assert [v["evenement_id"] for v in ligne["livraisons"]] == ["evt-1", "evt-2"]


def test_la_reception_n_ecrit_jamais_au_registre_des_mouvements(dep, par_nom):
    _recevoir(dep)

    with stockage.transaction():
        assert list(stockage.maillons(DEPARTEMENT, "principal")) == []
        assert list(stockage.maillons(DEPARTEMENT, "factures")) == []
    assert _liste(par_nom)["totaux"]["nombre_po"] == 1


def test_un_po_connu_sous_un_autre_fournisseur_lit_puis_met_en_quarantaine_sans_rien_ecrire(dep, par_nom):
    _recevoir(dep, evenement_id="evt-1", fournisseur="gentek")
    _publier(_charge(evenement_id="evt-2", fournisseur="royal"))

    resume = _drainer(dep, heure="2026-09-29T13:00:00+00:00")

    assert resume["echecs"] == 1 and len(_registre_ap()) == 1, "la deuxième réception n'est pas rangée"
    with stockage.transaction() as cnx:
        derniere = cnx.execute(select(EVENEMENTS_RECUS.c.derniere_erreur).where(
            EVENEMENTS_RECUS.c.evenement_id == "evt-2")).scalar_one()
    assert "REJ-AP-PO-INCOHERENT" in derniere, "l'erreur est gardée pour le réessai, puis pour la quarantaine"


def test_une_charge_invalide_leve_pour_que_le_repartiteur_reessaie(dep):
    charge = _charge()
    charge["lignes"][0]["quantite_recue"] = "-1"

    with stockage.transaction(), pytest.raises(ValueError, match="REJ-AP-RECEPTION-INVALIDE"):
        m5_outils._recevoir_reception_enregistree(charge)

    assert _registre_ap() == []


def test_m5_declare_consommer_le_type_et_le_fournit(dep):
    departement = charger_departements()[DEPARTEMENT]

    assert TYPE in departement.evenements_consomme
    assert TYPE in departement.charger_consommateurs()
    assert departement.evenements_publie == ("m5.rentabilite_chantier",), "M5 ne publie rien de plus"
    assert evenements.verifier_coherence({DEPARTEMENT: departement}) == []


# ===================================================================== la saisie : par un humain, jamais un agent seul
def test_l_admin_authentifie_saisit_une_facture_recalculee_et_recoit_le_rapprochement_propose(dep, par_nom):
    _recevoir(dep)

    resultat = _saisie_acceptee(par_nom, total_facture="344.93")

    facture = resultat["facture"]
    assert facture["statut"] == "SAISIE" and facture["saisi_par"] == "admin.fictif" and facture["voie"] == "appareil"
    assert (facture["montant_avant_taxes"], facture["total_taxes"], facture["montant_apres_taxes"]) == (
        "300.00", "44.93", "344.93")
    assert [t["montant"] for t in facture["taxes"]] == ["15.00", "29.93"]
    assert resultat["avertissements"] == []
    rapprochement = resultat["rapprochement"]
    assert rapprochement["statut"] == "PROPOSE" and rapprochement["verdict"] == "CONCORDANT"
    assert "ligne_id" not in facture
    (_reception, saisie) = _registre_ap()
    assert saisie["type_entree"] == "facture_fournisseur_saisie"


def test_le_doublon_est_refuse_et_rien_n_est_ecrit(dep, par_nom):
    _recevoir(dep)
    _saisie_acceptee(par_nom)
    avant = _instantane_base()

    reponse = _saisir(par_nom, date_facture="2026-10-02")

    assert _code(reponse) == "REJ-AP-FACTURE-DOUBLON"
    assert _instantane_base() == avant


def test_un_total_imprime_divergent_est_refuse_et_rien_n_est_ecrit(dep, par_nom):
    _recevoir(dep)
    avant = _instantane_base()

    reponse = _saisir(par_nom, total_facture="344.92")

    assert _code(reponse) == "REJ-AP-FACTURE-TOTAL-INCOHERENT"
    assert "344.92" in reponse["resultat"]["verdict"]["detail"] and "344.93" in reponse["resultat"]["verdict"]["detail"]
    assert _instantane_base() == avant


def test_un_po_sans_reception_est_refuse(dep, par_nom):
    avant = _instantane_base()

    assert _code(_saisir(par_nom, po_id="PO-JAMAIS-RECU")) == "REJ-AP-FACTURE-PO-SANS-RECEPTION"
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
def test_un_employe_ou_un_vendeur_ne_saisit_rien_et_rien_n_est_lu_ni_ecrit(dep, par_nom, monkeypatch, appelante):
    _recevoir(dep)
    avant = _instantane_base()

    def _interdit(*_args, **_kwargs):
        raise AssertionError("le registre des comptes à payer a été ouvert avant le refus")

    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5_outils, "_registre_comptes_a_payer", _interdit)
        reponse = _saisir(par_nom, identite_appelante=appelante)

    assert _code(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [FANTOME, contexte.IdentiteAppelante(personne="ancien.fictif", role="admin"),
                                       contexte.IdentiteAppelante(personne="marc.fictif", role="admin")],
                         ids=["inconnue", "desactivee", "role_retire"])
def test_une_identite_d_appareil_inconnue_desactivee_ou_sans_le_role_est_refusee(dep, par_nom, appelante):
    _recevoir(dep)
    avant = _instantane_base()

    assert _code(_saisir(par_nom, identite_appelante=appelante)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _instantane_base() == avant


def test_un_agent_sans_identite_ni_approbation_ne_saisit_rien(dep, par_nom):
    """Un département en mode `supervise` ou `autonome` exécute un N3 sans file : sans humain identifié, la saisie
    est refusée par l'outil lui-même."""
    _recevoir(dep)
    avant = _instantane_base()

    reponse = _saisir(par_nom, identite_appelante=None)

    assert _code(reponse) == "REJ-AP-HUMAIN-REQUIS"
    assert "ne la présente pas comme saisie" in reponse["resultat"]["verdict"]["detail"]
    assert _instantane_base() == avant


def test_une_demande_seulement_en_attente_ne_donne_pas_le_droit_de_saisir(dep, par_nom):
    """Un agent ne peut créer qu'une demande `en_attente` : elle n'autorise rien tant qu'un humain ne l'a pas
    décidée."""
    _recevoir(dep)
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    demande = capacites.appeler("m5_saisir_facture_fournisseur", _facture_args())
    assert demande["statut"] == "en_attente_approbation"
    avant = _instantane_base()

    reponse = _saisir(par_nom, identite_appelante=None)  # même arguments, sans que personne n'ait décidé

    assert _code(reponse) == "REJ-AP-HUMAIN-REQUIS" and _instantane_base() == avant


def test_l_agent_propose_la_finance_approuve_et_la_facture_porte_le_nom_de_l_approbatrice(dep, par_nom):
    _recevoir(dep)
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    dispo = outils_executables({DEPARTEMENT: dep}, stockage.transaction)

    demande = capacites.appeler("m5_saisir_facture_fournisseur", _facture_args())
    assert demande["statut"] == "en_attente_approbation" and len(_registre_ap()) == 1, "rien n'est saisi encore"
    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(cnx, demande["demande_id"], True, "financeuse", dispo, {DEPARTEMENT: dep})

    assert decision["statut"] == "executee", decision
    (_reception, saisie) = _registre_ap()
    assert saisie["voie"] == "approbation" and saisie["saisi_par"] == "financeuse"
    assert saisie["montant_apres_taxes"] == Decimal("344.93")


def test_un_refus_de_la_file_ne_saisit_rien(dep, par_nom):
    _recevoir(dep)
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    dispo = outils_executables({DEPARTEMENT: dep}, stockage.transaction)
    demande = capacites.appeler("m5_saisir_facture_fournisseur", _facture_args())

    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(cnx, demande["demande_id"], False, "nathan", dispo, {DEPARTEMENT: dep})

    assert decision["statut"] == "refusee" and len(_registre_ap()) == 1


def test_un_agent_en_mode_supervise_est_refuse_par_l_outil_lui_meme(dep, par_nom):
    """Mode `supervise` : le N3 s'exécute SANS file. C'est l'outil, pas la file, qui exige l'humain."""
    _recevoir(dep)
    supervise = dataclasses.replace(dep, mode="supervise")
    capacites = Capacites({DEPARTEMENT: supervise}, stockage.transaction)

    reponse = capacites.appeler("m5_saisir_facture_fournisseur", _facture_args())

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-AP-HUMAIN-REQUIS"
    assert len(_registre_ap()) == 1


# -- `_decision_approuvee_en_cours` : ce qui compte comme une décision humaine -----------------------------------------
def _decision(cnx, arguments):
    return m5_outils._decision_approuvee_en_cours(cnx, "m5_saisir_facture_fournisseur", arguments)


def test_une_demande_en_cours_approuvee_par_la_finance_est_une_decision_humaine(personnes):
    arguments = _facture_args()
    with stockage.transaction() as cnx:
        _ecrire_demande(cnx, arguments, "financeuse", "finance")
        assert _decision(cnx, arguments) == ("financeuse", "finance")


@pytest.mark.parametrize("cas", [
    dict(nom="autres_arguments", arguments=_facture_args(montant_avant_taxes="999.00")),
    dict(nom="un_argument_de_moins", arguments={k: v for k, v in _facture_args().items() if k != "total_facture"}),
    dict(nom="pas_en_cours", statut="en_attente"),
    dict(nom="deja_executee", statut="executee"),
    dict(nom="autre_outil", outil="m5_envoyer_facture"),
    dict(nom="autre_departement", departement="m06-material-control"),
    dict(nom="role_non_humain", decide_role="employee", decide_par="marc.fictif"),
    dict(nom="personne_inactive", decide_role="admin", decide_par="ancien.fictif"),
    dict(nom="personne_sans_ce_role", decide_role="finance", decide_par="marc.fictif"),
    dict(nom="sans_decideur", decide_role="finance", decide_par=None),
    dict(nom="decideur_inconnu", decide_role="finance", decide_par="inconnu.fictif"),
], ids=lambda cas: cas["nom"])
def test_ce_qui_ne_compte_pas_comme_une_decision_humaine(personnes, cas):
    arguments = _facture_args()
    ecrite = {"decide_par": "financeuse", "decide_role": "finance", "statut": "en_cours"}
    ecrite.update({k: v for k, v in cas.items() if k in ("decide_par", "decide_role", "statut")})
    with stockage.transaction() as cnx:
        _ecrire_demande(cnx, arguments, ecrite["decide_par"], ecrite["decide_role"], statut=ecrite["statut"],
                        **{k: v for k, v in cas.items() if k in ("outil", "departement")})
        assert _decision(cnx, cas.get("arguments", arguments)) is None


def test_sans_connexion_aucune_decision_n_est_reconnue():
    assert m5_outils._decision_approuvee_en_cours(None, "m5_saisir_facture_fournisseur", _facture_args()) is None


# -- heure : le serveur fait foi pendant un appel d'appareil idempotent ------------------------------------------------
def test_pendant_un_appel_d_appareil_l_heure_de_reception_du_serveur_fait_foi(dep, par_nom):
    _recevoir(dep)
    recu_le = dt.datetime(2026, 10, 9, 12, 0, 0, tzinfo=dt.UTC)
    reception = contexte.HorodatageAppareil(
        appareil="appareil-fictif", horodatage_appareil=dt.datetime(2020, 1, 1, tzinfo=dt.UTC), recu_le=recu_le)

    with contexte.receptionne_de(reception):
        resultat = _saisie_acceptee(par_nom, horodatage="2020-01-01T00:00:00+00:00")

    assert resultat["facture"]["horodatage"] == recu_le.isoformat(), "jamais l'horloge de l'appareil ni l'argument"


# -- le contrat de l'outil ---------------------------------------------------------------------------------------
def test_aucun_montant_calcule_ne_se_passe_en_argument(dep, par_nom):
    _recevoir(dep)
    for argument in ({"taxes": []}, {"total_taxes": "44.93"}, {"montant_apres_taxes": "344.93"}, {"statut": "PAYEE"},
                     {"saisi_par": "nathan"}, {"voie": "appareil"}, {"role": "admin"}):
        reponse = _saisir(par_nom, **argument)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", argument


def test_tous_les_parametres_sont_requis_pour_que_l_approbation_rejoue_les_arguments_exacts(par_nom):
    schema = par_nom["m5_saisir_facture_fournisseur"].parametres

    assert set(schema["required"]) == set(schema["properties"]) and schema["additionalProperties"] is False
    assert schema["properties"]["total_facture"]["type"] == ["string", "null"]


def test_l_outil_est_t1_n3_pour_l_admin_seulement(par_nom):
    outil = par_nom["m5_saisir_facture_fournisseur"]

    assert outil.autonomie.value == "T1" and outil.niveau_effectif is Niveau.N3
    assert outil.roles_appareil == frozenset({"admin"}) and outil.frontiere_humaine is False


# ===================================================================== la lecture : paginée, admin seulement
def test_l_admin_lit_sans_rien_fournir_et_sans_rien_ecrire(dep, par_nom):
    _recevoir(dep)
    _saisie_acceptee(par_nom)
    avant = _instantane_base()

    vue = _liste(par_nom)

    assert vue["role"] == "admin" and vue["total"] == 1 and vue["totaux"]["nombre_po"] == 1
    assert vue["comptes"][0]["rapprochement"]["verdict"] == "CONCORDANT"
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
@pytest.mark.parametrize("arguments", [{}, {"autorise_couts": True}, {"autorise_couts": False}],
                         ids=["rien", "veut_les_couts", "vue_sans_montant"])
def test_employe_et_vendeur_n_obtiennent_rien_et_rien_n_est_lu(dep, par_nom, monkeypatch, appelante, arguments):
    _recevoir(dep)

    def _interdit(*_args, **_kwargs):
        raise AssertionError("le registre a été ouvert avant le refus")

    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5_outils, "_registre_comptes_a_payer", _interdit)
        reponse = _appeler(par_nom, "m5_lister_comptes_a_payer", arguments, appelante)

    assert _code(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert "344.93" not in json.dumps(reponse)


def test_l_admin_ne_peut_que_restreindre_la_vue(dep, par_nom):
    _recevoir(dep)

    elargie = _appeler(par_nom, "m5_lister_comptes_a_payer", {"role": "employee"}, ADMIN)
    assert _code(elargie) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"

    masquee = _liste(par_nom, {"autorise_couts": False})
    assert masquee == {"role": "admin", "nombre_po": 1, "montants_masques": True}
    assert "344.93" not in json.dumps(masquee)


def test_sans_appareil_autorise_couts_reste_obligatoire(dep, par_nom):
    _recevoir(dep)

    sans = _appeler(par_nom, "m5_lister_comptes_a_payer", {})
    assert _code(sans) == "REJ-AUTORISE-COUTS-REQUIS"

    avec = _liste(par_nom, {"autorise_couts": True, "role": "gestionnaire"}, identite_appelante=None)
    assert avec["role"] == "gestionnaire" and avec["total"] == 1


def test_aucun_montant_ni_quantite_ne_se_passe_en_argument_de_lecture(par_nom):
    for argument in ({"montant": "1.00"}, {"total_a_payer": "0.00"}, {"comptes": []}, {"taux": "0.05"}):
        assert _appeler(par_nom, "m5_lister_comptes_a_payer", argument, ADMIN)["erreur"] == "arguments_invalides"


@pytest.mark.parametrize("arguments, code", [
    ({"depart": -1}, "REJ-AP-LISTE-DEPART-INVALIDE"),
    ({"depart": 5}, "REJ-AP-LISTE-DEPART-INVALIDE"),
    ({"po_id": "PO-FANTOME"}, "REJ-AP-PO-INCONNU"),
])
def test_les_refus_de_lecture_sont_nommes(dep, par_nom, arguments, code):
    _recevoir(dep)

    assert _code(_appeler(par_nom, "m5_lister_comptes_a_payer", arguments, ADMIN)) == code


def test_depart_de_mauvais_type_est_refuse_par_le_schema(par_nom):
    assert _appeler(par_nom, "m5_lister_comptes_a_payer", {"depart": "0"}, ADMIN)["erreur"] == "arguments_invalides"
    assert _appeler(par_nom, "m5_lister_comptes_a_payer", {"depart": 1.5}, ADMIN)["erreur"] == "arguments_invalides"


def test_un_fichier_de_taux_illisible_est_un_refus_nomme_pas_un_montant(dep, par_nom, monkeypatch, tmp_path):
    _recevoir(dep)
    mauvais = tmp_path / "taux.yaml"
    mauvais.write_text("schema_version: 2\n", encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_CHEMIN_TAUX_FISCAUX", mauvais)

    assert _code(_appeler(par_nom, "m5_lister_comptes_a_payer", {}, ADMIN)) == "REJ-TAUX-FICHIER-INVALIDE"
    assert _code(_saisir(par_nom)) == "REJ-TAUX-FICHIER-INVALIDE"


def test_la_lecture_par_pages_via_capacites_n_est_jamais_tronquee(dep, par_nom):
    """40 PO : la réponse complète dépasserait de loin les 6 000 caractères que `Capacites` laisse passer. Chaque
    page, telle que le modèle la reçoit, reste entière et la suite se lit par `prochain_depart`."""
    for numero in range(1, 41):
        _publier(_charge(evenement_id=f"evt-{numero:02d}", po_id=f"PO-{numero:02d}",
                         horodatage=f"2026-09-{(numero - 1) % 28 + 1:02d}T09:00:00-04:00"))
    resume = _drainer(dep)
    assert resume["traites"] == 40 and resume["echecs"] == 0
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    vus, depart, pages = [], 0, 0

    while depart is not None:
        with contexte.appele_par_appareil(ADMIN):
            reponse = capacites.appeler("m5_lister_comptes_a_payer", {"depart": depart})
        assert "tronque" not in reponse, f"page {pages} tronquée"
        assert len(json.dumps(reponse, ensure_ascii=False)) <= 6000
        page = reponse["resultat"]["resultat"]
        assert page["total"] == 40 and page["totaux"]["nombre_po"] == 40
        vus.extend(c["po_id"] for c in page["comptes"])
        depart, pages = page["prochain_depart"], pages + 1
        assert pages <= 40

    assert pages > 1 and len(vus) == 40 and len(set(vus)) == 40


def test_le_detail_d_un_po_entre_dans_une_page(dep, par_nom):
    _recevoir(dep, evenement_id="evt-1", gouttiere="60", vis="0", horodatage=LIVRAISON_1)
    _recevoir(dep, evenement_id="evt-2", gouttiere="0", vis="40", horodatage=LIVRAISON_2)
    _saisie_acceptee(par_nom, numero_facture="F-1001", montant_avant_taxes="300.00")
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)

    with contexte.appele_par_appareil(ADMIN):
        reponse = capacites.appeler("m5_lister_comptes_a_payer", {"po_id": "PO-1"})

    assert "tronque" not in reponse
    (ligne,) = reponse["resultat"]["resultat"]["comptes"]
    assert ligne["rapprochement"]["verdict"] == "ECART"
    assert ligne["rapprochement"]["sens"] == "FACTURE_INFERIEURE_AU_RECU"
    assert ligne["a_payer_apres_taxes"] == "367.93" and len(ligne["factures_saisies"]) == 1
