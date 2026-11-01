# M7 : studio créatif gouverné (images, logos, matériel imprimable, vidéo courte)

Statut (2026-11-01) : **tranche 1, jamais exécutée avec un vrai modèle, un vrai OCR, une vraie imprimerie ni un vrai réseau.**
Tout ce qui suit est prouvé avec des doubles de test, un moteur de rendu maison en Python pur et des polices de test. Ce que
cela ne prouve pas est dit à la section « Ce qui n'est PAS prouvé ». Rien n'est qualifié, rien n'est « complet ».

**Aucun vrai modèle n'a produit d'image.** Les fonds de tout le dépôt viennent de `GenerateurImageDouble` (dégradé et bandes
dérivés de la graine). **Aucun OCR réel n'a lu une sortie.** Le profil OCR existant (Tesseract 5.5 + pdfium isolés dans
bubblewrap, `opsys.ocr_runtime`) exige un bundle validé qui n'existe pas sur la machine de construction ; il est branché par un
adaptateur (`LecteurOCRProfil`) testé avec un `extraire_candidat` simulé seulement. Le contrôle qualité tourne ici sur deux
doubles : un lecteur de glyphes sur les PIXELS du PNG et un extracteur de texte vectoriel (SVG, PDF).

Décisions de départ : feuille de route r2 (« Création image/vidéo », « Composition et impression »), décision d'architecte r2
n°2 (le registre de fournisseurs porte les drapeaux de licence ; un moteur de politique refuse l'activation d'un composant non
conforme au client) et n°3 (la génération ne produit jamais un texte, un logo ou une mention finale : composition
déterministe obligatoire, contrôle de lecture à zéro erreur sur les informations critiques, validation humaine avant toute
publication ou impression), n°6 (questions juridiques à un avocat), recherche R5. Code :
`departments/m07-marketing/src/m7_marketing/studio/` et `.../studio_outils.py`.

## 1. Audit de l'existant (avant cette tranche)

