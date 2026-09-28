# M6-material-control

Material Control OS — inventaire, PO, variance sans accusation

Statut : département OPSYS complet (mode `ombre`), sur le modèle de M3. Les 9
stories du PRD (`docs/bmad/02-PRD-PM.md`) sont livrées et vertes : validation
des entrées WCT/formulaire/clés interdites (S001), catalogue + résolution de
prix FALLBACK (S002), cycle PO → réception (S003), stock localisé par
chantier (S004), variance d'inventaire sans accusation (S005),
réapprovisionnement suggéré (S006), contrats de sortie séparés par
destinataire (S007), registre append-only hash-chaîné (S008), conformité
statique + digest (S009). Couche département ajoutée : `department.yaml`,
`SOUL.md`, 3 skills (`receptionner-une-commande`,
`consommer-du-materiel-terrain`, `compter-l-inventaire`),
`src/m6_material_control/outils.py` (5 outils agent, dont
`m6_receptionner_commande` : réception → stock → variance de bout en bout),
`tests/test_outils_agent.py`.

Bugs corrigés (test rouge → vert) lors de cette passe :
- `materiel.py` n'exposait que `consommer_materiaux`. `enregistrer_reception`
  et `soumettre_comptage`, prescrits par `docs/bmad/03-ARCHITECTURE.md`
  (l.51, 406-410), n'existaient pas : `reception.traiter_reception` est une
  fonction pure qui n'écrit rien, donc aucun matériau reçu n'atteignait
  jamais le registre, et toute consommation ultérieure échouait par
  `REJ-STOCK-INSUFFISANT` faute de stock réellement enregistré. Les deux
  fonctions sont maintenant implémentées selon l'architecture (écriture
  atomique, `SignalPoAPayer` jamais émis si indéterminé, réévaluation du
  reorder).
- `frontieres.py` (clés interdites comme « virement », « statut_paiement »)
  n'était appelé nulle part dans le pipeline réel — câblé dans
  `validation.py` (WCT, formulaire, bon de commande, réception, comptage,
  seuils) et donc dans les 3 orchestrateurs d'écriture.
- Les montants M6 restent des `float` (contrat gelé), alors que
  M5-FinanceCore exige un `Decimal` fini. `contrats_sortie.py` porte
  désormais `montant_decimal_a_la_frontiere` (conversion sûre
  `Decimal(str(x))`, jamais `Decimal(x)`), prouvée par un test
  inter-départements M6 → M5 réel (`tests/test_frontiere_finance_m5.py`,
  aucune modification de m5_financecore).
