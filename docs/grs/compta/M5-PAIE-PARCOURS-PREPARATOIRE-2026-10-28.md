# M5 — Parcours de paie préparatoire : mode d'emploi du propriétaire (2026-10-28)

**Ce que c'est** : un atelier privé, dans la console, pour préparer la paie d'un employé sur une période et remettre un dossier
exploitable à votre professionnel. **Ce que ce n'est pas** : un système de paie. Rien n'est versé, remis, déclaré ni envoyé ;
aucun bulletin, T4, RL-1 ou RE n'est émis ; le résultat porte toujours `PREPARATOIRE` et `NON_QUALIFIEE_POUR_PAIE`.

## Parcours

1. Console → Finance → Paie → **Dossiers de paie préparatoires** → « Préparer un nouveau dossier ».
2. Remplissez les déclarations (période de 14 jours, date de paie, première paie de 2026, attestations, TD1, TP-1015.3, cumuls, pièces,
   paramètres employeur). Un champ vide reste **inconnu** ; une case décochée veut dire **non attesté**.
3. « Calculer l'aperçu » : vous voyez l'admission documentaire, les heures M4 et le taux M5 utilisés, chaque poste et ce qui manque.
   Retenues, net, DAS et coût employeur n'apparaissent que si **tous** leurs postes sont couverts.
4. « Conserver cette version » : la version est figée et chiffrée. Corrigez en créant une nouvelle version (l'ancienne ne change jamais).
5. Pour la période suivante, « Période suivante » reprend les cumuls simulés de la version courante — des hypothèses, jamais des salaires payés.
6. « Vérifier » compare le dossier aux sources actuelles (heures M4, contrat, admission, cumuls). Une différence mène à une nouvelle version explicite.
7. « Revue interne » : liée à la version et à l'empreinte exactes ; c'est votre revue, pas une validation fiscale. Puis exportez JSON ou page lisible pour votre CPA.

## Ce qui peut vous bloquer (volontairement)

- Admission refusée : les PDF d'autorité épinglés ne sont pas installés (voir `RACCORD-COORDINATEUR.md`).
- Hors domaine : surtemps, primes, avantages, rétroactif, régime CCQ, année à 27 paies, autre année que 2026.
- Postes employeur inconnus : FSS, CNESST, normes du travail et FDRCMO demandent vos déclarations avec pièce ; aucun taux n'est présumé.
- Source modifiée : heures M4 corrigées après coup → rebase.

Détails techniques : `departments/m05-financecore/docs/paie-parcours-preparatoire.md`. Reprise de mission :
`docs/reprise/M5-PAIE-PARCOURS-2026-10-28/`.
