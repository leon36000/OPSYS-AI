# ROUND D'HYPOTHÈSES ADVERSES — audit du dépôt OPSYS-AI

## Votre rôle

Vous êtes consulté AVANT que l'audit ne commence, et **on ne vous montre délibérément aucun
résultat**. On ne veut pas votre accord sur ce qui a été trouvé : on veut retirer à l'audité le
choix de ce qu'on regarde.

Votre production sera convertie en SONDES OBLIGATOIRES. Une hypothèse que vous formulez devient une
cible que l'audit doit mesurer, et dont il devra dire publiquement si elle est confirmée ou réfutée.
Une hypothèse trop vague pour être mesurée sera écartée — écrivez-les donc mesurables.

## Le contexte, en faits vérifiables uniquement

- Dépôt d'un progiciel de gestion, **Python bibliothèque standard uniquement** (contrainte gelée :
  aucune dépendance tierce en production).
- 10 modules métier (M1..M10) développés en ~6 semaines par une équipe **multi-modèles** : un
  orchestrateur pilote, des modèles de code écrivent, un trio de relecteurs de 3 fournisseurs
  distincts approuve chaque story, un script déterministe dépouille les verdicts.
- Méthode imposée : pour chaque story, branche dédiée, TDD (test rouge d'abord), portes de qualité
  locales, intégration continue, revue scellée par 3 fournisseurs, puis fusion.
- 168 pull requests fusionnées, 199 dossiers de revue, 644 verdicts scellés, ~2 840 tests.
- Les 10 modules sont au statut PARTIAL — c'est-à-dire : squelette et invariants posés, vague 1 de
  stories livrée, pas de mise en production.
- Un plan de référence (PDF) fige ~91 identifiants : décisions D-001..D-045, règles R-001..R-033,
  règles de gouvernance REG-01..REG-13.
- Plusieurs modules partagent un socle recopié : registre en journal d'ajout haché en chaîne,
  encodage canonique, conformité, machine à états.

## Structure réelle du dépôt (extraite de git, sans commentaire)

```
### Arborescence de premier niveau
  .claude
  .cursor
  .forge
  .github
  .gitignore
  .proof
  .sonarcloud.properties
  00-DIGEST.md
  AGENTS.md
  archive/pre-proof/AGENTS.md.pre-proof.bak
  CLAUDE.md
  archive/pre-proof/CLAUDE.md.pre-proof.bak
  CODEOWNERS
  FORGE_METHOD.md
  IMPLEMENTATION_SPEC.md
  LICENSE
  Modules M
  PACK_CONSENSUS_GRS_v2.md
  PROMPT_BOOTSTRAP_CLAUDE_CODE.md
  README.md
  RECONCILIATION.md
  Registres
  START_HERE.md
  VISION.md
  config.ini.example
  core
  docs
  ops
  pytest.ini
  registries
  reviews
  scripts
  stories
  surfaces
  tests

### Modules M/ (10 modules)
  Modules M/M1-front-office
  Modules M/M10-memoire
  Modules M/M2-revenue-crm
  Modules M/M3-estimation
  Modules M/M4-field-ops
  Modules M/M5-financecore
  Modules M/M6-material-control
  Modules M/M7-marketing
  Modules M/M8-analytics
  Modules M/M9-strategic-intelligence

### scripts/
  scripts/consensus_run.py
  scripts/ledger_append.py
  scripts/run-e2e.sh
  scripts/statut_lint.py
  scripts/structure_lint.py
  scripts/tally.py
  scripts/tests

### .github/workflows/
  .github/workflows/ci.yml

### registries/
  registries/frameworks.yaml
  registries/ledger/.gitkeep
  registries/ledger/decisions.jsonl
  registries/ledger/executions.jsonl
  registries/ledger/preuves.jsonl
  registries/modules.yaml
  registries/verdicts/.gitkeep
  registries/verdicts/mock-phaseC/gemini-3.1-pro.json
  registries/verdicts/mock-phaseC/glm-5.2.json
  registries/verdicts/mock-phaseC/longcat-2.0.json
  registries/verdicts/phaseC-live/Composer-2.5.json
  registries/verdicts/phaseC-live/DeepSeek-V4-Pro.json
  registries/verdicts/phaseC-live/GLM-5.2.json
  registries/verdicts/phaseC-live/Gemini-3.1-Pro.json
  registries/verdicts/phaseC-live/Gemini-3.6-Flash.json
  registries/verdicts/phaseC-live/Grok-4.5.json
  registries/verdicts/phaseC-live/Kimi-2.7.json
  registries/verdicts/phaseC-live/LongCat-2.0.json
  registries/verdicts/phaseC-live/MiMo-Pro-V2.json
  registries/verdicts/phaseC-live/MiniMax-M3.json
  registries/verdicts/phaseC-live/Qwen3.7-Max.json
  registries/verdicts/phaseC-live/raw/Composer-2.5.txt
  registries/verdicts/phaseC-live/raw/DeepSeek-V4-Pro.txt
  registries/verdicts/phaseC-live/raw/GLM-5.2.txt
  registries/verdicts/phaseC-live/raw/Gemini-3.1-Pro.txt
  registries/verdicts/phaseC-live/raw/Gemini-3.6-Flash.txt
  registries/verdicts/phaseC-live/raw/Grok-4.5.txt
  registries/verdicts/phaseC-live/raw/Kimi-2.7.round2.txt
  registries/verdicts/phaseC-live/raw/Kimi-2.7.txt
  registries/verdicts/phaseC-live/raw/LongCat-2.0.txt

### Volumétrie (fichiers suivis par extension)
    660 json
    340 py
    132 md
     67 gitkeep
     32 yaml
     16 txt
      4 jsonl
      4 html
      3 xml
      3 sh
      2 yml
      2 ini
      2 bak
      1 svg
      1 sha256

### Volumétrie du code Python des modules
  fichiers source : 135
  fichiers de test : 154
  lignes source    : 0 total
```

## CE QUE L'ON VOUS DEMANDE

Répondez UNIQUEMENT par un JSON strict :

```json
{
  "reviewer": "VOTRE_ALIAS",
  "vendor": "VOTRE_VENDOR",
  "hypotheses": [
    {
      "id": "HA-1",
      "enonce": "Ce que vous pensez qui est cassé, formulé comme une affirmation FALSIFIABLE",
      "pourquoi": "Le raisonnement : pourquoi CE mode de production produit CE défaut",
      "mesure": "La commande ou le test EXACT qui trancherait, exécutable sur le dépôt",
      "signal_de_confirmation": "Ce que l'on verrait si l'hypothèse est VRAIE",
      "signal_de_refutation": "Ce que l'on verrait si elle est FAUSSE",
      "classe": "code | plan | securite | performance | documentation | preuve | methode",
      "gravite_si_vraie": "critique | majeure | mineure"
    }
  ],
  "angle_mort_du_dispositif": "Quelle catégorie de défaut ce mode de production (multi-modèles,
     TDD, revue par 3 fournisseurs, dépouillement par script) est-il STRUCTURELLEMENT incapable
     de détecter ? Une seule réponse, la plus forte."
}
```

Produisez **entre 6 et 12 hypothèses**. Priorité absolue à celles qui :

1. exploitent une faiblesse SPÉCIFIQUE de la production multi-modèles (ce qu'un humain seul
   n'aurait pas produit, ou l'inverse : ce qu'une revue par modèles laisse systématiquement passer) ;
2. portent sur des choses qui passent TOUS les tests — un défaut que la suite verte ne peut pas
   voir vaut dix défauts qu'elle attrape ;
3. portent sur le dispositif de preuve lui-même (si l'instrument ment, tout ce qu'il a mesuré est
   suspect).

Ne proposez PAS : « il faudrait plus de tests », « la couverture est peut-être basse », « ajoutez
tel outil ». Ce sont des vœux, pas des hypothèses falsifiables.
