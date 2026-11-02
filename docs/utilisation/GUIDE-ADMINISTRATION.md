# Guide d'administration

Pour la personne qui installe et entretient OPSYS-AI. Chaque section dit d'abord **ce qui a été qualifié** (rejoué, avec preuves, dans les
conteneurs fictifs du banc `install/qualification/`) et marque **« non qualifié »** tout le reste : ces étapes sont documentées d'après
le code et les scripts, jamais rejouées sur un vrai serveur. Lisez d'abord les [limites connues](LIMITES-CONNUES.md).

La commande du moteur métier s'appelle `opsys-metier` (dans le conteneur ou le venv). Depuis le Core, `opsys metier <commande>` la lance.
La commande `opsys` seule est celle du Core : une ancienne invocation (`opsys personnes creer …`) répond par la nouvelle syntaxe et sort en erreur.

## 1. Installation en conteneur

| Étape | Statut |
|---|---|
| Image du moteur Python construite depuis le dépôt, utilisateur non root (uid 1000), `pip check` propre | **Qualifié** (banc, sans réseau, dépendances copiées d'un venv aux versions du verrou) |
| Premier démarrage « en attente de configuration » (code 3), puis après initialisation : prêt (code 0) | **Qualifié** (banc) |
| `docker compose` complet (`deploy/docker-compose.yml`), Caddy/TLS, DNS, Let's Encrypt | **Non qualifié** |
| Construction du Core (`opsys-core:local`) | **Non qualifié** |
| `install/install.sh` (installateur natif) | **Non qualifié** : il n'a jamais terminé au banc |
| `pip install --require-hashes` du verrou | **Non qualifié** (réseau requis) |

Procédure d'un VPS neuf (documentée, non rejouée) : [INSTALLATION-VPS](../ops/INSTALLATION-VPS.md). En résumé : Ubuntu 22.04/24.04 ou
Debian 12/13, 4 vCPU, 8 à 16 Go ; deux enregistrements DNS (le Control UI et `console.<domaine>`) ; `deploy/.env` rempli (domaine, courriel
ACME, au moins une clé de fournisseur de modèle, point d'accès d'embeddings) ; puis `sudo bash deploy/install.sh`. Le code de sortie `3`
veut dire « configuration opérateur manquante » (paliers, embeddings ou secrets) ; `0` valide des contrôles locaux et **ne certifie ni un
tour d'agent, ni la sandbox**. Installation sans Docker sur un poste : [INSTALLATION](../exploitation/INSTALLATION.md).

**Mémoire** (mesurée au banc, charge fictive triviale, moteur Python seul) : viable à 448 Mo, tué à 416 Mo. Prévoyez **au moins 1 Go** pour
le conteneur `opsys` (le Compose en donne 512 Mo) ; les processus longue durée prennent environ 280 Mo, chaque appel de commande 30 à 70 Mo. Le
besoin mémoire de la construction du Core n'est pas mesuré.

### Première personne et connexion

```bash
docker compose -f deploy/docker-compose.yml exec opsys \
  opsys-metier personnes creer nathan --nom "Nathan" --role nathan_owner     # mot de passe demandé sans écho
```

Rôles : `nathan_owner`, `admin`, `finance`, `manager`, `seller`, `employee`, `client`, `system_agent`. Pas de mot de passe partagé :
une personne, un compte. Connexion à `https://console.<domaine>` ; le Control UI demande `OPENCLAW_GATEWAY_TOKEN`. Appairage d'un
téléphone : `opsys-metier appareils appairer --personne <id> --role admin|employee|seller --config-dir <dossier>` (le rôle `client` n'a pas
d'appareil : il passe par un lien à jeton expirant). Qualifié au banc : connexion avec cookie `HttpOnly` / `Secure` / `SameSite`, sondes MCP et
console, en-têtes de sécurité, refus sans jeton.

## 2. Sauvegarde chiffrée et restauration

**Qualifié** (conteneurs fictifs) : sauvegarde chiffrée de l'instance SQLite, destruction, restauration sur un conteneur neuf, comparaison de
86 tables et 109 lignes identiques, refus typés sur 28 défauts injectés (mauvaise clé, base corrompue, disque plein, archive tronquée ou altérée,
version plus récente, clé rangée dans le dossier des sauvegardes).

```bash
python -m opsys.sauvegarde_chiffree generer-cle /chemin/hors/instance/sauvegarde.cle     # une fois ; fichier 0600 ; affiche le cle_id (non secret)
python -m opsys.sauvegarde_chiffree sauvegarder --dossier /chemin/sauvegardes --par <personne>
python -m opsys.sauvegarde_chiffree verifier /chemin/sauvegardes/<archive>
python -m opsys.sauvegarde_chiffree restaurer /chemin/sauvegardes/<archive> --par <personne>   # --remplacer pour écraser une instance non vide
python -m opsys.sauvegarde_chiffree retention --dossier /chemin/sauvegardes --garder 7 --jours 30            # plan seulement
python -m opsys.sauvegarde_chiffree retention --dossier /chemin/sauvegardes --garder 7 --jours 30 --appliquer  # met de côté, ne supprime jamais
```

Règles à retenir :

- **La clé de sauvegarde vit hors de la sauvegarde et hors de l'instance** (le logiciel refuse de la ranger dans le dossier des sauvegardes) et
  elle est distincte de la clé maîtresse du coffre. Sans elle, la sauvegarde est illisible : gardez-la en deux endroits hors serveur.
- La rétention **met de côté** (`a-detruire/`) ; la destruction définitive est une décision humaine.
- Chaque refus a un code `REJ-SAUVEGARDE-…` et un code de sortie (10 clé absente, 14 mauvaise clé, 15 altérée, 16 tronquée, 19 disque plein, 25
  version du logiciel plus récente…).
- L'export brut (`opsys-metier instance exporter --sortie <archive>`) n'est **pas chiffré** : préférez le module chiffré ci-dessus.

**Non qualifié** : `deploy/backup.sh` et `deploy/restore.sh` (volumes Compose, PostgreSQL), la copie hors site ([plan](../qualification/PLAN-COPIE-HORS-SITE.md),
jamais exécuté), la rotation des clés, une restauration réelle d'une instance de production. Faites un essai de restauration sur une
préproduction avant de compter dessus.

## 3. Mise à jour

**Qualifié** (au banc) : passage de la révision 0038 à 0040 par `opsys-metier base migrer` (0,96 s, 76 tables d'origine identiques), retour
arrière jusqu'à 0038 sur une copie, refus du logiciel précédent sur une base plus récente, migration interrompue à six moments (retour atomique ou
terminée, jamais à demi). La tête actuelle des migrations est **0052** ; les migrations 0041 à 0052 ne sont pas passées par ce banc.

```bash
opsys-metier base etat        # révision courante
opsys-metier base migrer      # monte à la tête ; sauvegardez d'abord
opsys-metier verifier         # manifestes, outils, droits d'appareil, avatars, packs
```

Mise à jour du code sur un VPS (non qualifiée) : sauvegarder, `git pull`, reconstruire (`docker compose build opsys openclaw-gateway`),
`docker compose up -d`, puis `docker compose ps`, `curl -fsS https://<domaine>/startupz` et `docker compose logs opsys --tail=50`. Les images
tierces sont épinglées par empreinte (digest) : une mise à jour est un changement relu du Compose, jamais une étiquette qui bouge.
**Toujours essayer sur une préproduction.** Le retour arrière d'une instance avec de vrais courriels n'est pas éprouvé (la migration 0040 refuse la
descente dès qu'une table de courriel contient une ligne).

## 4. Clés et coffre de secrets

Le coffre chiffre les clés d'API et les mots de passe au repos (AES-256-GCM, enveloppe de clés). Les agents ne reçoivent jamais une valeur :
ils reçoivent un **jeton opaque** lié à un porteur, à un usage et à une expiration. Une valeur n'est lisible que côté serveur, à l'instant de
l'appel, et masquée dans les journaux. L'export d'une valeur est toujours refusé.

```bash
opsys-metier coffre generer-cle-maitresse --fichier /chemin/hors/depot/coffre.cle      # une fois, 0600, hors Git
export OPSYS_COFFRE_CLE_FICHIER=/chemin/hors/depot/coffre.cle                          # (ou OPSYS_COFFRE_CLE, jamais les deux)
opsys-metier coffre definir <nom> --service <google|meta|quickbooks|microsoft|fournisseur_modele|…> --par <personne>   # la valeur est saisie sans écho
opsys-metier coffre lister
opsys-metier coffre jeton <nom> --porteur <qui> --usage fournisseur:<id> --duree-s 3600 --par <personne>
opsys-metier coffre rotation <nom> --par <personne>                  # nouvelle version, l'ancienne est détruite
opsys-metier coffre revoquer <nom> --confirmer --par <personne>      # immédiat et définitif
opsys-metier coffre rechiffrer --nouvelle-cle-fichier <chemin> --par <personne>   # rotation de la clé maîtresse
opsys-metier coffre journal
```

État : le coffre est livré et testé avec des données fictives. **Non qualifié** : rotation de la clé maîtresse en exploitation, garde de la clé hors
serveur, secrets réels. Les clés de `deploy/.env` (`chmod 600`) et du coffre sont deux mécanismes distincts : les clés de fournisseurs de modèles
du mode natif viennent des variables d'environnement nommées dans les paliers.

## 5. Fournisseurs de modèles et d'outils

Le **registre de fournisseurs** liste, pour chaque capacité (modèle de langage, embeddings, reranker, OCR, voix, avatar, image, vidéo,
recherche web, courriel, vision), les candidats avec leur **licence du code et des poids**, leurs seuils de revenu, territoires et droit de
service à des tiers. Un moteur de politique refuse l'activation d'un fournisseur non conforme à votre profil. Le catalogue compte 66 lignes ;
30 sont « non vérifiées à la source » ([registre des licences](../compliance/REGISTRE-FOURNISSEURS-LICENCES.md)).

```bash
opsys-metier fournisseurs profil --usage-commercial oui --revenu-usd <montant|inconnu> --territoire CA --heberge-pour-tiers non --par <personne>
opsys-metier fournisseurs lister
opsys-metier fournisseurs configurer <identifiant> --point-acces <url> --secret coffre:<nom> --par <personne> [--licence-lue] [--efvp-ref …] [--contrat-ref …]
opsys-metier fournisseurs activer <identifiant> --par <personne>     # refusé avec les codes de politique si non conforme
opsys-metier fournisseurs selectionner <capacité> <identifiant> [--departement M7] --par <personne>
opsys-metier fournisseurs tester <identifiant> --par <personne>
```

Règles : `--licence-lue` ne se dit qu'après avoir **lu le texte intégral** de la licence ; une API hors Québec exige une référence d'ÉFVP (Loi 25) ;
aucun repli silencieux (un fournisseur inactif ou devenu non conforme est un refus, pas un autre fournisseur). L'interface est dans la console,
page **Plateforme → Fournisseurs**. `qualifie` veut seulement dire qu'un test de connexion réel a répondu : ce n'est ni une qualité de
résultat, ni un accent québécois, ni une latence. **Aucun fournisseur du catalogue n'est « qualifié » par une mesure locale** (tous
`a_mesurer`).

## 6. Packs sectoriels

```bash
opsys-metier pack lister
opsys-metier pack valider <id>
opsys-metier pack afficher <id>
opsys-metier pack empreinte <id>
opsys-metier pack choisir <id> --par <personne>     # écrit la clé « pack » du profil d'entreprise
```

Deux packs sont livrés : `generique-pme` (défaut) et `renovation-exterieure-qc`. Un pack inconnu ou altéré est **refusé** (jamais de repli silencieux).
Une instance du premier client doit écrire explicitement `pack: renovation-exterieure-qc`. Seuls les blocs de prompt, le vocabulaire et les
services d'un pack sont lus par le système ; les gabarits et barèmes sont documentaires. Un seul secteur réel existe : le schéma n'a pas encore
été éprouvé par un second métier.

## 7. Planificateur des connecteurs (courriel, WordPress, réseaux sociaux)

Le planificateur est un tour dans le processus du serveur MCP, sous l'acteur système `opsys-systeme`. Chaque exécuteur est **`inactif` par
défaut**, puis `ombre` (il simule), puis `actif`. L'activation se fait **seulement par un administrateur, dans la console** (page
**Plateforme → Connecteurs**), avec un motif, et **expire au bout de 90 jours** : renouvelez-la.

| Exécuteur | Ce qu'il fait actif |
|---|---|
| `courriel.synchro` | Lit les nouveaux courriels des comptes connectés, ne transmet jamais l'historique d'amorçage à M1 |
| `courriel.envoi` | Envoie une seule fois chaque brouillon **approuvé** par une personne (72 h) |
| `m7.wordpress.brouillons` / `m7.wordpress.publication` | Transmet les brouillons ; publie les articles approuvés (une heure) |
| `m7.social.publication` | Publie à l'heure approuvée |

À configurer côté serveur : `OPSYS_COURRIEL_REDIRECT_URI`, `OPSYS_COURRIEL_GMAIL_CLIENT_ID` (+ `…_SECRET`), `OPSYS_COURRIEL_GRAPH_CLIENT_ID` / `_TENANT`
(+ `…_SECRET`) et le secret du coffre `courriel.state-cle` (32 octets au moins). **Statut : prouvé sur doubles seulement.** Aucun compte
réel, aucun transport WordPress ni adaptateur de réseau réel : en production, les ports sont « non raccordés » et les exécuteurs M7 refusent
(`REJ-PLAN-WORDPRESS-NON-RACCORDE`, `REJ-PLAN-SOCIAL-NON-RACCORDE`). Même activé, l'acteur système n'exécute jamais un geste N3 sans une approbation humaine consommée.
Déclarez aussi les serveurs de réception de confiance par compte, sinon toute facture reçue reste « à vérifier » (comportement sûr).

## 8. Registre MCP des outils

Le registre scellé (`src/opsys/registre_mcp/registre.v1.json`) liste chaque outil exposé avec une empreinte de son nom, de sa description et de son
schéma, et son niveau d'approbation. À la révision actuelle, **638 outils** y sont scellés (les 615 outils de départements, plus les outils communs, de
contexte et d'hôte).

```bash
opsys-metier registre-mcp verifier           # compare le catalogue réel au registre
opsys-metier registre-mcp lister
opsys-metier registre-mcp sceller --par <personne> --a-blanc    # montre le diff
opsys-metier registre-mcp sceller --par <personne>              # écrit une nouvelle révision (relire le diff d'abord)
opsys-metier registre-mcp rule-of-two
```

Tout outil ajouté ou modifié fait échouer `tests/test_registre_mcp.py` jusqu'à un nouveau scellement relu. **Attention : la garde est inerte tant que
`OPSYS_MCP_REGISTRE=defaut` n'est pas posé dans l'environnement du serveur MCP** ; ni les installateurs ni le Compose ne le posent aujourd'hui.
`OPSYS_MCP_REGISTRE_STRICT=1` fait échouer le démarrage sur un outil dérivé ; `OPSYS_TRACES=1` active le journal de traces. Ce mécanisme n'a jamais
été éprouvé contre le Core réel.

## 9. Départements, modes et approbations

```bash
opsys-metier departements                         # code, mode, nombre d'outils, compétences
opsys-metier mode m05-financecore supervise --par <personne>
opsys-metier approbations lister                  # la file ; « file » pour la file du propriétaire
opsys-metier approbations approuver <id> --par <personne>
```

Le mode `ombre` est le défaut (N3 et plus approuvés) ; ne passez pas un département en `autonome` avant d'avoir tranché l'écart noté dans les
[limites connues](LIMITES-CONNUES.md). Un compte de service (`system_agent`) ne peut pas décider d'une approbation.

## 10. Dépannage

| Symptôme | Cause probable et geste |
|---|---|
| Installation ou démarrage se termine par le code **3** | Il manque une configuration opérateur (paliers, embeddings, clé d'un fournisseur). C'est « en attente de configuration », pas une panne. Lisez le bilan, complétez, recréez `opsys`. |
| Le service s'arrête avec un message sur `OPSYS_CONSOLE_SECRET` ou `OPSYS_MCP_JETON` | Secret manquant : le service refuse de démarrer sans (sûr). Régénérez `deploy/.env` (`deploy/install.sh` ne remplace jamais un secret déjà posé). |
| `docker stop` donnait un code 1 | Corrigé : un arrêt demandé sort maintenant en 0 (« arrêt demandé »). |
| Conteneur tué (`OOMKilled`) | Mémoire sous le plancher mesuré ; donnez au moins 1 Go à `opsys`. |
| `/healthz` répond 200 mais rien ne marche | Ces deux adresses sont des réponses statiques de Caddy. Vérifiez `/startupz`, `…/connexion` de la console, `docker compose logs opsys`. |
| Un tour d'agent échoue avant le modèle | La sandbox Docker est obligatoire et le Compose de base ne raccorde pas le daemon : voir [EXPLOITATION](../ops/EXPLOITATION.md) ; ne désactivez pas la garde. |
| Refus `REJ-SAUVEGARDE-…` | Le code dit la cause : voir la liste du §2. L'instance existante n'est jamais modifiée par un refus. |
| Refus d'activer un fournisseur (`LICENCE_A_VERIFIER`, `SEUIL_REVENU_DEPASSE`, `TERRITOIRE_EXCLU`…) | La politique de licence fonctionne : lisez la licence, mettez à jour le profil de licence ou choisissez un autre fournisseur. |
| `REJ-MCP-EMPREINTE-DERIVE` | La définition d'un outil a changé sans nouveau scellement : relire le diff puis `registre-mcp sceller`. |
| La console bloque votre adresse | `fail2ban` (5 échecs en 10 minutes : 1 heure) ; `sudo fail2ban-client set opsys-console unbanip <ip>`. |
| Mot de passe oublié | `opsys-metier personnes mot-de-passe <identifiant>` (par une personne autorisée). |
| Une exigence de la politique de licences fait échouer les tests | Voir [INVENTAIRE-LICENCES](../compliance/INVENTAIRE-LICENCES.md) : régénérer le SBOM ou relever la licence manquante. |

Journaux : `docker compose logs -f opsys`, `journalctl -t opsys -f`. Aucun secret ni renseignement personnel n'est censé y figurer ; le banc a
vérifié l'absence de valeurs de jeton, de clés et de mots de passe dans les journaux et les volumes de l'essai.

## 11. Hébergement et Loi 25

Privilégiez un hébergeur au Canada. Une communication de renseignements personnels hors Québec exige une ÉFVP (gabarit :
[`docs/compliance/efvp/GABARIT-EFVP.md`](../compliance/efvp/GABARIT-EFVP.md)). Les politiques de consentement (SMS, appels, photos, GPS) sont des
**propositions non validées** : faites-les lire par une avocate ou un avocat avant toute collecte réelle.
