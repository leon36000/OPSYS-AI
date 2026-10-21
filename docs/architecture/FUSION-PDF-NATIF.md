# Fusion opérationnelle — PDF financier natif

Le backend local prépare du texte paginé à partir d'un PDF natif et conserve
la source et le résultat chiffrés. Il permet de vérifier la provenance avant
une future extraction financière. L’interface privée permet l’admission, la préparation
explicite et la consultation paginée des extraits par un administrateur actif.

## Admission et reprise

`opsys.fusion_pdf.creer` admet au maximum **1 Mio** de PDF avec une clé de
mutation opaque. L'acteur vient de la session serveur. La même clé avec les
mêmes octets rejoue le lot; une autre source sous cette clé est refusée.
La déduplication inclut l'acteur, la source SHA-256 et la configuration/version
de l'extracteur. Les commandes et les lots sont conservés sans expiration automatique.

Un lot `RECU` devient `EXTRAIT_PREPARATOIRE`, `REFUSE` ou
`ERREUR_REPRENABLE` par l'action explicite `preparer` avec révision attendue.
Le worker travaille hors transaction SQLite. Après son retour, le service
revérifie l'acteur actif, la source, la clé et la révision avant le commit
atomique du résultat, du quota et de l'audit. Un concurrent perdant reçoit un
conflit de révision. Le résultat préparé peut être relu sans reparsage.

Le résultat contient la source SHA-256, la version de pypdf et la configuration,
les pages numérotées dès 1, un fragment textuel par page et son empreinte UTF-8.
Il ne fournit pas de positions visuelles ou d'offsets dans les octets du PDF.
La validité de ces références établit une provenance; l'interprétation
comptable et la correspondance visuelle restent à vérifier.

## Isolation du parseur

Cette tranche exige **Linux, SQLite et bubblewrap système**. Le worker Python
autonome importe pypdf 6.19.0 dans des namespaces privés, sans réseau,
avec environnement vidé. Les montages de lecture comprennent `/usr`, les racines
canoniques de l'interpréteur et de ses bibliothèques, ainsi que le fichier worker.
Ce sont des répertoires runtime, pas une sélection fichier par fichier. Une clé
externe ou son parent dans ces racines est refusé avant l'ouverture du fichier ;
les permissions privées seules ne suffisent pas à l'exclure d'un montage.
L'absence de namespace, d'interpréteur compatible, de bwrap ou de limite
produit un état reprenable explicite. Le processus principal ne parse pas le PDF.

Les plafonds sont : 20 pages, 2 Mio de contenu décompressé par stream/page,
8 Mio de contenus cumulés, 256 Kio de texte, 512 Kio de réponse JSON et
8 Kio de stderr. Les limites kernel précèdent l'import du parseur et la
lecture de la source : mémoire virtuelle 512 Mio, CPU 10 s, fichiers/core
0, descripteurs 64. Le parent impose un délai mural de 15 s, ferme les pipes,
arrête le processus en échec et attend sa terminaison.

Les PDF chiffrés, contenus actifs détectés, images ou pages mixtes, texte
invisible détecté, rotations/annotations ambiguës, réparations signalées et
contenus hors bornes sont refusés. Ce filtre conservateur peut refuser une
facture avec logo. La détection universelle des ambiguïtés et l'OCR ne sont
pas livrés par ce parseur natif. Une consultation humaine reste nécessaire.

## Données et exploitation

La migration additive `0018` crée trois tables : `fusion_pdf_lots`,
`fusion_pdf_commandes` et `fusion_pdf_quota`. Elle préserve les tables CSV
et refuse une rétrogradation destructive. Le quota couvre **16 lots et
16 Mio de chiffrés binaires**, sources/résultats et tags AES-GCM inclus,
même pour les refus conservés. Base64 et métadonnées ajoutent du stockage.
Le quota PDF est indépendant du [quota CSV](FUSION-CSV.md).

Installer l'extra optionnel `ingestion-pdf` verrouillé à cryptography 50.0.2
et pypdf 6.19.0, puis fournir bwrap système. Les clés suivent le protocole
CSV : variable `OPSYS_INGESTION_CLE` par défaut ou nom référencé par
`OPSYS_INGESTION_CLE_REFERENCE`. Aucune clé n'est créée ou conservée en base.
La rotation conserve les références d'origine; sauvegarder séparément base
et clés via le dispositif de secrets de l'exploitant.

Les lectures sont réservées aux administrateurs actifs de la base entreprise.
Elles partagent cette base avec l'identité. Le backend ne filtre pas les lots
par auteur. Il refuse PostgreSQL pour ce pilote; aucune isolation SaaS entre
entreprises n'est qualifiée. Une déconnexion HTTP ne garantit pas un arrêt
immédiat du worker ou l'absence de commit : recharger le lot pour voir son état.

Les données restent dans le compartiment `FINANCIAL`. Le pilote n'interprète
aucun montant, n'écrit pas de facture/ledger et n'alimente pas la mémoire
générale M10, les embeddings ou un fournisseur LLM. La purge gouvernée et
l'ingestion massive multi-format gardent leurs critères propres.

## Vérification locale

Le [lot R28](../programme/LOT-FUSION-PDF-NATIF.md) détaille les preuves.
La sélection indépendante ROOT passe **122 cas** PDF/SQLite et régressions
CSV/console existante, zéro échec ou skip; le cas PostgreSQL est désélectionné.
Les 1 107 empreintes surveillées sont stables. Le vrai PDF M3 est généré
avec des identités fictives puis extrait dans bwrap; les limites kernel sont
lues avant le premier octet stdin. Cela ne qualifie pas un corpus financier
client, l'OCR, la précision comptable ou l'installation sur un VPS neuf.

La [qualification native du 2 octobre](../research/PDF-NATIF-GEOMETRIE-2026-10-02/README.md)
complète ces preuves : 56 tests de contrats et de refus des chemins sensibles,
puis contrôle `--pdf-only` réel avec les codes 0 / 3 / 1 sur une sonde publique
de zéro page. Le raccord opt-in de l'installateur existe ; son installation
intégrale sur un VPS reste à qualifier. Le profil Docker testé refuse toujours
la création des namespaces. Voir le [guide d'exploitation](../ops/INGESTION-PDF-DOCKER.md).

## Interface privée

Le hub `/fusion` donne accès aux pilotes CSV et PDF. `/fusion/pdf` liste au
maximum seize lots; l’admission multipart borne et ferme le fichier, puis
redirige vers les métadonnées. La préparation exige CSRF et révision attendue.
Le texte n’est affiché qu’après consultation explicite d’une page d’extraits;
il est échappé et les réponses restent privées, sans cache. La session et
l’identité sont revérifiées autour des opérations, y compris les erreurs.

Un lot inconnu répond 404; un résultat indisponible répond 409. Les erreurs
de clé, de corruption et de permission produisent des codes stables sans
exposer le contenu ou les détails internes. Les deux premiers cas donnaient
initialement 500 : leurs tests rouges et le correctif restent conservés.

ROOT vérifie l’ensemble backend et interface avec **145 cas**, zéro échec,
erreur ou skip, et 1 112 empreintes stables. Ces cas recouvrent les 122
précédents : les comptes ne s’additionnent pas. Le test PostgreSQL demeure
désélectionné puisque ce pilote refuse ce backend. Cette campagne HTTP ne
constitue pas une validation visuelle sur navigateur ou un déploiement VPS.
