"""PLAN T1.4-k2, de bout en bout : la personne authentifiée d'un appel d'appareil traverse
`Capacites.appeler` et le `_meta` MCP jusque dans M5, qui ne croit plus `role` ni `autorise_couts`.

Les tests par cas (rôle retiré, personne désactivée, argument qui élargit ou qui restreint, agent) sont
dans le département (`departments/m05-financecore/tests/test_acces_appareil.py`) ; ici on prouve la
CHAÎNE : identité du `_meta` MCP -> `contexte.appele_par_appareil` -> `m5_etat_tresorerie` -> refus nommé
ou état, sans aucune trace ni écriture, et la portée que le core applique (`openclaw.roles_outils`) qui
ferme M5 à l'employé et au vendeur. Vrais manifestes, vrais outils, vraies personnes ; données fictives
(AGENTS.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
from m5_financecore import outils as outils_m5
from mcp import Client
from sqlalchemy import select

from opsys import approbations, contexte, identite, openclaw, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.serveur_mcp import creer_serveur
from opsys.stockage.schema import META

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[1] / "departments"
DEPARTEMENTS_TESTES = {"m05-financecore"}
HORODATAGE = "2026-08-03T12:00:00+00:00"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")

# Les outils M5 de la portée `admin` : quatre lectures (dont deux de T1.5-d), la lecture des comptes à payer et la
# saisie d'une facture fournisseur par un humain (T4.15, une écriture : voir test_comptes_a_payer_outils.py), et le
# calendrier fiscal (T4.16, lecture pure).
OUTILS_DE_LECTURE_FINANCE = {"m5_etat_tresorerie", "m5_lister_attentes_facturation",
                             "m5_lire_rentabilite_chantier", "m5_lire_comptes_a_recevoir",
                             "m5_lister_comptes_a_payer", "m5_saisir_facture_fournisseur",
                             "m5_lire_echeances_fiscales",
                             # T4.15-c : facture sans PO (N3), correction et annulation d'une facture saisie (N4 :
                             # l'appel attend le propriétaire ou la finance, voir test_correction_outils.py)
                             "m5_saisir_facture_sans_po", "m5_corriger_facture_fournisseur",
                             "m5_annuler_facture_fournisseur",
                             # T4.16-d : la prévision de trésorerie (lecture pure, même règle d'accès)
                             "m5_prevoir_tresorerie",
                             # T4.19-b : le constat du cash libre publié au bus (T1, N3 : l'admin, avec le droit de
                             # voir les coûts ; voir departments/m05-financecore/tests/test_constat_cash_libre_outils.py)
                             "m5_constater_cash_libre"}
CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"
CODE_DIFFERENTE = "REJ-IDENTITE-FOURNIE-DIFFERENTE"
CODE_REQUIS = "REJ-AUTORISE-COUTS-REQUIS"


@pytest.fixture
def capacites(session, nathan):
    """Vrai département M5 (mode `ombre` de son manifeste), base migrée, nathan présent, registre de
    production garni : solde 500.00, provisions 80.00, argent disponible 420.00."""
    departements = charger_departements(RACINE_DEPARTEMENTS)
    assert departements["m05-financecore"].mode == "ombre"
    outils_m5.utiliser_stockage_durable()
    capacites = Capacites(departements, session, filtre=DEPARTEMENTS_TESTES, memoire=False)
    for montant, type_mouvement in (("500.00", "ENCAISSEMENT"), ("80.00", "PROVISION")):
        reponse = executer_atomique(capacites.index["m5_enregistrer_mouvement"][1], {
            "montant": montant, "type_mouvement": type_mouvement, "horodatage": HORODATAGE,
            "classe_retention": "STANDARD", "source": "test-fictif"})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return capacites


@pytest.fixture
def personnes(session, capacites):
    with session() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])


def _instantane_base():
    """Le contenu de TOUTES les tables : un appel de lecture, accordé ou refusé, ne doit rien écrire
    (ni registre, ni trace d'approbation, ni journal, ni idempotence)."""
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _appeler(capacites, nom, arguments, identite_appelante):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments)


