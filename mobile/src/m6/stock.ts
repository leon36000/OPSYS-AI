import { estDecimal, texteOuNull } from "../admin/lecteurs";

/** T4.23 : contrats relus dans M6 et les captures HTTP MCP fictives, sans calcul de stock local. */
export const OUTIL_DISPONIBILITE = "m6_lire_disponibilite";
export const OUTIL_DIGEST = "m6_produire_digest";

export interface ArticleStock {
  readonly materiau_id: string;
  readonly stock_theorique: string;
  readonly hors_main: string;
  readonly en_main: string;
  readonly reserve: string;
  readonly disponible: string;
  readonly par_emplacement: Readonly<Record<string, string>>;
}
export interface LigneManquanteStock {
  readonly materiau_id: string;
  readonly unite: string | null;
  readonly quantite_besoin: string;
  readonly quantite_reservee: string;
  readonly quantite_manquante: string;
}
export type StatutReservationStock = "pret" | "partiel" | "a_commander";
export interface ReservationStock {
  readonly devis_id: string;
  readonly chantier_id: string | null;
  readonly statut: StatutReservationStock;
  readonly lignes_manquantes: readonly LigneManquanteStock[];
}
export interface DisponibiliteStock {
  readonly articles: readonly ArticleStock[];
  readonly tronque: boolean;
  readonly reservations_actives: readonly ReservationStock[];
  readonly reservations_tronquees: boolean;
}
export type VerdictVarianceStock = "AUCUN_ECART" | "STOCK_INFERIEUR_AU_THEORIQUE" | "STOCK_SUPERIEUR_AU_THEORIQUE";
export interface VarianceStock {
  readonly chantier_id: string;
  readonly materiau_id: string;
  readonly verdict_variance: VerdictVarianceStock;
  readonly ecart: number;
}
export interface ReorderStock {
  readonly chantier_id: string;
  readonly materiau_id: string;
  readonly quantite_suggeree: number;
}
export interface DigestStock {
  readonly type: "DIGEST_MATERIEL";
  readonly nb_variances_stock: number;
  readonly nb_reorders_suggeres: number;
  readonly variances_significatives: readonly VarianceStock[];
  readonly reorders: readonly ReorderStock[];
  readonly hash_digest: string;
}

/** Données propres uniquement : JSON et objets normalisés à prototype nul. Aucun getter n'est exécuté. */
function objet(valeur: unknown): Record<string, unknown> | null {
  if (typeof valeur !== "object" || valeur === null || Array.isArray(valeur)) return null;
  try {
    const prototype = Object.getPrototypeOf(valeur);
    if (prototype !== Object.prototype && prototype !== null) return null;
    const descriptors = Object.getOwnPropertyDescriptors(valeur);
    const propres: Record<string, unknown> = Object.create(null);
    for (const [cle, descriptor] of Object.entries(descriptors)) {
      if (!("value" in descriptor)) return null;
      propres[cle] = descriptor.value;
    }
    return propres;
  } catch {
    return null;
  }
}

/** Toute ligne doit être lisible : pas de filtrage qui ferait disparaître un manque ou un écart. */
function liste<T>(valeur: unknown, lire: (v: unknown) => T | null, limite = Number.MAX_SAFE_INTEGER): T[] | null {
  if (!Array.isArray(valeur)) return null;
  try {
    if (Object.getPrototypeOf(valeur) !== Array.prototype) return null;
    const descriptors = Object.getOwnPropertyDescriptors(valeur);
    const longueur: unknown = Object.getOwnPropertyDescriptor(valeur, "length")?.value;
    if (typeof longueur !== "number" || !Number.isSafeInteger(longueur) || longueur < 0 || longueur > limite) return null;
    const lus: T[] = [];
    for (let i = 0; i < longueur; i++) {
      if (!Object.hasOwn(descriptors, String(i))) return null;
      const descriptor = descriptors[String(i)];
      if (!descriptor || !("value" in descriptor)) return null;
      const lu = lire(descriptor.value);
      if (lu === null) return null;
      lus.push(lu);
    }
    return lus;
  } catch {
    return null;
  }
}

function emplacements(valeur: unknown): Record<string, string> | null {
  const lu = objet(valeur);
  if (!lu || !Object.hasOwn(lu, "inconnu")) return null;
  const entries: [string, string][] = [];
  for (const [cle, quantite] of Object.entries(lu)) {
    if (!texteOuNull(cle) || !estDecimal(quantite)) return null;
    entries.push([cle, quantite]);
  }
  // fromEntries crée des propriétés propres même pour une clé telle que __proto__ : aucune pollution.
  return Object.fromEntries(entries);
}

function lireArticle(valeur: unknown): ArticleStock | null {
  const v = objet(valeur);
  if (!v) return null;
  const materiau_id = texteOuNull(v.materiau_id);
  const { stock_theorique, hors_main, en_main, reserve, disponible } = v;
  const par_emplacement = emplacements(v.par_emplacement);
  if (!materiau_id || !estDecimal(stock_theorique) || !estDecimal(hors_main) || !estDecimal(en_main)
    || !estDecimal(reserve) || !estDecimal(disponible) || !par_emplacement) return null;
  return { materiau_id, stock_theorique, hors_main, en_main, reserve, disponible, par_emplacement };
}

