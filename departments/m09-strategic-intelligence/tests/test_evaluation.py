"""M9.23 — évaluation : corpus versionné, attentes indépendantes, second oracle, échecs conservés (fictif)."""

import copy
import json
import os
import time
from pathlib import Path

import pytest
from m9_strategic_intelligence import evaluation as ev

FICTIF = True
CORPUS = json.loads((Path(__file__).resolve().parents[1] / "evals" / "corpus-v1.json").read_text(encoding="utf-8"))


def oracle_citation(sources, sortie):
    """Second oracle NAÏF, écrit sans réutiliser le code mesuré : une citation est admise si la source existe et que sa
    valeur est identique caractère pour caractère ; tout champ inattendu ou structure douteuse refuse la sortie."""
    if not isinstance(sortie, dict) or "affirmations" not in sortie or not isinstance(sortie["affirmations"], list):
        return "REFUSE"
    if not sortie["affirmations"] or set(sortie) - {"affirmations", "demandes"}:
        return "REFUSE"
    if "demandes" in sortie and (not isinstance(sortie["demandes"], list) or len(sortie["demandes"]) > 64):
        return "REFUSE"
    vus = set()
    for a in sortie["affirmations"]:
        if not isinstance(a, dict) or a.get("id") in vus or not a.get("id"):
            return "REFUSE"
        vus.add(a["id"])
        if a.get("nature") == "hypothese" and set(a) != {"id", "nature", "enonce"}:
            return "REFUSE"
        if a.get("nature") == "observation_source":
            if set(a) != {"id", "nature", "reference", "valeur"} or not a["reference"]:
                return "REFUSE"
            if a["reference"] not in sources or sources[a["reference"]] != a["valeur"]:
                return "REFUSE"
    return "ADMIS"


def test_corpus_versionne_couvre_les_six_categories_avec_justification_et_regle():
    cas = ev.valider_corpus(CORPUS)
    couverture = ev.categories_couvertes(cas)
    assert set(couverture) == set(ev.CATEGORIES) and all(n >= 6 for n in couverture.values())
    assert len(cas) >= 60 and CORPUS["version"] == "corpus-v1"
    assert all(c["justification"].strip() and c["regle"].strip() for c in cas)


def test_toutes_les_attentes_tiennent_et_le_taux_est_rendu_avec_son_intervalle():
    rapport = ev.evaluer(CORPUS)
    echecs = {c: b["echecs"] for c, b in rapport["par_categorie"].items() if b["echecs"]}
    assert echecs == {}, echecs
    glob = rapport["global"]
    assert glob["effectif"] == len(CORPUS["cas"]) and glob["reussites"] == glob["effectif"] and glob["taux"] == "1.0000"
    bas, haut = (float(x) for x in glob["wilson95"])
    assert 0.9 < bas < 1.0 and haut == 1.0, "100 % sur 61 cas n'est pas 100 % de confiance : l'intervalle le dit"
    assert rapport["modele_reel"] is False and rapport["cout_modele"]["tokens"] == 0 and rapport["biais_connus"]
    assert len(rapport["corpus_sha256"]) == 64 and rapport["par_categorie"]["gouvernance"]["effectif"] >= 12


def test_second_oracle_naif_recoupe_les_cas_de_citation_pour_le_code_et_pour_l_attente():
    cas = [c for c in CORPUS["cas"] if c["categorie"] in ("fidelite_citation", "inference", "demandes_et_injection")]
    sans_inference = [c for c in cas if c["categorie"] != "inference"]
    assert len(sans_inference) >= 20
    for c in sans_inference:
        oracle = oracle_citation(c["entree"]["sources"], c["entree"]["sortie"])
        assert oracle == ("ADMIS" if c["attente"]["verdict"] == "ADMIS" else "REFUSE"), (
            f"{c['id']} : attente et oracle divergent"
        )
        assert ev._executer(c)["verdict"] == oracle, f"{c['id']} : code et oracle divergent"  # noqa: SLF001


def test_une_attente_fausse_ou_un_code_casse_est_un_echec_conserve_et_non_moyenne():
    faux = copy.deepcopy(CORPUS)
    faux["cas"][0]["attente"] = {"verdict": "REFUSE", "code": "REJ-CONSEIL-CITATION"}
    faux["cas"][1]["attente"] = {"verdict": "ADMIS"}
    rapport = ev.evaluer(faux)
    assert rapport["global"]["echecs_total"] == 2
    ids = {e["id"] for b in rapport["par_categorie"].values() for e in b["echecs"]}
    assert ids == {faux["cas"][0]["id"], faux["cas"][1]["id"]}
    un = next(e for b in rapport["par_categorie"].values() for e in b["echecs"] if e["id"] == faux["cas"][0]["id"])
    assert "attendu 'REFUSE'" in un["ecarts"][0] and un["regle"]
    assert float(rapport["global"]["taux"]) < 1.0


def test_reproductible_meme_corpus_meme_rapport_et_corpus_modifie_autre_empreinte():
    a, b = ev.evaluer(CORPUS), ev.evaluer(copy.deepcopy(CORPUS))
    assert a == b
    modifie = copy.deepcopy(CORPUS)
    modifie["cas"][0]["justification"] += " (modifiée)"
    assert ev.evaluer(modifie)["corpus_sha256"] != a["corpus_sha256"]


@pytest.mark.parametrize(
    "corpus",
    [
        None,
        {},
        {"cas": []},
        {"cas": [{"id": "x"}]},
        {
            "cas": [
                {
                    "id": "a",
                    "categorie": "inconnue",
                    "entree": {},
                    "attente": {"verdict": "x"},
                    "justification": "j",
                    "regle": "r",
                }
            ]
        },
    ],
)
def test_corpus_invalide_refuse(corpus):
    with pytest.raises(ValueError, match="REJ-EVAL-CORPUS"):
        ev.evaluer(corpus)


def test_wilson_bornes_et_effectif_nul():
    assert ev.wilson(0, 0) == ("0.0000", "1.0000")
    bas, haut = (float(x) for x in ev.wilson(5, 10))
    assert 0.23 < bas < 0.24 and 0.76 < haut < 0.77
    assert float(ev.wilson(10, 10)[1]) == 1.0 and float(ev.wilson(0, 10)[0]) == 0.0


def test_latence_mesuree_par_le_harnais_et_preuve_ecrite_sur_demande():
    depart = time.perf_counter()
    rapport = ev.evaluer(CORPUS)
    duree = time.perf_counter() - depart
    assert duree < 5.0, "61 cas déterministes : quelques millisecondes attendues"
    sortie = os.environ.get("M9_EVAL_SORTIE")
    if sortie:  # preuve conservée sous un nom distinct par exécution (AGENTS.md : ne jamais écraser une preuve)
        chemin = Path(sortie)
        assert not chemin.exists(), "ne jamais écraser une preuve d'évaluation antérieure"
        chemin.write_text(
            json.dumps(
                {
                    **rapport,
                    "latence_secondes_harnais": round(duree, 6),
                    "latence_par_cas_ms": round(duree / rapport["global"]["effectif"] * 1000, 3),
                },
                ensure_ascii=False,
                indent=1,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
