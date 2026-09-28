import { construireReferenceFichier } from "./protocole";
import type { MutationOutbox } from "../outbox/types";

/**
 * État d'envoi d'UN fichier (une empreinte SHA-256, sur un chantier), calculé PUREMENT depuis
 * les mutations `fichier_bloc` déjà en file — jamais un appel réseau ici (voir
 * `envoiOrchestrateur.ts`/`service.ts` pour la lecture directe optionnelle de `m4_etat_fichier`,
 * utile pour la REPRISE après interruption, distincte de cette lecture LOCALE).
 *
 * `complet` est déterminé UNIQUEMENT par le statut `envoyee` de CHAQUE bloc attendu — jamais par
 * un appel à `m4_etat_fichier` : l'outbox (`src/outbox/vidangeur.ts`) ne marque `envoyee` qu'à
 * l'ACCUSÉ de réception du serveur pour ce bloc précis (R12 §4), donc « tous les blocs envoyee »
 * est déjà la même vérité que le serveur porterait dans `blocs_recus`/`complet` — recalculer
 * cette évidence par un appel réseau supplémentaire à chaque rendu d'écran serait un aller-retour
 * inutile (P11, économie de tokens/réseau).
 */
export type StatutEnvoiFichier = "non_demarre" | "en_cours" | "complet" | "echec_permanent";

export interface EtatEnvoiFichier {
  readonly statut: StatutEnvoiFichier;
  /** Non nul SEULEMENT si `statut === "complet"` — construite localement, jamais relue du
   * serveur (voir `construireReferenceFichier`, déterministe depuis l'empreinte). */
  readonly reference: string | null;
  readonly blocsEnvoyes: number;
  /** `0` tant qu'aucun bloc n'a encore été mis en file pour cette empreinte (`statut ===
   * "non_demarre"`) — jamais deviné avant le premier découpage réel. */
  readonly nombreBlocs: number;
}

function nombreBlocsDeclare(mutation: MutationOutbox): number | null {
  const valeur = mutation.payload.nombre_blocs;
  return typeof valeur === "number" && Number.isInteger(valeur) && valeur > 0 ? valeur : null;
}

export function calculerEtatEnvoiFichier(
  mutations: readonly MutationOutbox[],
  chantierId: string,
  sha256: string,
): EtatEnvoiFichier {
  const blocs = mutations.filter(
    (m) => m.type === "fichier_bloc" && m.chantierId === chantierId && m.payload.empreinte_sha256 === sha256,
  );

  if (blocs.length === 0) {
    return { statut: "non_demarre", reference: null, blocsEnvoyes: 0, nombreBlocs: 0 };
  }

  // Tous les blocs d'un même fichier portent la MÊME valeur (posée une seule fois au découpage,
  // envoiOrchestrateur.ts) — le premier bloc trouvé fait foi ; `null` (payload incohérent,
  // ne devrait jamais arriver) laisse `nombreBlocs` à 0, jamais une valeur devinée.
  const nombreBlocs = nombreBlocsDeclare(blocs[0]) ?? 0;
  const blocsEnvoyes = blocs.filter((m) => m.statut === "envoyee").length;

  // Un SEUL bloc en échec permanent condamne tout le fichier : redécouper et renvoyer les MÊMES
  // octets sous une NOUVELLE clé d'idempotence ne changerait pas l'issue d'un rejet business
  // (empreinte/type/taille), voir `envoiOrchestrateur.ts` — priorité sur "complet" même si les
  // AUTRES blocs ont déjà réussi : le fichier, dans son ensemble, ne peut plus jamais devenir
  // complet par cette voie.
  if (blocs.some((m) => m.statut === "echec_permanent")) {
    return { statut: "echec_permanent", reference: null, blocsEnvoyes, nombreBlocs };
  }

  if (nombreBlocs > 0 && blocsEnvoyes >= nombreBlocs) {
    return { statut: "complet", reference: construireReferenceFichier(sha256), blocsEnvoyes, nombreBlocs };
  }

  return { statut: "en_cours", reference: null, blocsEnvoyes, nombreBlocs };
}
