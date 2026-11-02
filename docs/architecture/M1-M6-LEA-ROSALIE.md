# M1 Front Office (Léa) et M6 Material Control (Rosalie) : tri des courriels, rendez-vous, identité, SMS, apprentissage, commande par courriel

Statut (2026-11-01, branche `claude/m1-m6-lea-rosalie`) : **code livré et prouvé contre des DOUBLES de réseau et de courrier,
sur le vrai socle (base SQLite migrée, bus, sas d'approbation, registres) et, pour les rendez-vous, contre le VRAI M4.** Aucun
test de cette tranche n'a touché Gmail, Microsoft Graph, un opérateur SMS, un fournisseur vocal ni un fournisseur réel.
**Rien ci-dessous ne doit se lire « complet » ou « qualifié » pour la production.** L'agent vocal (M1.2) n'est pas touché et
reste simulé ; le SMS réel (M1.7) n'existe toujours pas. Voir « Limites » et « Ce qui reste ».

Sources : matrices `docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M1.json` et `…-M6.json` (statuts de départ ABSENT/SIMULE),
[CONNECTEURS-COURRIEL.md](CONNECTEURS-COURRIEL.md) et [CABLAGE-CONNECTEURS.md](CABLAGE-CONNECTEURS.md) (le courriel, la réception de M1 et le sas
d'envoi N3 existaient déjà et sont réutilisés tels quels), [AVATARS-VOIX.md](AVATARS-VOIX.md) (contrat de session voix réutilisé pour le SMS).

## 0. Autonomie (règle d'architecte, `DECISIONS-ARCHITECTE-r1` §1)

| Autonome (N0 à N2) | Validation humaine obligatoire (N3 et plus) |
|---|---|
| lire, trier et aiguiller un courriel ; extraire des faits minimaux ; préparer un brouillon (réponse, confirmation, rappel, SMS, courriel de commande) ; proposer des semaines et retenir une fenêtre INTERNE ; proposer une amélioration ; ouvrir une vérification d'identité ; classer une demande de commande | tout envoi externe (courriel : sas N3 existant ; SMS : demande N4 sur `m1_emettre_notification`) ; confirmer un rendez-vous ; toute correction d'une classe de tri ; toute promotion d'une règle ou d'une phrase apprise (canari, promotion, retour arrière) ; attester un moyen d'identité ou valider une identité pour le sensible ; appliquer une confirmation de fournisseur douteuse ; classer une facture reçue par courriel ; marquer un PO envoyé (N4, existant) |

Les décisions de personne refusent un agent **même en mode `autonome`**, où un N3 s'exécute sans file : la garde est dans l'outil
(`tests/test_m1_m6_humain_requis.py`, huit outils).

## 1. Exigences visées et statut honnête

| Exigence | Statut avant | Statut après | Preuve et limite en une ligne |
|---|---|---|---|
| M1.6 Tri des courriels | ABSENT | **PARTIEL** | Classification par règles explicables, aiguillage par événements, corpus fictif de 260 cas : justesse 0,64 (dev) et 0,69 (test) ; jamais mesuré sur du courrier réel. |
| M1.9 Rappels et rendez-vous via M4 | ABSENT | **PARTIEL** | Capacité et cédule lues dans le VRAI M4 ; granularité = la semaine ; aucun déclencheur automatique de rappel ; aucune écriture dans M4. |
| M1.10 Statut client après vérification d'identité | ABSENT | **PARTIEL** | Machine d'états et preuves minimales prouvées ; **aucune lecture bornée M2/M3/M4/M5** : M1 décide s'il PEUT répondre, pas ce qu'il dit. |
| M1.13 Boucle d'apprentissage | ABSENT | **PARTIEL** | Retours humains -> propositions -> canari -> promotion -> retour arrière, hors ligne ; gain mesuré +3,0 points sur un corpus fictif ; les métriques de conversion et de temps de réponse ne sont pas là. |
| M1.7 Assistant SMS | SIMULE | **PARTIEL** (gouvernance réelle, transport simulé) | Divulgation, opt-in, STOP, message exact approuvé, pas de rejeu, prouvés ; **aucun SMS réel** : le bus d'émission est un double. |
| M1.2 Agent vocal | SIMULE | **SIMULE (inchangé)** | Vérifié : aucun runtime STT/TTS/SIP/VAD n'existe ; `CANAUX_REALISES = {messagerie}`. Rien n'a été branché. |
| M6.6 Commande par courriel via M1 | ABSENT | **PARTIEL** | Entrant (commande, confirmation, facture vers M5) et sortant (PO -> brouillon -> sas -> envoi constaté) prouvés sur doubles ; aucun envoi réel. |

## 2. Le flux

```
 courriel entrant ─► réception de M1 (CABLAGE-CONNECTEURS §5, inchangée) ─► m1.courriel_recu
                                                                              │ (M1 se consomme lui-même)
                                                                              ▼
            tri déterministe (tri_courriel + règles actives de l'apprentissage) ─► registre tri_courriel (append-only)
                                                                              │
                          m1.courriel_aiguille  (classe, confiance, règles, FAITS minimaux : jamais de texte ni d'adresse)
                 ┌────────────┬──────────────┼───────────────┬───────────────┐
        demande_soumission  plainte   facture_fournisseur   commande_materiaux / confirmation_fournisseur
        lead déjà publié    transfert   M5 : attente        M6 : brouillon de demande rapproché des devis et des WCT,
        par la réception    interne     « à saisir »        ou confirmation d'un PO (appliquée seule seulement si tout tient)
        (m1.lead_qualifie)  de M1       (jamais d'écriture)

 M6 : PO approuvé ─► m6_generer_courriel_po ─► m6.po_courriel_pret ─► M1 : BROUILLON au fournisseur dans le sas ─► m1_demander_envoi_courriel
      ─► une PERSONNE approuve l'empreinte exacte (N3) ─► le planificateur envoie UNE fois ─► m1.courriel_envoye
      ─► m1.commande_courriel_envoyee ─► M6 : attente « marquer le PO envoyé » (m6_marquer_po_envoye reste N4, humain)
```

## 3. M1.6 Tri des courriels

Code : `tri_regles.py` (54 règles `v1`, des données), `tri_courriel.py` (moteur pur), `tri_courriel_outils.py` (adaptateur), `tri_extraction.py`.

**Classes** (neuf) : `demande_soumission`, `plainte`, `facture_fournisseur`, `confirmation_fournisseur`, `commande_materiaux`, `reponse_client`,
`interne`, `pourriel_hameconnage`, `autre`. Les classes `emploi`, `partenariat` et `document` de la matrice sont regroupées dans `autre`
(candidature, partenariat, accusé, réponse automatique) : elles passent en revue humaine.

**Une règle** = identifiant, libellé en français, champ (objet, corps, tout), motif sur le texte normalisé (minuscules, sans accents, espaces
et lettres espacées recollées, citations et historique du fil retirés), poids entier non nul de -5 à 5. Le résultat porte la classe, une
**confiance** (formule fixe `(écart + 1) / (score + 2)`, bornée à 0,99), la **liste des règles déclenchées avec leur libellé**, le
département aiguillé, `revue_humaine` et ses motifs (`classes_proches`, `confiance_basse`, `consigne_neutralisee`, `signaux_hameconnage`,
`indices_insuffisants`, `classe_autre`).

**Garde-fous structurels** (indépendants des règles) :
- `interne` exige le domaine de l'entreprise, DÉCLARÉ à `department.yaml/configuration/domaines_internes` (vide par défaut ; une messagerie
  publique est refusée) **et** SPF, DKIM et DMARC « pass » écrits par un serveur de réception de confiance. Le même domaine sans cette preuve
  est une usurpation (hameçonnage, +5) ; le vocabulaire de vie d'équipe d'un domaine étranger ne suffit pas.
- Un texte neutralisé (consigne cachée reconnue par le filtre de M1) force la relecture et ne change jamais la classe.
- Sous 3 points d'indices : `autre`, jamais une devinette. À égalité, la classe la plus prudente (hameçonnage d'abord).
- Le tri ne voit que la vue neutralisée (`provenance.filtrer`) ; aucune action externe : une plainte ouvre le transfert interne du registre de
  plaintes de M1 (`escalader_plainte`, idempotent par conversation), rien n'est envoyé.

