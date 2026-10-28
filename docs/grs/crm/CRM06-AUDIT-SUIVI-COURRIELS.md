# CRM06 — audit du suivi des courriels avant code

Date : 28 octobre 2026 UTC. Source : `4f80ab7f7bf95dc5ae00fd59db3c4f940e44f816`.
Owner : M1 pour la réception/canaux, M2 pour le rattachement client/projet, console pour la restitution.
CRM06 reste MANQUANT pour les courriels; OPSYS reste PARTIAL. Aucun message réel ni secret utilisé.
Préflight M10 de développement privé frais : `crm06-imap-m10-preflight-v1`, distinct de la mémoire projet.

## Existant et preuves manquantes

`core/extensions/imap/src/watcher.ts` ouvre la boîte en lecture seule, contrôle l’expéditeur puis
appelle `dispatchHookAgentTurn`. Son succès atteste l’admission d’un tour agent, pas une réception
métier durable. `prompt.ts` normalise/tronque le texte; il ne prouve pas le message original.
`state.ts` conserve curseur, claims expirant après sept jours et ring des cent Message-ID : pas
une archive. M1 `reception.py` valide le correspondant/canal; `outils.py` conserve le texte filtré.
Ni conversation par adresse ni client global ne désignent un chantier exact.

Le host SMS possède une capture privée et un ACK transactionnel (`opsys-sms-ingress-capture.ts`,
`opsys-sms-receipt-gate.ts`, `reception_sms_runtime.py`, `reception_sms_receipt.py`). Réutiliser
leur architecture de capture, autorité actuelle avant rejeu et reçu durable; jamais leurs droits
Twilio ni leurs assertions d’origine pour un courriel. Aucun outil modèle ne doit affirmer sa réception.

## Recherche de réutilisation

