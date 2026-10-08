import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { BoutonSecondaire } from './composants';
import { lirePreuvesPertesWct } from '../m6/preuvesLecture';
import sql from '../m6/fixturesPreuvesLectureSQL.json';
let mockEpoch = 0, mockRole = 'admin';
let mockBlur: (() => void) | undefined;
const mockLecture = jest.fn(), mockPreview = jest.fn(), mockPurge = jest.fn();
jest.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
jest.mock('expo-router', () => ({ useFocusEffect: (callback: () => () => void) => {
  const React = require('react'); React.useEffect(() => { mockBlur = callback(); return mockBlur; }, [callback]);
} }));
jest.mock('../roles/contexte', () => ({ useSessionAppareil: () => mockRole }));
jest.mock('../protocole/configuration', () => ({ capturerSessionAdminLecture: () => {
  const n = mockEpoch; return { session: mockRole === 'admin' ? { personne: 'ADMIN-FICTIF' } : null,
    courante: () => mockRole === 'admin' && n === mockEpoch };
} }));
jest.mock('./pertesAlertes', () => ({ chargerPreuvesPertesWctM6: (...a: unknown[]) => mockLecture(...a) }));
jest.mock('./apercuPreuveNatif', () => ({ chargerApercuPreuveNatif: (...a: unknown[]) => mockPreview(...a) }));
import { PreuvesMateriauxM6 } from './PreuvesMateriauxM6';
const capture = sql.captures[0], lu = lirePreuvesPertesWct(JSON.parse(capture.reponse_utf8), capture.requete.args);
if (!lu.ok) throw new Error('Fixture SQL source invalid');
const page = lu.value;
let arbre: ReactTestRenderer;
const texte = () => JSON.stringify(arbre.toJSON());
const bouton = (k: string) => arbre.root.findAllByType(BoutonSecondaire).find(b => b.props.texte === 'admin.preuvesMateriaux.' + k)!;
async function monter() { await act(async () => { arbre = create(<PreuvesMateriauxM6 wctId={page.wct_id} connected surRefus={jest.fn()} />); }); }
async function presser(k: string) { await act(async () => { bouton(k).props.onPress(); }); }
beforeEach(() => {
  mockEpoch = 0; mockRole = 'admin'; mockLecture.mockReset(); mockPreview.mockReset(); mockPurge.mockReset(); mockPurge.mockResolvedValue(undefined);
  mockLecture.mockResolvedValue({ source:'serveur', valeur:page, misAJourLe:'2026-10-08T00:00:00Z' });
  mockPreview.mockResolvedValue({ genre:'pret', uri:'file:///PRIVATE-FICTIF.png', courante:()=>true, purger:mockPurge });
});
afterEach(() => { act(() => arbre?.unmount()); });
test('lecture explicite fonctionne après montage/focus et conserve note/source', async () => {
  await monter(); await presser('charger');
  expect(mockLecture).toHaveBeenCalledWith(page.wct_id, 0);
  expect(texte()).toContain('FICTIF note de perte');
  expect(texte()).toContain('admin.preuvesMateriaux.uniteInconnue');
});
test('preview privé est purgé au blur et sans lecture hors ligne', async () => {
  await monter(); await presser('charger'); await presser('disponible');
  expect(arbre.root.findByType(require('react-native').Image).props.source.uri).toContain('PRIVATE-FICTIF.png');
  await act(async () => { mockBlur?.(); });
  expect(mockPurge).toHaveBeenCalled(); expect(texte()).not.toContain('PRIVATE-FICTIF.png');
  await act(async () => { arbre.update(<PreuvesMateriauxM6 wctId={page.wct_id} connected={false} surRefus={jest.fn()} />); });
  await presser('charger'); expect(mockLecture).toHaveBeenCalledTimes(1);
});
test('une réponse arrivée après réattribution ne paraît pas', async () => {
  let terminer!: (r: unknown) => void;
  mockLecture.mockImplementation(() => new Promise(resolve => { terminer = resolve; }));
  await monter(); await presser('charger');
  await act(async () => { mockEpoch++; mockRole='seller'; terminer({source:'serveur',valeur:page}); });
  expect(texte()).not.toContain('FICTIF note de perte');
});

test('une erreur de l’ancienne image ne supprime pas l’aperçu suivant', async () => {
  const { Image } = require('react-native');
  const purgeA = jest.fn(async () => undefined), purgeB = jest.fn(async () => undefined);
  mockPreview.mockResolvedValueOnce({genre:'pret',uri:'file:///PRIVATE-A.png',courante:()=>true,purger:purgeA})
    .mockResolvedValueOnce({genre:'pret',uri:'file:///PRIVATE-B.png',courante:()=>true,purger:purgeB});
  await monter(); await presser('charger'); await presser('disponible');
  const ancienneErreur = arbre.root.findByType(Image).props.onError;
  await presser('disponible');
  await act(async () => { ancienneErreur(); });
  expect(purgeA).toHaveBeenCalledTimes(1); expect(purgeB).not.toHaveBeenCalled();
  expect(arbre.root.findByType(require('react-native').Image).props.source.uri).toContain('PRIVATE-B.png');
});
