# R24 — dictée locale par clip dans le Core Talk existant

Contrat implémenté et qualifié localement par ROOT le 2 octobre 2026 UTC : **481 cas ciblés**
dans cinq campagnes distinctes. Le [bilan R24](REPRISE-DICTEE-BILAN-R24.md) en donne les reçus,
la portée et les limites; le [mode d'emploi](../architecture/DICTEE-LOCALE-CORE.md) décrit la
configuration. Cette tranche prolonge les recherches R22/R23 et le lot 7 du
[plan de reprise](REPRISE-PLAN-2026-10-02.md).

## Résultat et réutilisation

Un utilisateur dicte dans le composeur existant du Core. La session Talk reste de type
transcription, transport gateway-relay et brain none. Le texte final reste éditable; seul
l'envoi normal du message le transmet ensuite à l'agent départemental et à son contexte métier.
Aucun second orchestrateur, SDK vocal externe, moteur d'inférence ou avatar n'est installé.

Le fournisseur optionnel voice-call-local-clip s'enregistre dans l'extension voice-call et
son manifeste. Il réutilise les contrats de transcription, conversion PCMU et multipart du
SDK. Le transport local configuré passe par l'entrée SDK interne déjà déclarée pour les
extensions intégrées; aucun import relatif dans les internes du Core n'est ajouté.
Les candidats Pipecat/LiveKit/NVIDIA restent des recherches distinctes; aucune précision
fr-CA ni disponibilité ASR n'est déduite d'un adaptateur de protocole.

## Activation et transport

Configuration serveur sous voice-call.streaming.providers.voice-call-local-clip; sélection
explicite voice-call.streaming.provider requise. Une URL présente seule ne rend pas le provider
configuré pour la sélection automatique. Aucun provider par défaut n'est remplacé.

La première tranche accepte HTTP vers une IP loopback littérale canonique 127.0.0.1 ou ::1,
avec port valide et chemin de base borné. DNS, autres IP privées, identifiants URL, query,
fragment et formes d'adresse ambiguës sont refusés. Le Gateway contacte uniquement l'origine
configurée, sans redirect ni retry. Aucun secret n'est demandé dans cette tranche.
Le loopback appartient à la machine ou au conteneur du Gateway; un service dans un autre
conteneur exige un contrat réseau ultérieur.

Le clip reste en mémoire : au plus 240 000 octets PCMU mono 8 kHz, soit trente secondes.
La limite est cumulative, pas seulement par trame; un dépassement refuse le clip entier.
La conversion produit un WAV PCM16LE mono 8 kHz de 480 044 octets maximum. Le POST multipart
vers audio/transcriptions contient le fichier WAV, modèle et langue configurée; fr décrit le
paramètre linguistique, pas une qualité d'accent. Aucun fichier temporaire ni trace audio.

Timeout de requête au plus quatre secondes, avant la fenêtre de drain Talk existante de cinq
secondes. La réponse JSON est limitée à 8 KiB. Lecture, erreur, redirect, timeout et annulation
libèrent le transport et le body. Les messages d'erreur sont des codes fixes, sans URL,
exception brute, contenu de réponse, modèle, transcript ou audio.

## Terminer et annuler

Le contrat existant close mélange finalisation et nettoyage. Le nouvel attribut RPC facultatif
discardAudio sur talk.session.close doit être un booléen strict et reste réservé à la session
de transcription possédée par la connexion appelante. L'attribut absent ou false conserve le
comportement des anciens clients. Une autre connexion ne peut ni annuler ni consulter la session.
Les autres transports refusent l'intention discard après contrôle du propriétaire.

Le contrat de session ajoute cancel optionnel. Stop normal ferme pour produire un résultat;
annulation, déconnexion, expiration ou erreur nettoient et annulent, y compris pendant le drain.
Un provider historique sans cancel garde son comportement antérieur sans double fermeture.
Le fournisseur local annule le contrôleur HTTP, vide son tampon et supprime tout callback tardif.

L'UI propage l'annulation même si la création distante ou des appends sont encore en attente.
Un clip annulé avant finalisation explicite ne doit provoquer aucun POST. Après démarrage du
POST, l'annulation peut interrompre la requête et refuser le résultat, sans garantir que les
octets déjà transmis n'ont jamais été reçus. Les cartes de sessions restent liées au propriétaire
pendant la fenêtre nécessaire à la clôture; aucun transcript ne traverse une session supprimée.

## Vérifications réalisées

- Configuration strictement fermée, activation explicite et découverte réelle du plugin.
- WAV et multipart reçus par un serveur HTTP loopback fictif; résultat seulement après Stop.
- Plafond cumulatif, clip vide, close idempotent, cancel avant et pendant POST, aucun callback tardif.
- Redirect, erreurs HTTP/JSON, texte vide, réponse trop grande et timeout bornés sans fuite.
- Validator du RPC, propriétaire différent, refus sur autre backend et compatibilité sans nouvel attribut.
- Relais : annulation, déconnexion et expiration pendant/en dehors du drain; fournisseur historique.
- UI : terminer garde le texte éditable; annuler pendant create/append ne finalise pas le clip.
- Campagnes ciblées ROOT sur sources gelées, lint, contrats/manifeste et préimages conservées.

La consolidation retient extension **67** (r5), Gateway **320**, protocole **2** et UI **63**
(r3), puis compatibilité WebSocket **29** (r4). Chaque campagne possède son reçu et son JUnit;
les essais auteur et reprises ne s'ajoutent pas. Les snapshots de chaque campagne restent
identiques avant/après. Quatre amendements limités à l'extension séparent r3/r4 de r5 et sont
requalifiés par cette dernière; les surfaces Gateway, protocole et UI sont inchangées.
Le scope final contient 35 209 fichiers Core sélectionnés et `liaison_cibles.py`, soit 35 210
empreintes; il ne constitue pas une exécution de tous les tests du dépôt.

La suite WebSocket r3 avait zéro cas malgré exit 0, car son shard l'excluait. Le contrôle ROOT
a refusé ce résultat; la reprise r4 utilise son shard natif `unit-fast-fake-timers` et passe
29 cas. Les artefacts r3 restent conservés. Oxlint et oxfmt finaux passent; oxlint garde un
avertissement `max-lines` de 704 lignes pour un plafond de 700 dans le composeur existant.
Les tests du composeur utilisent jsdom, sans micro ni navigateur réel.

Le moteur ASR réel, la latence d'inférence, l'enregistrement micro navigateur de bout en bout,
la précision fr-CA, la conversation orale bidirectionnelle, TTS et avatar 3D restent à qualifier.
Le panneau de configuration de tous les fournisseurs reste un critère du produit complet;
ce premier adaptateur utilise la configuration serveur du Core existante.
