"""Contrat horaire individuel : parcours durable SQLite et identité/N4 réels. Toutes les personnes sont fictives."""

from __future__ import annotations

import contextlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import m5_financecore.outils as m5_outils
import pytest
from m5_financecore import registre
from sqlalchemy import update

from opsys import approbations as opsys_approbations
from opsys import contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

FICTIF = True
DEPARTEMENT = "m05-financecore"
_RACINE_M5 = Path(__file__).resolve().parents[1]
ADMIN_NATHAN = contexte.IdentiteAppelante("nathan", "admin")
ADMIN_COMPTA = contexte.IdentiteAppelante("comptable", "admin")
ADMIN_GESTION = contexte.IdentiteAppelante("gestion", "admin")
GESTIONNAIRE = contexte.IdentiteAppelante("gestion", "manager")
ADMIN_INACTIF = contexte.IdentiteAppelante("admin.inactif", "admin")
OWNER_CONSOLE = contexte.IdentiteAppelante("nathan", "nathan_owner", source="console")
EMPLOYEE = contexte.IdentiteAppelante("employe.fictif", "employee")
SELLER = contexte.IdentiteAppelante("vendeur.fictif", "seller")


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-salaire.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "nathan-fictif-1234", ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "comptable", "Comptable fictive", "comptable-fictif-1234", ["finance", "admin"])
        identite.creer_personne(cnx, "gestion", "Gestionnaire fictive", "gestion-fictif-1234", ["manager", "admin"])
        identite.creer_personne(cnx, "admin.inactif", "Admin inactif fictif", "admin-inactif-1234", ["admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé fictif", "employe-fictif-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur fictif", "vendeur-fictif-1234", ["seller"])
    yield
    stockage.liberer()


@pytest.fixture
def outils_par_nom():
    return {outil.nom: outil for outil in m5_outils.outils()}


@contextlib.contextmanager
def _identite(appelante):
    with contexte.appele_par_appareil(appelante):
        yield


def _appeler(outils_par_nom, nom, arguments, appelante):
    with _identite(appelante):
        reponse = executer_atomique(outils_par_nom[nom], arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _contrat_args(**overrides):
    args = {
        "employee_person_id": "employe.fictif",
        "contrat_id": "EMP-HORAIRE-001",
        "valide_du": "2026-10-01",
        "valide_jusqu_au": "2027-01-01",
        "fuseau": "America/Montreal",
        "devise": "CAD",
        "taux_horaire": "31.25",
        "source_humaine": "Contrat écrit signé, référence fictive CONTRAT-001",
        "date_source": "2026-09-30",
        "revision_attendue": 0,
        "ligne_id_attendue": "",
        "motif": "Enregistrement initial fictif",
    }
    args.update(overrides)
    return args


def _enregistrer(outils_par_nom, appelante=ADMIN_NATHAN, **overrides):
    return _appeler(outils_par_nom, "m5_enregistrer_contrat_horaire", _contrat_args(**overrides), appelante)


def test_n4_ecrit_dans_flux_dedie_et_lecteur_admin_retourne_le_contrat(outils_par_nom):
    ecrit = _enregistrer(outils_par_nom)

    assert ecrit["accepte"] is True
    contrat = ecrit["resultat"]
    assert (contrat["revision"], contrat["employee_person_id"], contrat["taux_horaire"]) == (
        1, "employe.fictif", "31.25"
    )
    assert contrat["devise"] == "CAD"
    assert contrat["remplace_ligne_id"] is None
    assert contrat["valide_jusqu_au"] == "2027-01-01"
    assert contrat["approbateur"] == {
        "personne": "nathan", "role": "nathan_owner", "voie": "appareil", "decision_id": None,
    }

    lu = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_COMPTA)
    assert lu["accepte"] is True and lu["resultat"]["taux_horaire"] == "31.25"
    assert len(stockage.maillons(DEPARTEMENT, "principal")) == 0
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 1


def test_owner_console_peut_valider_et_son_origine_est_tracee(outils_par_nom):
    result = _enregistrer(outils_par_nom, OWNER_CONSOLE)
    assert result["accepte"] is True
    assert result["resultat"]["approbateur"] == {
        "personne": "nathan", "role": "nathan_owner", "voie": "console", "decision_id": None,
    }


def test_admin_avec_role_manager_secondaire_peut_lire_salaire(outils_par_nom):
    _enregistrer(outils_par_nom)
    lu = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_GESTION)
    assert lu["accepte"] is True
    assert lu["resultat"]["taux_horaire"] == "31.25"


