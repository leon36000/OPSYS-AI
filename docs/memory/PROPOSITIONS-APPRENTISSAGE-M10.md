# Aperçu de tri des faits candidats M03

La route admin `/memoire/apprentissages-affaires` regroupe des événements POSTFLIGHT déjà présents
dans le registre M10 `affaires`. Elle compte les affaires distinctes par outil, résultat et code sur
365 jours; trois affaires font apparaître une ligne de tri. Les répétitions d'une même clé de dépôt
sont éliminées, tandis que plusieurs dépôts distincts d'une affaire restent des observations sans
augmenter le nombre d'affaires soutenant le groupe.

Ce parcours n'infère pas de cause ou d'efficacité. Il n'écrit aucun fait, n'active aucune procédure,
n'ajoute rien aux paquets des agents et ne lit pas la mémoire de développement. Les autres domaines
M10 restent hors agrégation. Les identifiants d'affaires ne sont pas rendus; les références sont les
`ligne_id` opaques des maillons. La liste des outils affichables vient des `Outil.nom` du catalogue
M03 chargé depuis son manifeste; les codes viennent du catalogue fermé `CODES_M3_LIST` de M03. Les
maillons portant un outil ou code absent du catalogue sont comptés comme omis, sans afficher leur
texte. Les faits candidats restent des candidats.

Une personne peut utiliser les tendances comme file de tri, examiner séparément les sources permises,
puis rédiger une procédure dans le parcours M03 existant. L'admission, l'indexation et l'activation
restent soumises à leurs contrôles humains, aux rôles, au CSRF et au CAS de version active. Les
résultats discordants ne sont pas arbitrés par cette page; le flux humain M10 de révision reste la
référence lorsqu'il existe deux assertions incompatibles.

Avant tout décodage ou copie Python, la lecture SQL vérifie l'ensemble des deux registres dans une
transaction SQLite, avec au plus 10 000 maillons combinés, 8 MiB au total et 64 KiB par maillon. Les
JSON à clés dupliquées, nombres non finis, structures profondes ou mal formées sont refusés avant
l'appel au codec typé déjà fourni par le stockage. Les chaînes Affaires et Événements doivent toutes
deux être valides. La relecture d'une tête commence par `length(CAST(maillon AS BLOB))`; un payload
au-dessus de 64 KiB est refusé avant sa sélection/décodage. Une seconde lecture compare les têtes
avant rendu et le rôle administrateur est revalidé. Une tête changée produit HTTP 409. La réponse a
`Cache-Control: no-store`.

Le contrat de cohérence n'est qualifié ici que pour SQLite. Le backend d'instance utilise une
transaction `BEGIN IMMEDIATE`; bien que cette route n'écrive pas, son snapshot borné peut brièvement
retenir le verrou d'écriture. PostgreSQL est refusé explicitement tant que l'isolation snapshot et la
course de revalidation des têtes ne sont pas qualifiées sur ce parcours.

Le rapport canonique (empreinte incluse) conserve toutes les références sources des groupes retenus.
Le rendu HTML affiche au plus 20 références par groupe et compte celles qui sont omises; la réponse
entière est limitée à 128 KiB UTF-8. Le rapport est borné à 20 groupes et son SHA-256 comprend version,
catalogues M03, cutoff UTC, têtes des deux registres et résultats triés. La taille de contexte M10 existante est en
caractères. Une comparaison de contexte future devra compter les octets UTF-8 du texte exactement
rendu, avec `len(serialisation.encode("utf-8"))`; aucune conversion en tokens n'est faite. Une mesure
de tokens exige le tokenizer, la révision et l'entrée réellement envoyée au modèle, et n'est pas
remplacée par une règle de trois sur les caractères.

Limite d'échelle : le préflight SQL ne matérialise pas un historique dépassant les plafonds, mais la
validation des chaînes et le décodage allouent ensuite une copie bornée pouvant approcher plusieurs
fois les 8 MiB d'entrée. Ce parcours n'est donc pas une preuve de capacité sur un registre massif;
un besoin supérieur exige un lecteur paginé avec validation de chaîne à tête cohérente.
