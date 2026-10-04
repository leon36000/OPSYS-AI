# Fusion — avancement personnel des imports M03

Le 4 octobre 2026, la synthèse Fusion montre les manifestes privés d'import M03 en
plus des sources déjà admises. Un lot interrompu reste visible par ses emplacements
ATTENTE, RECU, INDEXE et actifs. Le hub et la synthèse donnent accès à « Mes imports »
pour retrouver ou reprendre le lot. **M10 et OPSYS-AI restent PARTIELS.**

## Changement et périmètre

Le [design préalable](M10-FUSION-IMPORTS-DESIGN-2026-10-04.md) réutilise la projection
`IngestionProcedures.lister_lots(auteur=identité serveur)`. Aucune table, copie de
corps, extraction, indexation, activation ou génération supplémentaire. La carte
personnelle est séparée des séries/versions partagées et des filières financières
CSV/PDF/AP. Les observations portent sur des magasins et instants distincts; elles
ne sont ni additionnées ni présentées comme un snapshot global atomique.

Fichiers : `src/opsys/console/fusion_synthese.py`, `fusion_pdf_ui.py` (hub seulement)
et `tests/test_console_fusion_synthese.py`. Routes existantes :
`GET /fusion`, `GET /fusion-operationnelle/synthese`; reprise existante via
`/memoire/procedures/imports`. Aucun nouveau contrat MCP ou endpoint d'écriture.

## Contrôles et résultat observable

- Identité issue de la session, filtre propriétaire dans la lecture existante,
  revalidation de l'autorité avant/après les sources et avant réponse.
- Une révocation ou erreur de permissions refuse l'écran avec 403. Les paramètres
  inconnus sont refusés avant lecture; la réponse reste `private, no-store`.
- Au plus 64 lots, références uniques SHA-256, 1–5 emplacements, entiers non négatifs,
  somme ATTENTE + RECU + INDEXE exacte et actifs <= INDEXE. Une projection incohérente
  ou une panne produit « indisponible », jamais un compteur zéro inventé.
- Aucun titre, référence, hash de document, corps ou détail d'exception dans cette
  carte. Elle compte des étapes techniques, pas des documents validés ni une note
  de connaissance, de qualité, de rappel ou d'assimilation de l'entreprise.

Le parcours PostgreSQL crée un manifeste partiel et un autre auteur. Deux sessions
HTTP lisent leurs propres nombres; une version indexée puis activée change les
compteurs, l'arrivée du dernier fichier supprime ATTENTE, et l'oubli de la série
retire le manifeste concerné. Aucun index ou activation n'est déclenché par la vue.

## Preuves ROOT et reprises conservées

| Essai | Résultat |
|---|---|
| r110 | Ruff rouge sur une ligne de constante de 122 caractères. La mise en forme corrigée conserve exactement l'AST; pytest n'a pas été lancé. |
| r111 | Ruff vert, 126/127 tests réussis. La fixture demandait une activation avec version attendue `None` alors qu'une base était active : le CAS de production a correctement refusé. |
| r112 | **127/127 réussis**, dix fichiers complets, zéro échec/erreur/skip. La fixture utilise le SHA réel de la base et garde une assertion explicite de refus pour l'attente erronée. Aucun garde de production assoupli. |

La campagne r112 comprend les 95 cas Mes imports et les 32 cas de synthèse (unitaires,
HTTP et deux parcours PostgreSQL). Ces sous-comptes sont inclus dans 127; ils ne
s'ajoutent pas aux anciennes campagnes. Elle dure 54,774 s sous le harnais ROOT,
avec 1 226 empreintes sources identiques avant/après, sans OOM, garde déclenchée ni
survivant du run. Ruff couvre les fichiers de code concernés et les régressions.
Les jeux et identités sont fictifs; le test de pagination existant garde 51 séries
et 52 versions. La sandbox PDF n'a pas changé et conserve ses preuves natives distinctes.

Reçus, JUnit, logs, drivers, gels, revue et patchs r1/r2 :
[capsule immuable](../../research/REPRISE-2026-10-04/preuves/M10-FUSION-IMPORTS-r1.tar.xz)
et [inventaire avec empreintes](../../research/REPRISE-2026-10-04/preuves/M10-FUSION-IMPORTS-r1.json).
Le contrôle Gitleaks conserve une alerte brute `generic-api-key` sur le mot de passe
fictif de la fixture HTTP, déjà présent dans le parent publié. ROOT compare la ligne
et ses empreintes et vérifie son usage limité aux identités de test locales. Aucun
secret réel identifié dans cette portée; aucune règle, exclusion ou baseline ajoutée.
Le reçu brut rouge et la classification restent distincts, sans verdict global
« zéro alerte ». La capsule inclut les deux et le relevé final sur les sources publiées.

## Limites et suite

Procédures internes M03 TXT/MD seulement. Pas d'OCR, ingestion client universelle,
classement général, corpus représentatif, apprentissage automatique, activation
automatique ni note d'assimilation validée. Les accès des filières financières
partagées gardent leur propre périmètre. La réussite locale n'anticipe pas les
résultats de CI du prochain commit; ceux-ci sont suivis dans la PR #623.