**Faits minimaux** pour M5 et M6 (`tri_extraction.py`) : jetons de référence (PO, facture, devis, chantier, à vérifier par le destinataire),
lignes de quantités (`20 sacs de ciment`, jamais un prix ni une unité devinée), état annoncé par un fournisseur, dates ISO annoncées, empreinte
de l'adresse de l'expéditeur. Le bus ne porte jamais de texte ni d'adresse.

**Mesure** (`m1_evaluer_tri_courriel`, `tests/test_tri_courriel.py`). Corpus FICTIFS (`evals/tri-courriel-{dev,test}.v1.json`, `fictif: true`,
130 cas chacun, adresses `example.test`) écrits **chacun par un rédacteur indépendant, sans voir le code ni l'autre partition**, après les règles
`v1` ; `v1` est figé (son empreinte est épinglée) : un seul changement a suivi la première mesure, structurel (l'a priori « domaine interne » passe de
4 à 2 points : un collègue qui demande des matériaux n'est pas « interne »). Aucun réglage sur `test`.

| classe | dev : précision / rappel | test : précision / rappel |
|---|---|---|
| pourriel_hameconnage | 0,857 / 0,706 | 1,000 / 0,722 |
| plainte | 0,667 / 0,429 | 0,889 / 0,571 |
| facture_fournisseur | 0,688 / 0,688 | 0,667 / 0,875 |
| confirmation_fournisseur | 1,000 / 0,750 | 1,000 / 0,667 |
| commande_materiaux | 0,727 / 0,667 | 0,818 / 0,750 |
| demande_soumission | 0,818 / 0,474 | 0,909 / 0,556 |
| reponse_client | 0,800 / 0,500 | 0,889 / 0,500 |
| interne | 0,800 / 0,667 | 0,875 / 0,583 |
| autre | 0,300 / 1,000 | 0,300 / 1,000 |
| **justesse / F1 macro** | **0,638 / 0,660** | **0,685 / 0,707** |

Lecture honnête : `v1` s'abstient (« autre » + relecture) plutôt que de se tromper : 28 erreurs sur 47 (dev) et 28 sur 41 (test) sont des
abstentions ; 76 et 79 courriels sur 130 demandent une relecture. Les précisions des classes d'action sont élevées, les rappels sont moyens.
**Ce n'est pas un classifieur prêt pour la production** : le corpus est petit, fictif, rédigé par deux auteurs ; la mesure détecte une régression,
elle ne dit rien du courrier réel. **Injection** : 24 cas du corpus portent une consigne adressée à l'assistant (justesse 0,79 sur ces cas contre
0,65 sur les autres : plus longs et plus explicites, pas « mieux défendus ») ; des tests dédiés montrent qu'une consigne ajoutée à un message ne
change ni la classe ni l'aiguillage et force la relecture.

