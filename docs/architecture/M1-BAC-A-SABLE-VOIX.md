# M1 — Bac à sable vocal TEXTUEL et politique de dialogue d'un appel (M1.19)

Statut (2026-11-02) : **livré et prouvé sur SQLite, avec des faux appels écrits d'avance, des données fictives, les vrais morceaux
de M1 (qualification, plaintes, transferts avec résumé, registre, garde-fou) et la vraie session voix du socle.**

> **Ce que ce document NE dit PAS : que la voix marche.** Aucun audio, aucune détection de parole, aucune transcription, aucune
> synthèse, aucune ligne téléphonique, aucun fournisseur. Le canal voix reste « prévu » (`avatars.CANAUX_REALISES =
> {messagerie}`). M1.2 reste **SIMULE** ; M1.19 passe d'**ABSENT** à **SIMULE**, jamais à FAIT_PROUVE. Ce qu'on prouve ici, c'est
> que les **règles de dialogue** tiennent, avant qu'un moteur vocal ne les appelle.

## 1. Pourquoi

La définition du produit (§7 M1) dit : « Faible confiance de transcription : redemander. Deux échecs de compréhension, plainte,
sujet légal ou financier, urgence de sécurité : transfert humain immédiat », et la montée en charge de la voix passe par un
« bac à sable (faux clients) » avant tout appel réel. Cette politique n'existait qu'en prose ; le garde-fou de sortie (aucun prix,
date, engagement, aveu ni avis légal) existait, mais jamais en boucle avec un dialogue. Ce chantier écrit la politique en règles
pures et la fait tourner sur des appels scriptés, de façon déterministe.

## 2. Les pièces

| Pièce | Fichier | Rôle |
|---|---|---|
| Politique de dialogue | `departments/m01-front-office/src/m1_front_office/politique_dialogue.py` | règles pures : une décision par tour (continuer, réponse sûre, redemander, transférer, messagerie), textes fixes, lexique générique |
| Harnais | `…/bac_a_sable_voix.py` | joue un faux appel : session voix du socle, politique, répondant (port), garde-fou, qualification et transferts de M1, rapport |
| Répondant | port `Repondant` + `RepondantDeterministe` | ce qui parle quand la politique laisse parler ; le double ne dit que des phrases fixes tirées du profil |
| Essai passerelle | `…/tests/test_bac_a_sable_voix_passerelle.py` | adaptateur HTTP OpenAI-compatible **dans les tests** ; faux serveur local par défaut, vrai modèle en opt-in seulement |
| Skill | `departments/m01-front-office/skills/mener-un-appel-vocal/` | la politique résumée pour l'agent |

Aucun outil de département, aucune migration, aucun nouveau paquet : le registre MCP n'a pas changé.

## 3. La politique, dans l'ordre

Le premier qui s'applique décide. Une confiance faible n'empêche **jamais** de reconnaître un danger ou une plainte : un faux
positif coûte une lecture humaine, un faux négatif coûte bien plus.

| # | Condition | Décision | Tâche humaine (type, niveau) |
|---|---|---|---|
| 1 | urgence de sécurité (catégorie `securite` du profil) | transférer, **même sans personne disponible**, texte « je signale votre appel » | `urgence`, N5 |
| 2 | menace juridique (`avocat`) | transférer | `plainte`, N5, aucun brouillon |
| 3 | plainte (insatisfaction, dégât, garantie) | transférer | `plainte`, N4 |
| 4 | sujet légal (lexique générique) | transférer | `proprietaire`, N4 |
| 5 | sujet financier (lexique générique) | transférer | `finance`, N3 |
| 6 | demande explicite d'une personne | transférer | `ventes`, N3 |
| 7 | échec de compréhension : confiance sous le seuil, absente ou invalide ; silence ; le répondant n'a pas compris | redemander ; au `echecs_max`-ième échec **consécutif**, repli | `ventes`, N3 |
| 8 | question de prix ou de date | réponse sûre fixe, l'appel continue | aucune |
| 9 | sinon | le répondant parle, garde-fou ensuite | aucune |

