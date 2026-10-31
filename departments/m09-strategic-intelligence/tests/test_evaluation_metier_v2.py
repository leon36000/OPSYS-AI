"""M9.23 — harnais métier sur le corpus v2 : doubles de protocole ET pages des vrais producteurs (fictif)."""

import json
import os
import time
from pathlib import Path

import pytest
from m9_strategic_intelligence import evaluation_metier as em

FICTIF = True
EVALS = Path(__file__).resolve().parents[1] / "evals"
V1 = json.loads((EVALS / "corpus-metier-v1.json").read_text(encoding="utf-8"))
V2 = json.loads((EVALS / "corpus-metier-v2.json").read_text(encoding="utf-8"))
# Mêmes deux limites connues que v1 : aucune des 17 nouvelles attentes (écrites avant l'exécution) n'est rouge.
ROUGES_ATTENDUS = {"mkt-A07", "rep-V02"}
NOUVEAUX = {c["id"] for c in V2["cas"]} - {c["id"] for c in V1["cas"]}


def test_v1_gele_donne_toujours_58_sur_60_et_les_memes_deux_rouges_apres_le_raccordement():
    rapport = em.evaluer(V1)
    assert (rapport["global"]["reussites"], rapport["global"]["effectif"]) == (58, 60)
    assert {r["id"] for r in rapport["cas_rouges"]} == ROUGES_ATTENDUS
    assert rapport["corpus_sha256"].startswith("6faf3c0aefd1")  # le corpus v1 n'a pas été retouché


def test_v2_les_rouges_sont_exactement_les_limites_connues_et_les_nouveaux_cas_sont_verts():
    rapport = em.evaluer(V2)
    assert {r["id"] for r in rapport["cas_rouges"]} == ROUGES_ATTENDUS
    assert (rapport["global"]["reussites"], rapport["global"]["effectif"]) == (75, 77)
    assert len(NOUVEAUX) == 17 and not NOUVEAUX & {r["id"] for r in rapport["cas_rouges"]}
    assert rapport["effectifs"]["cas"] == 77 and rapport["fuites_entre_partitions"] == []
    assert rapport["par_partition"]["ajustement"]["effectif"] == 52
    assert rapport["par_partition"]["verification"]["effectif"] == 25
    assert rapport["modele_reel"] is False and rapport["verdicts_separes"]["qualification_modele_reel"] == "OUVERTE"
    bas, haut = (float(x) for x in rapport["global"]["wilson95"])
    assert 0.90 < bas < 75 / 77 < haut < 1.0


def test_les_attentes_des_nouveaux_cas_ne_sont_pas_vides_de_sens():
    """Une attente fausse rend chaque nouveau cas rouge : la verdure n'est pas un artefact du harnais."""
    for cas in V2["cas"]:
        if cas["id"] not in NOUVEAUX:
            continue
        faux = json.loads(json.dumps(cas))
        faux["attentes"] = {"invariants_violes": ["attendu impossible"]}
        assert em.evaluer_cas(faux)["ecarts"], cas["id"]


def test_la_fraicheur_declaree_par_m8_est_vue_par_le_harnais():
    resultats = {c["id"]: em.executer_cas(c) for c in V2["cas"] if c["id"].startswith("vil-") and c["id"] in NOUVEAUX}
    fraicheurs = {i: r["dossier"]["fraicheurs"]["m8.vue_executive"] for i, r in resultats.items()}
    assert fraicheurs == {
        "vil-A08": "HORS_FENETRE", "vil-A09": "DANS_LA_FENETRE", "vil-V04": "NON_EVALUEE", "vil-V05": "NON_EVALUEE",
    }  # fmt: skip


def test_preuve_v2_ecrite_sur_demande_sous_un_nom_distinct():
    sortie = os.environ.get("M9_EVAL_METIER_V2_SORTIE")
    if not sortie:
        pytest.skip("preuve non demandée (M9_EVAL_METIER_V2_SORTIE)")
    chemin = Path(sortie)
    assert not chemin.exists(), "ne jamais écraser une preuve d'évaluation antérieure"
    rapport = em.evaluer(V2, horloge=time.perf_counter)
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