| Ce qui existait | État | Ce que la tranche en fait |
|---|---|---|
| `opsys.fournisseurs` (registre, catalogue de 57 entrées, moteur de licence `politique.evaluer`, capacités `image`, `video`, `avatar`) | Complet côté configuration ; aucun consommateur image ou vidéo | **Réutilisé tel quel** (`studio/modeles.py`). Aucune copie des codes de refus ni du catalogue. Un seul ajout de donnée : `modeles.declaration_pour_double()` (générateur de test, déclaré comme n'importe quel fournisseur personnalisé). |
| `sas_social` et son refus `genere_non_compose` | Le sas croyait les médias sur parole (`origine`, `controle_ocr`, `ia_generee` déclarés) | **Durci** : un résolveur du registre des actifs du studio ferme trois failles (section 8). Paramètre `actifs` optionnel de `soumettre`, `approuver`, `executer`, `controler_contenu` ; les outils le fournissent toujours. |
| `site` (images `images/<nom>.svg|png`, QA, paquet) | Aucune notion de provenance d'image | **Durci** : `construire_site`, `preparer_paquet`, `demander_publication` refusent une image du studio non approuvée ou un fond brut. |
| `moderation` (visages, plaques), `usine.controle_texte`, `brand` | Logique pure, profil de marque versionné | **Réutilisés** : le texte libre d'un brief passe le garde-fou de texte public ; la marque vient du profil de marque, posée par l'outil. |
| Coffre de secrets, `journal_chaine`, file d'approbation, `_proprietaire_qui_decide` | Établis | **Réutilisés** (chaîne de hachage des registres, qui décide un N3). |
| `ocr_profil`, `ocr_runtime` (profil OCR) | Opt-in, PDF seulement, bundle absent ici | **Adaptateur** `LecteurOCRProfil` (PNG emballé dans un PDF d'une page). Non exécuté. |
| Pillow, reportlab, WeasyPrint | Pillow et reportlab dans le verrou d'exécution (extras), WeasyPrint absent ; aucun dans l'extra `dev` | **Non utilisés** : rendu raster, SVG et PDF en Python pur (`toile.py`, `rendus.py`) ; M7 interdit déjà les dépendances lourdes. |

## 2. Architecture en une page

```
 brief créatif (données structurées) ──► m7_preparer_brief_creatif (N2) ──► briefs_studio (journal chaîné)
        │  la marque vient du profil de marque ; éléments critiques typés ; français d'abord
        ▼
 m7_demander_fond_studio (N2) ──► registre de fournisseurs + politique de licence ──► jobs_studio (DEMANDE seulement)
                                                                                        │
                       exécuteur HORS transaction (non branché) ◄───────────────────────┘
                       re-sélection du modèle · adaptateur par le port · sortie revérifiée
                                   │  provenance_studio (modèle, version, graine, invite, licence, empreintes)
                                   ▼
                          actifs_studio : fond_brut (jamais publiable)
                                   │
 m7_composer_visuel_studio (N2) ◄──┘   gabarit déterministe : texte, logo et mentions posés par le gabarit
        ▼                              polices OFL épinglées · fond perdu · zone de sécurité · SVG + PNG (+ PDF)
 m7_controler_visuel_studio (N2)       lecture de la SORTIE · contraste · prépresse · licence revérifiée · rapport SIGNÉ
        ▼
 m7_demander_revue_visuel_studio (N2)  refusé si un constat critique échoue
        ▼
 m7_approuver_visuel_studio (N3)       décision de PERSONNE (propriétaire) liée aux empreintes de la composition ET du rapport
        ▼
 visuel « approuvé » ──► sas social (média « composition_deterministe » = visuel approuvé, sinon refus)
                     └─► site (image du studio = visuel approuvé, sinon refus ; fond brut jamais)
```

Principe : **aucun outil d'agent n'appelle un modèle, un réseau, une imprimerie ni un réseau social.** « Générer » consigne une
demande ; l'approbation consigne une décision (`VISUEL_APPROUVE_NON_PUBLIE`) ; rien ne part.

## 3. Le brief créatif

Schéma `opsys.studio.brief/v1` (`studio/brief.py`), validé en code, champ par champ, fail-closed (champ inconnu, type faux,
valeur hors liste : refus `REJ-STUDIO-BRIEF-*` avec chemin ; jamais une valeur corrigée).

| Champ | Contenu |
|---|---|
| `fictif` | Obligatoire. Un brief fictif n'accepte que des coordonnées fictives (téléphone 555-01XX, domaine réservé). |
| `objet`, `gabarit`, `format`, `canal` | Ce qu'on fabrique et où : `carte_affaires`, `affiche`, `banniere_social`, `couverture` ; canal compatible avec le gabarit. |
| `marque` | `{nom, couleurs #RRGGBB, langue « fr », empreinte_profil}` : **posée par l'outil** depuis le profil de marque existant (`brand.registre.lire_snapshot_marque`) ; un agent qui la fournit est refusé (`REJ-STUDIO-BRIEF-MARQUE-FOURNIE`). |
| `langues`, `textes` | `["fr"]` ou `["fr", "en"]` (français toujours premier) ; `titre` (obligatoire), `sous_titre`, `appel_action`. Le texte français passe le garde-fou de texte public (adresse, coordonnées, prix, garantie, exagération…). |
| `elements_critiques` | `telephone`, `courriel`, `adresse`, `licence_rbq`, `neq`, `prix`, `site_web` : **données structurées** `{type, valeur, source}` (le prix ajoute `valide_jusqu_au`). Forme validée (regex ASCII : un chiffre arabe-indien est refusé), caractères de contrôle, bidirectionnels et de largeur nulle refusés (attaque d'homographe). Jamais confiés à un modèle : le gabarit les pose, le contrôle les relit. |
| `mentions_obligatoires` | Textes posés **mot pour mot**. Les mentions exigées par la licence d'un modèle (ex. « Powered by … ») s'y ajoutent (constat `QC-MENTION-LICENCE`). |
| `fond` | `uni`, `degrade` (aucun modèle, donc aucune IA) ou `genere` : `sujet`, `ambiance`, `rendu`, `graine`. Un sujet qui nomme un logo, un texte, un slogan, une marque tierce ou « dans le style de » est refusé (heuristique par mots, fail-closed). |
| `couleur`, `ppp`, `logo_actif_id` | Profil couleur demandé (`rvb`, `cmjn` : **non réalisé**, section 12), résolution, logo approuvé à poser. |

**Contraintes légales.** Le français doit être « nettement prédominant » dans l'affichage commercial au Québec (R5 §5.4, Charte de
la langue française). Le seuil chiffré n'est pas établi (R5 §12 n°8, décision d'architecte r2 n°6) : le contrôle applique un
SEUIL PARAMÉTRABLE (`PolitiqueControle.ratio_francais_min`, 2,0 par défaut : surface du français / surface de l'autre langue),
**déclaré heuristique dans chaque rapport**, et la personne qui approuve un visuel bilingue atteste la prédominance
(`langue_francaise_validee`). **À valider par un avocat.**

## 4. Registre de modèles et politique de licence

Le registre est `opsys.fournisseurs` (capacités `image` et `video`, sélection par département, activation sous
`politique.evaluer`). Le studio l'appelle sans le copier :

- `modeles.selectionner(cnx, capacité)` : `registre.resoudre` (sélection de `m07-marketing`, sinon défaut global ; un
  fournisseur inactif ou devenu non conforme est un **refus** `REJ-STUDIO-MODELE-<code>`, jamais un repli) puis
  `politique.evaluer` ;
- l'**instantané de licence** qui entre à la provenance : bloc de licence du modèle, verdict de la politique, empreinte et
  révision du profil du client. Le profil lui-même (revenu déclaré compris) n'est pas recopié : un agent qui lit la
  provenance ne lit pas le chiffre d'affaires ;
- la licence est **revérifiée à chaque étape qui compte** : demande, exécution, composition, contrôle qualité
  (`QC-LICENCE`, échec si aucun verdict n'est fourni) et approbation (`REJ-STUDIO-LICENCE-NON-CONFORME`). Un revenu passé
  au-dessus d'un seuil, un territoire ajouté ou une désactivation invalident un fond déjà généré ;
- un fournisseur déclaré après coup (Nexora, un modèle absent du catalogue) passe par `registre.configurer(declaration=…)` et
  la même politique.

### Matrice des licences des modèles par défaut

Tirée du catalogue (R5 §1.1 et §2.1, niveaux de preuve de la recherche : [V] vérifié, [S] supposé ; **la revue trimestrielle
des licences reste à planifier**). Un test compare cette table au catalogue (`tests/studio/test_matrice_doc.py`).

| Modèle (id du catalogue) | Capacité | Statut | Licence des poids | Usage commercial | Seuil de revenu | Territoires exclus | Service à des tiers | Mention exigée | Texte intégral lu |
|---|---|---|---|---|---|---|---|---|---|
| `image.flux2-klein-4b.local` | image | adopte | Apache-2.0 | oui | — | — | autorise | — | oui |
| `image.qwen-image-2512.local` | image | adopte | Apache-2.0 | oui | — | — | autorise | — | oui |
| `image.qwen-image-edit-2511.local` | image | adopte | Apache-2.0 | oui | — | — | autorise | — | oui |
| `image.qwen-image-layered.local` | image | adopte | Apache-2.0 | oui | — | — | autorise | — | oui |
| `image.seedvr2.local` | image | adopte | Apache-2.0 | oui | — | — | autorise | — | oui |
| `image.z-image-turbo.local` | image | adopte | Apache-2.0 | oui | — | — | autorise | — | oui |
| `image.recraft-v4.1.api` | image | repli | Propriétaire (API) | sur contrat | — | — | incertain | — | oui |
| `image.flux3-image-klein.local` | image | conditionnel | FLUX Kommunity License v1.0 | sous seuil | 5 000 000 USD | — | incertain | — | non (à lire) |
| `image.bria-fibo-2.0-dev` | image | ecarte | CC BY-NC 4.0 (commercial sur contrat Bria) | **non** | — | — | interdit | — | oui |
| `image.flux1-dev` | image | ecarte | FLUX [dev] Non-Commercial License v2.0 | **non** | — | — | interdit | — | oui |
| `image.qwen-image-2.1` | image | ecarte | Qwen Research License | **non** | — | — | interdit | — | oui |
| `video.wan-2.2.local` | video | adopte | Apache-2.0 | oui | — | — | autorise | — | oui |
| `video.hunyuanvideo-1.5` | video | ecarte | Tencent Hunyuan Community | oui | — | UE, UK, KR | incertain | nommer le fournisseur réel (Tencent HunyuanVideo) | oui |
| `video.minimax-h3` | video | ecarte | MiniMax H3 Community License (2 août 2026) | oui | 20 000 000 USD | UE, UK, KR, US | incertain | MiniMax H3 | oui |
| `video.remotion` | video | ecarte | Licence maison : gratuite ≤ 3 employés, sinon Company License | sur contrat | — | — | interdit | — | oui |

Lecture : « adopte » = pile par défaut ; « repli » = API ; « conditionnel » = actif seulement si la politique l'accepte et
qu'un administrateur a lu la licence ; « ecarte » = refusé par la politique (raison citée au registre). Les drapeaux sont ceux de
`opsys.fournisseurs.modele.Licence` : `usage_commercial`, `seuil_revenu_usd`, `territoires_exclus`, `service_tiers`,
`mention_obligatoire`, `verification`. **Qui est le « licencié »** quand OPSYS génère pour plusieurs PME (R5 §12 n°1) reste une
question juridique ouverte : le profil déclare `heberge_pour_tiers` et la politique refuse (`SERVICE_TIERS_INCERTAIN`) une licence
dont le droit n'est pas établi. **À valider par un avocat.**

Modèles de R5 absents du catalogue (déclarables par `registre.configurer(declaration=…)`, jamais actifs par défaut) : Stable
Diffusion 3.5 (seuil 1 M$ [V2]), Krea 2 (seuil 1 M$, cessation immédiate au franchissement [V2]), LTX-2.x (seuil 10 M$, interdit de
retirer les marquages IA [V]), HiDream-I1 (MIT, mais encodeur Llama-3.1 sous licence Llama [S]), Chroma1-HD, MOSS-Image, Mochi 1,
CogVideoX (conditions à lire [I]).

## 5. Génération : ports, doubles, invite, graine, provenance, marquage

- **Ports** (`studio/generation.py`) : `GenerateurImage` et `GenerateurVideo` (`generer(demande) -> SortieGeneration`), chacun
  avec sa `nature` (`reel` ou `double`). `ADAPTATEURS_DE_PRODUCTION` est **vide** : aucun adaptateur réel n'est livré ; un
  fournisseur sélectionné sans adaptateur est un échec typé (`REJ-STUDIO-ADAPTATEUR-ABSENT`), jamais un repli sur un autre.
- **Doubles** : `GenerateurImageDouble` (PNG synthétique) et `GenerateurVideoDouble` (APNG). Même demande, mêmes octets :
  la graine est rejouable. Un brief **non fictif refuse un générateur double**.
- **Invite** : construite par le code à partir de champs structurés ; cadre fixe « aucun texte, aucun logo, aucune signature »
  et invite négative ; ni nom de marque ni coordonnées.
- **Séparation outil / exécuteur** (`studio/executeur.py`) : l'outil consigne une demande (`jobs_studio`) ; l'exécuteur, hors
  transaction (un secret du coffre ne se résout pas dans une transaction métier), refait la sélection, refuse tout remplacement de
  modèle (`REJ-STUDIO-MODELE-CHANGE`), appelle l'adaptateur, **revérifie la sortie** (PNG lisible, dimensions, graine rendue,
  modèle et version déclarés), écrit la provenance puis l'actif `fond`. Trois échecs closent la demande ; les messages d'erreur sont
  masqués (secrets) et tronqués. **Aucun planificateur ne l'appelle** dans cette version.
- **Provenance** (`provenance_studio`, journal chaîné append-only) : modèle, version, référence des poids, graine, invite et
  invite négative, paramètres, nature du générateur, instantané de licence, empreinte de la demande, SHA-256 de la sortie. L'empreinte
  de chaîne du maillon est l'**empreinte de provenance** reportée dans les métadonnées du visuel.
- **Marquage « généré par IA »** : calculé du brief et de la provenance (jamais fourni) et écrit dans le PNG (`tEXt`), le SVG
  (`<metadata>`) et le PDF (`Info` + XMP) ; `QC-MARQUAGE-IA` vérifie la cohérence des trois. La **divulgation** est exigée par le sas
  social : `media_synthetique_realiste` est calculé des médias (`ia_generee` et `realiste`), qui viennent du REGISTRE du studio
  (`realiste` est une attestation de la personne qui approuve).

## 6. Composition déterministe

Un gabarit transforme brief + police + fond en `plan.Plan` (coordonnées en pixels) ; le SVG, le PNG et le PDF sont trois rendus du
MÊME plan. Le texte n'est jamais modifié : il est envoyé à la ligne sur les espaces (une adresse d'abord après les virgules) ou
refusé (`REJ-STUDIO-TEXTE-NE-TIENT-PAS`) ; jamais tronqué, jamais coupé au milieu d'un mot, jamais sous la taille minimale.
Le texte vit sur un panneau de la couleur primaire de la marque : le contraste ne dépend pas du fond.

| Gabarit | Format | Dimensions | Fond perdu / sécurité | Résolution | Texte minimal | Source |
|---|---|---|---|---|---|---|
| `carte_affaires` | `3.5x2` | 3.5 × 2 po (fini) | 0.125 po / 0.125 po | 300 ppp (minimum 300) | 7 pt | R5 §4.2 l.270 [S] |
| `affiche` | `11x17` | 11 × 17 po (fini) | 0.125 po / 0.25 po | 150 ppp (minimum 150) | 12 pt | R5 §4.2 l.276 [S] ; texte minimal 12 pt : heuristique |
| `affiche` | `18x24` | 18 × 24 po (fini) | 0.125 po / 0.25 po | 150 ppp (minimum 150) | 12 pt | R5 §4.2 l.277 [S] |
| `banniere_social` | `1200x627` | 1200 × 627 px | — / 5% | écran | 2,1 % de √(L×H) | R5 §4.2 l.279 [S] |
| `banniere_social` | `1080x1350` | 1080 × 1350 px | — / 5% | écran | 2,1 % de √(L×H) | R5 §4.2 l.279 [S] |
| `banniere_social` | `1080x1080` | 1080 × 1080 px | — / 5% | écran | 2,1 % de √(L×H) | R5 §4.2 l.279 [S] |
| `banniere_social` | `1280x720` | 1280 × 720 px | — / 5% | écran | 2,1 % de √(L×H) | R5 §4.2 l.279 [S] |
| `banniere_social` | `1080x1920` | 1080 × 1920 px | — / 5% ; bandes réservées haut 14%, bas 20% | écran | 2,1 % de √(L×H) | R5 §4.2 l.279 [S] ; bandes d'interface [S] |
| `couverture` | `1640x624` | 1640 × 624 px | — / 5% | écran | 2,1 % de √(L×H) | dimension courante d'une couverture (2×820×312) [S] |

Hypothèses de mise en page de R5 §4.2, niveau [S] : **à confirmer auprès de l'imprimeur**. Texte minimal de 12 pt sur affiche :
heuristique de cette tranche. Zone de sécurité des bandes d'interface du 9:16 : [S].

- **Polices OFL uniquement** (`studio/polices.py`) : dossier `$OPSYS_HOME/studio/polices/` avec un manifeste `polices.json`
  (`id`, `famille`, `fichier`, `sha256` **épinglé**, `licence = OFL-1.1`, `source_url` https, `fictif`) écrit par un administrateur.
  Refus : autre licence, fichier dont la table `name` ne mentionne pas la SIL Open Font License, empreinte différente, chemin dans le
  nom, lien symbolique, police `fictif` en production. **Aucune police n'est livrée** : sans manifeste, le studio refuse de composer.
  Un caractère sans glyphe est refusé, jamais remplacé.
- **SVG** : texte vivant, police nommée **non incorporée** (aperçu éditable ; le rendu de référence est le PNG/PDF). Tout texte est
  échappé ; le lecteur `lire_svg` refuse contenu actif, entité, doctype, image externe.
- **PNG** : rendu par un rastériseur de contours TrueType en Python pur (remplissage par enroulement non nul, sous-échantillonnage 4×,
  glyphes posés à l'abscisse entière : déterministe au pixel près). C'est la sortie qui part vers un réseau.
- **PDF d'impression** : 1.4 écrit à la main, `MediaBox` (fond perdu compris), `TrimBox`, `BleedBox`, image de fond `DeviceRGB`,
  **texte converti en courbes** (R5 : « texte vectorisé » est un prépresse acceptable) enveloppé dans `/ActualText`, `Info` et XMP.
  **Ce n'est pas un PDF/X** (aucun `OutputIntent`, aucun CMJN) et il n'a été validé par aucun preflight : voir la section 12.
- **Logo** : chemins vectoriels du sous-ensemble `M L H V C Q Z` absolus, posés par le gabarit, en couleur de texte ; un logo non
  approuvé ne se pose pas.

## 7. Contrôle qualité avant la revue humaine

`studio/controle.py` : un rapport de constats `QC-*` (critiques ou avertissements), **signé par son empreinte SHA-256** (JSON
canonique). Un seul constat critique en échec rend le rapport non conforme : le visuel **ne peut pas passer en revue**
(`REJ-STUDIO-REVUE-CONTROLE-NON-CONFORME`). L'approbation porte l'empreinte du rapport : un rapport retouché, forgé (verdict
incohérent avec les constats), ou d'une autre composition est refusé.

| Constat | Ce qui est vérifié |
|---|---|
| `QC-ELEMENTS` | Les éléments attendus sont tirés du BRIEF (marque, textes, éléments critiques avec libellé, mentions) et le plan en porte exactement les mêmes, texte pour texte : une mention retirée ou un chiffre changé par un gabarit défectueux est pris. |
| `QC-OCR` | La SORTIE de chaque format (PNG, SVG, PDF) est relue par un `LecteurOCR` ; **zéro écart** (espaces normalisées, rien d'autre) ; tout texte lu hors des zones attendues est un échec. Format sans lecteur, lecteur qui échoue : échec (`QC-OCR-ABSENT`), jamais un saut. |
| `QC-INCONNU-CRITIQUE` | Tout téléphone, courriel, prix, licence RBQ, NEQ ou adresse web lu dans la sortie et absent du brief (texte halluciné par un fond) est un échec. |
| `QC-CONTRASTE` | Contraste WCAG AA (4,5:1 ; 3:1 au-delà de 18 pt) mesuré sur les PIXELS du PNG livré, hors encre, 5e et 95e centiles. |
| `QC-TAILLE-MIN`, `QC-ZONE-SECURITE` | Aucun texte sous la taille minimale ; tout texte et le logo dans la zone de sécurité et hors des bandes réservées. |
| `QC-FOND-PERDU`, `QC-RESOLUTION` | Fond perdu d'au moins 0,125 po, `TrimBox` et `BleedBox` du PDF relues et conformes ; résolution effective du fond (≥ 300 ppp carte, ≥ 150 affiche ; agrandissement ≤ 2× à l'écran) ; rendu d'impression sous le minimum refusé. |
| `QC-LANGUE-FR` | Surface du français / autre langue ≥ seuil paramétrable. **Heuristique, à valider par un avocat.** |
| `QC-MARQUAGE-IA` | Marquage cohérent dans PNG, SVG, PDF et avec la nature du fond ; provenance présente pour un fond généré. |
| `QC-LICENCE`, `QC-MENTION-LICENCE` | Licence du modèle revérifiée au moment du contrôle (**sans verdict : échec**) ; mention exigée par la licence présente dans les mentions. |
| `QC-PRIX-VALIDITE` | Aucun prix expiré. |
| `QC-POLICES` | Polices OFL épinglées, tous les glyphes présents. |
| `QC-REPRODUCTIBILITE` | Le plan, refait avec le fond et les polices, redonne EXACTEMENT les artefacts (pixels du PNG, octets du SVG et du PDF) : un fichier retouché ou remplacé sur le disque est pris. |
| `QC-FORMAT` | Jeu d'artefacts attendu (SVG et PNG ; PDF pour l'impression). |
| `QC-COULEUR` (avertissement) | Profil couleur déclaré : RVB (sRGB). Une demande CMJN est dite NON réalisée (le constat ne bloque pas la revue ; la conversion et le preflight reviennent à l'imprimeur). |

### Quel OCR a lu quoi

| Lecteur | Format | Nature | Ce qu'il fait réellement |
|---|---|---|---|
| `LecteurGabaritsPixels` | PNG | **double** | Lit les PIXELS : isole l'encre dans la zone de chaque ligne (indices du plan : zone, police, taille, couleur ; jamais le texte), découpe par colonnes, apparie chaque glyphe par recouvrement pondéré avec le glyphe rendu par la même police, replace les espaces par les avances. Un chiffre faux dans le PNG est lu faux. **Limites** : ne lit que les zones indiquées (un texte halluciné ailleurs ne le concerne pas) et que les polices du registre. |
| `LecteurTexteVectoriel` | SVG, PDF | **double** | Extrait le texte vivant du SVG et les `/ActualText` du PDF : atteste ce que l'artefact DÉCLARE, pas ce qu'il dessine. |
| `LecteurOCRProfil` | PDF, PNG emballé en PDF | **réel (non exécuté ici)** | Appelle `opsys.ocr_runtime.extraire_candidat` (Tesseract + pdfium, bubblewrap, bundle validé). Testé avec une fonction simulée ; jamais lancé. |

**Un visuel NON fictif ne s'approuve pas sur la lecture d'un double** (`REJ-STUDIO-OCR-REEL-REQUIS`) ni avec un fond d'un
générateur double : sur cette machine, aucun visuel réel ne peut donc être approuvé. C'est voulu : brancher le profil OCR (PDF) est
la première tâche avant tout usage réel.

## 8. Revue, approbation et portes du sas social et du site

États (`studio/actifs.py`, journal `actifs_studio` chaîné) : `fond_brut` (terminal) ; `compose → controle_conforme | controle_echec →
en_revue → approuve → revoque` ; `rejete`. L'**approbation** (`m7_approuver_visuel_studio`, N3) est une décision du propriétaire
(`nathan_owner`, établi par la plateforme : jamais un argument), liée à l'empreinte de la composition ET à celle du rapport,
avec des **attestations** de la personne : éléments critiques vérifiés à la source, aucun visage ni plaque identifiable, rendu
relu, allure réaliste ou non (`realiste`, qui fonde la divulgation d'IA), langue française validée si bilingue. La licence est
revérifiée à ce moment. Un journal altéré ou incohérent refuse tout.

**Portes** (`studio/portes.py`, règles pures appliquées par les sas existants) :

| Porte | Refus |
|---|---|
| Sas social, média « composition déterministe » | `REJ-SOCIAL-MEDIA-ACTIF-INCONNU` (pas un visuel du studio), `…-NON-APPROUVE` (état, fond ou logo seul), `…-ACTIF-INCOHERENT` (format, octets, dimensions différents du registre), `REJ-SOCIAL-MEDIA-IA-INCOHERENTE` (part d'IA ou allure réaliste différentes du registre) |
| Sas social, toute autre origine | `REJ-SOCIAL-MEDIA-ACTIF-ORIGINE-INCOHERENTE` : un actif du studio ne se présente jamais comme photo de chantier ou banque d'images |
| Registre altéré | `REJ-SOCIAL-ACTIFS-REGISTRE-ALTERE` : tout est refusé |
| Site | `REJ-SITE-IMAGE-STUDIO-NON-APPROUVE`, `REJ-SITE-IMAGE-STUDIO-FOND-BRUT`, `REJ-SITE-IMAGE-STUDIO-REGISTRE-ALTERE` |
| Point de sortie du sas | Le contrôle est refait avec le résolveur : un visuel révoqué entre l'approbation et l'envoi ne part pas |

`m7_lire_studio(media_sas=true)` rend le média d'un visuel approuvé, avec les faits du registre. Limites : une image du studio
**réencodée** (autre SHA-256) n'est pas reconnue ; le site n'a **aucun champ de divulgation d'IA** (l'export le rappelle).

## 9. Logos

`studio/logos.py` : port `Vectoriseur` (raster → chemins du sous-ensemble `vecteur.py`), `VectoriseurDouble` (rectangles par
plages fusionnées : ni courbes ni lissage), logo écrit par un agent (chemins fournis), SVG sûr (aucun script, aucune image, aucune
police), déclinaisons monochrome et négatif, contrôle de forme signé (≤ 200 chemins, lisible à 16 px, ni vide ni empâté,
avertissement présent).

**AVERTISSEMENT (dans chaque sortie : concept, SVG, rapport, approbation) :** un logo généré ou vectorisé automatiquement n'a
**aucune protection juridique garantie** ; le droit d'auteur sur une œuvre générée sans apport humain suffisant est incertain
(États-Unis, Canada ; R5 §5.3) ; rien ici ne vaut recherche d'antériorité ni dépôt. La voie est la **marque de commerce**, à
valider par un agent de marques ou un avocat. L'approbation d'un logo exige une note de contribution humaine (20 à 600
caractères), l'attestation de lecture de l'avertissement et la mention de la recherche d'antériorité (« faite » ou « renvoyée à un
agent de marques »).

**Plan vtracer / svgo (non installés, non exécutés)** : adaptateur derrière `Vectoriseur` qui appelle `vtracer` (MIT, couleur) en
sous-processus, normalise sa sortie vers le sous-ensemble (commandes absolues, aucune transformation ni style), passe `svgo` (MIT),
convertit la police OFL en chemins, produit horizontale, empilée et monogramme (travail de conception humain), puis recherche
d'antériorité assistée (OPIC, USPTO, WIPO).

## 10. Vidéo courte

Réalisé : port `GenerateurVideo`, `GenerateurVideoDouble` (APNG), sélection de la capacité `video` par le registre (Wan 2.2 adopté,
HunyuanVideo et MiniMax refusés par territoire), provenance, marquage. **Non réalisé** : l'habillage (titre, mentions,
sous-titres), le montage et la voix, qui exigent un montage déterministe (FFmpeg, Revideo ou MoviePy ; FFmpeg est absent de la
machine). Un clip n'existe donc que comme **fond brut** : le sas le refuse (`genere_non_compose` ; aucun visuel vidéo n'est
composé) et le site aussi.

