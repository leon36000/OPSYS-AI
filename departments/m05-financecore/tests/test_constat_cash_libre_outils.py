"""PLAN T4.19-b : `m5_constater_cash_libre` (T1, N3, `admin`) sur le VRAI socle : M5 fait constater le cash libre et le
publie au bus (`m5.cash_libre_constate`), dans la même transaction que la trace du constat.

Base SQLite temporaire migrée, registres durables réels (mouvements, factures clients, comptes à payer), vrai
manifeste de M5 (mode `ombre`) ou un manifeste de test qui déclare ce que le propriétaire décide, vraies approbations.
Le cas de référence est celui de `test_cash_libre.py` (calculé à la main) : solde 37654.33, taxes 1981.69, paies
4200.00, DAS 1350.75, comptes à payer 459.91, dettes 800.00, réserves 1000.00, cash libre 27861.98.

Ce que ce fichier prouve :
- le déclencheur est un outil T1 DÉDIÉ : un agent en mode `ombre` attend la décision d'un humain, l'admin de son
  téléphone (identité confirmée en base) l'exécute ; `m5_etat_tresorerie` (T0) ne publie RIEN ;
- un constat par date de référence et par version des données : le redire ne publie rien, un autre jour ou une autre
  version publie un nouvel événement, un retour à une version antérieure publie un événement DISTINCT ;
- un cash libre « non calculable, manque X » est publié tel quel, jamais un zéro ;
- tout refus vient AVANT la lecture des registres et sans aucune écriture ;
- la trace et l'événement réussissent ou échouent ensemble ; ni le grand livre, ni les factures ne bougent.

Personnes, montants et identifiants fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import (
    analyse,
    comptes_a_payer,
    constat_cash_libre,
    facturation,
    registre,
    taux_fiscaux,
)
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION
from sqlalchemy import select

from opsys import approbations as opsys_approbations
from opsys import contexte, evenements, idempotence, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, META

FICTIF = True
D = Decimal
_RACINE_M5 = Path(__file__).resolve().parents[1]
DEPARTEMENT = "m05-financecore"
TYPE = "m5.cash_libre_constate"
OUTIL = "m5_constater_cash_libre"
AUJOURD_HUI = "2026-09-29"
LENDEMAIN = "2026-09-30"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
ANCIEN = contexte.IdentiteAppelante(personne="ancien.fictif", role="admin")
FANTOME = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")
EMPLOYE_QUI_SE_DIT_ADMIN = contexte.IdentiteAppelante(personne="marc.fictif", role="admin")

CONFIGURATION_COMPLETE = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "4200.00", "source": "brouillon de paie de Marc Tremblay (fictif)", "au": "2026-09-25"},
        "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
}


def _sans(configuration, composante):
    obligations = {c: v for c, v in configuration["obligations_declarees"].items() if c != composante}
    return {**configuration, "obligations_declarees": obligations}


def _avec_dettes(configuration, montant):
    dettes = {**configuration["obligations_declarees"]["dettes"], "montant": montant}
    return {**configuration, "obligations_declarees": {**configuration["obligations_declarees"], "dettes": dettes}}


# ------------------------------------------------------------------------------------------- installation
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-constat.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
        identite.creer_personne(cnx, "ancien.fictif", "Ancien Admin Fictif", "mot-de-passe-ancien-1234", ["admin"],
                                actif=False)
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner", "admin"])
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


def _mouvement(reg, montant, type_mouvement, horodatage="2026-08-01T12:00:00-04:00"):
    registre.enregistrer_mouvement({"montant": D(montant), "type_mouvement": type_mouvement, "horodatage": horodatage,
                                    "classe_retention": "STANDARD", "source": "test-fictif"}, reg)


def _peupler_mouvements():
    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        _mouvement(reg, "50000.00", "ENCAISSEMENT")
        _mouvement(reg, "-12345.67", "DECAISSEMENT", "2026-08-15T12:00:00-04:00")
        _mouvement(reg, "1000.00", "PROVISION", "2026-09-10T12:00:00-04:00")


def _peupler_factures_clients(taux):
    lignes = (
        ("F-1", "D-1", "10000.00", "2026-07-15", "ENVOYEE"), ("F-2", "D-2", "3333.33", "2026-08-20", "PAYEE"),
        ("F-3", "D-3", "1000.00", "2026-06-10", "ENVOYEE"), ("F-4", "D-4", "500.00", "2026-09-01", "BROUILLON"),
        ("F-5", "D-5", "200.00", "2026-07-01", "ENVOYEE"), ("F-6", "D-6", "100.00", "2026-06-30", "ENVOYEE"),
    )
    with stockage.transaction():
        reg = m5_outils._registre_factures(None)
        for facture_id, devis, prix, jour, statut in lignes:
            _, verdict = facturation.creer_facture_brouillon(
                facture_id, "CH-1", devis, "C-1",
                [{"description": "travaux (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": prix,
                  "reference_ligne_devis": "L-1"}], f"{jour}T09:00:00-04:00", taux, reg)
            assert verdict is None, verdict
            if statut in ("ENVOYEE", "PAYEE"):
                assert facturation.envoyer_facture(facture_id, f"{jour}T09:30:00-04:00", reg)[1] is None
            if statut == "PAYEE":
                payee = facturation.marquer_facture_payee(facture_id, "nathan", "2026-09-05T09:00:00-04:00", reg)
                assert payee[1] is None


def _reception(evenement_id, po_id, quantite, horodatage):
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": horodatage, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": quantite, "quantite_recue": quantite,
                    "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": "5.00", "verdict_prix_reception": "PRIX_CATALOGUE",
                    "ecart_prix_critique": False}],
    }


def _peupler_a_payer(taux):
    with stockage.transaction():
        for evenement, po, quantite, horodatage in (("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),
                                                    ("e-2", "PO-2", "20", "2026-09-16T09:00:00-04:00")):
            m5_outils._recevoir_reception_enregistree(_reception(evenement, po, quantite, horodatage))
        reg = m5_outils._registre_comptes_a_payer()
        for po, numero, jour, montant in (("PO-1", "F-1001", "2026-09-14", "300.00"),
                                          ("PO-2", "F-2001", "2026-06-20", "100.00")):
            _, verdict = comptes_a_payer.saisir_facture_fournisseur(
                po_id=po, fournisseur_id="gentek", numero_facture=numero, date_facture=jour,
                montant_avant_taxes=montant, total_facture=None, saisi_par="nathan", voie="appareil",
                horodatage="2026-09-20T10:00:00-04:00", dictionnaire_taux=taux, registre_cible=reg)
            assert verdict is None, verdict


@pytest.fixture
def cas_fictif(taux, declare):
    """Le cas de référence complet : registres durables peuplés et manifeste qui déclare tout."""
    declare(CONFIGURATION_COMPLETE)
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=ADMIN):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _constat(par_nom, jour=AUJOURD_HUI, identite_appelante=ADMIN, **arguments):
    """Un appel ACCEPTÉ : le corps de `resultat.resultat` (`deja_constate`, `publie`, `constat`, `mention`)."""
    reponse = _appeler(par_nom, OUTIL, {"aujourd_hui": jour, **arguments}, identite_appelante)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _refus(par_nom, arguments, identite_appelante=ADMIN):
    """Un refus nommé : le code du verdict (jamais une panne, jamais un constat)."""
    reponse = _appeler(par_nom, OUTIL, arguments, identite_appelante)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    assert set(reponse["resultat"]) == {"accepte", "verdict"}, "un refus ne rend ni constat ni montant"
    return reponse["resultat"]["verdict"]["code"]


def _etat(par_nom, identite_appelante=ADMIN):
    reponse = _appeler(par_nom, "m5_etat_tresorerie", {}, identite_appelante)
    assert reponse["ok"] is True and "verdict" not in reponse["resultat"], reponse
    return reponse["resultat"]


def _publies():
    """Les charges `m5.cash_libre_constate` publiées, par rang : `(evenement_id, producteur, charge)`."""
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.producteur,
                                    EVENEMENTS_SORTANTS.c.charge)
                             .where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)).all()
    publies = [(ligne.evenement_id, ligne.producteur, codec.decoder(ligne.charge)) for ligne in lignes]
    return sorted(publies, key=lambda paire: paire[2]["sequence"])


def _traces():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, "constats_cash_libre"))


def _instantane_base():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


def _tables_changees(avant, apres):
    return {nom for nom in avant if avant[nom] != apres[nom]}


def _registre(nom):
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, nom))


# ============================================================================================= le contrat
def test_l_outil_est_un_t1_n3_pour_l_admin_seulement_avec_ses_arguments_et_sa_mention(par_nom):
    outil = par_nom[OUTIL]

    assert outil.autonomie.value == "T1" and outil.niveau_effectif is Niveau.N3 and outil.frontiere_humaine is False
    assert outil.roles_appareil == frozenset({"admin"})
    schema = outil.parametres
    assert set(schema["properties"]) == {"aujourd_hui", "role", "autorise_couts"}
    assert schema["required"] == ["aujourd_hui"] and schema["additionalProperties"] is False
    assert schema["properties"]["aujourd_hui"]["type"] == "string"
    assert len(outil.description) <= 1024
    for morceau in ("CONSTATER", "m5.cash_libre_constate", "jamais zéro", "deja_constate", "aucun paiement",
                    "Analyse préparatoire"):
        assert morceau in outil.description, morceau
    assert OUTIL in analyse.SORTIES_D_ANALYSE


def test_m5_declare_publier_le_constat_et_le_catalogue_le_connait(dep):
    assert dep.evenements_publie == ("m5.rentabilite_chantier", TYPE)
    assert TYPE in evenements.types_connus()
    assert evenements.verifier_coherence({DEPARTEMENT: dep}) == []


def test_le_seul_outil_t3_reste_les_deux_d_avant_le_constat_est_une_ecriture_interne(par_nom):
    assert {nom for nom, o in par_nom.items() if o.autonomie.value == "T3"} == {
        "m5_enregistrer_mouvement", "m5_enregistrer_paiement_facture"}


# ======================================================================= 1. le cas fictif, constaté et publié
def test_le_cas_fictif_est_constate_et_publie_avec_sa_trace_dans_la_meme_transaction(par_nom, cas_fictif):
    avant = _instantane_base()

    corps = _constat(par_nom)

    assert set(corps) == {"role", "deja_constate", "publie", "constat", "mention"}
    assert (corps["role"], corps["deja_constate"], corps["publie"], corps["mention"]) == ("admin", False, True, MENTION)
    constat = corps["constat"]
    assert (constat["sequence"], constat["date_reference"], constat["statut"]) == (1, AUJOURD_HUI, "CALCULE")
    assert (constat["cash_libre_cad"], constat["au_plus_cad"], constat["en_deficit"]) == ("27861.98", None, False)
    assert constat["manque"] == [] and constat["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    (publie,) = _publies()
    evenement_id, producteur, charge = publie
    assert producteur == DEPARTEMENT and evenement_id == charge["evenement_id"] == constat["evenement_id"]
    assert erreurs_charge(TYPE, charge) == []
    (trace,) = _traces()
    assert trace == constat_cash_libre.construire_trace(charge)
    assert _tables_changees(avant, _instantane_base()) == {"registres_maillons", "evenements_sortants"}


def test_le_constat_publie_les_memes_chiffres_que_l_etat_de_tresorerie(par_nom, cas_fictif):
    """Aucun second calcul : la charge est la lecture de `m5_etat_tresorerie`, rendue sous la forme du catalogue."""
    vue = _etat(par_nom)["cash_libre"]

    _constat(par_nom)

    ((_, _, charge),) = _publies()
    assert charge["version_donnees"] == vue["cash_libre_id"]
    assert (charge["cash_libre_cad"], charge["au_plus_cad"], charge["en_deficit"]) == (
        vue["cash_libre"], vue["au_plus"], vue["en_deficit"])
    assert charge["lecture"] == vue["lecture"] and charge["reserves"] == vue["reserves"]
    assert charge["hypotheses"] == vue["hypotheses"] and charge["mention"] == vue["mention"] == MENTION
    assert charge["solde"]["montant_cad"] == vue["solde"]["montant"]
    assert charge["solde"]["fraicheur"] == vue["solde"]["fraicheur"]
    assert [c["id"] for c in charge["composantes"]] == [c["id"] for c in vue["composantes"]]
    for publiee, lue in zip(charge["composantes"], vue["composantes"], strict=True):
        assert publiee["montant_cad"] == lue["montant"] and publiee["statut"] == lue["statut"], lue["id"]
        assert publiee["fraicheur"] == lue["fraicheur"], lue["id"]
        assert publiee["source"]["registres"] == lue["source"].get("registres", []), lue["id"]


def test_le_texte_du_proprietaire_et_le_detail_du_calcul_ne_partent_pas_au_bus(par_nom, cas_fictif):
    """La source d'une déclaration (`Marc Tremblay` dans le manifeste de test) reste dans la lecture de M5."""
    assert "Marc Tremblay" in json.dumps(_etat(par_nom)["cash_libre"], ensure_ascii=False)

    _constat(par_nom)

    ((_, _, charge),) = _publies()
    texte = json.dumps(charge, ensure_ascii=False)
    for interdit in ("Marc", "Tremblay", "brouillon de paie", "estimation du CPA", "prêt camion", "detail", "tps",
                     "tvq", "PO-1", "PO-2", "gentek", "F-1001", "apf-"):
        assert interdit not in texte, interdit
    assert {c["id"]: c["source"]["origine"] for c in charge["composantes"]}["paies"] == "DECLARATION_PROPRIETAIRE"


