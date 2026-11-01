# Packs sectoriels : un cœur générique PME, le métier dans un pack

Statut : tranche 1 (2026-11-01). Code : `src/opsys/packs/`. Données : `packs/<id>/`. Tests :
`tests/test_packs_sectoriels.py` (chargeur, empreinte, résolution, rendu, CLI) et
`tests/test_packs_generalisation.py` (non-régression, pack générique propre, garde du cœur, évaluation).

Un seul pack réel est livré (`renovation-exterieure-qc`, le premier client), plus le pack par défaut vide
(`generique-pme`). **Un second secteur n'a pas été qualifié** : le schéma n'a jamais été éprouvé contre un autre métier.

## Pourquoi

DECISIONS-ARCHITECTE-r1 §4 : les départements étaient écrits pour « une entreprise de rénovation extérieure au Québec ».
Le cœur devient générique PME ; la rénovation devient le premier pack sectoriel (vocabulaire, services, barèmes à
fournir, gabarits). Le profil d'entreprise choisit le pack ; l'onboarding pourra le proposer. Aucun texte de prompt du
cœur ne suppose un secteur hors du pack.

## Trois sortes de vocabulaire (l'audit qui a guidé la découpe)

| | Quoi | Où il vit | Exemples |
|---|---|---|---|
| (a) vocabulaire de métier générique | mots qu'une PME de services emploie quel que soit son secteur | **reste dans le cœur** | chantier, lead, soumission/devis, équipe, intervention, matériaux, facture |
| (b) vocabulaire sectoriel | types de travaux, produits, barèmes, métiers | **dans le pack** | gouttière, soffite, fascia, revêtement, bardeau, « rénovation extérieure » |
| (c) identifiants techniques | noms d'outils, d'événements, de colonnes, énumérés de contrats gelés | **ne se renomment pas** (contrats, tests) | `m3_estimer_projet`, `m4.travaux_termines`, `WCT` (unité de travail), `type_travaux: renovation_totale` (contrat v1 gelé), codes de service `gouttieres`… |

Un identifiant de la classe (c) peut CONTENIR un mot sectoriel (`renovation_totale`) sans que ce soit une fuite : ces
cas sont des exceptions nommées de la garde (ci-dessous), pas du texte de prompt.

### Ce que l'audit a trouvé (termes du pack rénovation, fichiers texte du dépôt)

- **Prompts** : 5 des 10 `SOUL.md` (M1, M2, M3, M4, M7) disent « d'une entreprise de rénovation extérieure au Québec » ; 1
  skill (M3 `estimer-un-projet`) ; 1 mission de `department.yaml` (M7). Les 5 autres `SOUL.md` n'ont que du vocabulaire (a)
  (« chantier ») : rien à changer.
- **Code et données du cœur** : catalogue de services de `opsys.taxonomie` (4 services), énumérés v1 gelés (6 copies),
  calendrier saisonnier de M7 (données), regex de matériaux et de métiers de M9 (`question_scenario.py`), motifs de
  `garde_fou_texte/engagements.py`, quelques commentaires et exemples de docstrings (réécrits).
- **Évaluation** : 22 des 120 cas du corpus supposent le secteur (sur 10 départements) ; M9 garde en plus ses trois
  corpus existants (référencés par empreinte, non réécrits).
- **Hors périmètre de la garde (dette recensée)**, après généralisation, en fichiers texte portant au moins un terme :
  `departments/*/tests` 283 fichiers, `tests/` du socle 165, `docs/` 92, `mobile/` 40 (données de test, un commentaire),
  `departments/*/fixtures` 18, `core/` 9 (fixtures de test), `departments/*/evals` 9 (corpus : les cas sectoriels sont
  étiquetés), `departments/*/docs` 4. Dans le cœur lui-même il reste 15 fichiers, tous des exceptions nommées de la garde.

## Ce que le cœur garantit

1. **Un pack par entreprise, jamais deviné.** `entreprise.yaml`, clé `pack`. Absente : `generique-pme`. Nommée mais
   introuvable, invalide ou altérée : refus typé, **jamais un repli sur le pack générique** (`openclaw configurer` sort en
   erreur avant toute écriture, la configuration précédente reste, le refus est consigné pour l'admin et visible dans la
   console `/connecteurs`).
