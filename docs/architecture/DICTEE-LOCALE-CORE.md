# Dictée locale dans le composeur Core

Cette tranche réutilise Talk et le composeur du Core pour transcrire un clip après validation.
Elle prépare les [sessions départementales](../programme/REPRISE-PLAN-2026-10-02.md), dont
la reconnaissance fr-CA, la synthèse vocale et les avatars restent à qualifier.
Le texte reçu reste éditable : l'utilisateur utilise ensuite l'envoi habituel du message.

## Configuration serveur

Le plugin intégré `voice-call` doit être chargé, tandis que son runtime de téléphonie peut
rester désactivé. Exemple de fragment à intégrer à la configuration Core existante :

```json
{
  "plugins": {
    "entries": {
      "voice-call": {
        "enabled": true,
        "config": {
          "enabled": false,
          "streaming": {
            "enabled": false,
            "provider": "voice-call-local-clip",
            "providers": {
              "voice-call-local-clip": {
                "baseUrl": "http://127.0.0.1:9000/v1",
                "model": "whisper-local",
                "language": "fr",
                "timeoutMs": 4000
              }
            }
          }
        }
      }
    }
  }
}
```

Le nom du modèle et le port sont des exemples. L'opérateur doit déjà disposer d'un moteur
local compatible avec `POST /v1/audio/transcriptions`. Aucun modèle n'est téléchargé ou
installé par cet adaptateur. La clé `config.enabled` concerne la téléphonie; celle du plugin
concerne son chargement. `streaming.enabled` concerne le webhook téléphonique. Le chemin
Talk de transcription utilise la sélection explicite `streaming.provider` et ses paramètres.
Une entrée dans `providers` seule n'active pas ce fournisseur.

La session Talk utilise le mode `transcription`, le transport `gateway-relay` et `brain: none`.
Elle n'exige aucun identifiant Twilio. Ce fragment serveur est indépendant du registre STT M1
de la console : une configuration enregistrée dans ce registre ne configure pas Talk.
L'interface unifiée de configuration des fournisseurs reste un travail du plan de reprise.

## Contrat du moteur local

Le Gateway accepte uniquement une origine HTTP à adresse littérale `127.0.0.1` ou `[::1]`,
port explicite entre 1 et 65535, avec chemin simple borné. Il refuse les noms DNS, les autres
adresses, identifiants URL, query, fragment, traversées et redirections. Le loopback appartient
au namespace réseau du Gateway : dans un conteneur, il désigne ce conteneur.

Le POST multipart transmet `file=dictation.wav`, `model` et `language`. Le fichier est un WAV
PCM16LE mono à 8 kHz, issu des trames PCMU du relais. Le plafond cumulatif est 240000 octets
PCMU, soit trente secondes; le WAV atteint au plus 480044 octets. Un dépassement refuse le
clip entier. La réponse doit être un objet JSON de moins de 8 KiB avec un champ `text` non vide.
Le paramètre `fr` ne démontre aucune précision pour l'accent québécois.

La requête et la lecture de son corps sont limitées à quatre secondes au maximum. Il n'y a
aucun retry. Un moteur qui dépasse ce délai produit une erreur contrôlée; choisir un modèle
et un matériel adaptés demande une mesure d'inférence réelle. Le tampon audio reste en mémoire;
l'adaptateur ne crée aucun fichier audio ni journal de transcription brute.

## Valider et annuler

La connexion et l'enregistrement remplissent le tampon sans contacter le moteur. La validation
du clip déclenche un seul POST. Annuler avant cette validation vide le tampon sans POST.
Après démarrage du POST, l'annulation interrompt la requête et refuse son résultat; elle ne
peut retirer des octets déjà reçus par le moteur.

L'intention d'annulation utilise `talk.session.close` avec `discardAudio: true`. Elle reste
réservée au propriétaire de la session de transcription, y compris pendant son drain normal
de cinq secondes. L'UI conserve cette intention si la création de session ou une trame sont
encore en attente. Déconnexion, expiration et erreur nettoient aussi la session. Les anciens
clients qui omettent cet attribut conservent leur fermeture normale.

## Vérification et portée

Le [contrat du lot R24](../programme/LOT-DICTEE-LOCALE-CORE.md) décrit les sources, les essais
et les preuves de qualification. Les tests HTTP utilisent un serveur loopback fictif qui reçoit
réellement le multipart/WAV. Ils ne font tourner aucun moteur de reconnaissance.

Le microphone d'un navigateur réel, la précision fr-CA, la latence d'inférence, les appels M1,
la conversation bidirectionnelle, TTS, la synchronisation d'un avatar et le déploiement VPS
restent des critères distincts. En cas d'indisponibilité du moteur, la saisie texte habituelle
du département reste le parcours utilisable.