def test_lire_l_etat_de_tresorerie_ne_publie_rien_seul_le_constat_publie(par_nom, cas_fictif):
    """Le déclencheur est un outil T1 dédié : la lecture (T0) reste une lecture."""
    avant = _instantane_base()

    _etat(par_nom)
    _etat(par_nom, ADMIN)

    assert _publies() == [] and _traces() == [] and _instantane_base() == avant
    assert par_nom["m5_etat_tresorerie"].autonomie.value == "T0"


def test_le_constat_n_ecrit_ni_au_grand_livre_ni_aux_factures_ni_aux_comptes_a_payer(par_nom, cas_fictif):
    avant = {nom: _registre(nom) for nom in ("principal", "factures", "comptes_a_payer")}
    approbations_avant = _instantane_base()["approbations"]

    _constat(par_nom)
    _constat(par_nom, LENDEMAIN)

    assert {nom: _registre(nom) for nom in avant} == avant
    assert len(avant["principal"]) == 3 and not [m for m in avant["principal"] if m["type_mouvement"] == "DECAISSEMENT"
                                                 and m["source"] != "test-fictif"]
    assert _instantane_base()["approbations"] == approbations_avant


def test_un_agent_avec_le_droit_de_voir_les_couts_constate_aussi_par_la_voie_des_agents(par_nom, cas_fictif):
    corps = _constat(par_nom, identite_appelante=None, autorise_couts=True, role="agent-fictif")

    assert corps["role"] == "agent-fictif" and corps["publie"] is True
    assert corps["constat"]["cash_libre_cad"] == "27861.98"
    assert len(_publies()) == 1


