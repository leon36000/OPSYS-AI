# M1 — Livraison interne de demandes du site

Date : 5 octobre 2026 UTC. Design adapté après l’[audit initial](M1-AUDIT-INITIAL-QUADRUPLE-A.md)
et l’inspection ciblée du formulaire, de `reception.py`, de `outils.py`, de `Capacites`
et des consommateurs M2. Ce document décrit la tranche à qualifier, pas un service publié.

## Besoin et réutilisation

Une demande de gouttières à Laval doit atteindre le registre M1 puis le CRM M2 avec sa
source marketing, sans nouvelle base CRM ni appel de modèle. L’extrait HTML actuel est
désactivé tant que son action est un marqueur. Il ne dispose pas d’un serveur de livraison.
Le moteur M1 possède déjà le canal `formulaire`, les contacts déclarés, le contrôle du rejeu,
la qualification et la publication transactionnelle `m1.lead_qualifie` vers M2.

La tranche réutilise FastAPI/Starlette, la bibliothèque standard HMAC-SHA256 et le
répartiteur `Capacites.appeler`. Elle adapte une frontière HTTP au contrat existant ; elle
n’ajoute ni framework d’agents, ni dépendance, ni connecteur de téléphonie. Aucun appel
direct au registre CRM ou à la fonction métier ne remplace le répartiteur.

## Frontière retenue

Le serveur du site transmet une enveloppe JSON signée au pont interne OPSYS. La clé dédiée
reste sur les deux serveurs. Elle ne figure jamais dans le navigateur, un exemple de clé
exploitable, une réponse ou un journal. Le site autorisé est fixé par la configuration
de l’instance ; la requête ne choisit ni entreprise, profil, acteur, département ni outil.

La signature couvre une version de protocole, le site, un timestamp, un nonce et les octets
exacts du corps. La comparaison est constante en temps ; l’écart autorisé est de 300 secondes.
Le timestamp signé reste l’horodatage canonique lors d’un rejeu. Le nonce et le site donnent
le même identifiant M1 pour les tentatives d’une demande. Un contenu contradictoire doit être
refusé par le registre canonique, sans second événement.

Authentifier le serveur émetteur ne vérifie pas l’identité du visiteur. Son courriel reste
déclaré. Aucune session humaine, identité d’appareil ou autorisation de publication n’est créée.
La route borne le flux, les champs et les en-têtes ; JSON ambigu, champs inconnus et UTM
invalides sont refusés. Les réponses sont génériques et sans cache, sans contenu client.

## Périmètre de données

Le premier protocole porte courriel, message et les quatre paramètres UTM déjà supportés.
Un nom ou téléphone secondaire non vide ne peut pas être supprimé silencieusement : tant
qu’un contrat canonique ne permet pas de le conserver comme donnée déclarée, le pont le
refuse. Ce protocole court ne branche donc pas le formulaire HTML complet.

Les messages suivent les règles existantes : qualification, demande de précisions ou
escalade humaine selon leur contenu. Recevoir une demande ne signifie pas envoyer une
réponse client, confirmer un rendez-vous ou publier une campagne.

## Configuration et exploitation

Le montage envisagé dans la fabrique de console reste désactivé par défaut. L’opérateur
fournit explicitement un site et une clé distincte de la clé des cookies. Sans configuration
ou M1 installé, la réception doit être indisponible et ne pas écrire de demande.

Un budget épuisé ou une panne n’est pas une donnée invalide : le serveur du site conserve
alors sa demande et doit gérer la reprise. Le pont n’ajoute pas de file d’attente parallèle.
Après expiration de l’enveloppe, la récupération exige un processus opérateur encore à
définir ; ne pas générer automatiquement un nouveau nonce pour masquer un échec.

L’ingestion passe par les politiques et budgets existants. Le consommateur M2 reste le
répartiteur du bus normal ; une réponse HTTP de réception ne promet pas une livraison
CRM synchrone. TLS, restriction réseau, limites de débit, rotation des clés, file durable
du serveur du site, front public et qualification VPS restent des travaux distincts.

## Preuves attendues

- Parcours HTTP signé vers `Capacites`, registre M1, événement et vrai consommateur M2 sur SQLite.
- Rejeu identique sans doublon ; contenu ou date contradictoires sans nouvel événement.
- Refus signature, site, date, champs, JSON, UTM, taille et en-têtes ambigus avant écriture métier.
- Configuration absente, M1 absent et budget épuisé : aucun lead inventé, erreur générique.
- Session console seule insuffisante ; clé de session non réutilisée comme clé du pont.
- Régressions des canaux, du formulaire HTML, des conversations et du raccord M1/M2.

M1 et OPSYS-AI restent **PARTIEL**. La qualification de cette tranche sera consignée
dans un rapport séparé avec ses sources, commandes, résultats et limites.
