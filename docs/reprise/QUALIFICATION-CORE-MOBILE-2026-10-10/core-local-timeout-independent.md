# Clôture indépendante Source4 r3 — NON QUALIFIÉ

Le log complet (13 997 octets, 136 lignes, SHA256 `419ab4fb5629f7cbfd320f865f618dc51a34191998fa261e9f185aa03ac06b3f`) et les reçus confirment un arrêt par la garde **timeout**, exit **143**, après **902,258 s**. Le RSS agrégé échantillonné culmine à **5 866 217 472 octets**, sous le plafond de 7 GiB. Aucune attribution du pic à Node/Go, ni diagnostic OOM, ne découle de cette preuve.

Les phases assets, tsdown-ai, packages et unified se terminent. Les lignes 104–131 attestent les seules invocations DTS **1 à 11 sur 18** terminées ; la phase DTS échoue à la ligne 134. Les phases suivantes et le build complet ne sont donc pas qualifiés. Affinité CPU 0, heap 5120, profil per-plugin et cache désactivé figurent dans l’argv réellement reçu.

## Conservation indépendante

Les 29 membres de préparation ont été rehashés ; manifeste `39a90eaff97dea5ee159956112169a2e728e8c35b9f12fae5a03d4bee8e7f8e7`. Les 46 entrées de lecture restent égales avant/après cette revue.

Précision de périmètre : les **36 421 chemins protégés** comprennent **36 398 chemins Core et 23 voisins Python/tests**, et non 36 421 fichiers Core. Les deux reçus d’audit n’ont aucune différence Source/runtime. Les 36 398 entrées Core sont indépendamment égales aux SHA attendus dans les deux census ; les 36 421 fichiers actuels et les **81 runtime pins** (SHA et realpath) sont égaux aux pins. Mobile reste hors inventaire.

Le census passe de 226 761 à 226 802 fichiers ; les 4 120 liens sont strictement inchangés. Le delta recalculé reproduit exactement le fichier enregistré : **42 ajouts, 1 suppression, 2 modifications**, tous sous les préfixes OUTPUTS autorisés ; zéro chemin non sûr ou changement hors catalogue. Ce contrôle autorise des sorties partielles, sans les qualifier comme utilisables.

## Fermeture et verrou

Les trois wrappers pré/build/post attestent EOF, sortie complète et fermeture de leurs processus observés avec stratégie **PIDFD**. Pour le build : 27 identités observées, cancellation.freeze_complete=true, remaining=[], error=null. Cela ne prouve pas la clôture de descendants jamais observés.

La ligne 136 indique explicitement `child cleanup unverified`. Le verrou `core/.artifacts/dist-artifacts.lock` demeure avec deux nouveaux fichiers identiques au census post et à la lecture actuelle :

- `child-2671391`, 27 octets, SHA `99f93608963721dadcb2f9dc39fa024099384a6ea6b3ba04f05241b18c1439c2` ; contenu « Awaiting child completion. » ; PID présent dans les 27 identités du wrapper.
- `owner.json`, 201 octets, SHA `b80a9bbcf11340f37fa4f96f0fa6335cacac477ca9eadd119e8e30e39ec17157` ; propriétaire PID 2670008, startedAt 2026-10-10T23:30:04.265Z.

Le propriétaire canonique `core/scripts/lib/dist-artifact-ownership.mts:28–43` crée le marqueur enfant et ne le retire que dans son finally ; les lignes 107–115 conservent le verrou si un tel marqueur subsiste. La fermeture externe observée ne remplace pas cette confirmation interne manquante. **Verrou et sorties partiels conservés sans modification** ; aucune suppression, réparation ou permission de réutilisation délivrée.

Aucun build, Node, Git, SSH, test produit ou modèle n’a été lancé. Le premier rapprochement de revue a arrêté sur les 23 chemins hors census Core ; la correction de cet oracle de lecture est tracée, sans effet Source. Aucun fichier de préparation Current18 n’a été modifié. Cette clôture ne qualifie ni Native, ni SMS livré, ni le nouveau candidat Current18.
