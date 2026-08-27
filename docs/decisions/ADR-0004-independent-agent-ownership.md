# ADR-0004 — Équipes indépendantes et ownership explicite (Codex / Claude Code)

Statut: Proposé (directive Nathan appliquée opérationnellement ; enregistrement canon différé — voir « Enregistrement canon » ci-dessous)
Date: 2026-08-26

Origine et traçabilité : ce document est **dérivé** de
`repo-overlay/docs/decisions/ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md` du pack
`OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2`, installé par la mission de l'issue **#563**.
Le titre et l'énoncé de cette issue ne sont pas recopiés ici — ils se modifient sur GitHub
sans que ce fichier en sache rien ; `gh issue view 563` fait foi.

**Il n'en est pas une copie octet-exacte.** Propriété stable, re-mesurable sans citer
aucun commit ni aucune révision — **contre le pack v1.2 spécifiquement**, celui dont ce
document est dérivé : le pack `OPSYS-AI-CLAUDE-ISSUES-AUTONOMOUS-v1.4`, devenu la référence
courante ailleurs dans cette PR, n'a plus ni `repo-overlay/`, ni aucun ADR, et ne peut donc
pas servir à cette comparaison-ci :

`diff -u "$OPSYS_PACK_V1_2/repo-overlay/docs/decisions/ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md" docs/decisions/ADR-0004-independent-agent-ownership.md`

où `$OPSYS_PACK_V1_2` désigne le répertoire où le pack `OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2`
(et lui seul) a été dépaqueté. Ce `diff -u` fait autorité sur les écarts réels. Ce qui se dit sans lui : la section
« Décision » ci-dessous est reprise **inchangée** du fichier du pack ; les écarts portent
notamment sur le titre, la ligne `Statut`, ce paragraphe, la section « Supersession
retirée », et des précisions ajoutées dans « Conséquences » et « Enregistrement canon ».
**Aucun décompte de lignes, de sections ou d'écarts n'est figé ici**, pour la même raison
qu'ailleurs dans cette PR : un décompte est une affirmation de plus à maintenir, que la
prochaine édition de ce fichier invalide sans qu'aucune opération Git n'y soit pour rien.

La section « Décision » ci-dessous n'a **pas** été réécrite au regard d'une pièce
justificative : elle est reprise inchangée du fichier du pack, et c'est le `diff -u`
ci-dessus qui le fait voir. `CURRENT-NATHAN-DIRECTIVE.md` du même pack (directive Nathan,
fichier hors dépôt) étaye **une partie** de ses puces, pas leur totalité — la vérification
se fait puce par puce contre ce fichier, elle n'est pas recopiée ici, et aucun décompte de
puces étayées n'est figé. Ce qui a été retiré, en revanche, l'a été explicitement et pour ce
motif-là : voir « Supersession retirée » ci-dessous.

Une version antérieure de ce paragraphe affirmait que ce document était installé
« à l'identique » depuis le pack. C'était faux, et réfutable par le `diff -u` ci-dessus :
c'est cette PR-ci qui s'écarte du pack, délibérément — d'où un registre d'écarts renvoyant à
une commande, plutôt qu'une affirmation d'identité que rien ne recensait. Rien n'est dit ici
de ce que porte une autre branche ou une autre PR : cela se lit à la source.

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
silencieusement. Le retrait porte sur cette seule affirmation ; les puces de « Décision »,
elles, sont conservées telles que le pack les écrit, sans tri au regard de la directive —
les deux choix sont visibles dans le `diff -u` ci-dessus.

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
- **Une version antérieure de ce paragraphe figeait un SHA de base et un décompte de commits
  comme preuve** ; la première avance de `main` a suffi à les rendre faux, avant même le
  merge. Ce qui est affirmé ici est **borné à
  une mesure datée**, et non présenté comme valant pour toute révision : rejouée sur
  `origin/main` le **2026-08-27**, cette commande rend une sortie vide. Rejouée le même jour
  en remplaçant `origin/main` par le `HEAD` de cette branche — qui porte déjà tous les
  fichiers que le merge apportera — elle rend également une sortie vide : c'est ce qui borne
  l'effet d'un rebase, d'un squash, d'un amend ou du merge de cette branche, sans avoir à le
  déduire. Le résultat ne survit en revanche **pas de droit** à l'avance de `main` : un
  commit ultérieur qui réintroduirait la formulation rendrait la sortie non vide.
  **La commande est à rejouer, pas à croire.** Ce que la sortie vide établissait à cette
  date : en dehors de la lignée de ce document, aucun commit alors présent dans l'historique
  interrogé n'avait ajouté ni retiré cette formulation.

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
