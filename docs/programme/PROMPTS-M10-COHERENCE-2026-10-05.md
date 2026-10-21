# M10 — prompt engineering et limites factuelles

Correction éditoriale du 5 octobre 2026 : SOUL, procédure de préflight et bannière du brief historique. Aucun outil, runtime, schéma, permission ou dépendance ajouté. La cible reste une mémoire d'entreprise rigoureuse et une mémoire de développement séparées par domaine et permissions ; ces objectifs ne prouvent pas que toutes les capacités sont livrées.

## Corrections

- L'append-only des maillons ne promet plus une capture complète ou une rétention sans perte. Une chaîne intacte ne dit pas si un événement attendu manque ; la réponse doit citer sources, dates, lacunes et contradictions.
- Le préflight actuel valide la forme des cinq champs et une liste non vide de références de décisions. Il ne vérifie pas leur existence ou la vérité du dossier. Les consignes imposent une vérification séparée des sources et, lorsqu'elle est fournie, de la référence canonique via l'outil existant. Aucune décision ou justification fictive ne doit être créée pour satisfaire le schéma. Un résultat `suffisant: true` n'est ni une approbation ni une preuve de succès métier.
- Le garde Core demeure conditionnel à son activation et aux contrats N3+ configurés. Une consigne ne l'active pas et ne peut pas le contourner. L'ordre des quatre couches du paquet est une présentation ; il ne remplace pas l'autorité des sources et ne minimise pas les signaux critiques.
- Seules les réponses structurées décodables peuvent devenir des faits candidats. Absence de candidat, transport perdu, approbation en attente ou intention incertaine ne deviennent pas un succès/refus inventé et n'autorisent pas à répéter l'action source. Le candidat reste hors paquet de contexte et hors consolidation d'affaire actuelle. Clé, affaire et provenance ne sont pas fabriquées.
- La reprise idempotente est limitée à la consolidation de la même affaire et du même jour. Elle n'est pas étendue aux appels métier. Le hash WCT reçu est conservé, sans prétendre qu'il certifie à lui seul toute l'exécution du chantier.
- Le brief analyste initial conserve son corps et ses décisions. Une bannière signale que ses inventaires « aucun M10 » et « application PREFLIGHT/POSTFLIGHT hors produit » sont dépassés. Elle renvoie aux rapports du Core, sans ratifier rétroactivement les anciennes affirmations de production ou tout D-014.

## Contrôle proportionné

La première revue Luna avait utilisé un autre checkout : elle est conservée comme non qualifiée pour les sources actives. La revue r2 a relu le checkout actif avec empreintes ; ROOT a vérifié le code et relevé en plus que le préflight ne contrôle pas l'existence des décisions. Préimages, diff, références et SHA sont conservés. Le YAML du skill et les quatorze noms d'outils cités ont été vérifiés contre le propriétaire réel. Le diagnostic CLI demeure réservé à l'opérateur local, sans nouvel outil modèle.

Ce patch factuel réversible est contrôlé par les contrats, le diff et les liens locaux, sans tests qui recopient le texte. Aucune évaluation de comportement LLM, amélioration statistique ou économie de tokens mesurée n'est annoncée. Le format compact de restitution réduit la répétition dans la consigne ; son effet doit encore être évalué. M10 reste PARTIEL : ingestion massive, RAG/graphe, réconciliation humaine, couverture complète et autonomie entreprise ne sont pas qualifiés par ce lot.

La docstring Python du préflight conserve une formulation historique sur le hook futur : dette documentaire identifiée, sans modification de runtime dans ce lot. Les gardes et contrats actuels doivent rester la référence pour l'exécution.

[Capsule de contrôle](../research/REPRISE-2026-10-05/preuves/PROMPTS-M10-COHERENCE-r1.tar.xz) ; [inventaire et SHA](../research/REPRISE-2026-10-05/preuves/PROMPTS-M10-COHERENCE-r1.json). r377 utilise le scanner de secrets par défaut sur les cinq documents, quinze références, deux revues et le plan ROOT, sans exception ajoutée. Ce périmètre ciblé ne prétend pas scanner tout le dépôt ou l'archive. Préparation Git isolée locale uniquement ; ni push ni CI distante qualifiés.
