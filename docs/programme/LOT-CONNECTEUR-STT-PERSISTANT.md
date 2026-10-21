# Connecteur STT M1 : configuration durable et consommation réelle

Mandat du 1er octobre 2026, heure de Toronto. Cette tranche poursuit le lot 2 du plan de reprise.
Le prompt retrouvé est conservé exactement dans [la pièce reçue](../produit/PROMPT-NATHAN-RECUPERE-2026-10-01.txt).
Les exigences M1/M5/M7/M10 et la vision d'ensemble restent applicables.

## Résultat attendu

Depuis Connecteurs, un propriétaire/administrateur humain peut déclarer les références des
variables serveur pour STT, enregistrer une révision persistante, la valider localement et
demander le diagnostic indicatif GET `/models` existant. La transcription M1 réelle consomme
cette configuration : aucune écriture globale dans `os.environ`, aucun deuxième client STT.
Les valeurs des secrets et endpoints restent hors HTML/JSON/journal/historique.
Les références nommées sont les seuls paramètres persistés dans cette tranche.

## Interfaces et invariants

- Connecteur pris en charge : `stt-m1`. Les trois autres entrées restent au stade catalogue;
  toute tentative d'écriture d'un autre identifiant est refusée.
- Configuration : `actif` booléen, `references` objet fermé avec `url`, `modele`, `cle`, `local`,
  `delai_s`; chaque valeur fournie est un nom de variable `[A-Z][A-Z0-9_]{0,127}`. `url` et
  `modele` sont requis; les champs optionnels absents restent absents, sans clé inventée.
  Références non résolues autorisées à l'enregistrement, annoncées comme incomplètes.
- PUT `/api/connecteurs/stt-m1/configuration` : objet fermé `actif`, `references`,
  `revision_attendue` entier ≥0, `mutation_id` identifiant borné. Persistance SQLAlchemy
  et migration Alembic **0016**, `down_revision=0015` (la migration 0015 existe déjà).
  Auteur issu de l'identité active, jamais du payload. Historique et journal sans valeurs.
- POST `/api/connecteurs/stt-m1/diagnostic` : acte manuel privé avec CSRF; configuration et
  révision explicites. GET `/models` réutilise `ConfigurationSTT.verifier_connexion`; délai
  diagnostic plafonné à 5 secondes, réponse bornée et redirections refusées. Ne transmet
  aucun audio/document. Refuser les diagnostics concurrents et éviter une répétition réseau
  du même identifiant déjà terminé; interruption/crash ne bloque pas définitivement les reprises.
- Au retour du réseau, revalider identité et révision avant réponse/enregistrement. Une
  observation d'une ancienne révision ne valide jamais une nouvelle configuration.
- Le résultat normalisé garde seulement statut indicatif, date/révision et `stt_verifie=false`.
  HTTP joignable ne prouve pas authentification, modèle ou transcription réussis.
- GET existants restent sans appel réseau. L'interface distingue présence, validation locale
  et dernière observation distante. Fournir les formulaires avec CSRF et un retour utile.
- `ConfigurationSTT.depuis_env(environ=...)` conserve son comportement explicite actuel.
  Sans argument, réutiliser une projection des références persistées vers les constantes
  existantes; en absence de ligne, conserver les anciennes variables. Une configuration
  désactivée ne retombe jamais sur le fournisseur historique. Une référence requise manquante
  dans une configuration active ne déclenche aucun appel réseau.

## Risques et preuves

Respecter session actuelle admin/owner et CSRF pour chaque écriture; contrôler les droits dans
la transaction qui persiste le changement, puis avant réponse. Révision attendue pour éviter
l'écrasement concurrent; mutation identique rejouée sans nouvelle ligne, payload différent refusé.
Les references sont des noms de variables, pas un coffre ni un stockage de jetons.
Utiliser la configuration explicitement choisie par l'administrateur; les politiques audio et
consentements M1 restent appliqués. Aucun appel fournisseur réel dans les vérifications du cloud.

Tests : routes absentes avant changement; migration/base existante et reprise; références et
payloads invalides, session/role/CSRF refusés, retrait de rôle, idempotence et conflit de révision;
configuration réouverte dans une nouvelle connexion/processus; environnement jamais modifié;
consommation STT persistée, repli historique et désactivation; diagnostic réseau factice borné,
redirection/erreur/no-secret, révision remplacée pendant diagnostic et concurrence/reprise.
Rerun ciblé console/STT/stockage puis intégration proportionnée sur l'état final; aucune promotion
globale des quatre connecteurs ni déclaration d'intégration fournisseur réelle.

## Propriété des modifications

Un seul agent écrit le code de cette tranche : `src/opsys/connecteurs.py`, tables/migration,
`console/connecteurs_ui.py`, montage dans `application.py`, raccord STT et tests associés.
Le chef de projet conserve le prompt, les décisions, les preuves intégrées et les documents.
Diff initial et préimages ciblées avant changement; pas de commit/push, installation ou déploiement.
