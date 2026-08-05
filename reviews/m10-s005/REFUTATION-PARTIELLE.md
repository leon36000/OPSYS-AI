# Round 1 — objection CRITIQUE de Qwen3.7-Max : fondée sur le fond, inexacte sur l'exemple

APPROVE 2/3 (DeepSeek-V4-Pro, Gemini-3.1-Pro) · REJECT 1/3 (Qwen3.7-Max, 1 objection critique).

## L'objection, verbatim

> « La vérification de `hash_tete` compare la valeur à l'ensemble des `ligne_id` du registre
> (`reference["hash_tete"] not in ligne_ids`). Cela indique que `hash_tete` est traité comme un
> simple `ligne_id` et non comme un hash cryptographique de la tête de chaîne. Par conséquent,
> l'intégrité du registre n'est pas vérifiée (le contenu de la tête pourrait être altéré sans
> invalider la référence) […] De plus, si `registre_cible.tete()` retournait un véritable hash,
> cette condition échouerait systématiquement. »

## Ce qui est FONDÉ — confirmé PAR MESURE, corrigé

Le cœur de l'objection est juste : **`verifier_reference` ne vérifiait pas l'intégrité de la
chaîne**. Reproduit avant correction :

```
=== AVANT falsification ===
  verifier_reference : (True, None)
  valider_chaine     : (True, '')
=== APRES falsification du CONTENU de la tete (r._chain[-1]["valeur"] = "FALSIFIEE") ===
  verifier_reference : (True, None)      <-- FAUX FEU VERT
  valider_chaine     : (False, 'maillon invalide : 89a9bdba…')
```

Une référence `memoire_m10` servie à M9 sur un registre corrompu aurait donc été validée. C'est
exactement le contraire de l'objectif annoncé (« rendre la référence réellement vérifiable plutôt
que déclarative »).

**Correction appliquée**, avec témoin RED d'abord :
`test_verifier_reference_rejette_une_reference_sur_une_chaine_falsifiee` a été écrit et vérifié
ROUGE (`assert True is False`) AVANT toute modification du code de production. `verifier_reference`
appelle désormais `registre_cible.valider_chaine()` en PREMIER et retourne le nouveau verdict
`REJ-REFERENCE-CHAINE-INVALIDE` si la chaîne est rompue. 139/139 verts après correction.

## Ce qui est INEXACT dans l'exemple — mesuré, non appliqué

Deux affirmations de l'objection sont fausses sur les faits, et les suivre aurait dégradé le code :

1. **« `hash_tete` est traité comme un simple `ligne_id` et non comme un hash cryptographique »**
   — `ligne_id` **EST** un hash cryptographique. Mesuré,
   `m10_memoire/registre.py:50` : `ligne_id = encodage.empreinte(entree_copy, precedent)`, et
   `encodage.empreinte` retourne un `hashlib.sha256(...).hexdigest()`. Les deux ne sont pas des
   objets différents : `tete()` retourne le `ligne_id` du dernier maillon, qui est le sha256 de son
   contenu chaîné au précédent.

2. **« si `registre_cible.tete()` retournait un véritable hash, cette condition échouerait
   systématiquement »** — faux : `tete()` retourne précisément ce hash, et la condition passe
   (139 tests verts, dont ceux de référence légitime). L'affirmation présuppose la distinction
   réfutée au point 1.

## Pourquoi les deux points comptent

Corriger « la classe » (trou d'intégrité réel) sans adopter « l'exemple » (nature supposée de
`hash_tete`) — patron déjà rencontré plusieurs fois dans ce dépôt : *une objection peut être fondée
en classe et fausse en exemple*. Avoir appliqué l'exemple tel quel (remplacer `tete()` par un
« vrai hash » distinct du `ligne_id`) aurait dupliqué un condensat déjà existant, sans rien
ajouter à la sécurité.

## Suite

Round 1 non unanime → **le trio COMPLET est relancé sur le code corrigé**, jamais une reprise
partielle : le sceau `prompt_sha256` couvre tout le prompt (pack + mémoire d'équipe), une relance
partielle produirait des sceaux distincts et un tally invalide.
