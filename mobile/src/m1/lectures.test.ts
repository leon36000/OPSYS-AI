import { creerChargeurLecturesTransferts } from "./lectures";
import { FIXTURES_M1 } from "./fixtures";
import { invoquerOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
const f = FIXTURES_M1.reponses;
const date = f.digest_date.args.date_reference;
const id = f.plainte_ouverte.args.transfert_id;
function harness() {
  const depot = new DepotCleValeurMemoire();
  let online = true, epoch = 0;
  let session: SessionEnvoi | null = { personne: "admin-fictif", jeton: "fictif", appareilId: "appareil-fictif", urlBase: "https://core.fictif" };
  const fetchImpl = jest.fn(async (_url: Parameters<typeof fetch>[0], init?: RequestInit) => {
    const req = JSON.parse(String(init?.body));
    const cas = req.tool === "m1_produire_digest" ? f.digest_date : f.plainte_ouverte;
    return new Response(JSON.stringify(cas.corps), { status: cas.statut_http });
  });
  const obtenirDepot = jest.fn(async () => depot);
  const d = { obtenirDepot, fetchImpl, appelerOutil: invoquerOutil,
    capturerSession: () => { const e = epoch; return { session, courante: () => session !== null && e === epoch }; },
    enLigne: () => online, horloge: () => ({ maintenant: new Date("2026-10-07T18:00:00Z"), decalageMinutesUTC: -240 }) };
  return { lectures: creerChargeurLecturesTransferts(d), fetchImpl, depot, obtenirDepot,
    horsLigne: () => { online = false; }, retirerRole: () => { epoch++; session = null; },
    autrePersonne: () => { epoch++; session = { ...session!, personne: "autre-fictif" }; } };
}
test("digest natif et fiche : arguments minimaux, cache réservé au texte agrégé", async () => {
  const h = harness();
  expect((await h.lectures.chargerDigest(date))?.source).toBe("serveur");
  expect((await h.lectures.chargerTransfert(id))?.source).toBe("serveur");
  const corps = h.fetchImpl.mock.calls.map(x => JSON.parse(String(x[1]?.body)));
  expect(corps).toEqual([{ tool: "m1_produire_digest", args: { date_reference: date } }, { tool: "m1_lire_transfert", args: { transfert_id: id } }]);
  expect(h.obtenirDepot).toHaveBeenCalledTimes(1);
  expect(h.depot.cles()).toHaveLength(1);
  const texte = await h.depot.lire(h.depot.cles()[0]);
  expect(JSON.parse(texte!).resultat).toEqual(f.digest_date.enveloppe);
  expect(texte).not.toContain(f.plainte_ouverte.enveloppe.resultat.resultat.conversation_id);
});
test("hors ligne : digest personnel/daté seul, aucune lecture réseau de contacts ni de l'autre personne", async () => {
  const h = harness(); await h.lectures.chargerDigest(date); h.horsLigne(); h.fetchImpl.mockClear();
  expect((await h.lectures.chargerDigest(date))?.source).toBe("cache");
  expect(await h.lectures.chargerTransfert(id)).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  h.autrePersonne(); expect((await h.lectures.chargerDigest(date))?.source).toBe("aucune");
  expect(h.fetchImpl).not.toHaveBeenCalled();
});
test("rôle retiré, date ou ID invalides : zéro ouverture KV et zéro HTTP", async () => {
  const h = harness();
  expect(await h.lectures.chargerDigest("2026-02-30")).toMatchObject({ source: "aucune", raison: { code: "REJ-DIGEST-DATE-INVALIDE" } });
  expect((await h.lectures.chargerTransfert("conversation-fictive"))?.source).toBe("aucune");
  h.retirerRole(); expect(await h.lectures.chargerTransfert(id)).toBeNull(); expect(await h.lectures.chargerDigest(date)).toBeNull();
  expect(h.obtenirDepot).not.toHaveBeenCalled(); expect(h.fetchImpl).not.toHaveBeenCalled();
});
test.each([f.role_retire_m1_produire_digest.corps, { ok: true, result: { ok: true, resultat: { accepte: false, verdict: {} } } }])(
  "un refus natif même illisible ne récupère pas le cache précédent (%p)", async corps => {
    const h = harness(); await h.lectures.chargerDigest(date);
    h.fetchImpl.mockImplementationOnce(async () => new Response(JSON.stringify(corps)));
    expect((await h.lectures.chargerDigest(date))?.source).toBe("refus");
  });
test("réponse fiche tardive après changement de personne n'est ni affichée ni gardée", async () => {
  const h = harness(); let finir!: (r: Response) => void;
  h.fetchImpl.mockImplementationOnce(() => new Promise<Response>(r => { finir = r; }));
  const lecture = h.lectures.chargerTransfert(id); h.autrePersonne();
  finir(new Response(JSON.stringify(f.plainte_ouverte.corps)));
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(h.depot.cles()).toHaveLength(0);
});
test("échec d'initialisation KV n'empêche pas le digest frais, hors ligne reste explicite", async () => {
  const h = harness(); h.obtenirDepot.mockRejectedValue(new Error("KV fictif indisponible"));
  expect((await h.lectures.chargerDigest(date))?.source).toBe("serveur");
  h.horsLigne(); h.fetchImpl.mockClear();
  expect((await h.lectures.chargerDigest(date))?.source).toBe("aucune"); expect(h.fetchImpl).not.toHaveBeenCalled();
});
test("fiche d'une autre référence ou digest d'une autre date ne sont pas affichés", async () => {
  const h = harness();
  h.fetchImpl.mockImplementationOnce(async () => new Response(JSON.stringify(f.urgence_ouverte.corps)));
  expect((await h.lectures.chargerTransfert(id))?.source).toBe("aucune");
  h.fetchImpl.mockImplementationOnce(async () => new Response(JSON.stringify(f.digest_autre_jour.corps)));
  expect((await h.lectures.chargerDigest(date))?.source).toBe("aucune");
  expect(h.depot.cles()).toHaveLength(0);
});
