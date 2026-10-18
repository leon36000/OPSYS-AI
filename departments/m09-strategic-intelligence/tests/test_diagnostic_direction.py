"""Diagnostic temporel serveur : vrais outils/Capacites, SQLite et sources fictives."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from m9_strategic_intelligence import outils as module
from m9_strategic_intelligence import registre
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import APPROBATIONS, ARTEFACTS, EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
NOM = "m9_diagnostiquer_dossier_direction"
ARGS = {"question": "Préparation fictive ?", "modules_attendus": ["M5-fictif", "M8-fictif"],
        "horodatage_reference": "2026-10-18T08:00:00Z"}


@pytest.fixture
def capacites(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'temporel-fictif.db'}")
    stockage.migrer()
    yield Capacites(charger_departements(Path(__file__).resolve().parents[2]), stockage.transaction,
                    filtre={"m09-strategic-intelligence"}, memoire=False)
    stockage.liberer()


def _outil(cible):
    outils = {o.nom: o for o in module.outils(registre_cible=cible, alertes_cible=[])}
    assert NOM in outils, "consommateur temporel absent"
    return outils[NOM]


def _registre(heure="2026-10-18T09:00:00Z", valeur="preuve fictive"):
    cible = registre.RegistreSnapshots()
    cible.ajouter({"module_source": "M5-fictif", "horodatage": heure, "valeurs": {"fait": valeur}})
    return cible


def _appeler(cible, **arguments):
    return executer_atomique(_outil(cible), {**ARGS, **arguments})


def _etat_metier():
    with stockage.transaction() as cnx:
        return {t.name: list(cnx.execute(select(t)).mappings())
                for t in (REGISTRES, APPROBATIONS, EVENEMENTS_SORTANTS, EVENEMENTS_RECUS, ARTEFACTS)}


def _personne(roles, actif=True):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin-fictif", "Admin fictif", "mot-de-passe-fictif",
                               roles, actif=actif)


def test_consommateur_declare_lecture_admin_fermee(capacites):
    outil = _outil(_registre())
    assert outil.roles_appareil == frozenset({"admin"})
    assert outil.niveau_effectif.value == "N0" and outil.autonomie.value == "T0"
    assert set(outil.parametres["properties"]) == set(ARGS)
    assert set(outil.parametres["required"]) == set(ARGS)
    assert outil.parametres["additionalProperties"] is False
    racine = Path(__file__).resolve().parents[3]
    assert Path(module.__file__).resolve().is_relative_to(racine)
    assert Path(stockage.__file__).resolve().is_relative_to(racine)


def test_capacites_admin_lie_dossier_diagnostic_et_preserve_sql(capacites, monkeypatch):
    ingestion = next(o for o in module.outils() if o.nom == "m9_etat_consolide")
    for heure, valeur in [("2026-10-18T09:00:00Z", "A fictif"),
                          ("2026-10-18T05:00:00-04:00", "B fictif")]:
        assert executer_atomique(ingestion, {"snapshot": {
            "module_source": "M5-fictif", "horodatage": heure, "valeurs": {"fait": valeur},
        }})["ok"] is True
    _personne(["admin"])
    avant = _etat_metier()
    lire = registre.RegistreSnapshots.lire
    captures = []

    def compter_capture_durable(self):
        if not isinstance(self._maillons, list):
            captures.append(self)
        return lire(self)

    monkeypatch.setattr(registre.RegistreSnapshots, "lire", compter_capture_durable)
    with contexte.appele_par_appareil(IdentiteAppelante("admin-fictif", "admin")):
        reponse = capacites.appeler(NOM, ARGS)
    assert reponse["ok"] is True, reponse
    assert len(captures) == 1
    assert set(reponse["resultat"]) == {"dossier", "diagnostic"}
    dossier, diagnostic = reponse["resultat"]["dossier"], reponse["resultat"]["diagnostic"]
    assert diagnostic["dossier_id"] == dossier["dossier_id"]
    assert diagnostic["etat_id"] == dossier["etat_id"]
    assert diagnostic["observations"][0]["diagnostic"] == "OBSERVATION_FUTURE"
    assert diagnostic["observations"][0]["ecart_secondes"] == -3600
    assert diagnostic["actualite_metier"] == dossier["actualite"] == "NON_EVALUEE"
    assert dossier["statut_preparation"] == "NON_VALIDE"
    assert len(dossier["contradictions"]) == 1 and len(dossier["preuves"]) == 2
    assert diagnostic["modules_manquants"] == dossier["modules_manquants"] == ["M8-fictif"]
    assert "tronque" not in reponse and "apercu" not in reponse
    assert _etat_metier() == avant


def test_capture_unique_source_changeante_et_reference_seule_change_diagnostic(capacites):
    lignes = _registre().lire()

    class SourceChangeante:
        lectures = 0

        def lire(self):
            self.lectures += 1
            assert self.lectures == 1, "seconde capture durable interdite"
            return deepcopy(lignes)

    source = SourceChangeante()
    reponse = _appeler(source)
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert source.lectures == 1 and resultat["dossier"]["preuves"] == lignes
    autre = _appeler(_registre(), horodatage_reference="2026-10-18T10:00:00Z")["resultat"]
    assert autre["dossier"] == resultat["dossier"]
    assert autre["diagnostic"]["diagnostic_id"] != resultat["diagnostic"]["diagnostic_id"]
    assert autre["diagnostic"]["observations"][0]["diagnostic"] == "ANTERIEURE_REFERENCE"


@pytest.mark.parametrize("role", ["employee", "seller", "client"])
def test_non_admin_refuse_avant_capture(capacites, role):
    class SourceInterdite:
        def lire(self):
            pytest.fail("lecture avant contrôle du rôle")
    with contexte.appele_par_appareil(IdentiteAppelante("personne-fictive", role)):
        reponse = _appeler(SourceInterdite())
    assert reponse["ok"] is False
    assert reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")


@pytest.mark.parametrize("roles,actif", [(["admin"], False), (["employee"], True), ([], True)])
def test_admin_declare_sans_role_sql_courant_refuse_avant_capture(capacites, roles, actif):
    _personne(roles, actif)

    class SourceInterdite:
        def lire(self):
            pytest.fail("lecture avant contrôle SQL courant")
    with contexte.appele_par_appareil(IdentiteAppelante("admin-fictif", "admin")):
        reponse = _appeler(SourceInterdite())
    assert reponse["ok"] is False
    assert reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")


def test_dossier_client_interdit_par_schema(capacites):
    reponse = capacites.appeler(NOM, {**ARGS, "dossier": {"faits_selectionnes": "forgés"}})
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", reponse


@pytest.mark.parametrize("reference", ["2026-10-18T08:00:00", "invalide", "", None])
def test_reference_invalide_refuse_sans_resultat(capacites, reference):
    reponse = _appeler(_registre(), horodatage_reference=reference)
    assert reponse["ok"] is False, reponse
    assert reponse.get("erreur") == "arguments_invalides" or reponse["details"].startswith("REJ-DIAGNOSTIC-REFERENCE")
    assert "resultat" not in reponse


def test_chaine_corrompue_refusee_sans_reparation(capacites):
    lignes = _registre().lire()
    lignes[0]["valeurs"]["fait"] = "altération fictive"
    avant = deepcopy(lignes)
    reponse = _appeler(registre.RegistreSnapshots(lignes))
    assert reponse["ok"] is False and reponse["details"].startswith("REJ-SNAPSHOT-CHAINE-INVALIDE")
    assert lignes == avant and "resultat" not in reponse


def test_budget_combine_refuse_quand_chaque_partie_tient(capacites, monkeypatch):
    resultat = _appeler(_registre())["resultat"]
    def taille(x):
        return len(json.dumps(x, ensure_ascii=False, allow_nan=False))

    borne = max(taille(resultat["dossier"]), taille(resultat["diagnostic"])) + 10
    assert taille(resultat) > borne
    monkeypatch.setattr(module, "BUDGET_SORTIE", borne)
    reponse = _appeler(_registre())
    assert reponse["ok"] is False and reponse["details"].startswith("REJ-DIAGNOSTIC-BORNE"), reponse
    assert "resultat" not in reponse and "tronque" not in reponse and "apercu" not in reponse


@pytest.mark.parametrize("limite", [40, 500])
def test_transport_plus_bas_refuse_sans_artefact(capacites, limite):
    avec_borne = Capacites(charger_departements(Path(__file__).resolve().parents[2]), stockage.transaction,
                          filtre={"m09-strategic-intelligence"}, memoire=False, limite_sortie=limite)
    avant = _etat_metier()
    reponse = avec_borne.appeler(NOM, ARGS)
    assert reponse["ok"] is False and reponse["erreur"] == "REJ-DIAGNOSTIC-SORTIE-TROP-VOLUMINEUSE", reponse
    assert "resultat" not in reponse and "tronque" not in reponse and "apercu" not in reponse
    assert _etat_metier() == avant
