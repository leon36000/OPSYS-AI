# R27 — provenance estimation–réel

La référence exacte entre devis et estimation ainsi que la comparaison de durée
sont **vérifiées localement le 2 octobre 2026**, dans le périmètre décrit par
le [contrat de provenance](../architecture/PROVENANCE-ESTIMATION-TEMPS.md).
Onze chemins sont livrés : cinq de production et six de tests. Les préimages
et les reprises restent séparées; aucun maillon historique n'est réécrit.

## Vérification ROOT

La campagne métier r3 du **08:13:15 au 08:13:46 UTC** passe **2 184 cas**,
zéro échec ou erreur, et saute une garde réservée à GitHub Actions. Sa reprise
isolée r5, **08:15:55 au 08:15:56 UTC**, active localement `GITHUB_ACTIONS=true`
et passe ce même cas. La couverture des deux sélections est **2 185 identités
de test uniques**, avec le skip initial explicitement conservé. Il ne s'agit pas
d'une exécution de CI distante. Les 1 102 empreintes sélectionnées sont stables
dans les deux campagnes; cette surveillance n'en qualifie pas toutes les sources.

La sélection métier couvre les tests M03 et les cascades d'acceptation, M8/M9 et
M10. Elle exclut trois instruments lançant des campagnes de mutation imbriquées :
`test_gardes_des_outils.py`, `test_outils_de_preuve.py` et
`test_campagne_m3_persistante.py`. Ces instruments ne sont pas qualifiés par R27.
Ruff sur dix fichiers Python, le catalogue dix départements/207 outils et le
contrôle du diff passent. L'état de formatage préexistant de sept fichiers est
conservé, sans formatage global.

## Reprises et cause du rouge

La première sélection ROOT r1 visait deux chemins de test inexistants : aucun
test exécuté, code de sortie 4. La campagne r2 trop large lançait les mutations
répétées et a été interrompue après 620 s : 786 passes, dix échecs observés,
sans dérive de source. Son XML contient un testcase d'interruption supplémentaire;
ses compteurs ne servent pas à une qualification. Les sorties originales restent
conservées, y compris les 22 reçus internes compactés sans perte.

La cause initiale était une fixture d'envoi : elle ajoutait chaque lead dans un
registre CRM neuf et concaténait plusieurs racines. Le contrôle d'intégrité M2
refusait correctement le ticket avant l'envoi; les instruments refusaient ensuite
de muter cette suite nominale rouge. Le correctif ingère les leads dans la chaîne
durable existante. Aucune règle métier de refus ni assertion n'est assouplie.
Une reprise r4 avec le seul environnement `CI=true` sautait encore la garde;
r5 utilise la variable effectivement lue. Toutes ces sorties restent datées.

## Preuves et suite

Les artefacts de travail figurent dans
`/workspace/poursuite-opsys-2026-10-02-r1/calibration-r27`, notamment
`FREEZE-ROOT-r3.json`, les XML r1/r2/r3/r4/r5, les revues et préimages.
Les reçus ROOT sont dans `/workspace/restructuration-opsys-2026-09-30/preuves`,
préfixes `provenance-estimation-metier-root-r3-2026-10-02`,
`provenance-estimation-qualite-root-r3-2026-10-02` et
`provenance-estimation-garde-ci-root-r5-2026-10-02`.

L'[archive R27](../research/R27-2026-10-02/README.md) réunit la sélection finale
et les reprises, sans additionner les cas auteur aux campagnes ROOT. Les travaux
PDF et les cohortes suivants restent hors de cette qualification. M3 global
et la calibration automatique ne sont pas déclarés terminés.
