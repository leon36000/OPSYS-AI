# Rapprochement humain et cash CFO privé — 3 octobre 2026

Cette tranche est intégrée et vérifiée localement sur SQLite. Elle permet de rapprocher les
déclarations humaines de paie/DAS avec les sources financières existantes, puis de consulter
un cash privé calculé par le propriétaire M5 existant. M5 dans son ensemble reste **PARTIEL**.

## Parcours et données

`GET /finance/paie/rapprochements` affiche les obligations actives et les sources à classer.
`POST` sur ce même chemin journalise une confirmation humaine. Les chemins portent le préfixe
de console configuré, `/opsys` par défaut. Un lien est présent dans le dossier CFO privé.
Un rôle vivant `finance` ou `nathan_owner` est requis; `admin` seul ne suffit pas. Les formulaires
exigent CSRF, identifiant de mutation, révision du journal et empreinte financière affichée.
Les pages CFO et de rapprochement répondent avec `no-store` et `no-cache`.

Le journal chiffré append-only conserve création, remplacement, règlement déclaré et
rapprochement. Son schéma 3 conserve les versions antérieures. La révision vérifie l'absence
d'écriture concurrente; l'empreinte financière lie les registres, les fichiers de configuration
et les obligations actives. Elle exclut les confirmations de rapprochement elles-mêmes pour
qu'une confirmation n'invalide pas immédiatement son propre résultat.

| Confirmation | Effet financier |
|---|---|
| `LEGACY_IDENTIQUE` | Identité exacte de montant et de source; la composante existante reste comptée une fois. |
| `NOUVELLE_COMPOSANTE` | Ajoute une obligation privée lorsque la catégorie legacy est absente. |
| `PROVISION_CREDIT` | Réduit uniquement le recouvrement confirmé entre une provision et une obligation déjà comptée. |
| `PROVISION_HORS_PAIE` | Classe la provision tout en conservant sa déduction intégrale. |

Le crédit est borné par la provision et l'obligation. Une source réutilisée, une obligation
non rapprochée, un doublon de période ou une source périmée rend le résultat **INCONNU**.
Les rapprochements d'obligations remplacées restent historiques et ne créditent plus le cash.
Changer un registre ou la configuration exige de nouvelles confirmations. Aucun chiffre
« au plus » n'est présenté comme disponible. Aucune provision ne signifie pas réserve zéro :
une déclaration explicite reste nécessaire. Une composante manquante est nommée dans la page.

## Propriétaires et protections

Le [service chiffré](../../../src/opsys/console/obligations_privees.py), la
[capture financière](../../../src/opsys/console/finance_snapshot_prive.py) et la
[route privée](../../../src/opsys/console/obligations_rapprochement_ui.py) utilisent la connexion
canonique et le calculateur `_resultat_cash_libre` existant. La capture lit chaque registre une
fois; les vérifications terminales relisent sa taille et sa tête. Les droits et sources sont
revérifiés après chiffrement et avant ajout. Le POST travaille dans le pool de threads existant.

Les registres financiers sont bornés avant matérialisation : 10 000 lignes et 8 MiB par registre,
64 KiB par ligne, sur trois registres. Le journal privé reste limité à 4 096 entrées. La page
refuse les mutations lorsqu'elle dépasse 200 sources ou obligations; elle ne valide pas une
liste tronquée. Le résultat complet n'est pas exposé au catalogue MCP ni à l'API publique.

## Vérification et sous-matrice

Les huit fichiers entiers passent **93 cas**, sans échec, erreur ou skip; Ruff passe sur dix
fichiers concernés. Deux parcours utilisent l'application réelle avec préfixe, connexion,
cookies, CSRF, SQLite, AES-GCM et calculateur M5. Ils vérifient cash exact, source périmée,
réserve absente, nouvelle confirmation, crédit partiel de provision, API sans pièce privée et
refus d'un admin seul. Les autres tests comportent aussi des doublures ciblées; les données
métier sont fictives.

584 sources restent identiques pendant la campagne. Durée du conducteur : environ 30 secondes;
RSS maximal mesuré du groupe pytest : 182 095 872 octets. Aucun nouvel OOM ni processus survivant.
Voir [preuve ROOT](../../research/REPRISE-2026-10-03/preuves/m5-rapprochement/VERIFICATION-ROOT.json),
[JUnit complet](../../research/REPRISE-2026-10-03/preuves/m5-rapprochement/pytest.xml.gz) et
[reçu brut](../../research/REPRISE-2026-10-03/preuves/m5-rapprochement/receipt.json.gz).
Les essais RED antérieurs sont conservés dans l'archive de campagne : erreurs de fixtures,
d'URL préfixée et de date fiscale fictive ont été corrigées sans contourner le calculateur.

| Capacité | État et preuve |
|---|---|
| Journal humain, chiffrement et transitions | Vérifié localement dans les 93 cas. |
| Classement des sources et crédit sans double déduction | Vérifié localement, données fictives. |
| Cash privé par moteur M5 existant | Vérifié dans deux parcours HTTP réels. |
| Dossier CFO HTML privé et permissions | Vérifié; cache interdit. |
| Consommation par prévision principale ou agents | À raccorder; aucune exposition privée implicite. |
| Paie nette, DAS, remise fiscale ou paiement réel | Non qualifié par cette tranche; validation humaine/professionnelle requise. |
| PostgreSQL, déploiement VPS et corpus client | Non qualifiés par cette campagne SQLite. |

## Limites et prochaine tranche

Le solde est celui des écritures M5, pas une lecture bancaire attestée. Les sources de paie sont
des déclarations humaines, pas des tables fiscales certifiées. Les fichiers sont comparés par
empreinte avant/après; une modification transitoire puis restaurée n'est pas détectée par ce
modèle. Le snapshot n'est pas une transaction atomique entre fichiers et SQLite.

Une répétition avec sources changées peut être refusée même si une confirmation précédente a
été écrite : recharger la page permet de relire le journal, sans nouvelle écriture automatique.
Les données financières privées restent dans l'espace humain. Leur usage par un agent ou un
autre consommateur nécessite un contrat de permissions et de provenance explicite.