## 11. Nexora Creative (fournisseur externe optionnel)

`studio/nexora.py` : `PortNexora` (contrat générique de R5 §7.3 : `capacites`, `soumettre` idempotent, `statut`, `artefacts`),
`NexoraDouble` (aucun réseau), `GenerateurNexora` (fait de Nexora un `GenerateurImage` du registre) et
`declarations_depuis_capacites`. **Aucune information privée sur Nexora n'a été consultée** et le transport réel (REST ou MCP)
n'existe pas.

Gouvernance : chaque modèle annoncé devient une déclaration personnalisée `verification="a_lire"`, `residence="inconnue"` (EFVP
requise) ; rien ne s'active seul. Un artefact d'un AUTRE modèle que celui demandé est refusé (aucun remplacement silencieux) ;
PNG exigé ; modèle et licence déclarés pour chaque sortie ; basculer vers un autre fournisseur = changer la sélection du registre.

Plan : 1) fiche de capacités fournie par Nathan (R5 §12 n°13) ; 2) transport REST (jeton par locataire dans le coffre, en-tête
`Idempotency-Key`, webhooks signés HMAC) derrière `PortNexora`, adaptateur de nature `reel` ; 3) tests de contrat dans la CI ;
4) un administrateur lit les licences, consigne l'EFVP et active sous la politique ; 5) l'exécuteur passe par la file de travaux.

