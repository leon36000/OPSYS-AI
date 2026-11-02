#!/usr/bin/env python3
# ruff: noqa: E501  (table de mutations : une mutation par ligne, motifs longs)
"""Mutations de SOURCE du banc d'embeddings : chaque garde, comparaison ou formule des métriques, de la fusion RRF, du
client de passerelle et du reclassement est affaiblie, les tests rapides du banc sont rejoués, puis le fichier est
RESTAURÉ. Une mutation « survivante » (tests toujours verts) est un trou des tests, ou une mutation équivalente à
expliquer.

Usage : mutations.py [--python PYTHON]   (PYTHONPATH/HOME/TMPDIR déjà posés comme pour pytest ; ne pas lancer en
parallèle d'une mesure réelle : elle chronomètre des appels).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
DOSSIER = RACINE / "install" / "qualification" / "embeddings_fr"
CIBLE = "tests/test_banc_embeddings_fr.py"
# Les trois tests de bout en bout (lents : rééchantillonnage complet) sont écartés ; les autres portent les mutations.
FILTRE = "not de_bout_en_bout and not tableau_markdown_et_cli and not cli_mesurer"

# (nom, fichier, ancien, nouveau)
MUTATIONS = [
    # --- métriques
    ("rappel-divise-par-k", "metriques.py", "len(set(classement[:k]) & set(pertinents)) / len(pertinents)",
     "len(set(classement[:k]) & set(pertinents)) / k"),
    ("rappel-k-plus-un", "metriques.py", "len(set(classement[:k]) & set(pertinents))",
     "len(set(classement[:k + 1]) & set(pertinents))"),
    ("rappel-sans-garde-vide", "metriques.py",
     'if not pertinents:\n        raise ValueError("rappel@k indéfini sans passage pertinent")', "if False:\n        pass"),
    ("mrr-rang-decale", "metriques.py", "return 1.0 / rang\n    return 0.0", "return 1.0 / (rang + 1)\n    return 0.0"),
    ("mrr-depart-a-2", "metriques.py", "for rang, identifiant in enumerate(classement[:k], start=1):\n        if identifiant in pertinents",
     "for rang, identifiant in enumerate(classement[:k], start=2):\n        if identifiant in pertinents"),
    ("mrr-ignore-k", "metriques.py", "for rang, identifiant in enumerate(classement[:k], start=1):\n        if identifiant in pertinents",
     "for rang, identifiant in enumerate(classement, start=1):\n        if identifiant in pertinents"),
    ("dcg-decote-decalee", "metriques.py", "g / math.log2(rang + 1)", "g / math.log2(rang + 2)"),
    ("ndcg-ideal-non-tronque", "metriques.py", "reverse=True)[:k]", "reverse=True)"),
    ("ndcg-ideal-croissant", "metriques.py", "reverse=True)[:k]", "reverse=False)[:k]"),
    ("ndcg-classement-non-tronque", "metriques.py", "for identifiant in classement[:k]]", "for identifiant in classement]"),
    ("ndcg-gain-nul-compte", "metriques.py", "for g in gains.values() if g > 0)", "for g in gains.values())"),
    ("quantile-position-fausse", "metriques.py", "position = q * (len(tri) - 1)", "position = q * len(tri) - 0.5"),
    ("quantile-sans-interpolation", "metriques.py", "tri[bas] + (tri[haut] - tri[bas]) * (position - bas)", "tri[bas]"),
    ("bootstrap-alpha-faux", "metriques.py", "alpha = (1.0 - niveau) / 2.0", "alpha = (1.0 - niveau)"),
    ("bootstrap-sans-dernier", "metriques.py", "valeurs[alea.randrange(n)]", "valeurs[alea.randrange(n - 1)]"),
    ("bootstrap-moyenne-biaisee", "metriques.py", ") / n for _ in range(repetitions))", ") / (n + 1) for _ in range(repetitions))"),
    ("difference-signe-inverse", "metriques.py", "ecarts = [x - y for x, y in zip(a, b, strict=True)]",
     "ecarts = [y - x for x, y in zip(a, b, strict=True)]"),
    ("difference-sans-garde-longueur", "metriques.py", "if len(a) != len(b):\n        raise ValueError",
     "if False:\n        raise ValueError"),
    # --- fusion
    ("rrf-rang-decale", "metriques.py", "+ poids_liste / (k + rang)", "+ poids_liste / (k + rang + 1)"),
    ("rrf-depart-a-0", "metriques.py", "for rang, identifiant in enumerate(liste, start=1):\n            scores",
     "for rang, identifiant in enumerate(liste, start=0):\n            scores"),
    ("rrf-ecrase-au-lieu-de-sommer", "metriques.py", "scores[identifiant] = scores.get(identifiant, 0.0) + poids_liste / (k + rang)",
     "scores[identifiant] = poids_liste / (k + rang)"),
    ("rrf-sans-k", "metriques.py", "+ poids_liste / (k + rang)", "+ poids_liste / rang"),
    ("rrf-poids-ignores", "metriques.py", "scores.get(identifiant, 0.0) + poids_liste / (k + rang)",
     "scores.get(identifiant, 0.0) + 1.0 / (k + rang)"),
    ("rrf-poids-decales", "metriques.py", "1.0 if poids is None else poids[position]", "1.0 if poids is None else poids[-1]"),
    ("rrf-poids-negatif-accepte", "metriques.py", "or any(p < 0 for p in poids)", "or False"),
    ("classer-ordre-inverse", "metriques.py", "key=lambda t: (-t[1], t[0])", "key=lambda t: (t[1], t[0])"),
    ("classer-sans-departage", "metriques.py", "key=lambda t: (-t[1], t[0])", "key=lambda t: (-t[1],)"),
    ("fusionner-k-ignore", "metriques.py", "return classer(fusion_rrf(listes, k, poids))", "return classer(fusion_rrf(listes, poids=poids))"),
    ("fusionner-poids-ignores", "metriques.py", "return classer(fusion_rrf(listes, k, poids))", "return classer(fusion_rrf(listes, k))"),
    # --- cosinus, séparation des questions sans réponse
    ("cosinus-sans-norme", "metriques.py", ") / (na * nb)", ")"),
    ("auc-egalite-comptee-pour-un", "metriques.py", "total += 1.0 if p > n else 0.5 if p == n else 0.0",
     "total += 1.0 if p >= n else 0.0"),
    ("auc-egalite-comptee-pour-zero", "metriques.py", "total += 1.0 if p > n else 0.5 if p == n else 0.0",
     "total += 1.0 if p > n else 0.0"),
    ("faux-acceptes-quantile-inverse", "metriques.py", "quantile(positifs, 1.0 - rappel_cible)", "quantile(positifs, rappel_cible)"),
    ("faux-acceptes-comparaison-stricte", "metriques.py", "if n >= seuil", "if n > seuil"),
    # --- corpus
    ("perturbation-garde-les-accents", "corpus.py", "mots = sans_accents(texte).split(\" \")", "mots = texte.split(\" \")"),
    ("perturbation-touche-les-nombres", "corpus.py", "len(m) >= 5 and m.isalpha()", "len(m) >= 5"),
    ("corpus-accepte-non-fictif", "corpus.py", 'if donnees.get("fictif") is not True:', "if False:"),
    ("corpus-jugement-inexistant-accepte", "corpus.py", "if ident not in passages:", "if False:"),
    ("corpus-negative-incoherente-acceptee", "corpus.py", 'if (genre == "negative") != (not pertinents):', "if False:"),
    ("corpus-courriel-reel-accepte", "corpus.py", 'if not domaine.endswith(".test"):', "if False:"),
    # --- juge
    ("juge-tri-croissant", "juge.py", "key=lambda identifiant: (-notes.get(identifiant, NOTE_MIN), position[identifiant])",
     "key=lambda identifiant: (notes.get(identifiant, NOTE_MIN), position[identifiant])"),
    ("juge-nombre-de-notes-non-verifie", "juge.py", "or len(notes) != attendu", "or False"),
    ("juge-note-hors-borne-acceptee", "juge.py", "not NOTE_MIN <= n <= NOTE_MAX", "not NOTE_MIN <= n <= NOTE_MAX + 5"),
    ("juge-presentation-triee", "juge.py", "alea.shuffle(melange)", "pass"),
    # --- banc
    ("banc-ecart-signe", "banc.py", "metriques.difference_appariee([a[i][cle] for i in ids], [b[i][cle] for i in ids]",
     "metriques.difference_appariee([b[i][cle] for i in ids], [a[i][cle] for i in ids]"),
    ("banc-distinguable-inverse", "banc.py", '"distinguable": not (bas <= 0.0 <= haut)', '"distinguable": (bas <= 0.0 <= haut)'),
    ("banc-cout-sans-requetes", "banc.py", "(jetons_doc + jetons_req)", "jetons_doc"),
    ("banc-rrf-k", "banc.py", "RRF_K = 60", "RRF_K = 61"),
    ("banc-hybride-sans-lexical", "banc.py", "metriques.fusionner([ids_lex, ids_vec], RRF_K)", "metriques.fusionner([ids_vec], RRF_K)"),
    ("banc-seuil-produit", "banc.py", "< SEUIL_VECTORIEL_PRODUIT else 0", "<= SEUIL_VECTORIEL_PRODUIT else 0"),
    ("banc-seuil-negatives-strict", "banc.py", ">= SEUIL_VECTORIEL_PRODUIT else 0", "> SEUIL_VECTORIEL_PRODUIT else 0"),
    ("banc-prefixe-inverse", "banc.py", "prefixe = config.prefixe_requete if role == \"requete\" else config.prefixe_document",
     "prefixe = config.prefixe_document if role == \"requete\" else config.prefixe_requete"),
    ("banc-input-type-inverse", "banc.py", '("query" if role == "requete" else "document")', '("document" if role == "requete" else "query")'),
    # --- lexical et cache
    ("lexique-couverture-stricte", "lexical_local.py", "trouves / len(termes) >= couverture", "trouves / len(termes) > couverture"),
    ("cache-cle-sans-prefixe", "cache.py", '"\\x00".join((modele, prefixe, input_type or "", texte))',
     '"\\x00".join((modele, input_type or "", texte))'),
    # --- passerelle
    ("passerelle-suit-les-redirections", "passerelle.py", "def redirect_request(self, *args: Any, **kwargs: Any) -> None:\n        return None",
     "def redirect_request(self, *args: Any, **kwargs: Any):\n        return super().redirect_request(*args, **kwargs)"),
    ("passerelle-cle-non-expurgee", "passerelle.py", 'return texte.replace(self._cle, "***")', "return texte"),
    ("passerelle-rejoue-les-erreurs-client", "passerelle.py", "if exc.code not in CODES_TRANSITOIRES:", "if False:"),
    ("passerelle-index-non-verifie", "passerelle.py", 'if [d["index"] for d in ordonnees] != list(range(len(textes))):',
     "if False:"),
    ("passerelle-vecteur-nul-accepte", "passerelle.py", "or not any(v):", ":"),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--python", default=sys.executable)
    args = p.parse_args()
    survivantes = []
    for nom, fichier, ancien, nouveau in MUTATIONS:
        chemin = DOSSIER / fichier
        original = chemin.read_text(encoding="utf-8")
        if original.count(ancien) < 1:
            print(f"[INVALIDE] {nom} : motif introuvable dans {fichier}")
            survivantes.append(nom + " (invalide)")
            continue
        chemin.write_text(original.replace(ancien, nouveau, 1), encoding="utf-8")
        try:
            r = subprocess.run([args.python, "-m", "pytest", "-p", "no:cacheprovider", "--import-mode=importlib", "-x",
                                "-q", "-k", FILTRE, CIBLE], cwd=RACINE, capture_output=True, text=True)
        finally:
            chemin.write_text(original, encoding="utf-8")
        tuee = r.returncode != 0
        print(f"[{'TUÉE ' if tuee else 'SURVIT'}] {nom}", flush=True)
        if not tuee:
            survivantes.append(nom)
    print(f"{len(MUTATIONS)} mutations, survivantes : {survivantes or 'aucune'}")
    return 1 if survivantes else 0


if __name__ == "__main__":
    raise SystemExit(main())
