# Connecteurs courriel — Gmail, Microsoft Graph, IMAP/SMTP, exports mbox (chantier 5, tranche 1)

Statut (2026-11-01) : **code livré, qualifié contre des DOUBLES seulement.** Aucun test de cette tranche n'a touché Gmail, Microsoft
Graph, un serveur IMAP/SMTP réel ni un fournisseur OAuth. Rien ci-dessous ne doit se lire « qualifié » ou « prêt pour la
production » ; voir « Plan de qualification réelle » et « Limites ».

Décisions d'architecte appliquées (`DECISIONS-ARCHITECTE-r1`, `FEUILLE-DE-ROUTE-TECHNO-r1` ligne « Courriel », recherche R3 §connecteurs) :
Gmail API avec le projet OAuth **du client** (type Internal) et des portées minimales ; Microsoft Graph avec requête delta (jamais EWS,
retiré) ; IMAP générique ; exports mbox pour l'historique ; secrets uniquement dans le coffre ; tout envoi est un brouillon N3.
Écart assumé avec la feuille de route : l'IMAP recommandé côté Node (ImapFlow, MIT) n'est pas utilisé ici ; ce paquet reste en
Python et en bibliothèque standard (`imaplib`, `smtplib`, `email`, `mailbox`-like maison pour mbox) : aucune dépendance ajoutée, donc aucune
entrée dans `docs/research/INGREDIENTS.md`.

Code : `src/opsys/courriel_connecteurs/` (déclaré dans `pyproject.toml`), `src/opsys/console/courriel_ui.py`, capacité « courriel »
dans `src/opsys/fournisseurs/`, migration `0040_connecteurs_courriel`. Tests : `tests/test_courriel_*.py`, doubles dans
`tests/fixtures/courriel_doubles.py` et montage dans `tests/fixtures/courriel_qa.py`.

## 0. Audit de l'existant (ce qui est réutilisé, ce qui ne l'est pas)

| Existant | Constat | Intégration |
|---|---|---|
| `opsys/connecteurs.py` | Configuration du connecteur **STT** (voix → texte) de M1, malgré son nom : aucun rapport avec le courriel | non réutilisé ; même discipline (références seulement, jamais de secret) |
| `opsys/reception_courriel_contrat.py`, `reception_courriel_stockage.py` | Codec et stockage chiffré d'**originaux IMAP** internes (`UIDVALIDITY`, `UID`), sans autorité ni surface hôte | pont `originaux.py` : arguments valides pour un message IMAP lu (testé contre `recevoir`/`lire` avec des rappels de test) ; **aucune autorité raccordée** |
| `opsys/ingestion_onboarding/` | Dépôt par nom, tâches durables, brouillons AP/CRM à confirmer | alimentation par `deposer` (archive déterministe), jamais de chemin parallèle |
| `m1_front_office/reception.py` | `preparer(canal="courriel", …)` : chemin vivant d'un message entrant | `isolation.arguments_reception_m1` (incrémental seulement) |
| `m1_front_office/provenance.py` | filtre anti-injection R-015 | appliqué champ par champ (import différé, fail-closed) |
| `opsys/secrets_coffre` | jetons opaques, AES-GCM en enveloppe, administrateur requis | seul lieu des jetons OAuth et mots de passe d'application |
| `opsys/approbations.py` | sas N3, `decider`, `approbateur_en_cours` | demande + outil `opsys_courriel_approuver_envoi` + garde d'envoi |
| `opsys/fournisseurs/` | registre + politique de licence | capacité « courriel » |

## 1. Architecture

