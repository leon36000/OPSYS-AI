# M3-estimation

Estimation Intelligence — vision, mesures a bornes, prix/marge

Statut: LIVRÉ (S001 à S009 — les neuf stories du PRD sont implémentées et
testées vertes : validation des entrées (S001), qualification de la qualité
photo (S002), hiérarchie des références d'échelle (S003), garde anti-
précision-inventée / prix bloqué (S004), Monte Carlo déterministe (S005),
plancher rentable (S006), contrat de sortie EstimationV1 et devis_id (S007),
registre append-only estimé-vs-réel (S008), échappatoires D-032 et digest
quotidien déterministe (S009). Outils d'agent exposés dans
`src/m3_estimation/outils.py` (`m3_estimer_projet` et les outils unitaires).
Suite de tests et suite de mutation vertes (`departments/m03-estimation/tests`).)

Identité authentifiée (PLAN T1.4-c4, T2.3-d, puis T1.4-k2, docs/architecture/ROLES.md) : pendant un appel
d'appareil, la vue d'un devis vient du rôle confirmé en base (l'employé ne voit ni coût, ni marge, ni prix ;
`role` ne peut que restreindre). Depuis T1.4-k2, un vendeur ne lit (`m3_lire_devis`) et n'obtient le
brouillon (`m3_generer_soumission_brouillon`) que des devis des leads dont il est le propriétaire : M3 relit
ce propriétaire à la source du bus (`m2.lead_assigne`, publié par M2 à la qualification), jamais depuis les
arguments, et sans importer M2. Le devis d'un autre, celui d'un lead sans propriétaire connu et un devis
inconnu donnent le même refus (`REJ-DEVIS-INTROUVABLE`). L'admin et la voie des agents ne sont pas filtrés.

