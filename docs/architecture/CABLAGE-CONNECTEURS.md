# Câblage des connecteurs : de la capacité livrée à l'agent qui s'en sert

Statut (2026-11-01) : **câblé et qualifié contre des DOUBLES seulement.** Aucun test de cette tranche n'a touché Gmail, Microsoft
Graph, un serveur IMAP/SMTP, un WordPress, un réseau social ni un fournisseur OAuth réels. **Rien n'est actif par défaut.** Ce
document dit ce qui est branché, ce qui reste manuel, et ce qui n'est pas prouvé.

Trois chantiers livrés restaient des îlots : les connecteurs courriel ([CONNECTEURS-COURRIEL.md](CONNECTEURS-COURRIEL.md)), les
exécuteurs WordPress et sociaux de M7 ([M7-WORDPRESS-SOCIAL.md](M7-WORDPRESS-SOCIAL.md)) et l'ingestion d'onboarding
([INGESTION-ONBOARDING.md](INGESTION-ONBOARDING.md)). Cette tranche les relie aux départements, à un planificateur, au bus, à la
console, sans élargir aucun droit.

**Suite (2026-11-01) : [M1-M6-LEA-ROSALIE.md](M1-M6-LEA-ROSALIE.md)** : tri des courriels reçus, aiguillage vers M5 et M6, courriel de commande d'un PO,
vérification d'identité, rendez-vous et SMS, par-dessus ce câblage. Une limite de ce document y est précisée : aucun serveur de réception de confiance n'est transmis
à l'ingestion, donc `authentification.fiable` est toujours faux en production.

## 1. Le flux

```
                         ┌───────────────────────────── console admin (/plateforme/connecteurs) ───────────────────────────┐
                         │ créer + connecter un compte (retour OAuth, state à usage unique)  ·  activer / désactiver        │
                         │ les exécuteurs (inactif · ombre · actif, 90 jours, motif)  ·  voir ce qui attend la direction    │
                         └──────────────┬───────────────────────────────────────────────────────┬──────────────────────────┘
                                        │ comptes, consentement Loi 25                          │ mode d'un exécuteur
                                        ▼                                                       ▼
  boîte courriel ──► ServiceCourriel ──► IngestionCourriel ◄──────── PLANIFICATEUR (opsys.connecteurs_planification) ◄── boucle du serveur MCP
  (Gmail/Graph/       (curseur, quota,      │        │                 acteur système `opsys-systeme` · créneau réservé · bail par ressource
   IMAP/mbox)          idempotence)         │        │                 arrêt propre · journal append-only
                                            │        │
        amorçage (historique) ──────────────┘        └────────────── entrant (après l'amorçage, option reception_m1)
          │ pièces ─► file d'onboarding                                   │  vue NEUTRALISÉE (isolation.py) ─► M1.recevoir_courriel_connecteur
          │ correspondants (option contacts_courriel)                     │  signal `courriel:<cle>` + ligne de provenance + lead éventuel
          ▼                                                               ▼
   brouillons « courriel_contact » ──► M2 (N3, humain) ─► contact confirmé     événement m1.courriel_recu ──► bus
                                                                          │
   Léa (M1) lit (T0) ─► m1_preparer_reponse_courriel (N2, destinataire imposé) ─► m1_demander_envoi_courriel (N2)
                                                                          │   = ouvre la demande N3 du sas ; RIEN n'est envoyé
                                                                          ▼
   la direction approuve l'empreinte exacte (opsys_courriel_approuver_envoi, N3, décider() de la file) ─► brouillon APPROUVE
                                                                          │
   PLANIFICATEUR · courriel.envoi ─► pré-contrôle (humain actif, exécutée, NON EXPIRÉE) ─► ServiceEnvoi.envoyer ─► garde du sas
        (jeton = demande + empreinte, consommé par comparaison-échange AVANT le premier octet) ─► UN message ─► m1.courriel_envoye

   M7 : brouillons WordPress ─► (revue, approbation N3 consignée) ─► PLANIFICATEUR · m7.wordpress.publication ─► jeton signé, UNE fois
        publications sociales approuvées et planifiées ─► PLANIFICATEUR · m7.social.publication ─► m7.publication_faite / _echouee
```

## 2. Ce qui est actif par défaut : RIEN

