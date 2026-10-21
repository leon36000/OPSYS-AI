import type { MutationOutbox } from "../outbox/types";

/**
 * Structure `PreuvesCompletion` attendue par `m4_completer_intervention` (T1.4-f) — préparée
 * SANS appeler la complétion elle-même (mission T1.4-e, item 2).
 *
 * `CLES_PREUVES_COMPLETION` ci-dessous est la copie EXACTE, clé pour clé et dans le même ordre,
 * de `departments/m04-field-ops/src/m4_field_ops/preuves.py`
 * (`CLES_PREUVES_COMPLETION = ("checklist_complete", "photos_apres", "notes", "signature")`),
 * lu ici en lecture seule (jamais importé ni exécuté, ADR-0008). `valider_preuves_completion`
 * (même fichier) exige ces QUATRE clés, RIEN DE PLUS (`additionalProperties`-style : « clé
 * étrangère » rejetée) — `construirePreuvesCompletion` ne peut donc produire que ces quatre
 * champs.
 */
export const CLES_PREUVES_COMPLETION = ["checklist_complete", "photos_apres", "notes", "signature"] as const;

/** Miroir TypeScript de `PreuvesCompletion` (voir l'en-tête de fichier). */
export interface PreuvesCompletionM4 {
  readonly checklist_complete: boolean;
  readonly photos_apres: readonly string[];
  readonly notes: string;
  readonly signature: string | null;
}

export interface ParametresPreuvesCompletion {
  readonly checklistComplete: boolean;
  /** Références LOCALES des photos après-chantier (voir `extraireReferencesPhotosLocales`
   * ci-dessous pour leur provenance et la limite documentée : ce ne sont PAS encore de vraies
   * références serveur, faute de route d'envoi du binaire). */
  readonly referencesPhotosApres: readonly string[];
  readonly notes: string;
  readonly signature: string | null;
}

/**
 * Assemble le dossier `PreuvesCompletion` — fonction pure, aucune validation métier dupliquée
 * ici (le serveur, `preuves.py`, reste la seule autorité fail-closed : checklist vraie,
 * photos_apres non vide, signature non vide si requise). Cette fonction ne fait QUE mettre en
 * forme ce que les écrans `checklist.tsx`/`photos.tsx`/`signature.tsx` ont déjà capturé
 * localement, pour que `complete.tsx` (T1.4-f) n'ait plus qu'à l'utiliser telle quelle.
 */
export function construirePreuvesCompletion(params: ParametresPreuvesCompletion): PreuvesCompletionM4 {
  return {
    checklist_complete: params.checklistComplete,
    photos_apres: [...params.referencesPhotosApres],
    notes: params.notes,
    signature: params.signature,
  };
}

/**
 * Extrait, depuis la file sortante (`src/outbox`), les références LOCALES des photos d'une
 * nature donnée pour un chantier — c'est-à-dire l'`id` (UUID) de chaque mutation `photo_upload`
 * encore `brouillon` (voir `src/photos/mutation.ts` : une mutation `photo_upload` reste
 * délibérément `brouillon`, jamais soumise, tant qu'aucune route serveur n'existe pour envoyer
 * le binaire — R12 §4, mission T1.4-e item 2).
 *
 * LIMITE ASSUMÉE, documentée aussi dans MOBILE.md : `photos_apres` attend, côté serveur, des
 * RÉFÉRENCES DE PHOTOS DÉJÀ REÇUES (probablement un identifiant émis par le futur point d'envoi
 * du binaire) — pas un `mutation_id` local. Utiliser ce dernier ici est un PLACEHOLDER délibéré
 * et nommé, du même esprit que `contextePointageProvisoire.ts` : il rend la STRUCTURE testable
 * dès maintenant, sans prétendre que ces chaînes seront acceptées telles quelles par
 * `m4_completer_intervention` avant qu'une route d'envoi n'existe (T1.4-f ou une tâche core
 * dédiée devra remplacer ces `mutation_id` par les vraies références une fois l'envoi câblé).
 */
export function extraireReferencesPhotosLocales(
  mutations: readonly MutationOutbox[],
  chantierId: string,
  nature: string,
): string[] {
  return mutations
    .filter(
      (m) =>
        m.type === "photo_upload" &&
        m.chantierId === chantierId &&
        m.statut === "brouillon" &&
        m.payload.nature === nature,
    )
    .map((m) => m.id);
}

/** Raccourci de `extraireReferencesPhotosLocales(..., "apres")` : seule la nature `"apres"`
 * alimente `preuves_completion.photos_apres` (`preuves.py`) — les photos `"avant"`/`"pendant"`
 * restent des preuves de chantier locales, jamais envoyées à `m4_completer_intervention`. */
export function extraireReferencePhotosApres(mutations: readonly MutationOutbox[], chantierId: string): string[] {
  return extraireReferencesPhotosLocales(mutations, chantierId, "apres");
}

/** Même principe que `extraireReferencesPhotosLocales`, pour la signature — au plus UNE
 * signature par chantier est attendue (le dernier brouillon `signature_capture` gagne, une
 * nouvelle capture remplaçant la précédente côté écran, voir `signature.tsx`). `null` si aucune
 * signature n'a été capturée (chantier ne l'exigeant pas, ou pas encore fait). */
export function extraireReferenceSignatureLocale(
  mutations: readonly MutationOutbox[],
  chantierId: string,
): string | null {
  const signatures = mutations.filter(
    (m) => m.type === "signature_capture" && m.chantierId === chantierId && m.statut === "brouillon",
  );
  if (signatures.length === 0) {
    return null;
  }
  return signatures[signatures.length - 1].id;
}
