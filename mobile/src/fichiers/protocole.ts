/**
 * Contrat mobile de `m4_deposer_fichier`/`m4_etat_fichier` (PLAN T1.4-f).
 *
 * CONTRAT FIXE, écrit avant la route serveur puis confronté à elle à l'intégration : les deux
 * outils sont livrés par PLAN T1.4-e2 (`departments/m04-field-ops/src/m4_field_ops/outils.py`,
 * dépôt `src/opsys/fichiers.py`, `docs/architecture/FICHIERS.md`) avec exactement ces paramètres
 * et ces formes de réponse. `m4_deposer_fichier` est N2 (tâche interne, jamais mis en attente
 * d'approbation) ; la complétion qui s'en sert reste soumise aux approbations :
 *
 *  - `m4_deposer_fichier(empreinte_sha256, taille_octets, type_mime, index_bloc, nombre_blocs,
 *    bloc_base64) -> {"accepte": true, "resultat": {"reference", "complet", "blocs_recus"}} |
 *    {"accepte": false, "verdict": {...}}` — même patron `depuis_couple` que `m4_pointer`
 *    (`src/m4/pointage.ts`) : un HTTP 200 peut être un REJET métier définitif
 *    (`REJ-FICHIER-PARAMETRES-INVALIDES`, `REJ-FICHIER-TROP-VOLUMINEUX`, `REJ-FICHIER-INCOHERENT`,
 *    `REJ-FICHIER-EMPREINTE-DISCORDANTE`, `REJ-FICHIER-TYPE-NON-PERMIS`).
 *  - `m4_etat_fichier(empreinte_sha256) -> {"accepte": true, "resultat": {"existe", "complet",
 *    "blocs_recus", "reference"}}` — MÊME patron `accepte`/`resultat`|`verdict`, pour reprendre
 *    un envoi interrompu sans réémettre les blocs déjà reçus.
 *
 * Même discipline que `src/m4/interventions.ts` (en-tête) : les petits utilitaires de lecture
 * défensive (`estObjet`/`texteOu`) sont RÉÉCRITS ici plutôt qu'importés de `src/m4/pointage.ts` —
 * risque de régression d'un refactor partagé jugé plus coûteux que la duplication d'une dizaine
 * de lignes (AGENTS.md : économie de tokens, jamais au prix de casser un écran qui marche déjà).
 */

/** `m4_deposer_fichier` n'accepte que ces deux types — CONTRAT FIXE. Les photos capturées par
 * `src/photos/service.ts` sont toujours `.jpg` (capture `imageType: "jpg"`) ; la signature
 * capturée par `src/signature/service.ts` est toujours `.png` par défaut de
 * `react-native-signature-canvas` (vérifié en lisant `node_modules/react-native-signature-canvas
 * /index.js` : `imageType || "image/png"`, jamais fixé autrement par `signature.tsx`) — voir
 * `src/fichiers/candidats.ts::deduireTypeMimeDepuisUri` pour la DÉRIVATION depuis l'extension
 * réelle du fichier local, jamais une valeur supposée en dur à cet endroit. */
export type TypeMimeFichier = "image/jpeg" | "image/png";

export const TYPES_MIME_FICHIER: readonly TypeMimeFichier[] = ["image/jpeg", "image/png"];

export interface VerdictServeurFichier {
  readonly code: string;
  readonly detail: string;
}

/** Args EXACTS d'un appel `m4_deposer_fichier` (un bloc). Snake_case : forme du contrat outil,
 * jamais retraduite ici (même discipline que `src/m4/pointage.ts::ArgumentsM4Pointer`). */
export interface ArgumentsM4DeposerFichier {
  readonly empreinte_sha256: string;
  readonly taille_octets: number;
  readonly type_mime: TypeMimeFichier;
  readonly index_bloc: number;
  readonly nombre_blocs: number;
  readonly bloc_base64: string;
}

export function construireArgumentsDeposerFichier(
  empreinteSha256: string,
  tailleOctets: number,
  typeMime: TypeMimeFichier,
  indexBloc: number,
  nombreBlocs: number,
  blocBase64: string,
): ArgumentsM4DeposerFichier {
  return {
    empreinte_sha256: empreinteSha256,
    taille_octets: tailleOctets,
    type_mime: typeMime,
    index_bloc: indexBloc,
    nombre_blocs: nombreBlocs,
    bloc_base64: blocBase64,
  };
}

export interface ArgumentsM4EtatFichier {
  readonly empreinte_sha256: string;
}

export function construireArgumentsEtatFichier(empreinteSha256: string): ArgumentsM4EtatFichier {
  return { empreinte_sha256: empreinteSha256 };
}

/** Référence construite par le serveur à la réception du DERNIER bloc — `"fichier:sha256:<hex>"`
 * (contrat donné). DÉTERMINISTE depuis l'empreinte déjà connue localement : le mobile n'a donc
 * jamais besoin d'attendre/relire la chaîne exacte renvoyée par le serveur pour la calculer —
 * seulement pour savoir QUAND le fichier est `complet` (voir `src/fichiers/etatEnvoi.ts`). */
