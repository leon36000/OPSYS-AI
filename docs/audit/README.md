# docs/audit/ — index de liaison preuves/registres -> code (R4-S11)

Ce répertoire n'existait pas sur `main` avant l'issue
[#593](https://github.com/leon36000/OPSYS-AI/issues/593) (backlog `R4-S11`, pack OPSYS-AI v1.4).

## Contenu

- `evidence-link-index.json` — index machine, généré.
- `EVIDENCE-LINK-INDEX.md` — même index, rendu lisible, généré.

**Les deux sont produits par `scripts/evidence_index.py` — ne jamais les éditer à la main.**
Pour les régénérer après tout changement sous `evidence/**`, `registries/**` ou `Registres/**` :

```
python3 scripts/evidence_index.py            # régénère
python3 scripts/evidence_index.py --check    # vérifie que le comité est à jour (rc=1 si dérive)
```

C'est un **instantané daté**, pas une vérité permanente : chaque entrée est mesurée à un commit
précis (`mesure_a_commit` dans le JSON), exactement comme `#591` ancre ses mesures sur
`origin/main (07106d8)`. Re-exécuter le script après de nouveaux commits pour re-mesurer.

`mesure_a_commit` n'est délibérément **pas** `git rev-parse HEAD` : dès que le commit qui ajoute cet
index existe, `HEAD` l'inclurait lui-même — un fichier ne peut pas contenir son propre hash. Mesuré
en session : `--check` sortait `ROUGE` juste après le premier commit de ce lot, sur un dépôt pourtant
propre. Ancré à la place sur `git log -1 --format=%H -- evidence registries Registres` (dernier
commit touchant réellement le périmètre indexé) : stable avant et après que ce commit d'index
lui-même — qui ne touche que `docs/audit/` et `scripts/` — soit committé. Verrouillé par
`test_regression_check_reste_vert_apres_avoir_committe_lindex` dans
`scripts/tests/test_evidence_index.py`.

## Ce qui est indexé, ce qui ne l'est pas

- Indexé : `evidence/**`, `registries/**`, `Registres/**` — un fichier versionné (`git ls-files`)
  = une entrée.
- **`reviews/**` est exclu de ce lot, cf. #591, en attente de décision Nathan.** Cette phrase est
  la seule mention de `reviews/**` que ce répertoire produit.
- `evidence/tasks/EXT-AUD-001-A1-R12-CANDIDATE/**` est exclu : territoire actif de la PR #566,
  laissé intact.

## Méthode

Deux méthodes nommées et rejouables — détail complet dans l'en-tête de `scripts/evidence_index.py` :

1. **champ-explicite** — le fichier porte un champ du vocabulaire de liaison au code (`base`,
   `reviewed_commit`, `reviewed_tree`, `base_tree`, `branche`/`branch`, `code_diff_sha256` recoupé
   contre un export `preuves_jointes` committé), vérifié contre un objet Git réel ou un recalcul
   de sha256 — jamais accepté sur la seule forme.
2. **commit-introducteur** — à défaut, le commit qui a ajouté ce chemin est identifié, et son
   message complet est scanné pour une référence Git résoluble, à la condition que ce commit ne
   touche pas d'autres bundles du périmètre indexé (sinon une citation qu'il contient peut porter
   sur autre chose que ce fichier — cas mesuré et documenté dans le code, voir `groupe_bundle`).

Si aucune des deux méthodes ne prouve de liaison vers du code (commit/tree/ref/diff) : statut
`NON_PROUVE`, avec la raison consignée. Jamais une liaison inventée, jamais un silence. Ce document
ne préjuge pas de la nécessité d'un lien pour chaque fichier ; il rapporte mécaniquement ce que les
deux méthodes trouvent, ou ne trouvent pas.

**Limite assumée sur `branche`/`branch`, différente en nature des trois autres champs.** Un commit
ou un tree, une fois créés, restent des objets Git stables ; une branche peut être supprimée par une
opération de routine (nettoyage post-merge) — aucune re-exécution future ne peut garantir de la
retrouver. `"verifie": true` sur ce champ atteste donc « cette branche existait au moment de cette
mesure », jamais une garantie permanente. Mesuré en session : la résolution de ref ne doit pas
dépendre de ce qu'un clone local a fetché — un clone à branche unique (la forme réelle du checkout
CI sans `fetch-depth` explicite) ne porte localement aucune ref pour les branches non checkées,
alors qu'elles existent bel et bien sur GitHub. `git_ref_exists()` interroge donc le remote en repli
(`git ls-remote`) quand la résolution locale échoue, plutôt que de dépendre de la complétude du
clone qui exécute le script.

## Constat mesuré à ce lot (commit `07106d81cb9d5935db775575ce29ad131bf6431a`)

114 entrées : 9 prouvées (toutes sous `evidence/tasks/`), 105 non prouvées. `registries/**` (69
fichiers) et `Registres/**` (2 fichiers) sont à **0 fichier prouvé** : ni champ de vocabulaire de
liaison au code, ni citation exploitable dans un commit introducteur dédié. C'est la même classe de
défaut que #591 documente sur `reviews/**`, mesurée ici sur un périmètre voisin mais distinct — à
signaler à Nathan au même titre.
