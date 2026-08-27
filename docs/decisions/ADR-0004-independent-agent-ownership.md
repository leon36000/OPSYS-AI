# ADR-0004 — Équipes indépendantes et ownership explicite (Codex / Claude Code)

Statut: Proposé (directive Nathan appliquée opérationnellement ; enregistrement canon différé — voir « Enregistrement canon » ci-dessous)
Date: 2026-08-26

Origine et traçabilité : ce document est **dérivé** de
`repo-overlay/docs/decisions/ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md` du pack
`OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2`, installé par la mission de l'issue **#563**
(« [OPS] Installer l'overlay de coordination Claude/Codex v1.2 »).

**Il n'en est pas une copie octet-exacte.** Propriété stable, re-mesurable sans citer
aucun commit ni aucune révision :

`diff -u "$OPSYS_PACK/repo-overlay/docs/decisions/ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md" docs/decisions/ADR-0004-independent-agent-ownership.md`

Ce `diff -u` fait autorité sur les écarts réels. Ce qui se dit sans lui : la section
« Décision » ci-dessous est reprise **inchangée** du fichier du pack ; les écarts portent
notamment sur le titre, la ligne `Statut`, ce paragraphe, la section « Supersession
retirée », et des précisions ajoutées dans « Conséquences » et « Enregistrement canon ».
**Aucun décompte de lignes, de sections ou d'écarts n'est figé ici**, pour la même raison
qu'ailleurs dans cette PR : un décompte est une affirmation de plus à maintenir, que la
prochaine édition de ce fichier invalide sans qu'aucune opération Git n'y soit pour rien.

La section « Décision » ci-dessous reprend `CURRENT-NATHAN-DIRECTIVE.md` du même pack
(directive Nathan, fichier hors dépôt) : c'est la pièce vérifiable derrière ces points ;
toute affirmation qui n'y est pas rattachée a été retirée (voir « Supersession retirée »
ci-dessous).

Une version antérieure de ce paragraphe affirmait que ce document était installé
« à l'identique » depuis le pack. C'était faux, et réfutable par le `diff -u` ci-dessus.
La copie installée par le commit `ad38bfd` (porté par la PR #566) est, elle,
octet-identique au fichier du pack — un contenu de commit ne change pas, contrairement à
l'état d'une PR. C'est donc cette PR-ci qui s'écarte du pack, délibérément : d'où un
registre d'écarts renvoyant à une commande, plutôt qu'une affirmation d'identité que rien
ne recensait.

## Décision

- GitHub est la source mutable partagée.
- Codex avance le Core C00–C24.
- Claude Code traite les issues et l'assainissement transversal.
- Exactement un owner par mission.
- Aucune plateforme n'est maître de l'autre.
- Une mise au point courte environ toutes les 24 heures suffit.
- La review croisée est facultative et ciblée.

## Supersession retirée

La version proposée de ce document affirmait remplacer « l'ancien modèle où Claude Code
était maître d'œuvre GitHub global ». **Cette affirmation est retirée** : elle n'était
rattachée à aucune pièce vérifiable — `CURRENT-NATHAN-DIRECTIVE.md` ne la porte pas. Cette
section documente le retrait pour que l'écart reste traçable au lieu de disparaître
silencieusement.

La commande qui interroge l'historique du dépôt sur cette formulation :

`git log origin/main --pickaxe-regex -S'ma.tre.d.(oe|œ)uvre|github global' --oneline -- . \
':!docs/decisions/ADR-0004-independent-agent-ownership.md' \
':!docs/decisions/ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md'`

Deux propriétés de cette formulation, et rien d'autre :

- **L'exclusion de chemin est obligatoire, pas décorative.** Ce document contient lui-même
  la formulation cherchée, pour la citer et la retirer ; son nom de travail avant renommage
  était `ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md`. Sans ces deux exclusions, la commande
  compterait ce document parmi ses propres preuves — et deviendrait non vide dès le merge de
  cette PR, c'est-à-dire au moment exact où un lecteur peut la rejouer.
- **Aucune sortie n'est figée ici, ni SHA de base, ni décompte de commits, ni date de
  mesure.** Une version antérieure de ce paragraphe figeait les trois comme preuve ; la
  première avance de `main` a suffi à les rendre faux, avant même le merge. Ce qui est
  affirmé est la propriété seule : rejouée sur `origin/main`, quelle que soit sa révision,
  cette commande rend une sortie vide — et le reste après un rebase, un squash ou un amend
  de cette branche, comme après le merge. Ce qu'elle établit : **en dehors de la lignée de
  ce document, aucun commit connu du dépôt n'a jamais ajouté ni retiré cette formulation.**

Cette vérification a échoué plusieurs fois avant de tenir, et chaque correction avait
déplacé le défaut au lieu de l'éliminer : d'abord un `git grep` sans révision, qui
n'interroge jamais l'historique ; puis un `git log --pickaxe-regex` correct mais sans
exclure ce document de ses propres preuves ; puis une version antérieure de ce paragraphe,
qui excluait bien ce document mais figeait le résultat sur une révision et un décompte que
la seule avance de `main` suffisait à réfuter. Aucun décompte de ces tentatives n'est retenu
ici : il faudrait le maintenir, et c'est exactement la dette que cette section a pour rôle
de ne pas contracter.

## Conséquences

- moins de coordination;
- queues distinctes;
- branches/worktrees distincts;
- autonomie dans le scope;
- gates proportionnés;
- aucun code métier M avant le handoff Core (`CORE_RC_VERIFIED` et handoff ratifié,
  puis un module à la fois, M7 en premier — `CURRENT-NATHAN-DIRECTIVE.md`).

## Enregistrement canon

**Non fait à ce jour.** La décision doit être enregistrée dans le canon GitHub lors de
la prochaine mise à jour autorisée. Tant que cet enregistrement n'a pas eu lieu, le
statut reste `Proposé` : ne pas lire ce document comme une ratification immuable au sens
d'ADR-0001/ADR-0002/ADR-0003.
