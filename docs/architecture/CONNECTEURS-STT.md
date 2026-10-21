# Configuration durable de la transcription M1

La console privée `/connecteurs` permet à un owner/admin actif d'activer le connecteur STT M1
et de choisir les **noms** des variables serveur pour URL, modèle, clé, mode local et délai.
Les valeurs restent dans l'environnement du processus; la base et les réponses ne conservent
que les références. Cette tranche ne fournit pas de coffre de secrets ni de connexion aux autres
plateformes affichées dans l'inventaire.

## Configuration et effet sur M1

Les migrations de la base d'instance créent les tables du connecteur en révision `0016`.
Le formulaire exige CSRF; `PUT /api/connecteurs/stt-m1/configuration` accepte seulement :

```json
{
  "actif": true,
  "references": {"url": "OPSYS_M1_STT_URL", "modele": "OPSYS_M1_STT_MODELE"},
  "revision_attendue": 0,
  "mutation_id": "stt-configuration-0001"
}
```

`cle`, `local` et `delai_s` sont optionnels dans `references`. Les références sont des noms de
variables, pas des URLs, tokens ou modèles. Les variables serveur doivent être provisionnées
séparément. Le mode local vaut `1`; hors mode local, HTTPS et le consentement de transfert externe
restent requis par l'import vocal. Une URL/modèle absent ou une configuration invalide produit
un refus explicite; aucun modèle n'est deviné. Une clé distante absente ne devient pas une
connexion autorisée.

L'enregistrement est versionné et conserve son acteur et son historique. Une mutation rejouée
par le même acteur avec le même contenu rend la même réponse; une autre identité, une révision
périmée ou un contenu différent sont refusés. Les GET n'appellent aucun fournisseur.

`ConfigurationSTT.depuis_env()` consulte la ligne persistée avant de résoudre ses références.
Une ligne désactivée coupe ce chemin; une ligne incomplète ne retombe pas sur les variables
historiques. En l'absence de ligne, le comportement historique est conservé. L'appel avec un
mapping `environ` explicite reste indépendant de la configuration persistée, notamment pour
les tests et transports injectés. Aucun code ne modifie `os.environ`.

## Contrôle distant manuel

`POST /api/connecteurs/stt-m1/diagnostic` prend seulement `revision` et `mutation_id`, avec session
et CSRF. Le bouton équivalent lance un GET `/models`, limité à cinq secondes et sans audio.
Le résultat expose état normalisé, date et révision observée; il ne valide pas le modèle, une
transcription, le consentement ni les capacités d'écriture du fournisseur. Le corps distant est
ignoré et les redirections sont refusées. Le diagnostic d'un endpoint déclaré distant refuse
localhost et les adresses IP littérales non publiques; cela ne constitue pas une protection DNS
universelle ni une qualification du réseau de production.

Une réservation de quinze secondes et son jeton protègent la concurrence/reprise. Acteur et
révision sont liés à toute tentative, même expirée; une ancienne tentative ne peut pas terminer
ou supprimer celle qui l'a remplacée. La clôture revérifie identité, configuration, révision et
expiration dans la transaction. Une observation ancienne reste datée de sa propre révision.
Les formulaires sont bornés à 16 Kio, avec champs inconnus ou répétés refusés.

## Qualification et limites

La campagne indépendante `stt-console-integres-root-r1-2026-10-02` passe 151 tests : STT persistant,
inventaire, console, upload vocal, transport STT existant, stockage et migrations. Les 1 075 sources
sélectionnées sont identiques avant/après. Un test PostgreSQL est désélectionné; l'essai préalable
Docker a échoué pendant initdb faute d'espace et ne qualifie pas la concurrence PostgreSQL.
Les transports des tests sont injectés : aucun fournisseur réel ou appel audio réel n'a été testé.
Le rapport et les reçus seront conservés avec la livraison intégrée; cette preuve qualifie le
parcours local décrit, pas le département M1 complet.

Contrat détaillé : [lot STT](../programme/LOT-CONNECTEUR-STT-PERSISTANT.md).
Suite produit : [plan de reprise](../programme/REPRISE-PLAN-2026-10-02.md).