def _code(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


# -- 1. la portée que le core applique : M5 est fermé à l'employé et au vendeur -------------------------
def test_le_core_ne_donne_les_outils_m5_ni_a_l_employe_ni_au_vendeur(capacites):
    portees = openclaw.roles_outils(capacites.departements)

    assert [n for n in portees["employee"] if n.startswith("m5_")] == []
    assert [n for n in portees["seller"] if n.startswith("m5_")] == []
    assert {n for n in portees["admin"] if n.startswith("m5_")} == OUTILS_DE_LECTURE_FINANCE
    # L'écriture financière et l'engagement ne sont dans aucun rôle : T3/N5 et la cascade §6.
    tous = {n for noms in portees.values() for n in noms}
    assert not tous & {"m5_enregistrer_mouvement", "m5_enregistrer_paiement_facture", "m5_envoyer_facture",
                       "m5_creer_facture_brouillon"}


# -- 2. par Capacites : la vue vient du rôle authentifié -----------------------------------------------
def test_l_admin_authentifie_voit_les_montants_sans_rien_dire_et_sans_trace(capacites, personnes, session):
    avant = _instantane_base()

    reponse = _appeler(capacites, "m5_etat_tresorerie", {}, ADMIN)

    assert reponse["ok"] is True and reponse["resultat"]["role"] == "admin"
    assert (reponse["resultat"]["solde"], reponse["resultat"]["argent_disponible"]) == ("500.00", "420.00")
    with session() as cnx:
        assert approbations.lister(cnx) == [], "une lecture (T0) ne passe ni par la file ni par la trace"
    assert _instantane_base() == avant


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
def test_un_employe_ou_un_vendeur_n_obtient_aucun_montant_meme_en_le_demandant(
        capacites, personnes, session, appelante):
    avant = _instantane_base()

    for arguments in ({"autorise_couts": True}, {"role": "admin", "autorise_couts": True}, {}):
        reponse = _appeler(capacites, "m5_etat_tresorerie", arguments, appelante)
        assert _code(reponse) == CODE_INVALIDE
        assert "500.00" not in json.dumps(reponse) and "420.00" not in json.dumps(reponse)
    assert _code(_appeler(capacites, "m5_lister_attentes_facturation", {}, appelante)) == CODE_INVALIDE
    for nom in ("m5_lire_rentabilite_chantier", "m5_lire_comptes_a_recevoir"):  # T1.5-d : même règle
        assert _code(_appeler(capacites, nom, {}, appelante)) == CODE_INVALIDE, nom
    assert _instantane_base() == avant


def test_un_agent_sans_identite_d_appareil_choisit_encore_sa_vue(capacites, personnes):
    complet = capacites.appeler("m5_etat_tresorerie", {"role": "gestionnaire", "autorise_couts": True})
    sans_montant = capacites.appeler("m5_etat_tresorerie", {"autorise_couts": False})
    implicite = capacites.appeler("m5_etat_tresorerie", {"role": "gestionnaire"})

    assert (complet["resultat"]["role"], complet["resultat"]["solde"]) == ("gestionnaire", "500.00")
    assert sans_montant["resultat"]["solde"] is None
    assert _code(implicite) == CODE_REQUIS


# -- 3. par MCP : l'identité vient du `_meta`, jamais des arguments -----------------------------------------
def _meta(personne, role):
    return {"opsys/appareil": "tel-fictif-t1-4-k2", "opsys/horodatageAppareil": "2026-09-28T10:15:00-04:00",
            "opsys/personne": personne, "opsys/role": role}


def test_mcp_le_schema_publie_ne_rend_plus_role_ni_autorise_couts_obligatoires(capacites, personnes):
    serveur = creer_serveur(capacites)

    async def scenario():
        async with Client(serveur) as client:
            return {o.name: o for o in (await client.list_tools()).tools}

    outil = anyio.run(scenario)["m5_etat_tresorerie"]

    assert "required" not in outil.input_schema
    assert {"role", "autorise_couts"} <= set(outil.input_schema["properties"])


def test_mcp_l_identite_du_meta_decide_pas_le_role_ni_autorise_couts_des_arguments(capacites, personnes, session):
    serveur = creer_serveur(capacites)

    async def scenario(appels):
        async with Client(serveur) as client:
            reponses = []
            for arguments, meta in appels:
                resultat = await client.call_tool("m5_etat_tresorerie", arguments, meta=meta)
                reponses.append(json.loads(resultat.content[0].text))
            return reponses

    avant = _instantane_base()
    admin_sans_arguments, admin_etiquette, vendeur_veut, employe_se_dit_admin, admin_restreint, agent = anyio.run(
        scenario, [
            ({}, _meta("admin.fictif", "admin")),
            ({"role": "gestionnaire", "autorise_couts": True}, _meta("admin.fictif", "admin")),
            ({"autorise_couts": True}, _meta("vendeur.fictif", "seller")),
            # Le jeton dit `employee`, les arguments se disent `admin` : c'est le jeton qui décide.
            ({"role": "admin", "autorise_couts": True}, _meta("marc.fictif", "employee")),
            ({"autorise_couts": False}, _meta("admin.fictif", "admin")),
            ({"autorise_couts": True}, None),
        ])

    assert admin_sans_arguments["ok"] is True and admin_sans_arguments["resultat"]["solde"] == "500.00"
    assert admin_sans_arguments["resultat"]["role"] == "admin"
    assert _code(admin_etiquette) == CODE_DIFFERENTE
    assert _code(vendeur_veut) == CODE_INVALIDE
    assert _code(employe_se_dit_admin) == CODE_INVALIDE
    assert admin_restreint["resultat"]["solde"] is None and admin_restreint["resultat"]["role"] == "admin"
    assert agent["resultat"]["solde"] == "500.00", "la voie des agents (sans jeton d'appareil) est inchangée"
    with session() as cnx:
        assert approbations.lister(cnx) == []
    assert _instantane_base() == avant


def test_mcp_une_personne_desactivee_ne_lit_plus_rien_avec_le_meme_jeton(capacites, personnes, session):
    serveur = creer_serveur(capacites)

    async def lire():
        async with Client(serveur) as client:
            resultat = await client.call_tool("m5_etat_tresorerie", {}, meta=_meta("admin.fictif", "admin"))
            return json.loads(resultat.content[0].text)

    assert anyio.run(lire)["resultat"]["solde"] == "500.00"
    with session() as cnx:
        identite.activer(cnx, "admin.fictif", False)
    avant = _instantane_base()

    refuse = anyio.run(lire)

    assert _code(refuse) == CODE_INVALIDE
    assert _instantane_base() == avant
