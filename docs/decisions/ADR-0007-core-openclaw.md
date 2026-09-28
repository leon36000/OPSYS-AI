# ADR-0007 — OPSYS-CORE bâti sur OpenClaw (remplace le choix Hermes de l'ADR-0006)

- Statut : **Accepté** (chef de projet, sur objection argumentée du propriétaire, 2026-09-28)
- Remplace : le point 1 de l'ADR-0006 (« OPSYS-CORE = Hermes Agent »). Le reste de l'ADR-0006
  reste en vigueur : départements, règle d'or, politiques, économie de tokens, déploiement,
  méthode allégée.

## Contexte

L'ADR-0006 avait retenu Hermes Agent pour deux raisons :
- il est écrit en Python, comme le code métier ;
- son dashboard est extensible sans fork.

Le propriétaire a objecté avec deux faits, vérifiés le 2026-09-28 dans le code d'OpenClaw
v2026.9.6.

### Mémoire

`docs/concepts/memory-architecture.md` décrit :
- des paliers de mémoire : instructions, noyau curé, épisodique, prospective, revue ;
- une **provenance** fermée : owner, agent, untrusted, system ;
- une consolidation « dreaming » à portes déterministes ;
- un rappel à deux voies, dont une sans aucun appel de modèle ;
- des intentions permanentes ;
- la purge de bout en bout d'une personne ou d'une source, utile pour la Loi 25 ;
- des mécanismes anti-empoisonnement au moment de l'écriture.

C'est supérieur à la mémoire de Hermes (plein texte + curation + plugins). Le principe « portes
déterministes, jugement du modèle à l'intérieur » est exactement la règle d'or d'OPSYS.

### Mobile

`apps/ios`, `apps/android` et Wear OS sont des applications **officielles**, publiées sur l'App
Store et Google Play. Elles offrent chat, voix, **approbations**, photo et vidéo, localisation et
SMS. Ce sont exactement les besoins terrain d'OPSYS :
- photos de chantier pour M3 ;
- pointage géolocalisé pour M4 ;
- approbations du patron ;
- voix pour M1.

Hermes n'a pas d'application mobile.

L'argument « même langage » ne tient plus : les départements sont exposés en **MCP**, protocole
qu'OpenClaw supporte nativement (stdio et streamable HTTP). Le langage du Core n'a donc plus
d'impact sur le métier.

## Décision

1. **OPSYS-CORE = OpenClaw épinglé.** Release `v2026.9.6` (commit `ce5bbdc2`), image
   `ghcr.io/openclaw/openclaw:2026.9.6@sha256:0a5ff5e6…`. Aucun fork profond : on passe par les
   interfaces publiques. Voir `core/UPSTREAM.md`.
2. **Départements = agents OpenClaw** générés par `opsys openclaw configurer`. Chacun reçoit :
   - un espace de travail (`SOUL.md`, `AGENTS.md`, `skills/`) ;
   - un fournisseur de modèles dédié ;
   - des automatisations.
   Ces fragments sont inclus par `$include`, ce qui laisse la configuration de l'utilisateur
   intacte.
3. **Capacités.** Serveur MCP OPSYS en streamable HTTP, protégé par jeton, sur le réseau interne.
   Politiques d'autonomie, approbations, troncature et garde budgétaire restent côté OPSYS : elles
   ne dépendent pas du runtime.
4. **Modèles et budgets.** LiteLLM devient la passerelle **par défaut** :
   - les paliers OPSYS deviennent des alias (`opsys-rapide`, etc.) ;
   - chaque département a une clé virtuelle avec un plafond de tokens par jour (`tpd_limit`), et
     optionnellement un budget en dollars sur 30 jours.
5. **Mémoire à deux couches :**
   - mémoire d'agent native d'OpenClaw (personnes, préférences, épisodes) ;
   - base de connaissances d'entreprise OPSYS (PostgreSQL + pgvector) exposée en MCP.
   Voir `docs/memory/RAG-PREMIUM.md`.
6. **Interfaces.**
   - Control UI d'OpenClaw pour les agents, les canaux et les sessions.
   - **Console OPSYS** pour les départements, les approbations, les budgets et les modèles.
7. **Mobile**, détaillé dans `docs/architecture/MOBILE.md` :
   - phase 1 : les apps officielles OpenClaw appairées à la passerelle OPSYS ;
   - phase 2 : fork rebrandé de `apps/ios` et `apps/android`, avec des écrans par département.
   La publication sur les stores est une frontière humaine (T3).
8. **Hermes devient un runtime alternatif.** Le serveur MCP fonctionne aussi en stdio ;
   `src/opsys/hermes_plugin.py` et `profils.py` sont conservés, testés et optionnels.

## Conséquences

- On garde tout le travail métier et le socle MCP. Les adaptateurs propres à Hermes ne sont plus
  le chemin principal.
- La sécurité est un point de vigilance, car OpenClaw a eu en 2026 la CVE-2026-25253 (corrigée) et
  la campagne ClawHavoc (skills malveillantes). Réponses :
  - version épinglée ;
  - **aucune installation automatique depuis ClawHub** ;
  - authentification obligatoire de la passerelle ;
  - sandbox des sessions non principales.
- OpenClaw est mono-tenant : une installation = une entreprise = un VPS, comme prévu.
- À valider sur un vrai VPS, car ce bac à sable interdit d'exécuter le code amont :
  - chargement des `$include` ;
  - découverte des outils MCP ;
  - restriction des outils par agent ;
  - automatisations ;
  - appairage des apps mobiles.
