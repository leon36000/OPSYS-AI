# CRM-12 — documents du devis et photos déclarées au chantier

## Objectif et pourquoi
Depuis une soumission acceptée, l’admin retrouve ses documents M3 et consulte les photos réellement déclarées par M4 pour ce projet. Cette vue répond au besoin de dossier visuel du secrétariat en réutilisant les propriétaires métier.

## État actuel et statut
**PARTIAL — tranche serveur locale qualifiée, bibliothèque complète non livrée.** La matrice CRM conserve le besoin complet : dépôt, classement, aperçu, pièces jointes reçues, versions/retrait et permissions. Aucun raccordement documentaire M10 ou mobile ajouté. Le produit OPSYS reste PARTIAL, sans GO runtime ni PASS global.

## Architecture, fichiers et routes
- `src/opsys/console/documents_chantier.py` : port privé et deux GET.
- `src/opsys/console/crm_ui.py` : lien depuis les devis acceptés, carte du dossier mise à jour.
- `src/opsys/console/journaux_http.py` : masque les paramètres des consultations documentaires, y compris refusées.
- `tests/test_console_documents_chantier.py` : 25 cas de parcours et refus.
- [Audit préalable](CRM12-AUDIT-DOCUMENTS-PAR-PROJET.md) : sources et décisions avant code.

GET `/crm/lead/{lead_id}/soumissions/{devis_id}/fichiers` : documents HTML/PDF M3 générés à la demande, photos WCT déclarées, état courant M4 et preuve de source.

GET `/crm/lead/{lead_id}/soumissions/{devis_id}/fichiers/photos/{sha}` : lecture privée **uniquement si** cette référence appartient au WCT de ce lead/devis/intervention, puis vérification native du binaire. Ce n’est pas un accès général au stockage par hash.

## Données et workflow
1. Admin SQL actif, cookie de console vivant, SQLite canonique. Aucun rôle déduit du texte de requête.
2. Bornes de tous les registres avant décodage : 10 000 maillons et 8 Mio par registre. Snapshots typés avec rang/date/texte SQL.
3. Réutilisation de `preparation_chantier.lire` : M2, devis accepté M3, publication canonique, réception et inscription unique M4.
4. Chaîne M4 et invariants outbox vérifiés; WCT unique du triplet exact, égal à sa publication. Comparaison canonique par codec natif typé : Decimal/texte, bool/entier distincts, NaN et infinis refusés.
5. Maximum 20 références, 256 caractères chacune. Les références externes ne sont ni suivies ni affichées. Les références CAS ne promettent pas la validité d’un binaire : chaque ouverture la revérifie.
6. Un seul blob par réponse, lecteur natif `fichiers.lire_blob_verifie` : assemblage borné, blocs, taille, SHA et signature MIME JPEG/PNG, maximum 10 Mio. Cette validation ne constitue pas un décodage complet de l’image.
7. Sources, autorité et blob relus avant réponse; HTML borné à 128 Kio. Réponse sans cache, nosniff et CSP restrictive; aucune écriture métier.

## Intégrations et permissions
M2 résout le dossier, M3 reste propriétaire du devis/PDF, M4 du chantier/WCT, `opsys.fichiers` du contenu. Aucun outil MCP, rôle d’appareil ou droit supplémentaire. Les contrats DEVICE M10 restent fermés à la console. Ni finance, ni achats, ni publication marketing ne sont déclenchés. GPS, technicien, signature, coordonnées et coûts ne sont pas copiés dans la galerie.

## Risques et limites explicites
- `preuves_completion.photos_apres`, notes et signature sont validées à la complétion mais ne sont pas conservées par l’outbox actuelle. Le champ optionnel distinct `WCT.photos` est la seule source de cette galerie. Aucun rattachement rétroactif n’est inventé. Une tranche M4 propriétaire doit corriger cette lacune pour les futures complétions.
- PDF M3 généré depuis le devis courant : aucun original reçu ou signé n’est archivé par cette vue. Les pièces PDF externes ne peuvent pas être déposées ici.
- Une photo disponible ne valide pas un chantier; `completed_pending_review` reste affiché tel quel. Aucun consentement marketing déduit.
- Aucun téléversement libre, classement, suppression, export massif, comparaison de versions ou politique de rétention générale ajouté. PostgreSQL et navigateur réel non qualifiés pour cette tranche.

## Tests et preuves
QA privée `crm12-v3` : **114 PASS / 37,13 s**, dont 25 nouveaux; régressions CRM, soumissions/modèles et préparation chantier incluses. Lint des quatre fichiers touchés et vérificateur natif : 10 départements, 306 outils, 177 portées d’appareil déclarées.

M1→M2→M3→M4 utilise les outils/bus natifs. L’état terrain est une fixture fictive explicite; complétion outbox, publication, dépôt CAS et GET utilisent les composants réels. Cela ne prouve pas le parcours complet d’une application terrain. Tests : absence de DML en lecture, projet/devis étranger, hash orphelin pourtant déposé, rôles révoqués avant source/pendant rendu/après blob, source modifiée, WCT dupliqué, chaîne/binaire corrompus, publication typée incohérente, NaN SQL, bornes et journaux masqués. Les premiers rouges et erreurs de fixture/lint sont conservés séparément.

Préflight M10 privé frais, sources versionnées épinglées; cette base vide de développement n’est pas la mémoire de production du projet. Résultats et reçus durables conservés dans les artefacts du chantier, sans addition des populations recoupées.

## Gates Nathan et prochaines étapes
Aucune approbation supplémentaire pour ces lectures fictives et réversibles. Les politiques et actions sur données réelles restent hors de cette QA. Réconcilier la CI de la tête publiée avant publication normale de la tranche. Ensuite : persistance atomique propriétaire M4 des preuves futures, dépôt/rattachement photos/PDF par projet, versions/retrait/rétention, puis consultation depuis le dossier complet et mobile dans la dernière phase.

## Correctif propriétaire préparé après cette tranche CRM
M4 conserve désormais localement les preuves des **futures** complétions dans le maillon privé, hors WCT diffusé : [contrat et qualification](../field/M4-PREUVES-COMPLETION-DURABLES.md), 392 tests ciblés/régressions sans addition à la population CRM ci-dessus. La galerie de cette tranche lit encore seulement `WCT.photos`; le raccordement explicite des nouvelles `photos_apres` est l’étape suivante. Les anciennes preuves absentes ne sont pas reconstituées.

## Raccordement ultérieur des nouvelles preuves
Le bloc privé M4 des futures complétions est maintenant raccordé à la galerie admin du chantier exact : [consultation et pagination](CRM12-PHOTOS-APRES-CONSULTATION.md). Notes/signature exclues, anciennes absences préservées, origines WCT/preuves distinctes, page de 20 références. Qualification locale 126 tests et navigateur réel, sans addition aux populations précédentes. Dépôt/classement/bibliothèque complète restent PARTIAL.
