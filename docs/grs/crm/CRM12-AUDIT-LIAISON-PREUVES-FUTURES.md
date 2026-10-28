# CRM-12 — raccordement des photos après conservées par M4

## Objectif et pourquoi
Afficher les photos après d’une nouvelle complétion depuis le devis/chantier exact, en plus des déclarations photo distinctes du WCT. Le dossier visuel doit refléter les preuves conservées par le propriétaire M4, sans reconstruire les anciennes pièces absentes ni exposer notes ou signature.

## État actuel avant code
Audit de `bdcb22caa1e65a235748391f3cff4fc235204df2`. La galerie CRM-12 lit seulement `WCT.photos`. M4 conserve désormais un bloc privé optionnel `preuves_completion` dans le maillon composite unique : version entière 1, booléen `signature_requise`, sous-objet fermé `preuves`. `photos_apres` est distinct de `WCT.photos`; les notes et la signature ne doivent pas entrer dans la galerie. Les invariants natifs valident le bloc; le hash de transition diffusé dans le WCT le lie au maillon, sans diffuser son contenu.

## Réutilisation et architecture
Réutiliser le port `src/opsys/console/documents_chantier.py`, l’ancre M2/M3/M4 existante, la chaîne/invariants outbox, l’égalité canonique avec la publication et le lecteur CAS vérifié. Aucun nouvel outil, droit, stockage, connecteur ou contrat événementiel. Le port ne projette du bloc privé que les références `photos_apres` du maillon sélectionné.

## Routes, données et workflow
GET galerie existante avec seul paramètre optionnel `decalage`, entier canonique multiple de 20. Déclarations WCT au plus 20 (borne existante); preuves M4 au plus 512 (contrat propriétaire). Page de 20 références, ordre stable : déclarations WCT puis photos après conservées. Une même image déclarée dans les deux groupes reste deux références de sources distinctes, jamais deux images uniques revendiquées. Navigation précédente/suivante fermée; un décalage absent de la source est refusé, sans troncature silencieuse.

GET photo existant sans paramètre libre : retrouver la référence dans l’ensemble autorisé du même chantier, indépendamment de la page affichée, puis relire le blob natif vérifié. La pagination n’est pas un contrôle d’autorisation. Le hash d’une signature conservée, d’un autre projet ou d’un dépôt orphelin ne donne aucun accès. Sources/admin/blob revérifiés après rendu comme dans la tranche précédente.

## Fichiers, permissions et intégrations
Modifier seulement le port et ses tests, puis les contrats CRM/M4/matrice concernés. Admin SQL vivant, session de console actuelle, SQLite canonique; aucune simulation DEVICE. M3 reste propriétaire des liens PDF/HTML existants. Aucune nouvelle émission vers M5/M6/M8/M9/M10 ni usage marketing. Les notes et signatures ne sont jamais ajoutées au DTO, à la réponse ou à l’URL de galerie.

## Risques, tests et critères
Tests HTTP sur vrai bus/ancrage et outbox/CAS natifs, données fictives. Prouver nouvelle photo consultable sans champ `WCT.photos`, sources distinguées, absence de notes/signature dans la page et refus de leur hash, refus autre projet, source modifiée, corruption du bloc, pagination de plus de 20 preuves, borne 512, requêtes fermées, ouverture d’une photo hors page autorisée. Conserver les refus et messages historiques quand le bloc est absent. Aucune qualification d’application terrain complète ou de récupération historique depuis une fixture.

## Gates Nathan, statut et prochaines étapes
**AUDIT TERMINÉ, CODE NON COMMENCÉ À LA CRÉATION.** Aucun gate additionnel pour ces lectures privées fictives et réversibles. Préflight M10 natif frais `crm12-archive-m10-preflight-v1` rc0 sur références de sources permises, sans élargir la garde des chemins `crm`; documentation CRM lue séparément dans Git. La base privée vide ne remplace pas la mémoire projet. Publication attend toujours la réconciliation terminale de la CI 10a4af68; anciennes intentions non rejouées. Bibliothèque documentaire complète, upload/classement/versions/rétention et mobile restent PARTIAL.

## Résultat après audit
Raccordement implémenté, **126 PASS / 34,98 s** (`crm12-archive-v2`), dont 40 tests de galerie; revue statique indépendante sans défaut concret résiduel identifié. Navigateur réel sur nouvelle instance privée : pagination 25 références, ouverture/décodage PNG, retour, 5 GET sans écriture; serveur/onglet nettoyés. [Contrat de consultation et limites](CRM12-PHOTOS-APRES-CONSULTATION.md). CI de publication et bibliothèque complète restent non qualifiées par cette seule tranche.
