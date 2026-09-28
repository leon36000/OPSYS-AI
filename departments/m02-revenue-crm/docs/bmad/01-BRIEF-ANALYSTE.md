BRIEF ANALYSTE — MODULE M2 (REVENUE CRM)

> Analyste et PM : Qwen3.7-Max. Architecte : Kimi-K3 (prose seule, aucun code — rôle respecté).
> Correction imposée au brief par l Orchestrateur : le critere « statut en moins de 100 ms » a ete
> REJETE (latence machine-dependante, non reproductible en CI, ne prouve rien) et remplace par un
> critere deterministe fail-closed. Addendum D3 demande par l Orchestrateur : la 2 tranchait la
> duplication sans en tarifer le COUT (heriter des defauts M1 + divergence silencieuse).
Rédigé par : Analyste BMAD | Statut : PROPOSÉ | Date : 2025-01-XX

1. BESOIN MÉTIER

M2 est le gardien du pipeline commercial. Son mandat unique tient en une phrase : aucun lead ne doit exister dans le système sans un statut explicite, un owner humain désigné, et une prochaine action horodatée. M2 reçoit de M1 les leads qualifiés (contrat LeadQualifie gelé, sha256 épinglé), les inscrit dans un registre append-only, leur attribue un statut parmi un enum fermé (nouveau, qualifie, converti, perdu), et garantit qu'à tout instant, chaque lead est traçable, actionnable, et prêt à être transmis aux modules aval uniquement lorsqu'il satisfait la readiness gate M3. Les bénéficiaires directs sont l'équipe commerciale (qui reçoit des leads propres, non dupliqués, avec contexte complet), Nathan (qui consulte le digest quotidien des leads en attente d'action), et M3/M4/M5 (qui ne reçoivent que des leads ayant franchi la readiness gate). M2 ne vend pas, ne chiffre pas, ne planifie pas d'intervention, ne facture pas : il organise la mémoire commerciale et garantit qu'aucune opportunité ne tombe dans un trou noir.

2. CONTRAINTES NON NÉGOCIABLES

La readiness gate vers M3 est un verrou strict : un lead ne part en estimation que s'il dispose d'un owner humain confirmé, d'un type de travaux validé, d'une ville renseignée, et d'au moins une interaction humaine post-qualification (le lead ne peut pas être transmis sur la seule base de la qualification automatique M1). La fusion de doublons est une décision exclusivement humaine : M2 peut détecter des doublons potentiels (même contact OU même combinaison ville et type de travaux, dans une fenêtre glissante de 7 jours calendaires calculée sur les dates d'ingestion fournies par l'appelant) et les signaler, mais jamais les fusionner automatiquement. Une fusion irréversible sur décision algorithmique serait une perte de données commerciales irrécupérable. Les frontières de vérité sont strictes et non négociables : M2 ne produit jamais de prix (domaine M3), jamais de date d'exécution ou de planification (domaine M4), jamais de chiffre financier ou de facture (domaine M5). M2 stocke et organise, il ne calcule pas. Tout champ tentant de déborder sur ces domaines est rejeté avec verdict REJ-FRONTIERE-VIOLEE.

3. CE QUI EST PROUVABLE MAINTENANT VS GATED/T3

Prouvable maintenant en CI Python, mode ombre, sans réseau ni CRM externe : registre append-only hash-chaîné (patron M1 réutilisé), machine à états des statuts avec transitions validées, détection de doublons potentiels avec signalement (pas de fusion), readiness gate M3 implémentée comme fonction booléenne pure, digest quotidien des leads en attente, adaptateurs in-memory fail-closed pour simuler l'écriture vers un CRM tiers (patron M1-S007), fixtures fictives marquées fictif: true, tests unitaires couvrant tous les chemins de transition et tous les rejets. GATED et hors périmètre immédiat : intégration réelle avec un CRM tiers (HubSpot, Pipedrive, ou autre) — cela nécessite des credentials, un environnement de test, et une validation T3 par Nathan. Envois réels de notifications (courriel, Slack) — GATED comme M1-S007. Webhooks entrants depuis formulaires web tiers — GATED. Toute écriture réelle en base de données externe — T3.

4. CE QUE M2 CONSOMME ET PRODUIT

