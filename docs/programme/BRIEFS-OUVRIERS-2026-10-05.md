# Briefs courts pour ouvriers IA

Format de délégation pour un patch métier borné. Le chef de projet choisit le lot et contrôle
la livraison; aucun consensus de modèles ni validation d’un fournisseur extérieur n’est exigé.
Un modèle disponible ne reçoit que le contexte nécessaire au lot. Ces consignes ne modifient
aucun budget runtime du produit et ne constituent pas une mesure de tokens économisés.

## Brief à transmettre

1. **Résultat métier :** un parcours concret avec lead/devis/chantier/facture, et ce qui doit
   être observé à la sortie. Nommer les critères qui restent hors périmètre.
2. **Sources :** chemins exacts des outils réutilisés, garde d’accès, lecteur de registre et
   test du parcours. Lire ces contrats avant d’écrire une doublure ou un adaptateur.
3. **Frontières :** acteur authentifié et cible, actions autorisées, champs interdits,
   états attente/refus, bornes de données et de sortie. Un rôle passé en argument n’accorde pas un droit.
4. **Contrats réels :** relever l’enveloppe et les types de retour, les clés exactes et la
   méthode publique du registre. Distinguer vue détaillée, résumé et charge événement :
   leurs clés diffèrent même lorsqu’elles décrivent le même chantier. Un champ conceptuellement utile n’existe pas nécessairement dans la réponse.
5. **Patch :** réutiliser les services existants; ne pas créer un second CRM, calcul financier
   ou moteur de mémoire. Expliquer une dépendance nouvelle par l’appel réellement effectué.
6. **Preuve :** au moins un parcours traversant les vrais outils et leur sérialisation,
   puis les refus pertinents. Une doublure teste une branche, elle ne prouve pas une intégration.
7. **Livraison :** fichiers préparés, préimages/SHA, patch, tests pertinents et limites.
   Geler une livraison identifiée; fournir une nouvelle version après correction. Aucun log écrasé.

## Retours à demander au worker

Le design initial ne doit contenir que les décisions nécessaires : source de vérité, jonction,
permissions et premier test. La livraison précise les écarts constatés et les preuves réellement
produites; pas de liste de qualités supposées du modèle ni de promesse d’autonomie complète.

Le chef de projet confronte les branches aux contrats réels avant promotion et exécute les contrôles
pertinents sur une source gelée. Une erreur de fixture se corrige sans affaiblir l’assertion métier.
Une erreur de contrat se corrige dans le patch et dans le cas traversant les vrais outils.
La délégation reste utile seulement si elle réduit le travail total à qualité équivalente.


## Préparer un cas traversant les composants

Avant de livrer un test, dérouler statiquement son montage : acteur créé, connexion et rôles,
configuration explicitement active, routeur réellement inclus dans l’application, source admissible,
valeurs du candidat, action humaine, puis état attendu. Réutiliser la fixture du parcours voisin
avant d’en fabriquer une autre. Un double de moteur OCR doit encore passer le véritable décodeur,
le contrat du bundle et les contrôles de provenance.

Lire le texte actuellement rendu avant d’écrire une assertion de régression native. Ne pas remplacer
un texte compatible pour satisfaire une attente inventée dans le test. Les références d’un candidat
OCR et les fragments PDF natifs sont deux formats distincts : vérifier chacun dans son propre parcours.

Pour les doubles MCP, conserver les arguments réellement reçus, borner les réponses simulées et
vérifier nombre d’appels, cible et état. Une cause observée dans un harnais de test ne démontre pas
un défaut du framework : distinguer observation, hypothèse et cause reproduite. La preuve HTTP vers
le vrai serveur reste nécessaire à une jonction entre TypeScript et Python.

Le coordinateur attribue chaque résultat à un fichier complet, conserve les échecs de montage,
et associe toute correction à une cause et à ses préimages. Un rapport de sous-agent sans exécution
reste une préparation; les contrôles après intégration déterminent le statut du livrable.

## Préserver l'identité et les états lors d'une reprise

Un reçu d'admission valide et un usage fournisseur inconnu sont deux observations distinctes.
Le brief doit définir les états séparément, conserver une réserve incertaine et interdire
d'inventer un résultat métier. Une clé de déduplication déjà enregistrée garde son identité :
changer longueur ou domaine de hash exige une stratégie de transition, pas une substitution silencieuse.

Pour un worker SQLite, réutiliser le nettoyage asynchrone du propriétaire et attendre sa fermeture
avant de rouvrir une base. Pour une vue HTTP sous préfixe, relire le contrat `Location` et le
`base_url` de la fixture avant de construire l'URL suivante. Ces contrôles empêchent les faux
échecs sans affaiblir les assertions métier.

Décrire explicitement chaque frontière de panne : un effet distant peut précéder le journal
local. L'outbox ne garantit pas seule l'absence de perte ou le exactly-once ; distinguer le rejeu
du dépôt M10 du rejeu de l'outil ayant causé l'effet. Le second reste bloqué sans preuve
d'idempotence ou rapprochement avec la même clé.
