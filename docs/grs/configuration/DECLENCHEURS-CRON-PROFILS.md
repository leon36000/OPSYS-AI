# Intentions cron des spécialistes — phase 1

Cette tranche rend les déclencheurs cron **déclarables**, pas encore exécutés.
Elle conserve une intention humaine durable et prépare la déclaration du scheduler
natif Core. Elle n'appelle ni CLI, Gateway, modèle, publication ni paiement.
Le consommateur de remise et ses leases restent à raccorder séparément.

## Autorité et configuration

`opsys.agents_declencheurs.demander(deps, profil_id, par=..., revision_attendue=...,
fuseau=..., mutation_id=...)` exige une personne active propriétaire ou admin,
relue dans la base. Le profil doit être actif, à la révision exacte attendue.
Les outils, limites, responsabilité et déclencheurs viennent du registre existant ;
les intentions ne deviennent pas un deuxième canon de configuration.

Le fuseau IANA est explicite et conservé dans l'intention ; aucun fuseau de la
machine n'est supposé. Le sous-ensemble cron initial est numérique à cinq champs :
nombres, `*`, listes, intervalles et pas positifs. Les noms de jours/mois et
syntaxes avancées sont refusés par cette tranche. Le scheduler natif devra valider
la déclaration lors de sa remise ; aucun calcul maison du prochain créneau.

La classification mémoire serveur R33 est relue. Une identité de profil absente
ou classée `client_session` sans contexte client autorisé est refusée, sans repli
global. L'empreinte concerne le binding de ce profil : l'ajout d'un autre profil
ou département ne révoque pas une intention sans rapport.

Les outils de la projection sont ceux du profil, vérifiés par le contrôleur
d'admission existant. Cette tranche cron interne refuse les outils T2/T3 et les
niveaux nécessitant une décision humaine (N3–N5) ; elle ne change pas leurs droits
sur les autres parcours. Aucun outil builtin `exec`, canal ou serveur libre n'est
ajouté. Une liste vide reste vide. Les plafonds et la réservation de tokens seront
contrôlés par l'admission native **avant chaque stream**, pas réservés fictivement
au moment de déclarer un cron.

## Rejeu et retrait

La clé native stable contient l'identité canonique de l'instance, le profil, sa
révision, l'empreinte du cron et le fuseau. Même commande et même `mutation_id` :
reçu identique après revalidation vivante. Changement de payload : conflit.
Un reçu ancien ne réarme pas une intention à retirer ou périmée.

Une nouvelle révision crée une nouvelle clé. Les anciennes intentions sont
conservées `a_retirer`. `retirer(...)` peut demander le retrait d'un profil devenu
inactif, sans déclarer son job Core supprimé. Le futur transport devra trouver
l'ID natif par la clé de déclaration puis confirmer sa désactivation/suppression.
La projection ne transforme jamais un retrait demandé en retrait accompli.

`projeter(deps, intention_id, par=...)` revalide avant et après construction :
acteur opérateur, auteur humain de l'intention, profil/révision/empreinte, binding
mémoire et outils. Elle produit `cron.add` et un argv natif structuré : agent exact
`opsys-agent-ID`, session `isolated`, timeout 120 s et `--no-deliver`. Elle omet
`enabled` pour préserver le rejeu déclaratif natif sans réarmement. Le message ne
copie pas la responsabilité privée : il référence le mandat canonique du profil.
Aucun secret, modèle, rôle, commande shell ou credential Gateway n'est projeté.

## Transactions et bornes

Les fonctions gèrent `stockage.transaction` et son `BEGIN IMMEDIATE` SQLite avant
lecture/écriture. PostgreSQL est explicitement refusé avant ouverture ; aucune
preuve de concurrence PostgreSQL ou d'atomicité distribuée OPSYS/Core.

Migration additive `0019`, après `0018` : intentions et commandes uniquement.
Profil, identité d'instance et journaux existants restent leurs canons. L'intention,
son reçu idempotent et la trace d'auteur sont écrits dans la même transaction.
Une erreur annule l'ensemble ; aucun nettoyage silencieux du backlog.

Les comptes SQL plafonnent 16 intentions à déclarer et 100 intentions non terminales.
Ce n'est pas un compte de jobs effectivement actifs dans Core : le futur transport
doit réconcilier les retraits avant de déclarer les remplacements.
`lire_en_attente(par=..., limite=...)` compte en SQL et retourne au maximum dix
résumés, avec le nombre omis. Les tailles JSON de profils sont vérifiées en SQL
avant lecture, puis en profondeur/nœuds/types/nombres finis. Les clés JSON dupliquées
du profil ou d'un reçu sont refusées, sans modifier le codec global. Projection ≤16 KiB.

## Portée actuelle

Pas de nouvelle route UI/MCP ni d'activation d'autonomie par cette API interne.
`execute=False` et `execution_core=non_observee` restent explicites. Un administrateur
peut lire l'état de remise ; cela n'établit ni validité du modèle ni qualité métier.
La phase suivante doit qualifier transport native hors SQL, permission contrôleur,
leases/fencing, réponse perdue, retrait vivant et reprise. Aucun job autonome,
fournisseur, Gateway, Docker ou VPS n'est qualifié par cette phase SQLite.
