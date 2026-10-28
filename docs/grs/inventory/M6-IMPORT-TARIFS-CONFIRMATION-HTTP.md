# M6 / CRM-14 — revue et confirmation HTTP d’un lot tarifaire

Audit avant code, sourceb9f3800e. Statut initial : T1 privé qualifié localement, confirmation
HTTP absente. Objectif : la secrétaire revoit les lignes et confirme explicitement toutes les
versions tarifaires ou aucune. Aucun prix réel n’est appliqué pendant le développement.

## Existant, pourquoi et réutilisation

`import_tarifs_ui.py` fournit GET/POST d’aperçu, multipart borné, CSRF, revalidation T0 sur
catalogue/fournisseurs/livre, état aprèsrendu. `tarifs_ui.py` fournit les conventions de saisie
unitaire et nonce UUID; son appel de commodité ne convient pas au rollback aprèsrendu.
`import_tarifs_confirmation.py` possède le T1 privé atomique et son reçu clos de lot/enfants.
Le livre, réceptions, audit, idempotence et événements M10 restent chez leurs propriétaires.
Recherche GitHub/GitLab et choix de briques de l’import déjà conservés dans le chantier :
réutiliser FastAPI/Starlette, SQL canonique et ces propriétaires, sans nouvelle dépendance.

## Architecture, fichiers et route

Nouveau POST `/crm/materiaux/tarifs/importer/confirmer`, dans un adaptateur
`src/opsys/console/import_tarifs_confirmation_ui.py`, inclus dans le router d’aperçu.
Extension paramétrée du parseur multipart existant avec liste exacte des champs; défaut d’aperçu
conservé. Le formulaire de confirmation apparaît seulement après revue de toutes les lignes
admissibles. Nouveau nonce UUID serveur, CSRF, action explicite et empreintes source/préparation
de cet aperçu. Le navigateur redemande le même CSV : aucune copie cachée/base64 ou persistence
serveur du fichier ni des colonnes libres. Le même formulaire et même fichier permettent le rejeu.

## Données, workflow et intégrations

Admin courant avant lecture du corps → upload borné → CSRF/action/nonce/champs fermés → T1
avec source/préparation attendues obligatoires. T1 + relecture indépendante du reçu durable
parent/enfants + comparaison exacte de réponse + rendu échappé/borné + relecture du reçu et
dernière autorité résident dans `stockage.transaction()`. Une exception attrapée ultérieurement
ne doit pas valider des prix, audits ou événements orphelins. Réutiliser les bornes1Mio/50lignes,
64KioJSON,128KioHTML et le quota de sortie hérité.

Le rejeu relit le reçu historique avant toute exigence de fraîcheur actuelle : l’application du
lot modifie elle-même le livre. Les prix affichés sont ceux des versions confirmées du reçu,
sans promesse de prix courant ni nom actualisé non sourcé. Aucun devis historique recalculé.
Le writer produit les références M10 existantes; la page ne les republie pas et n’envoie rien
aux fournisseurs. Ce raccord n’implémente pas extraction courriel ou formats réels de fournisseurs.

## Permissions, risques et gates Nathan

Console admin SQL/session seulement, sans nouveau rôle appareil/MCP/agent. CSRF avant T1;
contrôle SQL et expiration aprèsrendu. Rejet de paramètres query, champs supplémentaires ou
dupliqués, faux nonce/action, CSV différent, mapping/document/fournisseur modifiés ou source
périmée. Erreurs fixes sans CSV/prix/contact sensible. HTML échappé, no-store/CSP et masquage
de toute query Uvicorn, slash final compris. Reçu parent/enfants fermé et typé, jamais simple
confiance dans le retour T1. Le reçu est une preuve calculée, pas une authentification fournisseur.

Aucune intervention Nathan nécessaire pour ces corrections réversibles et fixtures. La future
utilisation sur listes réelles reste soumise à la validation/politique autorisée. Aucun import
réel, courriel, commande, achat, paiement, nouvelle source/droit, production, merge ou déploiement.

## Tests, statut et suites

Vrai rouge TestClient avant code, puis aperçu CSV → confirmation explicite2lignes → versions,
réceptions, audit/outbox → rejeu exact après écriture ultérieure. Refus RBAC/CSRF/action/nonce,
champs/media/UTF8/tailles et changement d’intention. Rollback sur second enfant, mauvais résultat,
reçu corrompu, gabarit surdimensionné, révocation ou expiration finale. Source notes hors HTML et
stockage; XSS échappé; journaux privés. Régressions existantes d’aperçu/T1 réutilisées sans somme.

Préflight M10 natif frais `price-import-confirm-http-m10-preflight-v1` acquis dans instance privée
vide, contexte versionné épinglé; aucune revendication de mémoire projet. QA privée bornée
SourceRO/CPU1/1Gio/96tâches/600s/réseau refusé. Statut initial HTTP : non implémenté; produit,
M6 et CRM-14 restentPARTIAL. Suites : qualifier la confirmation HTTP, puis formats/courriel réels
sous portes propres et navigateur réel. Aucun compte de tests ne qualifie le produit entier.

