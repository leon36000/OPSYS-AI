# M10 — Mes imports et reprise depuis un nouveau navigateur

## Comportement livré

Après une interruption et fermeture du navigateur, l'administrateur retrouve son
lot dans **Mes imports M03**, puis renvoie uniquement le fichier encore en attente.
Le parcours ne dépend plus de la clé originale conservée dans le premier onglet.
La liste réutilise les manifestes PostgreSQL du [lot précédent](M10-IMPORT-LOTS-REPRISE-2026-10-04.md)
et le principe de liste/reprise déjà utilisé dans Fusion CSV.

GET `/opsys/memoire/procedures/imports` affiche la liste privée et le formulaire actuel.
GET `.../imports/ref/{reference}` et POST `.../ref/{reference}/reprendre` utilisent
l'empreinte de clé déjà stockée comme référence. La création garde sa clé d'idempotence;
les chemins historiques par clé fonctionnent encore. Aucun DDL, corps recopié ni
nouveau store. [Design et choix](M10-MES-IMPORTS-DESIGN-2026-10-04.md).

## Autorité et confidentialité

La projection est bornée à 64 manifestes et filtrée SQL par l'auteur serveur. Elle
n'affiche ni corps, titre documentaire ni clé originale; seuls référence et compteurs
ATTENTE/RECU/INDEXE/actifs sont exposés. Ces compteurs viennent des versions/séries,
sans cache d'état divergent. La référence SHA n'est **pas une autorisation** :
accéder directement à celle d'un autre auteur reste refusé et ne crée aucun document.

Sessions administrateur vivantes, CSRF, formulaire fermé, limites, validation complète
avant effet, correspondance des fichiers/titres/SHA et revalidation immédiatement avant
chaque admission restent les mêmes. Lecture/admission par clé ou référence convergent
vers les mêmes transactions privées. Les erreurs 404 sont génériques pour un lot
absent/non autorisé; une panne de stockage reste 503. La liste et les autres pages
restent `no-store`; un rôle retiré pendant la projection interdit son affichage.

L'oubli retire le lot de la liste et bloque lecture/reprise par référence comme par
clé. Une version/indexation/activation nouvelle actualise la projection à la lecture.

## Qualification

**ROOT r108 : 95/95 cas sur neuf fichiers complets, zéro échec/erreur/skip, 44,894 s.**
Les 82 cas de la précédente tranche restent dans cette même commande; on ne les
additionne pas au nouveau total. Les neuf fichiers Python contrôlés passent Ruff.
Les 1 226 sources gelées, y compris SQL, sont identiques avant/après; gardes 180 s/
512 MiB non déclenchées, OOM inchangé à zéro et aucun survivant du groupe de test.

Le PostgreSQL éphémère est réel. Le parcours console ferme le premier TestClient
après un vrai succès puis une panne injectée, recrée application/session/navigateur,
trouve la référence dans la liste, n'y voit pas la clé précédente, reprend le seul
slot 4 et garde l'identifiant/version du slot 1. Le fournisseur PostgreSQL reste le
même et le service est nouvellement instancié. La panne est simulée; persistance,
login, listes, transactions, isolation d'auteurs et comptage sont réels.

Les autres cas vérifient auteur absent/autre, référence malformée ou majuscule,
CSRF invalide, fichier modifié sans deuxième version, max 64, états après activation,
effacement et retrait de rôle pendant liste. Les tests d'oubli/concurrence/rollback
et les outils d'autorité historiques restent exécutés dans les 95 cas.

Preuves : [capsule ROOT r108/r109](../../research/REPRISE-2026-10-04/preuves/M10-MES-IMPORTS-r1.tar.xz)
et [inventaire](../../research/REPRISE-2026-10-04/preuves/M10-MES-IMPORTS-r1.json).
Le contrôle Gitleaks r109 porte sur les fichiers de cette tranche; son résultat est
conservé dans la capsule. La CI native du nouveau commit est distincte des succès
natifs des commits précédents.

## Limites

Le fichier en attente doit toujours être resélectionné et correspondre au SHA attendu.
Cette liste n'est pas une bibliothèque de corps téléchargeables, un import comptable
client universel, une migration PDF/OCR ni une mesure d'assimilation d'entreprise.
Le périmètre reste les procédures internes M03 TXT/MD sans PII/secrets, attestées par
l'humain. M10 et OPSYS-AI restent **PARTIELS**.