# ================================================================ 2. un constat par date et par version des données
def test_redemander_le_meme_constat_ne_publie_rien_et_ne_change_rien(par_nom, cas_fictif):
    premier = _constat(par_nom)
    apres_le_premier = _instantane_base()

    second = _constat(par_nom)

    assert (second["deja_constate"], second["publie"]) == (True, False)
    assert second["constat"] == premier["constat"], "le même constat, avec le même identifiant"
    assert _instantane_base() == apres_le_premier, "rien n'a été écrit : ni trace, ni événement"
    assert len(_publies()) == 1 and len(_traces()) == 1


def test_un_autre_jour_avec_les_memes_donnees_publie_un_nouveau_constat(par_nom, cas_fictif):
    un = _constat(par_nom)["constat"]

    deux = _constat(par_nom, LENDEMAIN)["constat"]

    assert (un["sequence"], deux["sequence"]) == (1, 2)
    assert un["version_donnees"] == deux["version_donnees"], "aucune donnée n'a changé : seul le jour a changé"
    assert deux["date_reference"] == LENDEMAIN and un["evenement_id"] != deux["evenement_id"]
    assert [c["sequence"] for _, _, c in _publies()] == [1, 2]
    assert [t["date_reference"] for t in _traces()] == [AUJOURD_HUI, LENDEMAIN]