## 4. M1.13 Boucle d'apprentissage

Code : `apprentissage.py` (pur), `tri_courriel_outils.py`. Registre `apprentissage` (append-only).

1. **Retours humains** : `m1_consigner_correction_tri` (une personne corrige une classe) et `m1_consigner_retour_brouillon` (accepté, corrigé avec
   texte final, rejeté). Le registre ne garde **jamais le texte du client** : pseudonyme court de l'expéditeur (pour compter des sources distinctes),
   classes, similarité, et les phrases AJOUTÉES par la personne qui passent un filtre (3 à 14 mots, ni chiffre, ni lien, ni adresse, ni mot de consigne).
2. **Propositions** (`m1_proposer_amelioration`, autonome, hors ligne, déterministe) : des expressions de 1 à 3 mots présentes dans au moins 2 retours de
   signaux distincts venant d'au moins 2 expéditeurs distincts, rares dans les autres classes (≤ 10 %), jamais un chiffre, lien, adresse, jeton de
   neutralisation ni mot de consigne ; poids ≤ 2 (une règle apprise ne renverse pas une règle forte) ; au plus 12 règles. La proposition est mesurée
   sur le corpus de garde (dev + test) : régressions de précision ou de rappel au-delà de 2 points nommées. Pour les gabarits : une phrase ajoutée dans
   au moins 3 BROUILLONS distincts du même gabarit (le support compte les brouillons, pas les signataires : une petite entreprise n'a qu'une propriétaire
   pour les décisions N3 ; c'est sa promotion qui protège), re-contrôlée par le garde-fou de sortie au moment de proposer ; le `gabarit_id` doit exister.
3. **Promotion humaine uniquement** (`m1_decider_proposition`, N3) : `canari` (1 à 50 % des courriels, choisis par hachage du signal ; le tri
   compare en ombre avec les règles actives) -> `complete` (seulement depuis un canari) ou `retour_arriere` ; `refusee`. La mesure est REFAITE à la
   décision : une régression bloque (`REJ-M1-APPR-REGRESSION`) ; un corpus de garde absent bloque aussi. L'historique reste au registre.
4. **Gabarits** : une phrase promue s'insère dans le gabarit actif avant la ligne STOP ou la signature, après le même garde-fou de sortie. Le canari
   d'un gabarit (1 à 50 %) n'ajoute la phrase qu'aux messages dont la clé (rendez-vous + échéance, ou conversation SMS + gabarit) tombe dans le canari ;
   le retour arrière la retire. Aucune mesure chiffrée n'existe pour les gabarits (pas de corpus de réponses) : seule la revue humaine décide.

**Mesure d'amélioration** (`tests/test_apprentissage.py`) : les 47 erreurs de `v1` sur `dev` deviennent des corrections humaines ; les règles
proposées (12, poids 1 ou 2), évaluées sur `test` (jamais utilisé pour apprendre), font passer la justesse de **0,685 à 0,715** (4 courriels corrigés,
0 cassé, 0 régression nommée). Gain réel, petit, avec des règles bruitées (« n'est pas », « fois ») : c'est exactement pourquoi une personne promeut.
Un expéditeur qui se corrige seul 4 fois ne fabrique aucune règle (testé de bout en bout).

## 5. M1.10 Statut client après vérification d'identité

Code : `identite_client.py` (machine d'états pure), `identite_client_outils.py`. Registre `verifications_identite` (pseudonyme du correspondant : même
empreinte que l'identifiant de conversation ; empreinte salée du code ; jamais l'adresse, jamais le code, jamais une pièce).

États : `inconnu` -> `a_verifier` -> `verifie` (n moyens) -> `refuse` | `expire`. Niveaux d'accès : `aucun` -> `probable` (1 moyen) -> `general` (2 moyens distincts) ->
`sensible` (en plus, décision d'une personne, 4 h). Un moyen vit 60 min, le code 30 min, trois essais puis verrou 24 h, rétention de la ligne 1 à 365 jours (défaut 90).

Moyens : `code_courriel` (un code à 6 chiffres dans un BROUILLON du sas ; le **retour** du code depuis la même adresse est la preuve ; l'agent ne le voit jamais :
masqué dans `m1_lire_reponse_courriel` ; il ne peut pas se l'attester) ; moyens attestés par une PERSONNE authentifiée (rappel au numéro du dossier, référence
citée, connaissance du dossier, pièce vue : le TYPE seulement ; un numéro de pièce ou de permis est refusé).

Refus d'usurpation testés : autre expéditeur avec le bon code ; authentification en échec ou consigne neutralisée dans la réponse ; code cité dans le texte
QUOTÉ de notre propre courriel (aucun essai consommé) ; deux codes candidats ; rejeu de la même réponse (ni succès ni échec en double) ; réponse antérieure à
l'ouverture ; code expiré ; verrouillage après trois mauvais codes ; valider sans moyen ; un agent qui atteste ou valide (queue N3, et refus même en `autonome`) ;
un correspondant vérifié n'élève pas un autre correspondant.

**Ce que M1.10 ne fait PAS** : il n'existe aucune lecture bornée de M2/M3/M4/M5 depuis M1. `reponse_autorisee` dit si M1 peut parler de statut ou de sensible ; ce qu'il
dit (état d'une soumission, d'une visite, d'une facture) reste à fournir par une personne ou par un futur pont de lecture. Sans niveau suffisant : « Je vais vérifier
avec l'équipe. » **Loi 25** : finalité déclarée (énumérée), rétention bornée, pseudonymisation, aucune pièce conservée ; la purge physique d'une ligne n'est pas
livrée (registre append-only) : l'adresse et l'objet d'un courriel reçu sont désormais scellés par une clé propre, détruite à l'échéance du compte
([PLANIFICATION.md](PLANIFICATION.md) §5) ; le texte neutralisé et le contact du lead restent. À valider auprès d'un avocat / conseiller en protection des
renseignements personnels (EFVP) avant tout usage réel.

## 6. M1.9 Rappels et rendez-vous via la cédule de M4

Code : `rendez_vous.py` (pur), `rendez_vous_outils.py`, port privé `Capacites._lecteur_capacite_m4` (`src/opsys/capacites.py`, `departements.py`).

- **Droits** : le port n'ouvre que **deux lectures T0 déjà existantes** de M4 (`m4_lire_capacite_equipe`, `m4_lire_cedule_semaine`), seulement depuis le contexte de M1 ;
  M4 revérifie l'identité à chaque lecture (la cédule exige un admin authentifié). Aucun rôle d'appareil n'est élargi. Seul `m1_confirmer_rendez_vous` est nouveau
  pour `admin` (ROLES.md).
- **Proposer** : `m1_proposer_fenetres_rdv` lit la capacité (`portee=semaine_type`) de 1 à 4 semaines (lundis, horizon 120 jours) et calcule en **minutes entières**
  les minutes libres (déclarées moins planifiées), moins les retenues de M1 (conflit) : « disponible » seulement si une équipe peut prendre la durée demandée. Une
  semaine non calculable côté M4 dit « non calculable, manque X » (jamais zéro). Le contrat `m4.capacite_equipe` v1 est vérifié (unité, semaine, entiers) avant tout calcul.
  **Granularité : la semaine.** M4 n'expose pas de créneau libre à l'heure ; M1 n'en invente aucun et ne promet aucune date.
- **Retenir** : engagement interne de 48 h (1 à 168 h), capacité relue à l'instant de la retenue (une proposition périmée ne retient rien), expiration, annulation.
- **Confirmer** : décision d'une personne (admin, depuis l'app) ; M4 doit déjà avoir daté et confirmé la cédule de cette intervention (`date_confirmee`, `planifiee`,
  durée suffisante) ; l'heure est lue de M4. Sans créneau : `REJ-M1-RDV-CEDULE-ABSENTE`, rien n'est confirmé. Une intervention ne porte qu'un rendez-vous. C'est la
  règle de gouvernance de la cédule (proposer N1 -> appliquer N3 -> dater par un admin) : M1 ne la contourne pas.
- **Messages** : après confirmation seulement, brouillons de confirmation (courriel) et de rappels (courriel ou SMS) à partir de gabarits fixes, avec échéances calculées
  par le code (48 h, 24 h, 2 h avant, seulement à venir). L'envoi passe par le sas. **Aucun déclencheur automatique n'envoie un rappel à son échéance** (`rappels_dus` les liste).
- Idempotence : par clé de demande ; les messages par (type, échéance).

## 7. M1.7 Assistant SMS (et M1.2 Agent vocal)

**M1.2 (vérifié, non touché)** : aucun runtime STT/TTS/SIP/VAD ; `avatars.CANAUX_REALISES = {messagerie}` ; la politique refuse tout canal vocal « disponible » ;
`phases_voix.py` est une machine à états d'événements fournis par l'hôte. Reste **SIMULE**.

**M1.7** : `assistant_sms.py` (machine d'états pure), `assistant_sms_outils.py`, `gabarits.py`. Réutilise le contrat de session voix (divulgation canonique, pas d'action sans sas)
et le sas existant.
- États : `inconnu` -> `ouverte` -> `opt_in_demande` -> `opt_in` ; `retire` (STOP) prime sur tout. Un SMS n'est préparé que pour un correspondant qui a écrit.
- **Divulgation d'abord** : le premier message est la divulgation « assistant virtuel (intelligence artificielle) » (gabarit) ; aucun autre avant qu'elle soit livrée.
- **Opt-in exprès** : un rappel (proactif) exige un OUI du correspondant APRÈS la divulgation livrée ; un OUI spontané ou antérieur ne compte pas. Une réponse est permise dans la fenêtre de 24 h.
- **Message exact approuvé** : `m1_sms_preparer_message` (gabarit fixe, garde-fou de sortie, longueur ≤ 480) puis `m1_sms_demander_envoi` : demande **N4** sur l'outil existant
  `m1_emettre_notification` avec `canal = sms:<conversation>` et le texte exact. À l'exécution, `garde_execution` refuse si le correspondant s'est retiré entre-temps
  (`REJ-SMS-RETRAIT`) ou si le texte n'est pas un brouillon demandé.
- **Résultat inconnu, pas de rejeu** : l'issue est « ENVOYE_INCONNU » (approuvé et remis au bus de test) ou « ECHEC_INCONNU » ; un brouillon n'est jamais redemandé ; un nouveau message est un nouveau brouillon.
- Statut de dossier : gabarit « Je vais vérifier avec l'équipe » ; paiement : « l'équipe des finances vous transmettra les instructions » (M5 fournit, M1 ne donne ni lien ni montant).
- **Simulé** : `m1_emettre_notification` écrit sur un bus en mode ombre. Aucun SMS réel n'a jamais été émis ni reçu par ce code ; aucun opérateur ; la politique d'opt-in SMS (Loi 25 / LCAP) est en PROPOSITION.

## 8. M6.6 Commande par courriel via M1 (et pont M1 -> M5)

Code M6 : `commande_courriel.py` (pur), `commande_courriel_outils.py`, `bons_commande.confirmer_fournisseur`. Code M1 : `commande_fournisseur.py`. Code M5 : `facture_courriel.py`, `facture_courriel_outils.py`.

- **Entrant, demande de commande** (`commande_materiaux`) : brouillon de demande (`m6_lire_commandes_courriel`) rapproché **par identifiant exact** cité dans le courriel (devis, chantier, PO ;
  jamais par ressemblance) du prévu d'un devis (quantité demandée vs prévue, écart nommé, unité différente) et des WCT reçus ; fournisseur reconnu par l'empreinte de sa boîte de
  commande ; **idempotent par message** (`Message-ID` -> `signal_id`) ; provenance (message, règles, confiance, version, empreinte de l'expéditeur) rangée avec chaque fait. Aucun PO n'est
  créé : la suggestion pointe `m6_creer_po_brouillon`. `m6_traiter_commande_courriel` (N2) classe la demande.
- **Entrant, confirmation de fournisseur** : `sent_to_supplier` -> `supplier_confirmed` **seulement si tout tient** : un seul PO nommé, expéditeur = boîte de commande du fournisseur du PO,
  authentification complète de confiance, aucune relecture exigée par le tri, aucune rupture/report/substitution annoncés, confirmation explicite, PO bien au statut envoyé. Sinon une attente
  (`m6_valider_confirmation_courriel`, N3 humain). Les dates annoncées sont rangées comme « annoncées », jamais promises.
- **Sortant** : `m6_generer_courriel_po` (N2 depuis C2, brouillon interne) publie `m6.po_courriel_pret` (destinataire = la boîte de commande déclarée à la fiche du fournisseur ; objet « Commande
  matériaux — PO — ville » ; corps COMPLET : chantier, date requise, livraison ou ramassage et lieu, lignes avec unité et perte déclarée visible, demande de confirmation, aucun prix ; `empreinte`
  = celle du courriel exact, rangée sur le PO) ; M1 en tire un brouillon dans le sas (compte connecté avec usage `lecture_envoi` ; sinon le bus réessaie puis met en quarantaine, sans perte) ;
  l'envoi suit le chemin N3 existant : UNE personne approuve l'empreinte exacte du brouillon. **Plus de seconde approbation (C2)** : `m1.commande_courriel_envoyee` porte maintenant
  `empreinte_courriel_po` (celle que M6 avait offerte) et `contenu_identique` (le brouillon envoyé a la même empreinte qu'à sa préparation : personne n'a changé le texte au sas). M6 passe le PO
  de `email_ready` à `sent_to_supplier`, en rangeant le constat sur la transition, SEULEMENT si le PO est `email_ready`, l'empreinte est celle du courriel de CE PO et `contenu_identique` est
  vrai. Sinon (vieux constat sans ces champs, texte modifié au sas, autre bon) rien ne change et l'attente « marquer le PO envoyé » (N4) reste à une personne, comme pour un envoi hors M1
  (téléphone, portail). Le statut ne change donc que par un envoi DÉJÀ approuvé et constaté, ou par `m6_marquer_po_envoye` (N4) : aucun chemin d'envoi automatique n'est ouvert.
  Convention de numérotation : le tri de M1 ne reconnaît une référence de bon de commande que sous la forme « PO-<chiffre>… » (`tri_extraction._PO`), donc `PO-2026-014` se rapproche d'une
  confirmation de fournisseur, `PO-GENTEK-1` non.
- **M5** : une facture de fournisseur reçue par courriel devient une **attente « à saisir »** (`m5_lister_factures_courriel`, classement humain `m5_classer_facture_courriel`) avec les PO reconnus ;
  drapeau « à vérifier » (fausse facture possible) si l'authentification n'est pas complète ou si le tri exige une relecture. **Aucun montant n'est lu, aucune facture ni écriture créée.**
  À valider auprès d'un comptable (CPA) / professionnel qualifié.

## 9. Événements

| Type | Producteur | Consommateurs | Contenu (jamais de texte ni d'adresse de courriel de client) |
|---|---|---|---|
| `m1.courriel_aiguille` | M1 (tri) | M5, M6 | classe, confiance, règles, aiguillage, relecture, jetons de référence, lignes de quantités, état et dates annoncés, empreinte de l'expéditeur |
| `m6.po_courriel_pret` | M6 | M1 | po_id, fournisseur, destinataire (boîte de commande déclarée par l'entreprise), objet, corps généré par M6, empreinte |
| `m1.commande_courriel_envoyee` | M1 | M6 | po_id, brouillon, empreinte, instant d'envoi, `empreinte_courriel_po` et `contenu_identique` (facultatifs, C2) |

`m1.courriel_recu` et `m1.courriel_envoye` (existants) sont désormais aussi consommés par M1 lui-même. Tous ont un `evenement_id` déterministe (rejeu = no-op).

## 10. Outils ajoutés (aucun droit d'appareil élargi)

| Département | Outil | Niveau | Qui |
|---|---|---|---|
| M1 | `m1_trier_courriel`, `m1_lire_tri_courriel`, `m1_evaluer_tri_courriel` | N2, N0, N0 | agent |
| M1 | `m1_consigner_correction_tri`, `m1_consigner_retour_brouillon`, `m1_decider_proposition` | N3 | **personne** |
| M1 | `m1_proposer_amelioration`, `m1_lire_apprentissage` | N2, N0 | agent |
| M1 | `m1_ouvrir_verification_identite`, `m1_consigner_moyen_verification`, `m1_lire_verification_identite` | N2, N2, N0 | agent |
| M1 | `m1_attester_moyen_verification`, `m1_decider_verification_identite` | N3 | **personne** |
| M1 | `m1_proposer_fenetres_rdv`, `m1_retenir_fenetre_rdv`, `m1_preparer_messages_rdv`, `m1_annuler_rendez_vous`, `m1_lire_rendez_vous` | N2, N2, N2, N2, N0 | agent |
| M1 | `m1_confirmer_rendez_vous` | N3 | **personne**, appareil `admin` seulement |
| M1 | `m1_sms_preparer_message`, `m1_sms_demander_envoi`, `m1_lire_session_sms` | N2, N2, N0 | agent |
| M5 | `m5_lister_factures_courriel` ; `m5_classer_facture_courriel` | N0 ; N3 | agent ; **personne** |
| M6 | `m6_lire_commandes_courriel` ; `m6_traiter_commande_courriel` ; `m6_valider_confirmation_courriel` | N0 ; N2 ; N3 | agent ; agent ; **personne** |
| M6 (C2, C3) | `m6_creer_po_brouillon`, `m6_creer_pos_depuis_besoin`, `m6_generer_courriel_po` ; `m6_lister_po`, `m6_lire_po` ; `m6_changer_statut_po` | N2 ; N0 ; N3 | agent ; agent ou admin ; **personne** |

Registres (tous append-only, `stockage.maillons`) : M1 `tri_courriel`, `apprentissage`, `verifications_identite`, `sms_assistant`, `rendez_vous`, `commandes_fournisseur` ; M5 `factures_courriel` ;
M6 `commandes_courriel`. **Aucune migration** n'est nécessaire (le numéro 0048 réservé reste libre). Les refus des nouveaux outils sont des `ValueError("REJ-…: détail")` (même idiome que
`courriel_outils`), à une exception voulue : le code d'un mauvais essai de code d'identité est RENDU (et non levé) pour que l'essai raté soit écrit et qu'il survive à l'appel.

## 11. Preuves

Voir le rapport de livraison pour les suites lancées. En résumé : tests purs (règles, extraction, apprentissage, identité, gabarits, SMS, rendez-vous, M6), tests de bout en bout sur le vrai socle
(`tests/test_m1_*_e2e.py`, `tests/test_m1_m6_courriel_flux.py`, `tests/test_m1_m6_humain_requis.py`), raccord au vrai M4 (`tests/test_m1_rendez_vous_m4_reel.py`), balayage de temps linéaire des motifs
(un motif quadratique a été trouvé et corrigé par le test existant de M1 : `_FIN_DE_FIL`, `_COUPE`, puis `_A_ECARTER`).

Trouvailles pendant la construction (corrigées, avec test) : (1) un refus LEVÉ après une écriture annule l'écriture : les essais ratés d'un code d'identité n'étaient pas comptés ; (2) les catalogues de verdicts
de M1 et de M5 sont fermés (un code inconnu levait une exception) ; (3) `valider_arguments` du socle n'applique ni longueur, ni motif, ni bornes numériques : chaque borne est revérifiée dans le code ;
(4) les verdicts SPF/DKIM/DMARC étaient lus même quand l'en-tête était écrit par l'expéditeur : seul un serveur de réception de confiance les rend crédibles (`fiable`).

## 12. Limites (sans euphémisme)

- **Aucun service réel** : ni courriel (Gmail, Graph, IMAP), ni opérateur SMS, ni voix. Tout est prouvé sur doubles ; seul M4 est réel dans les tests de rendez-vous.
- **Serveurs de réception de confiance non câblés** : le planificateur de courriel n'en fournit aucun à l'ingestion (`serveurs_fiables=None`) : en production, `authentification.fiable` est toujours faux,
  donc `interne` est inatteignable, l'authentification n'est jamais « complète », les confirmations de fournisseur ne s'appliquent jamais seules et toute facture reçue est « à vérifier ». C'est le
  comportement sûr, mais il faut déclarer ces serveurs (par compte) avant que l'automatisation serve. Les tests le déclarent explicitement.
- **Corpus fictif, petit, deux auteurs** : la mesure du tri ne dit rien du courrier réel ; `v1` n'a jamais vu un message de client. Les règles sont francophones (quelques-unes anglaises).
- **Pas de lecture M2/M3/M4/M5 pour le statut client** (M1.10) ; pas de métriques de conversion, de délai de réponse ni de raison de perte (M1.13) ; les rappels n'ont aucun déclencheur automatique (M1.9).
- **Rendez-vous à la semaine** : pas de créneau libre à l'heure, M4 ne l'expose pas. Les rendez-vous d'estimation menés par un vendeur (agenda de M2) ne sont pas couverts.
- **Concurrence** : prouvée par les transactions SQLite d'un seul processus ; aucun essai multi-processus sur ces registres, aucun essai PostgreSQL.
- **Rétention et Loi 25** : pas de purge physique d'une ligne ; l'adresse et l'objet des courriels reçus sont scellés et effaçables par destruction de clé ([PLANIFICATION.md](PLANIFICATION.md) §5) ; le registre de M1 conserve encore le texte neutralisé (`contenu_filtre`) et le contact du lead, et les lignes écrites avant ce changement portent l'adresse en clair ; EFVP et avis juridique non faits.
- **Le tri ne fait pas de brouillon de réponse** : `m1_preparer_reponse_courriel` (existant) reste l'outil ; la boucle d'apprentissage des gabarits couvre les gabarits de rendez-vous et de SMS, pas le texte libre.
- Un lead déjà publié par la réception (`m1.lead_qualifie`) pour un courriel que le tri juge ensuite « plainte » n'est pas retiré ; le transfert interne s'ouvre en plus.

## 13. Ce qui reste (suivi explicite)

Déclarer les serveurs de réception de confiance par compte ; lecture bornée de statut M2/M3/M4/M5 pour M1.10 ; déclencheur planifié des rappels (exécuteur du planificateur, N3 consommé) ;
transport SMS réel et son opt-in validé ; runtime vocal (M1.2) ; métriques d'apprentissage (délais, conversions, raisons de perte) ; mesure sur courrier réel anonymisé avec accord ;
purge physique des vérifications d'identité (décision humaine) ; essai PostgreSQL et multi-processus.
