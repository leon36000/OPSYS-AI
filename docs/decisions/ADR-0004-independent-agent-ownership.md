# ADR-0004 — Équipes indépendantes et ownership explicite (Codex / Claude Code)

Statut: Proposé (directive Nathan appliquée opérationnellement ; enregistrement canon différé — voir « Enregistrement canon » ci-dessous)
Date: 2026-08-26

Origine et traçabilité : ce document est installé à l'identique par la mission de
l'issue **#563** (« [OPS] Installer l'overlay de coordination Claude/Codex v1.2 »),
depuis le pack `OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2`. Son contenu reprend
`CURRENT-NATHAN-DIRECTIVE.md` du même pack (directive Nathan, fichier hors dépôt) :
c'est la pièce vérifiable derrière chaque affirmation de ce document ; toute
affirmation qui n'y est pas rattachée a été retirée (voir « Supersession retirée »
ci-dessous).

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
était maître d'œuvre GitHub global ». Une première vérification (revue #1) citait
`git grep -niE "ma.tre.d.(oe|œ)uvre|github global"` « sur l'historique de ce dépôt » :
c'était inexact à double titre — un `git grep` sans révision n'interroge que l'arbre de
travail courant, jamais l'historique, et rejouée telle quelle aujourd'hui cette commande
retourne une correspondance : celle portée par ce paragraphe lui-même, qui cite la
formulation pour la retirer. Ce n'est pas une preuve, dans un sens ou dans l'autre, sur un
modèle antérieur réel.

Cette phrase a déjà été corrigée une fois sans que l'erreur de fond disparaisse — elle a
seulement changé de nature. La revue #1 ci-dessus avait utilisé un `git grep` sans révision,
qui n'interroge jamais l'historique. La correction qui l'a suivie (revue #2) a bien interrogé
l'historique, via `git log --pickaxe-regex` sur `origin/main`, mais sans exclure le chemin de
ce document — qui contient lui-même la formulation cherchée, deux paragraphes plus haut et
juste au-dessus, pour la citer et la retirer. Une commande qui compte ce document parmi ses
propres preuves n'en est pas une : dès le merge de cette PR, `origin/main` porte ce fichier,
et la même commande y trouve alors sa propre trace — la conclusion en gras devenait fausse au
moment exact où un lecteur pouvait la rejouer. La correction n'est donc pas de rejouer la même
commande plus tard, mais d'exclure explicitement le seul endroit ayant légitimement le droit
de porter cette formulation : ce document, et son nom de travail avant renommage,
`ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md`.

`git log origin/main --pickaxe-regex -S'ma.tre.d.(oe|œ)uvre|github global' --oneline -- . \
':!docs/decisions/ADR-0004-independent-agent-ownership.md' \
':!docs/decisions/ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md'`

Rejouée sur `origin/main`, cette commande rend une sortie vide — sans figer ni un SHA de
base, ni un décompte de commits, ni la date à laquelle elle a été rejouée : aucun des trois
n'est la propriété qui compte, et tous changent à chaque avance de `main`. (Une version
antérieure de ce paragraphe figeait les trois — un SHA de base, un décompte de commits et une
date de mesure, présentés comme la preuve — et la toute première avance de `main` qui a suivi
a suffi à rendre les trois faux avant même le merge de cette PR : `origin/main` pointe
aujourd'hui vers un autre SHA, avec un autre décompte, et pointera encore ailleurs demain. Ni
le SHA ni le décompte ne sont repris ici, y compris à titre d'exemple : c'est précisément ce
que ce paragraphe corrige, et les reproduire ne ferait que déplacer le défaut d'une phrase à
l'autre.) Sans l'exclusion de
chemin, la même commande sur `origin/main` est déjà vide aussi tant que cette PR n'est pas
mergée (`origin/main` ne porte encore aucun des deux chemins) : la différence entre les deux
formes n'est donc pas visible avant le merge. Elle l'est sur cette branche, où l'un de ses
commits a introduit la formulation et d'autres — dont celui-ci — l'ont discutée pour la
retirer : sans l'exclusion, ces commits font passer la commande de vide à non vide ; avec
elle, le résultat reste vide — que cette branche compte trois commits ou trente, qu'elle soit
rebasée, squashée ou amendée, et quel que soit ce que `main` accumule pendant ce temps. C'est
cette propriété, et non une révision ou un décompte figés, qui reste vraie après le merge :
**en dehors de la lignée de ce document, aucun commit connu du dépôt n'a jamais ajouté ni
retiré cette formulation.** Le fond de l'affirmation tient donc ; sa méthode de vérification a
échoué trois fois de suite, chaque correction ayant déplacé le défaut sans l'éliminer : une
première fois en cherchant sans révision (`git grep` n'interroge jamais l'historique) ; une
deuxième fois en interrogeant l'historique mais sans exclure ce document de ses propres
preuves ; une troisième fois — ce paragraphe, avant ce commit — en excluant bien ce document
mais en figeant le résultat sur une révision et un décompte que la seule avance de `main`
suffit à réfuter. La condition pour que la vérification tienne cette fois est double :
exclure ce document de ses propres preuves (déjà fait ci-dessus), et n'énoncer que la
propriété — la commande rend une sortie vide sur `origin/main`, quelle que soit sa révision —
jamais une révision ou un décompte précis qui n'en serait qu'une photographie périssable.

L'affirmation n'était de toute façon rattachée à aucune pièce vérifiable et a donc été
retirée plutôt que reformulée — cette section documente le retrait pour que l'écart reste
traçable au lieu de disparaître silencieusement.

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
