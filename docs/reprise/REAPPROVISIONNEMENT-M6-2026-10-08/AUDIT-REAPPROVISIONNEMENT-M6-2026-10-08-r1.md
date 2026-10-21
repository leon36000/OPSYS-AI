# Réapprovisionnement courant M6 — audit qualifié, 8 octobre 2026 Toronto

Le propriétaire lit dans Stock les articles déjà constatés par M6, avec leur état calculé sur les sources courantes, leurs quantités théoriques, seuils, cibles et références. OPSYS-AI et la profondeur M6 restent PARTIEL. Date Toronto : 2026-10-08T11:53:29.582985-04:00. Cet audit décrit les preuves acquises ; la nouvelle CI exacte reste distincte.

Parent publié `4ee2d616c1863df19c06c3560a4d7c1cb7727ec9`, arbre `33b29ce961713f800ae7ac470d218ad383e0123f` : six workflows verts, PR privée #623 ouverte en brouillon. CI exacte : 4 683 tests socle / 17 sauts / un warning, 4 153 tests mobiles / 187 suites et typage vert. Artefact Core `11557051616`, SHA `c122ba733fe5ff4a2059edb63427b4ab4286e8e97eba57d22fca6dee2bf37bf9`, 40 phases, reprise et sources vérifiées. Cette CI ne qualifie pas les nouveaux fichiers de réapprovisionnement.

## Tranche implémentée

Nouvelle façade `m6_lire_reapprovisionnement_appareil`, DEVICE admin actuel, T0/N0. Les arguments requis sont uniquement `decalage` et `limite`, entiers stricts bornés. Personne active et rôle actuel sont contrôlés avant toute source métier ou configuration. Aucun seuil ni historique fourni par l’appelant, aucun recalcul de stock sur le mobile.

Le moteur existant de réapprovisionnement fait autorité, avec disponibilité dérivée des mouvements, réservations et emplacements. La configuration réelle reste celle du manifeste M6, sans seuil inventé. Les quatre états sont conservés : stock bas, suffisant selon le seuil, seuil absent, configuration invalide. Seuls les articles déjà constatés sont couverts ; dernier constat par rang durable, puis ordre décroissant des derniers rangs, sans chronologie des dates. La complétion du WCT attachée au constat ne date pas le calcul courant.

Les quantités restent des textes décimaux canoniques, calculés sous contexte exact et pièges d’arrondi. Les grands nombres ne passent pas par un flottant JavaScript. En main négatif est conservé et interdit une quantité proposée ; disponible négatif reste affiché. L’unité homogène du stock demeure inconnue ; l’unité source du dernier constat est affichée séparément. Ni inventaire physique, coût, délai fournisseur, saison, responsable, photo ou achat ne sont déduits.

Publication M4 réelle, producteur, schéma, identifiant, date, mouvement de déclaration et liens sont rapprochés. Un reçu M6 absent est légitime si la déclaration a précédé la livraison ; un reçu lié existant incohérent est refusé. Les reçus étrangers sont comptés et leur copie est empreintée, sans imposer à leurs métadonnées anciennes les restrictions des champs affichés. Les empreintes de snapshots sont calculées pour la lecture, jamais présentées comme des chaînes historiques conservées.

DIRECT entière bornée à 5 400 points de code, page réduite puis refus nominal si elle ne tient pas. Au plafond réel de Cap, le lecteur refuse avant tout stockage de secours ou artefact. Le budget des six copies de sources est de 10 000 lignes combinées après copies : aucune garantie d’allocation avant copie.

Carte réellement composée dans Stock, lecture explicite, pages courantes remplaçantes, sources et limites fr-CA/en-CA. Capture de session/autorité et génération réseau, fermeture des réponses et anciens callbacks après changement de personne, jeton, rôle, focus ou cycle réseau. Aucun cache, outbox, intention ou effet ajouté à cette lecture.

## Vérifications et historique

21 fichiers rapprochés depuis B, puis quatre deltas corrigés avec préimages exactes dans R. Source globale corrigée `d70c954596766aa8e323aee09e48bcd91274806acb910265f8b26dde89cbb999`, inventaire de 43 497 fichiers, inchangée pendant les contrôles. Core `eec3fe98eb432fd35fee805533d2a81dfc6a9c2b` et verrous inchangés ; le dist existant est qualifié séparément sur le même arbre.

Version corrigée : 4 319 tests mobiles / 190 suites, TypeScript global et Ruff verts ; 1 471 tests M6, portées et limites Cap affectées verts. La qualification précédente de 2 718 tests / un saut PostgreSQL+pgvector local conserve son périmètre et ses sources d’avant correctif. Le saut vient du socket Docker local refusé. Vérificateur 224 outils / 132 déclarations appareils ; ses définitions ne changent pas dans les derniers deltas de compatibilité.