## Qualification locale et état final de cette tranche

La route et le formulaire sont implémentés. QA finale `price-import-confirm-http-v5` :
118PASS/35,55s, dont28nouveauxHTTP,17aperçuHTTP,31lotprivé,23préparationprivée et19conformité.
La cohorte71PASS compatible est réutilisée sans addition; la phase63cas/62PASS et son échec d’assertion interdisant
à tort le bouton de déconnexion est distinct des défauts produit. Contrôle natif306outils,
177déclarés, aucune portée ajoutée. Le writer de saisie, le T1 de lot et les contrats purs
restent inchangés; le T0 annonce désormais CONFIRMATION_EXPLICITE_REQUISE.

Preuve métier : aperçu multipart2lignes sans écriture → clic explicite avec même CSV →
2versions et2réceptions, puis écritures ultérieures et rejeu affichant exactement le même
reçu historique sans modification SQL. Les notes libres sont absentes de l’HTML et de toutes
les tables. Le vrai drainage M10 des références du lot est réutilisé dans la cohorte locale.
Les contrôles de rendu/résultat/reçu, révocation et expiration finale, deuxième enfant refusé,
CSRF, faux nonce/action, fichier/mapping/source/préparation changés et champs/media/UTF8/tailles
sont vérifiés sans écriture résiduelle. Référence documentaire XSS échappée, queries masquées
y compris slash final. Formulaire absent pour lot partiellement invalide.

Revue statique indépendante des transactions, rejeu, intentions, sources et permissions :
aucun constat concret résiduel à la revue. Revue root : trois erreurs CSV client classées503
ont été reproduites puis corrigées400; limites413, état serveur incohérent503 et conflit409
restent distincts. Ancien avertissement de confirmation absente reproduit puis remplacé par
confirmation explicite requise. Artefacts conservés dans le chantier :
`PRICE-IMPORT-CONFIRMATION-HTTP-LOCAL-QUALIFIED.json`, logs/RESULT/RECEIPT/XML et sourcepins
de chaque phase, rouges compris. QA SourceRO/CPU1/1Gio/swap0/96tâches/600s/réseau refusé.

Statut : parcours HTTP/SQLite qualifié localement, sans navigateur réel dans cette preuve.
M6, CRM-14 et produit restentPARTIAL. Aucune donnée ou liste de prix réelle utilisée, aucun
prix officiel appliqué, aucun courriel/achat/paiement/déploiement. CI globale du parent publié
en cours au dernier relevé; aucun PASS global revendiqué. Prochaine étape : qualification
visuelle/navigateur sous harnais privé autorisé et sandbox effectif (ancien échec sandbox
Chromium reste historique), puis détection/extraction courriel et formats fournisseurs sourcés
sous portes propres. Pas de rejeu de l’ancien lancement Chromium ni de suppression du sandbox.

## Parcours navigateur intégré sur fixtures (qualification complémentaire)

Depuis la même source03725737, un serveur ASGI neuf et une base SQLite fictive isolée ont
été exercés dans le navigateur intégré via Cua. Connexion admin fictive → choix réel du CSV
par dialogue fichier → mapping/séparateur explicites → aperçu2lignes A_REVOIR → rechoix du même
CSV → clic de confirmation → reçu visible HTTP200. CapturesJPEG et textes DOM conservés :
`crm-import-browser-20261028-r1/apercu-v1.jpg` et `recu-v1.jpg`. La preuve SQL après réponse
constate2tarifs/2réceptions, +3réclamations/+2audits/+2événements source par rapport à l’amorçage.
Aucun format réel fournisseur ou donnée d’entreprise; ni courriel, achat ou finance exécutés.

Harnais serveur : SourceRO, homes/tmp privés avant imports, CPU1/1Gio/swap0/96tâches/TTL900s,
IPv6 refusé et syscall connect sortant refusé par noyau, vérifiés avant imports métier; écoute
entrante127.0.0.1 sur port OS exclusif. Navigateur hors unité serveur, actions limitées à cette
origine fictive. Un premier amorçage a échoué sur un mauvais nom de variable de harnais avant
migration/utilisateur; tentative suivante distincte corrigée, sans rejeu du premier reçu.
L’ancien lancement Chromium CLI échoué n’a pas été relancé et aucun sandbox n’a été désactivé.
Unité serveur possédée arrêtée, PID absent et état inactive/dead relus.

Limite explicite : le retour arrière sur le POST no-store produit ERR_CACHE_MISS dans ce
navigateur; la navigation suivante et fermeture explicite ont été refusées par sa politique
de page interne data:. Aucun contournement; onglet temporaire non marqué pour conservation,
nettoyage automatique de fin de tour attendu, non encore constaté. Le rejeu navigateur reste
NON VÉRIFIÉ; le rejeu HTTP natif118PASS garde sa propre preuve, sans addition des populations.
Preuve : `PRICE-IMPORT-CONFIRMATION-BROWSER-QUALIFIED.json`. Parcours nominal navigateur vérifié,
qualification navigateur complète ouverte; produit/M6/CRM-14 restentPARTIAL.
