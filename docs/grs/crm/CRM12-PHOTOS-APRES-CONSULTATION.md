# CRM-12 — consulter les photos après du chantier exact

## Objectif et pourquoi
Le secrétariat retrouve les photos après conservées par M4 depuis la soumission acceptée, sans les confondre avec les déclarations photo du WCT. La galerie offre une consultation privée et paginée, liée aux preuves du chantier. Les PDF/HTML M3 existants restent accessibles depuis le même écran.

## État actuel et statut
**Tranche serveur qualifiée localement, bibliothèque documentaire toujours PARTIAL.** Les nouvelles preuves M4 sont raccordées; les anciennes complétions sans bloc restent explicitement sans preuve retrouvée. Aucun document historique n’est reconstruit. Upload libre, classement, pièces PDF reçues, versions/retrait/rétention et application mobile ne sont pas livrés par cette tranche.

## Architecture, fichiers et routes
Réutilisation de `src/opsys/console/documents_chantier.py`, `preparation_chantier.lire`, du registre/invariants outbox M4 et de `fichiers.lire_blob_verifie`. Tests dans `tests/test_console_documents_chantier.py`. Voir l’[audit avant code](CRM12-AUDIT-LIAISON-PREUVES-FUTURES.md) et le [contrat de conservation propriétaire M4](../field/M4-PREUVES-COMPLETION-DURABLES.md).

- GET `/crm/lead/{lead_id}/soumissions/{devis_id}/fichiers` : première page.
- Même GET avec `?decalage=20`, puis 40, etc. : pagination fermée, 20 références par page. Un seul paramètre, entier ASCII canonique multiple de 20; doublons, zéros initiaux, autres paramètres ou sélection hors source refusés.
- GET `/crm/lead/{lead_id}/soumissions/{devis_id}/fichiers/photos/{sha}` : ouverture d’une photo autorisée pour ce chantier, sans paramètre libre. La pagination ne remplace pas l’autorisation : une photo de la dernière page reste consultable directement si elle appartient réellement à la même source autorisée.

## Données et workflow
1. Admin SQL actif, session courante et connexion canonique SQLite; bornes avant décodage.
2. M2/M3/M4 vérifient le lead, le devis accepté, l’inscription unique, la réception et la publication canonique. Chaîne et invariants M4 validés.
3. Sélection du **maillon exact** porteur du WCT publié : les seules références privées projetées sont `preuves_completion.preuves.photos_apres`. La signature et les notes ne sont pas projetées ni ajoutées à l’ensemble de hashes autorisés.
4. Ordre déterministe : déclarations `WCT.photos` (borne existante 20), puis photos après conservées (borne propriétaire M4 512). Chaque entrée garde son origine et son numéro. Les comptes portent sur des **références**, pas des images uniques : une même image peut être déclarée dans les deux sources. Maximum 532 références, page de 20, sans troncature silencieuse.
5. Chaque ouverture retrouve la référence dans l’ensemble autorisé du même triplet, puis lit un seul blob CAS vérifié : blocs, taille, SHA et signature MIME. Le navigateur de QA a également décodé un vrai petit PNG fictif.
6. Sources et autorité sont relues après rendu; le blob est revérifié avant réponse. Empreinte de source identique entre pages d’une même lecture stable; aucune mutation métier.

## Intégrations et permissions
Aucun nouvel outil, droit, rôle d’appareil, schéma événementiel, stockage ou connecteur. M4 reste propriétaire des preuves; le port de console ne simule pas une identité DEVICE. Le PDF M3 est généré depuis le devis courant, sans prétendre être un original signé archivé. Aucun partage marketing ou nouvelle émission vers les autres départements.

## Risques et limites
Un hash ne constitue pas une permission : signature, fichier orphelin ou autre projet sont refusés même si le binaire existe. Les références externes ne sont jamais suivies ni exposées. Les notes/signatures restent privées, sans contenu ni hash ajouté au DTO. Une photo ne valide pas le chantier; le statut en attente de revue est conservé. Source incohérente, bloc invalide, quota dépassé ou binaire corrompu ferment la réponse. Réponses sans cache, nosniff et CSP restrictive; requêtes de galerie masquées dans les journaux.

Cette qualification n’inclut pas PostgreSQL, une application terrain complète, une récupération historique ni des documents de production. La présentation actuelle est une galerie de consultation; elle ne certifie pas l’ensemble du CRM demandé.

## Tests et preuves
`crm12-archive-v2` : **126 PASS / 34,98 s**, dont 40 tests de galerie (15 nouveaux), plus régressions CRM, préparation et conservation M4. Lint des quatre fichiers sélectionnés et vérificateur natif : 10 départements, 306 outils, 177 portées déclarées. Les résultats 114/392/40 antérieurs recoupent cette population et ne sont pas additionnés.

Cas démontrés : nouvelles photos consultables sans `WCT.photos`, origines distinctes, notes et hash de signature absents du DTO/HTML, signature et autre projet refusés, pagination 25 et 512 références, ouverture hors page autorisée, retour page 0, requêtes fermées et protections de source/autorité héritées. Le rouge initial est conservé : 5 échecs/35 réussites dus au raccordement/pagination absents.

Navigateur IAB réel, nouvelle instance privée `gallery-v2` : connexion du compte fictif, page 1 (1–20), page 2 (21–25), ouverture de la photo 25, décodage PNG `complete=true`, taille 1×1, retour puis page précédente. **5 GET HTTP 200**, empreinte de toutes les tables inchangée avant/après chacun. Capture et DOM page 2 conservés. Source en lecture seule, limites vérifiées avant imports (CPU 1, mémoire 1 Gio, swap 0, 96 processus, TTL 900 s), réseau sortant refusé par le noyau et écoute IPv4 loopback éphémère. Serveur possédé arrêté, reçu rc0, unité inactive/MainPID0; onglet fermé et inventaire IAB vide. Une première préparation `gallery-v1` a échoué au parsing du harnais avant imports/commande/unité/base : historique conservé, erreur de harnais, aucun bug produit déduit et aucune réémission de cette intention.

## Gates Nathan et prochaines étapes
Aucun gate supplémentaire pour ces lectures fictives réversibles. Préflight M10 privé frais rc0, chemins de source permis, aucune extension de la garde mémoire; la base vide ne remplace pas la mémoire projet. Réconcilier la CI de la tête publiée avant publication normale de la tranche. Ensuite : bibliothèque photos/PDF avec dépôt et rattachement contrôlés, versions/retrait/rétention, puis mobile dans la phase prévue. OPSYS reste PARTIAL, sans GO runtime ni PASS global.
