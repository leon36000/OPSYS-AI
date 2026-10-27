# M6 — Notes d’achat internes, CRM-09 (tranche serveur)

## Objectif, pourquoi et audit préalable
Le secrétariat veut décrire les achats d’un chantier en texte libre sans sélectionner des articles. L’inspection préalable de `fb6e9947`, conservée dans `parallel-wave2-20261027-r1/m6/audit-plan.md`, confirme que les PO existants imposent des lignes structurées et calculent le manque de matériaux. Une note ne doit pas devenir un faux article, prix, PO ou mouvement de stock. Le contrat initial et ses sources sont conservés dans `parallel-wave1-20261027-r1/m6/contract.md` (preuves locales hors dépôt).

## Architecture, fichiers et données
`departments/m06-material-control/src/m6_material_control/notes_commande.py` contient validation, versions et projection. `outils.py` apporte l’identité SQL, les besoins M6, l’horloge serveur et le registre durable `notes_commande`. Aucune nouvelle table SQL. `src/opsys/capacites.py` relie l’intention de transport et contrôle l’autorité avant le cache ; `approbations.py` masque `texte_libre` dans les traces tout en conservant l’empreinte des vrais arguments. Le registre est la source canonique ; aucune promesse de chiffrement de cette note n’est ajoutée.

Une version conserve note_id, devis_id, chantier_id, texte exact, révision, auteur, date serveur, référence précédente, empreinte chaînée et intention de mutation. L’ancrage est figé. Une correction ajoute une version ; les anciennes versions restent lisibles. Le registre accepte au plus 10 000 versions ; au-delà, refus explicite, sans prétendre servir un historique illimité.

## Outils et workflows
- `m6_enregistrer_note_commande(note_id, devis_id, texte_libre, revision_attendue)` : première révision attendue 0, puis révision courante. Texte non vide jusqu’à 20 000 caractères, espaces/accents/retours conservés ; contrôles refusés sauf CR/LF/TAB. Auteur et instant exclusivement serveur.
- `m6_lire_note_commande(note_id, revision?)` : version courante ou historique exacte ; absence et corruption explicites. Une lecture ne prend aucune enveloppe de mutation.

Ces outils utilisent les transports de capacités existants. Aucun nouvel endpoint HTTP de cockpit, formulaire ni écran n’est livré ici. Flux : admin authentifié → besoins M6 du devis connus → chantier réel connu → contrôle version/intention → append et audit atomiques → reçu sourcé. Un prévu vide connu est accepté sans sélection de catalogue ; un devis absent ou sans chantier est refusé. Une note sur un simple lead reste à concevoir via référence M2 autorisée.

## Permissions, rejeu, intégrations et risques
Admin actif réel uniquement, avec identité appareil/console établie par la plateforme. Aucun rôle auteur dans les arguments, pas d’agent anonyme. Le même appareil/clé/contenu restitue la version initiale, même après une correction ou expiration du reçu de transport. Autre contenu ou autre auteur sur la même intention : refus. Révocation admin ou compte inactif : aucun texte restitué. Deux corrections concurrentes sur une révision : une seule réussit. Note et audit s’annulent ensemble en cas de panne.

La limite de sortie du consommateur reste effective : défaut 6 000 caractères au socle. Un texte long nécessite un consommateur explicitement dimensionné ; sinon refus avant écriture, sans artefact partiel contenant la note. Les lectures et reçus sont également contrôlés. La borne des appels métier directs est 131 072 caractères de réponse sérialisée, distincte de la longueur maximale de note.

Aucun PO, réservation, prix fournisseur, stock, envoi M1, coût M5, événement M8 ou mémoire M10 n’est produit. La note peut décrire un besoin, mais son texte ne constitue pas un coût validé. M10 : le préflight existant a été lu ; il contrôle une structure et ne certifie ni faits ni permissions. Le garde Core reste fermé pour une mutation N3 sans contrat devis→affaire résolu. Aucun faux scope ni désactivation du garde : intégration agent/M10 encore à réaliser.

## Gates Nathan
Enregistrer cette note interne ne passe aucune commande. Structuration proposée, conversion en lignes, validation de PO et envoi fournisseur devront conserver les contrôles M6/M1 existants. Aucun engagement financier implicite. Les limites de cette tranche ne réduisent pas l’ambition M6 complète.

## Tests, statut et prochaines étapes
31 cas ciblés passent avec vrais outils, SQLite durable et Capacites : texte long et bornes, permissions, rejeu/cache expiré, révocation, auteur différent, versions/ancrage, course de deux connexions, rollback, corruption, quotas et absence de texte brut dans les journaux. Fixtures autonomes fictives ; aucun import d’un autre fichier de tests. La réouverture est une nouvelle connexion, pas un redémarrage de processus. Une panne d’audit injectée sert à vérifier le rollback ; elle n’est pas présentée comme panne de production.

Statut **PARTIAL** : capacité serveur locale, aucun écran ni qualification PostgreSQL. La note n’est ni un PO ni un courriel envoyé. Prochaines étapes : formulaire secrétariat avec choix d’un ancrage connu, historique et protection contre les conflits ; contrat d’ancrage avant chantier ; M10 devis→affaire ; proposition de structuration puis conversion explicitement validée. Sources de QA : `work/chantier-opsys-20261010/m6-notes-qa-20261027-r1/`.


Vérification finale intégrée : **200 tests réussis, 5 SKIP PostgreSQL**, sur une seule population de 205 cas. Les 33 cas des notes sont inclus ; ne pas additionner les tentatives. Les 5 SKIP gardent leur motif historique : Docker est inaccessible dans ce harnais sans réseau ni socket Docker, ce qui ne prouve pas une panne de l’hôte. Le transport MCP reste non qualifié : la première sélection de régression n’a pas pu collecter trois fichiers faute du paquet `mcp` dans cet environnement privé ; ils ne sont pas annoncés verts. La reprise couvre explicitement M6 et les capacités/journaux sans dépendance MCP. Lint des fichiers sélectionnés et vérificateur passent.

La revue indépendante a trouvé un chemin sans enveloppe de mutation qui pouvait créer une demande d’approbation contenant la note brute. Deux tests SQLite/Capacites ont reproduit ce défaut avant correction (`notes-no-meta-red-v1`). Le garde exige maintenant l’intention authentifiée avant tout dispatch/création de demande. Les deux tests passent dans la régression finale `notes-regression-v2`, avec vérification de l’absence de demande et de texte exposé par la liste générique. Ce défaut du candidat local n’a pas été publié.