IMAP natif déjà équipé d’`imapflow 2.0.2`, `mailauth 5.0.3`, `mailparser 3.9.26` dans le lock local.
Pas de remplacement ou installation. [ImapFlow](https://github.com/postalsys/imapflow) annonce MIT;
[licence Mailparser](https://github.com/nodemailer/mailparser/blob/master/LICENSE) MIT, tandis que
son [README](https://github.com/nodemailer/mailparser) annonce désormais la maintenance seulement.
Ce constat amont ne change pas les versions locales et ne qualifie pas une montée de version.
Recherche GitLab : [Mailman/HyperKitty](https://gitlab.com/mailman/mailman-hyperkitty) est une archive
de listes, pas le contrat M1/projet recherché; aucune adoption, extraction ou licence supposée.
Les bibliothèques natives suffisent; aucun nouvel ingrédient ajouté.

## Constat à corriger avant le nouveau raccord

Le curseur durable est indexé par compte seulement. `initializeImapCursor` reprend une UIDValidity
identique sans connaître la boîte. Changer INBOX vers une autre boîte sous le même compte peut donc
réutiliser la progression d’un espace UID étranger. La clé de claim omet également la boîte et le
Message-ID déclaratif ne peut pas remplacer la provenance IMAP. Revue indépendante statique confirme
ces frontières; une reproduction doit encore qualifier le premier constat.

### Décision de tranche : lier le curseur à sa boîte, refuser l’ambiguïté

Premier correctif borné : enregistrer la boîte avec chaque nouveau curseur; même boîte/UIDValidity
reprend, changement de boîte refuse avant FETCH et avant avance. Un curseur historique sans boîte
est ambigu : refus explicite, conservation intégrale, aucune migration/devinette/réinitialisation
silencieuse. Un changement d’UIDValidity dans la même boîte garde le reset natif documenté.
La comparaison de boîte est exacte et conservatrice; aucun alias/casse/Unicode présumé.
Le site d’avance doit relire le curseur et sa boîte; identité incohérente = aucune écriture.

Alternative écartée : nouveau namespace avec baseline automatique, car il pourrait ignorer des
messages encore en attente. Le multi-boîtes partagé, le changement de serveur sous le même compte,
les claims/rings et la provenance durable demandent des tranches distinctes; aucun succès global
annoncé par ce seul garde. L’exploitation d’un curseur ancien nécessite une procédure de reprise
vérifiée avant activation; ce patch ne purge ni ne requalifie l’historique et n’est pas déployé.

## Architecture cible du suivi complet, non livrée ici

Capturer après contrôle d’expéditeur et avant tour modèle : compte, boîte, UIDValidity/UID, Message-ID
optionnel, source brute complète et SHA, corps/encodage versionnés, réception serveur et verdict
explicite. Date du message, date interne IMAP et réception serveur distinctes. Source tronquée =
refus ou état partiel nommé. ACK durable avant progression; même identité/autres octets = conflit.
D’abord « à rattacher », puis liaison admin au lead M2 exact relu avec CAS/audit. Une réponse ou un
Message-ID ne suffit pas à choisir un projet. Aucun envoyé/livré sans preuve native distincte.

## Tests, permissions et suite

Avant correction : prouver qu’une autre boîte réutilise le curseur à tort. Après : reprise légitime,
autre boîte et legacy refusés sans DML, avance refusée si boîte change, reset UIDValidity conservé,
appels watcher raccordés et fixture de packaging explicitement liée à sa boîte. Tests IMAP natifs
ciblés, lint et preuve protocole réelle si prérequis disponible; tout blocage de harnais reste nommé.
CPU/mémoire/temps/processus bornés, home/tmp privés avant imports, Source RO, données fictives.
Aucun nouveau droit, exposition, connexion réelle, modification fournisseur, envoi, purge ou modèle.
Le suivi CRM, les fils/réponses et l’automatisation IMAP→M1→M2 restent à implémenter après ce garde.

## Résultat du premier correctif

Trois tests ont reproduit les reprises/avances ambiguës. La revue indépendante a ensuite identifié
le contrôle tautologique d’un curseur changé après ouverture; quatre rouges supplémentaires couvrent
ce scénario (boîte différente, legacy et UIDValidity), puis une seule passe de correction les ferme.
Le watcher conserve maintenant la boîte **et l’UIDValidity réellement ouvertes par connexion**,
contrôle le curseur avant FETCH et avant chaque message après FETCH, et avance depuis cette identité.
Le raccord ne prend plus `cursor.mailbox` pour preuve de la boîte de la connexion.

`imap-v7` : **47 PASS**, format/lint natifs OK, sources épinglées et unités fermées. Dont deux essais
sur le vrai store SQLite du SDK : entête SQLite sous home fictif, fermeture/réouverture et conservation
exacte des curseurs lié/legacy. Les scénarios de transport sont explicitement mockés; aucune preuve
TCP, connexion réelle ou réception métier M1 n’est revendiquée. Le test de confinement loopback
n’a pas prouvé le filtre noyau : réseau des tests resté interdit. Les erreurs de prérequis OpenSSL,
cache Vite, collision d’artefact de formatage et répertoire global du coordinateur restent distinctes
des bugs produit. Le dernier est résolu par le sélecteur natif du coordinateur dans le home privé,
sans permission d’écriture ajoutée à `/tmp`. Diagnostic fictif temporaire retiré.

Voir [garde, limites et activation](CRM06-IMAP-GARDE-BOITE.md). Suivi client courriel complet toujours
MANQUANT, activation d’un ancien état ambigu soumise à une procédure de reprise validée.

## Tranche suivante : contrat original

Le [codec pur](CRM06-COURRIEL-CONTRAT.md) contrôle la capture binaire, son identité et ses bornes.
60 tests natifs passent après correction causale mémoire et copie privée concurrente. Aucun stockage,
ACK M1, capacité Host, permission ou rattachement n’est livré par ce seul composant.

## Fondation SQLite interne

Le [propriétaire chiffré](CRM06-COURRIEL-STOCKAGE.md) ajoute original/reçu/audit atomiques,
contrôle vivant injecté, vérification de clé et readback SQL avant commit. Aucun connecteur ou
profil M1 actif ne le consomme; origine fournisseur, fil client et rattachement restent manquants.
