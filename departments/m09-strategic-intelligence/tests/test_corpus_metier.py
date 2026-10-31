"""M9.23 — corpus métier versionné : schéma, couverture, partitions disjointes (fictif)."""

import copy
import json
from collections import Counter
from pathlib import Path

import jsonschema
import pytest

FICTIF = True
EVALS = Path(__file__).resolve().parents[1] / "evals"
CORPUS = json.loads((EVALS / "corpus-metier-v1.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((EVALS / "corpus-metier-v1.schema.json").read_text(encoding="utf-8"))
FAMILLES = {
    "dir": "rapport_direction",
    "mkt": "budget_marketing",
    "tre": "tresorerie_serree",
    "lea": "leads_hors_capacite",
    "vil": "nouvelle_ville",
    "rep": "reputation",
}
PERTURBATIONS = {"nominal", "absence", "tardive", "contradiction", "perimee", "unite_date", "homonyme", "injection"}


def _erreurs(corpus):
    return list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(corpus))


def test_le_schema_est_valide_et_le_corpus_le_respecte():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert _erreurs(CORPUS) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.pop("fictif"),
        lambda c: c.update(fictif=False),
        lambda c: c["cas"][0].update(famille="autre"),
        lambda c: c["cas"][0].update(partition="entrainement"),
        lambda c: c["cas"][0].update(supplement=1),
        lambda c: c["cas"][0]["perturbations"].append("inconnue"),
        lambda c: c["cas"][0].pop("regle"),
        lambda c: c["cas"][0].update(attentes={}),
        lambda c: c.pop("contrats_simules"),
        lambda c: c["double_protocole"].update(statut="MODELE_REEL"),
        lambda c: next(x for x in c["cas"] if x["chemin"] == "conseil").pop("double_protocole"),
        lambda c: next(x for x in c["cas"] if x["chemin"] == "conseil")["entree"].pop("captures"),
        lambda c: next(x for x in c["cas"] if x["chemin"] == "priorisation")["entree"].pop("candidats"),
        lambda c: next(x for x in c["cas"] if x["chemin"] == "occasions")["entree"].pop("occasions"),
    ],
)
def test_le_schema_refuse_un_corpus_degrade(mutation):
    degrade = copy.deepcopy(CORPUS)
    mutation(degrade)
    assert _erreurs(degrade), "la mutation doit être rejetée par le schéma"


def test_six_familles_et_deux_partitions_avec_un_effectif_minimal():
    effectifs = Counter((c["famille"], c["partition"]) for c in CORPUS["cas"])
    for famille in FAMILLES.values():
        assert effectifs[(famille, "ajustement")] >= 6, famille
        assert effectifs[(famille, "verification")] >= 3, famille
    assert len(CORPUS["cas"]) >= 60


def test_chaque_perturbation_est_couverte_dans_les_deux_partitions():
    for partition in ("ajustement", "verification"):
        vues = {p for c in CORPUS["cas"] if c["partition"] == partition for p in c["perturbations"]}
        assert vues == PERTURBATIONS, (partition, PERTURBATIONS - vues)


def test_identifiants_uniques_prefixe_famille_et_lettre_de_partition_coherents():
    ids = [c["id"] for c in CORPUS["cas"]]
    assert len(ids) == len(set(ids))
    for c in CORPUS["cas"]:
        prefixe, suffixe = c["id"].split("-")
        assert FAMILLES[prefixe] == c["famille"], c["id"]
        assert {"A": "ajustement", "V": "verification"}[suffixe[0]] == c["partition"], c["id"]


def test_les_partitions_sont_disjointes_sur_les_identifiants_les_entrees_et_les_sorties_figees():
    a = [c for c in CORPUS["cas"] if c["partition"] == "ajustement"]
    v = [c for c in CORPUS["cas"] if c["partition"] == "verification"]
    assert {c["id"] for c in a}.isdisjoint({c["id"] for c in v})

    def cle(c):
        return json.dumps([c["chemin"], c["entree"]], sort_keys=True)

    assert {cle(c) for c in a}.isdisjoint({cle(c) for c in v})
    doubles_a = {json.dumps(c["double_protocole"], sort_keys=True) for c in a if c.get("double_protocole")}
    doubles_v = {json.dumps(c["double_protocole"], sort_keys=True) for c in v if c.get("double_protocole")}
    assert doubles_a.isdisjoint(doubles_v)


def test_contrats_simules_et_producteurs_absents_sont_nommes_et_les_rouges_connus_justifies():
    texte = " ".join(CORPUS["contrats_simules"])
    for nom in ("m7.performance_campagnes", "m1.digest", "m4.cedule_semaine", "m8.vue_executive"):
        assert nom in texte, nom
    absents = " ".join(CORPUS["producteurs_absents"])
    for nom in ("m4.capacite_equipe", "m7.depenses_marketing", "m1.plaintes_structurees"):
        assert nom in absents, nom
    assert CORPUS["double_protocole"]["statut"] == "DOUBLE_DE_PROTOCOLE_REDIGE_A_LA_MAIN"
    for c in CORPUS["cas"]:
        assert c["regle"].strip() and c["scenario"].strip() and c["justification"].strip()
        if "rouge_connu" in c:
            assert c["rouge_connu"]["raison"].strip() and c["rouge_connu"]["proposition"].strip()


def test_donnees_fictives_aucune_adresse_ni_telephone():
    texte = json.dumps(CORPUS, ensure_ascii=False)
    assert "@" not in texte and "http" not in texte
