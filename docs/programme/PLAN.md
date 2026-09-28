# Plan d'exécution OPSYS-AI

Source du QUOI : [définition produit](../produit/DEFINITION-PRODUIT.md). Décision d'architecture :
[ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md). Mode de travail : [BOUCLE.md](BOUCLE.md).

Règle d'ordre (définition §13 point 6, ADR-0008) : on livre par **tranches verticales rattachées aux
flux de §6**, jamais une couche d'infrastructure sans département qui s'en sert (§14.4).

Légende : `[x]` fait avec preuve · `[ ]` à faire · `BLOQUÉ :` raison · `GATE NATHAN` : décision ou
identifiants du propriétaire, repli livré en attendant.

## T0 — Fondations (le core et le socle, au service de T1)

- [x] T0.1 Définition produit injectée (`docs/produit/`, révision 3 annotée). Preuve : commit du 2026-09-28.
- [x] T0.2 ADR-0008 : fork dur d'OpenClaw, trois couches, points ouverts décidés. Preuve : même commit.
- [ ] T0.3 Audits sans modification M1–M10 (`docs/departements/`) et études R11 (fork), R12 (mobile),
      R13 (socle métier) ; vérifier chaque sortie, puis détailler T1–T4 ci-dessous.
- [ ] T0.4 Import du fork : instantané de `v2026.9.6` (commit `eb377ac5`) dans `core/`,
      `core/NOTICE` (MIT, © OpenClaw Foundation), `core/PROVENANCE.md` ; retrait de `core/UPSTREAM.md`.
- [ ] T0.5 CI du core : job GitHub qui installe Node et pnpm, construit et teste le core tel
      qu'importé (référence verte avant toute modification). En cours : `.github/workflows/core.yml`
      construit d'abord la release amont intacte (Node 24, pnpm 12.4, `pnpm build`, `pnpm test:fast`).
- [ ] T0.6 Élagage selon R11 (canaux et fournisseurs inutiles, docs, apps natives…), CI verte.
- [ ] T0.7 Renommage OpenClaw → OPSYS (CLI `opsys`, `~/.opsys`, paquets, variables, UI), CI verte.
- [ ] T0.8 ADR-0009 socle métier (base de données, événements, workflows à validation humaine,
      RBAC, audit, observabilité) d'après R13.
- [ ] T0.9 ADR-0010 mémoire (RAM par moteur de contexte, M10 gouvernance, RAG d'entreprise)
      d'après l'audit M10.
- [ ] T0.10 Superviseur : le core lance et surveille le moteur métier Python (via `uv`), santé et
      journaux unifiés, une seule authentification.
- [ ] T0.12 M3 : l'outillage de mutation (`tests/outils_preuve/muter_*.py`) travaille sur une copie
      temporaire, jamais sur la vraie source. Une exécution tuée a laissé une mutation dans
      `blocage_prix.py`, restaurée depuis le commit le 2026-09-28.
- [ ] T0.11 Installateur en une commande (dérivé de `install.sh` / `install.ps1`), désinstallation
      et export documentés ; Docker Compose en option serveur.

## T1 — « Travaux terminés » : la chorégraphie centrale (§6, §9.7)

Première tranche métier : elle traverse neuf départements et l'app mobile.

- [ ] T1.0 Persistance des registres des départements : le registre de M2 est une liste en mémoire
      effacée à chaque redémarrage (audit M2). Bloquant de production, traité avec ADR-0009.
- [ ] T1.1 Données et API : jobs et machine à états (M4), sessions de travail et punch (M4.4),
      matériaux prévus et utilisés (M6.10–M6.12), facture brouillon (M5.2), activité client (M2).
- [ ] T1.2 Événements : `job.completed` déclenche la cascade (M6 variance, M5 facture brouillon, M2
      activité et prochaine action, M7 demande d'avis, M3 estimé vs réel, M8 métriques, M10 mémoire).
- [ ] T1.3 Approbations N3–N4 (complétion, facture, écart matériaux), file du propriétaire.
- [ ] T1.4 App mobile Expo : squelette, appairage, profils, punch, chantier du jour, « Terminer »,
      formulaire des matériaux, hors ligne ; approbations côté propriétaire.
- [ ] T1.5 E2E : travaux terminés normaux ; écart de 40 % → `completed_pending_review` et alerte
      sur le mobile de l'admin.

## T2 — Du lead à la soumission (§6, flux principal)

- [ ] T2.1 M1 : intake omnicanal par les canaux du core, qualification, appel manqué.
- [ ] T2.2 M2 : lead structuré, Client 360, préparation à l'estimation, prochaine action.
- [ ] T2.3 M3 : estimation honnête, soumission brouillon, approbation, besoins matériaux vers M6.
- [ ] T2.4 M6 : catalogue, livre de prix, PO brouillon, courriel fournisseur via M1 (repli manuel).

## T3 — Mesure, direction, mémoire

- [ ] T3.1 M8 : registre de métriques, qualité et fraîcheur, alertes qui proposent une action.
- [ ] T3.2 M9 : briefing du matin sourcé, décisions en attente sur mobile.
- [ ] T3.3 M10 : paquets de contexte en couches, consolidation nocturne, audit « non-oubli ».

## T4 — Profondeur des départements

Détaillée à partir des audits (T0.3) : voix M1 par étapes, CFO IA M5, usine à contenu M7, VRP,
météo et GPS M4, vision M3, conseil d'agents M9…

## T5 — Durcissement et SaaS

Secrets chiffrés, RBAC par métrique, Loi 25 (consentements, rétention, export, effacement),
multi-instances, sauvegardes, observabilité, veille de sécurité du fork (mensuelle).

## Décisions attendues de Nathan (GATE NATHAN, ne bloquent pas la boucle)

- Nom commercial : « Gouttières et Revêtements Synergy » ou « … Lanaudière » (définition §13.4).
- Portée SaaS de M5 (§13.8).
- Licence d'OPSYS (`LICENSE` Apache-2.0 ou propriétaire, ADR-0003).
- Identifiants : Twilio, QuickBooks, CCube, Stripe, Plaid, Google (Ads, Search Console, Business
  Profile), Meta, TikTok, LinkedIn, YouTube.
- Rotation de la clé fuitée (#612).
- **Prompts maîtres d'origine des départements** (annexe A de la définition) : ils portent le
  détail fonctionnel (routes, tables, KPI, scénarios de test). Exemple : les 21 sections du rapport
  de décision M9, dont la définition ne liste qu'une douzaine (audit M9).
