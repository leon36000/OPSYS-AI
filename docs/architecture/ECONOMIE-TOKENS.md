# Économie de tokens — mécanismes actuels et consolidation

Révision : 1er octobre 2026. Sources : `src/opsys/{jetons,capacites,modeles,departements,
openclaw,passerelle,admission_agents}.py`, fork `core/`, [recherche core R16](../research/R16-2026-09-30/recherche-core.md),
[ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md) et
[ADR-0012](../decisions/ADR-0012-reutilisation-profondeur-productivite.md).
Le chemin courant choisit les providers natifs par défaut. `openclaw.generer` accepte LiteLLM en
compatibilité explicite (`--mode-fournisseur litellm`); `install/install.sh`,
`install/install.ps1` et `deploy/entrypoint.sh` partent en mode natif. La recherche R3 décrit le
routage historique, pas une décision actuelle d'imposer une gateway. Les tests d'un adaptateur
ne prouvent ni un service fournisseur déployé ni une facture ou un plafond monétaire réel.

## État observé

| Mécanisme | Présent | Limite à traiter |
|---|---|---|
| Déterminisme | Outils métier calculent montants, quantités, dates, scores et validations | Un appel LLM ne doit pas recopier/recalculer un résultat déjà disponible |
| Agents/outils par département | Manifestes, skills et configuration core générée | Plusieurs spécialistes et budgets de rôle à configurer dans le dashboard |
| Sorties bornées | `jetons.tronquer` / `Capacites._tronquer` ; limite par défaut 6 000 caractères, tête/fin et artefact relisible | Des caractères ne sont pas des tokens ; les preuves omises doivent rester référencées et accessibles |
| Compteurs et budgets | `jetons.py` : normalisation, incrément atomique, agrégat exact, état du budget ; `admission_agents.py` : enveloppes et réservations agent/département/entreprise | Les compteurs observés et l'admission pré-appel ne démontrent pas à eux seuls une couverture de tous les appels du core ou fournisseurs |
| Paliers modèles | `modeles.py`, manifestes et console | Attribution statique ne prouve pas un routage qualité/coût efficace |
| Providers natifs | Choix par défaut du générateur et des installateurs | L'usage réel des appels natifs, retries et compaction reste à couvrir/réconcilier selon chaque chemin |
| LiteLLM optionnel | Client de configuration et synchronisation de compteurs dans `passerelle.py`, mode opt-in | Le plafond gateway ne prouve pas un plafond de dépense durable ou une facture réelle |
| Cache fournisseur | Mécanismes hérités du core, préfixes stables des espaces agents | Qualité, taux réel, paramétrage par fournisseur, fraîcheur et permissions à mesurer |
| Compaction | Mécanismes natifs du core ; les agents à profil configurable sont refusés pour la compaction générique tant que son appel fournisseur n'a pas d'admission | Un refus d'admission n'est pas une compaction réussie ni une preuve que son coût est couvert |
| Métriques | Compteurs Python, usage natif et console | Tableau coût/qualité de bout en bout et facturation fournisseur comparable manquent encore |

## Contrat des compteurs et admission actuels

Chaque compteur stocké (`appels`, entrée, sortie et cache lu) est un entier exact dans
`[0, 2^63-1]`. Les booléens, flottants (y compris NaN/inf), chaînes, négatifs et valeurs hors
borne sont refusés avant écriture. Les alias connus des fournisseurs sont conservés; si un alias
est présent, sa valeur doit elle aussi être valide. Un champ absent vaut zéro pour compatibilité,
et `usage=None` est traité comme aucun compteur. Cette convention n'atteste pas que le fournisseur
a fourni le relevé complet ni qu'un zéro représente une vraie consommation nulle.

`enregistrer_usage` additionne les compteurs avec une garde conditionnelle atomique et refuse une
cellule qui dépasserait la borne. Les totaux d'une période sont calculés en entiers Python : ils
peuvent dépasser 64 bits sans débordement; `etat_budget` rend alors toujours le niveau épuisé quand
le total excède le plafond. Une ligne SQL reste, elle, limitée à 64 bits. L'upsert conditionnel
utilise `RETURNING` pour distinguer un refus d'une écriture réussie, sans s'appuyer sur `rowcount`.

