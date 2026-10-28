# Lot 0 — inventaire factuel (SHA `3ab7692f`)

Synthèse de deux inventaires en lecture seule (producteurs M1–M8/M10, runtime natif), vérifiés sur les chemins cités.

## Ce qui existe déjà dans M9 (à réutiliser)
Registre de snapshots chaîné et durable, état consolidé et contradictions (même module + même instant), dossier de direction
sourcé, diagnostic temporel (âge ≠ fraîcheur), audit de citations déterministe, suivi de décision approuvé (N3) et clôture,
échéancier/bilan de suivis, briefing du matin borné, rapports de période et d'activité, console de lecture `/strategie…`.
24 outils M9, tous `admin` sur appareil. Tests : 673 (département) + 267 (11 fichiers socle) verts à la base.

## Producteurs (ce que M9 peut lire réellement)
| Source | Lectures T0 existantes | Lacune |
|---|---|---|
| M2 | `m2_lister_leads`, `m2_lister_relances`, digest | pas de valeur monétaire de pipeline, pas d'événement perdu/converti |
| M3 | `m3_lire_ecarts_estime_reel`, `m3_lire_devis`, apprentissage | pas de marge agrégée ni liste de devis entreprise |
| M4 | interventions, cédule semaine, retards/incidents, météo, préparation | pas de métrique de capacité ; absences/compositions console-seulement |
| M5 | `m5_etat_tresorerie`, `m5_prevoir_tresorerie`, rentabilité chantier, créances/dettes, dossier CFO | admin ; pas de projection 12/24 mois ni scénarios ; grant CFO 90 s |
| M6 | `m6_lire_disponibilite`, variance chantier, prix | aucun risque de rupture / hausse de prix calculé (M6.20 absent) |
| M7 | `m7_lire_performance_campagnes` | coût par lead et ROI toujours `None` |
| M8 | vue exécutive, mesures chantier/contenus, registre de métriques, provenance M5 | pas de paquet de preuves M8.17 ; deux régimes de version |
| M10 | paquet de contexte par affaire (4 couches), révisions, références | pas de vue entreprise ; FINANCIAL/SENSITIVE exclus ; rétention non décrite |

Vers M9 il n'existe que deux événements (M8) et aucun port de lecture. Les ports privés du socle sont codés pour M5 seulement
(`departements.py` `charger_outils`, `capacites.py` `ports_prives`). Aucune convention commune de temps/révision entre producteurs.

## Runtime natif (conseil, budget, approbations)
- Agents : profils SQL (`agents.py`) par département, outils restreints au département, limites tours/retries/concurrence ;
  l'agent de base `base-<dept>` est généré (`agents_base.py`). Aucun département multi-agents déclaré dans un manifeste.
- Budget : `admission_agents.reserver/concilier/liberer` appliquent plafonds, tours, retries et concurrence (tokens, pas des dollars) ;
  côté Core (TypeScript) la réservation précède chaque stream fournisseur. Statut documenté PARTIEL.
- **Aucun port Python ne demande un tour d'agent Core** ; `agents_declencheurs` projette seulement un `cron.add`. Briques privées M9 dans
  `core/` sans consommateur : `m9-private-prepared-stream.ts`, `m9-private-admission-binding.ts`, `m9-private-audit-source.ts`.
- Approbations : T0–T3/N0–N5, M9 en mode `ombre` (seuil N3), `liaison_cibles` (ticket scellé 120 s), idempotence `(appareil, clé)`.
- Planification : `planifications` génère un script `automatisations.sh` ; pas d'exécuteur trouvé hors cron profil agent (non qualifié).
- Backend modèle : références d'identifiants listées (noms seulement) ; aucune définie dans cet environnement, pas de `paliers.yaml`.
  **La qualification réelle du conseil est donc un gate** (pas un défaut du produit) ; les doubles prouvent seulement le protocole.
- Gardes M9 : `conformite.py` interdit réseau/horloge/aléa/littéraux de coût/imports `mN_`/clés `cause`, `responsable`.

## Lecture de la matrice
Voir `MATRICE-EXIGENCES.json` (`current_status`, `lot0_finding`). Aucune ligne retirée ; `initial_status` conservé.