- Les cinq exécuteurs sont `inactif` : une ligne absente, expirée, d'un mode inconnu, ou le coupe-circuit
  `OPSYS_PLANIFICATEUR_CONNECTEURS=0`, valent `inactif` (fail-closed). Le tour d'un exécuteur inactif ne lit rien chez un
  fournisseur et n'ouvre aucun secret (testé : zéro requête au transport).
- Un compte courriel n'existe pas tant qu'un admin ne l'a pas créé, avec une finalité, une rétention et le consentement du titulaire
  (Loi 25), puis connecté. Ses deux options sont fermées : `reception_m1` (les nouveaux courriels deviennent des réceptions de M1) et
  `contacts_courriel` (l'historique propose des contacts au CRM).
- Aucun outil d'agent n'envoie, ne publie, n'active un exécuteur ni ne décide une approbation.

**Activer** (console, admin ; session serveur, jeton CSRF, rôle relu en base ; refusé depuis le MCP, un département ou un appareil) :
`inactif` → `ombre` (le tour CONSTATE ce qu'il ferait, sans appeler aucun fournisseur ni rien écrire au métier, et le journalise)
→ `actif` (il exécute). Chaque activation expire après **90 jours** (renouvellement explicite) et porte un motif ; le journal est
append-only.

| Exécuteur | Niveau | Ce qu'il fait quand il est actif |
|---|---|---|
| `courriel.synchro` | N2 | Lit les nouvelles pages des comptes connectés (reprise sur curseur persisté APRÈS la page, débit limité, idempotence par `Message-ID` + empreinte), dépose les pièces et les correspondants dans la file d'onboarding, transmet l'entrant à M1 (comptes qui l'ont demandé). |
| `courriel.envoi` | N3, approbation consommée | Envoie UNE fois chaque brouillon approuvé, dont l'approbation est humaine, exécutée et non expirée (72 h) ; marque INCERTAIN une réservation orpheline (jamais rejouée). |
| `m7.wordpress.brouillons` | N2 | Transmet au site les brouillons (statut `draft`/`pending` : le client et le plugin refusent le reste) ; trois échecs écartent un brouillon. |
| `m7.wordpress.publication` | N3, approbation consommée | Publie les articles approuvés (une heure de validité) ; une approbation expirée ferme la publication en échec SANS toucher au site ; une réponse perdue se réconcilie en relisant le site. |
| `m7.social.publication` | N3/N4, approbation consommée | Publie à l'heure approuvée (fenêtre, quota, tolérance de retard) ; reprise bornée d'un échec transitoire ; retrouve une publication d'issue incertaine avant tout nouvel envoi. |

## 3. Décisions (et pourquoi)

**Pas de second cron.** L'opérateur cron existant (`agents_cron_*`, `agents_declencheurs`) planifie des **tours d'agent** dans le
scheduler natif du core (message + `toolsAllow` d'outils N0–N2) : on ne peut ni y loger un exécuteur déterministe, ni y
laisser passer un geste N3 (il les refuse : `CRON-OUTIL-FRONTIERE-HUMAINE`), et son raccord au core n'est pas qualifié ici.
Les exécuteurs de M7 ne doivent d'ailleurs jamais être un outil d'agent. Le planificateur est donc un TOUR dans le processus du
serveur MCP, lancé par la boucle du serveur à côté de celle du répartiteur d'événements (même cycle de vie, même arrêt propre), sur
le modèle du réconciliateur du coût certifié : `inactif`/`ombre`/`actif`, acteur système, octroi par un admin avec expiration à 90
jours. Un profil d'agent peut toujours planifier un tour de lecture (les outils de lecture et de brouillon de M1 sont N0/N2) ;
l'ENVOI et la PUBLICATION ne passent que par le planificateur et le sas. **À valider par l'architecte** : si un opérateur cron
unique pour les tâches déterministes est voulu, `planificateur.tour` en est le point d'entrée.

**Acteur système, jamais d'approbation.** Le tour tourne sous `opsys-systeme` (portée `planificateur`, hors requête, non
réentrant, fermé à la fin du tour ; le moteur de recalcul refuse cette portée et inversement). Cet acteur n'est pas une personne :
`approbations.decider` le refuse. Il n'exécute une action N3 que par une approbation HUMAINE déjà consommée :
- envoi : le pré-contrôle du planificateur et la garde du sas relisent la demande (outil d'approbation, N3 au moins, `executee`, approbateur
  humain actif, 72 h au plus) ; la garde lie le jeton à l'empreinte et consomme par comparaison-échange (`APPROUVE` → `ENVOI_RESERVE`)
  dans une transaction validée AVANT le premier octet réseau ;
- publication : l'approbation consignée (rôle `nathan_owner`, empreinte du contenu actuel, expiration) est vérifiée, le jeton est consigné comme
  ÉMIS avant d'être envoyé (une approbation sert une fois).

**Un seul exécuteur à la fois par ressource.** Un bail par ressource (`planificateur_baux` : porteur, jeton de fencing croissant,
expiration) : acquisition atomique, renouvellement avant chaque geste durable (un porteur dépossédé s'arrête), libération dans tous les
cas. Un compte courriel partage son bail entre la synchronisation et l'envoi (jamais deux usages simultanés des mêmes jetons). Le
bail n'est pas la seule protection : sans lui, la comparaison-échange du sas empêche quand même le double envoi (testé).

**Arrêt propre.** `demander_arret()` est posé avant l'annulation de la boucle ; le tour s'arrête entre deux ressources et avant chaque
page, libère ses baux, ne signale AUCUNE erreur au compte. Un tour a aussi une durée maximale (240 s).

**L'ENVOI N3 n'est pas un outil.** `m1_demander_envoi_courriel` (T1/N2) ouvre la demande N3 du sas ; il est N2 parce que la demande
ne sort rien (et parce que le garde N3 du core exige un contexte d'affaire que la session d'un client n'a pas encore). L'outil du
sas `opsys_courriel_approuver_envoi` est un outil commun N3 de `Capacites`, exécuté par `approbations.decider` (console, CLI), **caché**
à tout agent sur les points d'accès MCP. Décideur par défaut de M1 : `nathan_owner` seul (le manifeste n'ajoute rien).

## 4. Les outils de M1 (Léa)

| Outil | Niveau | Rôle | Appareil |
|---|---|---|---|
| `m1_lister_comptes_courriel` | T0/N0 | Comptes connectés : état, usage, dernier passage ; jamais un secret ni son nom. | aucun |
| `m1_lire_courriels_recus` | T0/N0 | Boîte de réception de M1 (texte NEUTRALISÉ, `provenance.fiabilite = non_fiable`, signaux, état de la réponse). | aucun |
| `m1_lire_reponse_courriel` | T0/N0 | Le brouillon préparé, son état dans le sas, son empreinte. | aucun |
| `m1_preparer_reponse_courriel` | T1/N2 | Crée ou révise le brouillon ; **destinataire = expéditeur du courriel reçu, imposé par le code** (aucun paramètre) ; garde-fou de sortie (prix, date d'exécution, engagement, aveu, avis légal). | aucun |
| `m1_demander_envoi_courriel` | T1/N2 | Ouvre la demande N3 (contexte et sources obligatoires). Rien n'est envoyé. | aucun |

Compagnon : la skill `repondre-a-un-courriel`. Aucun rôle d'appareil, aucun élargissement de droits : voir [ROLES.md](ROLES.md).
Une révision après la demande rend l'approbation caduque ; une réponse `ENVOYE`/`INCERTAIN` est figée.

## 5. La réception de M1 (sans doublon)

`m1_front_office.courriel_outils.recevoir_courriel_connecteur` n'est pas un outil : le connecteur l'appelle, avec la vue neutralisée.
Elle passe par le **même pipeline** que `m1_recevoir_message_canal` (provenance, registre anti-perte, qualification, lead publié au
bus), dans une seule transaction avec la ligne de provenance `reception_courriel_connecteur_v1` (compte, fournisseur, dossier,
empreinte, signaux, authentification rapportée, décision) et l'événement `m1.courriel_recu`.

- **Identité** : `cle_signal` = SHA-256 du `Message-ID` (sinon compte + référence du fournisseur), donc le signal `courriel:<cle>` est
  le même quels que soient le compte, le dossier, l'amorçage ou la voie. Un courriel déjà reçu n'est pas reçu deux fois : par un
  nouvel amorçage, une autre étiquette, un autre compte, ni par l'outil `m1_recevoir_message_canal` appelé avec la même clé
  (testés dans les deux ordres).
- **Amorçage = historique** : tant qu'un dossier n'a pas fini son premier passage complet, ses messages ne vont JAMAIS à M1 (un lead par
  vieux courriel serait faux) ; le drapeau d'amorçage vit dans les curseurs du compte.
- **Configuration de M1 manquante** (service, zone) : la page s'arrête, le curseur n'avance pas (`REJ-COURRIEL-M1-REFUSE`, reprenable) ; rien n'est perdu.
- **Limite honnête** : le chemin `reception_courriel_*` (originaux IMAP chiffrés) n'est PAS raccordé (il exige une clé externe dédiée et une
  autorité d'hôte non livrées). Le courriel du core (`extension imap`) n'a pas de configuration OPSYS et fournit son propre identifiant :
  le sans-doublon est prouvé pour les deux entrées qui partagent la clé (`cle_signal`), pas pour un identifiant du core que M1 ne peut pas deviner.
  Il faut choisir UNE voie par boîte.
- L'adresse de l'expéditeur et le texte neutralisé entrent au registre append-only de M1 (sans purge) : à traiter avec la rétention de M1 avant tout usage réel.

## 6. Onboarding : contacts

Voir [INGESTION-ONBOARDING.md](INGESTION-ONBOARDING.md) §11 : genre de brouillon `courriel_contact`, lots reprenables,
`m2_valider_brouillon_onboarding_contact_courriel` (N3, humain), jamais d'écriture au CRM sans confirmation.

## 7. Événements du bus

| Type | Producteur | Quand | Contenu (jamais d'adresse ni de texte) |
|---|---|---|---|
| `m1.courriel_recu` | M1 | un courriel entrant devient une réception | signal, compte, fournisseur, décision, signaux |
| `m1.brouillon_courriel_pret` | M1 | une réponse est préparée ou révisée | brouillon, révision, empreinte |
| `m1.approbation_envoi_demandee` | M1 | la demande N3 est déposée | demande, brouillon, empreinte |
| `m1.courriel_envoye` | planificateur | l'envoi unique a eu lieu | brouillon, empreinte, fournisseur, instant |
| `m1.envoi_courriel_echoue` | planificateur | refus (approbation expirée/invalide), échec ou issue INCERTAINE | issue, code |
| `m7.publication_faite` | planificateur | publication WordPress ou sociale faite | canal, cible, identifiant externe |
| `m7.publication_echouee` | planificateur | échec, approbation expirée, issue incertaine | canal, code, transitoire, incertain |

Tous ont un `evenement_id` déterministe : un rejeu n'en publie pas un second. Un profil d'agent peut les consommer (déclencheur
`evenement`) ; aucun consommateur n'est livré ici.

## 8. Console

`/plateforme/connecteurs` (lien depuis les pages Plateforme), `/api/plateforme/connecteurs`, `/courriel/oauth/retour`.
- **Connexion** : créer le compte (finalité, rétention, consentement), « Connecter » (OAuth : PKCE S256, portées minimales, `state` signé, lié au compte, valable 10 min,
  **à usage unique** : consommé même si l'échange échoue). Le départ vers le fournisseur est un **lien** (la CSP `form-action 'self'` bloquerait une redirection).
- **Retour** : la session qui revient doit être celle qui a démarré l'autorisation ; le `code` et le `state` ne sont ni redirigés (303 vers une
  adresse propre), ni journalisés (`Referrer-Policy: no-referrer`, journal d'accès masqué par `journaux_http`), ni affichés. Aucun jeton d'accès n'est dans une URL : il
  va du fournisseur au serveur puis au coffre. Un mot de passe IMAP est saisi une fois et jamais réaffiché.
- **Écritures** : CSRF, rôle relu avant ET après, `no-store`, page contrôlée contre les valeurs secrètes actives (500 sinon).
- **À configurer côté serveur** (`connecteurs_planification.hote`) : `OPSYS_COURRIEL_REDIRECT_URI`, `OPSYS_COURRIEL_GMAIL_CLIENT_ID`
  (+ `OPSYS_COURRIEL_GMAIL_SECRET`), `OPSYS_COURRIEL_GRAPH_CLIENT_ID`/`_TENANT` (+ `_SECRET`) et le secret du coffre `courriel.state-cle` (≥ 32 octets,
  base64) ; sans eux, le service dit `REJ-COURRIEL-OAUTH-CONFIGURATION`.

## 9. Migration

`0044_planificateur_connecteurs` : trois tables (`planificateur_executeurs`, `planificateur_baux`, `planificateur_journal` immuable) et la CHECK de
`ingestion_brouillons.genre` élargie à `courriel_contact` (remplacée en place sur SQLite). **`down_revision = "0040"` dans ce worktree** (la tête de la ligne
architecte) : à l'intégration, l'architecte le réaligne sur `"0043"` (0041 m10-connaissances, 0042 m7-studio-creatif, 0043 observabilite-mcp). Trois
tests épinglaient la tête « 0040 » : ils lisent désormais la tête alembic. La descente est refusée dès qu'une ligne existe.

## 10. Ce qui reste manuel

- Obtenir et déclarer l'accès OAuth réel du client (projet Google « Internal », application Entra), les secrets du coffre, l'EFVP (Loi 25) ; connecter les comptes.
- Activer chaque exécuteur (d'abord `ombre`, puis `actif`), le renouveler tous les 90 jours.
- Décider chaque envoi et chaque publication dans la file d'approbation ; vérifier la boîte « Envoyés » après une issue INCERTAINE.
- Écrire et qualifier un transport WordPress réel et des adaptateurs de réseaux réels (**aucun n'existe** : en production ces ports sont « non raccordés », les
  exécuteurs M7 refusent avec `REJ-PLAN-WORDPRESS-NON-RACCORDE` / `REJ-PLAN-SOCIAL-NON-RACCORDE`).
- Déclarer le profil d'entreprise de M1 (services, zone) : sans lui, la réception d'un courriel entrant s'arrête (reprenable).
- Rétention : aucune purge n'existe (courriel : déclarée mais non appliquée ; registre de M1 : append-only).

## 11. Preuves et limites (sans euphémisme)

**Prouvé (sur doubles)** : tests `tests/test_cablage_*.py` (planificateur, courriel de bout en bout, M7, onboarding, console, MCP, migration SQLite et
PostgreSQL éphémère) : compte fictif → synchro planifiée → courriel entrant avec injection → réception de M1 → brouillon → demande →
refus sans approbation → approbation humaine → envoi unique → rejeu sans second envoi ; idem publication WordPress et sociale ; huit fils et six
processus en concurrence ; expiration ; arrêt propre ; réponse perdue ; fuites de secrets.

**Mutations** (script `mutations-cablage.py` du rapport) : 26 mutations manuelles du code (retirer le bail ou son renouvellement, ignorer l'expiration d'une
approbation d'envoi ou de publication, retirer le pré-contrôle du planificateur, la consommation par comparaison-échange du sas ou la garde de
l'adaptateur, faire exécuter le mode ombre, ne jamais expirer une activation, ne plus réserver le créneau, ignorer l'arrêt propre, traiter l'historique
comme de l'entrant, retirer la déduplication, ajouter un destinataire, rendre visible l'outil du sas, retirer CSRF, la comparaison d'initiateur du retour
OAuth ou le masquage du journal d'accès…). Au premier passage 5 ont survécu (fencing, comparaison-échange sous SQLite, arrêt propre, périmètre de l'envoi
en ombre) : les tests ont été renforcés (porteur dépossédé, écriture concurrente entre lecture et réservation, interruption observable, expiration en ombre)
et les 26 sont maintenant tuées. Une survivance d'origine mérite d'être dite : sous SQLite, `BEGIN IMMEDIATE` rend la comparaison-échange du sas redondante
au niveau d'une seule base ; elle n'est prouvée que par une écriture injectée entre la lecture et la réservation.

**Non prouvé** :
- Aucun service réel (voir le statut) ; le plugin PHP n'a jamais tourné ; `TransportUrllib` n'a jamais parlé à un serveur.
- Le filtre d'injection est un ensemble de motifs : il remplace le segment de consigne reconnu, la suite du texte reste une DONNÉE signalée non fiable. La barrière
  réelle est structurelle (destinataire imposé, aucun outil d'envoi, approbation N3), pas la détection.
- La concurrence est prouvée sur SQLite (fils et processus d'une même machine) ; aucun essai multi-machines ni sous charge, aucun essai de concurrence sur PostgreSQL.
- Le planificateur tourne dans le processus du serveur MCP ; un second processus du serveur est sûr (créneau et bail en base) mais cela n'a pas été exercé hors des tests.
- Le rafraîchissement concurrent d'un jeton OAuth entre deux processus n'est pas éprouvé (voir CONNECTEURS-COURRIEL §13).
- Rétention, purge, EFVP et conformité Loi 25 : à valider auprès d'un professionnel qualifié (avocat / conseiller en protection des renseignements personnels).
- Les compteurs d'un brouillon `courriel_contact` sont ceux du premier lot qui a vu le correspondant.