## 12. Impression : ce qui est réalisé et le plan pour le reste

Réalisé : fond perdu de 0,125 po, zone de sécurité, boîtes de page, texte vectorisé, texte minimal, résolution du fond, profil
couleur **déclaré RVB** (le brief peut demander `cmjn` : la composition reste en RVB et le dit).

**Non réalisé, plan documenté** : CMJN et PDF/X-4 par WeasyPrint ≥ 67 (BSD-3, `--pdf-variant pdf/x-4`), conversion des images par
Little CMS, boîtes et `OutputIntent` vérifiés par pikepdf (MPL-2.0), profil ICC fourni par l'imprimeur (la redistribution de
GRACoL/SWOP est [I]), noir 100 % K pour le petit texte, limite d'encrage ; **aucun validateur PDF/X libre n'est connu** (R5 §12
n°6) : le preflight de l'imprimeur (ou callas) reste la barrière, et une épreuve imprimée est validée à l'œil. Ghostscript
(AGPL) n'est pas utilisé.

## 13. Outils M7 et portées

Dix outils, **aucun rôle d'appareil** (`ROLES.md`) :

| Outil | Niveau | Rôle |
|---|---|---|
| `m7_preparer_brief_creatif` | T1 / N2 | valider et consigner un brief ; marque posée par l'outil ; idempotent par clé |
| `m7_demander_fond_studio` | T1 / N2 | consigner une demande de fond ; modèle choisi par le registre ; aucun modèle appelé |
| `m7_composer_visuel_studio` | T1 / N2 | composer par gabarit (SVG, PNG, PDF) ; fond et logo approuvés seulement |
| `m7_controler_visuel_studio` | T1 / N2 | contrôle qualité signé ; nature du lecteur consignée |
| `m7_demander_revue_visuel_studio` | T1 / N2 | mettre en revue un visuel conforme |
| `m7_approuver_visuel_studio` | T1 / **N3** | approbation humaine ; consignée, jamais exécutée |
| `m7_retirer_visuel_studio` | T1 / N2 | rejeter ou révoquer |
| `m7_vectoriser_logo_studio` | T1 / N2 | concept de logo ; avertissement juridique |
| `m7_exporter_visuel_vers_site` | T1 / N2 | copier un visuel approuvé vers les actifs d'un site |
| `m7_lire_studio` | T0 | briefs, actifs, rapports, provenance, `media_sas` |