def test_une_donnee_qui_change_le_meme_jour_publie_un_nouveau_constat(par_nom, cas_fictif):
    un = _constat(par_nom)["constat"]
    with stockage.transaction():
        _mouvement(m5_outils._registre_mouvements(None), "100.00", "ENCAISSEMENT", "2026-09-28T12:00:00-04:00")

    deux = _constat(par_nom)

    assert deux["publie"] is True and deux["deja_constate"] is False
    assert (un["cash_libre_cad"], deux["constat"]["cash_libre_cad"]) == ("27861.98", "27961.98")
    assert deux["constat"]["version_donnees"] != un["version_donnees"]
    assert deux["constat"]["sequence"] == 2 and len(_publies()) == 2


def test_un_retour_a_une_version_anterieure_publie_un_evenement_distinct(par_nom, cas_fictif, declare):
    """Dettes 800 -> 900 -> 800, le même jour : le troisième constat a la version du premier. Sans le rang dans
    l'identifiant, le bus avalerait son événement (no-op) et M8 resterait sur les 27761.98 $ du deuxième."""
    un = _constat(par_nom)["constat"]
    declare(_avec_dettes(CONFIGURATION_COMPLETE, "900.00"))
    deux = _constat(par_nom)["constat"]
    declare(CONFIGURATION_COMPLETE)

    trois = _constat(par_nom)

    assert (un["cash_libre_cad"], deux["cash_libre_cad"], trois["constat"]["cash_libre_cad"]) == (
        "27861.98", "27761.98", "27861.98")
    assert trois["constat"]["version_donnees"] == un["version_donnees"], "la même version qu'au départ"
    assert trois["deja_constate"] is False and trois["publie"] is True
    assert trois["constat"]["evenement_id"] not in (un["evenement_id"], deux["evenement_id"])
    assert [c["sequence"] for _, _, c in _publies()] == [1, 2, 3]
    assert len({e for e, _, _ in _publies()}) == 3
    # et le redire une deuxième fois, tout de suite, n'ajoute rien : c'est le DERNIER constat
    assert _constat(par_nom)["deja_constate"] is True and len(_publies()) == 3


