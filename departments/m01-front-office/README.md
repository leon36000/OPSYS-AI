# M1-front-office

Front Office IA — reception omnicanale, voix 0->5, qualification, adjointe

Statut: PARTIAL (EPIC E — vague 1 livrée en mode ombre : registre, machine à états des phases
voix 0->5, garde-fou des interdits absolus, qualification, adaptateurs, digest.)

## Résumé privé de réception — tranche du 4 octobre 2026

Le port canonique `m1_produire_digest` existe ; son exposition dans la console
est **qualifiée localement** : ROOT r142, 1 667 tests sur 37 fichiers complets,
sans échec/erreur/skip, Ruff vert et 1 242 sources inchangées. Deux GET privés
avec date choisie ou jour UTC par défaut affiché réutilisent ses agrégats, avec bornes SQLite,
grammaire fermée, rôles relus
et `no-store`. Le suivi des conversations est courant, même pour une date
ancienne ; ce n’est pas un instantané historique uniforme. ROOT r137 conserve
un baseline de route absente : 0 réussite, 1 échec, 1 241 sources inchangées.
Voir le [design](../../docs/grs/reception/M1-DIGEST-CONSOLE-DESIGN-2026-10-04.md)
et le [rapport](../../docs/grs/reception/M1-DIGEST-CONSOLE-RAPPORT-2026-10-04.md).
Les tentatives de rappel non terminales restent une tranche distincte.
M1 global demeure **PARTIEL**.

## Garde-fou des interdits et STOP publié au bus (PLAN T4.17-c)

- **Le garde-fou est celui du socle** (`opsys.garde_fou_texte`) : `garde_fou.py` ne fait plus que choisir les familles de M1
  (`PROFIL_REPONSE_CLIENT` : `prix_montant`, `date_execution`, `engagement`, `aveu`, `avis_legal`) et rendre le verdict de la
  première famille violée (`REJ-INTERDIT-*`, avec un `detail`). Un texte public de M7 a d'autres familles ; aucun département
  n'importe l'autre. Les corpus (44 textes interdits, 22 légitimes) sont inchangés et verts.
- **L'avis légal est vérifié partout** (`REJ-INTERDIT-AVIS-LEGAL`), pas seulement sur le gabarit de plainte : brouillons, questions
  du profil, gabarits, résumés de transfert, `m1_verifier_garde_fou`. Un résumé de l'agent ne peut donc pas nommer un avocat : il
  omet `resume` et le code compose le sien ([M1-canaux](../../docs/departements/M1-canaux.md) §11).
- **Le STOP d'un client est publié au bus** (`m1.retrait_consentement`, `retrait.py`) : les `lead_id` des leads déjà ouverts pour
  ce correspondant, le canal, l'heure et le signal du STOP. Jamais un numéro ni un courriel : le lien avec le chantier est le
  `lead_id`, que M2, M4 et M7 connaissent aussi. Un lead ouvert après le STOP est retiré à son tour. M7 le consomme et bloque tout
  contenu de ces leads (§12 du même document).

## Canaux du core (PLAN T2.1-a)

M1 reçoit le public par le canal SMS d'OPSYS-CORE : `m1_recevoir_message_canal` qualifie le message (taxonomie des
services et zone du profil d'entreprise, expéditeur comme contact), l'inscrit au registre anti-perte et publie le lead
v2 au bus (`m1.lead_qualifie`, `source` = le canal). Le canal est désactivé tant que ses identifiants et la validation
écrite des politiques ne sont pas fournis ; aucune réponse n'est envoyée au client sans approbation humaine.
Conception, configuration générée, garde-fous et greffes du core à faire : [M1-canaux](../../docs/departements/M1-canaux.md).

M2 consomme ce lead pour de vrai depuis T2.1-b (`evenements.consomme` de M2, sans greffe) : ingestion complète, idempotente ;
un refus lève, le répartiteur réessaie puis met en quarantaine.

## Formulaire du site et UTM (PLAN T4.17-e3)

Un lead venu d'un contenu de M7 garde son `utm_content` jusqu'à M8 :

