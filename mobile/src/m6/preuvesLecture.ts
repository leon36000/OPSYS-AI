import { horodatageM10Valide } from '../m10/contrat';
import type { Reponse } from '../m7/contrat';
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from '../protocole/jsonLecture';

export const OUTIL_PREUVES_PERTES_M6 = 'm6_lire_preuves_pertes_wct_appareil';
export interface ArgumentsPreuvesM6 { readonly wct_id: string; readonly decalage: number; readonly limite: number }
export interface ReferencePreuveM6<R extends 'principal' | 'preuves_pertes_bris'> {
  readonly registre: R; readonly index: number; readonly hash_maillon: string;
}
export interface PhotoPreuveM6 {
  readonly position_photo: number; readonly reference: string; readonly empreinte_sha256: string;
  readonly type_mime: 'image/jpeg' | 'image/png'; readonly taille_octets: number;
  /** CAS integrity now; actual pixel decoding is independently required before preview. */
  readonly etat_actuel: 'disponible' | 'indisponible';
}
export interface PreuvePerteM6 {
  readonly etat: 'absente' | 'note_seule' | 'photos_declarees';
  readonly reference: ReferencePreuveM6<'preuves_pertes_bris'> | null;
  readonly position_ligne: number | null; readonly note: string | null;
  readonly enregistre_le: string | null; readonly horodatage_appareil_declare: string | null;
  readonly photos: readonly PhotoPreuveM6[];
}
export interface PerteAvecPreuveM6 {
  readonly reference_mouvement: ReferencePreuveM6<'principal'>; readonly materiau_id: string;
  readonly type_mouvement: 'PERTE' | 'BRIS'; readonly quantite: string; readonly unite: null;
  readonly preuve: PreuvePerteM6;
}
export interface PagePreuvesM6 extends ArgumentsPreuvesM6 {
  readonly intervention_id: string; readonly total: number; readonly decalage_suivant: number | null;
  readonly pertes_bris: readonly PerteAvecPreuveM6[];
  readonly couverture: { readonly preuves: 'declarations_associees_aux_mouvements';
    readonly photos: 'integrite_et_association_sans_authenticite_scene';
    readonly dates: 'reception_serveur_et_heure_appareil_sans_date_du_dommage'; readonly plafond_lignes: 10000 };
}
const objet = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const ferme = (v: unknown, keys: readonly string[]): v is Record<string, unknown> =>
  objet(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const entier = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && Array.from(v).length <= 256 &&
  !/^\p{White_Space}+$/u.test(v) && !/[\p{Cc}\p{Cs}]/u.test(v);
const date = (v: unknown): v is string => typeof v === 'string' && v.length <= 64 && horodatageM10Valide(v);
const note = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && Array.from(v).length <= 500 &&
  !/^\p{White_Space}+$/u.test(v) && !/[\p{Cc}\p{Cs}]/u.test(v.replace(/[\t\r\n]/g, ''));
function reference<R extends 'principal' | 'preuves_pertes_bris'>(v: unknown, registre: R): ReferencePreuveM6<R> | null {
  return ferme(v, ['registre', 'index', 'hash_maillon']) && v.registre === registre && entier(v.index) &&
    v.index < 10000 && hash(v.hash_maillon) ? { registre, index: v.index, hash_maillon: v.hash_maillon } : null;
}
function photo(v: unknown, position: number): PhotoPreuveM6 | null {
  if (!ferme(v, ['position_photo', 'reference', 'empreinte_sha256', 'type_mime', 'taille_octets', 'etat_actuel']) ||
    v.position_photo !== position || !hash(v.empreinte_sha256) || v.reference !== 'fichier:sha256:' + v.empreinte_sha256 ||
    (v.type_mime !== 'image/png' && v.type_mime !== 'image/jpeg') || !entier(v.taille_octets) ||
    v.taille_octets < 1 || v.taille_octets > 10485760 ||
    (v.etat_actuel !== 'disponible' && v.etat_actuel !== 'indisponible')) return null;
  return { position_photo: position, reference: 'fichier:sha256:' + v.empreinte_sha256,
    empreinte_sha256: v.empreinte_sha256, type_mime: v.type_mime, taille_octets: v.taille_octets, etat_actuel: v.etat_actuel };
}
function preuve(v: unknown): PreuvePerteM6 | null {
  if (!ferme(v, ['etat', 'reference', 'position_ligne', 'note', 'enregistre_le', 'horodatage_appareil_declare', 'photos']) ||
    !Array.isArray(v.photos) || v.photos.length > 3) return null;
  if (v.etat === 'absente') return v.reference === null && v.position_ligne === null && v.note === null &&
    v.enregistre_le === null && v.horodatage_appareil_declare === null && v.photos.length === 0
    ? { etat: 'absente', reference: null, position_ligne: null, note: null, enregistre_le: null,
      horodatage_appareil_declare: null, photos: [] } : null;
  const ref = reference(v.reference, 'preuves_pertes_bris');
  if (!ref || !entier(v.position_ligne) || v.position_ligne > 23 || !note(v.note) || !date(v.enregistre_le) ||
    !(v.horodatage_appareil_declare === null || date(v.horodatage_appareil_declare)) ||
    (v.etat !== 'note_seule' && v.etat !== 'photos_declarees') ||
    (v.etat === 'note_seule' ? v.photos.length !== 0 : v.photos.length === 0)) return null;
  const photos: PhotoPreuveM6[] = [];
  for (const [i, brut] of v.photos.entries()) {
    const p = photo(brut, i); if (!p || photos.some(x => x.reference === p.reference)) return null; photos.push(p);
  }
  return { etat: v.etat, reference: ref, position_ligne: v.position_ligne, note: v.note,
    enregistre_le: v.enregistre_le, horodatage_appareil_declare: v.horodatage_appareil_declare, photos };
}
function perte(v: unknown): PerteAvecPreuveM6 | null {
  if (!ferme(v, ['reference_mouvement', 'materiau_id', 'type_mouvement', 'quantite', 'unite', 'preuve']) ||
    !id(v.materiau_id) || (v.type_mouvement !== 'PERTE' && v.type_mouvement !== 'BRIS') || v.unite !== null ||
    typeof v.quantite !== 'string' || v.quantite.length > 5400 ||
    !/^-(?:0|[1-9]\d*)(?:\.\d*[1-9])?$/.test(v.quantite) || v.quantite === '-0') return null;
  const ref = reference(v.reference_mouvement, 'principal'), p = preuve(v.preuve);
  return ref && p ? { reference_mouvement: ref, materiau_id: v.materiau_id, type_mouvement: v.type_mouvement,
    quantite: v.quantite, unite: null, preuve: p } : null;
}
function argumentsValides(v: unknown): v is ArgumentsPreuvesM6 {
  return ferme(v, ['wct_id', 'decalage', 'limite']) && id(v.wct_id) && entier(v.decalage) && v.decalage <= 10000 &&
    entier(v.limite) && v.limite >= 1 && v.limite <= 8;
}
export function construireArgumentsPreuves(wctId: string, decalage = 0, limite = 1): ArgumentsPreuvesM6 {
  const a = { wct_id: wctId, decalage, limite };
  if (!argumentsValides(a)) throw new Error('Arguments de preuves matériaux invalides.');
  return a;
}
const illisible = (): Reponse<PagePreuvesM6> => ({ ok: false, code: 'reponse_illisible', detail: '' });
/** Closed current page; preserves signed decimal text and missing evidence without repair. */
export function lirePreuvesPertesWct(brut: unknown, args: ArgumentsPreuvesM6): Reponse<PagePreuvesM6> {
  const a = copierJsonLecture(args), r = copierJsonLecture(brut);
  if (a === JSON_LECTURE_INVALIDE || r === JSON_LECTURE_INVALIDE || !argumentsValides(a) || !objet(r)) return illisible();
  if (r.ok === false && id(r.erreur) && (typeof r.details === 'string' ||
    (Array.isArray(r.details) && r.details.every(d => typeof d === 'string'))))
    return { ok: false, code: r.erreur, detail: typeof r.details === 'string' ? r.details : r.details.join('\n') };
  if (objet(r.resultat) && r.resultat.accepte === false && ferme(r.resultat.verdict, ['code', 'detail']) &&
    id(r.resultat.verdict.code) && typeof r.resultat.verdict.detail === 'string')
    return { ok: false, code: r.resultat.verdict.code, detail: r.resultat.verdict.detail };
  if (!ferme(r, ['ok', 'resultat']) || r.ok !== true || !ferme(r.resultat, ['wct_id', 'intervention_id', 'decalage',
    'limite', 'total', 'decalage_suivant', 'pertes_bris', 'couverture'])) return illisible();
  const v = r.resultat, c = v.couverture;
  if (v.wct_id !== a.wct_id || v.decalage !== a.decalage || v.limite !== a.limite || !id(v.intervention_id) ||
    !entier(v.total) || v.total > 10000 || !Array.isArray(v.pertes_bris) || v.pertes_bris.length > a.limite ||
    v.pertes_bris.length > Math.max(0, v.total - a.decalage) || (a.decalage < v.total && !v.pertes_bris.length) ||
    !ferme(c, ['preuves', 'photos', 'dates', 'plafond_lignes']) || c.preuves !== 'declarations_associees_aux_mouvements' ||
    c.photos !== 'integrite_et_association_sans_authenticite_scene' ||
    c.dates !== 'reception_serveur_et_heure_appareil_sans_date_du_dommage' || c.plafond_lignes !== 10000) return illisible();
  const suivant = v.pertes_bris.length && a.decalage + v.pertes_bris.length < v.total ? a.decalage + v.pertes_bris.length : null;
  if (v.decalage_suivant !== suivant) return illisible();
  const pertes: PerteAvecPreuveM6[] = [], preuves = new Set<number>();
  for (const brut of v.pertes_bris) {
    const p = perte(brut); if (!p || (pertes.length && p.reference_mouvement.index <= pertes[pertes.length - 1].reference_mouvement.index)) return illisible();
    if (p.preuve.reference && preuves.has(p.preuve.reference.index)) return illisible();
    if (p.preuve.reference) preuves.add(p.preuve.reference.index);
    pertes.push(p);
  }
  return { ok: true, value: { wct_id: a.wct_id, intervention_id: v.intervention_id, decalage: a.decalage, limite: a.limite,
    total: v.total, decalage_suivant: suivant, pertes_bris: pertes,
    couverture: { preuves: c.preuves, photos: c.photos, dates: c.dates, plafond_lignes: c.plafond_lignes } } };
}
