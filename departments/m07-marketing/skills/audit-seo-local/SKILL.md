---
name: audit-seo-local
description: À utiliser pour contrôler les règles locales SEO et AEO d'une page de l'entreprise, en distinguant structure HTML et preuve de visibilité externe.
---

# Auditer le SEO et l'AEO local

1. Identifie le dossier local et sa source. Appelle `m7_auditer_seo_site(site_dir)` avec le
   chemin fourni ; son défaut est le site généré du département, pas une preuve du site client
   en ligne. Lis le `resume` :
   `regles_ko` doit être 0 avant de continuer. Si non, liste les `verdicts` en échec (title,
   meta_description, lang_fr, h1_unique, json_ld_valide, script_externe, robots_crawlable) et
   ce qu'il faut corriger — ne propose jamais toi-même une correction de contenu sans le dire
   explicitement au propriétaire du site.
2. Appelle `m7_evaluer_aeo` avec le `html_path` de la page examinée et un `timestamp` ISO 8601
   réel (jamais inventé). Sans `html_path`, le défaut est le site du département. Lis
   `surface_reports` pour les trois surfaces (`google_aio`, `perplexity`, `assistants_ia`) :
   - `A-08` (NAP LocalBusiness, surface perplexity) : le `@type` schema.org doit être
     `HomeAndConstructionBusiness` (ou un autre sous-type de `LocalBusiness`) — jamais
     `Organization` seul pour cette règle locale. Ce constat de structure ne prouve ni présence
     ni absence de la fiche chez Google ou les assistants IA.
   - `A-09` (fraîcheur) : signale toute page dont la date dépasse 12 mois.
   - `A-06`/`A-07` (statistiques et citations) : une statistique chiffrée sans source
     (`data-source`) est `candidat_a_verifier`, pas une conformité acquise.
3. Une règle `non_conforme` n'est jamais silencieuse : rapporte-la telle quelle avec sa
   `measured_fact`, et propose l'action corrective précise (jamais une réécriture inventée du
   contenu réel de l'entreprise).
4. Restitue la page/source contrôlée, la date, les règles conformes ou à corriger et leurs limites.
   Si les deux audits sont propres, indique « contrôles locaux SEO/AEO passés ». L'indexation,
   les impressions, le classement et la visibilité réelle restent inconnus sans données externes
   qualifiées. La publication exige encore validation humaine et contrôles marque, confidentialité
   et contenu ; un audit local vert n'est pas une autorisation de publier.
