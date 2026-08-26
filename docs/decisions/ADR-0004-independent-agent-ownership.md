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

Vérification réellement rejouée sur l'historique du tronc :
`git log origin/main --pickaxe-regex -S'ma.tre.d.(oe|œ)uvre|github global' --oneline`
→ sortie vide (810 commits parcourus sur `origin/main`, aucune correspondance) : **aucun
commit du tronc n'a jamais ajouté ni retiré cette formulation.** Le fond de l'affirmation
tient donc, sur cette base ; sa méthode de vérification initiale ne tenait pas.
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
