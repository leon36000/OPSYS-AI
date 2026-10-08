import { construireReferenceFichier, lireContexteBlocFichier, validerRecuFichier, lireMutationsFichiers } from "./protocole";
import type { MutationOutbox } from "../outbox/types";

/** État LOCAL des reçus stricts. Même « complet » reste historique ; seul le préparer
 * après octets + query serveur sous capture actuelle donne pret live, jamais persisté. */
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

export function calculerEtatEnvoiFichier(mutations: readonly MutationOutbox[], chantierId: string, sha256: string): EtatEnvoiFichier {
  const enCours: EtatEnvoiFichier = { statut: "en_cours", reference: null, blocsEnvoyes: 0, nombreBlocs: 0 };
  // Snapshot complet : aucun getter du dépôt/sélecteur n'est exécuté en lisant les champs.
  const snapshot = lireMutationsFichiers(mutations); if (!snapshot) return enCours;
  const blocs = snapshot.filter(m => m.chantierId === chantierId && m.payload.empreinte_sha256 === sha256);
  if (!blocs.length) return { statut: "non_demarre", reference: null, blocsEnvoyes: 0, nombreBlocs: 0 };
  const contexts = blocs.map(lireContexteBlocFichier), premier = contexts[0];
  if (!premier || contexts.some(c => !c || Object.keys(premier.contexte).some(k => Reflect.get(c.contexte, k) !== Reflect.get(premier.contexte, k)))) return enCours;
  const nombreBlocs = premier.contexte.nombre_blocs;
  const recus = new Set(blocs.filter(m => validerRecuFichier(m)).map(m => lireContexteBlocFichier(m)?.index));
  if (blocs.some(m => m.statut === "echec_permanent")) return { statut: "echec_permanent", reference: null, blocsEnvoyes: recus.size, nombreBlocs };
  if (new Set(contexts.map(c => c?.index)).size !== blocs.length) return { ...enCours, blocsEnvoyes: recus.size, nombreBlocs };
  return { statut: recus.size === nombreBlocs ? "complet" : "en_cours",
    reference: recus.size === nombreBlocs ? construireReferenceFichier(sha256) : null, blocsEnvoyes: recus.size, nombreBlocs };
}
