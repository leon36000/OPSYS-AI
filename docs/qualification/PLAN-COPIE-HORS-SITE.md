# Plan de copie hors site des sauvegardes — NON EXÉCUTÉ

> **Statut : plan seulement.** Aucun fournisseur n'est choisi, aucun compte n'est créé, aucune copie n'a été faite,
> aucun secret n'a été manipulé. La qualification en conteneur ([QUALIFICATION-CONTENEUR.md](QUALIFICATION-CONTENEUR.md))
> ne prouve que la sauvegarde **locale** chiffrée et sa restauration. Le choix du fournisseur, l'ouverture du compte, les
> identifiants et le paiement sont des décisions humaines (frontière T3) : Nathan décide. Tout avis juridique ou fiscal
> ci-dessous est **à valider auprès d'un professionnel qualifié** (juriste pour la Loi 25, comptable/CPA pour les coûts).

## 1. Ce qu'on copie, et ce qu'on ne copie jamais ensemble

| Élément | Où il vit sur le serveur | Hors site |
|---|---|---|
| Archive chiffrée `opsys-sauvegarde-<horodatage>-<id>.tar.gz.enc` (AES-256-GCM) | `/sauvegardes` | **Oui** (déjà chiffrée avant de partir) |
| Son descriptif `.meta.json` (révision, empreinte du clair, `cle_id`) | `/sauvegardes` | Oui (non sensible : aucun secret, aucune donnée) |
| Clé de sauvegarde (`OPSYS_SAUVEGARDE_CLE_FICHIER`) | dossier privé 0700 hors de l'instance et hors des sauvegardes | **Jamais avec les archives, jamais chez le même fournisseur.** Copie séparée, voir §3 |
| Clé maîtresse du coffre de secrets (`OPSYS_COFFRE_CLE_FICHIER`) | idem, distincte | Séparément, voir §3 : sans elle, les secrets du coffre restaurés restent illisibles |
| Secrets d'environnement (`deploy/.env`) | hôte | **Non** : à reprovisionner depuis le gestionnaire de secrets de Nathan |

Une archive hors site sans sa clé est illisible ; une clé sans archive ne sert à rien. Les séparer est le but.

## 2. Choix du fournisseur (décision de Nathan)

Critères à comparer — chaque ligne est à **vérifier auprès du fournisseur au moment du choix** (aucune affirmation de cette
liste n'est vérifiée ici) :

- **Localisation des données** : Loi 25 (Québec) : héberger au Canada, idéalement au Québec, évite une évaluation des
  facteurs relatifs à la vie privée (ÉFVP) pour la communication hors Québec ; hors Canada, l'ÉFVP est requise et se
  documente. *À valider auprès d'un professionnel qualifié (juriste).*
- **Protocole** : stockage objet compatible S3 (outils `rclone` ou `restic`, déjà prévu par `RESTIC_REPOSITORY` dans
  `deploy/backup.sh`) ou SFTP vers un second serveur.
- **Immuabilité** : verrouillage d'objet / versionnage / suppression différée, pour qu'un compte compromis ne puisse pas
  effacer les copies.
- **Accès à droits séparés** : un identifiant qui peut seulement **écrire** (celui du serveur), un autre qui peut **lire**
  (celui de la restauration, hors serveur).
- **Coût** : stockage + sorties de données (frais de téléchargement lors d'une restauration) — *chiffrer l'estimation et la
  faire valider par le comptable*.
- **Durée de rétention minimale** (frais de suppression anticipée) compatible avec la politique §4.

Candidats à évaluer (liste non exhaustive, aucun n'est recommandé ici) : un stockage objet d'un hébergeur canadien
(par exemple celui de l'hébergeur du VPS, s'il offre une région canadienne), un second VPS au Canada via SFTP, un fournisseur
de stockage objet généraliste avec région canadienne.

## 3. Garde de la clé (humain, hors serveur)

1. Générer la clé sur le serveur : `python -m opsys.sauvegarde_chiffree generer-cle /chemin/prive/sauvegarde.cle`
   (0600, jamais d'écrasement). Noter le `cle_id` affiché (non secret) : il identifie la clé dans l'en-tête de chaque archive.
2. Une personne autorisée (Nathan) copie la clé **à la main** sur deux supports distincts, dans deux lieux distincts
   (par exemple gestionnaire de mots de passe de l'entreprise + clé USB chiffrée au coffre). Jamais par courriel, jamais dans
   Git, jamais dans le dossier des sauvegardes (le logiciel refuse : `REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE`).
3. Rotation : générer une nouvelle clé, sauvegarder avec elle ; **conserver** l'ancienne tant qu'une archive qui l'utilise
   existe (le `cle_id` dit laquelle sert pour quelle archive). Détruire une ancienne clé est une décision humaine.

## 4. Politique proposée (à confirmer)

- **Cadence** : une sauvegarde chiffrée par jour (cron), copie hors site dans l'heure.
- **Rétention locale** : 7 dernières **et** toute sauvegarde de moins de 30 jours (`retention --garder 7 --jours 30`) ; ce qui
  sort de la politique est **mis de côté** dans `a-detruire/`, jamais supprimé par le logiciel (destruction = humain).
- **Rétention hors site** : 30 jours quotidiens + 12 mensuels (à ajuster au coût), avec verrouillage d'objet.
- **Effacement (Loi 25)** : un effacement dans l'instance ne touche pas les archives existantes. Tenir le registre des
  archives et prévoir leur expiration ; une demande d'effacement se traite aussi sur les copies hors site à leur échéance.
- **RPO** visé : 24 h. **RTO** visé : à mesurer (voir §6), le banc donne le temps de restauration d'une instance fictive.

## 5. Mise en œuvre — commandes d'illustration (NON exécutées, à adapter au fournisseur choisi)

```bash
# Sur le serveur, après la sauvegarde chiffrée (jeton d'ÉCRITURE seulement, jamais de suppression) :
rclone copyto /sauvegardes/opsys-sauvegarde-<horodatage>-<id>.tar.gz.enc  <remote>:<seau>/opsys/  --immutable
rclone copyto /sauvegardes/opsys-sauvegarde-<horodatage>-<id>.tar.gz.enc.meta.json <remote>:<seau>/opsys/
# Contrôle d'intégrité côté distant, sans la clé :
rclone check /sauvegardes <remote>:<seau>/opsys/ --one-way --include "opsys-sauvegarde-*"
```

La copie ne contient que des fichiers déjà chiffrés ; une compromission du compte de stockage ne révèle aucune donnée tant
que la clé reste séparée (§3).

## 6. Preuves à produire avant de déclarer la copie hors site « en place » (rien de ceci n'est fait)

1. Une copie réelle vers le fournisseur choisi, avec identifiants à droits séparés (écriture seule / lecture seule).
2. Une **restauration depuis le hors site** sur un conteneur ou serveur neuf, avec la clé récupérée depuis son support
   hors serveur : `python -m opsys.sauvegarde_chiffree restaurer <archive>` suivi de la comparaison d'empreintes du banc.
3. Un test de refus : archive hors site modifiée d'un bit → `REJ-SAUVEGARDE-ALTEREE` ; mauvaise clé →
   `REJ-SAUVEGARDE-MAUVAISE-CLE`.
4. Une alerte si la dernière copie hors site a plus de 26 h (supervision à définir).
5. Une mesure du temps de téléchargement et du coût réel d'une restauration complète.
6. La validation juridique de l'hébergement (Loi 25) et comptable des coûts.

Tant que ces six points ne sont pas démontrés, la formule exacte est : **« sauvegarde locale chiffrée prouvée en
conteneur ; copie hors site non prouvée »**.
