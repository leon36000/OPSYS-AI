# OCR M5 — profil PDFium candidat exécuté sous confinement

4 octobre 2026 UTC. **Pilote local uniquement**, sans activation produit,
installation dans l'environnement partagé ni changement du lecteur PDF natif.
Le [wheel candidat épinglé](M5-OCR-ARTEFACT-PDFIUM-2026-10-04.md) est distinct
du wrapper 5.3.0 du premier pilote. ROOT éprouve ici son chargement effectif,
le rendu et la sortie Tesseract dans le même confinement Linux/bubblewrap.

## Résultat ROOT r171

Deux scans synthétiques déjà utilisés par le [premier pilote](M5-OCR-PILOTE-CPU-2026-10-04.md)
sont rendus puis reconnus réellement, sans réseau. Les TSV bruts passent le
[contrat de candidat](../../grs/compta/M5-OCR-CONTRAT-2026-10-04.md), chacun avec
55 tokens conservés tels quels. Les 82 tests complets du contrat passent aussi,
zéro échec/erreur/skip, 0,328 s JUnit. Ruff et vérificateur métier réussissent ;
1 258 sources surveillées inchangées, aucune hausse OOM ou processus survivant.
Campagne de 5,054 s ; pic RSS du groupe OCR observé 50 262 016 octets.
Le sondage de RSS ne représente pas une mesure instantanée exhaustive.

| Scan fictif | Source | Rendu | OCR | TSV | Dimensions |
|---|---:|---:|---:|---:|---|
| Propre | 69 672 octets | 0,243 s | 0,344 s | 3 196 octets | 1 275 × 1 651 |
| Incliné, contraste réduit | 289 910 octets | 0,272 s | 0,332 s | 2 999 octets | 1 275 × 1 651 |

Ce sont deux observations, pas un benchmark de production ou un débit serveur.
Les chaînes de lignes synthétiques attendues concordent strictement 10/10
sur le scan propre et 4/10 sur le scan incliné. Cette comparaison sensible à
la casse ne mesure pas la précision comptable. Une erreur significative demeure :
le scan incliné reconnaît `FACT-FICTIVE-007` pour l'identifiant synthétique
attendu `FACT-FICTIVE-001`. Aucun correctif automatique ne le remplace.
Accepter un TSV valide ne valide donc ni la facture ni un montant.

## Identités et enveloppe réellement éprouvées

Le wheel 5.13.0 est vérifié à taille et SHA-256 exactes, puis toutes ses entrées
hashées RECORD sont contrôlées. Ses packages sont extraits uniquement en RAM,
montés en lecture seule. Avant import, le worker contrôle le hash natif et les
JSON de version ; après import, il exige les chemins réels du wrapper, du
module raw, du module de configuration et de la bibliothèque chargée sous
`/rasterizer`. Le paquet partagé 5.3.0 n'est pas utilisé pour le rendu.

- Wrapper : `pypdfium2-5.13.0`, wheel SHA-256
  `81df25c1ab4c13ff773102d3cbea1967511d079123b067fc077bd0c4d57d91d8`.
- PDFium : build 153.0/7999, bibliothèque SHA-256
  `224f8ece41f7e35891f11c10073b7b7062d7a18e9ef870586162a85c46130f7d`.
- Tesseract 5.5.0 / Leptonica 1.84.1 : sonde réelle de version avant lancement.
- Modèle français déjà acquis : SHA-256
  `ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca`.

Sources ≤ 1 Mio, une page, 150 DPI, ≤ 4 000 000 pixels ; PNG et sortie ≤ 512 Kio.
Environnement effacé, namespaces `--unshare-all`, fichiers de code/modèle en
lecture seule, stdin/pipes et `/tmp` tmpfs ; aucune connexion fournisseur.
Chaque worker garde 512 Mio d'espace d'adressage, 10 s CPU, 15 s au mur,
`RLIMIT_FSIZE=0`. Le processus Tesseract utilise trois variables non secrètes
pour locale et threads. Aucun repli hors confinement.

## Refus conservés et corrections du pilote

r166 échoue au chargement : l'extraction ne comprenait pas le nouveau package
`pypdfium2_cfg`. Le diagnostic borné r167 prouve `ModuleNotFoundError`.
Le nouveau harness r5 inclut ce package déjà présent dans le wheel et son
RECORD ; aucun téléchargement ou ajout de dépendance OPSYS.

r168 rend le scan mais échoue à obtenir le TSV. Les diagnostics r169/r170
prouvent `read_params_file: Can't open tsv` : le dossier de modèle privé ne
contient pas ce fichier de configuration. Le harness r6 restaure la commande
explicite du premier pilote, `-c tessedit_create_tsv=1`, avec `--psm 6`.
Cette correction du lanceur ne change ni moteur ni poids. Les répertoires,
logs et reçus rouges restent intacts ; les diagnostics ne sont pas des suites
fonctionnelles vertes. Le résultat final vient d'une seule campagne ROOT r171.

## Limites et suite

Les TSV sont conservés privés uniquement parce que les pièces sont fictives.
Le résumé ne conserve pas leurs tokens ; les enveloppes PNG/base64 et stderr
sont représentées par tailles/empreintes. La capsule contient les sources du
pilote, fixtures et sorties synthétiques ; binaires et poids externes restent
référencés par empreinte, sans redistribution dans cette preuve.

Cette expérience ne qualifie pas un classificateur universel image seule,
un corpus d'entreprise réel, photos/multipage/redressement, une image Docker,
un VPS, chiffrement durable, revue console/mobile ou saisie AP. Aucun registre
financier ni mémoire financière n'est écrit. Les notices de distribution restent
celles du candidat exact ; aucune signature/build reproductible n'est prouvée.
M5 et OPSYS-AI restent **PARTIEL**. Prochaine tranche : worker produit et
prévol mesuré, puis stockage et revue humaine avec leurs propres preuves.

[Capsule immuable](preuves/M5-OCR-RUNTIME-PDFIUM-r1.tar.xz) et
[inventaire](preuves/M5-OCR-RUNTIME-PDFIUM-r1.json).
