import { construireArgumentsPreuves, lirePreuvesPertesWct } from './preuvesLecture';

const args = { wct_id: 'WCT-FICTIF', decalage: 0, limite: 1 };
const ref = { registre: 'principal', index: 4, hash_maillon: 'a'.repeat(64) };
const absente = { etat: 'absente', reference: null, position_ligne: null, note: null,
  enregistre_le: null, horodatage_appareil_declare: null, photos: [] };
const couverture = { preuves: 'declarations_associees_aux_mouvements',
  photos: 'integrite_et_association_sans_authenticite_scene',
  dates: 'reception_serveur_et_heure_appareil_sans_date_du_dommage', plafond_lignes: 10000 };
function reponse(preuve: unknown = absente) {
  return { ok: true, resultat: { wct_id: args.wct_id, intervention_id: 'INT-FICTIF', decalage: 0, limite: 1,
    total: 1, decalage_suivant: null, pertes_bris: [{ reference_mouvement: ref,
      materiau_id: 'SKU-FICTIF', type_mouvement: 'PERTE', quantite: '-1.25', unite: null, preuve }], couverture } };
}
const photo = { position_photo: 0, reference: 'fichier:sha256:' + 'b'.repeat(64),
  empreinte_sha256: 'b'.repeat(64), type_mime: 'image/png', taille_octets: 307899, etat_actuel: 'disponible' };
const note = { etat: 'note_seule', reference: { registre: 'preuves_pertes_bris', index: 0, hash_maillon: 'c'.repeat(64) },
  position_ligne: 0, note: 'FICTIF déclaré 🛠', enregistre_le: '2026-10-08T00:00:00+00:00',
  horodatage_appareil_declare: null, photos: [] };

test('absence reste inconnue et quantité texte reste exacte sans unité inventée', () => {
  const avant = reponse();
  expect(lirePreuvesPertesWct(avant, args)).toEqual({ ok: true, value: avant.resultat });
  expect(avant.resultat.pertes_bris[0].preuve).toEqual(absente);
});
test('note seule et fichiers référencés ne prétendent pas prouver la scène', () => {
  expect(lirePreuvesPertesWct(reponse(note), args).ok).toBe(true);
  expect(lirePreuvesPertesWct(reponse({ ...note, etat: 'photos_declarees', photos: [photo] }), args).ok).toBe(true);
  expect(lirePreuvesPertesWct(reponse({ ...note, etat: 'photos_declarees', photos: [{ ...photo, etat_actuel: 'indisponible' }] }), args).ok).toBe(true);
});
test.each([
  { ...absente, note: 'inventé' }, { ...note, position_ligne: true }, { ...note, note: ' ' },
  { ...note, note: 'a'.repeat(501) }, { ...note, note: '\u0000' }, { ...note, note: '\ud800' },
  { ...note, photos: [photo] }, { ...note, etat: 'photos_declarees', photos: [] },
  { ...note, source: 'inventé' }, { ...note, reference: ref },
  { ...note, etat: 'photos_declarees', photos: [{ ...photo, reference: 'fichier:sha256:' + 'd'.repeat(64) }] },
  { ...note, etat: 'photos_declarees', photos: [{ ...photo, position_photo: 1 }] },
  { ...note, etat: 'photos_declarees', photos: [{ ...photo, taille_octets: 10485761 }] },
])('corruption fermée avant lecture partielle (%#)', preuve => {
  expect(lirePreuvesPertesWct(reponse(preuve), args).ok).toBe(false);
});
test.each(['0', '-0', '1', '-1e3', '', '-NaN'])('quantité signée invalide %s', quantite => {
  const r = reponse(); r.resultat.pertes_bris[0].quantite = quantite;
  expect(lirePreuvesPertesWct(r, args).ok).toBe(false);
});
test('cible et pagination sont liées à la demande courante', () => {
  const r = reponse();
  expect(lirePreuvesPertesWct(r, { ...args, wct_id: 'AUTRE' }).ok).toBe(false);
  expect(lirePreuvesPertesWct(r, { ...args, decalage: 1 }).ok).toBe(false);
  expect(lirePreuvesPertesWct({ ...r, resultat: { ...r.resultat, decalage_suivant: 0 } }, args).ok).toBe(false);
  expect(construireArgumentsPreuves('WCT-FICTIF')).toEqual(args);
  expect(() => construireArgumentsPreuves(' ', 0, 1)).toThrow();
});
test('getters non invoqués, aucune réparation du JSON hostile', () => {
  let appels = 0;
  const hostile = Object.defineProperty({}, 'ok', { enumerable: true, get: () => { appels++; return true; } });
  expect(lirePreuvesPertesWct(hostile, args).ok).toBe(false);
  expect(appels).toBe(0);
});

// Real original Cap/SQLite DTO bodies replayed at the client codec boundary; no new HTTP run.
import sql from './fixturesPreuvesLectureSQL.json';
import { createHash } from 'node:crypto';
test.each(sql.captures)('SQL source original $phase', capture => {
  expect(createHash('sha256').update(capture.reponse_utf8, 'utf8').digest('hex')).toBe(capture.source_sha256);
  const lu = lirePreuvesPertesWct(JSON.parse(capture.reponse_utf8), capture.requete.args);
  expect(lu.ok).toBe(true);
  if (lu.ok) expect(lu.value).toEqual(JSON.parse(capture.reponse_utf8).resultat);
});
test('note500points Unicode et FEFF restent verbatim selon contratPython', () => {
  for (const texte of ['🛠'.repeat(500), '\uFEFF']) {
    const lu = lirePreuvesPertesWct(reponse({ ...note, note: texte }), args);
    expect(lu.ok).toBe(true);
    if (lu.ok) expect(lu.value.pertes_bris[0].preuve.note).toBe(texte);
  }
});
