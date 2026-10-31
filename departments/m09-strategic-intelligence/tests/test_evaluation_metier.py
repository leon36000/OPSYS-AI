"""M9.23 — harnais métier : vrais chemins M9, doubles de protocole, cas rouges conservés (fictif)."""

import ast
import copy
import json
import os
import re
import time
from datetime import date
from pathlib import Path

import pytest
from m9_strategic_intelligence import evaluation_metier as em

FICTIF = True
M9 = Path(__file__).resolve().parents[1]
CORPUS = json.loads((M9 / "evals" / "corpus-metier-v1.json").read_text(encoding="utf-8"))
SOURCE = M9 / "src" / "m9_strategic_intelligence" / "evaluation_metier.py"
# État APRÈS les deux corrections (mêmes entrées figées) : ne restent que les deux limites connues déclarées dans le
# corpus (avant correction : 7 rouges, voir preuves-evaluation-metier/EVAL-METIER-avant-correction-*.json).
ROUGES_ATTENDUS = {
    "mkt-A07",  # limite connue : type d'action déclaré par le modèle
    "rep-V02",  # limite connue : entier nu en texte libre
}


def _rouges(rapport):
    return {r["id"] for r in rapport["cas_rouges"]}


def test_le_corpus_est_valide_et_sans_fuite_entre_partitions():
    assert len(em.valider_corpus_metier(CORPUS)) == 60
    assert em.fuites_entre_partitions(CORPUS) == []


def test_une_fuite_de_l_ajustement_vers_la_verification_est_detectee():
    triche = copy.deepcopy(CORPUS)
    source = next(c for c in triche["cas"] if c["id"] == "tre-A01")
    copie = copy.deepcopy(source) | {"id": "tre-V09", "partition": "verification"}
    triche["cas"].append(copie)
    assert any("entrée identique" in f for f in em.fuites_entre_partitions(triche))
    meme_id = copy.deepcopy(CORPUS)
    meme_id["cas"][-1]["partition"] = "ajustement"
    meme_id["cas"][0]["id"] = meme_id["cas"][-1]["id"]
    with pytest.raises(ValueError, match="REJ-EVALMETIER-CORPUS"):
        em.fuites_entre_partitions(meme_id)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.pop("fictif"),
        lambda c: c.pop("contrats_simules"),
        lambda c: c["cas"][0].update(famille="autre"),
        lambda c: c["cas"][0].update(chemin="inconnu"),
        lambda c: c["cas"][0].update(perturbations=[]),
        lambda c: c["cas"][1].update(id=c["cas"][0]["id"]),
    ],
)
def test_corpus_degrade_refuse(mutation):
    degrade = copy.deepcopy(CORPUS)
    mutation(degrade)
    with pytest.raises(ValueError, match="REJ-EVALMETIER-CORPUS"):
        em.valider_corpus_metier(degrade)


def test_sceaux_de_partition_stables_et_sensibles_a_toute_retouche():
    avant = em.evaluer(CORPUS)["sceaux_partitions"]
    modifie = copy.deepcopy(CORPUS)
    cas_v = next(c for c in modifie["cas"] if c["partition"] == "verification")
    cas_v["justification"] += " (retouchée)"
    apres = em.evaluer(modifie)["sceaux_partitions"]
    assert apres["ajustement"] == avant["ajustement"] and apres["verification"] != avant["verification"]


def test_rapport_reproductible_effectifs_wilson_et_verdicts_separes():
    a, b = em.evaluer(CORPUS), em.evaluer(copy.deepcopy(CORPUS))
    assert a == b
    assert a["modele_reel"] is False and a["effectifs"]["cas"] == 60
    assert a["verdicts_separes"]["qualification_modele_reel"] == "OUVERTE"
    assert a["verdicts_separes"]["execution_core_native"] == "OUVERTE"
    assert a["verdicts_separes"]["qualite_metier_conseil"] == "NON_ETABLIE"
    assert a["mesures_modele"] == {
        "latence": "UNKNOWN",
        "tokens": "UNKNOWN",
        "cout": "UNKNOWN",
        "raison": "aucun modèle appelé : sorties figées",
    }
    par_famille = a["effectifs"]["par_famille_partition"]
    assert set(par_famille) == set(em.FAMILLES)
    assert sum(sum(v.values()) for v in par_famille.values()) == 60
    glob = a["global"]
    assert glob["effectif"] == 60 and glob["reussites"] + len(a["cas_rouges"]) == 60
    bas, haut = (float(x) for x in glob["wilson95"])
    assert 0.0 < bas < float(glob["taux"]) < haut < 1.0
    assert a["biais_connus"] and a["limites"] and a["fuites_entre_partitions"] == []


def test_les_cas_rouges_sont_exactement_ceux_attendus_et_jamais_moyennes():
    rapport = em.evaluer(CORPUS)
    assert _rouges(rapport) == ROUGES_ATTENDUS
    assert all(r["ecarts"] for r in rapport["cas_rouges"])
    declares = {c["id"] for c in CORPUS["cas"] if "rouge_connu" in c}
    assert declares == {"mkt-A07", "rep-V02"} and declares <= _rouges(rapport)
    par_partition = rapport["par_partition"]
    assert par_partition["ajustement"]["effectif"] == 42 and par_partition["verification"]["effectif"] == 18
    assert {r["id"] for r in par_partition["verification"]["rouges"]} == {"rep-V02"}
    seule = em.evaluer(CORPUS, partition="verification")
    assert seule["partition_evaluee"] == "verification" and seule["effectifs"]["cas"] == 18
    assert _rouges(seule) == {"rep-V02"}