Soumission brouillon en PDF (PLAN T2.3-f, `soumission.py`, `soumission_pdf.py`) : `m3_generer_soumission_brouillon`
rend le brouillon d'un devis durable en HTML (défaut) ou en PDF (`format: "pdf"`). Les deux formats partent de
`soumission.contenu_client` (liste blanche : ni coût ni marge, jamais) et passent par les mêmes gardes de rôle et de
propriétaire. Le PDF est rendu par ReportLab (BSD-3-Clause, Python pur, aucune bibliothèque système), extra
`soumission` de `pyproject.toml` (`pip install -e ".[soumission]"`, déjà dans l'image Docker et le job M3 de la
CI) ; les tests le relisent avec `pypdf` (extra `dev`). Sans l'extra, un verdict dit d'installer l'extra
`soumission` : jamais un HTML renommé en PDF. Un champ requis absent, un horodatage sans fuseau, un montant qui
exigerait un arrondi ou un caractère hors Windows-1252 (jamais un carré « ■ » silencieux) donnent aussi un verdict
qui dit quoi fournir. Montants `Decimal` repris du devis et mis en forme à la québécoise (« 1 234,56 $ »), jamais
recalculés ; les taxes (TPS/TVQ) ne sont pas calculées par M3 (M5, §8) : le document dit « taxes en sus ». Tout
texte du client est une donnée : échappé, jamais interprété par ReportLab. Mêmes entrées, mêmes octets (mode
`invariant`, date de création tirée de l'horodatage du devis, jamais de l'horloge). La mention BROUILLON est sur
toute page : le devis ne modélise aucune approbation. La sortie de l'outil est en base64 (`contenu_base64`, avec
`taille_octets` et `empreinte_sha256`) et ne peut dépasser la sortie qu'un outil transmet sans troncature
(`jetons.LIMITE_SORTIE_DEFAUT`, de l'ordre de vingt lignes selon la longueur des descriptions) : au-delà, `REJ-SOUMISSION-PDF-TROP-VOLUMINEUX`, jamais un PDF
coupé. Ce format ne part nulle part : l'envoi au client est une décision du propriétaire (section suivante).

Revue et envoi d'un devis par approbation N4 (PLAN T4.7, M3.14, `revue_devis.py`, `m3_demander_envoi_devis`) :
le vendeur (ou l'admin) DEMANDE l'envoi d'un devis brouillon ; le propriétaire décide. L'outil est T2, **N4**,
ouvert à `seller` et à `admin` : `Capacites` ne l'exécute jamais sur cet appel, il met une demande dans la file
d'approbation et répond `en_attente_approbation` ; le devis reste `brouillon`. Seul `nathan_owner` décide
(`department.yaml/approbations.n4`, et l'app exige que la PERSONNE porte ce rôle : un `admin` qui ne l'est pas lit la
file, sans les arguments, et ne décide pas). Le devis approuvé ne part pas seul : `envoye` veut dire « approuvé pour
envoi », la livraison au client est à M1 (T2.1-c) et n'existe pas encore. Aucun outil d'envoi réel.
- **La revue** (`revue_devis.py`, module pur) dit POURQUOI regarder ce devis. Onze critères : prix sous le minimum
  rentable et alerte de plancher de l'estimation (ROUGES), confiance sous le seuil, mesure incertaine, photos
  insuffisantes, montant au-dessus du seuil, marge sous le seuil, chantier éloigné, service complexe, client à risque,
  donnée fournisseur absente (§7 M3, « validation humaine obligatoire si »). Chaque motif cite sa donnée et sa
  source : le devis (`prix_total`, `taux_marge`, lus tels quels), `contexte_revue` (faits recopiés de la réponse de
  `m3_estimer_projet`, dont `niveau_confiance_hierarchie`, ou connus d'une personne) et les seuils. Les comparaisons
  sont strictes (un devis exactement au seuil ne déclenche rien).
- **Les seuils** sont ceux de `department.yaml/configuration/revue_devis` (confiance minimale, montant maximal, marge
  minimale, distance maximale, minimum rentable), VIDES à dessein : un seuil vide ou invalide rend son critère « non
  évaluable » (« seuil à configurer : marge_minimale »), jamais un chiffre par défaut. Un fait absent est aussi « non
  évaluable » et dit quoi fournir : le silence n'est jamais « rien à signaler ». Un contexte fourni de travers (clé
  inconnue, type faux) refuse toute la revue. Une alerte rouge n'empêche pas l'envoi : le propriétaire la lit et
  décide (§7 M3.11, « jamais sous le minimum rentable sans alerte rouge et validation de Nathan »).
- **L'attente de la file porte les motifs.** M3 déclare une `attentes()` : une entrée `revue_envoi_devis` par demande
  en attente (de même `id` que la demande, N4), dont le résumé est la revue du devis d'aujourd'hui, l'alerte rouge
  d'abord, borné à ce que l'app montre (240 caractères ; le reste est compté, `+ 2 autres`). Elle disparaît quand la
  demande est décidée.
- **Approuvé**, le devis passe `envoye` UNE fois, à l'instant de la décision (l'horloge du socle, jamais une heure
  fournie), avec la personne, son rôle et la synthèse de la revue (codes seulement) au maillon ; `m3.devis_envoye`
  est publié dans la même transaction (`m3-devis-envoye-<devis_id>`, schéma fermé du catalogue : identifiants et
  `horodatage_envoi`, ni coût, ni marge, ni prix). Un devis déjà `envoye` est un rejeu : rien n'est écrit ni
  republié. M2 ne consomme pas encore cet événement : la relance de M2 (T2.3-c) repose toujours sur
  `m3.devis_sans_reponse` ; T4.9 branchera M2 sur `m3.devis_envoye`.
- **L'outil refuse de s'exécuter hors d'une décision** (`REJ-ENVOI-SANS-APPROBATION`) : il relit la demande que
  `approbations.decider` vient de réserver (mêmes arguments, approbateur `nathan_owner` actif). Le mode `autonome`
  n'met que N5 en file ; sans cette garde, un agent enverrait le devis seul.
- **Limite connue.** L'outil ne s'exécute qu'à la décision, sans l'identité de l'appareil du vendeur : le filtre par
  propriétaire de lead (T1.4-k2) ne peut pas s'y appliquer. Un vendeur peut donc demander l'envoi du devis d'un lead
  qui n'est pas le sien ; il n'apprend rien, et le propriétaire lit le devis, la revue et les faits avant d'approuver.