def test_ecriture_agent_attend_decision_n4_reelle_du_socle(base_durable):
    dep = lire_manifeste(_RACINE_M5)
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction, memoire=False)
    demande = capacites.appeler("m5_enregistrer_contrat_horaire", _contrat_args())
    assert demande["statut"] == "en_attente_approbation"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 0

    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, demande["demande_id"], True, "nathan",
            outils_executables({DEPARTEMENT: dep}, stockage.transaction), {DEPARTEMENT: dep},
        )
    assert decision["statut"] == "executee"
    courant = stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")[0]
    assert courant["approbateur"]["personne"] == "nathan"
    assert courant["approbateur"]["role"] == "nathan_owner"
    assert courant["approbateur"]["voie"] == "approbation"
    assert courant["approbateur"]["decision_id"] == demande["demande_id"]


def test_revision_n4_cas_et_rejeu_ancien_hash_refuse(outils_par_nom):
    initial = _enregistrer(outils_par_nom)["resultat"]
    revision = _enregistrer(
        outils_par_nom,
        ADMIN_COMPTA,
        taux_horaire="32.00",
        revision_attendue=initial["revision"],
        ligne_id_attendue=initial["ligne_id"],
        motif="Révision fictive approuvée",
    )
    assert revision["accepte"] is True
    assert revision["resultat"]["revision"] == 2
    assert revision["resultat"]["remplace_ligne_id"] == initial["ligne_id"]

    rejeu = _enregistrer(outils_par_nom, ADMIN_NATHAN, taux_horaire="34.00",
                          revision_attendue=1, ligne_id_attendue=initial["ligne_id"])
    assert rejeu["accepte"] is False
    assert rejeu["verdict"]["code"] == "REJ-SALAIRE-REVISION-PERIMEE"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 2
    courant = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_COMPTA)
    assert courant["accepte"] is True
    assert (courant["resultat"]["revision"], courant["resultat"]["taux_horaire"]) == (2, "32.00")


def test_deux_revisions_concurrentes_avec_meme_tete_n_enregistrent_qu_une(outils_par_nom):
    initial = _enregistrer(outils_par_nom)["resultat"]
    depart = Barrier(2)

    def reviser(taux):
        depart.wait(timeout=5)
        return _enregistrer(
            outils_par_nom,
            taux_horaire=taux,
            revision_attendue=initial["revision"],
            ligne_id_attendue=initial["ligne_id"],
            motif="Révision concurrente fictive",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(reviser, ("32.00", "33.00")))
    assert sum(resultat["accepte"] for resultat in resultats) == 1
    refuse = next(resultat for resultat in resultats if not resultat["accepte"])
    assert refuse["verdict"]["code"] == "REJ-SALAIRE-REVISION-PERIMEE"
    journal = registre.Registre(maillons=stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires"))
    assert journal.taille() == 2 and journal.valider_chaine() == (True, "")


def test_retrait_append_only_et_relecture_refusee(outils_par_nom):
    initial = _enregistrer(outils_par_nom)["resultat"]
    retire = _appeler(outils_par_nom, "m5_revoquer_contrat_horaire", {
        "employee_person_id": "employe.fictif", "contrat_id": "EMP-HORAIRE-001",
        "revision_attendue": 1, "ligne_id_attendue": initial["ligne_id"],
        "motif": "Fin de relation fictive",
    }, ADMIN_NATHAN)
    assert retire["accepte"] is True and retire["resultat"]["revision"] == 2
    assert retire["resultat"]["type_entree"] == "contrat_horaire_revoque"
    lu = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, OWNER_CONSOLE)
    assert lu["accepte"] is False and lu["verdict"]["code"] == "REJ-SALAIRE-CONTRAT-REVOQUE"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 2


def test_nouveau_contrat_apres_revocation_est_la_seule_revision_lisible(outils_par_nom):
    initial = _enregistrer(outils_par_nom)["resultat"]
    _appeler(outils_par_nom, "m5_revoquer_contrat_horaire", {
        "employee_person_id": "employe.fictif", "contrat_id": "EMP-HORAIRE-001", "revision_attendue": 1,
        "ligne_id_attendue": initial["ligne_id"], "motif": "Fin du premier contrat fictif",
    }, ADMIN_NATHAN)
    nouveau = _enregistrer(outils_par_nom, contrat_id="EMP-HORAIRE-002", taux_horaire="32.00")
    assert nouveau["accepte"] is True
    lu = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_COMPTA)
    assert lu["accepte"] is True
    assert lu["resultat"]["contrat_id"] == "EMP-HORAIRE-002"
    assert lu["resultat"]["taux_horaire"] == "32.00"


@pytest.mark.parametrize(
    "appelante", [None, EMPLOYEE, SELLER, GESTIONNAIRE], ids=["agent", "employe", "vendeur", "manager"]
)
def test_lecteur_refuse_avant_lecture_salariale(outils_par_nom, monkeypatch, appelante):
    def lire_interdit():
        raise AssertionError("le journal salarial ne doit pas être lu")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", lire_interdit)
    with _identite(appelante):
        enveloppe = executer_atomique(outils_par_nom["m5_lire_contrat_horaire"], {
            "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
            "fuseau": "America/Montreal",
        })
    assert enveloppe["ok"] is True
    reponse = enveloppe["resultat"]
    assert reponse["accepte"] is False


