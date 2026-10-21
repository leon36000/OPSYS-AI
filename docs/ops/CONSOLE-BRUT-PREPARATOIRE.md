# Préparer un brouillon de brut régulier depuis la console

La console offre un écran de préparation réservé à une personne propriétaire active (`nathan_owner`). La page de saisie est `GET /finance/paie`; le formulaire de calcul est `POST /finance/paie`, et l’API correspondante est `POST /api/finance/paie/brut`. Ces routes sont servies sous le préfixe de la console, `/opsys` par défaut. Elles sont montées par `opsys.console.application`.

L’écran vide ne préremplit aucun montant. Il présente les personnes actives portant le rôle `employee`, par nom, puis demande les sept arguments de l’outil : identifiant du salarié, premier et dernier jours inclusifs (`AAAA-MM-JJ`), fuseau IANA, politique d’arrondi, hypothèse ou référence humaine d’arrondi, et références de sources attendues. La politique disponible est `centime_demi_superieur`; l’utilisateur doit la choisir explicitement. L’hypothèse est obligatoire et reste déclarative, non vérifiée.

Chaque requête d’écriture vérifie le jeton CSRF de la session : champ `csrf` pour le formulaire, en-tête `X-CSRF-Token` pour l’API. Le serveur revalide dans la base que la personne est active et a le rôle `nathan_owner` avant de lister les salariés et avant l’appel métier. Un rôle `admin` seul, un compte employé ou manager, une session anonyme ou un rôle propriétaire retiré sont refusés. Aucun rôle ou identifiant d’acteur transmis par le client n’est accepté.

## Lire ou épingler les sources

« Lire les sources courantes » envoie `sources_attendues: null` à `m5_preparer_brut_regulier`. Après un résultat, la page conserve deux gestes distincts : relire explicitement les sources courantes, ou « Recalculer ce snapshot » en renvoyant les références M4 et M5 exactes présentées. Si une référence a changé, l’outil renvoie `REJ-SALAIRE-REVISION-PERIMEE`; la page n’actualise pas le snapshot et ne relance pas le calcul silencieusement.

Le résultat affiche le brut arrondi en CAD, la fraction exacte sous la forme `numerateur_centimes / 60`, les minutes régulières, les lignes et révisions M4/M5, l’empreinte M4 et la référence d’arrondi. L’outil calcule à partir d’une projection M4 complète et du contrat horaire courant M5. Voir [M5.4.b — brouillon de brut régulier](../../departments/m05-financecore/docs/m54b-brut-regulier-preparatoire.md) pour les règles de période, de source et les limites métier.

Ce résultat est préparatoire et demande une validation humaine. Il ne constitue pas une paie et ne crée ni contrat, ni validation M4, ni obligation, ni paiement. Les retenues, cotisations, DAS, coûts employeur, paie nette et paiement ne sont pas calculés; le résultat n’alimente pas le cash libre. Cette route console n’ajoute aucun grant CFO aux agents.

## Vérification et portée

Dans la copie scratch `/tmp/m54-paie-pont-r1`, les tests ciblés `tests/test_console_paie.py` ont exécuté la vraie route ASGI avec les fonctions M4 et M5 réelles et des données synthétiques : 7 tests passent. Cette preuve vérifie notamment le calcul, le contrôle owner/CSRF, le refus d’un snapshot périmé et l’absence de nouveaux maillons métier. Elle ne constitue pas encore une validation de l’intégration au dépôt actif.
