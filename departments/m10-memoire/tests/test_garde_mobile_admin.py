"""M10 : identité confirmée avant lecture et arbitrage humain (données fictives)."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from m10_memoire import humain, registre, revision
from m10_memoire import outils as m10
from sqlalchemy import text

from opsys import contexte, identite, stockage
from opsys.outils import executer, executer_atomique

FICTIF = True
ADMIN = contexte.IdentiteAppelante("admin.fictif", "admin")
EMPLOYE = contexte.IdentiteAppelante("employe.fictif", "employee")
VENDEUR = contexte.IdentiteAppelante("vendeur.fictif", "seller")
LECTURES = {
    "m10_lister_signaux": {},
    "m10_statut_decision": {"decision_id": "DEC-A-FICTIF"},
    "m10_statut_revision": {"revision_ligne_id": "revision-inconnue-fictive"},
}
DATE = "2026-09-15T12:00:00-04:00"
MAILLON = frozenset({
    "type_entree", "horodatage", "ligne_id_a", "ligne_id_b", "statut", "revision_ligne_id",
    "ligne_id", "precedent_ligne_id", "par", "role", "source_decision",
})


@pytest.fixture
def outils(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm10-admin-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        for acteur in (ADMIN, EMPLOYE, VENDEUR):
            identite.creer_personne(cnx, acteur.personne, "Personne fictive", "mot-de-passe-fictif-1234", [acteur.role])
    yield {o.nom: o for o in m10.outils()}
    stockage.liberer()


def _tables():
    with stockage.transaction() as cnx:
        noms = cnx.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )).scalars().all()
        return {nom: sorted(
            [dict(ligne) for ligne in cnx.execute(text(f'SELECT * FROM "{nom}"')).mappings()],
            key=lambda ligne: json.dumps(ligne, sort_keys=True, default=str),
        ) for nom in noms}


def _interdire_lecture(monkeypatch):
    def interdit():
        raise AssertionError("identité refusée avant lecture des registres")

    for cible in (m10._REGISTRE_EVENEMENTS, m10._REGISTRE_AFFAIRES):
        monkeypatch.setattr(cible, "lire", interdit)


CAS_REFUS = [
    pytest.param(EMPLOYE, None, id="employe"),
    pytest.param(VENDEUR, None, id="vendeur"),
    pytest.param(contexte.IdentiteAppelante("fantome.fictif", "admin"), None, id="inconnu"),
    pytest.param(ADMIN, "inactive", id="inactif"),
    pytest.param(ADMIN, "role_retire", id="role_retire"),
    pytest.param(contexte.IdentiteAppelante(EMPLOYE.personne, "admin"), None, id="role_non_porte"),
]


def _retirer(perturbation):
    if perturbation is not None:
        with stockage.transaction() as cnx:
            if perturbation == "inactive":
                identite.activer(cnx, ADMIN.personne, False)
            else:
                identite.retirer_role(cnx, ADMIN.personne, "admin")


@pytest.mark.parametrize("nom", LECTURES)
@pytest.mark.parametrize(("acteur", "perturbation"), CAS_REFUS)
def test_lecture_refuse_identite_avant_registre_sans_ecriture(outils, monkeypatch, nom, acteur, perturbation):
    _retirer(perturbation)
    avant = _tables()
    _interdire_lecture(monkeypatch)
    with contexte.appele_par_appareil(acteur):
        reponse = executer_atomique(outils[nom], LECTURES[nom])
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _tables() == avant


@pytest.mark.parametrize("nom", LECTURES)
def test_lecture_hors_transaction_refuse_et_ne_lit_rien(outils, monkeypatch, nom):
    avant = _tables()
    _interdire_lecture(monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        reponse = executer(outils[nom], LECTURES[nom])
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _tables() == avant


@pytest.mark.parametrize("nom", LECTURES)
def test_admin_non_proprietaire_garde_enveloppe_directe_et_voie_interne(outils, nom):
    avant = _tables()
    interne = executer_atomique(outils[nom], LECTURES[nom])
    with contexte.appele_par_appareil(ADMIN):
        admin = executer_atomique(outils[nom], LECTURES[nom])
    assert admin == interne and admin["ok"] is True
    assert "accepte" not in admin["resultat"]
    assert _tables() == avant


@pytest.mark.parametrize("nom", LECTURES)
def test_apres_contexte_refuse_lecture_interne_reste_autorisee(outils, nom):
    with contexte.appele_par_appareil(EMPLOYE):
        reponse = executer_atomique(outils[nom], LECTURES[nom])
    assert reponse["resultat"]["accepte"] is False
    assert contexte.identite_appelante() is None
    assert executer(outils[nom], LECTURES[nom])["ok"] is True


def _signalement():
    lignes = []
    for ident in ("DEC-A-FICTIF", "DEC-B-FICTIF"):
        reponse = m10.journaliser_decision({
            "decision_id": ident, "raison": "Raison métier fictive tracée.",
            "statut": "proposee", "options_ecartees": "Ne rien faire",
        }, DATE)
        assert reponse["accepte"] is True
        lignes.append(reponse["decision"]["ligne_id"])
    signalement = m10.signaler_revision(*lignes, DATE)
    assert signalement["accepte"] is True
    return signalement["resultat"]["ligne_id"]


@pytest.mark.parametrize(("acteur", "perturbation"), [pytest.param(None, None, id="agent"), *CAS_REFUS])
def test_arbitrage_refuse_avant_registre_sans_maillon(outils, monkeypatch, acteur, perturbation):
    ident = _signalement()
    _retirer(perturbation)
    avant = _tables()
    _interdire_lecture(monkeypatch)
    with contexte.appele_par_appareil(acteur):
        reponse = executer_atomique(outils["m10_arbitrer_revision"], {
            "revision_ligne_id": ident, "statut": "distincts_confirmes", "horodatage": DATE,
        })
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] in {
        humain.REJ_HUMAIN_REQUIS, humain.REJ_HUMAIN_IDENTITE_INVALIDE, humain.REJ_HUMAIN_ROLE_INSUFFISANT,
    }
    assert _tables() == avant


def test_arbitrage_admin_trace_acteur_et_reception_sans_alterer_historique(outils):
    ident = _signalement()
    avant = m10._REGISTRE_AFFAIRES.lire()
    reception = contexte.HorodatageAppareil("tel-fictif", dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
                                          dt.datetime(2026, 9, 16, 16, 30, tzinfo=dt.UTC))
    with contexte.appele_par_appareil(ADMIN), contexte.receptionne_de(reception):
        reponse = executer_atomique(outils["m10_arbitrer_revision"], {
            "revision_ligne_id": ident, "statut": "distincts_confirmes", "horodatage": "2000-01-01T00:00:00Z",
        })
    assert reponse["resultat"]["accepte"] is True
    maillon = reponse["resultat"]["resultat"]
    assert set(maillon) == MAILLON
    assert (maillon["par"], maillon["role"], maillon["source_decision"]) == (ADMIN.personne, "admin", "appareil")
    assert maillon["horodatage"] == "2026-09-16T16:30:00+00:00"
    assert m10._REGISTRE_AFFAIRES.lire()[:-1] == avant
    assert m10.statut_revision(ident) == {"statut": "distincts_confirmes"}


@pytest.mark.parametrize("acteur", [
    {}, {"par": "admin.fictif", "role": "employee", "source": "appareil"},
    {"par": "admin.fictif", "role": "admin", "source": "agent"},
])
def test_revision_pure_rejette_acteur_fourni_invalide_sans_ecrire(acteur):
    cible = registre.Registre()
    maillon, verdict = revision.arbitrer_revision(cible, "inconnue", "distincts_confirmes", DATE, acteur=acteur)
    assert maillon is None and verdict["code"] == humain.REJ_HUMAIN_ACTEUR_INVALIDE
    assert cible.lire() == []


@pytest.mark.parametrize(("acteur", "perturbation"), CAS_REFUS)
def test_catalogue_refuse_avant_snapshot_sans_ecriture(outils, monkeypatch, acteur, perturbation):
    _retirer(perturbation)
    avant = _tables()
    _interdire_lecture(monkeypatch)
    with contexte.appele_par_appareil(acteur):
        reponse = executer_atomique(outils["m10_lister_references"], {})
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _tables() == avant


def test_catalogue_admin_et_interne_couple_un_snapshot_sans_texte_prive(outils, monkeypatch):
    revision_id = _signalement()
    m10.journaliser_decision({
        "decision_id": "DEC-PRIVEE-FICTIVE", "raison": "CONFIDENTIEL_FICTIF", "statut": "proposee",
        "options_ecartees": "CONFIDENTIEL_FICTIF",
    }, DATE, "CLIENT_PRIVATE")
    tete_privee = m10._REGISTRE_AFFAIRES.tete()
    avant = _tables()
    lire = m10._REGISTRE_AFFAIRES.lire
    appels = []

    def snapshot_unique():
        appels.append(1)
        assert len(appels) == 1, "une seule lecture durable par appel"
        return lire()

    monkeypatch.setattr(m10._REGISTRE_AFFAIRES, "lire", snapshot_unique)
    with contexte.appele_par_appareil(ADMIN):
        admin = executer_atomique(outils["m10_lister_references"], {})
    assert admin["ok"] and admin["resultat"]["accepte"]
    page = admin["resultat"]["resultat"]
    assert page["total"] == page["affichees"] == 3
    assert page["confidentialite"]["nb_retenus"] == 1
    assert [r["revision_ligne_id"] for r in page["revisions"]] == [revision_id]
    texte = json.dumps(admin, ensure_ascii=False)
    assert "CONFIDENTIEL_FICTIF" not in texte and "DEC-PRIVEE-FICTIVE" not in texte and tete_privee not in texte
    assert len(texte) == page["taille_caracteres"] <= 5400
    appels.clear()
    assert executer_atomique(outils["m10_lister_references"], {}) == admin
    assert len(appels) == 1
    assert _tables() == avant


@pytest.mark.parametrize("args", [
    {"limite": True}, {"decalage": 1.5},
    {"affaire_id": "LEAD-1"}, {"personne": "admin.fictif"}, {"domaine": "developpement"},
])
def test_catalogue_schema_ferme_refuse_pagination_et_filtres_etrangers(outils, monkeypatch, args):
    avant = _tables()
    _interdire_lecture(monkeypatch)
    reponse = executer_atomique(outils["m10_lister_references"], args)
    assert reponse["erreur"] == "arguments_invalides"
    assert _tables() == avant


@pytest.mark.parametrize("args", [{"limite": 0}, {"limite": 9}, {"decalage": -1}])
def test_catalogue_bornes_metier_avant_lecture_si_schema_ne_verifie_pas_min_max(outils, monkeypatch, args):
    avant = _tables()
    _interdire_lecture(monkeypatch)
    reponse = executer_atomique(outils["m10_lister_references"], args)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CATALOGUE-PAGINATION-INVALIDE"
    assert _tables() == avant


@pytest.mark.parametrize(("acteur", "perturbation"), CAS_REFUS)
def test_dossier_refuse_avant_snapshot_sans_ecriture(outils, monkeypatch, acteur, perturbation):
    _retirer(perturbation)
    avant = _tables()
    _interdire_lecture(monkeypatch)
    with contexte.appele_par_appareil(acteur):
        reponse = executer_atomique(outils["m10_lire_revision"], {"revision_ligne_id": "inconnue-fictive"})
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _tables() == avant


def test_dossier_admin_actif_un_snapshot_puis_voie_interne_sans_contexte(outils, monkeypatch):
    ident = _signalement()
    avant = _tables()
    lire = m10._REGISTRE_AFFAIRES.lire
    appels = []

    def snapshot_unique():
        appels.append(1)
        assert len(appels) == 1
        return lire()

    monkeypatch.setattr(m10._REGISTRE_AFFAIRES, "lire", snapshot_unique)
    with contexte.appele_par_appareil(ADMIN):
        admin = executer_atomique(outils["m10_lire_revision"], {"revision_ligne_id": ident})
    assert admin["ok"] and admin["resultat"]["accepte"]
    assert len(admin["resultat"]["resultat"]["faits"]) == 2
    appels.clear()
    assert executer_atomique(outils["m10_lire_revision"], {"revision_ligne_id": ident}) == admin
    assert len(appels) == 1 and _tables() == avant


def test_dossier_hors_transaction_refuse_avant_snapshot(outils, monkeypatch):
    _interdire_lecture(monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        reponse = executer(outils["m10_lire_revision"], {"revision_ligne_id": "inconnue-fictive"})
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


@pytest.mark.parametrize("args", [{}, {"revision_ligne_id": 1}, {"revision_ligne_id": "x", "domaine": "dev"}])
def test_dossier_schema_ferme_avec_identifiant_requis(outils, monkeypatch, args):
    _interdire_lecture(monkeypatch)
    assert executer_atomique(outils["m10_lire_revision"], args)["erreur"] == "arguments_invalides"
