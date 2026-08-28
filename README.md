# OPSYS-AI — Core d'automatisation d'entreprise

OPSYS-AI construit et qualifie d'abord un Core d'entreprise autoritatif. Le
programme actif est **Core v2.3.0**.

## Commencer ici

1. Lire [`docs/core/CANON-INDEX.md`](docs/core/CANON-INDEX.md).
2. Lire les décisions actives sous `docs/decisions/`.
3. Pour une mission Core, consulter le registre, le graphe et le contrat sous
   `.opsys/core-control/2.3.0/`.
4. Utiliser une issue, une branche et un worktree dédiés, puis lier les tests
   et la preuve au commit et à l'arbre exacts.

## Ordre du programme

```text
C00 → C24
→ M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9
→ surfaces mobile, cockpit et avatar finales
```

Pendant le Core, aucune logique métier `M1` à `M10` n'est complétée. Les
frontières et les surfaces différées sont définies dans le canon indexé.

## Développement et preuve

- pas de push direct sur la branche par défaut ;
- RED/GREEN et non-régressions avant l'intégration ;
- aucune preuve, revue ou réussite fabriquée ;
- une mission terminée doit être vérifiable sur son commit et son arbre exacts.

Les fichiers racine sont des portails. Le canon actif se trouve dans
[`docs/core/CANON-INDEX.md`](docs/core/CANON-INDEX.md).

## Licence

Voir `LICENSE`.
