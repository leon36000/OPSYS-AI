---
name: audit-seo-local
description: Procédure pour auditer la conformité SEO et AEO (visibilité IA) du site de l'entreprise avant d'affirmer qu'une page est prête à publier.
---

# Auditer le SEO et l'AEO local

1. Appelle `m7_auditer_seo_site` (défaut : le site généré du département). Lis le `resume` :
   `regles_ko` doit être 0 avant de continuer. Si non, liste les `verdicts` en échec (title,
   meta_description, lang_fr, h1_unique, json_ld_valide, script_externe, robots_crawlable) et
   ce qu'il faut corriger — ne propose jamais toi-même une correction de contenu sans le dire
   explicitement au propriétaire du site.
2. Appelle `m7_evaluer_aeo` avec un `timestamp` ISO 8601 réel (jamais inventé). Lis
   `surface_reports` pour les trois surfaces (`google_aio`, `perplexity`, `assistants_ia`) :
   - `A-08` (NAP LocalBusiness, surface perplexity) : le `@type` schema.org doit être
     `HomeAndConstructionBusiness` (ou un autre sous-type de `LocalBusiness`) — jamais
     `Organization` seul, sinon la fiche est invisible pour les assistants IA.
   - `A-09` (fraîcheur) : signale toute page dont la date dépasse 12 mois.
   - `A-06`/`A-07` (statistiques et citations) : une statistique chiffrée sans source
     (`data-source`) est `candidat_a_verifier`, pas une conformité acquise.
3. Une règle `non_conforme` n'est jamais silencieuse : rapporte-la telle quelle avec sa
   `measured_fact`, et propose l'action corrective précise (jamais une réécriture inventée du
   contenu réel de l'entreprise).
4. Ne conclus « le site est prêt » que si les DEUX audits (SEO technique et AEO) sont propres.
