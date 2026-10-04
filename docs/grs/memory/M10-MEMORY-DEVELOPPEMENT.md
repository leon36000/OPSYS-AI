# M10 — mémoire de développement

La tranche développeur utilise le registre canonique append-only de maillons
`m10-memoire/developpement` dans la base OPSYS de l'instance. Prompts exacts et empreintes,
versions de plans et étapes, décisions sourcées, changements, preuves de tests et rapports sont
liés par des relations durables. Les vues de recherche SQLite sont temporaires en mémoire; aucune
base de vérité secondaire ni migration de schéma n'est ajoutée. Les sauvegardes/restaurations
canoniques emportent ces maillons.

Le parcours est `prompt → plan versionné → exécution → postflight`. Le preflight retrouve les
éléments « must know », les sources de preuve, les versions/fraîcheurs, relations et contradictions.
Le postflight capture le statut, les changements, tests et rapport; les rejoués identiques sont
idempotents, les affirmations contradictoires restent conservées et visibles. Sans preuve
disponible, le rappel indique `unavailable`/`unknown`, sans fabriquer de complétude.

Un postflight peut contenir un diagnostic facultatif avec exactement les champs
`incident_id`, `symptom`, `cause`, `cause_status`, `prevention`, `source_refs` et `observed_at`.
Les statuts de cause autres que `unknown` exigent des références de source. Ces champs décrivent
les assertions de l’auteur : `confirmed` ne certifie pas la cause et un résultat de test n’est pas
validé automatiquement. Les réponses postflight qui comportent ce diagnostic portent
`diagnostic_assurance: "author_assertion_unverified"`; les anciens postflights sans diagnostic
gardent leur réponse existante. Cette extension réutilise le maillon et les relations actuels; elle
n’ajoute ni API de stockage ni nouveau moteur de recherche. Elle ne change pas E05 ni ses mesures,
et n’établit aucun rappel général.

Le preflight expose aussi des compteurs et des indicateurs de limites/troncature. La fenêtre des
élements `must_know` reste plafonnée à 30; les contradictions sont recherchées parmi les claims
candidats même si leur claim est hors de cette fenêtre, puis leur sortie est bornée à 30 claims et
deux preuves par claim. Une contradiction trouvée hors de la fenêtre `must_know` est signalée avec
ses preuves disponibles, sans être injectée comme élément `must_know`. Les plafonds de sortie ne
bornent pas universellement le registre, les candidats examinés, les sources du dépôt ou le coût de
lecture/reconstruction du journal. Les compteurs et `truncated` rendent des omissions visibles; ils
ne certifient pas que le contexte ou les preuves sont exhaustifs. Le statut compatible `available`
signifie qu’un contenu pertinent a été trouvé, pas que tout le contenu pertinent l’a été.

### Sélection ciblée par références et lignées

Le preflight de développement peut ancrer un événement par égalité exacte entre un chemin fourni
et une valeur dans les champs structurés de référence (`source_refs`, `files`, `fichiers`, etc.).
Un chemin proche (`foo.py.old`) ou mentionné seulement en prose n’est pas une ancre de fichier,
même si cet événement peut encore ressortir comme candidat lexical ordinaire. Les identifiants des
champs typés (`prompt_id`, `plan_id`, `decision_id`, `operation_id`) sont comparés aux tokens
entiers de `task`; un token identique à un `entity_id` peut aussi ancrer cet événement. Il faut donc
citer explicitement les identifiants dans la tâche : un mot courant qui coïncide avec un identifiant
reste une correspondance exacte et peut créer une ancre non voulue.

Depuis une ancre, le parcours suit uniquement les arêtes `superseded_by` persistées. Les événements
sont filtrés par module et statut avant traversal; une cible hors module ou inéligible bloque cette
branche et laisse la lignée non résolue. Une arête peut viser un événement dont l’`entity_id` a changé,
car la relation lie les identifiants d’événement, et la succession n’est jamais déduite du seul numéro
de version, de la date ou d’un identifiant stable. Une convergence de chemins n’est pas un cycle; une
boucle réelle, une arête bloquée ou une limite atteinte est signalée comme non résolue/omise.

La sélection rend au plus 30 éléments `must_know`, 30 liens et visite au plus 1 000 nœuds de lignée.
Les endpoints admissibles des lignées ciblées sont classés avant les anciennes ancres afin de garder
la version non remplacée dans la fenêtre quand elle y tient; avec 30 ancres et 30 endpoints, les
ancres anciennes peuvent donc être omises. Les compteurs `lineage_*`, `links_omitted`,
`candidates_omitted` et `truncated` exposent ces limites. Une lignée non résolue n’autorise pas à
deviner son endpoint et aucun plafond ne rend le registre exhaustif.

Le classement conserve d’abord la pertinence lexicale; la fraîcheur connue départage ensuite, puis
l’horodatage. La fraîcheur est calculée par dépôt, chemin et SHA-256 : deux snapshots du même chemin
ne partagent pas leur état `current`/`stale`. Une référence de chemin seule ne prouve pas qu’un
candidat soit lié au hash courant. La sélection reste relationnelle et lexicale; elle n’ajoute ni
moteur vectoriel, ni graphe externe, ni permissions nouvelles. La preuve ciblée et ses limites sont
dans le [rapport scratch r4](../../../../restructuration-opsys-2026-09-30/preuves/m10-preflight-selection-2026-10-01-r4/final/rapport-r4.md).