2. **Le texte du cœur ne nomme aucun secteur.** `tests/test_packs_generalisation.py` balaie les fichiers du cœur avec la
   liste de termes du pack rénovation ; seules des exceptions explicites (fichier, termes, nombre de lignes, raison)
   passent, et une exception inutilisée échoue.
3. **Avec le pack du premier client, rien ne change.** Les dix `SOUL.md` d'avant et le skill de M3 sont retrouvés mot pour
   mot (sha256 épinglés), suivis d'un bloc sectoriel ajouté en fin de SOUL, lui aussi retrouvé mot pour mot dans la sortie.
4. **Avec le pack générique, aucune sortie effective** (SOUL.md, AGENTS.md, skills, distribution Hermes) ne porte un
   terme sectoriel ; le bloc injecté dit à l'agent de ne supposer aucun secteur et de demander ce qui manque.
5. **Aucune valeur inventée.** Un barème « à fournir par l'entreprise » ne porte jamais de valeur (`valeur: null`,
   `REJ-PACK-BAREME-INVENTE` sinon). Les chiffres restent calculés par les outils (AGENTS.md : le code calcule).
6. **Aucun droit n'est élargi.** Un pack ne porte ni outil, ni portée d'appareil, ni niveau d'approbation, ni budget : du
   texte, des listes et des paramètres à fournir. Il ne touche ni migration, ni contrat, ni événement.

## Anatomie d'un pack

```
packs/<id>/
  pack.yaml            # manifeste opsys.pack/v1 (schéma fermé)
  EMPREINTE.sha256     # sha256:<hex> du contenu (tous les fichiers sauf elle-même)
  gabarits/*.md        # gabarits de documents déclarés dans le manifeste (rien de non déclaré n'est admis)
```

| Clé de `pack.yaml` | Contenu |
|---|---|
| `schema`, `id`, `version` (x.y.z), `nom`, `langue` (`fr-CA`), `description` | identité ; `id` = nom du dossier |
| `sectoriel` | `false` : pack vide de secteur (le générique) ; `true` : porte du contenu |
| `fictif` | `true` obligatoire : barèmes, exemples et gabarits ne viennent d'aucune entreprise réelle |
| `vocabulaire` | `secteur` et `qualificatif_secteur` : les valeurs des **jetons** du cœur (`{{secteur}}`, `{{qualificatif_secteur}}`) ; vides pour un pack non sectoriel |
| `appellations` | `client`, `chantier`, `soumission`, `equipe`, `materiaux` : comment CE secteur dit le vocabulaire générique (a) |
| `services` | `{code, libelle, mots_cles}` : le catalogue de services du secteur |
| `glossaire` | `{terme, definition}` |
| `gabarits` | `{id, document, fichier, statut: exemple}` : un point de départ à revoir, jamais un texte validé |
| `baremes` | `{id, libelle, unite, statut, valeur, ou_fournir}` ; `a_fournir_par_entreprise` ⇒ `valeur: null` ; `exemple_fictif` ⇒ nombre, rendu « exemple fictif non contractuel » |
| `exemples` | `{id, departement, demande, fictif: true}` |
| `blocs` | `m01` à `m10` (les dix, explicitement) : `{ligne, inclure: [services, glossaire, baremes, appellations]}` |
| `termes_sectoriels` | les termes que la garde interdit dans le cœur (sans accent ni casse, début de mot) ; non vide pour un pack sectoriel |

### Jetons et bloc sectoriel

Un texte du cœur qui avait besoin du secteur porte un jeton, résolu par `opsys.packs.rendre_jetons` :
« d'une entreprise {{qualificatif_secteur}} au Québec » devient « d'une entreprise de rénovation extérieure au Québec »
(pack rénovation, mot pour mot comme avant) ou « d'une entreprise au Québec » (pack générique : l'espace du jeton
disparaît avec lui). Un jeton inconnu ou une accolade restante est `REJ-PACK-JETON-INCONNU` : jamais un `{{…}}` dans un
prompt. Les jetons valent pour `SOUL.md` et les fichiers Markdown des skills ; pas pour `department.yaml` (la mission de M7
est devenue générique : « une entreprise cliente au Québec » ; le secteur est dans le bloc de son SOUL).

