# Revue adverse indépendante — sécurité et correction (2026-11-01)

Base : `5208490a4` (ligne architecte, vagues 1 à 4). Branche : `claude/revue-adverse`.
Périmètre : le code livré aux vagues 1 à 3 (et ce que la vague 4 y avait déjà raccordé). Posture : auditeur hostile ;
aucun rapport de livraison n'a été cru, chaque constat ci-dessous repose sur un exploit exécuté.

> Statut : **qualifié sur doubles et bases SQLite de test seulement.** Aucun service réel (fournisseur courriel,
> WordPress, réseaux sociaux, PostgreSQL) n'a été attaqué : la revue n'a aucun accès réseau. Rien ici ne vaut
> attestation de sécurité. Tout avis sur la conformité reste « À valider auprès d'un professionnel qualifié ».

## 1. Méthode

1. **Lecture ciblée des frontières**, pas lecture exhaustive (le dépôt compte plus de 500 000 lignes) : entrées non
   fiables, comparaisons de jetons, validations par expression régulière, ouvertures de fichiers, SQL, sérialisation,
   arrondis, et écarts entre ce qu'un docstring affirme et ce que le code fait.
2. **Exploit d'abord.** Chaque faille a un test pytest écrit pour l'exploiter. Il est ROUGE sur le code de base
   (`5208490a4`, exécuté sur une copie `git archive` du commit, pas sur le worktree modifié), corrigé minimalement,
   puis VERT, avec au moins un cas négatif (le comportement légitime reste accepté).
3. **Mutations** sur chaque correctif (garde retirée, comparaison inversée, validation supprimée, ordre de lecture
   changé) : voir §4. Une mutation survivante a toujours mené à un test de plus.
4. **Cinq équipes parallèles** sur un même worktree, à fichiers disjoints : le coordonnateur (`coord` : garde-fou de
   texte, registre MCP, OAuth, coffre, pont BI, sauvegarde) et quatre auditeurs (`app` : approbations ; `web` :
   HTTP/fichiers/rendus ; `reg` : registres, déclencheurs, migrations, concurrence ; `num` : correction numérique).