Export Android JS réel depuis R : 1 581 modules, bundle SHA `82c2634a556a595e5d9dd65f66fc9740d92fca37213da49c920bc91a7f5af5f0`, marqueurs du nouvel écran et du contrat présents. Aucun téléphone ni bytecode Hermes qualifié par cet export.

13 réponses SQL r3 réelles, 49 tables intégrales inchangées par lecture et zéro artefact, puis 124 tests du lecteur pur dont 13 consommations exactes. Les cinq succès historiques sont aussi consommés par le vrai client et le service avec fetch de rejeu fictif. Ce rejeu n’est pas une campagne HTTP native. La revue du raccord Stock et des courses est distincte de la revue backend.

Rouges conservés : façade absente, plafond réel tentant le fallback, collecte d’un service absent, oracle de double encodage du rendu, types en construction, faux oracle d’égalité entre empreinte d’un maillon et snapshot entier. Disponibilité : ancien reçu étranger sans empreinte, metadata legacy de transfert, puis finding P2 sur identifiant de transfert et liaisons internes légales. Correctif minimal, exemples du vrai writer et complément indépendant : trois probes et neuf tests ciblés verts, 49 tables préservées. Les contraintes publiques 256, liens, révisions, signes, nombres finis et chaînes restent contrôlés. Aucun résultat initial n’est rebaptisé preuve de la version finale.

## Parcours natif et critères restants

Campagne native réelle sur les 21 sources gelées : DEVICE opaque → Gateway Node 24 → HTTP MCP → SQLite fictif. **41 appels Gateway / 36 MCP**, 36 HTTP 200, quatre 403 et un 401 ; **41 paires de 49 tables intégrales inchangées**, zéro artefact. Métadonnées appairées nathan/admin distinctes du rôle SQL actuel ; révocation admin refusée après deux lectures d’identité et avant tout snapshot/config/résolution/itération/getter ou SELECT métier. Corps Gateway entier et SHA des octets identiques après redémarrage. Pipeline réel M4 complétion → reçu M6, puis writers M6 existants ; préparation séparée des lectures. Pages courantes ordinaires 4/10, limite 8, suivant 4, 4 639 caractères ; décimaux exacts, références Unicode et metadata legacy, sources 10 001 et plafond réel Cap 800 refusés sans artefact. 37,24 s, pic 1,336 Go sous 8 Go, deux CPU / 180 s CPU par processus ; aucune garde déclenchée. 64 dépendances et inventaire global de 43 497 fichiers contrôlés avant/après. ROOT vérifie tous les manifestes/empreintes/paires/révocation/reprise et constate les groupes de processus absents après nettoyage DB/config/auth. Scanners propres ; deux connexions catalogue externes bloquées, aucune admise dans la garde Node, sans garantie réseau de toute la machine.

Les **39 DTO UTF-8 originaux** et deux projections exactes de preuve (`avant_decimal_cancellation`, `avant_restart_body_entier`) sont consommés par le vrai client avec transport de rejeu, sans réécriture de réponse ni nouvel appel HTTP. Après ces deux fichiers consommateurs, qualification complète : **4367 tests mobiles / 191 suites**, TypeScript global vert sur le même inventaire de sources. Le 401 sans champ `ok`, les arguments illégaux, refus d’autorité/nominal et données valides gardent des classifications distinctes. Aucun téléphone, Expo SQLite ou bytecode Hermes revendiqué.

Deux rouges de harnais natif sont conservés : une grande quantité hors page, puis une enveloppe de 5 298 caractères légale malgré l’oracle de dépassement. Correction des seules données de harnais, aucune modification du lecteur pour satisfaire ces faux oracles. Les capsules r1/r2 non scellées sont en quarantaine privée et ne sont pas exportées ; leurs dispositions publiques gardent références et empreintes.

Commit/push ordinaires sur la branche privée existante, PR #623 en brouillon, audit/registre/capsule rattachés. Nouvelle CI du commit exact requise ; six workflows verts du parent 4ee conservés séparément.

Conservation : 302 sources et 124 supports du pack léger, 104 références de preuves exclues, supplément absent et conversations absentes inconnues. Chaque divergence et absence garde une disposition explicite. Dix départements profonds, OpenClaw, permissions, dashboard, mobile quatre profils/hors ligne, avatars et mémoires séparées restent l’ambition.

Prochaine priorité identifiée : un ACK de déclaration M6 inconnu peut retirer l’intention de l’outbox mémoire dans le vrai chemin client/descripteur/vidangeur ; correctif séparé en B, sans modifier les sources natives gelées. Les preuves de pertes/bris restent limitées : pas de motif/date/preuve par mouvement conservés. Aucune revendication de livraison de photos, répétitions, causes, inventaire physique ou fonctionnement permanent.
