# M5-financecore

FinanceCore — comptabilite, fiscalite (mention CPA), paie, CFO IA

Statut : département OPSYS complet (mode `ombre`), sur le modèle de M3. Les 7
stories du PRD (`docs/bmad/02-PRD-PM.md`) sont livrées et vertes : contrats
gelés + validation d'entrée (S001), registre append-only hash-chaîné (S002),
solde/argent disponible (S003), taux fiscaux versionnés (S004), registre
d'approbation F0-F7 (S005), état financier filtré par rôle (S006), conformité
statique transversale (S007). Couche département ajoutée : `department.yaml`,
`SOUL.md`, 2 skills (`tenir-le-registre-financier`,
`gerer-les-approbations-f0-f7`), `src/m5_financecore/outils.py` (5 outils
agent), `tests/test_outils_agent.py`.

Quatre bugs corrigés (test rouge → vert) lors de cette passe :
- `soldes.py` n'imposait aucun signe : un DECAISSEMENT positif gonflait le
  solde au lieu de le diminuer. Le signe est désormais imposé à l'écriture
  (`validation.py::valider_mouvement`, `REJ-MOUVEMENT-SIGNE-INCOHERENT`).
- `etat_financier.construire_etat_financier` exposait le solde par défaut
  (`autorise_couts=True`) : un rôle non autorisé (ex. « employe ») le voyait
  sans le demander. Par défaut désormais : refus (fail-closed).
- `approbation.py` acceptait n'importe quelle chaîne comme preuve MFA/CPA
  F6/F7. Une preuve doit maintenant être une structure JSON vérifiable
  (`methode`, `horodatage` ISO 8601 avec fuseau, `identifiant_approbateur`) —
  aucun fournisseur MFA n'est présumé ni codé en dur.
- Les taux fiscaux versionnés (`contracts/taux_fiscaux.v1.yaml`) n'étaient
  utilisés par aucun calcul : `taxes.py` (nouveau) calcule TPS/TVQ en Decimal
  en les lisant via `taux_fiscaux.rechercher_taux`, jamais codés en dur.
