# M7-S010 — Competitive Engine (snapshots locaux, verdicts par règle)

## Manifeste
story_id M7-S010 · T2 · allowed: src/competitive/, tests/, fixtures/concurrents/ · deps: M7-S003 ·
touches_ledger: false · zéro réseau (Cloudflare bloque les bots IA — crawl réel différé T3).

## Critères d'acceptation (testables)
1. Fixtures LOCALES 100 % fictives (meta.yaml `fictif: true` OBLIGATOIRE — refus de charger sinon,
   prouvé par test) et anonymes (domaines .example) : fort / faible / casse (ce dernier volontairement
   mal formé pour prouver parse_error=KO).
2. Verdicts PAR RÈGLE C-01..C-07 (title, meta description, h1 unique, schema.org, maillage ≥3,
   robots anti-bots-IA, sitemap bien formé) + C-08 couverture thématique (Jaccard sur mots
   significatifs, stopwords fichier, textes bruts) — JAMAIS de score agrégé (REJ-0040, vérifié par
   test « aucune sous-chaîne score »).
3. parse_error → verdict KO explicite (jamais avalé), prouvé sur la fixture cassée.
4. Rapport DÉTERMINISTE (timestamp fourni par l'appelant ; double appel = dicts identiques, testé).
5. Zéro réseau : sources des 4 modules sans urllib/socket/http.client/requests (test getsource).
6. Comparaison vs NOTRE site réel (src/site/static/index.html de main).

## Pipeline
ADR MiMo-Pro-V2 seconde passe (incident passe 1 = code → rejetée, journalisé ; Kimi-K3 vide ×3) ·
tests DeepSeek (RED collecte capturé) · fixtures DeepSeek (Kimi-2.7 HTTP 401) · impl DeepSeek ·
alignements impl→tests (les tests sont la spec) · revue trio Gemini/MiniMax/Qwen (≠ codeur deepseek,
≠ architecte xiaomi) · merge auto gates verts (délégation Nathan 2026-07-25).