def test_un_constat_du_meme_jour_et_de_la_meme_version_que_l_avant_dernier_n_est_pas_un_doublon(par_nom, cas_fictif,
                                                                                          declare):
    """La comparaison est avec le DERNIER constat seulement : A, B, puis A de nouveau est un troisième constat."""
    _constat(par_nom)
    declare(_avec_dettes(CONFIGURATION_COMPLETE, "900.00"))
    _constat(par_nom)
    declare(CONFIGURATION_COMPLETE)

    assert _constat(par_nom)["publie"] is True
    assert len(_traces()) == 3


# =========================================== 3. « non calculable, manque X » : publié tel quel, jamais un zéro
def test_un_cash_libre_non_calculable_est_publie_tel_quel_avec_son_manque(par_nom, cas_fictif, declare):
    declare(_sans(CONFIGURATION_COMPLETE, "paies"))

    corps = _constat(par_nom)

    constat = corps["constat"]
    assert corps["publie"] is True and constat["statut"] == "NON_CALCULABLE"
    assert constat["cash_libre_cad"] is None and constat["en_deficit"] is None
    assert constat["au_plus_cad"] == "32061.98", "un repère (le solde moins ce qui est connu), pas de l'argent"
    assert constat["manque"] == [{"composante": "paies", "code": "REJ-CASH-PAIE-A-DECLARER"}]
    assert "PAS de l'argent disponible" in constat["lecture"]
    ((_, _, charge),) = _publies()
    paies = {c["id"]: c for c in charge["composantes"]}["paies"]
    assert (paies["statut"], paies["montant_cad"], paies["source"]["origine"]) == ("NON_CALCULABLE", None, "AUCUNE")
    assert erreurs_charge(TYPE, charge) == []
    assert _traces()[0]["statut"] == "NON_CALCULABLE"


def test_le_manifeste_livre_ne_suppose_rien_le_constat_dit_tout_ce_qui_manque(par_nom, taux):
    """Sans déclaration du propriétaire (le vrai manifeste de M5, GATE NATHAN) : taxes, paies, DAS, dettes."""
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)

    constat = _constat(par_nom)["constat"]

    assert constat["statut"] == "NON_CALCULABLE" and constat["cash_libre_cad"] is None
    assert {m["composante"] for m in constat["manque"]} == {"taxes_a_remettre", "paies", "das", "dettes"}
    assert constat["au_plus_cad"] == "36194.42", "37654.33 - 459.91 - 1000.00 : seul ce que M5 connaît est retranché"
    assert D("37654.33") - D("459.91") - D("1000.00") == D("36194.42")
    assert len(_publies()) == 1


def test_sans_aucun_mouvement_le_solde_est_inconnu_et_le_constat_ne_donne_aucun_chiffre(par_nom, declare):
    declare(CONFIGURATION_COMPLETE)

    constat = _constat(par_nom)["constat"]

    assert constat["statut"] == "NON_CALCULABLE" and constat["cash_libre_cad"] is None
    assert constat["au_plus_cad"] is None
    assert constat["manque"][0] == {"composante": "solde", "code": "REJ-CASH-SOLDE-ABSENT"}
    ((_, _, charge),) = _publies()
    assert charge["solde"]["montant_cad"] is None and erreurs_charge(TYPE, charge) == []


def test_un_constat_non_calculable_redit_ne_se_publie_pas_deux_fois(par_nom, cas_fictif, declare):
    declare(_sans(CONFIGURATION_COMPLETE, "paies"))
    premier = _constat(par_nom)

    second = _constat(par_nom)

    assert (second["deja_constate"], second["publie"]) == (True, False)
    assert second["constat"] == premier["constat"] and len(_publies()) == 1


