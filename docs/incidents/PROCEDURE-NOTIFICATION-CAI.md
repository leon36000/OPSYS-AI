> **PROPOSITION (P0-7)** — document généré par l'équipe OPSYS-AI et validé par revue scellée
> multi-modèles. **VALIDATION FINALE : Nathan (T3)** — aucun usage externe ni engagement avant sa
> validation écrite. Responsable de la protection des renseignements personnels (RP) : **Nathan**.

# Procédure de notification en cas d'incident de confidentialité

> Source : alignée sur le runbook D-037 du plan maître et sur §14.2.

## 1. Détection et qualification

- Identifier l'incident, la brèche ou l'accès non autorisé.
- Déterminer s'il existe un risque de **préjudice sérieux**.
- Critères de gravité : ______ (à remplir lors de l'EFVP)
- Décideur final sur le caractère sérieux : **Nathan**.

## 2. Confinement

- Isoler les systèmes affectés.
- Couper l'accès aux données concernées.
- Geler les déploiements en cours jusqu'à clarification.

## 3. Rotation des secrets touchés

- Identifier les secrets, clés API, identifiants et certificats potentiellement exposés.
- Les révoquer et les régénérer.
- Documenter la rotation dans le registre d'incidents.

## 4. Restauration par la chaîne prouvée

- Restaurer les systèmes affectés à partir de la chaîne prouvée (P0-9).
- Vérifier l'intégrité des sauvegardes avant rétablissement.
- Ne pas réintroduire de données compromises sans validation.

> Source : Plan maître §14.2 — « secrets touchés -> restaurer par la chaîne prouvée (P0-9) -> notifier selon 14.2 ».

## 5. Notification

- Si un risque de préjudice sérieux est confirmé, notifier la Commission d'accès à l'information (CAI).
- Notifier les personnes concernées.
- [À VÉRIFIER — juriste : délais exacts de notification à la CAI et aux personnes concernées.]

## 6. Inscription au registre d'incidents

- Inscrire l'incident dans le registre des incidents de confidentialité.
- Conservation obligatoire : cinq ans.
- Référencer les entrées précédentes si l'incident fait l'objet de corrections.

> Source : Plan maître §14.2 — « registre d'incidents 5 ans + notification CAI si préjudice sérieux ».

## 7. Post-mortem sans blâme

- Rédiger un post-mortem dans le ledger.
- Identifier les actions correctives.
- Suivre la mise en œuvre des actions correctives.
- Aucun blâme individuel : l'objectif est l'amélioration des systèmes.

## 8. Exercice annuel

- Réaliser un exercice annuel sur un scénario réaliste.
- Documenter les apprentissages et les écarts.
- Mettre à jour la procédure si nécessaire.

---

> **Encadré — sanctions**
> Le plan maître §14.2 rappelle que les sanctions prévues par la Loi 25 peuvent atteindre **25 M$ / 4 % du chiffre d'affaires mondial**.
