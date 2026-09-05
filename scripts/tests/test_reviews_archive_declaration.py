"""#591 / AUD-PROOF-006 : les verdicts historiques de reviews/ ne portent aucun champ qui les lie au
code jugé (mesuré sur 07106d8, 2026-08-27 : 711 verdicts, 9 clés, 0 liant au code) et leurs sceaux
prompt_sha256 n'ont aucune préimage committée. reviews/README.md le déclare ; ce test (A) scelle la
déclaration et (B) re-mesure l'invariant sur l'arbre courant — si un verdict lié au code apparaît un
jour sous reviews/, (B) rougit et force la mise à jour de la déclaration."""
from __future__ import annotations

import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
README = RACINE / "reviews" / "README.md"
CLES_LIANT_AU_CODE = {
    "code_diff_sha256", "reviewed_commit", "reviewed_tree", "commit", "tree", "head_sha",
    "base", "merge_base", "revision", "diff_sha256",
}


def test_la_declaration_d_archive_existe_et_dit_ce_que_les_verdicts_n_attestent_pas():
    texte = README.read_text(encoding="utf-8")
    assert "Statut : ARCHIVE" in texte
    assert "#591" in texte
    assert "Aucun champ ne lie un verdict au code" in texte
    assert "aucune préimage n'est committée" in texte


def test_aucun_verdict_historique_ne_porte_de_cle_liant_au_code():
    fichiers = sorted((RACINE / "reviews").rglob("*.json"))
    assert fichiers, "corpus reviews/ vide ?"
    lies = []
    for fichier in fichiers:
        cles = set(json.loads(fichier.read_text(encoding="utf-8")).keys())
        if cles & CLES_LIANT_AU_CODE:
            lies.append(str(fichier.relative_to(RACINE)))
    assert lies == [], f"verdict(s) lie(s) au code sous reviews/ — mettre a jour reviews/README.md : {lies[:5]}"