def test_la_declaration_qui_arrive_apres_coup_donne_un_constat_calcule_qui_remplace_le_non_calculable(
        par_nom, cas_fictif, declare):
    declare(_sans(CONFIGURATION_COMPLETE, "paies"))
    manquant = _constat(par_nom)["constat"]
    declare(CONFIGURATION_COMPLETE)

    complet = _constat(par_nom)["constat"]

    assert (manquant["statut"], complet["statut"]) == ("NON_CALCULABLE", "CALCULE")
    assert complet["sequence"] == manquant["sequence"] + 1 and complet["cash_libre_cad"] == "27861.98"
    charges = [c for _, _, c in _publies()]
    assert charges[0]["cash_libre_cad"] is None, "l'historique reste : le manque n'a jamais porté de montant"
    assert charges[1]["manque"] == []


# ============================================================ 4. tout refus vient avant la lecture, sans écriture
@pytest.fixture
def registre_interdit(monkeypatch):
    """Un refus arrive AVANT toute lecture : ouvrir le registre des mouvements échoue le test."""
    appels = []

    def ouvrir(*args, **kwargs):
        appels.append(args)
        raise AssertionError("le registre des mouvements a été ouvert avant le refus")

    monkeypatch.setattr(m5_outils, "_registre_mouvements", ouvrir)
    return appels


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
def test_employe_et_vendeur_n_ont_aucune_portee_meme_si_le_core_les_laissait_passer(
        par_nom, cas_fictif, registre_interdit, appelante):
    avant = _instantane_base()

    assert _refus(par_nom, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True}, appelante) == (
        "REJ-IDENTITE-APPAREIL-INVALIDE")
    assert _refus(par_nom, {"aujourd_hui": AUJOURD_HUI}, appelante) == "REJ-IDENTITE-APPAREIL-INVALIDE"

    assert _instantane_base() == avant and registre_interdit == []


@pytest.mark.parametrize("appelante", [ANCIEN, FANTOME, EMPLOYE_QUI_SE_DIT_ADMIN],
                         ids=["personne_desactivee", "personne_inconnue", "employe_qui_se_dit_admin"])
def test_une_identite_qui_ne_tient_plus_en_base_est_refusee_avant_toute_lecture(
        par_nom, cas_fictif, registre_interdit, appelante):
    avant = _instantane_base()

    assert _refus(par_nom, {"aujourd_hui": AUJOURD_HUI}, appelante) == "REJ-IDENTITE-APPAREIL-INVALIDE"

    assert _instantane_base() == avant and registre_interdit == []


def test_un_role_different_de_celui_du_jeton_est_refuse(par_nom, cas_fictif, registre_interdit):
    avant = _instantane_base()

    code = _refus(par_nom, {"aujourd_hui": AUJOURD_HUI, "role": "employee"})

    assert code == "REJ-IDENTITE-FOURNIE-DIFFERENTE" and _instantane_base() == avant and registre_interdit == []


