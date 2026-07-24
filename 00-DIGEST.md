RAPPEL PROOF — OPSYS-AI (PROOF-Team). P preuve avant DONE (DONE-avec-preuve ou BLOCKED-avec-raison, rien d'autre).
R revue aveugle scellee multi-vendor (Team 3x3), depouillee par SCRIPT — jamais d'auto-review, jamais meme vendor codeur/reviewer.
O orchestrateur unique — ne se relit jamais. O outils deterministes = autorite — aucun LLM n'ecrit un score.
F T3 = humain seul (paiements, secrets prod, suppressions, publication, engagements).
Interdits: stubs, TODO en diff, tests sans assertion, donnees inventees, --no-verify, commit direct main, auto-approbation, affirmation sans source.
Chaque story: pack scope -> codeur assigne (PAS toi) -> TDD -> gates -> PR -> revue scellee -> tally script -> merge -> registre -> docs a jour.
Taille story: cible <=1 h humain-equivalent, cap dur 3 h — au-dela, DECOUPER (D-044).
Arborescence D-038: Modules M/<MX>/frameworks/<Nom-exact>/ — un framework mal range ne merge pas.
Toute sortie de subagent finit par PREUVE: ou BLOCKED:. Le blocage honnete est acceptable; l'exception silencieuse jamais.

