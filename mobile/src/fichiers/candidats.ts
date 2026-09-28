import type { TypeMimeFichier } from "./protocole";
import type { MutationOutbox } from "../outbox/types";

/**
 * Sélectionne, dans la file sortante, les mutations `photo_upload`(nature `apres`)/
 * `signature_capture` déjà CAPTURÉES localement (brouillon, `src/photos/service.ts`/
 * `src/signature/service.ts`) et prêtes à être ENVOYÉES par blocs (PLAN T1.4-f). Ce module ne
 * lit QUE la file sortante déjà en mémoire (`readonly MutationOutbox[]`) : aucun accès
 * fichier/réseau ici, entièrement pur et testable — la lecture des octets et l'envoi eux-mêmes
 * sont dans `envoiOrchestrateur.ts`/`service.ts`.
 *
 * Ne remplace ni ne modifie `src/m4/preuvesCompletion.ts::extraireReferencesPhotosLocales`/
 * `extraireReferenceSignatureLocale` (T1.4-e, inchangés, toujours utilisés tels quels pour
 * simplement COMPTER/LISTER les captures locales) : ce module renvoie le PAYLOAD complet
 * (uri/sha256/taille), nécessaire pour DÉCOUPER ET ENVOYER un fichier, pas seulement son id.
 */
export interface CandidatFichierM4 {
  readonly mutationId: string;
  readonly chantierId: string;
  readonly uri: string;
  readonly sha256: string;
  readonly tailleOctets: number;
  /** `null` si l'extension du fichier local n'est ni `.jpg`/`.jpeg` ni `.png` — CONTRAT FIXE
   * `m4_deposer_fichier` (`TypeMimeFichier`) : fail-closed en aval (`envoiOrchestrateur.ts`),
   * jamais un type deviné ou par défaut. */
  readonly typeMime: TypeMimeFichier | null;
}

/**
 * Déduit le type MIME réel depuis l'EXTENSION du fichier local — jamais deviné ni fixé en dur
 * dans ce module : `src/photos/service.ts` écrit toujours `.jpg` (capture `imageType: "jpg"`),
 * `src/signature/service.ts` écrit l'extension renvoyée par `extensionDepuisMimeType` (le VRAI
 * type MIME capturé depuis la DataURL — `.png` par défaut de `react-native-signature-canvas`,
 * `imageType || "image/png"`, `node_modules/react-native-signature-canvas/index.js`, jamais
 * surchargé par `signature.tsx`). Toute autre extension (`.svg`, `.bin`…) rend `null` : le
 * contrat `m4_deposer_fichier` n'accepte QUE image/jpeg ou image/png.
 */
export function deduireTypeMimeDepuisUri(uri: string): TypeMimeFichier | null {
  const minuscule = uri.toLowerCase();
  if (minuscule.endsWith(".jpg") || minuscule.endsWith(".jpeg")) {
    return "image/jpeg";
  }
  if (minuscule.endsWith(".png")) {
    return "image/png";
  }
  return null;
}

function texteChamp(valeur: unknown): string | null {
  return typeof valeur === "string" && valeur !== "" ? valeur : null;
}

function nombreChamp(valeur: unknown): number | null {
  return typeof valeur === "number" && Number.isFinite(valeur) ? valeur : null;
}

/** `null` si le brouillon est corrompu/incomplet (champ manquant ou mal typé) — fail-closed,
 * jamais un candidat inventé à partir d'un payload partiel. Ne devrait jamais arriver en
 * pratique : `src/photos/mutation.ts`/`src/signature/mutation.ts` construisent toujours ces
 * champs, mais un brouillon relu depuis SQLite après une future migration de schéma doit rester
 * défensif, même discipline que `src/m4/interventions.ts::estInterventionM4`. */
function versCandidat(mutation: MutationOutbox): CandidatFichierM4 | null {
  const uri = texteChamp(mutation.payload.uri);
  const sha256 = texteChamp(mutation.payload.sha256);
  const tailleOctets = nombreChamp(mutation.payload.taille_octets);
  if (uri === null || sha256 === null || tailleOctets === null) {
    return null;
  }
  return {
    mutationId: mutation.id,
    chantierId: mutation.chantierId,
    uri,
    sha256,
    tailleOctets,
    typeMime: deduireTypeMimeDepuisUri(uri),
  };
}

/** Photos `apres` d'un chantier — même filtre que `preuvesCompletion.ts::extraireReferencesPhotosLocales`
 * (nature "apres" uniquement : les photos "avant"/"pendant" ne sont jamais envoyées à M4, voir sa
 * docstring), payload complet. */
export function candidatsPhotosApres(mutations: readonly MutationOutbox[], chantierId: string): CandidatFichierM4[] {
  return mutations
    .filter(
      (m) => m.type === "photo_upload" && m.chantierId === chantierId && m.statut === "brouillon" && m.payload.nature === "apres",
    )
    .map(versCandidat)
    .filter((c): c is CandidatFichierM4 => c !== null);
}

/** Dernière capture de signature du chantier — même choix que
 * `preuvesCompletion.ts::extraireReferenceSignatureLocale` (une nouvelle capture remplace la
 * précédente côté écran). `null` si aucune signature capturée. */
export function candidatSignature(mutations: readonly MutationOutbox[], chantierId: string): CandidatFichierM4 | null {
  const signatures = mutations.filter((m) => m.type === "signature_capture" && m.chantierId === chantierId && m.statut === "brouillon");
  if (signatures.length === 0) {
    return null;
  }
  return versCandidat(signatures[signatures.length - 1]);
}