function lireManque(valeur: unknown): LigneManquanteStock | null {
  const v = objet(valeur);
  if (!v) return null;
  const materiau_id = texteOuNull(v.materiau_id);
  const unite = v.unite === null ? null : texteOuNull(v.unite);
  const { quantite_besoin, quantite_reservee, quantite_manquante } = v;
  if (!materiau_id || (v.unite !== null && unite === null) || !estDecimal(quantite_besoin)
    || !estDecimal(quantite_reservee) || !estDecimal(quantite_manquante)) return null;
  return { materiau_id, unite, quantite_besoin, quantite_reservee, quantite_manquante };
}

function estStatut(valeur: unknown): valeur is StatutReservationStock {
  return valeur === "pret" || valeur === "partiel" || valeur === "a_commander";
}
function lireReservation(valeur: unknown): ReservationStock | null {
  const v = objet(valeur);
  if (!v) return null;
  const devis_id = texteOuNull(v.devis_id);
  const chantier_id = v.chantier_id === null ? null : texteOuNull(v.chantier_id);
  const lignes_manquantes = liste(v.lignes_manquantes, lireManque);
  if (!devis_id || (v.chantier_id !== null && chantier_id === null) || !estStatut(v.statut) || !lignes_manquantes) return null;
  return { devis_id, chantier_id, statut: v.statut, lignes_manquantes };
}

/** Quantités signées en texte, limites natives 15/10. La troncature métier est un résultat lisible. */
export function lireDisponibilite(valeur: unknown): DisponibiliteStock | null {
  const v = objet(valeur);
  if (!v || typeof v.tronque !== "boolean" || typeof v.reservations_tronquees !== "boolean") return null;
  const articles = liste(v.articles, lireArticle, 15);
  const reservations_actives = liste(v.reservations_actives, lireReservation, 10);
  if (!articles || !reservations_actives || (v.tronque && articles.length !== 15)
    || (v.reservations_tronquees && reservations_actives.length !== 10)) return null;
  return { articles, tronque: v.tronque, reservations_actives, reservations_tronquees: v.reservations_tronquees };
}

function nombreFini(valeur: unknown): valeur is number {
  return typeof valeur === "number" && Number.isFinite(valeur);
}
function compteur(valeur: unknown): valeur is number {
  return typeof valeur === "number" && Number.isSafeInteger(valeur) && valeur >= 0;
}
function estVerdict(valeur: unknown): valeur is VerdictVarianceStock {
  return valeur === "AUCUN_ECART" || valeur === "STOCK_INFERIEUR_AU_THEORIQUE" || valeur === "STOCK_SUPERIEUR_AU_THEORIQUE";
}
function lireVariance(valeur: unknown): VarianceStock | null {
  const v = objet(valeur);
  if (!v) return null;
  const chantier_id = texteOuNull(v.chantier_id), materiau_id = texteOuNull(v.materiau_id);
  if (!chantier_id || !materiau_id || !estVerdict(v.verdict_variance) || !nombreFini(v.ecart)) return null;
  return { chantier_id, materiau_id, verdict_variance: v.verdict_variance, ecart: v.ecart };
}
function lireReorder(valeur: unknown): ReorderStock | null {
  const v = objet(valeur);
  if (!v) return null;
  const chantier_id = texteOuNull(v.chantier_id), materiau_id = texteOuNull(v.materiau_id);
  if (!chantier_id || !materiau_id || !nombreFini(v.quantite_suggeree) || v.quantite_suggeree <= 0) return null;
  return { chantier_id, materiau_id, quantite_suggeree: v.quantite_suggeree };
}

/** Digest natif général : nombres finis, comptes exacts des listes entières, aucune quantité convertie. */
export function lireDigest(valeur: unknown): DigestStock | null {
  const v = objet(valeur);
  if (!v || v.type !== "DIGEST_MATERIEL" || !compteur(v.nb_variances_stock) || !compteur(v.nb_reorders_suggeres)
    || typeof v.hash_digest !== "string" || !/^[0-9a-f]{64}$/.test(v.hash_digest)) return null;
  const variances_significatives = liste(v.variances_significatives, lireVariance);
  const reorders = liste(v.reorders, lireReorder);
  if (!variances_significatives || !reorders || v.nb_variances_stock !== variances_significatives.length
    || v.nb_reorders_suggeres !== reorders.length) return null;
  return { type: v.type, nb_variances_stock: v.nb_variances_stock, nb_reorders_suggeres: v.nb_reorders_suggeres,
    variances_significatives, reorders, hash_digest: v.hash_digest };
}

/** L'appel admin {} n'apporte aucun seuil : une suggestion serait contradictoire avec cette lecture. */
export function lireDigestSansSeuils(valeur: unknown): DigestStock | null {
  const lu = lireDigest(valeur);
  return lu && lu.nb_reorders_suggeres === 0 ? lu : null;
}