def test_un_constat_sans_le_droit_de_voir_les_couts_est_refuse_jamais_publie_sans_montant(
        par_nom, cas_fictif, registre_interdit):
    avant = _instantane_base()

    assert _refus(par_nom, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": False}) == "REJ-CONSTAT-COUTS-REQUIS"
    assert _refus(par_nom, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": False}, None) == "REJ-CONSTAT-COUTS-REQUIS"

    assert _instantane_base() == avant and registre_interdit == []


def test_sans_appareil_autorise_couts_est_obligatoire_explicite_et_booleen(par_nom, cas_fictif, registre_interdit):
    avant = _instantane_base()

    assert _refus(par_nom, {"aujourd_hui": AUJOURD_HUI}, None) == "REJ-AUTORISE-COUTS-REQUIS"
    assert _refus(par_nom, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": None}, None) == "REJ-AUTORISE-COUTS-REQUIS"
    reponse = _appeler(par_nom, OUTIL, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": "true"}, None)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", "le schéma refuse une chaîne"

    assert _instantane_base() == avant and registre_interdit == []


@pytest.mark.parametrize("jour", ["2026-9-29", "29/09/2026", "20260929", "2026-02-30", "aujourd'hui", ""])
def test_une_date_illisible_est_refusee_avant_toute_lecture_jamais_corrigee(par_nom, cas_fictif, registre_interdit,
                                                                            jour):
    avant = _instantane_base()

    assert _refus(par_nom, {"aujourd_hui": jour}) == "REJ-CONSTAT-DATE-INVALIDE"

    assert _instantane_base() == avant and registre_interdit == []


def test_la_date_est_requise_et_un_argument_inconnu_est_refuse_par_le_schema(par_nom, cas_fictif):
    for arguments in ({}, {"aujourd_hui": None}, {"aujourd_hui": AUJOURD_HUI, "montant": "1.00"},
                      {"aujourd_hui": AUJOURD_HUI, "cash_libre": "27861.98"}, {"aujourd_hui": 20260929}):
        reponse = _appeler(par_nom, OUTIL, arguments)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", arguments
    assert _publies() == [] and _traces() == []


def test_hors_du_stockage_durable_il_n_y_a_ni_registre_reel_ni_bus_le_constat_est_refuse(par_nom, cas_fictif,
                                                                                         registre_interdit):
    m5_outils.reinitialiser_stockage_mouvements()
    avant = _instantane_base()

    assert _refus(par_nom, {"aujourd_hui": AUJOURD_HUI}) == "REJ-CONSTAT-STOCKAGE-NON-DURABLE"

    assert _instantane_base() == avant and registre_interdit == []


# ========================================================================= 5. la trace et l'événement, ensemble
def test_la_publication_qui_echoue_annule_aussi_la_trace(par_nom, cas_fictif, monkeypatch):
    """Même transaction : si l'événement ne peut pas partir (charge non conforme au catalogue), la trace n'existe pas
    non plus. M8 ne peut jamais voir un constat que M5 n'aurait pas tracé, ni l'inverse."""
    avant = _instantane_base()
    vraie = constat_cash_libre.charge_evenement
    monkeypatch.setattr(constat_cash_libre, "charge_evenement",
                        lambda resultat, jour, sequence: {**vraie(resultat, jour, sequence), "devise": "USD"})

    reponse = _appeler(par_nom, OUTIL, {"aujourd_hui": AUJOURD_HUI})

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier" and "charge invalide" in reponse["details"]
    assert _traces() == [] and _publies() == [] and _instantane_base() == avant


def test_une_trace_qui_echoue_n_envoie_aucun_evenement(par_nom, cas_fictif, monkeypatch):
    avant = _instantane_base()

    def trace_impossible(charge):
        raise ValueError("trace impossible (fictive)")

    monkeypatch.setattr(constat_cash_libre, "construire_trace", trace_impossible)

    reponse = _appeler(par_nom, OUTIL, {"aujourd_hui": AUJOURD_HUI})

    assert reponse["ok"] is False and "trace impossible" in reponse["details"]
    assert _publies() == [] and _instantane_base() == avant


def test_un_registre_des_comptes_a_payer_incoherent_ne_donne_aucun_constat(par_nom, cas_fictif):
    """Une annulation qui vise une facture absente : le calcul LÈVE (jamais un chiffre à demi lu), rien n'est publié."""
    with stockage.transaction():
        reg = m5_outils._registre_comptes_a_payer()
        reg.ajouter({
            "type_entree": "annulation_facture_fournisseur", "facture_fournisseur_id": "apf-inexistante",
            "motif": "test (fictif)", "horodatage": "2026-09-21T10:00:00-04:00", "annule_par": "nathan",
            "role": "admin", "voie": "appareil"})
    avant = _instantane_base()

    reponse = _appeler(par_nom, OUTIL, {"aujourd_hui": AUJOURD_HUI})

    assert reponse["ok"] is False, reponse
    assert _publies() == [] and _traces() == [] and _instantane_base() == avant


# ============================================================ 6. par le vrai chemin des appels (`Capacites`)
def test_un_agent_en_mode_ombre_demande_et_rien_n_est_publie_tant_qu_un_humain_n_a_pas_decide(dep, cas_fictif):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    assert dep.mode == "ombre"
    avant = _instantane_base()

    demande = capacites.appeler(OUTIL, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True})

    assert demande["ok"] is True and demande["statut"] == "en_attente_approbation", demande
    assert _publies() == [] and _traces() == []
    assert _tables_changees(avant, _instantane_base()) == {"approbations"}, "seule la demande est écrite"
    with stockage.transaction() as cnx:
        (ligne,) = cnx.execute(select(APPROBATIONS.c.niveau, APPROBATIONS.c.statut, APPROBATIONS.c.outil).where(
            APPROBATIONS.c.id == demande["demande_id"])).all()
    assert tuple(ligne) == ("N3", "en_attente", OUTIL)


def test_le_proprietaire_approuve_la_demande_de_l_agent_et_le_constat_part(dep, cas_fictif):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    demande = capacites.appeler(OUTIL, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True})

    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, demande["demande_id"], True, "nathan",
            outils_executables({DEPARTEMENT: dep}, stockage.transaction), {DEPARTEMENT: dep})

    assert decision["statut"] == "executee" and decision["reponse"]["ok"] is True, decision
    assert decision["reponse"]["resultat"]["accepte"] is True
    ((evenement_id, _, charge),) = _publies()
    assert charge["cash_libre_cad"] == "27861.98" and charge["date_reference"] == AUJOURD_HUI
    assert decision["reponse"]["resultat"]["resultat"]["constat"]["evenement_id"] == evenement_id
    assert len(_traces()) == 1


def test_une_demande_refusee_ne_publie_rien(dep, cas_fictif):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    demande = capacites.appeler(OUTIL, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True})

    with stockage.transaction() as cnx:
        opsys_approbations.decider(
            cnx, demande["demande_id"], False, "nathan",
            outils_executables({DEPARTEMENT: dep}, stockage.transaction), {DEPARTEMENT: dep})

    assert _publies() == [] and _traces() == []