```
            ┌────────────────────────── ServiceCourriel (connexion, révocation, fabrique d'adaptateurs) ─────────────┐
 admin ───► │ comptes (état, consentement Loi 25, curseurs, journal append-only)      oauth (PKCE, state, portées)    │
            └──────────────┬──────────────────────────────────────────────────────────────┬────────────────────────┘
                           │                                                              │ jetons : COFFRE seulement
   FournisseurCourriel (port)                                                   jetons.StockageJetonsCoffre
   ├─ gmail   (REST)  ┐                                                                    ▲
   ├─ graph   (REST)  ├─ ClientApi (401→refresh, 429/Retry-After, 5xx, hôtes) ◄─ Transport (INJECTÉ ; urllib en production)
   ├─ imap    (imaplib/smtplib, fabriques INJECTÉES)
   └─ mbox    (lecture seule, fichier déposé)
        │ MessageBrut (RFC 5322)
        ▼
  normalisation ─► MessageNormalise ─► ingestion ─► ZIP déterministe ─► ingestion_onboarding.service.deposer ─► brouillons AP / CRM
        │                                  (idempotence, quota, reprise)                 (N3 : décision humaine existante)
        └─► isolation.vue_pour_agent (SEUL format montré à un agent : neutralisé, signalé, provenance)

  envoi : creer_brouillon (scellé, empreinte) → demander_approbation (sas N3) → décision humaine → ServiceEnvoi.envoyer
          → adaptateur.envoyer_brouillon(brouillon, JetonApprobation) → GardeEnvoiSas (vérifie + consomme) → transport
```

## 2. Le port `FournisseurCourriel`

`lister_boites()`, `lister_dossiers()`, `synchroniser(dossier, curseur, limite)`, `lire_message(ref)`, `envoyer_brouillon(brouillon, jeton)`.

| Fournisseur | Curseur opaque (`<préfixe>:v1:…`) | Amorçage | Incrémental | Suppressions vues |
|---|---|---|---|---|
| Gmail | phase `l` (jeton de page) puis `h` (historyId) | `users.getProfile` lu AVANT `messages.list` | `users.history.list` | oui (`messagesDeleted`) |
| Graph | `nextLink` puis `deltaLink` revalidés | `…/mailFolders/{id}/messages/delta` | idem | oui (`@removed`) |
| IMAP | (dossier, UIDVALIDITY, dernier UID) | `UID SEARCH UID 1:*` | `UID n:*` refiltré | non (pas de QRESYNC) |
| mbox | (décalage en octets, taille du fichier, nombre) | lecture ligne à ligne | — (fichier fini) | non |

- Le curseur d'une `PageSync` ne couvre que cette page : l'ingestion ne le persiste qu'**après** avoir traité la page.
- Curseur périmé (`historyId` 404, `deltaLink` 410, UIDVALIDITY changé, fichier mbox modifié) : `REJ-COURRIEL-CURSEUR-EXPIRE`
  (reprenable) ; l'ingestion efface le curseur et relance un amorçage, l'idempotence absorbe les messages déjà vus.
- Graph : `Prefer: IdType="ImmutableId"` sur chaque appel (l'identifiant d'un message ne change pas quand il change de dossier ;
  il change s'il passe à une boîte d'archive ou est réimporté — source : Microsoft Learn, « Obtain immutable identifiers for Outlook
  resources », https://learn.microsoft.com/graph/outlook-immutable-id).
- Gmail : `historyId` « typiquement valide au moins une semaine, parfois quelques heures » ; 404 → synchronisation complète
  (source : https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list).
- Tout identifiant venant d'un serveur est validé par expression régulière avant d'entrer dans une URL ; tout lien de pagination est
  revalidé (HTTPS, hôte du fournisseur, sans identifiant ni port, chemin sous `/v1.0/me/mailFolders/` pour Graph).
- IMAP : `SELECT` en lecture seule, `BODY.PEEK[]` (jamais marqué lu), taille demandée avant téléchargement, noms de dossier cités et
  échappés, CR/LF/NUL refusés, hôtes privés ou `localhost` refusés. Connexion TLS implicite seulement (pas de STARTTLS).

## 3. Cycle OAuth côté serveur

1. `demarrer_autorisation` (administrateur, **consentement Loi 25 consigné**) : URL avec `response_type=code`, `scope` = portées
   minimales de l'usage, `code_challenge` PKCE S256, `state` = charge JSON + HMAC-SHA256 (clé serveur, tirée du coffre en production).
   Le `code_verifier` n'est jamais stocké : il se re-dérive du nonce du `state` par HMAC.
2. `terminer_autorisation` : signature, expiration (10 min), puis **consommation atomique du nonce** (`courriel_etats_oauth`) validée
   même si l'échange échoue ensuite ; échange du code via le `Transport` injecté ; **portées accordées vérifiées** ; jeton d'accès +
   refresh token écrits dans le coffre (`courriel.<compte>.g<génération>`, AES-256-GCM en enveloppe, clé maîtresse hors base).
3. Rafraîchissement : proactif à 60 s de l'expiration, et sur 401 (une seule fois). Verrou par instance + relecture du coffre avant
   d'appeler le fournisseur. **Rotation** : si le fournisseur renvoie un nouveau refresh token, il remplace l'ancien ; sinon l'ancien
   est conservé. Les portées sont revérifiées à chaque rafraîchissement.
4. Révocation : appel au point de révocation du fournisseur quand il existe (Google), puis révocation du secret dans le coffre (octets
   détruits), état `revoque` terminal. Microsoft n'a pas de point de révocation par jeton utilisé ici : le retrait du consentement
   se fait dans Entra (documenté, non automatisé).
5. États d'un compte : `non_connecte`, `autorisation_en_cours`, `connecte`, `reconnexion_requise` (jeton révoqué/expiré, 401 répété,
   portée excessive, coffre refusé), `revoque`, `erreur`.

