# Revue et qualification de la première tranche CRM

Statut : PARTIAL. Répertoire de leads et dossier client en lecture seule ; aucune parité complète
QuickBooks/C-CUBE/Google Agenda déclarée. Les besoins CRM-01 à CRM-16 et les familles de rapports
restent dans EXIGENCES-SECRETARIAT-3EN1.md et le brief dépersonnalisé.

Claude Code CLI 2.1.310 a effectivement exécuté claude-sonnet-5-5, effort high, avec les seuls outils
Read/Glob/Grep/Edit/Write dans un snapshot privé. Il n’a pas exécuté les tests ni écrit dans Source.
La revue ROOT reprend sa livraison, sans changer les rôles d’une personne réelle ni ouvrir un droit
appareil. La console continue de demander un admin actif en base ; nathan_owner seul reste refusé
par les outils M2. Le rôle adapté de secrétariat reste à concevoir, sans attribuer admin automatiquement.

## Comportement et preuves

GET /crm consulte les leads M2, paginés et filtrés par statut. GET /crm/lead/{lead_id} affiche le contact,
les projets du même client et ses activités récentes. Les sections non reliées sont indiquées comme
indisponibles. Aucune route CRM d’écriture, aucun envoi courriel et aucune seconde base commerciale.
La présence d’un tableau des sections ne prouve pas leur fonctionnalité.

Les 17 tests initiaux de Claude passent. Un contrôle indépendant ROOT révèle qu’un décalage numérique
de 5000 caractères déclenche ValueError avant de rendre le refus HTTP prévu. La longueur est désormais
bornée avant conversion. Le rouge crm-v4 est conservé ; le lot crm-v5 passe : 157 cas comprenant CRM,
console générale, réception, métier et lectures M9 ; le lint des cinq fichiers Python modifiés passe.
Ces populations se recoupent : ne pas les additionner. TestClient exerce les routes FastAPI et SQLite
durable avec des identités fictives ; il ne prouve pas encore le rendu navigateur ni un déploiement.

Les deux premières tentatives de préparation QA ont atteint la limite de 32 processus du harnais
pendant l’installation privée des dépendances. Elles n’ont pas importé le produit. La reprise borne
les workers de l’installateur et porte le plafond à 96 processus, 1 GiB RAM, CPU 1, 90 secondes, avec
Source en lecture seule sous Landlock et sockets Internet interdits avant imports. Roues réutilisées
uniquement après vérification de leurs empreintes uv.lock ; aucun appel réseau QA.

## Limites et prochaine tranche

Recherche par nom, coordonnées éditables, notes modifiables, agenda/cédule, courriels exacts et réponses,
clauses, soumissions, achats libres, facturation corrigible, photos/PDF et rapports complets ne sont pas
livrés par cette tranche. Revoir les contrats manquants avec leurs départements ; brancher d’abord la
note client existante et les soumissions en conservant CSRF, idempotence, auteur authentifié et RBAC.
La phase mobile suit les exigences serveur. Toute automatisation financière reste dans M5 et ses validations.

Preuves externes à Source : chantier crm-secretariat-sonnet55-20261027-r1 et crm-root-qa-20261027-r1.
Les captures originales restent privées ; seuls leurs besoins dépersonnalisés entrent dans le dépôt.
