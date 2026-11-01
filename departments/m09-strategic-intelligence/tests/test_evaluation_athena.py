"""Athéna : corpus d'évaluation ``corpus-athena-v1.json`` (nouveau fichier). Attentes écrites à la main, échecs
conservés,
empreinte scellée dans le gabarit commun, les trois corpus existants intacts (fictif)."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from m9_strategic_intelligence import evaluation_athena as ea

FICTIF = True
EVALS = Path(__file__).resolve().parents[1] / "evals"
CORPUS = json.loads((EVALS / "corpus-athena-v1.json").read_text(encoding="utf-8"))
EMPREINTES_GELEES = {
    "corpus-v1.json": "3c24182c883f3c4335ea4c1615932b9426c95a53f5313accadeb41a080630c51",
    "corpus-metier-v1.json": "c556193afe8c61236828ed48a3145e7773c0087dc2afe3512800102713aed37f",
    "corpus-metier-v2.json": "bc10a610052b00ac3fb86d6a832ef34cac8f9c236bbbcbf5bb8040b421c6bb40",
}


def test_les_trois_corpus_existants_gardent_leurs_empreintes():
    for nom, attendue in EMPREINTES_GELEES.items():
        assert hashlib.sha256((EVALS / nom).read_bytes()).hexdigest() == attendue, nom


def test_le_nouveau_fichier_est_scelle_dans_le_gabarit_commun():
    gabarit = yaml.safe_load((EVALS / "gabarit.v1.yaml").read_text(encoding="utf-8"))
    refs = {r["chemin"]: r for r in gabarit["references"]}
    ref = refs["evals/corpus-athena-v1.json"]
    assert ref["sha256"] == hashlib.sha256((EVALS / "corpus-athena-v1.json").read_bytes()).hexdigest()
    assert ref["executeur"] == "m9_strategic_intelligence.evaluation_athena:evaluer"
    assert set(EMPREINTES_GELEES) == {Path(c).name for c in refs} - {"corpus-athena-v1.json"}


def test_le_corpus_couvre_les_six_categories_avec_justification_et_regle():
    cas = ea.valider_corpus(CORPUS)
    effectifs: dict[str, int] = {}
    for c in cas:
        effectifs[c["categorie"]] = effectifs.get(c["categorie"], 0) + 1
    assert set(effectifs) == set(ea.CATEGORIES) and all(n >= 3 for n in effectifs.values())
    assert effectifs["recommandation"] >= 20 and effectifs["contrat_charge"] >= 15 and len(cas) >= 60
    assert all(c["justification"].strip() and c["regle"].strip() for c in cas)
    assert len({c["id"] for c in cas}) == len(cas)


def test_toutes_les_attentes_tiennent_et_le_taux_est_rendu_avec_son_intervalle():
    rapport = ea.evaluer(CORPUS)
    echecs = {c: b["echecs"] for c, b in rapport["par_categorie"].items() if b["echecs"]}
    assert echecs == {}, echecs
    glob = rapport["global"]
    assert glob["effectif"] == len(CORPUS["cas"]) and glob["taux"] == "1.0000"
    bas, haut = (float(x) for x in glob["wilson95"])
    assert 0.9 < bas < 1.0 and haut == 1.0, "100 % sur 66 cas n'est pas 100 % de confiance : l'intervalle le dit"
    assert rapport["modele_reel"] is False and rapport["cout_modele"]["tokens"] == 0 and rapport["biais_connus"]
    assert any("réel" in limite for limite in rapport["limites"])


def _cas(id_):
    return next(c for c in CORPUS["cas"] if c["id"] == id_)


def _avec(cas_modifies):
    return {**CORPUS, "cas": cas_modifies}


@pytest.mark.parametrize(
    ("id_", "mutation"),
    [
        ("cc-m8-faux-score", lambda c: c["attente"].update(verdict="CONFORME")),
        ("tb-sante-essai", lambda c: c["attente"].update(verdict="ETABLI")),
        ("rg-essai-presente-etabli", lambda c: c["attente"].update(verdict="ADMIS")),
        ("bc-mesure-perimee", lambda c: c["attente"].update(verdict="CONCORDE")),
        ("pr-niveau-puis-age", lambda c: c["attente"]["extra"].update(ids=["b", "a", "e", "d"])),
    ],
)
def test_une_attente_fausse_est_detectee_et_l_echec_est_conserve_avec_l_attendu_et_l_observe(id_, mutation):
    cas = copy.deepcopy(_cas(id_))
    mutation(cas)
    rapport = ea.evaluer(_avec([cas]))
    echecs = [e for b in rapport["par_categorie"].values() for e in b["echecs"]]
    assert [e["id"] for e in echecs] == [id_] and echecs[0]["ecarts"] and echecs[0]["regle"]
    assert rapport["global"]["echecs_total"] == 1 and rapport["global"]["taux"] == "0.0000"


def test_un_corpus_hors_forme_est_refuse_nommement():
    for mauvais in ({}, {"cas": []}, {"cas": [{"id": "x"}]}, {"cas": [{**_cas("pr-identifiant-departage"),
        "categorie": "autre"}]}):
        with pytest.raises(ValueError, match="REJ-EVAL-CORPUS"):
            ea.valider_corpus(mauvais)
    doublon = [_cas("pr-identifiant-departage")] * 2
    with pytest.raises(ValueError, match="REJ-EVAL-CORPUS"):
        ea.valider_corpus({"cas": doublon})
    sans_justification = {**_cas("pr-identifiant-departage"), "justification": " "}
    with pytest.raises(ValueError, match="REJ-EVAL-CORPUS"):
        ea.valider_corpus({"cas": [sans_justification]})


def test_le_rapport_est_deterministe_et_porte_l_empreinte_du_corpus():
    a, b = ea.evaluer(CORPUS), ea.evaluer(copy.deepcopy(CORPUS))
    assert a == b and len(a["corpus_sha256"]) == 64
    assert ea.evaluer(_avec(CORPUS["cas"][:-1]))["corpus_sha256"] != a["corpus_sha256"]