5. Les limites **déjà documentées comme telles** (doubles de test, absence de service réel, « le socle ne peut pas
   établir l'authenticité de l'appel : c'est le Core ») n'ont pas été comptées comme failles ; elles sont rappelées en §6.

Gravité : *critique* = contournement d'une approbation humaine, fuite de secret, exécution de code, perte d'intégrité
exploitable ; *élevée* = effet métier faux ou approbation détournée sans condition exotique ; *moyenne* = défense en
profondeur rompue ou déni de service ; *faible* = hygiène, latent, ou conditions d'exploitation étroites.
**Aucun constat critique n'a été établi.** Constats élevés : coord-01, app-01, app-02, app-04, num-04, num-05 (§3).

## 2. Surfaces couvertes

| Surface | Couverte | Résultat |
|---|---|---|
| Sas d'approbation N3/N4 (`approbations.py`, `decider`, `approbateur_en_cours`, `signataire_valide`) | lu en entier | solide ; app-04 (horloge de l'agent) |
| Courriel : OAuth (state, PKCE, portées), envoi sous sas, jeton lié à l'empreinte, expiration | lu en entier, exploits de rejeu/TOCTOU | sûr (voir §5) ; reg-02 (ingestion) |
| WordPress et réseaux sociaux : flux d'approbation, jeton, exécuteurs | exploits (entrelacement déterministe) | app-01, app-02, app-04 |
| Planificateur, acteur système `opsys-systeme`, bail et fencing | lu, exploits | reg-06 ; acteur système sûr |
| Droits d'appareil : code vs `ROLES.md` (17 employee, 28 seller, 247 admin) | comparaison exhaustive de l'inventaire d'outils | app-03 (doc) |
| Outil N2 qui décide (`m9_decider_demande_approbation`) | lu, exploits | sûr (identité relue, plafond, N5/T3 refusés) |
| HTTP : console, CSRF, redirections, wallboards (SSE), pont BI (jeton, OData, CSV), `/mcp` (jeton, `_meta`) | lu | web-04 ; reste sûr |
| SSRF : pagination des connecteurs courriel, URL WordPress, redirections suivies | exploits | web-02 ; reste sûr |
| Traversée de chemin : sauvegardes, packs, polices, studio, mbox, dossier CPA, paquets de site | lu, exploits | sûr (listes blanches, `O_NOFOLLOW`) |
| XSS/SVG : console (balayage AST des f-strings HTML), studio, site statique | exploits | web-06, web-07, web-08 |
| Désérialisation/exécution (`pickle`, `yaml.load`, `eval`, `shell=True`) | grep + lecture | rien de dangereux |
| Fuite de secrets (journaux, traces, erreurs, journal d'accès) | exploits | web-01, web-04 |
| Registres hash-chaînés, déclencheurs SQL (50), migrations 0035→0049, `writable_schema` | exploits, allers-retours avec données | reg-01, reg-03, reg-04, reg-05 |
| Concurrence réelle (6 sous-processus, SQLite fichier) : bail, idempotence, bus, migration | exploits | sûr |
| Injection de contenu non fiable : garde-fou de texte, isolation courriel/connaissances, Rule of Two, registre MCP | exploits | coord-01, reg-03 |
| Numérique : M5 (calcul, taxes, grand livre, QBO, relevés, prévisions), M6, M3, M8, M7 ads, M4 haversine | fuzz + exploits | num-01 à num-18, coord-02 |

## 3. Constats corrigés (preuve exécutable → correctif → test)

Convention de preuve : « rouge avant » = le test échoue sur `5208490a4` ; « vert après » = il passe sur la branche.
Les tests sont dans `tests/test_revue_adverse_*.py` (socle) et `departments/*/tests/**/test_revue_adverse_*.py`.

### 3.1 Garde-fou de texte et registre MCP

| Id | Gravité | Constat | Correctif | Test |
|---|---|---|---|---|
| coord-01 | élevée | Le garde-fou de texte (prix, garanties, téléphone, courriel, lien, exagération, avis légal) est contourné par un caractère **invisible** (espace de largeur nulle, trait d'union conditionnel, marque bidirectionnelle, balise Unicode, sélecteur de variante, caractère de contrôle) ou un **homoglyphe** cyrillique/grec : « 514​-555-1234 », « 99​$ », « meil​leur », « gar<а>ntie » passaient et étaient publiés tels quels. | `garde_fou_texte/_types.py` : `sans_invisibles` (catégories Unicode Cf et Cc, sélecteurs de variante) et repli des confusables, appliqués aux trois formes lues par les règles (`plier`, `normal`, `droit`). | `tests/test_revue_adverse_coord_garde_fou_invisibles.py` (11 rouges avant) |
| reg-03 | moyenne | L'historique du registre MCP (« qui a scellé quoi, quand ») n'était pas couvert par le sceau : même avec HMAC, `depuis_dict` acceptait un audit réécrit sans la clé. | `registre_mcp/registre.py` : `sceau.historique` (empreinte de toutes les fiches) dans la charge du sceau, vérifiée ; dernière fiche recoupée avec la révision courante. Les registres déjà scellés restent lisibles. | `tests/test_revue_adverse_reg_registre_mcp.py` (17 rouges) |

### 3.2 Approbations et gouvernance

| Id | Gravité | Constat | Correctif | Test |
|---|---|---|---|---|
| app-01 | élevée | **Une approbation consommée deux fois** (WordPress et réseaux sociaux) : `journal_chaine.ajouter` recalculait le rang à l'écriture ; deux exécuteurs lisant le même état écrivaient chacun leur `jeton_emis`/`tentative` et publiaient chacun. | `journal_chaine.ajouter(…, rang_attendu=)` : vraie comparaison-échange (`ConcurrenceJournal`) ; `consigner_jeton_emis` et `executer` lisent le rang avant l'état et refusent (`REJ-WP-APPROBATION-DEJA-UTILISEE`, `REJ-SOCIAL-EXECUTEUR-CONCURRENT`) sans rien envoyer. | `tests/test_revue_adverse_app_wordpress_course.py::test_deux_executeurs_qui_se_croisent_n_emettent_qu_un_jeton` ; `…/sas_social/test_revue_adverse_course_consommation.py` |
| app-02 | élevée | **Registre empoisonné à vie** : une écriture impossible depuis l'état courant (annulation pendant l'appel réseau, échec tardif, double conclusion) rendait `charger` incohérent pour tous les articles, définitivement (journal append-only). | Écritures gardées par état attendu et comparaison-échange ; tolérance de pliage pour une annulation posée en vol (`ANNULE` + jeton parti donne `publie`). | `tests/test_revue_adverse_app_wordpress_course.py`, `…/sas_social/test_revue_adverse_annulation_en_vol.py` (13) |
| app-04 | élevée | **L'agent choisit l'heure de l'approbation** : l'outil exécuté par la file recevait `horodatage` en argument ; avec 2099, l'approbation WordPress restait « valable une heure » jusqu'en 2099 ; le délai minimal d'un `schedule` se contournait avec une date passée. | `approbations.instant_de_la_decision_en_cours` (heure serveur `decide_le`), utilisée par `publication_outils._horodatage` (sauf appel d'appareil : réception serveur). | `test_un_agent_ne_peut_pas_fixer_l_heure_d_une_approbation_wordpress` |
| app-03 | faible | Six lectures M9 (N0/T0) projetées sur `admin` mais absentes de `ROLES.md`, et rien ne pinnait l'écart doc/code. | `ROLES.md` nomme les six outils ; garde de cohérence code → doc. | `tests/test_revue_adverse_app_roles_doc.py` |
| reg-06 | faible | Le jeton de fencing du bail « croissant » repartait à 1 après `liberer`. | `bail.py` : la ligne est conservée (« libre ») au lieu d'être supprimée. | `tests/test_revue_adverse_reg_concurrence.py` |