M2 consomme exclusivement le contrat gelé LeadQualifie produit par M1 : lead_id, conversation_id, contact, type_travaux (enum fermé : renovation_totale, extension, ravalement, isolation_thermique, autre), ville, urgence_declaree, canal (telephone, courriel, formulaire, texte). M2 ne redéfinit pas ce contrat, ne l'étend pas, ne le modifie pas. M2 produit pour M3 un lead enrichi avec owner humain assigné et readiness gate franchie (statut qualifie + owner confirmé + interaction humaine post-qualification). M2 produit pour M4 le même lead enrichi, avec en plus la disponibilité déclarée du client (champ optionnel ajouté par M2, jamais une date ferme). M2 produit pour M5 un résumé du lead converti (statut converti) avec référence au devis M3 accepté, sans jamais stocker le montant. M2 ne produit rien pour M1 (le flux est unidirectionnel).

5. RISQUES D'ENTRÉE

R-M2-001 : lead orphelin sans owner — un lead qualifié reste en statut nouveau sans assignation humaine, créant un trou noir commercial. Mitigation : alerte digest après 24h sans owner, escalade après 48h. R-M2-002 : doublon fusionné à tort — si la fusion automatique était implémentée (elle ne l'est pas, mais le risque doit être documenté), deux leads distincts seraient écrasés en un seul, perdant l'historique de l'un. Mitigation : fusion exclusivement humaine, avec audit trail complet. R-M2-003 : statut incohérent — un lead marqué converti sans devis M3 associé, ou qualifie sans owner. Mitigation : machine à états avec transitions validées, rejet de toute transition illégale. R-M2-004 : readiness gate contournée — un lead transmis à M3 sans satisfaire les critères, créant une estimation sur données incomplètes. Mitigation : M3 refuse tout lead ne portant pas le marqueur readiness_ok: true signé par M2. R-M2-005 : empiètement sur prix/dates — un champ M2 tente de stocker un prix ou une date d'intervention, violant les frontières de vérité. Mitigation : validation stricte du schéma, rejet avec verdict REJ-FRONTIERE-VIOLEE.

6. CRITÈRES DE SUCCÈS MESURABLES EN MODE OMBRE

Tous les critères ci-dessous sont des propriétés booléennes vérifiables par un test unitaire ou d'intégration déterministe, sans dépendance à la machine, au runner, ou à une métrique de couverture.

CS-M2-01 : toute ingestion réussie d'un contrat LeadQualifie valide produit un lead dont le statut appartient à l'énumération fermée {nouveau, qualifie, converti, perdu} ; aucune ingestion ne produit un lead sans statut.

CS-M2-02 : toute ingestion d'un contrat violant les frontières de vérité est rejetée avec le verdict REJ-FRONTIERE-VIOLEE et n'inscrit aucun maillon au registre.

CS-M2-03 : zéro lead sans owner après 48 heures simulées — le digest quotidien, produit avec un horodatage d'appelant postérieur de plus de 48 heures à la date d'ingestion fournie, liste exhaustivement tout lead en statut nouveau dépourvu d'owner.

CS-M2-04 : zéro transition de statut illégale acceptée — tout chemin hors table reçoit REJ-TRANSITION-ILLEGALE, toute condition manquante sur un chemin autorisé reçoit le verdict spécifique (REJ-OWNER-ABSENT, REJ-DEVIS-ABSENT, REJ-MOTIF-ABSENT).

CS-M2-05 : zéro fusion automatique de doublons — après signalement, le registre contient toujours les deux leads distincts ; aucune fonction de fusion n'existe dans l'arborescence du module.

CS-M2-06 : readiness gate M3 — la gate retourne faux dès qu'une quelconque des quatre conditions manque, et l'interaction humaine exigée doit être strictement postérieure ou égale à l'horodatage de transition vers qualifie.

CS-M2-07 : frontières de vérité — zéro champ prix, date d'exécution, montant financier, ou engagement contractuel stocké dans M2 après toute séquence d'opérations valides.

CS-M2-08 : digest quotidien — la liste produite est exhaustive, triée par date d'ingestion fournie par l'appelant, et identique entre deux exécutions successives avec les mêmes entrées.

CS-M2-09 : registre hash-chaîné — valider_chaine retourne vrai après toute séquence d'opérations valides et faux après altération, troncature ou réordonnancement d'un maillon.

CS-M2-10 : conformité dupliquée — les fichiers dupliqués depuis M1 (encodage, horodatage, registre) portent une empreinte sha256 attendue épinglée comme constante littérale dans les tests M2, et une suite de cas d'abus héritée de M1 est rejouée contre les implémentations M2.

CS-M2-11 : mode ombre — zéro appel réseau, zéro écriture externe, zéro donnée réelle, zéro horloge interne (tout horodatage est un paramètre fourni par l'appelant).

