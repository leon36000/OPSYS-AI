import { creerChargeurContexteMateriaux } from "./contexteMateriaux";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionMateriauxLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import captures from "../m6/fixturesContexteMateriaux.json";

const config = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APPAREIL-FICTIF" };
beforeEach(() => { definirConfigurationAppel(null); definirPersonneConfirmee(null); });
afterEach(() => { definirConfigurationAppel(null); definirPersonneConfirmee(null); });
function preparer(role = "employee") {
  definirConfigurationAppel(config); definirPersonneConfirmee({ ...config, personne: "PERSONNE-FICTIVE", role });
  let epoch = 0, online = true;
  const fetchImpl = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: {} } }), { status: 200 }));
  const chargeur = creerChargeurContexteMateriaux({ capturerSession: capturerSessionMateriauxLecture,
    capturerReseau: () => { const debut = epoch; return { enLigne: online, courante: () => online && debut === epoch }; },
    appelerOutil: invoquerOutil, fetchImpl });
  return { chargeur, fetchImpl, reseau: (valeur: boolean) => { online = valeur; epoch++; } };
}
test.each(["seller", "client", "operator"])('profil %s ne lance aucun HTTP', async role => {
  const c = preparer(role); expect(await c.chargeur.charger("INT-FICTIF", "WCT-FICTIF", 0)).toMatchObject({ source: "aucune" });
  expect(c.fetchImpl).not.toHaveBeenCalled();
});
test('hors ligne ne lit ni cache ni serveur', async () => {
  const c = preparer(); c.reseau(false);
  expect(await c.chargeur.charger("INT-FICTIF", "WCT-FICTIF", 0)).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(c.fetchImpl).not.toHaveBeenCalled();
});
test.each([-1, 10001, 1.5, NaN])('page %s invalide sans appel ni réparation', async offset => {
  const c = preparer(); expect(await c.chargeur.charger("INT-FICTIF", "WCT-FICTIF", offset)).toMatchObject({ source: "aucune" });
  expect(c.fetchImpl).not.toHaveBeenCalled();
});
test('vrai client envoie seulement les quatre arguments, sans mutation', async () => {
  const c = preparer(); const resultat = await c.chargeur.charger("INT-FICTIF", "WCT-FICTIF", 8);
  expect(resultat).toMatchObject({ source: "aucune" }); expect(c.fetchImpl).toHaveBeenCalledTimes(1);
  const corps = JSON.parse(String(c.fetchImpl.mock.calls[0][1]?.body));
  expect(corps).toEqual({ tool: "m6_lire_contexte_materiaux_appareil", args: { intervention_id: "INT-FICTIF", wct_id: "WCT-FICTIF", decalage: 8, limite: 8 } });
});
test.each([401, 403])('HTTP %s refuse la lecture sans ancien contenu', async status => {
  const c = preparer(); c.fetchImpl.mockImplementation(async () => new Response(JSON.stringify({ ok: false, error: { type: "FICTIF" } }), { status }));
  expect(await c.chargeur.charger("INT-FICTIF", "WCT-FICTIF", 0)).toMatchObject({ source: "refus" });
});
test.each(['role', 'personne', 'jeton', 'reseau'])('%s remplace une réponse en vol', async changement => {
  const c = preparer(); let terminer!: (r: Response) => void;
  c.fetchImpl.mockImplementation(() => new Promise<Response>(resolve => { terminer = resolve; }));
  const promise = c.chargeur.charger("INT-FICTIF", "WCT-FICTIF", 0);
  await Promise.resolve();
  if (changement === 'role') definirPersonneConfirmee({ ...config, personne: "PERSONNE-FICTIVE", role: "seller" });
  if (changement === 'personne') { definirPersonneConfirmee({ ...config, personne: "AUTRE-FICTIVE", role: "employee" }); definirPersonneConfirmee({ ...config, personne: "PERSONNE-FICTIVE", role: "employee" }); }
  if (changement === 'jeton') definirConfigurationAppel({ ...config, jeton: "JETON-AUTRE-FICTIF" });
  if (changement === 'reseau') { c.reseau(false); c.reseau(true); }
  terminer(new Response(JSON.stringify({ ok: true, result: { ok: true, resultat: {} } }), { status: 200 }));
  expect(await promise).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
});
test.each(captures.captures.map(c => [c.phase, c] as const))('SQL réel %s consommé par le vrai client et le service', async (_phase, capture) => {
  const c = preparer(capture.phase.startsWith('admin-') || capture.phase.includes('admin-revoque') ? 'admin' : 'employee');
  c.fetchImpl.mockImplementation(async () => new Response(JSON.stringify({ ok: true, result: capture.response }), { status: 200 }));
  const args = capture.request.args, resultat = await c.chargeur.charger(args.intervention_id, args.wct_id, args.decalage, args.limite);
  if (args.limite === 9) {
    expect(resultat).toMatchObject({ source: 'aucune', raison: { code: 'arguments_invalides' } }); expect(c.fetchImpl).not.toHaveBeenCalled();
  } else if ('wct' in capture.response.resultat) {
    expect(resultat).toEqual({ source: 'serveur', valeur: capture.response.resultat });
  } else {
    expect(resultat).toMatchObject({ source: 'refus', verdict: capture.response.resultat.verdict });
  }
});
