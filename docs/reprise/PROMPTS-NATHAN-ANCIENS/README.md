# Anciens prompts de Nathan — exigences fonctionnelles à reprendre (reçus le 2026-11-02)

Nathan a fourni d'anciens prompts « Quadruple A » (GRS/Forge, juin 2026) pour chaque département, **à n'utiliser que pour les
fonctionnalités et l'intention**. Ils décrivent une architecture ancienne (FastAPI `grs_api`, `module8_marketing`, LangGraph, Cognee,
Langfuse, Temporal, Cursor preflight/postflight, n8n) qui n'est PAS celle d'OPSYS-AI actuel (départements `departments/mNN-*`, bus
d'événements, sas d'approbation N0–N5, registre MCP scellé, SQLite/PostgreSQL, Core TypeScript, app mobile).

Règle de lecture : **chaque exigence fonctionnelle est reprise ou justifiée comme déjà couverte ; chaque choix technique ancien est
remplacé par l'équivalent actuel** (ex. « route FastAPI » → outil MCP de département déclaré au manifeste ; « table PostgreSQL » →
registre append-only du département portable SQLite/PostgreSQL ; « n8n » → planificateur durable ; « validation Nathan » → sas
d'approbation de niveau N3+). Les règles d'or du prompt (jamais de faux likes/bots/spam, jamais de dépense sans validation, exactitude
avant vitesse, pas de « terminé » sans preuve) restent valables et sont déjà celles du dépôt.

Fichiers :
- `M2-CRM-REVENUE.md` — condensé fonctionnel du prompt M2 (CRM, Client 360, pipeline, relances, quote-to-cash).
- `M3-ESTIMATION-INTELLIGENCE.md` — condensé fonctionnel du prompt M3 (estimation, vision, mesure, prix, marge, apprentissage).
- `M1-RECEPTION-FRONT-OFFICE.md` — condensé fonctionnel du prompt M1 (réception, adjointe administrative, voix, omnicanal).
- `M7-MARKETING-CROISSANCE.md` — condensé fonctionnel du prompt M7.
- `M9-INTELLIGENCE-STRATEGIQUE.md` — condensé fonctionnel du prompt M9 (direction IA, décisions, scénarios, risques, occasions).
- `M10-MEMOIRE.md` — condensé fonctionnel du prompt M10.
- `M5-FINANCECORE-CFO.md` — condensé fonctionnel du prompt M5 (comptabilité, finance, paie, fiscalité, CFO IA).
- `ANALYSE-M1-M5-M7-M10.md` — (à produire) correspondance exigence → état réel → écart → backlog.

Les autres départements seront ajoutés par Nathan au fur et à mesure (1 ou 2 à la fois).