Registres (journaux génériques `opsys.stockage`, **aucune migration**, déclarés dans `memoire.ecriture`) : `briefs_studio`,
`jobs_studio`, `provenance_studio`, `actifs_studio`. Aucune commande CLI métier n'est ajoutée. Procédure d'ajout d'un outil :
manifeste (`department.yaml` : `memoire.ecriture`, `approbations`), niveau, portées d'appareil (`tests/test_portees_appareil.py`,
`ROLES.md`).

## 14. Ce qui n'est PAS prouvé

1. **Aucun vrai modèle n'a produit d'image** ; aucune mesure de qualité, de vitesse ou de mémoire (GB10 ou autre). Les licences
   sont celles de R5 au 2026-10-31, niveaux [V]/[S] ; rien n'a été relu à la source.
2. **Aucun OCR réel** n'a lu une sortie. Le double à pixels ne prouve que la chaîne (rendu → lecture → comparaison) sur la police
   de test et les polices du registre ; il ne lit pas le texte d'un fond.
3. **Aucune police OFL réelle n'a été utilisée** : les tests emploient une police fabriquée par le code (cases de 5×7 pixels,
   courbes et composites de test) ; le lecteur TrueType n'a pas été essayé sur Lato, Noto ou Source Sans (format 4 et 12, `glyf`
   simple et composite couverts par la police de test ; pas de CFF, ni de variations).