- **`formulaire` est un canal de `m1_recevoir_message_canal`** (l'adresse ou le numéro que le visiteur a écrit, jamais vérifié :
  le contact s'étiquette « écrit par le client ») et **le seul qui porte un `utm`** ; un SMS, un courriel ou un appel qui en
  fournit un est refusé (`REJ-UTM-CANAL-SANS-SENS`), rien n'est écrit.
- **Une seule règle de validation, celle de M2** (`contrats.utm_invalide` : quatre clés, valeurs non vides, aucune autre borne),
  gardée par `tests/test_utm_derive_m2.py`. Un `utm` invalide est refusé (`REJ-UTM-INVALIDE`), avec ce qu'il faut corriger.
- **Porté tel quel** par le lead que le message fait naître, jamais deviné ni complété. Un `utm` qu'aucun lead ne porte
  (demande incomplète, conversation déjà qualifiée, plainte) est dit dans la réponse (`utm.statut`) et reste au registre.
- **`site/formulaire-demande.html`** : l'extrait que le propriétaire colle sur son site ; son script recopie les `utm_*` de
  l'adresse de la page. Rien n'est publié ; le récepteur du formulaire reste à construire (T3).

Règles, limites et décisions de Nathan : [M1-canaux](../../docs/departements/M1-canaux.md) §13.

## Qualification par conversation (PLAN T2.1-b)

Un client qui écrit le service dans un message et la ville dans le suivant donne un lead complet : `conversation.py` (module
pur) rassemble les messages d'une même conversation dans la fenêtre que le profil d'entreprise déclare
(`fenetre_conversation_minutes`, jamais une durée par défaut) et le lead naît quand service et ville sont connus, un seul
par conversation ouverte. Un message rejoué ne compte pas deux fois ; STOP ferme la conversation ; une fenêtre expirée
n'est plus rassemblée. Sans fenêtre déclarée, la qualification reste message par message et la réponse le dit
(`conversation.verdict`). Ce qui est demandé au client est un brouillon (`brouillon_reponse`, `envoye: false`) : il ne part que
par `m1_emettre_notification` (N4), après approbation. Règles et limites : [M1-canaux](../../docs/departements/M1-canaux.md) §8.

## Qualification complète (PLAN T4.4)

Une conversation ne meurt plus à la porte, et rien n'est envoyé ni décidé par le modèle :

- **Le verdict nomme chaque champ manquant** (`service`, `ville`, `contact`) et la conversation cumule le contact et l'urgence
  comme le service et la ville (`qualification.py`, `conversation.py`).
- **Questions obligatoires par service** (`questions.py`) : écrites par le propriétaire dans `entreprise.yaml`
  (`questions_qualification`, lu par `opsys.taxonomie`), jamais dans le code. Sans elles, le verdict le dit et rien n'est inventé.
  Une question est répondue quand un de ses mots-clés figure dans la conversation ; chacune passe seule au garde-fou.
- **Demande de photos fermée** (`photos.py`) tant que `POLITIQUE-photos-non-contractuelles.md` n'est pas marquée
  `STATUT_VALIDATION: valide` (même lecture que M3).
- **Score de lead** (`score.py`) : urgence, complétude, zone, pondérés par les poids du profil (`poids_score_lead`), en
  fractions exactes, explicable critère par critère ; sans poids, « poids à configurer » et aucun score. Il reste au registre de
  M1 : le contrat `LeadQualifie` v2 n'a pas changé (le passer à M2 est une v3).
- **Prochaine action datée** (`suivi.py`) : une ligne `suivi_conversation` au registre par message reçu, datée de l'heure de la
  plateforme et de la fin de la fenêtre du profil (jamais d'une horloge) ; le digest en tire les conversations sans suivi.
- **Le client qui répond « lequel des services ? » lève l'ambiguïté** (`conversation.services_retenus`).

Fixtures fictives (`fictif: true`) : `fixtures/qualification/profil-fictif.v1.yaml`. Conception, limites et décisions de Nathan :
[M1-canaux](../../docs/departements/M1-canaux.md) §9.

## Plaintes, urgences et transfert humain (PLAN T4.5)

Une plainte ou une urgence de sécurité n'est jamais un lead. Rien n'est envoyé, et aucun contrat n'a changé :

- **Détection par règles** (`plaintes.py`), avant la qualification, sur le texte filtré. Les mots sont ceux du propriétaire,
  dans son profil d'entreprise (`signaux_plainte`, cinq catégories : insatisfaction, dégât, garantie, avocat, sécurité) ;
  sans eux, le verdict dit « vocabulaire à configurer » et rien n'est reconnu. **La plainte prime** : un tel message n'ouvre
  jamais de lead. Une urgence de sécurité est escaladée tout de suite, sans conseil de sécurité ni promesse d'intervention.
- **Transfert humain** (`transferts.py`) : type fermé (ventes, estimation, admin, finance, plainte, urgence, technique,
  propriétaire), **résumé obligatoire** (composé par le code, ou fourni par l'agent puis contrôlé : non vide, sans contact,
  garde-fou), destinataire lu de `destinataires_transfert` (vide par défaut : « destinataire à configurer »). Outils :
  `m1_transferer`, `m1_escalader_plainte` (N2, tâche interne), `m1_lire_transfert` (admin), `m1_clore_transfert` (admin, décision
  humaine : un agent ne clôt jamais seul).
- **« À voir »** : `attentes()` rend une attente par transfert ouvert, sans donnée personnelle, triée par niveau (N5 urgence de
  sécurité et menace juridique, N4 plainte, N3 le reste) puis ancienneté. L'admin la voit, l'employé reçoit 403. Elle disparaît
  quand une personne clôt le transfert.
- **Gabarit empathique** : un brouillon (`envoye: false`), sans excuse, promesse, conseil ni avis légal, passé par le garde-fou
  des interdits (avis légal compris, depuis T4.17-c) ; l'envoi reste `m1_emettre_notification` (N4).

Fixtures fictives (`fictif: true`) : `fixtures/plaintes/plaintes.v1.yaml` (48 plaintes et urgences, 12 demandes ordinaires, 4
limites documentées). Conception, niveaux N, limites et décisions de Nathan :
[M1-canaux](../../docs/departements/M1-canaux.md) §10.