La synchronisation LiteLLM transmet les valeurs JSON brutes à cette validation; elle ne les convertit
pas avec `int()` et ne tronque donc pas `1.5` en `1`. Les compteurs manquants y ont encore la valeur
zéro par compatibilité. Tests liés : `tests/test_jetons_i64.py`,
`tests/test_jetons_passerelle_i64.py` et `tests/test_openclaw_passerelle.py` couvrent bornes,
alias, erreurs de types, somme exacte, rollback du lot LiteLLM et budget épuisé en SQLite. La
suite Python référencée ici utilise SQLite; le contrôle séparé PostgreSQL du socle a couvert la
migration des compteurs et la concurrence de l'upsert. Les tests SQLite nommés ne sont pas des
tests PostgreSQL, et aucun de ces contrôles ne prouve une couverture de toutes les voies fournisseur
ou une facture exacte.

L'admission d'agent réserve avant l'exécution des enveloppes de tokens pour les périodes jour/mois
aux niveaux profil-agent, département et entreprise; tours, tentatives/retries et concurrence sont
également limités. La réservation conservée après une exécution de résultat inconnu doit être
rapprochée. Le rapprochement manuel enregistre une déclaration humaine et une référence de relevé,
mais OPSYS ne vérifie pas le relevé externe; il ne faut pas présenter ce total comme vérifié par le
fournisseur. Les tests de ces contrats sont dans `tests/test_admission_agents.py`. L'idempotence du
registre OPSYS n'est pas une garantie `exactly once` d'un effet fournisseur concurrent ou d'une
facturation après crash.

### Réutilisation des transcriptions M1

Le routeur console M1 ne réutilise un résultat STT qu'après acceptation et commit de l'import
canonique M1. Il compare une empreinte opaque de la requête qui couvre l'audio, les localisateurs
(`source`, événement, appel), les consentements fournis à cet upload et la configuration STT.
La clé API contribue au digest final via son SHA-256; ni la clé ni son empreinte isolée ne sont
journalisées. Le registre M1 normalise les localisateurs
`source`/événement/appel avec `strip` avant recherche et écriture; l'empreinte conserve les valeurs
de requête brutes, donc un changement d'espacement peut seulement produire un défaut de cache.
Le consentement à l'enregistrement et, pour un endpoint externe, le consentement au transfert
doivent être présents et accordés pour produire l'empreinte et chercher un résultat. La session
d'administration humaine (owner/admin actif) est relue avant et après la recherche. Le registre
privé conserve les empreintes et le lien vers l'import réussi, pas le média ou le texte transcrit.

Cette réutilisation exacte évite un nouvel appel STT lorsqu'une requête identique est rejouée après
un import accepté. La vérification puis l'appel fournisseur et l'écriture du marqueur ne forment
pas une transaction unique : deux demandes simultanées ou un arrêt avant le marqueur peuvent
relancer STT. Ce n'est pas une garantie `exactly once` concurrente ou après crash. Sources et tests
: `src/opsys/console/voicemail_ui.py`,
`departments/m01-front-office/src/m1_front_office/{voicemail_stt,outils}.py`,
`tests/test_console_voicemail_upload.py` et
`departments/m01-front-office/tests/test_voicemail_stt.py`.

## Ordre d'optimisation

1. **Éviter l'appel inutile.** Réception, normalisation, déduplication, calcul, catalogue, règles,
   lookup exact et rapports structurés sont exécutés par code. L'agent traite l'incertitude ou
   l'explication demandée ; un cron ne démarre pas dix conversations pour constater zéro changement.
2. **Composer les outils.** Un outil métier peut récupérer, calculer et rendre un résultat sourcé
   en une fois. Séparer les commandes à effet de bord et leurs approbations ; ne pas transformer
   l'outil composé en permission universelle.
3. **Réutiliser le travail.** Résultat lié à objet/source/version/configuration, avec invalidation
   et durée de validité. Le cache est isolé par instance, domaine, principal et portée autorisée.
   Ne jamais réutiliser un ancien verdict financier, consentement ou droit vivant par similarité.
4. **Récupérer le contexte utile.** Recherche autorisée avant lecture, couche must-know réservée,
   sources consultables ensuite, seuls outils de la tâche exposés. Données rappelées et instructions
   restent distinctes ; un texte RAG ne peut octroyer des permissions.
5. **Adapter le modèle.** Modèle rapide/local pour une tâche évaluée simple, plus fort pour un
   raisonnement qui le justifie ; escalade sur échec/confiance insuffisante. Ne pas changer de
   modèle constamment dans une session et détruire le cache. Les données sensibles suivent leur
   politique d'egress, même si le modèle cloud serait moins cher.
6. **Borner l'exécution.** Budget, sortie maximale, tours, retries, durée et concurrence. Un
   spécialiste est invoqué sur un besoin ; pas de débat ou consensus permanent entre modèles.