def test_latence_du_harnais_est_unknown_sans_horloge_injectee_et_mesuree_avec():
    assert em.evaluer(CORPUS)["latence_harnais_secondes"] == "UNKNOWN"
    mesuree = em.evaluer(CORPUS, horloge=time.perf_counter)["latence_harnais_secondes"]
    assert isinstance(mesuree, float) and 0.0 <= mesuree < 30.0


def test_mesures_conseil_abstentions_et_refus_avec_intervalles():
    conseil = em.evaluer(CORPUS)["conseil"]
    assert conseil["sessions"] == 29
    for cle in ("abstention_attendue", "abstention_observee", "depots_refuses"):
        assert {"k", "n", "taux", "wilson95"} <= set(conseil[cle])
    assert conseil["abstention_attendue"]["k"] == 2 and conseil["abstention_observee"]["k"] == 2
    assert conseil["depots_refuses"]["n"] > 0
    assert set(conseil["par_famille"]) == {
        "budget_marketing",
        "leads_hors_capacite",
        "nouvelle_ville",
        "reputation",
        "tresorerie_serree",
    }


def test_une_attente_fausse_rend_le_cas_rouge_pour_chaque_chemin():
    attentes_fausses = {
        "conseil": {"cloture": {"issue": "ABSTENTION"}},
        "direction": {"audit": {"issue": "REFUSE", "code": "REJ-AUDIT-FAUX"}},
        "previsions": {"domaines": {"tresorerie": {"statut": "PERIMEE"}}},
        "priorisation": {"retenus": ["zzz"]},
        "occasions": {"radar": {"issue": "REFUSE", "code": "REJ-FAUX"}},
    }
    for chemin, fausse in attentes_fausses.items():
        cas = copy.deepcopy(next(c for c in CORPUS["cas"] if c["chemin"] == chemin and c["id"] not in ROUGES_ATTENDUS))
        cas["attentes"] = fausse
        resultat = em.evaluer_cas(cas)
        assert resultat["ecarts"], chemin


def test_l_oracle_de_montants_libres_distingue_citation_et_invention():
    assert em.montants_libres("hausse de 5 000 $", []) == ["5 000 $"]
    assert em.montants_libres("hausse de 5 000 $", ["5000.00"]) == []
    assert em.montants_libres("le budget est de 0 $", ["DEPENSES_NON_BRANCHEES"]) == ["0 $"]
    assert em.montants_libres("coût de 0,00 $", []) == ["0,00 $"]
    assert em.montants_libres("marge de 3.5 %", ["3.5 %"]) == []
    assert em.montants_libres("solde 4200.00", ["4200.00"]) == []
    assert em.montants_libres("solde 4200.00", []) == ["4200.00"]
    assert em.montants_libres("échéance le 2026-11-09", ["2026-11-09"]) == []
    assert em.montants_libres("échéance le 2026-11-09", []) == ["2026-11-09"]
    assert em.montants_libres("3 leads, lead-2 et m6", []) == [], "entiers nus et identifiants ne sont pas des montants"


def test_attentes_ecrites_a_la_main_coherentes_avec_les_formules_du_cahier_sans_le_code_teste():
    """Recalcul indépendant : score = 3*impact + 2*urgence + confiance ; âge = jours entre deux dates civiles."""
    for cas in CORPUS["cas"]:
        if cas["chemin"] == "priorisation" and "scores" in cas["attentes"]:
            for c in cas["entree"]["candidats"]:
                if c["id"] in cas["attentes"]["scores"]:
                    assert cas["attentes"]["scores"][c["id"]] == 3 * c["impact"] + 2 * c["urgence"] + c["confiance"]
            classement = cas["attentes"]["classement"]
            scores = [cas["attentes"]["scores"][i] for i in classement]
            assert scores == sorted(scores, reverse=True), cas["id"]
        if cas["chemin"] == "previsions":
            for domaine in cas["attentes"]["domaines"].values():
                if "age_jours" in domaine:
                    capture = cas["entree"]["captures"][domaine.get("courante", 0)]
                    jour = date.fromisoformat(capture["reference"])
                    connaissance = date.fromisoformat(cas["entree"]["connaissance"][:10])
                    assert (connaissance - jour).days == domaine["age_jours"], cas["id"]


def test_aucune_branche_par_identifiant_de_cas_aucun_modele_aucun_reseau():
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
    motif = re.compile(r"^[a-z]{3}-[AV]\d{2}$")
    chaines = [n.value for n in ast.walk(arbre) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [c for c in chaines if motif.match(c)], "le harnais ne doit connaître aucun identifiant de cas"
    imports = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            imports |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            imports.add((n.module or "").split(".")[0])
    assert not imports & {"opsys", "requests", "httpx", "urllib", "socket", "anthropic", "openai", "subprocess"}


def test_preuve_ecrite_sur_demande_sous_un_nom_distinct():
    sortie = os.environ.get("M9_EVAL_METIER_SORTIE")
    if not sortie:
        pytest.skip("preuve non demandée (M9_EVAL_METIER_SORTIE)")
    chemin = Path(sortie)
    assert not chemin.exists(), "ne jamais écraser une preuve d'évaluation antérieure"
    rapport = em.evaluer(CORPUS, horloge=time.perf_counter)
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
