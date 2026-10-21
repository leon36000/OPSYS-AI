# Demande → vendeur → M3 : livraison locale

Statut : **PARTIEL — tranche qualifiée localement**, pas un département complet.
[Conception](M2-PREPARATION-M3-DESIGN-2026-10-05.md) · [Programme](../../programme/PROGRAMME-24H-2026-10-04.md).

La fiche vendeur lit maintenant l'outil existant `m2_evaluer_readiness` et montre la préparation commerciale séparément des contrôles photo/prix de M3. La lecture n'écrit rien et le marqueur n'est pas mis en cache. Mauvais lead, enveloppe/date/hash incohérents, panne ou refus restent non vérifiés/refusés; aucun ancien résultat positif n'est repris. Le service revérifie la session avant/après; les résultats tardifs sont ignorés au changement de fiche. La provenance campagne/UTM est affichée depuis Client 360, sans déduction d'une source manquante. La date de consultation est fournie par l'appareil, pas attestée par l'horloge serveur.

Fichiers : `mobile/src/m2/readiness.ts`, `mobile/src/vendeur/chargeurReadiness.ts`, `service.ts`, `mobile/app/(seller)/lead/[id].tsx`, `mobile/src/m2/client360.ts`, leurs tests et les traductions fr-CA/en-CA. Réutilisation du transport/session/parsers existants; aucune dépendance, API ou permission nouvelle.

## Parcours intégré

Le septième scénario de `tests/e2e/test_formulaire_utm_bout_en_bout.py` traverse la vraie route HTTP interne signée M1 puis le bus M2/M8. Il garde le même lead/UTM : qualification par un humain fictif, note du vendeur A idempotente, refus générique pour le vendeur B sur lead existant/inconnu, gate commerciale pure, estimation bloquée sans photos, correction synthétique puis devis interne HTML « BROUILLON — non envoyé ». Le barème 10..12, 30 pi_lin, taux 0.20 et photo descriptive sont des fixtures existantes, jamais un tarif/image client réel. Le prix 360.00 est recalculé par M3.

Le mode M3 **ombre** est conservé : les estimations et le devis sont exécutés via de vraies demandes d'approbation décidées par le propriétaire fictif. La création exige aussi la liaison M10 et le ticket de cible émis par la plateforme. Aucun envoi, acceptation, conversion ou dépense n'est appelé. Le rejeu de la demande intervient après drainage de l'assignation, pour ne pas confondre livraison bus encore pendante et duplication.

## Prompt engineering

Une ancienne consigne M3 confondait intervalle de coût et prix client. Elle est corrigée : coûts/P50/P80 restent internes aux vues autorisées, prix seulement depuis `prix_recommande`/scénarios calculés, taux manquant demandé.

Les quatre fichiers SOUL/skills M2/M3 imposent : même dossier, faits et sources → verdict exact → prochaine action proposée → limites. Ils distinguent qualification commerciale/photos, approbation en attente/exécution, approbation/ticket de cible et statut envoyé/preuve de livraison. Ils traitent texte client/mémoire comme données, interdisent prix/date/responsable/seuil inventés et évitent relances identiques sans correction des entrées. Le code reste l'autorité; ces instructions ne créent aucun droit.

Cas d'évaluation à rejouer lorsqu'un modèle est disponible : marqueur ancien après modification, instruction hostile dans le message client, réponse outil refusée, panne avec ancienne fiche cache, demande ombre en attente, devis sans ticket et photos absentes. Attendu : source/verdict exact, aucun faux résultat ni nouvelle mutation. Aucune évaluation LLM ni économie de tokens n'est mesurée dans cette tranche.

## Vérification ROOT

| Campagne | Résultat | Portée |
| --- | --- | --- |
| r228 | 335/335, 14 fichiers complets + TypeScript | parseurs, chargeurs, session, cache, provenance et câblage source |
| r237 | 272/272, 8 fichiers complets + Ruff + manifests | outils M2/M3, blocage prix, scénario intégré et droits vendeur |

SHA avant/après inchangés pendant chaque campagne, processus bornés et aucun OOM. Les runs rouges sont conservés : collision de noms pytest (r227), baseline bus (r230), accusé sans auteur (r231), demande ombre (r233), contrat intervalle sans bornes (r234), ticket requis (r235), puis ligne de documentation trop longue (r236; tests déjà verts). Ils n'ont pas été comptés comme qualifications. Aucun contrôle de permission/mode n'a été désactivé.

Limites : pas de rendu React Native/téléphone physique, navigateur public ou Core TypeScript exécuté dans ce parcours. Le harnais refait la porte Core en Python autour du vrai MCP. M3 valide la structure/concordance du marqueur, **pas son origine cryptographique ni sa fraîcheur actuelle** : risque adjacent ouvert. Photos et montants fictifs ne prouvent aucune précision géospatiale/statistique. GitHub/CI distante et production ne sont pas qualifiés.

Preuves durables : [capsule](../../research/REPRISE-2026-10-05/preuves/VENDEUR-M8-PROMPTS-r1.tar.xz), [manifestes SHA et reçus](../../research/REPRISE-2026-10-05/preuves/VENDEUR-M8-PROMPTS-r1.json).