4. **Aucun PDF/X, aucun CMJN, aucun preflight d'imprimeur** ; le PDF n'a pas été ouvert dans un lecteur de PDF tiers (structure,
   `xref` et boîtes vérifiés par notre propre lecteur seulement).
5. **Aucune vidéo composée** ; FFmpeg est absent.
6. **vtracer et svgo n'ont pas tourné** ; le double de vectorisation est un traceur de rectangles.
7. **Nexora** : contrat générique seulement ; aucun transport, aucune fiche de capacités.
8. **L'exécuteur de génération n'est branché à aucun planificateur** ; aucun adaptateur de modèle réel n'existe.
9. **Le registre de fournisseurs n'est pas qualifié** (tout `a_mesurer`) et le profil de licence est déclaré par un humain.
10. **Juridique, à valider par un avocat** : seuil de « nettement prédominant », licencié des licences à seuil, protection d'un logo
    généré (marque de commerce), divulgation de l'IA, Loi 25 (EFVP avant tout transfert hors Québec).
11. Les contrôles de contenu (garde-fou de texte, détection de mots interdits dans le sujet d'un fond) sont des motifs, pas un
    jugement. Aucune détection de visage, de plaque, de marque de tiers ni de contenu inapproprié n'est faite sur le fond : la revue
    humaine l'atteste.
12. Une image du studio réencodée (autre SHA-256) échappe aux portes ; le site n'a pas de champ de divulgation d'IA.

## 15. Commandes

```bash
pytest departments/m07-marketing/tests/studio                       # le studio (462 tests, quelques minutes en Python pur)
pytest departments/m07-marketing/tests/sas_social departments/m07-marketing/tests/site \
       departments/m07-marketing/tests/test_outils_publication.py   # les sas durcis
pytest tests/test_paquets_declares.py tests/test_garde_fou_texte.py tests/test_commande_metier.py tests/test_portees_appareil.py
# l'exécuteur de génération (hors outil), avec le double de test : voir tests/studio/test_bout_en_bout.py
```
