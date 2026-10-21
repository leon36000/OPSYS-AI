import { construireFormulaireMateriauxUtilises, construireLigneDeclaree, TYPES_LIGNE_MATERIAUX } from "../m6/materiaux";
import type { FormulaireMateriauxUtilisesM6, LigneDeclareeChantierM6, TypeLigneMateriaux } from "../m6/materiaux";
import { estimationEnNombreExact } from "../m6/contexteMateriaux";

/**
 * Logique PURE de `app/(employee)/job/[id]/materials.tsx` (M6.10, R12 §5 étape 5, PLAN T1.4-f),
 * même discipline que `src/ecrans/complete.ts`/`src/ecrans/job.ts` : l'écran importe ce module et
 * ne fait lui-même que le câblage React.
 *
 * **Aucune quantité ni prix proposés par défaut (mission item 3).** `creerLigneVide` ne pré-remplit
 * JAMAIS `quantiteTexte`/`quantiteEstimeeTexte` — l'employé saisit chaque valeur, le serveur
 * calcule le coût (`materiel.soumettre_materiaux_utilises::_dernier_cout_unitaire_connu`, jamais
 * transmis par le mobile — voir `src/m6/materiaux.ts`).
 *
 * **Saisie en texte, conversion à la validation.** Une ligne EN COURS DE SAISIE garde ses nombres
 * en texte brut (`quantiteTexte`) plutôt qu'en `number | null` : un champ numérique React Native
 * qui convertirait à chaque frappe perdrait un « 12. » en cours de composition (le `.` seul ne
 * parse pas) — la conversion (`Number`, `,` toléré comme séparateur décimal fr-CA) n'a lieu qu'à
 * `validerLigne`/`convertirLigne`.
 */

export interface LigneEnSaisie {
  readonly id: string;
  readonly typeLigne: TypeLigneMateriaux;
  readonly materiauId: string;
  readonly quantiteTexte: string;
  readonly unite: string;
  /** Requis pour une ligne prévue par le contrat serveur ; jamais déduit du réel. */
  readonly quantiteEstimeeTexte: string;
  /** Utilisés seulement si `typeLigne === "achat_terrain"` — au moins un des deux doit être vrai
   * (`REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`, `materiel.py`, lu). */
  readonly photoFournie: boolean;
  readonly recuFourni: boolean;
}

/** `id` fourni par l'appelant (même discipline que `src/checklist/logique.ts::ajouterItem` —
 * `expo-crypto.randomUUID()` en production, déterministe dans les tests). Aucun champ
 * pré-rempli : l'employé choisit le type et saisit tout le reste. */
export function creerLigneVide(id: string): LigneEnSaisie {
  return {
    id,
    typeLigne: "prevu",
    materiauId: "",
    quantiteTexte: "",
    unite: "",
    quantiteEstimeeTexte: "",
    photoFournie: false,
    recuFourni: false,
  };
}

export function ajouterLigne(lignes: readonly LigneEnSaisie[], nouvelle: LigneEnSaisie): LigneEnSaisie[] {
  return [...lignes, nouvelle];
}

export function retirerLigne(lignes: readonly LigneEnSaisie[], id: string): LigneEnSaisie[] {
  return lignes.filter((l) => l.id !== id);
}

export function modifierLigne(lignes: readonly LigneEnSaisie[], id: string, patch: Partial<LigneEnSaisie>): LigneEnSaisie[] {
  return lignes.map((l) => (l.id === id ? { ...l, ...patch } : l));
}

export type ErreurLigne =
  | "materiau_id_manquant"
  | "unite_manquante"
  | "quantite_invalide"
  | "quantite_estimee_invalide"
  | "achat_terrain_preuve_manquante";

/** `,` toléré comme séparateur décimal (fr-CA) en plus de `.` — jamais un arrondi ni une valeur
 * par défaut : un texte non numérique (y compris vide) rend `null`, fail-closed. */
function parseNombre(texte: string): number | null {
  const nettoye = texte.trim().replace(",", ".");
  if (nettoye === "") {
    return null;
  }
  // La comparaison exacte porte sur la valeur JSON envoyée au writer existant.
  // Les formes décimales usuelles restent admises, sans arrondir une saisie.
  const decimal = nettoye.replace(/^\./, "0.").replace(/\.$/, ".0");
  return estimationEnNombreExact(decimal);
}

/** Ordre des contrôles épinglé (même discipline que `preuves.py`, lu) : matériau -> unité ->
 * quantité -> quantité estimée requise (si "prevu") -> preuve d'achat terrain (si
 * "achat_terrain"). Première faute rencontrée. */
export function validerLigne(ligne: LigneEnSaisie): ErreurLigne | null {
  if (/^\p{White_Space}*$/u.test(ligne.materiauId)) {
    return "materiau_id_manquant";
  }
  if (/^\p{White_Space}*$/u.test(ligne.unite)) {
    return "unite_manquante";
  }
  if (parseNombre(ligne.quantiteTexte) === null) {
    return "quantite_invalide";
  }
  if (ligne.typeLigne === "prevu" && parseNombre(ligne.quantiteEstimeeTexte) === null) {
    return "quantite_estimee_invalide";
  }
  if (ligne.typeLigne === "achat_terrain" && !ligne.photoFournie && !ligne.recuFourni) {
    return "achat_terrain_preuve_manquante";
  }
  return null;
}

/** `null` si `validerLigne` refuse — jamais une conversion partielle envoyée. */
export function convertirLigne(ligne: LigneEnSaisie): LigneDeclareeChantierM6 | null {
  if (validerLigne(ligne) !== null) {
    return null;
  }
  const quantite = parseNombre(ligne.quantiteTexte);
  if (quantite === null) {
    return null; // défensif, déjà exclu par validerLigne ci-dessus
  }
  const quantiteEstimeeBrute = ligne.typeLigne === "prevu" ? parseNombre(ligne.quantiteEstimeeTexte) : null;
  return construireLigneDeclaree({
    typeLigne: ligne.typeLigne,
    materiauId: ligne.materiauId,
    quantite,
    unite: ligne.unite,
    quantiteEstimee: quantiteEstimeeBrute ?? undefined,
    photoFournie: ligne.photoFournie,
    recuFourni: ligne.recuFourni,
  });
}

export type RaisonBlocageFormulaire = "aucune_ligne" | "lignes_invalides";

export type EtatPreparationFormulaire =
  | { readonly pret: false; readonly raison: RaisonBlocageFormulaire }
  | { readonly pret: true; readonly formulaire: FormulaireMateriauxUtilisesM6 };

/** Décide si le formulaire peut être soumis — au moins une ligne, ET toutes valides (aucune
 * ligne partiellement saisie tolérée : `REJ-CONTRAT-INVALIDE`/`REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`
 * seraient de toute façon refusés côté serveur, autant le dire ici avant l'appel réseau). */
export function evaluerPreparationFormulaire(
  wctId: string,
  interventionId: string,
  chantierId: string,
  lignes: readonly LigneEnSaisie[],
): EtatPreparationFormulaire {
  if (lignes.length === 0) {
    return { pret: false, raison: "aucune_ligne" };
  }
  const converties = lignes.map(convertirLigne);
  if (converties.some((c) => c === null)) {
    return { pret: false, raison: "lignes_invalides" };
  }
  return {
    pret: true,
    formulaire: construireFormulaireMateriauxUtilises(wctId, interventionId, chantierId, converties as LigneDeclareeChantierM6[]),
  };
}

export { TYPES_LIGNE_MATERIAUX };