7. **Mesurer avant ajout de brique.** Une seconde gateway, un compresseur ou un graphe ajoute
   maintenance, mémoire/RAM et appels. Adopter seulement après un parcours comparatif concluant.

## Frontière avant l'appel fournisseur et cible restante

`admission_agents.reserver` réserve actuellement une enveloppe avant les cycles du runtime qui
l'appellent. Les niveaux profil-agent, département et entreprise ont des budgets jour/mois; le
chemin tient aussi compte des tours, retries et appels concurrents. La limite est donc effective
sur ce chemin testé, pas automatiquement sur tous les usages ou tous les chemins du Core.

R16 reste la cible d'extension : démontrer la couverture de chaque provider natif, des appels
imbriqués, retries, résumés et compaction, ainsi que le rapprochement après succès, erreur et
timeout/crash. La compaction générique est actuellement refusée pour les agents à profil configurable
car son appel fournisseur distinct n'est pas relié à l'admission runtime. Ce refus est codé dans
`core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts` et couvert par
`core/src/agents/embedded-agent-runner/opsys-runtime-admission.test.ts`; il ne vaut ni compaction
accomplie ni couverture budgétaire réussie. Le traitement des réservations inconnues et le
rapprochement manuel sont décrits dans la section précédente.

Le budget de tokens ne vaut pas budget dollars. Sans relevé de prix et d'usage fournisseur
complet, le coût reste inconnu; un compteur cache-read ou une baisse de tokens ne certifie pas une
économie en dollars. Les profils et plafonds de tokens actuels ne prouvent donc ni un coût total
par rôle/modèle, ni l'inclusion des coûts de compaction et des voies encore non instrumentées.

## Dashboard cible

Configuration par département et rôle : modèle/palier/repli, tools et scope, budget jour/mois,
limites de contexte/sortie/tours/retries/concurrence, événements et planning, alertes/arrêt/escalade.
La console des profils d'agents et son contrôle DON-01 sont corrigés localement; le
[registre d'audit](../programme/REGISTRE-AUDIT-2026-09-30.md) marque ce constat « CORRIGÉ LOCAL ».
La cible produit de configuration par rôle et de couverture de toutes les voies reste plus large
que les enveloppes profil-agent/département/entreprise actuellement admises.

Mesures par flux : appels, tokens entrée/sortie/cache, coûts estimés/réels/inconnus, appels évités,
réservations, refus budget, retries, latence p50/p95, couverture de sources, réussite métier,
corrections humaines. Le résultat d'un outil et l'usage du fournisseur ont une corrélation commune.

## Briques à examiner

- **Hermes** : contrats mémoire/context engine, compaction, skills et cycle de sous-agents ;
  ingrédients précis sous MIT, pas une deuxième boucle d'agents obligatoire.
- **Agent Skills** : format commun des procédures, sélection pertinente ; texte du skill relu,
  capacité attribuée par serveur, aucune permission ajoutée par le document.
- **lossless-claw** : compaction et références persistantes à mesurer ; conflit avec le slot de
  contexte OPSYS à résoudre par extraction/adaptation, jamais installation aveugle simultanée.
- **LangMem/QMD** : mémoire procédurale ou recherche documentaire locale en banc isolé ; pas canon
  métier automatique ni installation d'un modèle lourd par défaut sur petit VPS.
- **Bifrost/LiteLLM** : gateway optionnelle selon besoin mesuré ; une limite déclarée ne vaut
  garantie concurrente/durable de dépense. Pas d'ajout de process sans gain établi.

Les licences, commits, interfaces et contre-indications figurent dans R16. TensorZero est archivé
au moment de la recherche : ne pas le proposer comme nouvelle passerelle par défaut.

## Validation de l'économie

Banc reproductible : intake soumission, estimation, chantier terminé, facture/AP, contenu marketing,
question CFO et rappel mémoire. Pour chacun : même données autorisées, mêmes sorties attendues et
cas négatifs, comparaison avec mécanisme désactivé, preuve de coût fournisseur ou statut inconnu.
Tester limite avant appel, deux appels concurrents, retry, crash, compaction, sous-agent, fournisseur
sans usage, cache expiré, changement de permission et séparation client A/B. Qualité métier et
confidentialité doivent rester au moins au niveau de la référence.

Aucun objectif d'économie chiffré n'est annoncé avant ce banc. Les tests techniques ne deviennent
pas une garantie de facture fournisseur, et un benchmark public n'est pas un résultat OPSYS.
