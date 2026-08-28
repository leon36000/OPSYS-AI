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
motif-là : voir « Supersession retirée » ci-dessous. Rien n'est dit ici de ce que porte une
autre branche ou une autre PR : cela se lit à la source.

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

`git log origin/main --pickaxe-regex -i -S'ma.tre.d.(oe|œ)uvre|github global' --oneline -- ':/' \
':!docs/decisions/ADR-0004-independent-agent-ownership.md' \
':!docs/decisions/ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md'`

(`:/` ancre le pathspec à la racine du dépôt — `-- .` rendrait une sortie vide sans rien
prouver si la commande est rejouée depuis un sous-répertoire, mesuré.)

Trois propriétés de cette formulation, et rien d'autre :

- **L'exclusion de chemin est obligatoire, pas décorative.** Ce document contient lui-même
  la formulation cherchée, pour la citer et la retirer ; son nom de travail avant renommage
  était `ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md`. Sans ces deux exclusions, la commande
  compterait ce document parmi ses propres preuves. **Contrôle positif, précision de révision
  nécessaire** : ce document est ajouté PAR cette branche (statut `A` dans son diff), absent
  d'`origin/main` — le rejouer sans les deux exclusions contre `origin/main` reste vide (rien
  à y trouver), et ne serait un contrôle positif qu'**après** le merge de cette PR. Rejoué
  MAINTENANT, avant merge, contre le `HEAD` de cette branche (qui porte déjà ce document) sans
  les deux exclusions : la commande rend une sortie NON vide (ce document cite lui-même la
  formulation), la preuve que le motif régulier sait effectivement matcher quand la formulation
  est présente — une sortie vide sur la forme AVEC exclusions n'est donc pas un motif mort.
- **`-i` est nécessaire, pas cosmétique.** La seconde alternative du motif, `github global`,
  est écrite tout en minuscules ; `-S` de `git log` est sensible à la casse par défaut. Sans
  `-i`, une occurrence réelle sous la graphie citée dans ce document (« GitHub global », G et
  H majuscules) ne matcherait PAS cette alternative, et une sortie vide ne distinguerait plus
  « formulation absente » de « motif qui n'a pas pu correspondre ». (Le sort de la première
  alternative, `ma.tre...`, dépend en plus de la locale d'exécution — hors du point ici : `-i`
  reste nécessaire indépendamment d'elle.)
- **Borné par construction, pas par une valeur figée.** Rejouée sur `origin/main`, cette
  commande (avec `-i`) rend une sortie vide. Rejouée en remplaçant `origin/main` par le `HEAD`
  de cette branche — qui porte déjà tous les fichiers que le merge apportera — elle rend
  également une sortie vide : c'est ce qui borne l'effet d'un rebase, d'un squash, d'un amend
  ou du merge de cette branche, sans avoir à citer ni SHA ni date. Le résultat ne survit en
  revanche **pas de droit** à l'avance de `main` : un commit ultérieur qui réintroduirait la
  formulation rendrait la sortie non vide.
  **La commande est à rejouer, pas à croire.** Ce que sa sortie vide établit : en dehors de la
  lignée de ce document, aucun commit alors présent dans l'historique interrogé n'a ajouté ni
  retiré cette formulation, sous aucune casse.

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
