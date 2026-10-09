# Reprise des intentions après refus de preuves M6

Daté Toronto : 2026-10-08T21:55:53.060848-04:00. Parent exact `c7be76bdad87292b5002042a7a633125049d868f`. OPSYS-AI reste **PARTIEL**.

## Défaut et comportement corrigé

Après un succès serveur dont la réponse est perdue, une garde d'identité ou de source peut refuser
la tentative suivante avant lecture du résultat idempotent. Ce refus ne prouve pas l'absence du
succès antérieur. Le mobile reconnaissait le code générique d'identité, mais classait le namespace
réel `REJ-M6-PREUVES-*` comme définitif. Les tests ont reproduit la tentative de l'UUID suivant au
troisième cycle ; ils n'établissent pas un second effet serveur effectivement appliqué.

Deux conditions corrigent l'interpréteur : refus externe pré-claim M6 incertain, identité générique
ou M6 incertaine dans les deux formes. L'intention reste en attente avec le même UUID, le même
payload et le même corps RPC ; la suivante est bloquée jusqu'à confirmation. Un refus métier frais
interne certain reste définitif. Aucun changement du vidangeur, du SDK, du backend ou des permissions.
L'ancien statut permanent conservait physiquement UUID/payload ; leur effacement n'est pas revendiqué.

## Qualification et précision des preuves

Six enveloppes Cap/SQLite ont été capturées depuis les vrais producteurs d'un monde fictif : succès,
rôle retiré/restauré, source à 10 001 lignes/restaurée et refus métier frais. La fixture est identique
aux octets capturés, avec leurs empreintes. Les quatre refus pré-claim/replays conservent intégralement
les 49 tables ; les replays retrouvent les références du succès initial. Le refus frais change seulement
`mutations_appliquees` : son code est `DECLARATION-DEJA-SOUMISE`. Son contexte Cap800 ne démontre pas
un nouveau refus de taille. Aucun artefact, stock, coût ou statut M4 nouveau n'est produit.

Rouge déterminant : cinq échecs produit, 18 réussites. Le premier essai mêlant trois défauts produit
et deux présupposés SDK est conservé séparément. Après correction : 127 tests ciblés, puis **4 941
tests mobile sur 212 suites**, TypeScript strict vert et empreintes sources stables. SDK, dépôt mémoire
de production et vidangeur sont réels ; fetch rejoue les captures. L'identité est injectée et confirmée
en SQL, sans nouvel appairage opaque DEVICE, Gateway, perte réseau HTTP réelle ou téléphone déduit.

La première invocation complète Root utilisait un mauvais séparateur pnpm : aucun test sélectionné,
auto-installation et lock supplémentaire. L'essai reste rouge ; le lock non canonique est archivé hors
projet. `npm ci` a restauré le package-lock autoritatif inchangé, puis Jest/tsc ont été invoqués directement.
Il ne s'agit pas d'une mise à niveau générale de dépendances. Les versions installées avant cette
auto-installation n'étaient pas intégralement hachées ; la restauration suit le lock canonique.

Le harnais v2 attend les propriétaires observés et EOF avant scellement ; 15 tests fictifs et un smoke
sur l'inventaire Git réel le qualifient. V1, ses rouges et les 88 octets tardifs restent conservés.
Cadence d'observation et backpressure peuvent perturber les mesures ; descendants jamais observés,
SIGKILL et modification volontaire restent hors garantie. Les anciens essais ne sont pas réétiquetés.

## CI exacte et suite

La CI du parent c7be [37865159071](https://github.com/leon36000/OPSYS-AI/actions/runs/37865159071)
a fermé ses preuves applicables. Ses six fast shards utilisent effectivement un worker et 4096 Mio,
avec les trois reporters : 14 776 réussites, 31 skips motivés, 1 005 fichiers distincts, aucun diagnostic
non géré. Les tas mesurés en fin de module ne sont ni pics RSS ni compteurs OOM. Le Core reste au
sous-arbre `4ad1a927b4286039c23f7b93cbf43c2d02b61c7e`. Le run e041 rouge est conservé avec son refus
correct de gates ; aucun succès de c7be ne lui est attribué et aucun succès parent ne qualifie le nouveau commit.

La capsule contient 167 membres vérifiés au roundtrip, SHA256 `eba9b800a70828ad54992914031fa96218f1d6baa5e9d08b8914c8487969f15c`. Le registre
rapproche les trois sources et leurs préimages ; credentials, CLI brut, bases et archives CI brutes sont exclus.
Nouveau commit exact et sa CI restent requis après publication normale sur la branche privée existante.
Aucune force-push, fusion main, production, paiement ou action client réelle.

La conception T4.27-b est corrigée : autorité/source avant claim, révision attendue seulement en écriture
fraîche, replay de sa propre référence persistée même après v2. Les trois outils sont des propositions,
pas une capacité livrée. Six causes canoniques choisies par l'admin, décision M4 N4 et mémoire M10 restent
distinctes. La verticale M7→M1→M2→M3→M4/M6→M5→M8/M9/M10 et la profondeur des dix départements restent
la file ; téléphone, N5, isolation mémoire, 104 références absentes et conversations inconnues gardent leurs limites.
