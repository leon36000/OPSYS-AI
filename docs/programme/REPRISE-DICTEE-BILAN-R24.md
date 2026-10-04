# Bilan R24 — dictée locale et annulation explicite

Qualification ROOT du 2 octobre 2026 UTC, branche locale
`codex/restructuration-2026-09-30`, base `2e56c0d5605dfe575bde9244f38924d5390f2674`.
Le [contrat](LOT-DICTEE-LOCALE-CORE.md) et le
[guide de configuration](../architecture/DICTEE-LOCALE-CORE.md) décrivent le fonctionnement.

## Résultat

Le fournisseur intégré `voice-call-local-clip` réutilise les interfaces Talk, le SDK de
transcription, la conversion PCMU et l'envoi multipart existants. Il garde le clip en mémoire
jusqu'à sa validation, puis contacte un endpoint ASR loopback explicitement configuré.
Le texte final reste éditable avant l'envoi au département. Le plugin peut être chargé avec
la téléphonie et son streaming désactivés; ce scénario est maintenant testé sans Twilio.

L'annulation traverse le composeur, le RPC strict `discardAudio`, le contrôle du propriétaire,
le drain du Gateway et `cancel()` du fournisseur. Elle reste effective pendant une création
ou un envoi audio en attente, ainsi que pendant la clôture normale. L'expiration, la
déconnexion et les erreurs nettoient aussi la session. La fermeture historique reste compatible.

Un clip annulé avant validation ne produit aucun POST. Une annulation après démarrage peut
interrompre la requête et supprimer le résultat tardif, sans retirer des octets déjà reçus.
Le clip est limité à trente secondes, la réponse JSON à 8 KiB et la requête à quatre secondes.
Les URL ambiguës, traversées, DNS, réseaux non loopback et redirections sont refusés.
Les logs inspectés projettent les métadonnées autorisées, sans audio ni transcript brut.

## Preuves indépendantes

Les [archives R24](../research/R24-2026-10-02/README.md) conservent les reçus originaux,
préimages, sources du lot, JUnit, journaux, revues et amendements. La sélection ROOT totalise
**481 cas sans échec, erreur ni skip**, dans cinq campagnes disjointes :

| Campagne | Reçu ROOT | Cas | Fichiers de tests |
|---|---|---:|---:|
| Extension/fournisseur | r5, 05:43:25–05:43:43 UTC | 67 | 3 |
| Gateway, propriété et permissions | r3, 05:35:04–05:36:12 UTC | 320 | 4 |
| Compatibilité WebSocket | r4, 05:38:11–05:38:24 UTC | 29 | 1 |
| Schéma RPC | r3 | 2 | 1 |
| Composeur et conversation | r3 | 63 | 2 |

Les horaires sont ceux des reçus englobants; les commandes ont leurs propres horaires.
Les comptes auteur ou historiques ne s'ajoutent pas à 481. Ce tableau consolide des campagnes
distinctes, sans les présenter comme un seul run. Les surfaces Gateway/protocole/UI demeurent
inchangées; quatre amendements de l'extension entre r3/r4 et r5 sont explicitement recensés et
requalifiés par r5. Les snapshots de chacun des runs sont stables avant/après.

Le contrôle final couvre **35 210 empreintes sélectionnées**, soit 35 209 fichiers Core
hors dépendances/dist/caches/symlinks, plus `src/opsys/liaison_cibles.py`. Les empreintes Python
R25 restent historiques et ne constituent pas une nouvelle campagne Python R24.
Oxlint sur 17 fichiers et oxfmt sur ces fichiers plus le manifeste passent. Oxlint conserve
un avertissement de longueur du composeur, 704 lignes contre un plafond de 700, sans erreur.
Le diff du dépôt est également contrôlé avant archivage.

La suite WebSocket r3 avait zéro cas : son shard `unit-src` excluait ce fichier déjà classé
`unit-fast-fake-timers`. Le contrôle ROOT a rejeté la qualification malgré exit 0. La reprise
r4 passe les 29 cas dans le shard natif; les preuves vides et leur refus restent archivés.
La revue suivante a fait corriger une fixture HTTP qui référençait un paramètre mal nommé,
clarifier l'état de connexion après erreur terminale et ajouter le scénario sans téléphonie.

## Limites et suite

Les essais HTTP utilisent un serveur loopback réel avec réponse fictive; aucun moteur ASR
n'a été exécuté. Les tests UI utilisent jsdom. Ils ne qualifient ni microphone navigateur,
inférence et accent fr-CA, latence terrain, téléphonie M1, TTS, conversation bidirectionnelle,
avatar 3D ou déploiement VPS. Un Gateway conteneurisé exige un moteur accessible dans son
namespace loopback; aucune autorisation DNS/LAN n'est ajoutée par ce lot.

La configuration reste serveur. Le registre STT M1 de la console n'active pas ce fournisseur
Talk. Le panneau commun des agents/connecteurs et les parcours audio/3D départementaux gardent
leurs critères complets dans le [plan de reprise](REPRISE-PLAN-2026-10-02.md).
La mémoire documentaire avance ensuite depuis le store PostgreSQL qualifié en
[R25](LOT-QUALIFICATION-MEMOIRE-PG.md). Aucun département complet ni OPSYS à 100 % n'est annoncé;
aucun commit, push, fusion ou déploiement n'a été effectué.