export function construireReferenceFichier(empreinteSha256: string): string {
  return `fichier:sha256:${empreinteSha256}`;
}

export interface ResultatDepotBloc {
  readonly reference: string | null;
  readonly complet: boolean;
  readonly blocsRecus: readonly number[];
}

export type InterpretationDeposerFichier =
  | { readonly accepte: true; readonly resultat: ResultatDepotBloc }
  | { readonly accepte: false; readonly verdict: VerdictServeurFichier };

export interface ResultatEtatFichier {
  readonly existe: boolean;
  readonly complet: boolean;
  readonly blocsRecus: readonly number[];
  readonly reference: string | null;
}

export type InterpretationEtatFichier =
  | { readonly accepte: true; readonly resultat: ResultatEtatFichier }
  | { readonly accepte: false; readonly verdict: VerdictServeurFichier };

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null;
}

function texteOu(valeur: unknown, repli: string): string {
  return typeof valeur === "string" ? valeur : repli;
}

function texteOuNul(valeur: unknown): string | null {
  return typeof valeur === "string" ? valeur : null;
}

function tableauIndices(valeur: unknown): number[] {
  if (!Array.isArray(valeur)) {
    return [];
  }
  return valeur.filter((v): v is number => typeof v === "number" && Number.isInteger(v));
}

function verdictDepuisBrut(valeur: unknown): VerdictServeurFichier {
  const brut = estObjet(valeur) ? valeur : {};
  return { code: texteOu(brut.code, "REJ-INCONNU"), detail: texteOu(brut.detail, "") };
}

/** Erreur TECHNIQUE de `outils.executer` (`{"ok": false, ...}`) — distincte d'un rejet MÉTIER
 * (`accepte: false`), même distinction que partout ailleurs dans `src/m4`/`src/today`. */
function verdictDepuisErreurTechnique(enveloppe: Record<string, unknown>): VerdictServeurFichier {
  return { code: texteOu(enveloppe.erreur, "erreur_inconnue"), detail: texteOu(enveloppe.details, "") };
}

/**
 * Interprète la réponse BUSINESS de `m4_deposer_fichier` — lecture DÉFENSIVE (même esprit que
 * `interpreterResultatPointage`) : une forme non reconnue à l'intérieur d'un `accepte: true` est
 * traitée comme « pas encore complet, aucune référence » plutôt qu'un blocage — jamais un succès
 * FAUSSÉ en un rejet, ni l'inverse. Jamais vérifiée contre un serveur réel dans ce bac à sable :
 * à confirmer au premier test de bout en bout contre le vrai contrat (T1.5), voir MOBILE.md.
 */
export function interpreterResultatDeposerFichier(resultatBrut: unknown): InterpretationDeposerFichier {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { accepte: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const resultatMetier = estObjet(enveloppe.resultat) ? enveloppe.resultat : undefined;

  if (resultatMetier?.accepte === false) {
    return { accepte: false, verdict: verdictDepuisBrut(resultatMetier.verdict) };
  }
  if (resultatMetier?.accepte === true) {
    const r = estObjet(resultatMetier.resultat) ? resultatMetier.resultat : {};
    return {
      accepte: true,
      resultat: { reference: texteOuNul(r.reference), complet: r.complet === true, blocsRecus: tableauIndices(r.blocs_recus) },
    };
  }
  return { accepte: true, resultat: { reference: null, complet: false, blocsRecus: [] } };
}

/**
 * Interprète la réponse de `m4_etat_fichier` — MÊME patron `accepte`/`resultat`|`verdict` que
 * `m4_deposer_fichier` ci-dessus (contrat donné), lecture tout aussi défensive : une forme non
 * reconnue rend « n'existe pas encore » plutôt qu'un blocage — cet appel sert uniquement à
 * DÉCIDER quels blocs (re)envoyer (`envoiOrchestrateur.ts`), jamais à marquer quoi que ce soit
 * comme envoyé : seul un `m4_deposer_fichier` accepté fait foi pour ça (voir `descripteurs.ts`).
 */
export function interpreterResultatEtatFichier(resultatBrut: unknown): InterpretationEtatFichier {
  const enveloppe = estObjet(resultatBrut) ? resultatBrut : {};
  if (enveloppe.ok === false) {
    return { accepte: false, verdict: verdictDepuisErreurTechnique(enveloppe) };
  }
  const resultatMetier = estObjet(enveloppe.resultat) ? enveloppe.resultat : undefined;

  if (resultatMetier?.accepte === false) {
    return { accepte: false, verdict: verdictDepuisBrut(resultatMetier.verdict) };
  }
  if (resultatMetier?.accepte === true) {
    const r = estObjet(resultatMetier.resultat) ? resultatMetier.resultat : {};
    return {
      accepte: true,
      resultat: {
        existe: r.existe === true,
        complet: r.complet === true,
        blocsRecus: tableauIndices(r.blocs_recus),
        reference: texteOuNul(r.reference),
      },
    };
  }
  return { accepte: true, resultat: { existe: false, complet: false, blocsRecus: [], reference: null } };
}
