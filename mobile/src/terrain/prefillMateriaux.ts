import { creerLigneVide } from "../ecrans/materials";
import { estimationEnNombreExact } from "../m6/contexteMateriaux";
import type { ContexteMateriauxM6 } from "../m6/contexteMateriaux";
import type { BrouillonMateriaux } from "./brouillonMateriaux";

export type RefusPrefillMateriaux = "intention_en_attente" | "cible_changee" | "cible_absente" | "prevu_absent"
  | "prevu_vide" | "source_changee" | "page_deja_importee" | "estimation_non_importable" | "trop_de_lignes" | "identifiants_invalides";
/** Action explicite uniquement. Ajoute une page à la saisie sans la réécrire ; aucun réel estimé. */
export function appliquerPagePrevue(d: BrouillonMateriaux, c: ContexteMateriauxM6, nouvelId: () => string):
  { readonly ok: true; readonly valeur: BrouillonMateriaux } | { readonly ok: false; readonly raison: RefusPrefillMateriaux } {
  const refus = (raison: RefusPrefillMateriaux) => ({ ok: false as const, raison });
  if (d.intentionId !== null) return refus("intention_en_attente");
  const chantier = c.chantier.chantier_id;
  if (chantier === null) return refus("cible_absente");
  if ((d.wctId !== null && d.wctId !== c.wct.wct_id) || (d.chantierId !== null && d.chantierId !== chantier)) return refus("cible_changee");
  const source = c.prevu.source;
  if (source === null) return refus("prevu_absent");
  if (d.sourcePrevu !== null && d.sourcePrevu !== source.empreinte_snapshot) return refus("source_changee");
  if (c.lignes.length === 0) return refus("prevu_vide");
  if (c.lignes.some(l => d.positionsImportees.includes(l.position_source))) return refus("page_deja_importee");
  if (c.lignes.some(l => estimationEnNombreExact(l.quantite_estimee) === null)) return refus("estimation_non_importable");
  if (d.lignes.length + c.lignes.length > 128) return refus("trop_de_lignes");
  const ids = c.lignes.map(nouvelId), existants = new Set(d.lignes.map(l => l.id));
  if (ids.some(id => typeof id !== "string" || id.length === 0 || id.length > 4096 || existants.has(id)) || new Set(ids).size !== ids.length) return refus("identifiants_invalides");
  const lignes = c.lignes.map((l, i) => ({ ...creerLigneVide(ids[i]), typeLigne: "prevu" as const,
    materiauId: l.materiau_id, unite: l.unite, quantiteEstimeeTexte: l.quantite_estimee }));
  return { ok: true, valeur: { ...d, wctId: c.wct.wct_id, chantierId: chantier, sourcePrevu: source.empreinte_snapshot,
    positionsImportees: [...d.positionsImportees, ...c.lignes.map(l => l.position_source)], lignes: [...d.lignes, ...lignes] } };
}
