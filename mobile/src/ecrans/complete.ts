import { calculerEtatEnvoiFichier } from "../fichiers/etatEnvoi";
import { construirePreuvesCompletion } from "../m4/preuvesCompletion";
import type { PreuvesCompletionM4 } from "../m4/preuvesCompletion";
import type { MutationOutbox } from "../outbox/types";

/**
 * Logique PURE de `app/(employee)/job/[id]/complete.tsx` (« Terminer », R12 §5 étape 5, PLAN
 * T1.4-f), même discipline que `src/ecrans/job.ts`/`src/ecrans/punch.ts` : l'écran importe ce
 * module et ne fait lui-même que le câblage React.
 *
 * **Dépendance d'ordre obligatoire (mission item 2) : `evaluerPreparationCompletion` ne rend
 * JAMAIS `pret: true` tant qu'un seul fichier attendu (photos « après » + signature si présente)
 * n'est pas `complet` (`src/fichiers/etatEnvoi.ts`)** — la complétion ne peut donc structurellement
 * pas partir avant ses fichiers : il n'existe aucun chemin de code qui construise
 * `PreuvesCompletionM4` sans être passé par ce contrôle.
 *
 * **`signature_requise` : demandé explicitement à l'employé, jamais déduit.** Aucune donnée
 * serveur n'indique, pour un chantier donné, si une signature client est exigée (même absence
 * structurelle que le catalogue de checklist, voir `src/checklist/types.ts`) : plutôt que de la
 * déduire silencieusement de « une signature a-t-elle été capturée » (ce qui masquerait un cas où
 * une signature EST requise mais n'a pas pu être obtenue), `signatureRequise: boolean | null`
 * — `null` = pas encore choisi — bloque tant que l'employé n'a pas répondu explicitement, même
 * patron fail-closed que `champTechnicien` sur `job/[id]/index.tsx`. Documenté aussi dans
 * MOBILE.md.
 */
export type RaisonBlocageCompletion =
  | "checklist_incomplete"
  | "aucune_photo_apres"
  | "signature_requise_non_choisie"
  | "signature_requise_mais_absente"
  | "fichiers_en_echec"
  | "fichiers_en_cours";

export type EtatPreparationCompletion =
  | { readonly pret: false; readonly raison: RaisonBlocageCompletion }
  | { readonly pret: true; readonly preuves: PreuvesCompletionM4 };

export interface ParametresEvaluationCompletion {
  readonly checklistComplete: boolean;
  /** Empreintes SHA-256 de chaque photo « après » CAPTURÉE localement (`src/fichiers/candidats.ts
   * ::candidatsPhotosApres`, une par photo) — PAS des références serveur : celles-ci sont
   * résolues ICI depuis `mutations` (`src/fichiers/etatEnvoi.ts`), une fois chaque envoi
   * `complet`. */
  readonly photosApresSha256: readonly string[];
  /** `null` si aucune signature n'a encore été capturée (`candidatSignature` a renvoyé `null`). */
  readonly signatureSha256: string | null;
  /** `null` = pas encore choisi par l'employé (voir en-tête) — jamais un défaut deviné. */
  readonly signatureRequise: boolean | null;
  readonly notes: string;
  /** La file sortante COMPLÈTE (toutes mutations, tous chantiers) — filtrée en interne par
   * `calculerEtatEnvoiFichier`, même discipline que le reste de `src/fichiers`. */
  readonly mutations: readonly MutationOutbox[];
  readonly chantierId: string;
}

/**
 * Décide si « Terminer » peut construire et soumettre `PreuvesCompletionM4`, ou pourquoi pas
 * encore — fonction PURE, aucun accès réseau/fichier ici (l'ENVOI des fichiers manquants reste le
 * travail de `src/fichiers/envoiOrchestrateur.ts`, appelé séparément par l'écran AVANT
 * d'interroger cette fonction à nouveau). Ordre des contrôles, épinglé (même discipline que
 * `preuves.py::valider_preuves_completion`, lu) : checklist -> photos_apres non vide ->
 * signature_requise choisi -> signature présente si requise -> état d'envoi de CHAQUE fichier
 * attendu. Un SEUL échec permanent parmi les fichiers attendus bloque tout (`fichiers_en_echec`),
 * prioritaire sur « en cours » : reprendre la photo/signature en cause est la seule issue, pas
 * une nouvelle attente.
 */
export function evaluerPreparationCompletion(params: ParametresEvaluationCompletion): EtatPreparationCompletion {
  if (!params.checklistComplete) {
    return { pret: false, raison: "checklist_incomplete" };
  }
  if (params.photosApresSha256.length === 0) {
    return { pret: false, raison: "aucune_photo_apres" };
  }
  if (params.signatureRequise === null) {
    return { pret: false, raison: "signature_requise_non_choisie" };
  }
  if (params.signatureRequise && params.signatureSha256 === null) {
    return { pret: false, raison: "signature_requise_mais_absente" };
  }

  const etatsPhotos = params.photosApresSha256.map((sha) => calculerEtatEnvoiFichier(params.mutations, params.chantierId, sha));
  const etatSignature =
    params.signatureSha256 !== null ? calculerEtatEnvoiFichier(params.mutations, params.chantierId, params.signatureSha256) : null;
  const tousLesEtats = etatSignature ? [...etatsPhotos, etatSignature] : etatsPhotos;

  if (tousLesEtats.some((e) => e.statut === "echec_permanent")) {
    return { pret: false, raison: "fichiers_en_echec" };
  }
  if (!tousLesEtats.every((e) => e.statut === "complet")) {
    return { pret: false, raison: "fichiers_en_cours" };
  }

  const preuves = construirePreuvesCompletion({
    checklistComplete: params.checklistComplete,
    // `.reference!` : sûr ici, tous les états ci-dessus valent déjà "complet" (contrôlé juste
    // au-dessus), et `calculerEtatEnvoiFichier` garantit `reference` non nulle dans ce cas.
    referencesPhotosApres: etatsPhotos.map((e) => e.reference!),
    notes: params.notes,
    signature: etatSignature ? etatSignature.reference : null,
  });

  return { pret: true, preuves };
}
