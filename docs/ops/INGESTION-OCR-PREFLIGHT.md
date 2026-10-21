# Prévol OCR manuel pour l’opérateur

**QUALIFIÉ LOCAL — r212**, 4 octobre 2026 UTC. Image serveur et VPS :
**NON QUALIFIÉS**. M5 et OPSYS-AI restent **PARTIEL**.

Ce diagnostic vérifie si le bundle administré et le confinement disponibles
peuvent reconnaître une page fictive fixe. Il précède l’activation opérationnelle
de la [revue privée](../grs/compta/M5-OCR-CONSOLE-2026-10-04.md).
Il ne modifie pas les données d’une entreprise et ne provisionne aucun composant.

## Invocation

Depuis le dépôt avec l’environnement Python installé :

```sh
OPSYS_INGESTION_OCR_BUNDLE=/chemin/absolu/bundle-administré \
  python deploy/readiness_ocr.py --ocr-only
```

Le chemin est un choix de l’opérateur du serveur, sans valeur fournie par HTTP.
Le bundle doit déjà être provisionné selon le [profil qualifié](../grs/compta/M5-OCR-WORKER-2026-10-04.md).
La présence de la commande dans une image ne prouve pas que ses dépendances
ou ses namespaces sont disponibles. Appeler le diagnostic dans l’environnement
et sous l’utilisateur qui exécuteront réellement le service.

| Code | Sens |
|---|---|
| 0 | La fixture et le profil ont passé la sonde OCR confinée locale. |
| 1 | Configuration, fixture, profil, résultat ou confinement indisponible. |
| 2 | Invocation invalide ; seul `--ocr-only` est accepté. |
| 3 | OCR non activé : variable absente ou vide ; aucun worker appelé. |

Les sorties sont fermées et génériques : aucun chemin opérateur, détail
exception, clé ou texte reconnu. Les refus ne déclenchent ni téléchargement,
installation, parseur hôte, fournisseur IA ni assouplissement du confinement.
Ce diagnostic reste manuel ; le healthcheck standard et la sonde PDF native
restent distincts.

## Ce qui est vérifié

`deploy/readiness_ocr.py` réutilise `chemin_bundle` et
`ocr_runtime.extraire_candidat`. La fixture `deploy/fixtures/ocr-image-fictive.pdf`
est une création ROOT entièrement fictive, copiée byte pour byte depuis le
parcours r190 : 12 194 octets, SHA256
`a8487a4255aac8d40d5f88d635045a14a4f80a1b535757a53f610fdca3348d22`.
Elle contient seulement une page bitmap avec trois mots de test. Sa taille,
son type régulier et son empreinte sont contrôlés avant l’appel au worker.
L’ouverture sans suivi de symlink et non bloquante refuse aussi un tube nommé.

Le worker existant fournit le candidat validé par son contrat. La sonde compare
en mémoire l’identité fictive, la révision, le SHA source, le profil/configuration,
les dimensions et les trois mots attendus, sans les afficher. Elle n’importe
pas pypdf/PDFium dans le diagnostic et ne produit aucune interprétation financière.
Les fichiers temporaires techniques du runtime restent ceux de son confinement
existant ; aucune base métier ni clé d’ingestion n’est requise par cette sonde.

## Preuves et limites

r212 : **117/117**, cinq fichiers complets, aucun échec/erreur/skip ; Ruff et
vérificateur métier réussis, 1 319 sources/ressources surveillées inchangées,
11,517 secondes. Dix-huit tests de prévol, quinze de configuration console,
trente-deux de déploiement/readiness existants, vingt-neuf de profil OCR et
vingt-trois de runtime sont compris dans 117. Les anciens totaux se recouvrent.
Le périmètre surveillé inclut aussi les scripts/configurations de déploiement
lus par ces tests, sans être un audit exhaustif du dépôt.

ROOT exécute la vraie CLI sur le bundle local épinglé, sans double du runtime :
états absent3, profil absent1, arguments invalides2, succès0. La reconnaissance
emprunte effectivement bubblewrap/PDFium/Tesseract. Le répertoire métier et
la base fictive interdits par le harness ne sont pas créés ; les sorties ne
contiennent ni mots reconnus ni chemins. Le test ne déploie aucun serveur.

Historique : r209 **13P/1F** reproduit le blocage d’ouverture d’une fixture
FIFO avant la correction non bloquante. r210 est arrêté par deux règles Ruff,
sans exécution du parcours réel ni de pytest. r211 passe 117 et la vraie sonde ;
r212 étend la surveillance aux dépendances de déploiement. Les journaux sont
conservés sous noms distincts, avec les préimages. Le RED initial de l’agent
est une collecte sans module ; ses tests substituent explicitement le runtime.

Capsule et manifeste :
`docs/research/REPRISE-2026-10-04/preuves/M5-OCR-PREFLIGHT-r1.tar.xz` et
`M5-OCR-PREFLIGHT-r1.json`. Le PDF fictif est inclus ; les binaires/modèles
externes sont seulement référencés par empreinte, sans redistribution.

La réussite ne vérifie ni le stockage/clé/quota, ni la précision de scans clients,
ni les limites mémoire agrégées d’un conteneur, ni un VPS, ni la CI native au SHA
courant. Le packaging serveur du bundle, les dépendances système et la
compatibilité du daemon restent décrits dans l’[audit image](../grs/compta/M5-OCR-IMAGE-AUDIT-2026-10-04.md).
Aucun succès ne recommande `privileged`, l’ajout de capacités ou la suppression
de seccomp. Les changements restent locaux ; la publication GitHub est bloquée
par l’authentification 401 constatée.