def test_admin_inactif_est_refuse_avant_lecture_salariale(outils_par_nom, monkeypatch):
    with stockage.transaction() as cnx:
        identite.activer(cnx, "admin.inactif", False)

    def lire_interdit():
        raise AssertionError("le journal salarial ne doit pas être lu")

    monkeypatch.setattr(m5_outils, "_registre_contrats_salaries", lire_interdit)
    result = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_INACTIF)
    assert result["accepte"] is False


@pytest.mark.parametrize("valeur", ["0", "-1", "NaN", "Infinity", "1e999999", "1000000.00"])
def test_taux_refuse_decimal_nonpositif_nonfini_ou_hors_borne(outils_par_nom, valeur):
    resultat = _enregistrer(outils_par_nom, taux_horaire=valeur)
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-TAUX-INVALIDE"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 0


def test_taux_json_nombre_refuse_par_le_contrat(outils_par_nom):
    enveloppe = executer_atomique(
        outils_par_nom["m5_enregistrer_contrat_horaire"], _contrat_args(taux_horaire=31.25)
    )
    assert enveloppe["ok"] is False and enveloppe["erreur"] == "arguments_invalides"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 0


@pytest.mark.parametrize(("source_humaine", "date_source"), [("", "2026-09-30"), ("Référence fictive", "")])
def test_source_humaine_et_date_sont_obligatoires(outils_par_nom, source_humaine, date_source):
    resultat = _enregistrer(outils_par_nom, source_humaine=source_humaine, date_source=date_source)
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-SOURCE-INVALIDE"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 0


@pytest.mark.parametrize(
    ("valide_du", "valide_jusqu_au", "fuseau"),
    [("2026-10-01", "2026-10-01", "America/Montreal"),
     ("2026-10-02", "2026-10-01", "America/Montreal"),
     ("2026-10-01", "2027-01-01", "Mars/Olympus")],
)
def test_periode_et_fuseau_invalides_refuses(outils_par_nom, valide_du, valide_jusqu_au, fuseau):
    resultat = _enregistrer(outils_par_nom, valide_du=valide_du, valide_jusqu_au=valide_jusqu_au, fuseau=fuseau)
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-PERIODE-INVALIDE"


def test_lecture_exige_contrat_couvrant_toute_periode_et_un_seul_taux(outils_par_nom):
    _enregistrer(outils_par_nom)
    resultat = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-09-30", "valide_jusqu_au": "2026-10-02",
        "fuseau": "America/Montreal",
    }, OWNER_CONSOLE)
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-COUVERTURE-ABSENTE"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 1
    journal = registre.Registre(maillons=stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires"))
    assert journal.valider_chaine() == (True, "")


def test_lecture_accepte_une_seule_date_inclusive(outils_par_nom):
    _enregistrer(outils_par_nom, valide_du="2026-09-01", valide_jusqu_au="2026-10-01")
    resultat = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-09-14", "valide_jusqu_au": "2026-09-14",
        "fuseau": "America/Montreal",
    }, ADMIN_NATHAN)
    assert resultat["accepte"] is True
    assert resultat["resultat"]["taux_horaire"] == "31.25"


def test_lecture_refuse_date_de_fin_exclusive_du_contrat_et_dates_inversees(outils_par_nom):
    _enregistrer(outils_par_nom, valide_du="2026-09-01", valide_jusqu_au="2026-10-01")
    fin_exclusive = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-01", "valide_jusqu_au": "2026-10-01",
        "fuseau": "America/Montreal",
    }, ADMIN_NATHAN)
    assert fin_exclusive["accepte"] is False
    assert fin_exclusive["verdict"]["code"] == "REJ-SALAIRE-COUVERTURE-ABSENTE"

    inverse = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-09-15", "valide_jusqu_au": "2026-09-14",
        "fuseau": "America/Montreal",
    }, ADMIN_NATHAN)
    assert inverse["accepte"] is False
    assert inverse["verdict"]["code"] == "REJ-SALAIRE-PERIODE-INVALIDE"


def test_lecture_refuse_maillon_enregistre_sans_motif_meme_si_rehashe(outils_par_nom):
    initial = _enregistrer(outils_par_nom)["resultat"]
    altered = dict(initial, motif="")
    rebuilt = registre.Registre()
    rebuilt.ajouter({k: v for k, v in altered.items() if k not in {"ligne_id", "precedent_ligne_id"}})
    maillon_rehashe = rebuilt.lire()[0]
    assert rebuilt.valider_chaine() == (True, "")

    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (
        REGISTRES.c.registre == "contrats_salaries_horaires") & (REGISTRES.c.rang == 0)
    with stockage.transaction() as cnx:
        assert cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon_rehashe))).rowcount == 1
    resultat = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_NATHAN)
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-STRUCTURE-INVALIDE"