Le coffre exige un administrateur actif pour définir, tourner ou révoquer un secret : l'identité de la personne qui a connecté le
compte est relue en base à chaque opération. Si elle n'est plus administratrice, le rafraîchissement est refusé
(`REJ-COURRIEL-COFFRE-REFUSE`) et le compte passe en « reconnexion requise ». Aucun contournement du coffre.

## 4. Portées minimales par fournisseur

| Fournisseur | Lecture (requise) | Envoi (seulement si usage `lecture_envoi`) | Toléré | Tout le reste |
|---|---|---|---|---|
| Gmail | `https://www.googleapis.com/auth/gmail.readonly` | `https://www.googleapis.com/auth/gmail.send` | — | `REJ-COURRIEL-PORTEE-EXCESSIVE` |
| Graph (délégué) | `Mail.Read` | `Mail.Send` | `offline_access`, `openid`, `profile`, `email` | idem (`Mail.ReadWrite`, `*.Shared`, `*.All`, `Files.*`…) |
| IMAP/SMTP | mot de passe d'application (pas de portée OAuth) | idem | — | XOAUTH2 non pris en charge |

Sources officielles :
- Gmail — liste et classification des scopes : https://developers.google.com/workspace/gmail/api/auth/scopes (lue le 2026-11-01) :
  `gmail.readonly` **restreint**, `gmail.send` **sensible**, `gmail.compose`, `gmail.modify`, `gmail.metadata` et `https://mail.google.com/`
  **restreints**. Un scope restreint exige vérification + évaluation de sécurité annuelle (CASA) dès que les données passent par un
  serveur, sauf projet « Internal » de l'organisation Workspace du client (R3 §connecteurs, https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).
  C'est pourquoi `gmail.readonly` seul est demandé à l'onboarding (jamais `mail.google.com` ni `gmail.modify`) et `gmail.send`
  n'est ajouté que pour un compte qui doit envoyer.
- Graph — permissions : https://learn.microsoft.com/graph/permissions-reference (lue le 2026-11-01) : `Mail.Read` et `Mail.Send` délégués,
  consentement administrateur non requis ; `Mail.ReadWrite` « ne comprend pas l'envoi » et modifie le courrier : refusé ici ;
  `offline_access` est un scope OIDC qui n'ajoute aucun accès. Requête delta : https://learn.microsoft.com/graph/delta-query-messages.
- Les paramètres PKCE et `access_type=offline`/`prompt=consent` côté Google, et l'identifiant de serveur `mx.google.com` dans
  `Authentication-Results`, sont **à vérifier** à la qualification réelle (non relus à la source dans cette tranche).
- Les jetons de portée de Graph arrivent parfois préfixés (`https://graph.microsoft.com/Mail.Read`) et sans casse stable : la
  comparaison retire le préfixe et ignore la casse.

## 5. Normalisation et isolation du contenu

