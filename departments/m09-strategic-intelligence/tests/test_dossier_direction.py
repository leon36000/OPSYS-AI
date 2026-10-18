"""Dossier préparatoire : consommation réelle, données exclusivement fictives."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from m9_strategic_intelligence import encodage, registre
from m9_strategic_intelligence import outils as module
from sqlalchemy import select

from opsys import contexte, identite, jetons, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import APPROBATIONS, ARTEFACTS, EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
NOM = "m9_preparer_dossier_direction"
QUESTION = "Quels faits reçus éclairent la préparation des chantiers fictifs ?"
ATTENDUS = ["M5-fictif", "M8-fictif", "M6-fictif"]


@pytest.fixture
def capacites(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'dossier-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    departements = charger_departements(Path(__file__).resolve().parents[2])
    yield Capacites(departements, stockage.transaction, filtre={"m09-strategic-intelligence"}, memoire=False)
    stockage.liberer()


def _ingerer(capacites, source="M5-fictif", heure="2026-10-18T07:00:00Z", valeur="équipe A fictive"):
    # Préparation fictive via le vrai adaptateur transactionnel ; la lecture testée passe
    # ensuite par Capacites. Aucun contournement de politique dans le produit.
    outil = next(o for o in module.outils() if o.nom == "m9_etat_consolide")
    reponse = executer_atomique(outil, {"snapshot": {
        "module_source": source, "horodatage": heure, "valeurs": {"chantier_fictif": valeur},
    }})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _dossier(capacites, **arguments):
    reponse = capacites.appeler(NOM, {"question": QUESTION, "modules_attendus": ATTENDUS, **arguments})
    assert reponse["ok"] is True, reponse
    assert "tronque" not in reponse and "apercu" not in reponse
    assert len(json.dumps(reponse, ensure_ascii=False)) <= jetons.LIMITE_SORTIE_DEFAUT
    return reponse["resultat"]


def _etat_metier():
    with stockage.transaction() as cnx:
        return {table.name: list(cnx.execute(select(table)).mappings())
                for table in (REGISTRES, APPROBATIONS, EVENEMENTS_SORTANTS, EVENEMENTS_RECUS)}


def test_temoin_socle_et_imports_du_checkout_isole(capacites):
    racine = Path(__file__).resolve().parents[3]
    assert Path(module.__file__).resolve().is_relative_to(racine)
    assert Path(stockage.__file__).resolve().is_relative_to(racine)
    _ingerer(capacites)
    etat = capacites.appeler("m9_lire_etat_consolide", {})
    assert etat["ok"] is True and set(etat["resultat"]["faits_par_module"]) == {"M5-fictif"}


def test_dossier_sans_invention_preserve_faits_et_source(capacites):
    _ingerer(capacites)
    _ingerer(capacites, "M8-fictif", valeur="retard fictif déclaré")
    avant = capacites.appeler("m9_lire_etat_consolide", {})["resultat"]
    source = deepcopy(list(stockage.maillons("m09-strategic-intelligence", "snapshots")))
    etat_metier = _etat_metier()

    dossier = _dossier(capacites)

    assert set(dossier) == {
        "type", "question", "dossier_id", "modules_attendus", "etat_id", "statut_preparation",
        "actualite", "faits_selectionnes", "contradictions", "preuves", "modules_manquants", "limites",
    }
    assert dossier["type"] == "DOSSIER_PREPARATOIRE_DIRECTION"
    assert dossier["question"] == QUESTION and dossier["modules_attendus"] == ATTENDUS
    assert dossier["etat_id"] == avant["etat_id"]
    assert dossier["faits_selectionnes"] == avant["faits_par_module"]
    assert dossier["preuves"] == source and dossier["contradictions"] == []
    assert dossier["modules_manquants"] == ["M6-fictif"]
    assert dossier["statut_preparation"] == "NON_VALIDE" and dossier["actualite"] == "NON_EVALUEE"
    assert dossier["limites"]
    assert list(stockage.maillons("m09-strategic-intelligence", "snapshots")) == source
    assert capacites.appeler("m9_lire_etat_consolide", {})["resultat"] == avant
    assert _etat_metier() == etat_metier  # journal d'invocation du socle autorisé séparément


def test_contradiction_cite_aussi_variante_non_selectionnee(capacites):
    _ingerer(capacites, heure="2026-10-18T03:00:00-04:00", valeur="équipe A fictive")
    _ingerer(capacites, heure="2026-10-18T07:00:00Z", valeur="équipe B fictive")
    etat = capacites.appeler("m9_lire_etat_consolide", {})["resultat"]
    source = list(stockage.maillons("m09-strategic-intelligence", "snapshots"))

    dossier = _dossier(capacites)

    assert dossier["faits_selectionnes"] == etat["faits_par_module"]
    assert dossier["contradictions"] == etat["contradictions"]
    assert dossier["preuves"] == source and len(dossier["preuves"]) == 2
    assert dossier["faits_selectionnes"]["M5-fictif"]["index"] == 1
    assert dossier["preuves"][0]["valeurs"] != dossier["preuves"][1]["valeurs"]
    assert dossier["actualite"] == "NON_EVALUEE" and dossier["statut_preparation"] == "NON_VALIDE"


def _registre(valeur="équipe fictive", heure="2026-10-18T07:00:00Z"):
    cible = registre.RegistreSnapshots()
    cible.ajouter({"module_source": "M5-fictif", "horodatage": heure, "valeurs": {"chantier_fictif": valeur}})
    return cible


def _outil(cible):
    outils = {o.nom: o for o in module.outils(registre_cible=cible, alertes_cible=[])}
    assert NOM in outils, "outil de dossier absent"
    return outils[NOM]


def _appeler(cible, **arguments):
    return executer_atomique(_outil(cible), {"question": QUESTION, "modules_attendus": ATTENDUS, **arguments})


def test_une_capture_unique_meme_si_la_source_change(capacites):
    avant = _registre().lire()
    class SourceChangeante:
        lectures = 0

        def lire(self):
            self.lectures += 1
            assert self.lectures == 1, "seconde capture durable interdite"
            return deepcopy(avant)

    cible = SourceChangeante()
    reponse = _appeler(cible)
    assert reponse["ok"] is True, reponse
    assert cible.lectures == 1 and reponse["resultat"]["preuves"] == avant
    assert reponse["resultat"]["faits_selectionnes"]["M5-fictif"] == avant[0]


@pytest.mark.parametrize("question,modules", [
    ("", ATTENDUS), ("  ", ATTENDUS), (None, ATTENDUS), ("x" * 2049, ATTENDUS),
    (QUESTION, []), (QUESTION, ["M5-fictif"] * 2), (QUESTION, [""]),
    (QUESTION, ["  "]), (QUESTION, [True]), (QUESTION, ["x" * 129]),
    (QUESTION, [str(i) for i in range(17)]), (QUESTION, "M5-fictif"),
])
def test_entrees_invalides_refusees(capacites, question, modules):
    reponse = _appeler(_registre(), question=question, modules_attendus=modules)
    assert reponse["ok"] is False and reponse["erreur"] in {"refus_metier", "arguments_invalides"}, reponse
    assert "resultat" not in reponse


def test_chaine_rompue_refusee_sans_reparation(capacites):
    lignes = _registre().lire()
    lignes[0]["valeurs"]["chantier_fictif"] = "altération fictive"
    avant = deepcopy(lignes)
    reponse = _appeler(registre.RegistreSnapshots(lignes))
    assert reponse["ok"] is False and reponse["details"].startswith("REJ-SNAPSHOT-CHAINE-INVALIDE")
    assert lignes == avant


@pytest.mark.parametrize("ambigu", [False, True])
def test_reference_ambiguë_meme_dans_chaine_valide(capacites, ambigu):
    cible = _registre(heure="2026-10-18T03:00:00-04:00")
    cible.ajouter({"module_source": "M5-fictif", "horodatage": "2026-10-18T07:00:00Z",
                   "valeurs": {"chantier_fictif": "autre équipe fictive"}})
    lignes = cible.lire()
    if ambigu:
        lignes[1]["index"] = 0
        lignes[1]["hash_maillon"] = encodage.empreinte(
            0, lignes[1]["module_source"], lignes[1]["horodatage"], lignes[1]["valeurs"], lignes[1]["hash_precedent"],
        )
    cible = registre.RegistreSnapshots(lignes)
    assert cible.valider_chaine() == (True, "")  # vrai validateur, pas un mock
    avant = deepcopy(lignes)
    reponse = _appeler(cible)
    if ambigu:
        assert reponse["ok"] is False and reponse["details"].startswith("REJ-DOSSIER-REFERENCE"), reponse
        assert "resultat" not in reponse
    else:
        assert reponse["ok"] is True and reponse["resultat"]["preuves"] == lignes
    assert lignes == avant


def test_reference_absente_refusee_sans_substitution(capacites, monkeypatch):
    original = module.etat_consolide_module.construire_etat_consolide
    def reference_absente(copie):
        etat = original(copie)
        etat["contradictions"] = [{"ligne_id_a": 0, "ligne_id_b": 99}]
        return etat
    monkeypatch.setattr(module.etat_consolide_module, "construire_etat_consolide", reference_absente)
    reponse = _appeler(_registre())
    assert reponse["ok"] is False and reponse["details"].startswith("REJ-DOSSIER-REFERENCE"), reponse


@pytest.mark.parametrize("heure", ["pas-un-instant", "2026-20-45T07:00:00Z"])
def test_horodatage_invalide_refuse(capacites, heure):
    reponse = _appeler(_registre(heure=heure))
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier", reponse


def test_trop_de_preuves_refus_explicite_jamais_troncature(capacites):
    reponse = _appeler(_registre(valeur="preuve fictive " * 500))
    assert reponse["ok"] is False and reponse["details"].startswith("REJ-DOSSIER-BORNE"), reponse
    assert "resultat" not in reponse and "tronque" not in reponse


def test_identite_stable_sensible_a_question_sources_et_perimetre(capacites):
    cible = _registre()
    dossier = _appeler(cible)["resultat"]
    assert _appeler(cible)["resultat"] == dossier
    contenu = {k: v for k, v in dossier.items() if k != "dossier_id"}
    assert dossier["dossier_id"] == hashlib.sha256(json.dumps(
        contenu, sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    assert _appeler(cible, question="Autre question fictive ?")["resultat"]["dossier_id"] != dossier["dossier_id"]
    assert _appeler(cible, modules_attendus=["M5-fictif"])["resultat"]["dossier_id"] != dossier["dossier_id"]
    assert _appeler(_registre(valeur="autre fait fictif"))["resultat"]["dossier_id"] != dossier["dossier_id"]


@pytest.mark.parametrize("role", ["employee", "seller", "client"])
def test_appareil_sans_admin_refuse_avant_capture(capacites, role):
    class SourceFermee:
        def lire(self):
            pytest.fail("capture avant garde admin")
    outil = _outil(SourceFermee())
    assert outil.roles_appareil == frozenset({"admin"})
    with contexte.appele_par_appareil(IdentiteAppelante("personne-fictive", role)):
        reponse = executer_atomique(outil, {"question": QUESTION, "modules_attendus": ATTENDUS})
    assert reponse["ok"] is False and reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE"), reponse


@pytest.mark.parametrize("actif", [True, False])
def test_admin_sql_courant_requis(capacites, monkeypatch, actif):
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "hachage-fictif-non-authentifiable")
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin-fictif", "admin fictif", "fictif", ["admin"], actif=actif)
    with contexte.appele_par_appareil(IdentiteAppelante("admin-fictif", "admin")):
        reponse = _appeler(_registre())
    assert reponse["ok"] is actif, reponse
    if not actif:
        assert reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")


def test_registre_vide_n_invente_pas_de_couverture(capacites):
    dossier = _appeler(registre.RegistreSnapshots(), question="  Question fictive exacte ?  ")["resultat"]
    assert dossier["question"] == "  Question fictive exacte ?  "
    assert dossier["faits_selectionnes"] == {} and dossier["preuves"] == []
    assert dossier["modules_manquants"] == sorted(ATTENDUS)
    assert dossier["actualite"] == "NON_EVALUEE" and dossier["statut_preparation"] == "NON_VALIDE"


@pytest.mark.parametrize("limite", [40, 500])
def test_transport_plus_bas_refuse_sans_artefact(capacites, limite):
    _ingerer(capacites)
    avec_borne = Capacites(charger_departements(Path(__file__).resolve().parents[2]), stockage.transaction,
                          filtre={"m09-strategic-intelligence"}, memoire=False, limite_sortie=limite)
    with stockage.transaction() as cnx:
        artefacts_avant = list(cnx.execute(select(ARTEFACTS)).mappings())
    reponse = avec_borne.appeler(NOM, {"question": QUESTION, "modules_attendus": ATTENDUS})
    assert reponse["ok"] is False and reponse["erreur"] == "REJ-DOSSIER-SORTIE-TROP-VOLUMINEUSE", reponse
    assert "tronque" not in reponse and "apercu" not in reponse and "resultat" not in reponse
    with stockage.transaction() as cnx:
        assert list(cnx.execute(select(ARTEFACTS)).mappings()) == artefacts_avant


def test_contradiction_historique_reste_citee_apres_fait_plus_recent(capacites):
    _ingerer(capacites, heure="2026-10-18T03:00:00-04:00", valeur="A fictif")
    _ingerer(capacites, heure="2026-10-18T07:00:00Z", valeur="B fictif")
    _ingerer(capacites, heure="2026-10-18T08:00:00Z", valeur="C fictif")
    dossier = _dossier(capacites)
    assert dossier["faits_selectionnes"]["M5-fictif"]["index"] == 2
    assert [p["index"] for p in dossier["preuves"]] == [0, 1, 2]
    assert [(c["ligne_id_a"], c["ligne_id_b"]) for c in dossier["contradictions"]] == [(0, 1)]


@pytest.mark.parametrize("valeurs", [{1: "clé numérique fictive"}, {"champ_fictif": ("tuple fictif",)}])
def test_source_qui_changerait_de_type_json_refusee_sans_fausse_preuve(capacites, valeurs):
    # Source frontière synthétique, réellement hashée : le codec durable refuse déjà
    # les clés non textuelles et l'ingestion ordinaire exige des valeurs textuelles.
    cible = registre.RegistreSnapshots()
    cible.ajouter({"module_source": "M5-fictif", "horodatage": "2026-10-18T07:00:00Z", "valeurs": valeurs})
    assert cible.valider_chaine() == (True, "")
    avant = cible.lire()
    reponse = _appeler(cible)
    assert reponse["ok"] is False and reponse["details"].startswith("REJ-DOSSIER-SERIALISATION"), reponse
    assert "resultat" not in reponse and cible.lire() == avant
