# Rapprochement M5 : choisir une provision réellement proposée

Après réparation des dépendances, `qa-r42` exécute les cinq fichiers auparavant
bloqués en collecte : 108 réussis, un échec, aucun ignoré. Le parcours privé
échoue avant le POST de crédit : le parseur navigateur ne retient que la première
option du menu des provisions, alors que l’interface en propose plusieurs.
Les références sont des hashes incorporant les dates ; leur ordre lexicographique
peut varier. Une provision pourtant proposée est donc déclarée introuvable par le test.

Le parseur conserve maintenant séparément les options de chaque formulaire.
La recherche vérifie que la référence ciblée est effectivement proposée, puis
la sélectionne dans le payload POST. Elle refuse toujours une source absente.
Les choix ne sont pas ajoutés au payload financier. Trois régressions vérifient
les deux ordres possibles et le refus d’une référence inventée.

Aucun code métier, tri d’interface, montant ou contrôle d’approbation n’est modifié.
Les deux parcours HTTP réels vérifient toujours le calcul privé, le crédit partiel,
le classement hors paie, les autorisations et les événements durables.

## Preuves

- `qa-r42` : 109 cas, 108 réussis et un échec du parseur ; reçu rouge conservé.
- `qa-r50` : source finale figée, Ruff/actionlint réussis et **112 réussis,
  aucun ignoré**, cinq fichiers entiers : fusion AP navigateur, rapprochement
  navigateur M5, fusion AP, PDF et import durable d’appel manqué M1.
  Les 109 cas précédemment collectés sont désormais réellement exécutés ; les
  trois nouveaux cas expliquent le total de 112. Ce total n’est pas une couverture
  globale du socle.
- `qa-r51` : Gitleaks du fichier modifié sans alerte brute.

Cette correction de test ne qualifie aucun paiement, paie officielle ou fiscalité.
Le produit reste PARTIEL et la PR #623 brouillon. La CI générale, la durée des
preuves M3 et la dernière interopérabilité Core doivent encore terminer sur GitHub.
Le gate mobile reste rouge sur les dépendances documentées.

[Archive](preuves/RAPPROCHEMENT-CHOIX-SOURCE-r1.tar.xz) et
[inventaire SHA256](preuves/RAPPROCHEMENT-CHOIX-SOURCE-r1.json).
