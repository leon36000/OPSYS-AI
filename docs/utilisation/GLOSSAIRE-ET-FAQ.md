# Glossaire et foire aux questions

## Glossaire

| Mot | Ce que ça veut dire |
|---|---|
| **Acteur système** (`opsys-systeme`) | Identité de service, sans session humaine, qui exécute des tâches internes réversibles (recalculs, tours du planificateur). Elle n'est pas une personne : elle ne peut jamais approuver quoi que ce soit. |
| **Approbation** | Décision d'une personne sur un geste que le système a préparé. Elle est signée, datée, journalisée, liée à ce que vous avez vu et valable une seule fois. |
| **Avatar** | Nom, rôle, voix et visage d'un département (Léa, Victor, Mathis, Gabriel, Sophie, Rosalie, Chloé, Olivier, Athéna, Mnémo). Seule la messagerie est disponible. |
| **Brouillon à confirmer** | Une écriture, une facture ou une fiche que le système prépare sans la rendre définitive. Une personne la confirme. |
| **CAI** | Commission d'accès à l'information du Québec. |
| **Console** | L'interface web d'OPSYS (approbations, départements, plateforme). Adresse `console.<votre-domaine>`. |
| **Control UI** | L'interface du Core où l'on clavarde avec les agents. |
| **Coffre de secrets** | Endroit chiffré où vivent les clés et mots de passe. Les agents n'en voient que des jetons opaques. |
| **Core** (OPSYS-CORE) | Le moteur d'agents (dérivé d'OpenClaw, licence MIT) : canaux, agents, interface de contrôle. |
| **Coût certifié** | Coût d'un chantier recalculé par un calcul déterministe, avec un statut (à jour, périmé, inconnu). |
| **CPA** | Comptable professionnel agréé. |
| **Département** | L'un des dix modules M1 à M10, chacun avec sa mission, ses outils et son avatar. |
| **Digest** | Empreinte numérique qui épingle l'image exacte d'un conteneur ; plus sûr qu'une étiquette de version. |
| **Double** | Simulation de test qui remplace un service externe (courriel, réseau social, modèle). Un parcours « prouvé sur doubles » n'a jamais parlé au vrai service. |
| **ÉFVP** | Évaluation des facteurs relatifs à la vie privée, exigée par la Loi 25 avant certains transferts de renseignements personnels. |
| **Empreinte** | Résumé cryptographique (SHA-256) d'un contenu : si une virgule change, l'empreinte change. |
| **Exécuteur** | Une tâche du planificateur (synchroniser les courriels, publier un article approuvé…). Inactif par défaut. |
| **Fail-closed** (« refus par défaut ») | Quand une donnée ou une permission manque, le système refuse et dit quoi fournir ; il n'invente pas de valeur. |
| **Gate / porte fermée** | Condition externe qu'il faut remplir (une décision, un accès, une validation) avant d'aller plus loin. |
| **Idempotence** | Rejouer la même demande ne produit pas un deuxième effet (pas de double envoi). |
| **Journal append-only** | Registre où l'on ajoute sans jamais réécrire ; certaines tables le font respecter par la base elle-même. |
| **Loi 25** | Loi québécoise sur la protection des renseignements personnels. |
| **Matrice d'exigences** | Tableau, par département, de ce que le produit doit faire et de ce qui est réellement prouvé. |
| **MCP** | Protocole par lequel les agents appellent les outils des départements. |
| **Migration** | Évolution contrôlée de la structure de la base. La « tête » est la plus récente (0086 aujourd'hui). |
| **Mode (ombre, supervisé, autonome)** | Niveau d'autonomie d'un département : à partir de quel niveau N un geste attend une approbation. |
| **N0 à N5** | Niveaux d'approbation : lecture, brouillon, tâche interne (automatiques) ; N3 validation d'une personne ; N4 le propriétaire ; N5 le propriétaire ET le professionnel. |
| **Outil** | Un geste précis qu'un département sait faire (ex. « calculer un devis »). Il y en a 666. |
| **Pack sectoriel** | Vocabulaire, services et barèmes d'un métier. `generique-pme` ou `renovation-exterieure-qc`. |
| **Passerelle (Gateway)** | Le service du Core qui reçoit les agents, les appareils et les canaux. |
| **Planificateur** | Tâches récurrentes sûres (synchronisation, envois et publications déjà approuvés), sous l'acteur système. |
| **Qualifié** | Rejoué avec preuves sur la vraie cible. « Qualifié sur conteneur fictif » n'est pas « qualifié sur un serveur ». |
| **Registre MCP** | Liste scellée des outils autorisés, avec l'empreinte de leur définition ; refuse un outil dont la définition a changé en silence. |
| **Rule of Two** | Règle de sécurité : un même tour ne doit pas cumuler contenu non fiable, accès à des données sensibles et action vers l'extérieur sans approbation. |
| **SBOM** | Inventaire des composants logiciels et de leurs licences (`docs/compliance/sbom.cdx.json`). |
| **Sas d'approbation** | Passage obligé d'un envoi ou d'une publication : la demande attend une décision, puis ne s'exécute qu'une fois. |
| **SQLite / PostgreSQL** | Les deux bases possibles. SQLite par défaut (une PME), PostgreSQL ensuite (plusieurs clients). |
| **VPS** | Serveur privé virtuel loué chez un hébergeur. |
| **WCT** | Abréviation interne de M4 pour le dossier de fin de travaux publié aux autres départements. |

## Foire aux questions

**Est-ce que le système peut envoyer un courriel ou publier sans mon accord ?**
Non. L'envoi d'un courriel (N3) et toute publication publique passent par le sas d'approbation. Le code d'envoi est séparé des outils des
agents, et l'acteur système n'exécute un envoi que s'il trouve une approbation humaine valide (72 heures pour un courriel, une heure pour
un article WordPress). Précision : aujourd'hui, **rien de tout cela n'a été essayé contre un vrai compte** (voir [limites](LIMITES-CONNUES.md)).

