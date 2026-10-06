# M5 — propager la rentabilité après la décision humaine

Statut : correction vérifiée localement, pas de qualification globale en production.
[Programme](../../programme/PROGRAMME-24H-2026-10-04.md) ·
[Lecture M3](../estimation/M3-APPRENTISSAGE-LECTURE-RAPPORT-2026-10-05.md).

## Défaut reproduit

En r251, le vrai parcours M2/M3/M4/M6/M5/M8/M10 a finalisé une facture fictive par
`approbations.decider` N4. Le détail M5 indiquait un coût complet et un prix définitif;
sa trace dérivée et le fait M8 conservaient pourtant la version du brouillon. Le lecteur M3
excluait correctement la marge : deux cas passaient, ce troisième échouait.
Les wrappers d’envoi et de constatation de paiement ne déclenchaient pas le calcul dérivé.

## Correction

Après une transition acceptée, `outils.py` retrouve le devis depuis la vue canonique des
factures actives puis réutilise `_essayer_cout_reel`. La trace append-only et l’événement
`m5.rentabilite_chantier` sont écrits dans la transaction de l’outil approuvé. Une panne de
publication annule ensemble transition, trace et événement; la décision est enregistrée en échec.
L’enveloppe durable ne contient aucun devis : le maillon de transition porte seulement la facture,
son statut et ses dates. Aucun montant n’est fourni ou recalculé par le modèle.

Les simulations avec historique injecté restent isolées. N4 conserve les rôles financiers;
N5 conserve le propriétaire et l’attestation professionnelle. Une décision déjà traitée ne
s’exécute pas deux fois. La nouvelle version PAYEE reflète le changement de statut sans créer
un encaissement dans le grand livre. Ce parcours ne transporte aucun courriel ni paiement réel.

## Vérification ROOT

- r252 : les trois cas initiaux passent après correction.
- r253 : 419 réussites, un échec conservé. L’ancien test attendait un rattrapage manuel après
  envoi; il vérifie désormais la trace immédiate, son historique intact et l’absence de doublon.
- **r254 : 420 tests réussis dans seize fichiers complets, zéro échec/erreur/skip**, Ruff
  et `opsys-metier verifier` verts. Sources gelées avant/après, aucun changement ni OOM.

Le parcours réel couvre brouillon exclu, WCT critique exclu, facture ENVOYEE puis PAYEE via
approbations N4/N5, concordance M5/M8, absence de mutation lors de la lecture M3, rejeu et
rollback complet après une panne fictive de publication. Les suites existantes vérifient aussi
refus de rôle, montant partiel/écart, attestation absente et simulations de facturation.

Limites : SQLite et logique déterministe dans cette tranche; pas de serveur PostgreSQL actuel,
corpus client, précision d’estimation mesurée, modèle activé ou transport financier externe.
La correction n’actualise pas toutes les mutations de prix/taux possibles : leurs garde-fous
continuent d’exclure une trace périmée tant qu’une nouvelle dérivation n’est pas exécutée.

Preuves : [capsule](../../research/REPRISE-2026-10-05/preuves/FINALITE-PROPAGATION-M5-r1.tar.xz)
et [inventaire](../../research/REPRISE-2026-10-05/preuves/FINALITE-PROPAGATION-M5-r1.json).
