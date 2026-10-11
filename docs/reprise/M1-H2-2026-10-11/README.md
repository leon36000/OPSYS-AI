# M1 H2 — conserver le registre de naissance du runtime plugin

Audit Toronto : 2026-10-11T14:55:18.650858-04:00.

OPSYS-AI reste **PARTIEL**. Cette coupe ferme une incohérence du Core : un état authentiquement construit avec le registre A pouvait recevoir le registre B, tout en conservant le runtime A. Le lecteur existant exige désormais un champ `registry` propre de type data et identique au registre capturé à la construction. Il refuse les accessors avant toute lecture de leur getter. Le runtime d’origine reste capturé une seule fois. Aucun nouveau registrar positif, SDK ou grant n’est ajouté.

Le changement tient à un propriétaire de production (`registry-state.ts`) et au fichier de qualification `registry-runtime.state-coherence.test.ts`. Les collections du même registre restent mutables ; l’adoption suit le propriétaire courant du record, sans rebinder le registre de naissance. Restaurer la paire peut restaurer sa lisibilité : H2 ne livre pas de poison historique H/P ni l’ensemble des permissions.

La reprise directe « Continue » succède à l’ancienne échéance de 11 h Toronto ; l’automation ancienne reste en pause. Le parent publié0e et ses qualifications CI/SMS fermées restent historiques. Les104 preuves absentes du transfert léger et son supplément absent restent absents, jamais crédités comme réexécutés.

## Vérification locale sur le candidat isolé

Les preuves Q sont locales, avec reçus fermés, JSON/JUnit, empreintes et limites ; elles ne sont pas des artefacts téléchargés de GitHub.

- Première tentative : échec d’import avant collecte,0 test. La copie initiale de `core/node_modules` avait omis les répertoires de résolution des workspaces.56 répertoires existants ont ensuite été copiés explicitement,985 fichiers/250 liens identiques, sans installation ni script de paquet. L’échec est conservé.
- RED :7 cas,2 témoins PASS et5 assertions nouvelles en échec attendu. Les quatre substitutions/data-getter ne refusaient pas ; le getter hostile levait son erreur propre. Les assertions situées après `toThrow` en échec n’étaient pas créditées.
- GREEN : même fichier byte-identique,7 PASS/noSkip ; les trois compteurs getter à zéro sont réellement atteints. Contrôles de style des deux chemins verts, check-only. Revues indépendantes bornées et avis Opus5.5 observé/configuréMAX sans outil ; les avis ne remplacent aucun test et l’effort fournisseur reste inconnu.
- Anciens ingress :37 PASS/noSkip. Une erreur de scellement Q a modifié les modes des preuves/cache après leur clôture,24,664s plus tard. Les empreintes des2900 fichiers du manifeste fautif ont été rapprochées sans divergence ; ce manifeste reste NONQUAL. Aucun mode restauré ni contenu de preuve réécrit. Les scellements ultérieurs utilisent une liste explicite de fichiers statiques, sans parcours global d’un namespace actif.
- Sept suites voisines :63 PASS/noSkip observés dans des invocations canoniques distinctes (catalogue15, ownership2, config23, lifecycle9, migration2, config-capture1, gateway-bindings11).
- TypeScript canonique :16 306 chemins uniques observés,0 diagnostic et les17 productions requises présentes ;13 112 sources liées,3 194 dépendances rehachées après clôture.69,186s, RSS5 816 057 856octets. Ce projet TypeScript exclut les fichiers de tests.

Source de qualification complète43851 : `948fbca7112ea29cbef73cd4faa8d11f0956db971d449642054a09f0272a185c`. Production finale `60a9095bee9eb001b992a795639c9cd253c2e4ff57b52d70eab94c5e4a5153b5`, test final `3e67b16611178edda8063364c9525c66bdea428697cbbcdc257cd52f38482765`. Les1312 pins GREEN et1319 pins de la campagne voisine sont distincts ; aucun résultat vieux n’est prêté au candidat. La limite de protection de940 entrées compilateur avant le RED reste explicite ; les inventaires fixes ne garantissent pas tous les descendants non observés ni toutes les dépendances hors liste.

## Publication et suite

Le build Core complet et la CI applicable du **nouveau commit exact** restent en attente de publication normale sur la branche privée existante et de leurs reçus runners. Aucun build actuel0e n’est une preuve de H2. Aucun force-push, fusion ou déploiement. Docker local inaccessible reste distinct des validations runners.

La réserve Opus `registryParams` est confrontée aux propriétaires complets : rôle réel config/hooks/hostCron/sessions, mais modification du state interne non établie via loader/API lus. Le registre local du resolver est déjà capturé quand ces paramètres sont lus. Si une future interface expose state/params, elle demandera ses oracles au point réel de handoff. H/P/OriginalC, slots, P/M/T et admission native restent des obligations séparées.

La suite conserve les dix départements profonds, Core OpenClaw, outils déterministes, permissions, dashboard, quatre profils mobiles/hors ligne, avatars et mémoires métier/développement séparées. La verticale M7→M1→M2→M3→M4/M6→M5→M8/M9/M10 et les capacités restantes demeurent au registre avec dépendances et preuves exigées.
