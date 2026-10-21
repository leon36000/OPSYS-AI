import { appliquerPagePrevue } from "./prefillMateriaux";
import { creerLigneVide } from "../ecrans/materials";
import type { ContexteMateriauxM6 } from "../m6/contexteMateriaux";
import type { BrouillonMateriaux } from "./brouillonMateriaux";
const FICTIF = true;
const initial = (): BrouillonMateriaux => ({ wctId: "WCT-FICTIF", chantierId: "CHANTIER-M3-FICTIF", lignes: [], intentionId: null, sourcePrevu: null, positionsImportees: [] });
const contexte = () => ({ wct: { wct_id: "WCT-FICTIF" }, chantier: { chantier_id: "CHANTIER-M3-FICTIF" },
  prevu: { statut: "definitif", source: { empreinte_snapshot: "a".repeat(64) } },
  lignes: [{ position_source: 3, materiau_id: "SKU-FICTIF", unite: "pi", quantite_estimee: "00012.2500", origine_quantite: "texte_m3_verifie" }],
} as unknown as ContexteMateriauxM6); // Vecteur synthétique du helper, aucune capture serveur revendiquée.
test('import explicite : quantité réelle vide, texte prévu inchangé, vrai chantier conservé', () => {
  expect(FICTIF).toBe(true); const r = appliquerPagePrevue(initial(), contexte(), () => "LIGNE-IMPORTEE-FICTIVE");
  expect(r.ok).toBe(true); if (!r.ok) throw new Error(r.raison);
  expect(r.valeur.lignes[0]).toMatchObject({ typeLigne: "prevu", quantiteTexte: "", quantiteEstimeeTexte: "00012.2500", materiauId: "SKU-FICTIF", unite: "pi" });
  expect(r.valeur.chantierId).toBe("CHANTIER-M3-FICTIF"); expect(r.valeur.positionsImportees).toEqual([3]);
});
test('ajoute sans écraser la saisie existante', () => {
  const d = { ...initial(), lignes: [{ ...creerLigneVide("MANUELLE-FICTIVE"), quantiteTexte: "12." }] };
  const r = appliquerPagePrevue(d, contexte(), () => "IMPORTEE-FICTIVE");
  expect(r.ok).toBe(true); if (!r.ok) throw new Error(r.raison);
  expect(r.valeur.lignes[0]).toEqual(d.lignes[0]); expect(d.lignes).toHaveLength(1);
});
test.each(['source', 'wct', 'chantier', 'intention'])('%s divergente ne remplace rien', champ => {
  const d = initial();
  const mauvais = champ === 'source' ? { ...d, sourcePrevu: 'b'.repeat(64), positionsImportees: [0] }
    : champ === 'wct' ? { ...d, wctId: 'AUTRE-WCT' } : champ === 'chantier' ? { ...d, chantierId: 'AUTRE-CHANTIER' } : { ...d, intentionId: 'UUID-PENDING-FICTIF' };
  const copie = JSON.stringify(mauvais); expect(appliquerPagePrevue(mauvais, contexte(), () => 'LIGNE-FICTIVE').ok).toBe(false);
  expect(JSON.stringify(mauvais)).toBe(copie);
});
test('même position déjà importée ne crée pas une deuxième ligne', () => {
  const r = appliquerPagePrevue(initial(), contexte(), () => 'LIGNE-FICTIVE'); if (!r.ok) throw new Error(r.raison);
  expect(appliquerPagePrevue(r.valeur, contexte(), () => 'LIGNE-DOUBLE-FICTIVE')).toMatchObject({ ok: false, raison: 'page_deja_importee' });
});
test.each(['9007199254740993', '1.00000000000000000001'])('estimation %s non importable conserve tout le brouillon', quantite => {
  const c = { ...contexte(), lignes: [{ ...contexte().lignes[0], quantite_estimee: quantite }] };
  expect(appliquerPagePrevue(initial(), c, () => 'LIGNE-FICTIVE')).toMatchObject({ ok: false, raison: 'estimation_non_importable' });
});
