# Bilan des corrections et raccords locaux — 30 septembre 2026

Le travail conserve la refonte récente de Claude et corrige les défauts reproduits avant
d'approfondir les départements. Il comporte **douze chantiers**, décrits dans le
[plan d'exécution](RESTRUCTURATION-2026-09-30.md). Les quatre anciens blocs de suivi en étaient
des regroupements. Aucun nombre de blocs ou de tests ne vaut complétion des dix départements.

Base : `2e56c0d5605dfe575bde9244f38924d5390f2674`, branche locale
`codex/restructuration-2026-09-30`. Les modifications restent non commitées. Le `main` audité
séparément était `fcb65bcf20980a0b36847dbd41808527ba616d52`.

## Ce qui a changé

- **Direction et règles** : préférence durable pour les briques existantes, recherche GitHub et
  GitLab avec licences/provenance, périmètre profond des dix modules, retrait du consensus de trois
  modèles et de l'attente d'un fournisseur extérieur pour développer. Les frontières humaines
  métier restent actives. Voir [directives](../produit/DIRECTIVES-NATHAN.md) et
  [périmètre](../produit/PERIMETRE-MODULES.md).
- **Invariants métier** : facture envoyée préservée lors d'une collision, stock non débité deux
  fois par changement de clé de transport, destinataire privé dérivé du principal, rôle et compte
  revalidés, mémoire/RAG isolés par portée, captures mobile conservées sous leur propriétaire.
  Un refus métier dans une enveloppe transport réussie reste un **échec** dans les approbations.
- **Exploitation** : providers natifs par défaut, LiteLLM explicite, secrets référencés, dépendances
  Python verrouillées et image moteur installée avec hashes; restauration de l'instance et
  sauvegarde Docker v3 corrigées. Compose utilise notre fork local, avec PostgreSQL, Valkey et
  LiteLLM optionnels. Les 63 tests d'installation passent sur moteur réel et core fictif.
- **Agents** : profils multiples, outils limités, budget/tours/retries/concurrence, console et
  migrations transactionnelles. Le runner embedded réserve avant le `StreamFn` des profils
  configurables et concilie l'usage connu. Un candidat abandonné avant admission ne crée pas de
  trou d'ordinal. La compaction générique des profils concernés est refusée tant qu'elle n'est pas
  comptabilisée. Les outils MCP privés ne sont pas proposés au modèle.
- **M10** : registres prompts/plans/décisions/postflights, sources Git, contexte avant/après travail,
  API/CLI et console. Audit des liens incomplets, contradictions et sources périmées, sans modifier
  la mémoire. Les sources trop grandes, non régulières ou symboliques sont refusées; les scans
  partiels gardent les coordonnées Git et M10 reste classé M10. Les champs secrets structurés
  sont masqués; un postflight sans plan reste conservé et signalé.
- **M1** : réception manuelle, appels manqués, messages vocaux, rappels et transferts avec contexte.
  La console accepte un WAV manuel borné; les fichiers temporaires sont fermés. L'adaptateur STT
  exige les consentements distincts, utilise l'endpoint configuré par l'opérateur et borne taille,
  durée et délai. L'identité est relue avant le transfert et avant l'import. Une panne conserve
  le rappel canonique. Les 50 tests du montage réel utilisent un STT fictif local, sans téléphone.
- **M7** : marque, observations growth, campagnes locales, réputation neutre et usine chantier vers
  contenus. Calendrier durable dans la console, validation du contenu et du créneau, export manuel
  après contrôle du consentement actuel. Aucun connecteur public n'est simulé comme opérationnel.
- **M5** : cash libre avec obligations documentées, décision d'achat comparant comptant/financement/
  location, calendrier paie/DAS/dette déclaré et TPS/TVQ versionné, console. Sans pièce fiscale
  utilisable, le montant est inconnu; un brouillon ne prouve pas zéro. Les calculs sur pièces
  reçues portent une couverture partielle, conservée et affichée aussi sur le mobile.
- **CI et ménage** : dix départements propres selon Ruff, M3 désormais linté en CI; tests Core
  d'admission ajoutés aux cibles, installation sans scripts de dépendances implicites. Les pages
  d'entrée et guides d'exploitation reflètent le défaut natif et les limites de validation.

## Preuves et contrôle qualité

Le [registre](REGISTRE-AUDIT-2026-09-30.md) conserve les 47 constats d'origine : **42 corrigés
localement, 5 partiels**. Les écarts trouvés durant l'implémentation sont suivis séparément. Une
correction locale n'est pas une validation de production ni une clôture de module.

Au **jalon R17**, avant les raccords supplémentaires décrits ci-dessous, le socle et les dix
suites ordinaires départementales totalisaient **16 506 tests Python passés,
105 sautés et aucun échec**. Le mobile passait **2 607 tests dans 118 suites**, avec typecheck.
Les tests Core sont rapportés séparément, sans somme de suites qui pourraient se chevaucher.

Les résultats finaux, empreintes et limites sont regroupés dans le
[dossier de vérification R17](../research/R17-2026-09-30/README.md). Les rapports rouges et les
exécutions interrompues restent distincts des résultats verts. Les fixtures et fournisseurs
simulés sont identifiés; aucune somme de tests chevauchants n'est présentée comme couverture.

## Raccords supplémentaires M7 et M10 — jalon R18

M7 lit désormais les événements canoniques M2, M3 et M5 et les expose dans la console de
performance par campagne. La période porte sur les associations de clients M2 observées,
en UTC, et non sur toutes les demandes marketing initiales. Les événements contradictoires ou
hors cohorte sont exclus explicitement. La marge constatée dans M5 reste distincte de l'argent
encaissé; les dépenses publicitaires, le coût par lead et le ROI demeurent inconnus.

M10 possède un job de consolidation développement distinct des outils métier, avec autorisation
humaine révocable, capacité de service dans un fichier privé et journal canonique des prises de
travail, rapports et checkpoints. La déclaration cron réutilise le runner de commandes natif du
Core, sans modèle. Le véritable Gateway local a exécuté une échéance sur des données synthétiques;
un rapport et son checkpoint sont présents et le rejeu conserve le même rapport sans doublon.
La console permet de lire les sources, empreintes, omissions et limites, puis de révoquer ou
renouveler le job. Une autorisation active ne signifie pas que le cron a été installé.

Ce lot de jobs exige **SQLite fichier sur le même hôte**. PostgreSQL, les conteneurs séparés,
un service système persistant et une nuit de production ne sont pas prouvés. Le job ne mesure
pas la complétion des départements ni une conscience; son modèle de soi distingue sources
observées et informations inconnues. La reconstruction préalable du canon reste intégrale.

Les preuves ciblées sont conservées dans [R18](../research/R18-2026-09-30/README.md), avec leurs
périmètres propres. Elles ne s'ajoutent pas au total historique R17 et ne sont pas additionnées
entre elles. Le nouveau raccord de tickets M2/M3 est encore en cours de validation et n'est
pas certifié par R18.

## Ce qui empêche une déclaration de complétion générale

La frontière de compte OS du shell agent reste à construire; le binding universel de la cible
métier n'est pas prouvé universellement; la tranche de huit mutations M2/M3 passe sa vérification
intégrée. L'admission runtime ne couvre pas les
agents historiques, les transports propres des plugins ou tous les déclencheurs. Elle borne des
tokens estimés, pas un montant CAD.

La mémoire développement reconstruit son journal canonique complet avant les plafonds d'analyse;
la consolidation planifiée reste limitée au raccord local SQLite décrit ci-dessus. Le retrieval
vectoriel et un score de rappel à grande échelle ne sont pas livrés.
La voix live, son modèle réel, STT/TTS, interruption et sandbox restent à valider. M7 exige encore
les connecteurs réels, l'attribution exhaustive, le ROI lié aux dépenses et le périmètre CMO complet.
M5 exige les tables
de paie et obligations officiellement sourcées, projections intégrées, scénarios CFO complets et
évaluations professionnelles; ses registres n'ont pas d'attestation générale d'exhaustivité.

L'image Docker officielle Core n'a pas été construite dans cet environnement limité en stockage
avec driver `vfs`; compilation et packaging locaux sont des preuves différentes. Aucun VPS neuf,
runtime Windows, téléphone réel ou CI distante de cette branche n'a été validé. La restauration
de plusieurs volumes n'offre pas de rollback distribué automatique. Les avis npm modérés du
mobile restent suivis. Aucune mise en production, publication, fusion ou action financière réelle
n'a été effectuée.

Les prochains lots suivent le plan : frontière d'exécution, couverture des chemins agents,
consolidation/évaluation mémoire, réception vocale progressive, mesure marketing et FinanceCore/CFO.