`MessageNormalise` : identifiant fournisseur, dossier, fil (fournisseur sinon dérivé de `References`/`In-Reply-To`/`Message-ID`),
`Message-ID`, expéditeur, destinataires, copie, adresse de réponse, objet (une ligne), date en UTC, corps texte, pièces jointes
(`sha256`, taille, type déclaré, **type détecté par octets magiques**, `mime_verifie`, cohérence de l'extension, `dangereux`),
verdicts SPF/DKIM/DMARC et empreinte du contenu.

- HTML réduit à son **texte visible** : scripts, styles, commentaires, `display:none`, taille 0, `hidden`, `aria-hidden`,
  `opacity:0`, gabarits sont écartés (vecteur classique d'injection invisible).
- Caractères de contrôle, invisibles (largeur nulle, soft hyphen) et marques bidirectionnelles retirés ; noms de pièces jamais un chemin.
- `Authentication-Results` : seul l'en-tête le plus haut est lu ; les verdicts sont **rapportés**, jamais revérifiés, et `fiable`
  n'est vrai que si l'identifiant du serveur figure dans la liste configurée du compte.
- Bornes : 32 Mio par message, 100 pièces, 8 Mio par pièce (au-delà : empreinte seulement), 200 000 caractères de corps.

**Le corps d'un courriel est une donnée non fiable.** `isolation.vue_pour_agent` est le seul format montré à un agent :
normalisation NFKC, filtre anti-injection de provenance de M1 (`m1_front_office.provenance.filtrer`, appliqué champ par champ :
objet, corps, noms de personnes, noms de pièces, adresse de réponse), **signaux du garde-fou de texte** (`opsys.garde_fou_texte`,
familles prix, date d'exécution, engagement, aveu, avis légal : le texte entrant dit qu'il contient une promesse ou un avis légal
que l'agent ne doit pas reprendre à son compte), `provenance` (source, fournisseur, compte, `fiabilite: non_fiable`, avertissement).
Si le filtre est introuvable, la vue est refusée (fail-closed). `arguments_reception_m1` produit les arguments de
`m1_front_office.reception.preparer` pour le chemin **incrémental vivant** de M1 ; l'historique d'onboarding ne l'emprunte jamais.

## 6. Ingestion dans la file d'onboarding

`IngestionCourriel.synchroniser(compte, fournisseur, dossier)` (ou `synchroniser_compte` pour tous les dossiers suivis) :

- les pièces admises (PDF, PNG, JPEG, texte, CSV, XLSX **d'après leur signature**) sont empaquetées dans une archive ZIP
  déterministe, déposée dans `<OPSYS_HOME>/imports/onboarding/` (nom = SHA-256, `O_EXCL`, jamais d'écrasement) et confiée à
  `ingestion_onboarding.service.deposer` ; le pipeline existant refait ses contrôles (types, archive gardée, quotas, dédoublonnage SHA-256,
  chiffrement). Les brouillons AP (M5) et CRM (M2) qui en sortent attendent la décision humaine existante : **mode « brouillon à confirmer »**.
- pièces refusées avec leur raison, jamais transmises ni exécutées : `dangereux` (exécutable, script, HTML/SVG, macro Office),
  `type_incoherent` (déclaré ≠ détecté), `extension_incoherente`, `type_non_accepte` (zip, binaire…), `trop_gros`, `vide`.
- **Idempotence** : clé = `Message-ID` (sinon référence fournisseur) + empreinte du contenu (`courriel_messages`) ; références
  déjà traitées mémorisées (`courriel_refs`) pour ne pas relire un message déjà fait.
- **Reprise** : curseur persisté après la page, dans la même transaction que les clés d'idempotence ; un arrêt entre le dépôt et la
  validation rejoue le même lot (archive identique → même clé de mutation).
- **Débit** : `LimiteurDebit` (seau à jetons, horloge injectée). À sec, la page en cours est validée pour ce qui est fait et
  **le curseur n'avance pas** ; le reste suit au prochain passage (progrès garanti même si la page dépasse le débit).
- Un message illisible, trop gros ou disparu n'arrête pas l'ingestion.
- **Non fait ici** : le corps des courriels n'est ni stocké ni indexé (aucun genre de brouillon « courriel » dans l'ingestion
  d'onboarding : seuls `ap_facture_fournisseur` et `crm_client` existent) ; il alimentera la mémoire M10 dans une tranche ultérieure.
- Exports mbox (`FournisseurMbox`, compte de fournisseur `mbox`) : voir ci-dessous.

### Exports mbox

Fichier déposé dans `<OPSYS_HOME>/imports/courriel/`, lu par son **nom seul** (`*.mbox`, `*.mbox.gz`), `O_NOFOLLOW`, fichier ordinaire,
lecture seule (aucune écriture : testé par comparaison des octets et des dates). Bornes : fichier 10 Gio (2 Gio compressé), 1 000 000
de messages, 32 Mio par message (référencé mais jamais chargé au-delà), ligne de 64 Kio, **bombe de décompression** `.gz` (taille
décompressée 20 Gio et ratio 100 une fois 64 Mio décompressés), séparateur `From ` reconnu seulement après une ligne vide et avec une
date, `>From` désécapé (mboxrd). Un `.gz` se reprend en relisant depuis le début (coûteux sur de très gros fichiers).

## 7. Envoi sous sas d'approbation

Un envoi n'est **jamais direct** : c'est un brouillon dont la transmission est N3.

1. `creer_brouillon` : adresses nues validées (pas de nom, pas de CR/LF/NUL : **injection d'en-têtes refusée**), objet une ligne,
   pièces (types permis, signature = type déclaré, nom sûr, 5 pièces / 5 Mio), **garde-fou de texte de sortie** (prix, date
   d'exécution, engagement, aveu, avis légal : `REJ-COURRIEL-BROUILLON-GARDE-FOU`, remplaçable par un appelant de confiance),
   expéditeur = adresse du compte (non choisi par l'appelant). Contenu **scellé** (AES-GCM, clé d'ingestion) et lié à une
   `empreinte` SHA-256 de tout ce qui part (expéditeur, à/cc/cci, objet, corps, pièces par empreinte, réponse à).
2. `demander_approbation` : `approbations.creer_demande(…, niveau=N3)` ; arguments : empreinte, destinataires, objet, **contexte** et
   **sources** obligatoires, jamais le corps. Département par défaut `m01-front-office` (politique d'approbation N3 de son manifeste).
3. Décision humaine par `approbations.decider` avec l'outil `opsys_courriel_approuver_envoi` (N3, fermé aux appareils) : il relit le
   brouillon dans la transaction de la décision et le marque `APPROUVE` seulement si l'empreinte soumise est l'actuelle ; il
   n'envoie rien.
4. `ServiceEnvoi.envoyer` présente un `JetonApprobation(demande, empreinte)` à `envoyer_brouillon`. Les adaptateurs n'ont **aucune**
   autre méthode d'envoi ; sans garde raccordée, tout envoi est refusé. La `GardeEnvoiSas` vérifie contre la base du sas : demande
   existante, outil, niveau ≥ N3, statut `executee`, approbateur **humain actif** (relu), brouillon/révision/empreinte/compte
   concordants, compte connecté en envoi ; puis **consomme** par comparaison-échange (`APPROUVE` → `ENVOI_RESERVE`) dans une
   transaction **validée avant** le premier octet réseau.
5. Issues : `envoye` ; `non_traite` (429 : réservation rendue, le même jeton resserre) ; `echec` (refus définitif : nouveau
   brouillon approuvé requis) ; `incertain` (5xx, coupure : le message a peut-être été remis ; **jamais de reprise automatique**).
   Une réservation jamais terminée devient `INCERTAIN` (`marquer_reservations_orphelines`).

Le jeton n'est pas un secret porteur : sa valeur tient à l'état du sas, relu à chaque envoi. Cas testés : sans jeton, jeton vide ou
inconnu, demande en attente / refusée, jeton rejoué (séquentiel et concurrent), brouillon modifié après approbation, destinataire
ajouté (à, cc, cci), approbation d'un autre brouillon ou d'un autre outil, niveau insuffisant, approbateur désactivé ou agent,
compte révoqué, en-têtes injectés.

## 8. Registre, console, journal

- **Registre de fournisseurs** : capacité « courriel » (`courriel.gmail.api`, `courriel.graph.api`, `courriel.imap.generique`,
  `courriel.mbox.local`), licence `sur_contrat` pour Gmail/Graph (le contrat est celui du client : `contrat_ref` requis) et EFVP
  requise hors Québec (`EFVP_REQUISE`) — la politique existante fait le travail. Toutes à `qualification: a_mesurer`.
  Le raccordement automatique du registre à `ServiceCourriel` (résoudre le fournisseur actif par département) n'est pas fait.
- **Console** `/courriel`, `/courriel/comptes/{id}` (+ API JSON) : état, portées, consentement, dernier synchro, **dernier code
  d'erreur typé**, brouillons (statut seulement), journal ; administrateur relu en base, `no-store`, aucun jeton ni contenu.
- **Journal** `courriel_journal` : append-only (déclencheurs SQLite et PostgreSQL), détails limités à une liste blanche de clés
  scalaires courtes : ni contenu, ni adresse de correspondant, ni jeton (rejet par `ValueError` sinon).
- Tables : `courriel_comptes`, `courriel_etats_oauth`, `courriel_messages`, `courriel_refs`, `courriel_brouillons`, `courriel_journal`.
  Aucune ne contient de jeton ; les brouillons sont scellés ; les messages lus ne laissent qu'une clé et une empreinte.

## 9. Mapping des erreurs

| Situation chez le fournisseur / le système | Code | Reprenable | État du compte |
|---|---|---|---|
| 401, puis 401 après un rafraîchissement | `REJ-COURRIEL-AUTH-REFUSEE` | non | reconnexion requise |
| `invalid_grant` au rafraîchissement | `REJ-COURRIEL-JETON-REVOQUE` | non | reconnexion requise |
| portée excessive / manquante accordée | `REJ-COURRIEL-PORTEE-EXCESSIVE` / `-INSUFFISANTE` | non | erreur ou reconnexion |
| 403 `rateLimitExceeded`, `userRateLimitExceeded`, 429 | `REJ-COURRIEL-LIMITE-DEBIT` (après attente bornée de 30 s) | oui (`reessayer_apres_s`) | inchangé |
| 403 autre | `REJ-COURRIEL-PERMISSION-REFUSEE` | non | inchangé |
| 404 (message) / 404 `history` / 410 delta / UIDVALIDITY | `…-INTROUVABLE` / `…-CURSEUR-EXPIRE` | — / oui | inchangé |
| 5xx répétés / délai / connexion | `REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE` / `…-RESEAU` | oui | inchangé |
| 5xx ou coupure pendant un envoi | `REJ-COURRIEL-ENVOI-INCERTAIN` | **non** | brouillon `INCERTAIN` |
| autre 4xx | `REJ-COURRIEL-REQUETE-INVALIDE` | non | inchangé |
| lien de pagination hors hôte | `REJ-COURRIEL-LIEN-NON-AUTORISE` | non | inchangé |
| IMAP : mauvais mot de passe | `REJ-COURRIEL-IMAP-AUTH` | non | reconnexion requise |
| file d'onboarding saturée (429/507) | `REJ-COURRIEL-INGESTION-REFUSEE` | oui | inchangé |

Une erreur ne recopie **jamais** le corps de la réponse du fournisseur (il peut contenir du courriel) ni un en-tête ; tout détail est
masqué par `secrets_coffre.masquage`. Codes (liste fermée, épinglée par `tests/test_courriel_documentation.py`) :

- `REJ-COURRIEL-ARGUMENT-INVALIDE`
- `REJ-COURRIEL-FOURNISSEUR-INCONNU`
- `REJ-COURRIEL-COMPTE-INCONNU`
- `REJ-COURRIEL-COMPTE-INACTIF`
- `REJ-COURRIEL-COMPTE-EXISTE`
- `REJ-COURRIEL-CONSENTEMENT-ABSENT`
- `REJ-COURRIEL-ADMIN-REQUIS`
- `REJ-COURRIEL-OAUTH-ETAT-INVALIDE`
- `REJ-COURRIEL-OAUTH-ETAT-EXPIRE`
- `REJ-COURRIEL-OAUTH-ETAT-REUTILISE`
- `REJ-COURRIEL-OAUTH-ECHANGE-REFUSE`
- `REJ-COURRIEL-OAUTH-CONFIGURATION`
- `REJ-COURRIEL-PORTEE-EXCESSIVE`
- `REJ-COURRIEL-PORTEE-INSUFFISANTE`
- `REJ-COURRIEL-REFRESH-ABSENT`
- `REJ-COURRIEL-JETON-REVOQUE`
- `REJ-COURRIEL-JETON-EXPIRE`
- `REJ-COURRIEL-COFFRE-INDISPONIBLE`
- `REJ-COURRIEL-COFFRE-REFUSE`
- `REJ-COURRIEL-AUTH-REFUSEE`
- `REJ-COURRIEL-PERMISSION-REFUSEE`
- `REJ-COURRIEL-LIMITE-DEBIT`
- `REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE`
- `REJ-COURRIEL-RESEAU`
- `REJ-COURRIEL-REQUETE-INVALIDE`
- `REJ-COURRIEL-INTROUVABLE`
- `REJ-COURRIEL-REPONSE-INVALIDE`
- `REJ-COURRIEL-LIEN-NON-AUTORISE`
- `REJ-COURRIEL-CURSEUR-INVALIDE`
- `REJ-COURRIEL-CURSEUR-EXPIRE`
- `REJ-COURRIEL-IMAP-AUTH`
- `REJ-COURRIEL-IMAP-PROTOCOLE`
- `REJ-COURRIEL-MESSAGE-INVALIDE`
- `REJ-COURRIEL-MESSAGE-TROP-GROS`
- `REJ-COURRIEL-FILTRE-INDISPONIBLE`
- `REJ-COURRIEL-QUOTA-DEBIT`
- `REJ-COURRIEL-INGESTION-REFUSEE`
- `REJ-COURRIEL-MBOX-NOM-INVALIDE`
- `REJ-COURRIEL-MBOX-ABSENT`
- `REJ-COURRIEL-MBOX-TROP-GROS`
- `REJ-COURRIEL-MBOX-BOMBE`
- `REJ-COURRIEL-MBOX-FORMAT`
- `REJ-COURRIEL-BROUILLON-INCONNU`
- `REJ-COURRIEL-BROUILLON-INVALIDE`
- `REJ-COURRIEL-BROUILLON-TROP-GROS`
- `REJ-COURRIEL-BROUILLON-GARDE-FOU`
- `REJ-COURRIEL-BROUILLON-ETAT`
- `REJ-COURRIEL-APPROBATION-ABSENTE`
- `REJ-COURRIEL-APPROBATION-INVALIDE`
- `REJ-COURRIEL-APPROBATION-NON-APPROUVEE`
- `REJ-COURRIEL-APPROBATION-REJOUEE`
- `REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE`
- `REJ-COURRIEL-ENVOI-ECHEC`
- `REJ-COURRIEL-ENVOI-INCERTAIN`
- `REJ-COURRIEL-ENVOI-NON-SUPPORTE`

## 10. Loi 25

- **Consentement** : un compte ne se connecte pas sans consentement consigné (`consentement_le`, `consentement_par`) pour une
  **finalité déclarée** (`finalite`, 500 caractères). Sans lui : `REJ-COURRIEL-CONSENTEMENT-ABSENT`, même pour un mot de passe d'application.
- **Minimisation** : portées minimales ; dossiers suivis déclarés par compte (par défaut la boîte de réception seule) ; le client peut
  exclure ses dossiers personnels ; le corps n'est pas conservé ; les originaux d'ingestion sont scellés.
- **Rétention** : `retention_jours` (1 à 3650) est **déclarée** par compte. **La purge n'est pas implémentée** : aucune tâche n'efface
  encore les originaux ni les clés d'idempotence à l'échéance. À faire avant tout usage réel.
- **Communication hors Québec** : Gmail (États-Unis) et Graph exigent une EFVP préalable (`efvp_ref`), vérifiée par la politique du
  registre. EFVP avant le projet (LPRPSP art. 3.3 et art. 17 : voir recherche R3). « À valider auprès d'un professionnel
  qualifié (avocat / conseiller en protection des renseignements personnels) » : ce document ne constitue pas un avis juridique.
- **Journal** sans contenu ni adresse de correspondant ; révocation immédiate d'un compte (secret détruit).

## 11. Migration et numérotation

Migration **0040** (`0040_connecteurs_courriel.py`) : six tables, déclencheurs du journal, et élargissement de la contrainte
`fournisseurs_configurations.capacite` à « courriel » (reconstruction de table sur SQLite). Elle porte le numéro 0040 pour ne pas
entrer en collision avec une 0039 visée par un autre chantier ; **`down_revision` vaut « 0038 »** (la tête de ce worktree).
À l'intégration : si 0039 existe, remplacer `down_revision = "0038"` par `"0039"` et réaligner trois tests qui épinglent la tête
(`tests/test_wct_attente_migration_qa.py`, `tests/test_coffre_secrets.py`, `tests/test_courriel_registre_console.py`) ; si les deux
migrations visent la même tête sans être chaînées, `get_heads()` renverra deux têtes. La descente est refusée dès qu'une ligne existe
dans une table du chantier ou qu'un fournisseur « courriel » est configuré. Testée sur SQLite et sur PostgreSQL éphémère (conteneur).

## 12. Plan de qualification réelle (NON fait ici)

À faire avec un compte **fictif** du client, jamais une vraie boîte :
1. Gmail : projet Google Cloud de type Internal dans un Workspace de test ; autoriser `gmail.readonly` ; vérifier l'URL (PKCE,
   `access_type=offline`, `prompt=consent`) ; échange ; rafraîchissement ; **est-ce que le refresh token est renvoyé à chaque
   consentement ?** ; amorçage de 1 000 messages avec mesure des unités de quota ; incrémental ; `historyId` volontairement vieilli ;
   authserv-id réel d'`Authentication-Results` ; `gmail.send` : format du `raw`, comportement de l'en-tête `Bcc`, `Message-ID` généré.
2. Graph : application Entra mono-locataire ; `Mail.Read` délégué ; delta sur 3 dossiers ; `@removed` ; `deltaLink` périmé (410) ;
   `ImmutableId` après un déplacement ; throttling réel (429 + `Retry-After`) ; `sendMail` (202, `saveToSentItems`, pièce de 3 Mio) ;
   restriction par politique d'accès aux boîtes (RBAC for Applications).
3. IMAP : serveurs réels (Gmail IMAP, Outlook, Dovecot) : UIDVALIDITY, `UID n:*`, noms de dossiers en UTF-7 modifié, `BODY.PEEK[]`
   sur messages > 10 Mio, délais, `SMTP_SSL`, rejet de destinataires.
4. mbox : un vrai export Google Takeout (`.mbox`) et un export Thunderbird ; séparateurs ; très gros fichier (mesure mémoire/temps).
5. `TransportUrllib` : TLS réel, proxys d'entreprise, délais, corps tronqués.
6. De bout en bout : un compte fictif → file d'onboarding → brouillons → décision humaine → un envoi N3 réel vers une adresse de test.
7. Mesures : débit réel, taux de doublons, faux positifs du filtre d'injection sur un corpus de courriels fictifs québécois.

## 13. Limites (sans euphémisme)

- **Jamais exécuté contre un vrai service.** Les doubles (`FauxGmail`, `FauxGraph`, `FauxOAuth`, `FauxImap4SSL`, `FauxSmtpSSL`) sont
  écrits d'après la documentation ; un défaut de compréhension de l'API se reproduirait dans le code ET dans le double.
- `TransportUrllib` n'a été testé qu'avec un `ouvrir` injecté. Aucun point de HTTP réel, aucune négociation TLS vérifiée.
- Le filtre d'injection est un ensemble de motifs : une formulation qu'il ne connaît pas passe. La protection réelle est l'absence
  d'outil d'action dans un contexte de lecture et la validation humaine N3 des envois ; elle dépend du câblage des agents, non vérifié ici.
- L'**outil d'approbation et les services ne sont pas raccordés** au serveur MCP, à `Capacites` ni à un manifeste de département
  (aucun département n'a été touché) ; la route de retour OAuth (`redirect_uri`) et les écrans de connexion, d'envoi et de décision n'existent pas.
  La console est en lecture seule.
- **Rétention non appliquée** (voir Loi 25) ; corps des courriels non conservé ; aucun genre de brouillon « courriel » dans l'onboarding.
- Pas de QRESYNC/CONDSTORE (suppressions IMAP invisibles), pas de XOAUTH2, pas de STARTTLS, pas de sous-dossiers Graph, un `.mbox.gz`
  se relit depuis le début à chaque reprise, pas de PST/EML.
- Le rafraîchissement concurrent est protégé dans un processus (verrou) et par relecture du coffre ; deux processus simultanés avec
  un fournisseur qui fait tourner le refresh token peuvent s'invalider mutuellement (non éprouvé).
- Le garde-fou de texte de sortie (prix, engagement…) est celui de M1 : trop strict pour un courriel qui doit légitimement contenir un
  prix (`profil=None` réservé à un appelant de confiance). Un humain doit lire le brouillon avant d'approuver : la console ne l'affiche pas encore.
- Les caractères de largeur nulle ou stylisés sont ramenés par NFKC avant le filtre, mais le texte rendu à l'agent est la forme normalisée.
- PostgreSQL : la migration est testée ; l'exécution des connecteurs n'est testée que sur SQLite.
