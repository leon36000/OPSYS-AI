# Réapprovisionnement courant M6 — contrat de continuation

Parent publié : `4ee2d616c1863df19c06c3560a4d7c1cb7727ec9`. Travail isolé dans `OPSYS-AI-m2-notes-20261008`, sans modification du clone R pendant sa CI. Décision technique dans l’autorisation de Nathan de poursuivre et prendre les décisions ; OPSYS-AI reste PARTIEL.

Le besoin est existant : lire dans Stock les articles déjà constatés par M6, leur état courant et ce qui manque à leur configuration. La file À voir possède déjà les alertes mais les réduit en résumés. Le digest historique par chantier et ses seuils fournis par l’appelant restent séparés. Aucune commande, modification de seuil ou écriture n’est créée par cette lecture.

## Sources et règle

Réutiliser `reapprovisionnement.evaluer` et `lire_parametres`, `stock.deriver_disponibilite`, `reservations.reserve_par_article`, `emplacements.hors_main_par_article`. Aucun nouveau calcul côté mobile. Le stock est théorique, tous lieux ; en main = théorique − hors main, disponible = en main − réservé. Les paramètres viennent du seul `department.yaml` M6, `configuration.reapprovisionnement.articles`. La configuration réelle initiale vide reste vide.

Couverture : articles présents dans `besoins_commande`, dernier constat choisi par rang durable du registre, puis ordre strict des derniers rangs décroissants (pas chronologie des dates). Inclure les quatre états : `stock_bas`, `stock_suffisant`, `seuil_absent`, `configuration_invalide`. Une réception ou réservation peut changer l’état courant sans nouveau constat. La date du dernier constat n’est pas celle du calcul et n’est pas présentée comme telle. Aucun article jamais constaté n’est implicitement évalué. Aucun inventaire physique, homogénéité d’unité, saison, délai fournisseur ou cause d’écart n’est déduit.

## Interface prévue

`m6_lire_reapprovisionnement_appareil` : DEVICE seulement, personne active et rôle admin courant avant config/registre/bus ; T0/N0. Arguments requis et fermés `{decalage, limite}`, entiers stricts, 0…10 000 et 1…8. Aucun seuil, historique, rôle ou auteur dans le corps.

DIRECT entière : `articles`, `pagination` (même contrat courant que les pertes M6), `source_configuration`, `sources_registres`, `couverture`, `borne_caracteres`, `taille_caracteres`. Plafond 5 400 caractères de l’enveloppe complète, diminution de page puis refus nominal si rien ne tient. Plafond réel Cap refuse sans transaction de fallback ni artefact. Quota de sources 10 000 lignes combinées après copies, sans prétention de borne mémoire avant copie.

Article fermé : `materiau_id`, `statut`, `chiffres` (`stock_theorique`, `hors_main`, `en_main`, `reserve`, `disponible` en textes décimaux canoniques), `seuil_reapprovisionnement`, `quantite_cible`, `quantite_a_commander` (textes ou null), `stock_negatif` (vrai exactement si `en_main < 0`, même en configuration absente), `code_configuration`, `unite` (null), `unite_dernier_constat` (source ou null), `dernier_constat`. Les paramètres absents/inutilisables restent null ; la quantité proposée n’apparaît que pour le stock bas conforme à la règle existante, jamais pour du stock en main négatif. Une quantité disponible négative est gardée, jamais ramenée à zéro. Le champ historique `stock_theorique` du verdict réapprovisionnement désigne son argument en main ; les cinq chiffres de cette façade viennent de `stock.deriver_disponibilite`, sans renommer ce champ en total.

Dernier constat fermé : `reference` (`registre: besoins_commande`, rang réel, `empreinte_snapshot` du contenu copié), `type_entree`, `evenement_declencheur`, `horodatage`, `chantier_id`. Ce registre ne conserve ni hash ni empreinte ; celle-ci est calculée pour la lecture et désignée comme snapshot, jamais tête de chaîne ou empreinte historique conservée. Rapprocher le dernier constat de la publication M4 réelle (type, producteur, catalogue, identifiant, date) et d’au moins un mouvement de déclaration du même WCT/article/chantier. Un reçu M6 peut être absent légitimement : la déclaration relit M4 et peut précéder la livraison du WCT à M6. Ne pas exiger un reçu absent ; vérifier celui qui existe. L’identité composée `constat_id` reste vérifiée côté serveur, sans imposer une limite arbitraire à cet identifiant composé.

