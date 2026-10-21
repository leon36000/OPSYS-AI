# M3 — lecture jointe des apprentissages d’un chantier

Statut : tranche vérifiée localement; apprentissage empirique global non qualifié.
[Programme](../../programme/PROGRAMME-24H-2026-10-04.md) ·
[Protocole empirique](M3-APPRENTISSAGE-QUALIFICATION-EMPIRIQUE-2026-10-05.md).

## Comportement livré

`m3_lire_apprentissage_chantier(wct_id, coupure_utc)` est un outil T0 réservé à un administrateur
actif authentifié par appareil. Il joint le devis accepté et le hash exact de l’estimation M3,
la preuve WCT et le statut vérifié M4, l’admission train/holdout de la cohorte, les mesures M8
issues de M6 et la lecture actuelle de rentabilité M5. Dépendances M5 et M8 ajoutées au manifeste M3.

La coupure est un horodatage UTC fourni explicitement. Elle borne l’observation de calibration;
elle ne demande pas un état financier historique. Les sources sont relues séquentiellement et
leurs preuves comparées; aucun snapshot transactionnel commun n’est garanti. La sortie est bornée
à 6 000 caractères, les scans M3 à 20 000 estimations et 10 000 lignes de devis; une limite dépassée
reste un refus. Les API internes et registres existants sont réutilisés.

Une observation exclue par la cohorte, un WCT ambigu ou non vérifié, une jointure absente et
une lecture incohérente produisent des motifs précis. Une marge exige simultanément prix définitif,
coût complet, verdict `CALCULEE`, trace M5 à jour et concordance de sa version et de sa valeur M8.
La lecture M5 filtrée rend une vue détaillée : `cout_reel.complet` et `marge_reelle`; les clés
de son événement ne sont pas substituées à ce contrat. La version M8 provient du fait reçu;
un historique sans version reste inconnu. L’unité matérielle reste celle portée par sa source.

La durée M4 est une durée écoulée, pas une paie ni des heures-personnes. Aucune cause de variance
n’est inventée. GPS, identité terrain et coordonnées client sont absents du rapport. Ce lecteur
ne modifie pas les registres métier, ne promeut pas de barème et ne déclenche aucune action financière.

## Preuve exécutée par ROOT

**r249 : 219 tests réussis, zéro échec/erreur/skip dans onze fichiers complets**, Ruff et
`opsys-metier verifier` verts. Sources gelées avant/après sans changement; aucun OOM.
Les branches unitaires vérifient droits, révocation avant réponse, finalité/coûts inconnus,
doublons, unités manquantes, versions modifiées pendant lecture et coupure non UTC.

Le parcours SQLite traverse les vrais outils M2/M3/M4/M6/M5/M8 et le bus/M10 sur données fictives.
Un chantier avec quantité réelle conforme atteint l’observation admise, mais sa facture reste
brouillon : coût complet conservé, marge exclue et montant absent. Un écart matériel critique laisse
le chantier en attente de revue et exclut l’observation. Capture des registres et du bus avant/après :
aucune mutation métier pendant la lecture. Les montants M5 et leur historique M10 sont conservés.

Les échecs r244–r248 sont conservés : incompatibilités de fixtures et d’enveloppes, attente de revue
M4, vue détaillée M5 confondue avec événement, assertions anciennes sur les marges brouillon, puis
ordre des imports. Aucun test métier n’a été supprimé pour qualifier le patch.

Qualification initiale r249 : le parcours réel positif avec facture définitive restait alors non exécuté.
La reprise [M5 finalité et propagation](../compta/M5-FINALITE-PROPAGATION-RAPPORT-2026-10-05.md)
ferme ce manque avec **r254 : 420 tests, seize fichiers complets, Ruff et contrats verts**. Les vrais outils,
la décision humaine N4, puis N5 avec attestation fictive, mettent à jour les versions M5/M8 et rendent
la marge admissible au lecteur; les brouillons restent exclus. Rejeu interdit et panne de publication
annulent ou empêchent la transition et ses effets dérivés sans mouvement comptable automatique.
PostgreSQL actuel, production, corpus client et précision avant/après ne sont pas qualifiés ici.
Aucun réglage de barème ou modèle activé.

Preuves durables : [capsule](../../research/REPRISE-2026-10-05/preuves/APPRENTISSAGE-CHANTIER-r1.tar.xz)
et [inventaire](../../research/REPRISE-2026-10-05/preuves/APPRENTISSAGE-CHANTIER-r1.json).
