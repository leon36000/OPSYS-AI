# Centre privé de configuration

La page **Connecteurs** rassemble les dix départements, leurs paliers de modèles,
les plafonds de tokens et les profils de spécialistes configurés. Elle renvoie aux
pages existantes **Modèles**, **Agents**, **Budgets**, **Départements** et
**Approbations**. La configuration STT conserve son formulaire et son diagnostic
manuel ; consulter le centre ne déclenche aucun contrôle distant.

Un propriétaire ou administrateur actif peut consulter `/opsys/connecteurs` et
`/opsys/api/connecteurs`. Le rôle et l'état du compte sont relus dans la base avant
la lecture, après celle-ci et après le rendu. Les réponses portent `no-store`.
Les rôles employé, vendeur, client et agent système ne reçoivent pas cette vue.

## Ce que la page établit

La projection lit les manifestes chargés, les modes effectifs, les profils et les
plafonds canoniques existants, ainsi que le fichier de paliers choisi par le
serveur. Le JSON ajoute `resultat.configuration_dashboard`, version
`opsys.configuration_dashboard/v1`, à l'API de connecteurs existante.

Pour un palier, **présence déclarée** signifie uniquement que ses références
requises sont présentes dans l'environnement. Une valeur invalide peut être
présente : aucune authentification fournisseur n'est établie. La vue affiche les
noms de références, jamais leurs valeurs, les URLs, les DSN ou les identifiants
de modèles. Le catalogue des adaptateurs reste partiel ; une absence de ligne
ne signifie pas qu'aucune API n'est nécessaire au département.

Les dépendances, événements et espaces de mémoire sont déclarés par les
manifestes ; les politiques métier existantes décident des opérations autorisées.
La consultation ne crée aucune permission et ne change aucun canon.

## Activation et autonomie

**Profil activé**, **configuration projetée** et **tâche exécutée** sont des états
distincts. Le centre ne mesure ni le chargement du profil par Core ni ses
exécutions. Les déclencheurs de profils sont actuellement déclarés et non
raccordés à un consommateur autonome. Cette tranche n'ajoute ni ordonnanceur,
ni outbox, ni appel de modèle.

Les budgets affichés sont des plafonds de tokens, pas des coûts financiers.
Les plafonds entreprise des spécialistes ne couvrent pas universellement les
agents historiques. Leur absence est indiquée et l'admission d'une nouvelle
génération de spécialiste reste refusée selon son contrat existant.

## Bornes et diagnostics

La lecture compte les profils en SQL avant de sélectionner au maximum
50 résumés triés par identifiant ; le nombre omis reste visible. Les champs
libres responsabilité, outils, déclencheurs et historique ne sont pas chargés.
La projection accepte au maximum 16 départements et les quatre paliers existants.

Le fichier YAML et les réponses HTML/JSON sont limités à 64 KiB en octets UTF-8.
Le YAML est borné avant parsing, puis limité en profondeur et en nombre de
nœuds ; les clés dupliquées, cycles, nombres non finis et schémas invalides sont
refusés par un diagnostic fermé, sans contenu ni chemin privé. Une configuration
absente reste **non configurée**. Une configuration illisible ou excessive refuse
la réponse ; elle n'est pas remplacée par une configuration supposée valide.

Les limites concernent cette projection et ses réponses, pas la totalité des
lecteurs ou écrivains de configuration du produit. Les tests de cette tranche
utilisent SQLite et des personnes/configurations fictives ; ils ne qualifient
aucune connexion réseau, exécution autonome, installation VPS ou atomicité
PostgreSQL.