Source configuration : chemin fixe du manifeste et du bloc, SHA-256 du fichier effectivement lu. Sources registres : nom, nombre de lignes et empreinte du snapshot explicitement désignée comme telle, jamais une tête durable inventée. Aucun coût, payload financier, emplacement individuel, membre d’équipe ou contenu brut de configuration exposé.

## Validation et mobile

Toute source requise illisible, corrompue ou incohérente produit un refus nommé sans filtrage silencieux, réparation ou ancienne version ressuscitée. Vérifier chaînes et schémas, rangs et liaisons, nombres finis, réservations et transferts ; garder la sémantique des règles existantes. Reprendre le contrat de codepoints/Unicode des pertes M6, sans normaliser les identifiants sources. Les précisions décimales et les grandes valeurs nécessitent des tests de frontière et un refus explicite si la projection ne peut les représenter dans sa borne.

Carte dans la vraie page Stock : lecture explicite, page courante remplaçante, sources et limites fr-CA/en-CA. Aucun cache, dépôt, SQLite, intention ou outbox nouveau. Capturer autorité/session et réseau avant l’appel ; fermer les réponses et callbacks après changement de personne, jeton, rôle, focus ou génération réseau, y compris A→B→A. Ne pas afficher d’ancien état après un refus connu. Garder les globales Stock et Pertes/Alertes déjà qualifiées.

## Preuves requises

Rouge utile puis vert : outil absent, plafond Cap avec absence d’artefact ; égalité au seuil ; seuil absent, bloc invalide et article invalide ; réception/réservation modifiant l’état courant ; stock en main négatif avec proposition null ; article hors couverture ; dernière position durable et lien WCT ; corruption/NaN/Infinity/quantité booléenne ; gros volume/Unicode/pages ; retrait admin avant les sources. Registres intégralement inchangés durant les lectures et reprise identique après redémarrage.

Fixtures SQL fictives issues du vrai producteur puis lecteur mobile fermé, services avec vraie configuration/protocole, rendu dans la vraie page Stock et courses d’autorité. Types, Ruff, vérificateur métier, suites affectées et mobile complet intégrés ; Android réel. Native DEVICE/Gateway/MCP séparé du rejeu et du téléphone. Nouveau commit privé puis CI exacte ; aucune attribution d’une CI parent aux nouveaux octets.

La validation des schémas réels peut préciser les sous-objets avant la première implémentation ; toute évolution est conservée avec préimage et disposition. M6.13 profond, inventaire physique, preuves/photos, coûts et achats réels restent suivis avec leurs critères propres.

## DTO fermé scellé avant producteur (r1)

La définition exacte des sous-objets est dans `qualification/M6-reapprovisionnement-backend-r1/contrat-dto-r1.json`. `sources_registres` est un tableau de quatre objets `{registre,lignes,empreinte_snapshot}`, dans l’ordre `besoins_commande`, `principal`, `reservations`, `emplacements`. `source_publications` est exactement `{evenements:{type:"m4.travaux_termines",lignes,empreinte_snapshot},recus_m6:{registre:"wct_recus",lignes,empreinte_snapshot}}`. Les copies des reçus M6 et des publications ciblées comptent aussi dans les 10000 lignes. `dernier_constat.reference_bus` est `{type:"m4.travaux_termines",evenement_id}` réellement relu.

`couverture` est exactement `{articles:"articles_deja_constates",stock:"theorique_disponible",unites:"homogeneite_non_confirmee",horodatage:"dernier_constat_sans_date_calcul",plafond_lignes:10000}`. Le fichier de `source_configuration` est le chemin fixe `departments/m06-material-control/department.yaml`, son `chemin` est `configuration.reapprovisionnement.articles`, et son `sha256` porte les octets effectivement copiés. Un fichier non copiable refuse nominalement ; un fichier lisible mais malformé donne `configuration_invalide` avec ce SHA et un code canonique, jamais son texte brut. Les seuil/cible configurés d’un article suffisant viennent de `lire_parametres` : leur absence dans le verdict `evaluer` ne les rend pas inconnus. Aucune valeur numérique n’est rejetée seulement pour dépasser MAX_SAFE_INTEGER quand sa projection est un texte décimal.
