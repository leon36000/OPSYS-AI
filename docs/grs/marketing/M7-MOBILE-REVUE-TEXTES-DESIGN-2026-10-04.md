# M7 — revue des textes de chantier depuis l'app Admin

Statut initial : **EN COURS**, 4 octobre 2026 UTC. Le département marketing
doit rendre ses brouillons exploitables par le propriétaire sur le terrain.
Le pont réel M4 → M7 et la console existante sont conservés.

## Réutilisation et décision

Le bus `m4.travaux_termines` alimente déjà le WCT reçu et l'usine M7.
`m7_lister_contenus_chantier` donne les textes complets, leur plateforme,
révision, source de marque, fraîcheur et preuve de consentement. Les variantes
déterministes ne constituent pas des publications. `m7_decider_contenu`
revalide le propriétaire actif, le retrait, la révision et le contrôle du texte
dans sa transaction. Ces comportements ne sont pas reconstruits en TypeScript.

La capacité appareil `admin` permet d'atteindre M7 ; elle ne suffit pas pour
approuver. La disposition N3 applique la validation humaine au départ et
le service M7 exige en plus le rôle courant `nathan_owner`. La liste M9
existante fournit la preuve serveur `proprietaire` pour cette identité.
Ses attentes départementales sont seulement informatives ; elles ne sont
pas des demandes d'approbation M9 pouvant décider ces textes.

Le nouvel écran appelle donc les outils M7 directement par le transport
appareil existant, sans transmettre un rôle ou une personne dans les arguments.
Aucun changement de politique, de backend, de dépendance ou de registre.

## Parcours et contrôles

1. Entrée dans l'écran : effacer toute vue précédente, charger en direct
   la preuve propriétaire et une page bornée de textes M7.
2. Montrer texte entier, plateforme, WCT, révision, statut, source/fraîcheur
   de marque, preuve de consentement et avertissements. Pagination explicite
   à huit éléments au plus ; aucun élément supplémentaire masqué silencieusement.
3. Seul le propriétaire confirmé peut décider un texte `PROPOSE` affiché
   avec marque fraîche. Le serveur reste autorité si le consentement ou
   l'identité change entre lecture et action.
4. Rejet avec motif de 5 à 500 caractères ; un score ou un rôle d'appareil
   ne vaut jamais approbation. Action en ligne, confirmation du texte concerné,
   identifiant de mutation et horodatage par le protocole existant.
5. Après décision, relire le serveur. Une enveloppe d'exécution réussie
   peut contenir un refus métier : conserver ce refus. Si le transport rend
   l'issue incertaine, imposer la relecture sans rejouer aveuglément l'action.
6. Perte réseau, changement d'identité ou sortie de l'écran : invalider
   la vue et les commandes. Aucun cache persistant ni file hors ligne.

## Plan d'implémentation autorisé

Luna possède les nouveaux fichiers `mobile/src/m7/` (contrat, service,
contrôleur et tests) et `mobile/app/(admin)/marketing.tsx`, ainsi que la seule
entrée marketing visible de `mobile/app/(admin)/admin.tsx` ; le layout reste
dans sa portée pour le routage. Préimages des deux fichiers avant édition.
ROOT possède ce design, les rapports et la qualification finale. Tests de
comportement avant implémentation, reçus distincts même lorsqu'ils échouent.

Contrat fermé et réponses mal formées, preuve propriétaire absente/fausse,
statut/fraîcheur incompatible, rejet invalide, retrait après lecture,
décision incertaine, relecture échouée, hors ligne et changement d'identité
doivent garder la décision fermée. Les contrôles backend existants seront
vérifiés avec leurs vrais parcours SQLite et appareil.

## Limites

La tranche concerne les **textes** : aucun accès aux octets des photos,
approbation média, export, planification, publication sociale ni dépense.
La saisie AP et les données privées financières restent séparées.
Jest/typecheck et parcours backend ne remplacent pas un essai sur téléphone
physique ni une qualification PostgreSQL des écritures médias. M7 au complet
reste PARTIEL ; la publication GitHub est actuellement bloquée par son
authentification, indépendamment de la qualification locale.