- **Sans personne disponible** (`humain_disponible=False`), tout transfert sauf l'urgence de sécurité devient une **prise de
  message** (« messagerie intelligente en repli ») : l'avatar invite à laisser un message ; ce que l'appelant dit est qualifié par
  les mêmes règles que celles d'un message vocal ; la tâche humaine s'ouvre quand même (type conservé). Rien n'est perdu.
- **Les mots de la plainte et du danger sont ceux du propriétaire** (`signaux_plainte` du profil, jamais ici). **Sans vocabulaire
  adopté, ni colère ni danger ne sont reconnus** (même comportement fail-closed que pour un message écrit) : c'est une
  **précondition de tout appel réel**, voir [PACKS-SECTORIELS](PACKS-SECTORIELS.md), « Propositions de profil ».
- **Les décisions de Nathan, sans valeur par défaut** : `SeuilsDialogue(confiance_minimale, echecs_max)`. La définition du
  produit dit « deux » échecs ; elle ne dit pas « de suite » : **les échecs comptés sont consécutifs** (un tour compris remet le
  compte à zéro), choix à confirmer. Une confiance absente, non numérique, booléenne, NaN, infinie ou hors de 0 à 1 est une
  confiance faible.
- **Le lexique générique** (sujets légal et financier, demande d'une personne, prix, date : `LEXIQUE_V1`) est une proposition
  écrite à la main, comme les règles de tri des courriels, sans aucun mot de métier. Le code lit des mots, pas le sens :
  « combien de temps » sonne comme une question de prix (réponse sûre, sans conséquence) ; une ironie sans mot du vocabulaire
  n'est pas vue (tests qui épinglent ces limites).
- **Tous les textes que dit la politique** (`TEXTES`) sont fixes, passent le garde-fou, ne contiennent ni chiffre, ni excuse, ni
  promesse, ni conseil de sécurité.

## 4. Le harnais, ce qu'il fait et refuse

1. **Divulgation d'abord** : la première parole est le texte canonique « assistant virtuel » de la session du socle ; une
   interruption l'annule et elle est refaite avant toute autre parole (même pour un danger).
2. **Garde-fou en boucle** : chaque phrase du répondant passe `garde_fou.verifier_sortie` ; une violation n'est **jamais dite**, elle
   est remplacée par une phrase sûre fixe et consignée (hachage et code, pas le texte). Les 44 textes interdits et 22 légitimes du
   corpus de M1 sont rejoués comme sorties du répondant.
3. **Consentement** : sans `accorde`, la parole de l'appelant n'entre ni au registre ni au rapport (comme un message vocal) ;
   la tâche humaine s'ouvre quand même, avec un résumé composé par le code. Avec `accorde`, la session du socle conserve la
   transcription (rétention par défaut du socle : 30 jours) ; jamais l'audio.
4. **Un texte peu sûr n'ouvre jamais de lead** : le répondant ne voit que les tours compris ; le texte d'un tour de faible confiance
   n'entre pas au registre, sauf colère, menace ou danger (la plainte prime : aucun lead).
5. **Aucun effet de bord réel** : aucune action exécutable (port sans outil), aucun message au client, aucun appel réseau, aucune horloge
   système (l'horloge est injectée, le délai de réponse est SIMULÉ), aucun hasard. **Refuse de tourner sur le registre de
   production** (`REJ-BAC-A-SABLE-PRODUCTION`) : un faux appel ne doit jamais devenir un vrai lead.
6. **Rapport** : issue (`lead_cree`, `rappel_cree`, `transfert_humain`, `messagerie`), décisions tour par tour, paroles (nature :
   comprise, faible confiance, silence, message laissé ; divulgation, politique, répondant, remplacement garde-fou), tâche humaine
   (type, niveau, destinataire, résumé du code), lead, rappel, session, latences simulées, et la mention de sa portée.

Refus typés : `REJ-BAC-A-SABLE-PRODUCTION`, `-SCRIPT`, `-PROFIL`, `-HORLOGE`, `-REPONDANT`, `-SESSION` (une règle de la session
voix : durée maximale, quotas), `-TRANSFERT`, `-ACTION`.

## 5. Les scénarios (E2E, `tests/test_bac_a_sable_voix_scenarios.py`)

Instance fictive : services, zone, pack de rénovation choisi et **ses cinq propositions adoptées par une personne**.

| Scénario | Ce qui est prouvé |
|---|---|
| Appel complet de gouttières | service, ville, trois questions **du profil adopté** dans l'ordre écrit, clôture ; lead créé sur une base de test, publié au vrai bus, ingéré par le vrai M2 (contrat identique) ; questions restantes dans le résumé |
| Appelant en colère | plainte N4 au rôle du profil, aucun lead, résumé non vide, contact, avatar sans excuse ni promesse ; la colère à faible confiance reste un transfert (pas un « répétez ») ; menace juridique N5 sans brouillon ; sans consentement la tâche s'ouvre sans la parole ; sans personne : message à laisser |
| Faible confiance répétée | redemander puis repli ; aucun lead inventé d'un texte peu sûr ; un échec isolé ne déclenche rien et le compte repart ; sans personne : messagerie qualifiée ; messagerie vide : la demande n'est pas perdue ; le silence compte comme un échec |
| Question de prix | réponse sûre, aucun montant ni `$`, l'appel continue jusqu'au lead ; un répondant qui laisse échapper un prix, une date ou un engagement est neutralisé ; question de date |
| Urgence de sécurité | escalade immédiate N5, aucun conseil ni promesse, l'avatar se tait, même à faible confiance, sans personne, ou en interrompant la divulgation |
| Sans vocabulaire adopté | colère et danger NON reconnus : la limite, dite et épinglée |

## 6. Mutations (les tests tuent-ils ?)

**82 mutations, une à une, dans un clone du dépôt** (copie du worktree, les tests ciblés rejoués après chacune,
puis le fichier restauré et son empreinte comparée à l'originale : **les 82 restaurations vérifiées**) : 56 sur la politique de
dialogue et le harnais (M1-D), 26 sur l'adoption des propositions et les données du pack (M1-A). **80 tuées du premier coup, 2
survivantes** (H22, A10), toutes deux des vrais trous de tests, fermées par un test puis rejouées (tuées) :

- **H22** (l'avis légal passait le garde-fou en boucle) : le corpus d'interdits de M1 (44 textes) ne contient aucun avis légal ;
  cinq phrases de la garde de l'avis légal sont maintenant rejouées comme sorties du répondant.
- **A10** (une valeur chiffrée n'était plus étiquetée « recommandation, non validée ») : le test d'étiquette manquait.

Les mutations de « **mauvaise dimension** » demandées par la leçon de l'intégration de M7 (la cause rangée dans la mauvaise
catégorie) : P07 (colère traitée comme faible confiance), P08 (urgence rangée en simple message), P09 (danger transféré comme
une tâche de vente), P10 (menace juridique = plainte ordinaire), P12 (sujet légal envoyé aux finances), P19 (le danger devient
une messagerie sans personne), P22 (repli sur échecs répétés = plainte), H09 (l'incompréhension du répondant repart de zéro au
lieu de s'ajouter aux échecs), H24 (disponibilité d'une personne ignorée par le harnais), A05 (le vocabulaire est écrit comme
une table de destinataires), A11 (choisir un pack adopte tout : auto-activation). **Toutes tuées.**

### Politique de dialogue (P) et harnais (H)

| Id | Mutation | Résultat |
|---|---|---|
| P01 | seuil de confiance : >= devient > | tuée |
| P02 | comparaison de confiance inversée | tuée |
| P03 | confiance absente tenue pour bonne (fail-open) | tuée |
| P04 | repli au (n+1)-ième échec au lieu du n-ième | tuée |
| P05 | un tour compris ne remet plus le compte à zéro | tuée |
| P06 | les échecs ne s'accumulent plus | tuée |
| P07 | MAUVAISE DIMENSION : la colère traitée comme faible confiance | tuée |
| P08 | MAUVAISE DIMENSION : l'urgence rangée en simple message | tuée |
| P09 | MAUVAISE DIMENSION : danger transféré comme une tâche de vente | tuée |
| P10 | MAUVAISE DIMENSION : menace juridique = plainte ordinaire | tuée |
| P11 | danger et plainte ignorés quand la confiance est faible | tuée |
| P12 | sujet légal envoyé aux finances | tuée |
| P13 | sujet financier ignoré | tuée |
| P14 | sujet légal ignoré | tuée |
| P15 | demande d'une personne ignorée | tuée |
| P16 | question de prix : plus de réponse sûre | tuée |
| P17 | question de date : plus de réponse sûre | tuée |
| P18 | disponibilité d'une personne ignorée (jamais de messagerie) | tuée |
| P19 | le danger devient une messagerie quand personne n'est là | tuée |
| P20 | la messagerie perd le type de la tâche humaine | tuée |
| P21 | un texte vide n'est plus un silence | tuée |
| P22 | repli sur échecs répétés ouvre une plainte | tuée |
| P23 | texte d'urgence remplacé par le texte de transfert | tuée |
| P24 | confiance > 1 acceptée | tuée |
| P25 | seuil de 1 refusé à tort | tuée |
| P26 | « remboursement » retiré du lexique financier | tuée |
| P27 | branche menace juridique supprimée | tuée |
| P28 | branche plainte supprimée | tuée |
| P29 | l'état suivant ne retient pas les échecs | tuée |
| P30 | un texte fixe viole le garde-fou | tuée |
| H01 | garde-fou en boucle désactivé | tuée |
| H02 | phrase refusée quand même dite | tuée |
| H03 | violation non consignée | tuée |
| H04 | garde du registre de production retirée | tuée |
| H05 | tout consentement non nul vaut « accorde » | tuée |
| H06 | parole écrite au registre sans consentement | tuée |
| H07 | tours de faible confiance vus par le répondant et le registre | tuée |
| H08 | texte déclencheur peu sûr toujours enregistré | tuée |
| H09 | MAUVAISE DIMENSION : l'incompréhension du répondant repart de zéro | tuée |
| H10 | divulgation interrompue non refaite | tuée |
| H11 | la tâche humaine voulue par la politique n'est jamais ouverte | tuée |
| H12 | la messagerie n'ouvre plus sa tâche humaine | tuée |
| H13 | la session du socle n'est pas mise en transfert | tuée |
| H14 | un appelant qui parle plus tôt fait reculer le temps | tuée |
| H15 | délai de réponse simulé non appliqué | tuée |
| H16 | instants décroissants acceptés | tuée |
| H17 | barge-in ignoré | tuée |
| H18 | le rapport ne dit plus sa portée | tuée |
| H19 | issue « messagerie » jamais rapportée | tuée |
| H20 | une demande incomplète n'ouvre plus de rappel (demande perdue) | tuée |
| H21 | incompréhension du répondant ignorée | tuée |
| H22 | l'avis légal passe le garde-fou en boucle | SURVIVANTE puis fermée |
| H23 | le consentement n'entre pas dans la session du socle | tuée |
| H24 | disponibilité d'une personne ignorée par le harnais | tuée |
| H26 | le registre reçoit la parole même sans consentement | tuée |
| H25 | le message laissé en messagerie n'entre pas au registre | tuée |

### Adoption des propositions (A) et données du pack (D, empreinte rescellée à chaque mutation de donnée)

| Id | Mutation | Résultat |
|---|---|---|
| A01 | l'adoption écrase la valeur du propriétaire | tuée |
| A02 | adoption non idempotente (réécrit et journalise) | tuée |
| A03 | adoption sans signature | tuée |
| A04 | adoption depuis un pack autre que celui du profil | tuée |
| A05 | MAUVAISE DIMENSION : le vocabulaire est écrit comme une table de destinataires | tuée |
| A06 | adoption non journalisée | tuée |
| A07 | un élément « validé » est accepté dans un pack | tuée |
| A08 | les validateurs du profil ne jugent plus les propositions | tuée |
| A09 | le pack générique peut proposer un profil | tuée |
| A10 | une valeur chiffrée n'est plus étiquetée « recommandation » | SURVIVANTE puis fermée |
| A11 | MAUVAISE DIMENSION : choisir un pack adopte tout (auto-activation) | tuée |
| A12 | questions proposées non validées/perdues | tuée |
| A13 | la fenêtre adoptée n'est jamais écrite | tuée |
| A14 | un profil vide est lu comme déjà adopté | tuée |
| D01 | DONNÉE : « fumée » et « fil électrique » retirés du vocabulaire du danger | tuée |
| D02 | DONNÉE : la plainte est destinée à un vendeur | tuée |
| D03 | DONNÉE : la question d'adresse des gouttières retirée | tuée |
| D04 | DONNÉE : « garantie » seul (faux positif d'un prospect) | tuée |
| D05 | DONNÉE : « étage » ne répond plus à la question des étages | tuée |
| D06 | DONNÉE : fenêtre de conversation à 0 | tuée |
| D07 | DONNÉE : poids de la zone à 0 | tuée |
| D08 | DONNÉE : une demande de photos reconnue par du texte | tuée |
| D09 | DONNÉE : « cour » (cour arrière) dans la menace juridique | tuée |
| D10 | DONNÉE : une question de budget | tuée |
| D11 | DONNÉE : un destinataire « client » | tuée |
| D12 | DONNÉE : un élément marqué « valide » | tuée |

Ce que ces mutations NE disent PAS : qu'aucune autre faute n'existe, ni que les tests couvrent la voix (aucune n'y touche). Les
mutations de données du pack montrent que les tests de bout en bout voient un mot de danger retiré, un destinataire changé, une
question perdue ou un faux positif ajouté, pas que les mots sont les bons pour de vrais clients.

## 7. Essai opt-in contre la passerelle de modèles

`OPSYS_ESSAI_PASSERELLE=1` et `OPSYS_PASSERELLE_CLE_FICHIER=<fichier>` lancent un essai avec un modèle rapide (quelques dizaines de
jetons, jamais de boucle). Par défaut, un faux serveur HTTP local répond au format de la passerelle et prouve que l'adaptateur et
le garde-fou tiennent quand le « modèle » dérape ou tombe en panne (panne = échec de compréhension = repli vers une personne).
Un essai réel a été fait une fois (Haiku, un appel, aucune violation : le modèle n'a pas dérapé, donc le garde-fou n'a pas été
exercé par un vrai modèle). La clé n'est ni affichée, ni écrite, ni journalisée.

## 8. Limites (dites sans euphémisme)

- **La voix n'est pas prouvée.** Ni latence réelle (les valeurs sont injectées), ni accent fr-CA, ni bruit, ni interruption réelle
  (le barge-in est un indicateur du script), ni qualité de transcription ou de synthèse.
- **Les seuils et le lexique sont des propositions.** La politique est exercée sur du texte écrit par l'auteur des tests ; aucun
  vrai appelant. Aucune mesure de faux positifs sur de vrais appels.
- **La remise « en direct » à une personne n'existe pas** : la session émet l'ordre `transferer_vers_humain` que seul un futur worker
  exécuterait. Aujourd'hui, un transfert est une tâche au registre (attente « À voir »), comme pour un message écrit.
- **Aucune notification poussée** : la personne voit la tâche en ouvrant la console.
- **Pas d'appel manqué complet** (M1-C), pas de lecture du statut d'un client (M1-G), pas de photos (une voix n'en reçoit pas).
- **Sans vocabulaire adopté** (voir §3) ou sans fenêtre de conversation adoptée (les questions ne sont posées qu'avec elle), la
  qualité du dialogue est celle d'un profil vide.
- **Un répondant réel** (modèle) n'a été essayé qu'une fois, en opt-in ; sa qualité de dialogue n'est pas évaluée.