@pytest.mark.parametrize("mode", ["supervise", "autonome"])
def test_en_mode_supervise_ou_autonome_l_ecriture_interne_du_t1_s_execute_sans_file(dep, cas_fictif, mode):
    """T1 n'est une frontière humaine ni en `supervise` ni en `autonome` : c'est la règle du socle (ADR-0009 §4)."""
    capacites = Capacites({DEPARTEMENT: dataclasses.replace(dep, mode=mode)}, stockage.transaction)

    reponse = capacites.appeler(OUTIL, {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True})

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert len(_publies()) == 1 and len(_traces()) == 1


def _meta(cle="cle-constat-1"):
    return idempotence.Meta(cle=cle, appareil="tel-admin-fictif", horodatage_appareil="2026-09-29T10:00:00-04:00")


def test_l_admin_qui_lance_le_constat_depuis_son_appareil_l_execute_sans_file_avec_sa_trace(dep, cas_fictif):
    """Le socle valide au départ un N3 que la personne authentifiée lance elle-même (`_valider_au_depart`) : le constat
    part tout de suite, et la trace de cette validation est écrite dans la même transaction."""
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    assert dep.mode == "ombre"

    with contexte.appele_par_appareil(ADMIN):
        reponse = capacites.appeler(OUTIL, {"aujourd_hui": AUJOURD_HUI}, _meta())

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True and reponse["rejoue"] is False, reponse
    ((evenement_id, _, charge),) = _publies()
    assert reponse["resultat"]["resultat"]["constat"]["evenement_id"] == evenement_id
    assert charge["cash_libre_cad"] == "27861.98" and len(_traces()) == 1
    with stockage.transaction() as cnx:
        (ligne,) = cnx.execute(select(APPROBATIONS.c.outil, APPROBATIONS.c.statut, APPROBATIONS.c.decide_par,
                                      APPROBATIONS.c.niveau)).all()
    assert tuple(ligne) == (OUTIL, "executee", "admin.fictif", "N3")


def test_le_renvoi_de_la_meme_cle_rejoue_la_reponse_sans_publier_un_second_constat(dep, cas_fictif):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    with contexte.appele_par_appareil(ADMIN):
        premiere = capacites.appeler(OUTIL, {"aujourd_hui": AUJOURD_HUI}, _meta())
        apres_la_premiere = _instantane_base()

        renvoi = capacites.appeler(OUTIL, {"aujourd_hui": AUJOURD_HUI}, _meta())
        autre_jour = capacites.appeler(OUTIL, {"aujourd_hui": LENDEMAIN}, _meta())

    assert renvoi["rejoue"] is True and renvoi["resultat"] == premiere["resultat"]
    assert autre_jour["ok"] is False and autre_jour["erreur"] == "mutation_conflit"
    assert _instantane_base() == apres_la_premiere and len(_publies()) == 1


def test_l_employe_qui_appelle_l_outil_par_le_socle_est_refuse_hors_portee_sans_rien_ecrire(dep, cas_fictif):
    """Défense en profondeur : le core refuse déjà un rôle hors portée en amont ; le socle le redit."""
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    avant = _instantane_base()

    with contexte.appele_par_appareil(MARC):
        refuse = capacites.appeler(OUTIL, {"aujourd_hui": AUJOURD_HUI}, _meta("cle-employe"))

    assert refuse["ok"] is False and refuse["erreur"] == "hors_portee_role", refuse
    assert _publies() == [] and _traces() == []
    assert _tables_changees(avant, _instantane_base()) <= {"mutations_appliquees"}
