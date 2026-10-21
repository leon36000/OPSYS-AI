# R22 — STT durable, Fusion CSV, tickets M3 et trace de durée

Clôture locale du 2 octobre 2026 UTC. Base 2e56c0d5605dfe575bde9244f38924d5390f2674, branche codex/restructuration-2026-09-30. Voir le [bilan détaillé](../../programme/REPRISE-BILAN-2026-10-02.md). Aucun changement publié; les départements restent partiels hors de ces tranches.

| Campagne ROOT finale | Résultat | Portée |
|---|---|---|
| Python intégré r2 | 467 tests; zéro échec, erreur, skip; 82,830 s JUnit | STT, console, Fusion (19), migration/stockage SQLite, M2/M10/M3, HTTP MCP réel local (1), clôture de chantier E2E (16); PostgreSQL exclu |
| Core r3 | 405 tests dans neuf fichiers; zéro échec, erreur, skip | Config/garde/ticket/contexte MCP; pas de compilation globale ni appel LLM Gateway |
| Qualité r2 | Ruff, verrou offline, catalogue et diff verts | 24 fichiers Python; 10 départements, 207 outils, 116 capacités appareil |

Les 1 092 empreintes Python sélectionnées et 35 209 empreintes Core sélectionnées sont stables avant/après leur campagne respective. [SOURCES-FINALES.json](SOURCES-FINALES.json) décrit l’union exacte; certains fichiers générés Core préexistants sont inclus par le filtre du harnais. Les comptes des campagnes intermédiaires, des auteurs et des domaines ne s’additionnent pas.

Preuves Python : [reçu](preuves-root/poursuite-integree-root-r2-2026-10-02-resultat.json--ef7682fc7a05.gz), [JUnit](root/poursuite-integree-root-r2.xml--5c6e99599e69.gz), [journal](preuves-root/poursuite-integree-root-r2-2026-10-02.log--59a4614dffe5.gz).

Preuves Core : [reçu](root/core-c02-integre-root-r3-resultat.json--2d7459746cad.gz), [JUnit](root/core-c02-integre-root-r3.xml--71a17b3eb1d9.gz). Qualité : [commandes et dates](root/qualite-root-r2-commandes.json--fa054afdea08.gz).

## Changements et limites

STT : références de secrets persistées, révision/idempotence, diagnostic manuel borné sans audio et sans affirmation de STT réel. CSV : sources/résultats chiffrés AES-GCM, reprise par 100 lignes, parseur M5 réutilisé une fois, compte interne autorisé, quota 64 lots/64 MiB de ciphertext, provenance documentaire M10. PostgreSQL est explicitement refusé par le pilote. Aucun paiement, rapprochement final ou écriture fiscale.

C02 : m3_creer_devis utilise une cible composite stricte et les chaînes canoniques M2/M10 vérifiées; la garde reste partielle pour le catalogue général et ne certifie pas les coûts transmis. M3 : trace du barème et de la durée avec sémantique non_qualifiee; aucune calibration apprise ni gain mesuré.

Les premières préimages complètes CSV manquent. Les reprises suivantes ont leurs préimages et la comparaison ROOT de hashes; ces éléments ne remplacent pas les octets initiaux manquants. Les noms horaires manuels des premiers logs auteurs ne valent pas reçus datés. Les tests emploient des données fictives; leurs identifiants d’accès ne sont pas des secrets de production.

Les rouges sont conservés : mauvais chemin de config Core avant collecte, ancien test Core refusant un outil désormais permis, deux imports Ruff, et tentative auteur PostgreSQL échouant pendant initdb faute d’espace. Ils ne sont pas réécrits en résultats verts. La recherche voix/avatar (GitHub/GitLab, notices, captures) reste documentaire; aucun framework vocal/3D ou modèle NVIDIA n’a été installé ni intégré.

## Conservation

Le premier contrôle documentaire a vérifié le lien vers son propre reçu avant d’avoir créé ce fichier : ce seul faux positif est conservé dans `QUALIFICATION.json`. Le [contrôle r2](QUALIFICATION-R2.json), exécuté après création des reçus, clôt les liens et archives; il ne relance pas les tests métier.

[MANIFEST.json](MANIFEST.json) décrit 293 archives gzip déterministes : origine, taille et SHA-256 original/compressé. [QUALIFICATION.json](QUALIFICATION.json) vérifie les archives, liens locaux des docs de clôture et l’identité des sources au moment de cette clôture. Les preuves R19/R20/R21 restent inchangées. Les sources livrées et docs sont conservées en instantanés, même si le lot suivant les fait évoluer.
