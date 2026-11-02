# Méthode de veille open source (réutilisable par département)

Issue de la veille [mémoire d'expérience des agents](VEILLE-MEMOIRE-EXPERIENCE-AGENTS-2026-11.md) (2026-11-02). Complète `AGENTS.md`, « Briques open source ».

## Les 10 lignes

1. **Fixer la question et les filtres durs avant de chercher** : cas d'usage, licences admises, exécution locale, Loi 25, « le code calcule ». Écrire ce qui ferait **rejeter** une brique.
2. **Chercher large puis étroit** : GitHub (mots-clés, sujets, étoiles), arXiv, listes à jour, issues ; noter les requêtes pour que d'autres les rejouent. Ne pas se fier à un classement par étoiles.
3. **Lire le fichier `LICENSE` lui-même** (et les sous-dossiers) ; relever l'empreinte ; une bannière ou un champ d'API n'est pas une licence. Pas de licence = pas d'usage du code.
4. **Mesurer la maturité** : commit de tête et date, version, tests, issues ouvertes (lire les titres), PR fusionnés, dépendances, poids, mise en garde du README (« démonstration »).
5. **Chercher les échecs avant les succès** : issues de reproduction, critiques, audits de sécurité, articles qui comparent à des témoins simples (RAG brut, sans mémoire).
6. **Distinguer lu / résumé / déduit** ([L] [R] [S] [D]) ; ne jamais écrire qu'une méthode « marche » à partir d'un résumé ou d'un chiffre d'éditeur ; dire ce qui n'a pas été exécuté.
7. **Regarder le protocole** : jeux d'essai et de mémoire séparés ? plusieurs passages ? intervalles ? juge humain ou LLM ? même modèle pour agir, juger et apprendre ?
8. **Confronter à l'existant** : que fait déjà le dépôt (code lu) ? L'écart est-il la brique ou la matière ? Préférer réutiliser nos mécanismes de gouvernance.
9. **Décider par verdict daté** : ADOPTER / ADAPTER (idée seulement) / SURVEILLER (avec condition de réexamen) / IGNORER (avec raison) ; inscrire seulement ce qui est qualifié dans `INGREDIENTS.md`, à la fin du fichier.
10. **Rendre reproductible et honnête** : fichier de relevé (commit, licence, empreinte), sources avec URL et date de consultation, limites sans euphémisme, questions ouvertes pour Nathan ; relancer la veille à date fixe ou sur événement.

## Outillage

[`VEILLE-MEMOIRE-EXPERIENCE-2026-11/releve-depots.sh`](VEILLE-MEMOIRE-EXPERIENCE-2026-11/releve-depots.sh) produit le relevé (commit de tête, étoiles, fichier de licence lu, empreinte SHA-256, licence lue, écart avec l'API) à partir d'une liste de dépôts. Lecture seule via l'API GitHub, rien du dépôt n'est exécuté. Adapter la liste `DEPOTS` au département.

## Fiche à remplir par candidat

| Champ | Contenu |
|---|---|
| Projet, lien, version et commit | |
| Licence lue (fichier, taille, empreinte), sous-dossiers à licence propre | |
| Maturité : date du dernier commit, tests, issues et PR ouverts, mise en garde | |
| Ce que ça fait (lu dans le code ou le README) | |
| Ce que ça prouve réellement (protocole, témoins, répétitions, réplications) | |
| Coût et risque d'intégration (dépendances, poids, données, langue, local ou nuage) | |
| Existant OPSYS qui recouvre la même idée | |
| Verdict daté et condition de réexamen | |
| Niveaux de preuve : [L] lu · [R] résumé · [S] source secondaire · [D] déduit | |
