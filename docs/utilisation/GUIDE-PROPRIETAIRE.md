# Guide du propriétaire : ce que fait OPSYS-AI pour vous

Pour la direction d'une PME. Aucun jargon technique ici : les mots difficiles sont dans le [glossaire](GLOSSAIRE-ET-FAQ.md).
Ce guide dit ce que le système fait **dans le code livré**. Pour ce qui n'est pas encore prêt, lisez
[Limites connues et ce qui reste à valider](LIMITES-CONNUES.md) avant de vous fier à une fonction.

## 1. L'idée en trois phrases

OPSYS-AI est une équipe de dix départements virtuels qui partagent une seule vérité sur votre entreprise (clients, soumissions,
chantiers, matériaux, factures). Ils font le travail de préparation, de calcul et de suivi eux-mêmes. **Vous n'exécutez rien : vous
approuvez** les gestes qui vous engagent ou qui sortent de l'entreprise.

L'état du produit est honnête : il est en consolidation. Aucune instance de production n'existe, tous les départements démarrent en mode
« ombre » (ils proposent, vous approuvez), et plusieurs capacités ne tournent que sur des simulations de test (voir la page des limites).

## 2. Vos dix départements et leurs avatars

Chaque département a un avatar : un nom, un rôle, une voix et un visage prévus. **Aujourd'hui, seule la messagerie est disponible** : vous
clavardez avec l'avatar dans l'interface de contrôle. La voix en temps réel et l'avatar animé sont prévus, pas livrés. Les noms sont
modifiables pour votre entreprise (clé `avatars` du profil d'entreprise).

| Code | Département | Avatar | Ce qu'il fait pour vous | Outils |
|---|---|---|---|---:|
| M1 | Front Office | Léa | Reçoit chaque demande (courriel, SMS, formulaire, texte), la filtre, la qualifie par règles et la dirige vers le bon département. Aucune demande ne se perd : chacune laisse une ligne dans un registre. | 52 |
| M2 | Revenue CRM | Victor | Tient la vérité commerciale : clients, pistes, entonnoir de vente, relances préparées, prévisions. | 50 |
| M3 | Estimation | Mathis | Transforme une piste prête en estimation chiffrée, avec sa marge d'incertitude. Les prix viennent de calculs, jamais d'une estimation « de tête » du modèle. | 57 |
| M4 | Field Ops | Gabriel | Équipes, cédule, routes, exécution et clôture des chantiers, heures et preuves de fin de travaux. | 75 |
| M5 | FinanceCore | Sophie | Comptabilité, facturation, rapprochements, préparation fiscale et de paie, tableau de bord du CFO. Prépare des brouillons ; ne remplace pas votre CPA. | 109 |
| M6 | Material Control | Rosalie | Inventaire, achats, fournisseurs, sorties sur le terrain, écarts entre le prévu et l'utilisé. | 55 |
| M7 | Marketing | Chloé | Visibilité, site, contenu, réseaux sociaux, annonces, création visuelle. Rien ne se publie sans vous. | 101 |
| M8 | Analytics | Olivier | Mesures gouvernées, tableaux de bord, alertes, qualité des données : « peut-on se fier à ce chiffre ? » | 32 |
| M9 | Strategic Intelligence | Athéna | Conseil de direction : scénarios, risques, priorités, suivi des décisions. Elle propose, vous décidez. | 94 |
| M10 | Mémoire | Mnémo | Garde ce qui a été fait, décidé et appris ; base de connaissances sourcée. | 71 |

Total : **696 outils** (un outil = un geste précis qu'un département sait faire). **257** de ces outils sont ouverts à un téléphone
appairé (employé, vendeur ou administrateur) ; les autres sont réservés à l'ordinateur et aux agents.

Le cœur du système est **générique pour une PME**. Le vocabulaire d'un métier vient d'un « pack sectoriel » : `generique-pme` par défaut,
ou `renovation-exterieure-qc` pour la rénovation extérieure au Québec. Le choix est écrit dans le profil d'entreprise
(`opsys-metier pack choisir`) et n'est jamais deviné.

## 3. Ce qui est automatisé et ce que vous validez

Chaque outil porte un **niveau**, de N0 à N5. Plus le niveau monte, plus le geste est lourd à défaire.

| Niveau | Nature | Qui agit |
|---|---|---|
| N0 | Lecture | Automatique |
| N1 | Brouillon (réponse, facture, rapport, recommandation) | Automatique |
| N2 | Tâche interne, rappel, alerte, demande de validation | Automatique |
| **N3** | Action vers l'extérieur à faible risque, ou changement interne non final (publication approuvée, rapprochement proposé, écriture proposée) | **Une personne valide** |
| **N4** | Engagement : dépense, prix, campagne, envoi sensible, écriture comptable finale | **Vous (le propriétaire)** |
| **N5** | Argent réel, fiscal, légal, paie, ressources humaines, achat majeur | **Vous ET le professionnel concerné** (CPA, fiscaliste, avocat, prêteur). Jamais automatique. |

En pratique :

- **Ce que le système fait seul** : lire vos données, calculer, préparer des brouillons, classer, relancer en interne, alerter,
  publier des faits aux autres départements, recalculer des coûts, tenir les registres.
- **Ce que vous validez**, avec les gestes réels du code :

| Département | Exemples de gestes qui attendent une personne |
|---|---|
| M1 Léa | Envoyer une réponse par courriel (approbation valable 72 h) ; confirmer un rendez-vous ; valider l'identité d'un correspondant ; décider d'une amélioration de tri |
| M2 Victor | Confier une piste à un autre vendeur ; préparer une relance ; enregistrer un consentement de contact |
| M3 Mathis | Envoyer un devis au client ; marquer un devis accepté ; promouvoir ou retirer une calibration ; valider une détection sur photo |
| M4 Gabriel | Approuver une affectation qui engage le client ; résoudre une revue de fin de chantier ; valider les heures ; purger les données GPS |
| M5 Sophie | Envoyer une facture ; **enregistrer un paiement (N5)** ; rendre une écriture définitive ; clore un mois ; valider un import QuickBooks ; confirmer un rapprochement bancaire ; préparer (jamais exécuter) le paiement d'un fournisseur |
| M6 Rosalie | Accepter une déclaration de matériaux avec preuves ; classer la cause d'un écart ; trancher une confirmation de fournisseur reçue par courriel |
| M7 Chloé | Publier un site, un article WordPress ou une publication sociale (approbation d'une heure pour WordPress) ; **annonce payante (N4)** ; approuver un visuel ou un logo ; décider d'un créneau de calendrier |
| M8 Olivier | Aucun geste N3 ou plus : il lit, calcule et alerte |
| M9 Athéna | Ouvrir ou clore un suivi de décision |
| M10 Mnémo | Valider une source de connaissance ; déposer ou activer une version documentaire |

- **Ce qui ne s'automatise jamais** : paiements et virements, secrets de production, suppression définitive de données, publication ou
  déploiement public, engagements externes. Ce sont des frontières humaines.
- **Une approbation est liée à ce que vous avez vu** : pour un courriel, réviser le brouillon après la demande rend l'accord caduc ; pour une
  publication, l'accord est lié à l'empreinte du contenu. Il expire (72 heures pour un courriel, une heure pour un article WordPress) et ne
  sert qu'une fois.

## 4. Le mode de chaque département

| Mode | Ce qui demande votre approbation | Quand l'utiliser |
|---|---|---|
| `ombre` (défaut de tous les départements) | Tout geste à partir de N3 | Toujours au début |
| `supervise` | À partir de N4 | Après une période d'observation |
| `autonome` | À partir de N5 seulement | **À éviter pour l'instant** : cette règle est plus souple que la décision de l'architecte (N3 à N5 validés). À trancher d'abord. |

Changer de mode se fait par une personne autorisée : `opsys-metier mode <département> <mode> --par <personne>` (ou dans la console).

## 5. Comment approuver, concrètement

1. **Dans la console** (adresse `https://console.<votre-domaine>`), page **Approbations** : la file de tout ce qui attend, avec le résumé,
   le niveau, depuis quand et l'action proposée. Vous cliquez « Approuver et exécuter » ou « Refuser », avec un motif facultatif.
2. **Dans l'application mobile**, profil administrateur, écran **Approbations** : pour décider en déplacement. L'application est livrée en
   code et en tests logiciels ; elle n'a pas été éprouvée sur un téléphone réel.
3. **En ligne de commande** : `opsys-metier approbations lister`, puis `approuver <id>` ou `refuser <id>` (mot de passe tapé, jamais
   passé en argument). Pour un geste de niveau N5, la décision demande aussi l'attestation du professionnel (nom, profession, document).

Chaque décision est signée (qui, quand, pourquoi) et conservée dans un journal qu'on ne réécrit pas. Un agent ou un compte de service ne peut
jamais approuver à votre place.

## 6. Ce que vous devez fournir

- **Le profil de votre entreprise** : services, zone desservie, vocabulaire, personnes à qui transférer, fenêtres de conversation.
  Il est vide par défaut ; sans lui, la réception d'un courriel s'arrête (sans rien perdre).
- **Vos décisions ouvertes** : poids et seuils de pointage des pistes, minimum de rentabilité, barèmes, seuils de revue, politiques de
  consentement (SMS, appels, photos, GPS). Les outils concernés **refusent de deviner** tant que vous n'avez pas décidé. La liste complète est
  dans les [limites connues](LIMITES-CONNUES.md).
- **Vos réglages de direction** : l'écran « Réglages de direction » de la console liste ce qui manque (délais de relance et de dormance de M2,
  bornes du score de santé de M8), ce que chaque réglage débloque et, quand il existe, une valeur proposée « recommandation, non validée ».
  Vous adoptez (ou changez) la valeur avec une raison, en un geste de niveau N3 qui n'appartient qu'au propriétaire, et vous pouvez
  revenir en arrière en un geste. Rien ne s'applique sans vous. Voir [REGLAGES-DIRECTION](../architecture/REGLAGES-DIRECTION.md).
- **Vos accès** (Google, Microsoft, QuickBooks, réseaux sociaux) : ils passent par le coffre de secrets, jamais en clair, jamais vus par
  les agents. Voir le [guide d'administration](GUIDE-ADMINISTRATION.md).
- **Votre comptable (CPA) et votre avocat** : tout avis comptable, fiscal, juridique ou de placement porte la mention
  « À valider auprès d'un comptable (CPA) / professionnel qualifié ». Le système prépare ; il ne certifie pas.

## 7. Ce que vous pouvez attendre, et ce que vous ne devez pas attendre

Vous pouvez attendre : des brouillons, des calculs avec leur source, des refus clairs quand il manque une donnée (le système dit quoi
fournir), une trace de tout ce qui a été fait, et aucune action irréversible sans votre accord.

Ne vous attendez pas encore à : des appels vocaux de Léa, un avatar animé, des publications réelles sur vos réseaux, l'envoi réel de
courriels ou de SMS depuis un vrai compte, une paie ou des déclarations prêtes à transmettre, des images générées par un vrai modèle, ni à une
installation sur un serveur déjà qualifiée. Tout cela est détaillé, avec ses raisons, dans les [limites connues](LIMITES-CONNUES.md).
