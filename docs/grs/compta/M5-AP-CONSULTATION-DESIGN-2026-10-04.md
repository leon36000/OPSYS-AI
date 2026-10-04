# Consultation durable d'une saisie Fusion — conception préalable

4 octobre 2026, après publication de la saisie confirmée au commit `1f08a4a3`.
Statut initial : conception préalable. L’[implémentation de consultation](M5-AP-CONSULTATION-RAPPORT-2026-10-04.md) est présente ; qualification locale ROOT r130 réussie : 668/668 sur 21 fichiers complets. M5 global PARTIEL.

Problème de départ : après fermeture du navigateur, le GET du brouillon ne
montrait pas sa liaison `fusion_ap_saisies`; une nouvelle observation trouvait
une facture déjà créée. Le GET existant consulte désormais cette référence.
La reprise doit distinguer le brouillon `A_REVOIR`, la référence historique
et l'état courant canonique `SAISIE`, `CORRIGEE` ou `ANNULEE`.

Réutiliser la liaison 0024, les approbations et reçus existants, la chaîne M5
bornée et son unique projecteur `_etats_factures`. Aucun nouveau registre,
outil, migration, paiement, POST automatique ou whitelist générique.
Le lecteur exige propriétaire actif ou admin+finance, dans une transaction;
la page revalide ces droits avant et après rendu. Un admin sans finance garde
sa revue documentaire existante, sans nouvelle référence financière affichée.

Valider les hashes de provenance, le rang/maillon original, l'approbation N3
exécutée avec ses arguments, son résultat et le reçu idempotent exact. Le reçu
se lit sans `reclamer`, donc sans écriture. Bornes avant décodage des preuves,
arguments et résultats; toute corruption renvoie indisponible, sans faux
« aucune saisie ». Une absence de liaison ne prouve pas l'absence de facture
indépendante dans M5.

Cette consultation lit ce qui a été enregistré : elle ne recalcule pas les
anciennes taxes avec un dictionnaire fiscal remplacé et ne revalide pas la
facture imprimée. Les octets historiques PDF/taux ne sont pas recopiés.
Une modification ultérieure de ces sources n'efface pas la référence de dette;
la provenance affichée est historique, pas une observation fiscale actuelle.
Les corrections/annulations restent des pièces M5; elles ne réécrivent pas
l'original. Ne rendre ni motif libre, arguments, corps PDF ni source fiscale.

Le GET AP existant présente la référence et l'état courant aux droits financiers.
Le reçu de confirmation donne un lien vers ce GET et vers `/finance`, existant;
aucune fausse vue AP détaillée ni nouveau paramètre finance n'est revendiqué.
Afficher les seuls identifiants et compte de corrections, sans valeurs métier
supplémentaires. Le GET de revue conserve ses préconditions PDF actuelles;
si cette source est indisponible, la revue n'est pas une archive indépendante.

Tests : référence retrouvée après reconnexion; observation sans liaison;
correction/annulation puis lecture et rejeu; changement des taux sans perte
de référence; admin sans finance, révocation pendant lecture/rendu; corruption
preuve/maillon/approbation/reçu, bornes avant parsing; aucune table modifiée.
Les preuves SQLite/PDF natif fictif ne qualifient pas PostgreSQL, factures
réelles, mobile AP, rétention, paiement, ledger final ou CFO complet.
