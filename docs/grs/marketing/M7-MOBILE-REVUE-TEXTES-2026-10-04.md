# M7 — revue mobile des contenus de chantier

**QUALIFIÉ LOCAL — publication GitHub bloquée.** Cette tranche ajoute au profil
Admin la lecture des textes de chantier et leur décision humaine. Elle conserve
le pont M4 → M7, l'usine de contenu et les règles serveur déjà présentes. Le
département M7 complet reste **PARTIEL**.

## Parcours et périmètre

L'accueil Admin mène à « Marketing · contenus de chantier ». Le téléphone lit
le texte entier, la plateforme, la révision, la fraîcheur et la source de marque,
la preuve de consentement et les avertissements. Le serveur borne chaque page
en caractères et à huit contenus au plus ; le bouton suivant continue au
`decalage` renvoyé, sans supposer qu'une page contient toujours huit textes.

L'identité d'appareil vient du protocole existant. Le rôle `admin` permet la
lecture ; la preuve propriétaire M9 autorise seulement la présentation des
commandes. Le service M7 revérifie l'identité active, le rôle `nathan_owner`,
le statut, le consentement et les contrôles de contenu. Aucun rôle ou auteur
fourni par le téléphone ne remplace ces vérifications.

Le propriétaire approuve ou rejette un texte affiché. Un rejet exige un motif
de 5 à 500 caractères. Chaque décision possède un identifiant de mutation et
un horodatage. Une réponse techniquement réussie peut être un refus métier.
La relecture serveur suit la décision ; aucun envoi n'est rejoué automatiquement.
Aucune copie persistante ni file hors ligne ne conserve ces textes ou décisions.

## Revue et corrections

ROOT a demandé des corrections sur la session liée au serveur, les réponses
arrivant après une déconnexion, le verrou de mutation jusqu'à la fin de sa
relecture, le masquage immédiat des données lors d'un changement d'identité,
les messages de refus et la visibilité de l'état occupé. Les tests ROOT couvrent ces comportements, avec refus de toute décision concurrente
pendant la mutation et sa relecture.

Le contrôle des rôles a révélé un compteur documentaire périmé : 122 outils
exposés aux appareils sur **214**, au lieu de 213. Seul le compteur dans
[ROLES.md](../../architecture/ROLES.md) change ; aucune permission n'est élargie.

## Vérification et honnêteté des preuves

La campagne ROOT r173 conserve **260 succès / 1 échec** : ce compteur obsolète.
La campagne r174 passe **261/261**, huit fichiers complets, zéro échec, erreur
ou skip, avec Ruff et vérification des manifestes. Elle exerce les vrais
parcours backend SQLite et appareil, distincts des doubles de transport mobile.
La campagne ROOT r176 confirme **261/261**, zéro échec, erreur ou skip,
et inclut explicitement ROLES.md dans son empreinte : **1 250 chemins**
identiques avant et après, Ruff et manifestes verts.

La campagne mobile ROOT r175 passe **225/225 tests Jest**, neuf fichiers
complets, zéro échec ou skip, puis le typage TypeScript de toute l’application.
Les **366 chemins mobile** sélectionnés restent identiques avant/après.
Durée de campagne : 7,159 s. Les gardes de rôles, la session confirmée, le
transport, les enveloppes métier et les nouveaux contrôleur/service M7 sont
vérifiés ensemble. Parmi ces tests, **19** concernent les nouveaux comportements
M7 ; leurs appels réseau sont des doubles, distincts de l’E2E backend SQLite.
Aucun OOM ni processus de test restant dans les deux campagnes finales.
Les essais du sous-agent ne remplacent pas cette qualification indépendante.
Un log intermédiaire `pass.log`, observé rouge, a été écrasé par le sous-agent
sans sauvegarde. La perte est enregistrée ; ce log n'est pas reconstruit et
aucune histoire complète de tests avant code n'est affirmée. Le RED initial et
les essais suivants disponibles sont conservés avec leurs résultats réels,
y compris lorsque leur nom contient « green » et que le résultat est rouge.

## Limites

Aucun export, accès aux octets des médias, programmation sociale, publication,
dépense ou changement de backend n'est ajouté. Les médias restent séparés de
la revue des textes. Une marque périmée ne rend pas une décision disponible.
Le retrait de consentement et l'identité serveur font toujours autorité.

Les tests Jest et TypeScript ne remplacent pas une validation sur téléphone
physique. Les parcours backend ne prouvent pas une application complète sur
VPS ni un parcours vocal/avatar. Cette tranche n'achève ni M7 ni OPSYS-AI.
La publication GitHub est bloquée par l'authentification de l'environnement ;
ces modifications restent locales. Voir le [blocage documenté](../../research/REPRISE-2026-10-04/PUBLICATION-ATTENTE-2026-10-04.md)
et le [design](M7-MOBILE-REVUE-TEXTES-DESIGN-2026-10-04.md).

## Sources et preuves

- [Contrôleur](../../../mobile/src/m7/controle.ts), [contrat](../../../mobile/src/m7/contrat.ts) et [transport](../../../mobile/src/m7/service.ts).
- [Écran Admin](<../../../mobile/app/(admin)/marketing.tsx>) : revue des textes seulement.
- [Capsule](../../research/REPRISE-2026-10-04/preuves/M7-MOBILE-TEXTES-r1.tar.xz) et [inventaire](../../research/REPRISE-2026-10-04/preuves/M7-MOBILE-TEXTES-r1.json) : sources, préimages vérifiées, reçus ROOT et logs disponibles.