def test_lecture_refuse_plusieurs_taux_sur_une_periode(outils_par_nom):
    first = _enregistrer(outils_par_nom, valide_jusqu_au="2026-11-01")["resultat"]
    second = _enregistrer(
        outils_par_nom, contrat_id="EMP-HORAIRE-002", valide_du="2026-11-01", valide_jusqu_au="2027-01-01",
        taux_horaire="33.00",
    )
    assert second["accepte"] is True
    result = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-31", "valide_jusqu_au": "2026-11-01",
        "fuseau": "America/Montreal",
    }, ADMIN_COMPTA)
    assert result["accepte"] is False and result["verdict"]["code"] == "REJ-SALAIRE-TAUX-AMBIGU"
    assert first["ligne_id"] != second["resultat"]["ligne_id"]


def test_ecriture_refuse_deux_contrats_actifs_qui_se_chevauchent(outils_par_nom):
    _enregistrer(outils_par_nom)
    resultat = _enregistrer(
        outils_par_nom, contrat_id="EMP-HORAIRE-002", valide_du="2026-12-01", valide_jusqu_au="2027-03-01",
    )
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-CHEVAUCHEMENT"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 1


@pytest.mark.parametrize("champ", ["taux_horaire", "source_humaine"])
def test_chaine_alteree_est_refusee_sans_reparation(outils_par_nom, champ):
    initial = _enregistrer(outils_par_nom)["resultat"]
    corrupt = dict(initial, **{champ: "source ou taux altéré"})
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (
        REGISTRES.c.registre == "contrats_salaries_horaires") & (REGISTRES.c.rang == 0)
    with stockage.transaction() as cnx:
        assert cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(corrupt))).rowcount == 1
    maillons = stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")
    avant = maillons[0]
    resultat = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_NATHAN)
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-CHAINE-INVALIDE"
    assert maillons[0] == avant and maillons[0][champ] == "source ou taux altéré"
    assert initial["ligne_id"] == maillons[0]["ligne_id"]


def test_maillon_de_revocation_altere_sans_rehash_est_refuse(outils_par_nom):
    initial = _enregistrer(outils_par_nom)["resultat"]
    _appeler(outils_par_nom, "m5_revoquer_contrat_horaire", {
        "employee_person_id": "employe.fictif", "contrat_id": "EMP-HORAIRE-001", "revision_attendue": 1,
        "ligne_id_attendue": initial["ligne_id"], "motif": "Fin fictive",
    }, ADMIN_NATHAN)
    revocation = dict(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")[1], motif="source altérée")
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (
        REGISTRES.c.registre == "contrats_salaries_horaires") & (REGISTRES.c.rang == 1)
    with stockage.transaction() as cnx:
        assert cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(revocation))).rowcount == 1
    resultat = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_NATHAN)
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == "REJ-SALAIRE-CHAINE-INVALIDE"


def test_maillon_de_revision_altere_sans_rehash_est_refuse(outils_par_nom):
    initial = _enregistrer(outils_par_nom)["resultat"]
    _enregistrer(outils_par_nom, taux_horaire="32.00", revision_attendue=1,
                 ligne_id_attendue=initial["ligne_id"], motif="Révision fictive")
    revision = dict(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")[1], source_humaine="autre source")
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (
        REGISTRES.c.registre == "contrats_salaries_horaires") & (REGISTRES.c.rang == 1)
    with stockage.transaction() as cnx:
        assert cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(revision))).rowcount == 1
    resultat = _appeler(outils_par_nom, "m5_lire_contrat_horaire", {
        "employee_person_id": "employe.fictif", "valide_du": "2026-10-02", "valide_jusqu_au": "2026-12-31",
        "fuseau": "America/Montreal",
    }, ADMIN_NATHAN)
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == "REJ-SALAIRE-CHAINE-INVALIDE"


def test_personne_cible_doit_etre_employe_opsys_actif(outils_par_nom):
    resultat = _enregistrer(outils_par_nom, employee_person_id="vendeur.fictif")
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-EMPLOYE-INVALIDE"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 0


def test_personne_employee_inactive_est_refusee_avant_toute_ecriture(outils_par_nom):
    with stockage.transaction() as cnx:
        identite.activer(cnx, "employe.fictif", False)
    resultat = _enregistrer(outils_par_nom)
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-SALAIRE-EMPLOYE-INVALIDE"
    assert len(stockage.maillons(DEPARTEMENT, "contrats_salaries_horaires")) == 0
