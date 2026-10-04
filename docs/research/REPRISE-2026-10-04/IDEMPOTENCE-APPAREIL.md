# Lectures authentifiées et mutations d'appareil — 4 octobre 2026

Tranche suivant `6c4dfd8a4242723ad7dcd1a9156bb326c453de1c` dans la
[PR #623](https://github.com/leon36000/OPSYS-AI/pull/623).

## Défaut et correction

La réparation des lectures MCP a rendu à nouveau utilisable la paire personne/rôle sans
clé d'idempotence. La revue indépendante a identifié que cette paire pouvait également
atteindre une mutation : le Gateway ne classifierait pas une écriture et Python distribuait
l'appel quand `meta` valait `None`. Un pointage ou un départ de route M4 risquait donc d'être
appliqué plusieurs fois après des renvois réseau. L'authentification n'était pas contournée ;
la garantie d'idempotence manquait à cette frontière.

`Capacites.appeler` refuse désormais, **avant tout répartiteur, ticket ou effet**, un appel
portant une identité de source appareil sans enveloppe d'idempotence si l'outil n'est pas
à la fois T0 et N0. La classification vient du registre métier Python. Aucun nom d'outil
n'est recopié dans une liste Gateway et `readOnlyHint` MCP ne devient pas une autorité.
Le niveau compte aussi : l'import manuel d'avis M7 est mutable malgré son autonomie T0,
et sa déclaration N2 fait exiger la clé.

La lecture T0/N0 garde l'identité authentifiée. Les mutations avec enveloppe complète
gardent leur réclamation transactionnelle et leur rejeu. L'identité console et les agents
sans identité d'appareil conservent leur protocole. La mémoire reste fermée aux appareils.
Le parseur refuse également des champs appareil/horodatage sans clé, avant toute lecture.

Le runtime Core conserve en outre la compatibilité des appels internes avec un triplet
d'idempotence sans identité. Ce triplet ne crée pas une identité humaine et le profil
runtime serveur continue d'être ajouté. Une identité ou une enveloppe partielle reste refusée.

## Tests et revue

Le nouveau fichier `tests/test_idempotence_appareil.py` utilise le vrai client et serveur MCP :

- mutations N1 à N5 sans clé, même déclarées T0 : refus, journal métier inchangé et cinq
  tables SQL inchangées, y compris les approbations et réclamations ;
- registre réel M4 et M7 : départ de route et import manuel d'avis refusés sans clé ;
- lecture T0/N0 avec identité conservée, puis contexte nettoyé ;
- mutation identifiée avec clé rejouée sans seconde exécution ;
- appels console et agent préservés, mémoire appareil fermée, enveloppes partielles refusées.

`qa-r37` qualifie la source finale : **35 cas réussis, aucun ignoré**, Ruff réussi, dans
quatre fichiers entiers, dont le propriétaire M4 de l'heure serveur et du rejeu. Les campagnes
intermédiaires r28/r29 rouges de lint et r31/r34/r35 restent conservées et ne sont pas additionnées.
`qa-r33` qualifie format et lint des quatre fichiers TypeScript. `qa-r32` conserve les huit
erreurs de style préexistantes du fichier d'interopérabilité, corrigées par accolades et
callback sans valeur retournée. Aucun test natif TypeScript de cette tranche exécuté localement :
la qualification distante reste requise. `qa-r38` scanne les huit fichiers de code modifiés
avec Gitleaks : aucune alerte brute, sources figées et compteur OOM inchangé.

La CI Core sur `31dba4ef` avait passé les tests du superviseur corrigé, mais échoue dans
[l'interopérabilité Python HTTP](https://github.com/leon36000/OPSYS-AI/actions/runs/37167863141/job/111334508700) :
un test attendait encore une exception de métadonnées incomplètes pour la paire seule.
Il vérifie désormais le refus métier précis `idempotence_appareil_requise` sur une identité
valide et l'absence d'interaction ajoutée, puis conserve le refus des identités partielles,
des identités inconnues, du rejeu et de la liaison M10 révoquée. Ses scénarios ultérieurs
doivent encore repasser sur GitHub ; le succès E2E précédent ne les remplace pas.

## Validation Windows et limites

Le [job Windows 111338049491](https://github.com/leon36000/OPSYS-AI/actions/runs/37168883720/job/111338049491)
**réussit sur `6c4dfd8a`** après l'isolation des modules PowerShell. Les tests natifs de
permissions, d'export et de retrait de l'ACE Everyone sont exécutés. Le job inclut aussi
les exclusions de plateforme et scénarios optionnels préexistants ; aucun « zéro ignoré »
n'est annoncé pour ce job complet. Les Docker Desktop opt-in ne sont pas exécutés.
Le repli WinPS5 du nouveau helper a une preuve de sélection simulée, pas une preuve native
sur un poste ne disposant que de WinPS5. Les installations de production restent à qualifier.

La sécurité de la lecture sans clé dépend de la classification correcte T0/N0 des outils.
Un futur outil mutable mal classé ne serait pas couvert : cette limite et les frontières
de confiance sont décrites dans la revue archivée. Le jeton MCP de service reste réservé
au Gateway/service. Le produit demeure **PARTIEL**, la PR en brouillon et le gate mobile rouge.

[Archive de preuves](preuves/IDEMPOTENCE-APPAREIL-r1.tar.xz) et
[inventaire SHA256](preuves/IDEMPOTENCE-APPAREIL-r1.json) : reçus ROOT, JUnit, sources figées,
revue indépendante et observations GitHub. Aucune fusion automatique.