**Qui paie les fournisseurs et peut-on dépenser sans moi ?**
Les engagements de dépense (annonce payante, campagne) sont de niveau N4 : vous décidez. Le paiement d'une facture fournisseur est
**préparé**, jamais exécuté, par le système ; l'enregistrement d'un paiement est de niveau N5 (vous et le professionnel).

**Le système me donne-t-il des conseils fiscaux ou de placement ?**
Il prépare des brouillons, des calculs et de l'information générale. Tout avis comptable, fiscal, juridique ou de placement porte la
mention « À valider auprès d'un comptable (CPA) / professionnel qualifié ». Aucune règle fiscale du système n'est approuvée pour l'instant, et une
garde bloque toute recommandation personnalisée de titres.

**Les chiffres viennent d'où ? Peut-on se fier à un prix d'un agent ?**
Un prix, un solde, une date ou une quantité vient toujours d'un calcul déterministe testé, avec un reçu, jamais de l'estimation d'un modèle.
Quand une donnée manque, le système dit « inconnu » et ce qu'il faut fournir.

**Pourquoi tout démarre en mode « ombre » ?**
Parce que le produit est en consolidation et qu'aucune instance de production n'existe : le département propose, vous approuvez tout geste
à partir de N3. Passez à `supervise` seulement après une période d'observation ; évitez `autonome` tant que l'écart de règle noté dans les
[limites](LIMITES-CONNUES.md) n'est pas tranché.

**Mes données sont-elles envoyées à l'extérieur ?**
Seulement vers les services que vous branchez : un fournisseur de modèle infonuagique reçoit ce que l'on lui envoie, les modèles locaux non.
La Loi 25 exige une évaluation (ÉFVP) avant tout transfert de renseignements personnels hors Québec ; préférez un hébergeur canadien. Les
données réelles de clients ne servent jamais aux essais : tous les essais du dépôt utilisent des données fictives.

**Les avatars parlent-ils ?**
Pas encore. La messagerie (clavardage) est disponible ; la voix en temps réel et l'avatar animé sont prévus et déclarés « prévus » par le
système, qui refuse de les annoncer comme disponibles.

**Pourquoi y a-t-il autant de refus et de messages « à valider » ?**
C'est voulu : le système refuse plutôt que de deviner (valeur manquante, licence non lue, politique non validée, approbation expirée). Un
refus qui dit quoi fournir est le comportement attendu.

**Que se passe-t-il si je perds la clé de sauvegarde ?**
La sauvegarde chiffrée est illisible sans elle. Gardez-la hors du serveur, en deux endroits. La clé maîtresse du coffre est une autre clé, aussi
à garder hors du serveur.

**Comment savoir si une fonction est prête ?**
Lisez la [page des limites](LIMITES-CONNUES.md) : elle distingue « prouvé sur le vrai logiciel », « prouvé sur doubles », « prévu » et « non qualifié ».
Si une fonction n'y est pas dans la première catégorie, ne vous y fiez pas pour une opération réelle.

**Les licences des composants sont-elles sûres ?**
Un inventaire (SBOM) et une politique contrôlent les dépendances ; des écarts sont ouverts (par exemple une dépendance sous GPL-3.0 dans le verrou
du Core) et des questions sont soumises à un avocat. Voir [l'inventaire](../compliance/INVENTAIRE-LICENCES.md) et
[les questions à un avocat](../compliance/QUESTIONS-AVOCAT.md).

**Où sont les décisions qu'on attend de moi ?**
Dans la dernière section de la [page des limites](LIMITES-CONNUES.md), recopiées des matrices d'exigences.