### 3.3 Registres, déclencheurs, migrations, ingestion

| Id | Gravité | Constat | Correctif | Test |
|---|---|---|---|---|
| reg-01 | moyenne | `INSERT OR REPLACE` contourne **tous** les déclencheurs `BEFORE DELETE` (≈ 25 tables « immuables », dont `wct_attentes` et `avatars_consentements`), car `recursive_triggers` est à OFF. Exploitable seulement avec du SQL arbitraire (aucun code de `src/` n'utilise REPLACE) : défense en profondeur. | `stockage/moteur.py` : `PRAGMA recursive_triggers=ON` (aucun des 50 déclencheurs ne se rappelle lui-même). Limite : une connexion hors moteur n'a pas ce réglage. | `tests/test_revue_adverse_reg_declencheurs.py` |
| reg-02 | moyenne | Ingestion courriel : une référence répétée dans une page fournisseur (delta Graph) violait la clé primaire de `courriel_refs`, sans journal, et **bloquait le dossier à jamais** (le curseur n'avançait pas). | `ingestion.py` : ensemble `refs_de_la_page`, la répétition compte en `deja_vus`. | `tests/test_revue_adverse_reg_courriel.py` |
| reg-04 | faible | Journal de traces : une ligne hostile (NaN, imbrication démesurée, 200 Ko d'octets nuls en queue) faisait planter `verifier`/`lire` ou repartir la chaîne à `seq` 1. | `traces.py` : exceptions capturées, fenêtre de relecture de la queue agrandie (plafond 16 Mio). | `tests/test_revue_adverse_reg_traces.py` |
| reg-05 | faible | M1 : le champ `hash` d'un maillon était exclu de l'empreinte (vestige). | `m1_front_office/registre.py` : seuls `ligne_id` et `precedent_ligne_id` sont exclus. | `departments/m01-front-office/tests/test_revue_adverse_reg_registre.py` |

### 3.4 HTTP, fichiers, rendus, secrets

| Id | Gravité | Constat | Correctif | Test |
|---|---|---|---|---|
| web-01 | moyenne | **Fuite de secret par la trace d'exception** : la fabrique `logging` ne masquait que le message ; `logger.exception` laissait un secret du coffre ou un `Bearer …` dans la trace (cause chaînée comprise). | `masquage.py` : `exc_text` et `stack_info` masqués. | `tests/test_revue_adverse_web_journaux_redirections.py` (3 rouges) |
| web-02 | moyenne | `urllib` suivait les redirections 301/302/303 **avec l'en-tête `Authorization`** (embeddings, passerelle LiteLLM — clé maître —, répondants d'évaluation). | Ouvreur `_SansRedirection` dans `memoire/embeddings.py`, `passerelle.py`, `evaluation/repondants.py`. | 4 tests à deux serveurs 127.0.0.1 |
| web-05 | moyenne | Classeur .xlsx hostile de ~700 octets (cellule `r="AAAAAAAA1"`) : `MemoryError`/OOM dans l'import QBO. | `_colonne_excel` borné à 16 384 colonnes (`REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE`). | `departments/m05-financecore/tests/test_revue_adverse_web_m5.py` |
| web-06 | moyenne | Garde de contenu actif contournable par schéma déguisé (`java&#9;script:`, `da&#9;ta:`) : WordPress (`REJ-WP-CONTENU-ACTIF`, seule barrière testée côté OPSYS), G-14 du site, QA du site. | Retrait des blancs et contrôles avant comparaison. | `departments/m07-marketing/tests/site/test_revue_adverse_web_m7.py` |
| web-07 | faible | Garde SVG par regex contournée (`href="&#106;avascript:"`, `<set attributeName="href">`, `<animate>`, `url(&#104;ttps://…)`). Atténué par `<img>` et la CSP `default-src 'none'`. | `rendu_statique._svg_actif` : lecture XML, DOCTYPE/ENTITY refusés. | idem |
| web-03 | faible | `^…$` + `.match` accepte un « \n » final : `utilisateur="root\n"` contournait le refus de `root`, un slug « services\n » cassait l'archive, `empreinte_valide` acceptait 65 caractères. | `.fullmatch` dans `fichiers`, `site/deploiement`, `schema_site`, `paquet`. Une quarantaine d'autres sites `^…$`+`.match` subsistent sans impact démontré (§5). | idem + `test_revue_adverse_web_journaux_redirections.py` |
| web-04 | faible | Journal d'accès uvicorn : `question=`, `task=`, `files=` (texte libre saisi) en clair. | `journaux_http.MasquerRecherche`. | idem |
| web-08 | faible | Latent : couleur d'un logo `'#"><b/>'` injectait une balise dans le SVG. | `fullmatch(#RRGGBB)` dans `logos.svg_du_logo`. | idem |

### 3.5 Correction numérique

| Id | Gravité | Constat | Correctif |
|---|---|---|---|
| num-04 | élevée | `preparer_relances` : la clé d'idempotence (facture, niveau) était comparée avec `jours_retard`, `date_reference`, `texte` (qui changent chaque jour) : le lendemain, `REJ-OPS-DOUBLON` **refusait tout le lot**, aucune relance pour aucune autre facture. | `hors_identite=("jours_retard","date_reference","texte")` ; un montant modifié est listé en `ignorees`, rien n'est récrit. |
| num-05 | élevée | Mouvement de trésorerie `1E+100` puis `-1E+100` : le solde rendait `0E+37` au lieu de 12,34 ; `1E+9999999` faisait lever `Overflow` à chaque lecture, définitivement (registre append-only) ; `m5_enregistrer_mouvement` (T3) l'acceptait. | Borne de 999 999 999 999,99 $ en valeur absolue et 6 décimales (`registre.py`). |
| num-01 | moyenne | Cellule xlsx `<v>1E+99999999</v>` : `int(Decimal)` pendant des minutes (DoS) ; plus de 28 chiffres : `InvalidOperation` non attrapée. | `_EXPOSANT_CELLULE_MAX = 18`, refus typé. |
| num-02 | moyenne | TRI : un flux à racine ≈ −98,65 % faisait lever `ArithmeticError` (tolérance relative trop stricte) : `m5_calculer_rentabilite_investissement` plantait. | Acceptation si la VAN change de signe entre `racine ± QUANTUM_TRI`, sinon verdict `REJ-CALC-RESULTAT-HORS-PRECISION`. |
| num-06 | moyenne | Devis M3 sans borne : `1E+30` / `1E+999999` levaient `InvalidOperation`, un devis de 1,5×10²⁴ $ était accepté ; arrondi double (0,01 $ × 0,4999…). | Bornes (≤ 999 999 999 999,99 $, marge ≤ 1000), contexte exact par ligne. |
| num-08 | moyenne | Garde « CAD seulement » de M8 ne reconnaissait que `USD` ou `USD/mot` : « USD / lead », « € par lead », « dollars US » passaient. | Code ISO non CAD en mot entier + symboles et mots courants. |
| num-09 | moyenne | Bon de commande M6 en float : 4,35 $ × 100 = 434,99999999999994 $ ; quantité 1e308 → `inf`. | `montant_ligne_au_cent` (Decimal, demi-supérieur) ; hors domaine refusé. |
| num-10 | moyenne | Variance de chantier M6 en float : un écart d'exactement 10 % valait 0,09999999999999994, donc aucun signal « atteint ou dépasse ». | Calculs en `Decimal(str(x))`. |
| num-17 | moyenne | Un fait `devis_accepte` à `prix_total` `1E+30` faisait lever `InvalidOperation` dans `m8_carnet_signe_cad` et tout ce qui lit les mesures ; `1e999999999` → `Overflow`. | `decimal_lu` borne [1e-15, 1e15] ; la mesure devient non calculable et le dit. |
| num-03 | faible | `au_cent` arrondissait dans le contexte de l'appelant (28 chiffres) : `InvalidOperation` sur un projet à 50 ans. | Contexte propre à 50 chiffres. |
| num-07 | faible | `m5_calculer_taxes_tps_tvq("100.005")` rendait 114,985 (trois décimales). | Refus sous le cent. |
| num-11 | faible-moyenne | Quantité à commander en float (10,3 − 3,1 = 7,200000000000001) : recevoir 7,2 était une réception « inférieure », le bon ne se complétait jamais. | Écarts en Decimal exact. |
| num-12 | faible | AD-05 (publicité) ne se déclenchait que si `budget > 0` ; chargeur sans contrôle numérique (`.nan`). | `cout > budget` + validation. |
| num-13 | faible | `fin_de_periode("2026-01\n")` et chiffres Unicode (`２０２６-０１`) acceptés et stockés bruts (deux orthographes d'un même mois). | `re.ASCII` + `fullmatch`. |
| num-14 | faible-moyenne | `lier_piece` : sha256 + « \n » = « autre » empreinte : le contrôle « un reçu ne justifie qu'une dépense » se contournait. | `fullmatch`. |
| num-15 | faible-moyenne | Clé `contre_passation:<écriture>` sans issue : une contre-passation mal datée ne se corrigeait pas (`REJ-GL-PIECE-CONFLIT`). | La clé porte la date et l'empreinte du motif ; un seul brouillon devient définitif. |
| num-16 | faible | Entrepôt M8 : « --5 » passait puis `int()` levait. | `fullmatch(-?[0-9]+)`. |
| num-18 | faible | Relevé bancaire : « 1.23,45 » lu 123,45 $ ; « 12,34,56.78 » lu 123 456,78 $. | Groupes de 3 chiffres exigés, sinon refus « ambigu ». |
| coord-02 | faible | `pointage.distance_km` (haversine) : `ValueError: math domain error` pour ≈ 4 % des points antipodaux (a = 1,0000000000000002). | `a` ramené dans [0, 1]. Test : `departments/m04-field-ops/tests/test_revue_adverse_coord_haversine.py`. |

Tests numériques : `departments/m0{3,5,6,7,8}-*/tests/test_revue_adverse_num_*.py` (167 cas rouges sur le code de base).

## 4. Mutations

Plus de 120 mutations personnelles au total, **toutes tuées** au dernier passage :
`coord` 9 (garde-fou : retrait des catégories Cf, Cc, sélecteurs de variante, confusables, nettoyage de `plier`,
`normal` et `droit` ; haversine : retrait du clamp, clamp à demi) dont **2 survivantes** (nettoyage de `droit` et de
`normal`) qui ont mené au test des formes qui gardent casse et accents ; `app` ≈ 45 ; `web` 28 (une survivante :
`?files=` seul) ; `reg` 32 ; `num` > 100 (trois survivants équivalents documentés : `devis_durable._contexte_exact`
avec `cout_unitaire` au lieu de `prix_unitaire`, et deux `fullmatch→match` sur `_DATE` que `date.fromisoformat`
rattrape).

## 5. Examiné et jugé sûr (exécuté ou lu, pas supposé)

- **OAuth courriel** : `state` signé HMAC (nonce, compte, fournisseur, usage, expiration), usage unique par
  comparaison-échange, PKCE dérivé d'un HMAC serveur, portées minimales vérifiées à l'échange et au rafraîchissement,
  URL de rappel `https://` ou loopback strict, retour lié à la session qui a démarré l'autorisation.
- **SSRF courriel** : tout appel passe par `ClientApi.verifier_url` (https, hôte en liste blanche, ni identifiant ni
  port) ; `nextLink` revalidé ; aucune redirection suivie par le transport courriel.
- **Envoi de courriel sous sas** : contenu scellé AES-GCM, empreinte de tout ce qui part, jeton lié à l'empreinte,
  expiration sur l'heure serveur de la décision, consommation `APPROUVE→ENVOI_RESERVE` par comparaison-échange avant
  tout réseau, réservation orpheline = INCERTAIN (jamais rejouée), en-têtes sans injection.
- **Pont BI** : jeton dans l'en-tête seulement, comparaison en temps constant au coffre, quotas, lecture seule
  imposée au moteur (`PRAGMA query_only`), cellules CSV neutralisées, OData minimal qui refuse (501) ce qu'il ne fait pas.
- **Coffre de secrets** : AES-256-GCM en enveloppe avec AAD, clé maîtresse hors base (0600, `O_NOFOLLOW`),
  export impossible, journal d'accès append-only, jetons opaques liés à un porteur et un usage.
- **Sauvegarde chiffrée** : blocs authentifiés avec en-tête et drapeau « dernier », troncature/réordonnancement
  détectés, fichier final seulement après authentification complète ; **restauration** : tar en liste blanche de
  noms, empreintes du manifeste, `integrity_check`, révision connue.
- **Console** : aucune redirection ouverte (toutes préfixées), CSRF sur les écritures, rôle relu en base avant et
  après lecture, balayage AST des f-strings HTML : aucun texte de donnée non échappé.
- **Acteur système `opsys-systeme`** : n'existe que pendant un tour, hors requête HTTP/MCP, non copiable ni
  sérialisable, portée `reconciliateur` ou `planificateur` jamais interchangeable.
- **`m9_decider_demande_approbation`** (outil N2 qui décide) : identité relue en base, rôle `admin` exigé, plafond
  `nathan_owner`, N5/T3 refusés, aucun paramètre ne désigne le décideur.
- **Droits d'appareil** : aucun outil T3/N5 projeté ; aucun N3/N4 donné à `employee`/`seller` que la doc ne justifie.
- **Concurrence réelle** (6 sous-processus sur un fichier SQLite) : bail, idempotence, `bus.publier`,
  répartiteur (chaque événement livré une fois), migration simultanée.
- **Migrations 0035→0049** : tête unique ; montée pas à pas ; aller-retour avec données ; `writable_schema` (motif
  introuvable : erreur bruyante ; mode DEFENSIVE : erreur, base inchangée ; connexion ouverte : relit le schéma).
- **Numérique** : cotisations 2026 (plafonds RRQ/RQAP/AE jamais dépassés sur 26 périodes), constantes K de l'impôt
  fédéral recalculées, TPS 5 % / TVQ 9,975 %, balance du grand livre équilibrée sur 600 opérations aléatoires, tous les
  chemins créant des lignes passent par `normaliser_lignes` ; score de santé M8 refuse plutôt que d'inventer.
- **Packs, studio, mbox, onboarding** : YAML `SafeLoader`, liens symboliques refusés, noms de polices simples avec
  sha256 épinglé, bombes de décompression mesurées à la lecture.

## 6. Constats non corrigés, et pourquoi

| Id | Gravité | Constat | Raison |
|---|---|---|---|
| D-1 | élevée si non configuré | **La garde MCP (registre scellé + Rule of Two) est inactive par défaut** : sans `OPSYS_MCP_REGISTRE`, « rien n'est vérifié ». Aucun script de déploiement ni d'installation ne la pose. | Déjà documenté (`OBSERVABILITE-MCP.md` : « À faire par l'installateur… non fait ici »). La poser par défaut change le comportement de production : décision de l'architecte. **À faire avant toute mise en service.** |
| D-2 | élevée (limite) | **L'identité d'appel (`opsys/personne`, `opsys/role`) vient de `_meta`** ; seule `m3_lire_apprentissage_chantier` est attestée par la passerelle. Un porteur du jeton MCP peut forger `admin`. | Limite documentée (`approbations.signataire_valide` : « repose sur OPSYS-CORE »). Hors du socle Python ; à qualifier côté Core (jetons d'appareil, séparation des jetons MCP des agents). |
| D-3 | moyenne | `console.changer_mode` et l'activation des exécuteurs du planificateur n'exigent que `admin` ou `nathan_owner` : un gestionnaire `admin` peut mettre un département en `autonome`, alors que l'app lui interdit de décider un N3. | Décision d'architecte (séparation `admin`/`nathan_owner`). Non prouvé comme faille : aucun test n'affirme le contraire. |
| D-4 | moyenne | `secret_ref.nom` (sites WordPress, comptes sociaux) n'est validé que par expression régulière : un N3 approuvé pourrait nommer n'importe quel secret du coffre. | Ports non raccordés : non exploitable aujourd'hui. À durcir au raccordement (préfixe réservé ou `usage` coffre). |
| D-5 | moyenne | Durabilité : `synchronous=NORMAL` en WAL ; une coupure de courant peut perdre le commit `ENVOI_RESERVE` d'un courriel déjà parti, qui redevient `APPROUVE` et peut repartir en double. | Non prouvé (pas d'injection de panne). Piste : `synchronous=FULL` pour la réservation d'envoi. |
| D-6 | moyenne | `MaillonsDurables.append` sans `rang_attendu` : hors transaction englobante, lecture de la queue et ajout sont deux transactions (M1/M2/M4/M5). | Aucun appelant de production hors transaction trouvé ; correctif générique à concevoir (garde de chaînage dans `append`). |
| D-7 | faible | Les tables `journal`, `approbations`, `agents_*_historique`, `service_audit`, `m8_ent_constructions` n'ont **aucun déclencheur** ; `journal` et `approbations` n'ont pas de chaîne. | Limite connue (attaquant avec SQL arbitraire). Pas d'ancre externe : la queue d'un registre se supprime sans trace. |
| D-8 | faible | Seuils M8 (`evaluer_seuils`, `_etat_seuil`) comparés à la valeur déjà arrondie au centième : 66,666 % franchit un seuil de 66,67 (num-19, exploit exécuté). | Corriger change la forme des mesures (`valeur_exacte`). À planifier. |
| D-9 | faible | 10 migrations créent leurs tables depuis `schema.META` vivant (`table.create`) : les états intermédiaires d'une base neuve ne sont pas fidèles. Une future migration `add_column` échouerait à l'installation neuve. | À surveiller pour 0050–0052 : figer le DDL dans la migration. |
| D-10 | faible | `serveur_mcp.py` : `"details": str(exc)` sur les outils `opsys_runtime_*` (une exception SQLAlchemy porterait SQL et paramètres). | Non déclenché ; correctif proposé : code fixe + classe d'exception. |
| D-11 | faible | `ingestion.document_contacts` : nom/adresse d'un correspondant sans neutralisation de formule si le CSV s'ouvre dans un tableur. | Neutraliser casserait le nom importé au CRM ; à trancher. |
| D-12 | faible | `PII CLE_SECRETE` ne couvre pas `pass`, `passphrase`, `credentials`, `auth`. | Limite de la détection par motifs. |
| D-13 | faible | WordPress : `valider_url` accepte `x.internal` ou `127.0.0.1.nip.io` (aucun transport réel branché). | SSRF latent : refuser les adresses résolues privées/loopback/lien-local au raccordement. |
| D-14 | faible | Courriel sortant : la demande d'approbation montre destinataires, objet, contexte et sources, **jamais le corps** (empreinte seulement). | Choix de confidentialité assumé ; l'approbateur doit lire le brouillon dans la console. À valider avec le propriétaire. |
| D-15 | faible | ≈ 40 autres `^…$` + `.match` (ex. `identite._IDENTIFIANT`, `outils._NOM_OUTIL`, `departements._CRON`), sans impact démontré. | Hygiène : passer à `fullmatch` au fil de l'eau. |
| D-16 | faible | `studio/actifs.ResolveurDuRegistre` : deux actifs aux octets identiques, le dernier gagne pour approuvé/révoqué ; copie locale de la garde `approbateur_en_cours` en M2. | Fail-closed, pas de contournement prouvé. |

## 7. Ce qui n'a PAS été examiné

`core/` (TypeScript : passerelle, appairage, jetons d'appareil — donc l'authenticité de `_meta` ne peut pas être
affirmée) ; PostgreSQL (aucun backend ici : advisory locks, `READ COMMITTED`, déclencheurs plpgsql) ; `mesure_plan` (OpenCV
absent) ; rendu PDF et `fusion_pdf_worker`, `ocr_profil` ; `liaison_cibles` (ticket scellé) et
`agents_cron_autorite`/`admission_agents` ; `usine/service.py` au-delà du contrôle propriétaire, `site/*` hors gardes
de contenu, `studio/controle.py`/`ocr.py` ; M5 `outils.py` (7 900 lignes, par échantillonnage), `dossier_cpa`,
`dossier_decision_cfo`, `paie_qc_preparatoire` et `impot_quebec_regulier` en profondeur (fichiers épinglés,
intouchés) ; M10 hors connaissances ; les outils M2/M4/M5 un par un ; la survie des déclencheurs à une archive de
restauration forgée ; `derniere_erreur` des reçus d'événements (texte brut d'exception) ; aucune attaque sur un
service réel (fournisseurs courriel, WordPress, réseaux sociaux) ; aucune injection de panne (coupure de courant).

## 8. Suites lancées sur la branche (état final)

Départements entiers : M1 1909, M2 2269, M3 2774 (+36 sautés : campagne de mutation réservée au CI), M4 3579 (+20
sautés), M5 3801, M6 1817, M7 2662, M8 1356, M9 1553 (+2 sautés), M10 1498 : **tous passés, 0 échec**.
Socle (220 fichiers ciblés : stockage, coffre, courriel, câblage, registre MCP, traces, pont BI, embeddings,
passerelle, évaluation, console, approbations, garde-fou, paquets déclarés, commande métier, portées d'appareil,
sauvegarde, exportation, idempotence, événements, migrations, connecteurs, packs, connaissances, ingestion, recalcul
M4, tous les `test_revue_adverse_*`) : 4820 passés, 21 sautés, **86 échecs, tous préexistants** : 40 dans
`test_moteur_recalcul_m4_e2.py` (inventaire de tables, FTS5) et 46 dans les `test_console_fusion_*` (PDF/fusion,
isolation absente de cette machine). Le même lot sur une copie de `5208490a4` donne 91 échecs (les 86 + 5 qui ne
reproduisent pas sur la branche) : **aucun nouvel échec**. `ruff check src tests departments` : propre.
`verifier-wt.sh` : OK (537 outils).

## 9. Reproduire

```
W=<worktree>; P=$W/src; for d in $W/departments/*/src; do P=$P:$d; done
PYTHONPATH=$P python -m pytest -p no:cacheprovider --import-mode=importlib -rfE \
  tests/test_revue_adverse_*.py departments/*/tests/test_revue_adverse_*.py departments/m07-marketing/tests/*/test_revue_adverse_*.py
```

Pour vérifier le « rouge avant » : extraire `5208490a4` (`git archive`) dans un dossier et lancer les mêmes fichiers
avec `-o pythonpath=` (le `pythonpath` de `pyproject.toml` écrase sinon `PYTHONPATH`).
