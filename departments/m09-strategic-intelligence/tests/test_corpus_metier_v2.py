"""M9.23 — corpus métier v2 : v1 gelé + pages capturées des VRAIS producteurs raccordés (fictif)."""

import copy
import json
from collections import Counter
from pathlib import Path

import jsonschema
import pytest
from m9_strategic_intelligence import charges_producteurs as cp
from m9_strategic_intelligence import evaluation_metier as em

FICTIF = True
EVALS = Path(__file__).resolve().parents[1] / "evals"
V1 = json.loads((EVALS / "corpus-metier-v1.json").read_text(encoding="utf-8"))
V2 = json.loads((EVALS / "corpus-metier-v2.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((EVALS / "corpus-metier-v2.schema.json").read_text(encoding="utf-8"))
REMPLACES = {"mkt-A01", "mkt-A03", "lea-A02"}  # fixtures simulées remplacées par un vrai contrat, attentes inchangées
FALSIFIE = "lea-V05"  # page réelle falsifiée à la main (unité) pour sonder le garde-fou
NOUVEAUX = {
    "mkt-A08", "mkt-A09", "mkt-A10", "mkt-V04", "mkt-V05", "lea-A09", "lea-A10", "lea-V04", "lea-V05",
    "rep-A07", "rep-A08", "rep-A09", "rep-V04", "vil-A08", "vil-A09", "vil-V04", "vil-V05",
}  # fmt: skip
CONTRATS = {"m4.capacite_equipe", "m7.depenses_marketing", "m1.plaintes_structurees"}


def _par_id(corpus):
    return {c["id"]: c for c in corpus["cas"]}


def test_le_schema_v2_est_valide_et_le_corpus_le_respecte():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(V2)) == []
    assert V2["version"] == "corpus-metier-v2" and V1["version"] == "corpus-metier-v1"


def test_v1_reste_gele_et_v2_le_contient_sauf_trois_fixtures_remplacees_aux_attentes_inchangees():
    v1, v2 = _par_id(V1), _par_id(V2)
    assert set(v1) <= set(v2) and set(v2) - set(v1) == NOUVEAUX and len(V2["cas"]) == 77
    for identifiant, cas in v1.items():
        assert v2[identifiant]["attentes"] == cas["attentes"], f"{identifiant} : attentes modifiées"
        if identifiant not in REMPLACES:
            assert v2[identifiant] == cas, f"{identifiant} : cas v1 modifié"
        else:
            assert v2[identifiant]["entree"] != cas["entree"] and "[v2]" in v2[identifiant]["justification"]


def test_les_cas_remplaces_lisent_le_vrai_contrat_et_plus_le_champ_simule():
    v2 = _par_id(V2)
    lectures = {s["lecture"] for s in v2["lea-A02"]["entree"]["captures"]}
    assert lectures == {"m4.capacite_equipe"}
    for identifiant in ("mkt-A01", "mkt-A03"):
        assert "m7.depenses_marketing" in {s["lecture"] for s in v2[identifiant]["entree"]["captures"]}
        assert "DEPENSES_NON_BRANCHEES" not in json.dumps(v2[identifiant]["double_protocole"])


def test_effectifs_partitions_disjointes_et_perturbations_couvertes_dans_les_deux():
    effectifs = Counter(c["partition"] for c in V2["cas"])
    assert effectifs == {"ajustement": 52, "verification": 25}
    assert em.fuites_entre_partitions(V2) == []
    for partition in ("ajustement", "verification"):
        vues = {p for c in V2["cas"] if c["partition"] == partition for p in c["perturbations"]}
        assert vues == set(em.PERTURBATIONS)
    ids = [c["id"] for c in V2["cas"]]
    assert len(ids) == len(set(ids))


def test_contrats_reels_et_simules_sont_nommes_et_les_producteurs_publies_ne_sont_plus_absents():
    reels = " ".join(V2["contrats_reels"])
    for nom in (*CONTRATS, "m8.vue_executive"):
        assert nom in reels, nom
    assert "sans ingestion/saisie réelle" in reels and "NON CALCULABLE pour les semaines non datées" in reels
    absents = " ".join(V2["producteurs_absents"])
    assert not [nom for nom in CONTRATS if nom in absents]
    simules = " ".join(V2["contrats_simules"])
    for nom in ("m7.performance_campagnes", "m1.digest", "capacite_jours_personnes", "cout_ouverture_ville"):
        assert nom in simules, nom


def _pages_de_contrat(corpus):
    for cas in corpus["cas"]:
        if cas["chemin"] in ("conseil", "priorisation"):
            for capture in cas["entree"].get("captures", []):
                if capture["lecture"] in CONTRATS:
                    yield cas["id"], capture


def test_chaque_page_de_contrat_du_corpus_est_conforme_au_contrat_sauf_la_page_falsifiee():
    vues = 0
    for identifiant, capture in _pages_de_contrat(V2):
        erreurs = cp.valider(capture["lecture"], capture["pages"][0], capture.get("arguments"))
        assert bool(erreurs) == (identifiant == FALSIFIE), (identifiant, erreurs)
        vues += 1
    assert vues >= 15


def test_donnees_fictives_aucune_adresse_ni_telephone_ni_consigne_executable():
    texte = json.dumps(V2, ensure_ascii=False)
    assert "@" not in texte and "http" not in texte
    # Les pages M1 du corpus ne portent aucun numéro ni texte de client (Loi 25), même celles tirées d'un registre réel.
    for identifiant, capture in _pages_de_contrat(V2):
        if capture["lecture"] == "m1.plaintes_structurees":
            assert "555" not in json.dumps(capture["pages"]), identifiant


@pytest.mark.parametrize("cle", ["contrats_reels", "version"])
def test_le_schema_v2_refuse_un_corpus_degrade(cle):
    degrade = copy.deepcopy(V2)
    degrade.pop(cle)
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(degrade))
