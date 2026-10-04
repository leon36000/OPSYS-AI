# Provenance durable des demandes N4 humaines — plan d'audit

Date : 2026-09-30. Audit en lecture seule de `approbations.py`, `capacites.py`, `etat.py`, du schéma
et des tests existants. Aucun code ni contrat partagé n'a été modifié.

## Constat actuel

Le chemin N4 d'une personne authentifiée est déjà borné dans `Capacites._appeler_idempotent` : il
vérifie la portée de l'outil et relit en base que la personne est active et porte encore le rôle du
jeton (`_humain_appareil_cible_valide` → `approbations.signataire_valide`). Il utilise `_meta` MCP,
pas les arguments d'outil, pour reconnaître personne/rôle et reçoit aussi `Meta` (appareil, clé
d'idempotence, horodatage appareil). Il crée ensuite la ligne `approbations` et finalise la réponse
idempotente dans la même transaction SQLite/PostgreSQL.

En revanche, `approbations.creer_demande` ne persiste que niveau, outil, arguments, motif et heure;
le chemin N4 humain lui passe les mêmes informations qu'une demande générique. Il n'écrit aucune
entrée dans `journal`. Après coup, la ligne ne permet donc pas d'établir durablement qui a initié la
demande, sous quel rôle, depuis quel appareil, ni quelle clé de requête l'a créée. L'identité valide
au moment de l'appel est vérifiée, mais cette vérification n'est pas prouvable dans l'audit de création.
Les appels d'agents et les autres demandes génériques sont distincts et ne doivent pas recevoir une
attribution humaine inventée.

Le journal canonique existe déjà (`etat.journaliser`, table `JOURNAL` de la base d'instance) et est
utilisé par les décisions humaines. Il accepte acteur, action, cible et détails JSON. `idempotence`
expose `empreinte_arguments`, empreinte SHA-256 canonique déjà utilisée pour distinguer les arguments
au rejeu. Il n'est pas nécessaire de créer une base ou un journal parallèle.

## Patch minimal proposé pour une phase codable

Ajouter un paramètre interne optionnel de provenance à `approbations.creer_demande` (ou une variante
étroite dédiée) et ne le renseigner que dans la branche `demander_n4_humain` de
`Capacites._appeler_idempotent`, après la validation vivante existante. À la création, écrire dans la
même transaction une entrée canonique `approbation.demander_humain`, avec :

- `par`: identifiant de personne confirmé en base ; `details.role`: rôle de jeton confirmé ;
- `details.appareil` et `details.request_id`: valeurs `Meta` d'origine, jamais tirées des arguments ;
- `cible`: identifiant de la demande ; `details.departement`, `outil`, `niveau` et motif si utile ;
- `details.arguments_sha256`: `idempotence.empreinte_arguments(arguments)`, pas les arguments bruts ;
- horodatage généré côté serveur par `journaliser` (ne pas traiter l'heure d'appareil comme heure fiable).

Cette entrée n'est ni une décision ni une approbation. Elle complète la demande d'agent sans lui
attribuer un acteur humain; les appels génériques gardent leur comportement. Ne pas copier l'empreinte
dans le schéma `approbations` si le journal append-only suffit. Garder les arguments bruts uniquement
dans leur stockage actuel et considérer l'empreinte persistante comme donnée potentiellement
corrélable; aucun champ secret ne doit être ajouté aux détails.

## Atomicité, rejeu et vérifications à coder

La ligne d'approbation, le journal et `idempotence.finaliser` doivent rester dans la transaction
actuelle. Une panne du journal ou avant commit doit annuler les trois; au rejeu, `reclamer` doit rendre
la demande existante sans créer une deuxième ligne d'audit. Une clé réutilisée pour des arguments
différents reste un conflit, sans trace supplémentaire. La personne/rôle viennent du contexte `_meta`
authentifié et revérifié en base dans cette même transaction; aucune nouvelle identité ne doit être
acceptée par le schéma d'outil.

Tests à ajouter ultérieurement, quand le lot partagé sera dégelé :

1. demande N4 humaine : une ligne de demande et une entrée `approbation.demander_humain` avec personne,
   rôle, appareil, request ID, niveau, outil, timestamp serveur et hash vérifiable des arguments; aucune
   valeur brute des arguments sensibles dans le journal ;
2. renvoi idempotent : même demande/réponse et une seule entrée de journal ; clé réutilisée pour une
   autre charge : conflit et aucune nouvelle entrée ;
3. rôle/personne retiré avant création : aucun enregistrement ni entrée de provenance ;
4. panne injectée après insertion de demande/journal et avant commit : nouvelle lecture montre absence
   de demande, d'entrée de journal et de finalisation d'idempotence ; un appel valide ultérieur réussit ;
5. demandes d'agent/génériques et import historique : comportement et provenance inchangés.

## Portée et limites

Ce correctif n'établirait que la provenance de la demande humaine N4 dans le plan de contrôle OPSYS.
Il ne certifierait pas l'identité du détenteur physique de l'appareil au-delà du contrat d'authentification
Core, ni la décision ultérieure du propriétaire, ni l'exécution de l'outil. Il ne requiert pas de
migration de schéma : `JOURNAL` est déjà dans le stockage canonique. À valider avant codage contre les
contrats M2/M3 et les tests ciblés de `test_approbations_appareil.py`, `test_validation_au_depart.py`,
`test_idempotence.py` et `test_approbations_journal.py`.

## Références locales

- [`approbations.py`](../../src/opsys/approbations.py)
- [`capacites.py`](../../src/opsys/capacites.py)
- [`etat.py`](../../src/opsys/etat.py)
- [`idempotence.py`](../../src/opsys/idempotence.py)
- [`IDEMPOTENCE.md`, validation au départ](IDEMPOTENCE.md#8-validation-humaine-au-départ-t14-h)
- [`test_approbations_appareil.py`](../../tests/test_approbations_appareil.py)
- [`test_approbations_journal.py`](../../tests/test_approbations_journal.py)
- [`test_validation_au_depart.py`](../../tests/test_validation_au_depart.py)
- [`test_idempotence.py`](../../tests/test_idempotence.py)