À la génération (`opsys.profils.rendre_soul`, utilisé par `openclaw configurer` et la distribution Hermes), le `SOUL.md`
effectif est : texte du cœur rendu + **bloc sectoriel du département** (`## Contexte sectoriel — <nom> (pack <id> vN,
sha256:…)`, secteur, ligne du département, sections choisies) + capacités + règles communes. L'identité et l'empreinte du
pack figurent dans le prompt : un changement de pack se voit. Le répondant « passerelle » de l'évaluation envoie le même texte.

### Empreinte

`EMPREINTE.sha256` couvre le nom et le contenu de chaque fichier. Le chargeur la recalcule : un mot changé sans revue est
`REJ-PACK-EMPREINTE`. Après revue d'un changement : `opsys-metier pack empreinte <id> --ecrire` (valide tout sauf l'empreinte,
puis scelle). L'empreinte atteste QUEL contenu est actif ; elle ne remplace ni la revue ni un contrôle d'accès au dépôt.

## Résolution depuis le profil d'entreprise

```yaml
# $OPSYS_HOME/entreprise.yaml
pack: renovation-exterieure-qc      # absent : generique-pme
services: [gouttieres, revetement]  # inchangé : les services de l'entreprise restent déclarés ici
```

`opsys-metier pack choisir <id> --par <personne>` écrit cette clé (signée au journal d'audit, autres clés intactes) après
avoir chargé le pack. **Point d'appui de l'onboarding** : `opsys.packs.enregistrer_pack(id, par=…)` est la fonction que
`opsys.ingestion_onboarding` appellera pour proposer, puis faire confirmer par un humain, le pack de l'entreprise. Elle n'est
pas encore raccordée à l'ingestion : aujourd'hui, le choix est un geste humain explicite.

## Refus (catalogue fermé)

`REJ-PACK-INTROUVABLE`, `REJ-PACK-ID-INVALIDE`, `REJ-PACK-ILLISIBLE` (YAML illisible, clé en double, alias, trop gros),
`REJ-PACK-FICHIER-INVALIDE` (fichier absent, hors du pack, lien symbolique, caché, non déclaré),
`REJ-PACK-SCHEMA`, `REJ-PACK-CLE-INCONNUE`, `REJ-PACK-CHAMP-INVALIDE`, `REJ-PACK-DOUBLON`, `REJ-PACK-TERMES-ABSENTS`,
`REJ-PACK-GENERIQUE-NON-VIDE`, `REJ-PACK-BAREME-INVENTE`, `REJ-PACK-EMPREINTE-ABSENTE`, `REJ-PACK-EMPREINTE`,
`REJ-PACK-PROFIL-INVALIDE`, `REJ-PACK-NON-INSTALLE`, `REJ-PACK-JETON-INCONNU`, `REJ-PACK-DEPARTEMENT-INCONNU`. Le détail dit quoi
corriger, `chemin` nomme le champ. Un code hors de cette liste est une faute de programmation.

## Commandes

```bash
opsys-metier pack lister                         # packs installés, pack du profil, pack effectif
opsys-metier pack valider [--pack ID]            # schéma fermé, fichiers, empreinte
opsys-metier pack afficher ID --departement M3   # le bloc EXACT ajouté au prompt
opsys-metier pack empreinte ID [--ecrire]        # empreinte du contenu ; --ecrire scelle après revue
opsys-metier pack choisir ID --par NOM           # écrit `pack:` dans entreprise.yaml
opsys-metier verifier                            # valide aussi les packs et le pack du profil
```

Depuis le core : `opsys metier pack …`. Codes de sortie : 0, ou 2 pour un refus typé (JSON sur la sortie d'erreur).

## Créer un pack

1. Copier `packs/generique-pme/` sous `packs/<id>/` (id en minuscules et tirets) ; mettre `sectoriel: true`.
2. Renseigner `vocabulaire` (les deux jetons), `appellations`, `services` (codes stables en `[a-z][a-z0-9_]*`), `glossaire`,
   `gabarits` (fichiers `.md` sous `gabarits/`), `baremes` (tous `a_fournir_par_entreprise`, `valeur: null`), `exemples`
   (fictifs), les **dix** `blocs` et `termes_sectoriels` (tous les mots qui trahissent le secteur ; la garde les cherche).
3. `opsys-metier pack empreinte <id> --ecrire`, puis `opsys-metier pack valider --pack <id>`.
4. Relire `opsys-metier pack afficher <id> --departement Mn` pour chaque département : c'est ce que l'agent lira.
5. Lancer `tests/test_packs_generalisation.py` : la garde utilise les termes de TOUS les packs installés pour garder le
   pack générique ; un terme du nouveau pack qui se trouve déjà dans le cœur apparaîtra comme fuite à justifier ou à retirer
   (c'est voulu). Les services d'une entreprise restent déclarés dans son `entreprise.yaml` (voir `TAXONOMIE.md`).

Un pack ne doit **jamais** : porter un prix, une marge ou un seuil ; ajouter un outil, un droit ou un niveau d'approbation ;
renommer un identifiant technique ; citer une entreprise ou une personne réelle.

## La garde permanente du cœur

`test_aucun_terme_sectoriel_dans_les_fichiers_du_coeur_hors_des_exceptions_explicites` balaie `src/opsys`, `deploy`,
`install`, `scripts`, `outils` et, pour chaque département, tout sauf `tests/`, `fixtures/`, `docs/`, `evals/` et le
`README.md`. Les exceptions (liste dans le test, chacune avec fichier, termes permis, lignes permises et raison) sont :
le catalogue de services hérité de `taxonomie.py` ; les motifs du garde-fou d'engagements ; les six copies de l'énuméré v1
gelé (`type_travaux`) et les trois contrats YAML ; le calendrier saisonnier de M7 ; l'icône de toit et le slug de démo du
site M7 ; le parseur de scénarios de M9. Chacune est une dette ou un identifiant technique, pas un texte de prompt.

## Évaluation (gabarit commun)

Un cas du corpus qui suppose le secteur porte `pack: <id>` (22 cas, tous `renovation-exterieure-qc`). Le test de garde
exige que tout cas contenant un terme sectoriel porte l'étiquette (et que toute étiquette soit justifiée).
`opsys-metier evaluer lancer --pack ID` (défaut : le pack du profil, sinon `generique-pme` ; `--tous-les-cas` : aucun
filtre, diagnostic) écarte les cas d'un autre pack et **les nomme dans le rapport** (`pack.cas_ecartes`, ligne du
Markdown). Résultats (répondant `reference`, double déterministe, aucun modèle réel) : pack rénovation **120/120** ; pack
générique 98/98 sur le sous-ensemble neutre, 22 écartés. Le corpus et son empreinte restent ceux du fichier entier.

## Ce qui reste (suivi explicite)

- **Un seul secteur réel.** Le schéma et la découpe (a)/(b)/(c) n'ont jamais été éprouvés contre un second métier ; ils le
  seront au premier pack d'un autre secteur, qui peut révéler des champs manquants ou une garde trop étroite.
- **Le catalogue de services de `opsys.taxonomie` reste codé en dur.** Le pack en porte la copie documentée (égalité épinglée
  par test) ; la taxonomie ne lit pas encore le pack. Un `entreprise.yaml` sans `pack` et avec `services: [gouttieres]` continue
  de marcher (les services déclarés sont validés par la taxonomie, pas par le pack) ; mais ses agents lisent alors le texte
  générique tant que `pack:` n'est pas écrit : **les instances existantes du premier client doivent ajouter
  `pack: renovation-exterieure-qc` à leur profil** (`opsys-metier pack choisir`) pour retrouver le texte d'avant.
- **Données encore dans le cœur** (exceptions de la garde) : calendrier saisonnier de M7, regex de matériaux/métiers de M9.
- **Gabarits, exemples et barèmes ne sont consommés par aucun outil** : seuls les blocs de prompt, le vocabulaire et les
  services du pack sont lus aujourd'hui (SOUL.md). Les gabarits sont des points de départ documentaires.
- **Corpus d'évaluation générique** : le pack générique évalue 98 cas ; les 22 cas sectoriels n'ont pas d'équivalent neutre.
  Les corpus existants de M9 (`corpus-v1.json`, `corpus-metier-v*.json`) restent sectoriels.
- **Aucun modèle réel** n'a été mesuré avec le cœur générique : « le cœur ne nomme aucun secteur » est prouvé sur le texte,
  pas sur le comportement d'un agent.
- **Tests, fixtures, `docs/`, `mobile/` et `core/`** gardent des données du premier client (hors périmètre de la garde).
- **L'ingestion d'onboarding** ne choisit pas encore de pack (voir plus haut).