À titre de vérification du plafond de sortie, une fixture synthétique avec 31 claims contradictoires
et 3 preuves par claim a 93 preuves disponibles; le rapport en retourne 60 (30 × 2), donc
`evidence_omitted = 93 − 60 = 33`. Le sous-compteur d’omissions lié au plafond de deux preuves par
claim vaut 31; les deux autres preuves appartiennent au claim non retourné au-delà du plafond de
30 claims. Ces nombres décrivent cette fixture et ces plafonds, pas une mesure de rappel général ni
une promesse d’amélioration du rappel.

La fonction authentifiée `m10_memoire.developpement.auditer_developpement(repository=..., limite=...)`
fournit un rapport de contrôle non destructif : prompts courants sans plan, plans sans postflight,
relations vers une cible absente, sources devenues manquantes/modifiées/trop volumineuses et claims
contradictoires, chaque constat citant les maillons ou sources concernés. Les analyses sont plafonnées;
un rapport tronqué porte le statut `partial` et indique quels scans ont atteint leur plafond. Ce n'est
pas un scheduler nocturne, ne marque rien `done` et ne purge aucune preuve. Une fraîcheur devenue trop
volumineuse est détectée par taille et lecture hachée bornée; une source transformée en lien symbolique
est refusée sans suivre sa cible.

L'audit vérifie les cibles de relations hors de sa fenêtre via le registre entier : une cible existante
mais omise par la fenêtre est rapportée `relations_hors_fenetre`, jamais absente. Les claims sont
comparés dans leur espace `(module, claim_key)`, car un texte de claim identique dans deux modules ne
désigne pas la même assertion. Sans racine de dépôt fournie, le bloc `freshness` indique explicitement
`status: unknown` et compte les sources dont la fraîcheur n'a pas été vérifiée; cela ne signifie pas
qu'elles sont courantes. Le bloc expose aussi le total canonique des sources et les sources laissées
hors vérification par plafond; si aucune racine n'est fournie, tout le total est inconnu.

Les fonctions M10 revérifient dans le stockage canonique que l'appelant est une personne active
admin/owner. Le service fournit une factory `creer_router(...)` sous
`/api/memoire-developpement`; elle prend les callbacks de session/écriture authentifiés de la
console, vérifie l'état de rôle vivant, CSRF et construit le contexte d'appel côté serveur. Les
charges ne choisissent ni acteur, rôle, horodatage ni racine de scan. Le CLI autonome exige un TTY,
demande l'identifiant et le mot de passe avec `getpass`, puis appelle l'authentification OPSYS;
aucune variable d'environnement ne définit l'identité. L'intégration des pages/dashboard est
distincte de cette factory et doit être vérifiée dans l'application hôte.

Le raccord livré expose aussi `GET /api/memoire-developpement/audit?limite=100` (limite stricte 1 à 500,
aucun autre paramètre accepté). La session et le rôle admin/owner sont revérifiés avant la lecture;
la racine du dépôt vient de la configuration serveur. La console peut rendre le rapport avec
`memoire_ui.audit_contenu(rapport, prefixe)`, qui n'affiche que les constats, identifiants et empreintes,
jamais les prompts bruts. La commande `opsys metier memoire-developpement auditer [--depot PATH]
[--limite N]` exige la même authentification interactive que les autres commandes. Un résultat
`partial` retourne un code d'échec CLI afin que l'appelant ne le traite pas comme une vérification
complète. Ces interfaces restent des lectures non destructives; aucun correctif ou calendrier de
vérification automatique n'est exécuté.

Le scan est en lecture seule, limité aux fichiers Git suivis, avec exclusions et plafonds de taille;
il ne prouve pas l'exhaustivité du dépôt et ne lit pas les sources non suivies. Un scan depuis un
sous-répertoire conserve le chemin complet relatif à la racine Git, ce qui maintient la résolution
de fraîcheur et l'attribution du département. Chaque fichier passe par `fstat`/type régulier puis
une lecture en blocs limitée à `min(max_bytes, max_total_bytes_restants) + 1`; ce dernier octet permet
de détecter une croissance après le contrôle sans lire davantage. Les symlinks de fichier ou de
composant sont refusés avec `O_NOFOLLOW` lorsque disponible. Les contenus structurés masquent les
valeurs des clés sensibles reconnues exactement, sans masquer `token_count`, `retry_count` ou
`source_refs`. Les valeurs sensibles sont redigées ou refusées avant persistance. Le rappel actuel est lexical et fondé sur les
relations conservées : pas de recherche vectorielle du développement, ni de graphe externe, Temporal,
Qdrant ou Cognee. Ce lot est
un registre de travail reprenable, pas toute la mémoire M10 ni un dashboard complet.

Limite d'échelle connue : le helper reconstruit le journal canonique complet dans une vue SQLite
mémoire à chaque opération avant la lecture ciblée. Les fenêtres d'audit et de fichier sont bornées,
mais le coût de reconstruction du journal croît avec le registre; aucune migration ni nouvelle base
secondaire n'est introduite dans cette tranche.

Contrats et preuves : [rapport R17](../../research/R17-2026-09-30/M10-PREUVES.md),
[ADR-0010](../../decisions/ADR-0010-memoire.md).
