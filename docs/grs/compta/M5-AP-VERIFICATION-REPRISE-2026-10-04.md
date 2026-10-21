# Fusion AP → contrôles M5 en lecture seule

Tranche du 4 octobre 2026, issue de l'[audit et du design préalable](M5-AP-VERIFICATION-DESIGN-2026-10-04.md).
M5 et OPSYS-AI restent **PARTIEL**. Ce parcours observe les contrôles canoniques,
sans confirmer une facture ni remplacer la revue humaine/CPA.

## Parcours livré

Depuis le détail d'un brouillon PDF `A_REVOIR`, un administrateur actif possédant
aussi `finance` ou `nathan_owner` saisit les identifiants du fournisseur et du PO
reçu dans M5, puis atteste leur correspondance avec les champs imprimés. Ce choix
humain ne constitue pas une résolution automatique de noms de fournisseurs.

`POST /fusion/pdf/lots/{lot_id}/ap/verifier-m5` exige CSRF et les révisions PDF/AP
attendues. Le préfixe habituel de console s'applique (`/opsys` par défaut). Le POST
ne reçoit ni montant, ni acteur, ni taux fourni par le navigateur. Il relit les
champs chiffrés, les références, les octets PDF source et leur intégrité, puis la
chaîne AP M5 actuelle dans une transaction SQLite de l'instance.

Les montants doivent être des textes tels que `100.00`, `14.98`, `114.98`; date
`AAAA-MM-JJ`, devise `CAD`. Le formulaire AP existant permet la correction humaine
avec citations. `100.00 CAD`, virgule décimale, notation scientifique et détail de
taxes non structuré sont refusés; la taxe attendue ici est l'agrégat TPS+TVQ.

Le résultat présente les montants recalculés, les versions/sources fiscales, les
codes d'avertissement, les révisions, l'instant et l'empreinte du snapshot de
sources. Cette empreinte identifie les sources observées, **pas une décision ou
une approbation**, ni le mapping humain PO/fournisseur. Une répétition relit tout
et peut produire un nouvel instant d'observation. Une garde terminale refuse un
changement de source; les droits sont recontrôlés après chaque appel bloquant et
après le rendu HTML. Les réponses sensibles sont privées et `no-store`.

## Réutilisation et fichiers

| Fichier | Rôle |
|---|---|
| `departments/m05-financecore/src/m5_financecore/comptes_a_payer.py` | Préparation commune; nouveau `verifier_facture_fournisseur` pur, contrôle PO/fournisseur/dates/taxes/doublons à leur état courant |
| `departments/m05-financecore/src/m5_financecore/taux_fiscaux.py` | Option `contenu_octets` pour valider exactement les octets épinglés; même validateur, chemin historique inchangé |
| `src/opsys/console/fusion_ap_m5.py` | Autorité en base, source PDF/AP, chaîne AP bornée et vérifiée, taux et snapshots, aucun effet métier |
| `src/opsys/console/fusion_ap_ui.py` | Formulaire explicite et observation privée, validation fermée des champs, échappement HTML et révocation |

Les helpers PDF/AP existants sont réutilisés dans la même transaction. La source
claire est abandonnée après son contrôle; aucun corps, verdict ou snapshot n'est
stocké ailleurs. La chaîne est prébornée à 10 000 maillons, 8 Mio au total et
64 Kio par maillon; le fichier de taux à 64 Kio. Aucun nouveau registre, migration,
outil MCP, abonnement, dépendance, embedding, LLM ou appel réseau n'est ajouté.
La saisie existante conserve son comportement et son unique écriture canonique;
elle ne reçoit jamais une validation durable issue de cette page.

## Qualification

ROOT r119 : **363/363 tests, dix fichiers complets**, zéro échec/erreur/ignoré;
Ruff vert, sources gelées stables et aucune garde/OOM déclenchée. Ils couvrent les
anciens comptes AP, leurs outils et l'interdiction de décaissement, le calcul et
le chargement fiscal, les brouillons PDF/AP, ainsi que le nouveau parcours privé
sur SQLite réel et PDF fictif extrait par le worker natif isolé.

Les nouveaux tests comparent toutes les tables avant/après vérification et
répétition. Ils refusent PO non reçu, fournisseur différent, doublon vivant,
total/taxes incohérents, formats ambigus, devise non CAD, sources/révisions
modifiées, ciphertext/chaîne corrompus, source hors borne, CSRF, champs dupliqués
ou inconnus, paramètres query, admin sans finance et révocation pendant
traitement/rendu. Correction et annulation sont évaluées à leur état courant.

r116 (lint), r117 (collecte) et r118 (**353 réussis/4 refus de qualification**) sont
conservés. r118 reproduit un vrai défaut de rendu : retirer le rôle finance tout
en conservant admin permettait encore l'affichage. Le contrôle terminal le bloque
en r119. Les trois autres échecs concernaient les assertions de code/forme d'erreur
de fixtures; elles contrôlent désormais les codes exacts et les HTTP attendus,
sans assouplissement du service. La reprise compare le snapshot, pas l'égalité
de l'horodatage de deux observations différentes.

Preuves locales : capsule `M5-AP-VERIFICATION-r1` dans
`docs/research/REPRISE-2026-10-04/preuves/`, reçus et gels ROOT r116–r121.
La CI native du commit de cette tranche doit être suivie séparément; les anciennes
CI ne la remplacent pas. Les campagnes qui se recouvrent ne s'additionnent pas.

## Limites et prochaine tranche

Le résultat signifie seulement « contrôles M5 compatibles au snapshot observé ».
Il ne vérifie pas une exonération, toutes les mentions fiscales, le détail des
lignes ou la concordance des quantités/prix PO-réception-facture, ni l'exactitude
sémantique des citations. Les taux/source versionnés existants ne sont pas une
certification CPA. Aucun rapprochement n'est appliqué et aucun texte financier
n'est envoyé à la mémoire générale.

La [saisie M5 confirmée](M5-AP-SAISIE-RAPPORT-2026-10-04.md) dispose désormais
d'un second POST privé, distinct de cette vérification : approbation N3,
idempotence, revalidation et provenance Fusion `0024`. Ce POST de vérification
reste sans facture ni dette ; seule la confirmation explicite crée une dette
interne `SAISIE`, sans paiement ni écriture finale. Sans PO, OCR/image,
fournisseurs réels, rétention, ingestion massive, QuickBooks/CCube et actions
officielles restent à qualifier séparément.
