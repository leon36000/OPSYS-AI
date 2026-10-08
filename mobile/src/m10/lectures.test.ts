import { creerChargeurLecturesMemoire } from "./lectures";
import { FIXTURES_M10 } from "./fixtures";
import { FIXTURES_DOSSIER_M10 } from "./fixturesDossier";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { capturerSessionAdminLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { lireCacheSection } from "../admin/cache";
import fixturesPaquet from "./fixturesPaquetAffaire.json";

const session = { urlBase: "https://core.fictif.test", jeton: "jeton-fictif", appareilId: "appareil-fictif" };
const personne = { jeton: session.jeton, appareilId: session.appareilId, personne: "gestionnaire.fictif", role: "admin" };
const f = FIXTURES_M10.reponses;
function setup() {
  definirConfigurationAppel(session); definirPersonneConfirmee(personne);
  const depot = new DepotCleValeurMemoire(); let online = true;
  const envelopes = new Map<string, unknown>([
    ["m10_lister_signaux", f.signaux_ouverts.enveloppe], ["m10_lister_references", f.catalogue_page_1.enveloppe],
    ["m10_statut_decision", f.decision_proposee.enveloppe], ["m10_statut_revision", f.revision_en_attente.enveloppe],
    ["m10_lire_revision", FIXTURES_DOSSIER_M10.reponses.dossier_complet.enveloppe],
  ]);
  const appeler = jest.fn(async (p: ParametresAppelOutil): Promise<ResultatAppelOutil> => ({ ok: true, result: envelopes.get(p.requete.tool) }));
  const obtenirDepot = jest.fn(async () => depot);
  const deps = { capturerSession: capturerSessionAdminLecture, obtenirDepot, appelerOutil: appeler, fetchImpl: fetch,
    horloge: () => ({ maintenant: new Date("2026-10-07T15:00:00Z"), decalageMinutesUTC: -240 }), enLigne: () => online };
  return { depot, appeler, obtenirDepot, chargeur: creerChargeurLecturesMemoire(deps), deps, horsLigne: () => { online = false; } };
}
afterEach(() => { definirPersonneConfirmee(null); definirConfigurationAppel(null); });

test("arguments natifs exacts, date client, projections normalisées et cache uniquement informatif", async () => {
  const h = setup();
  expect((await h.chargeur.chargerSignaux())?.source).toBe("serveur");
  expect((await h.chargeur.chargerReferences())?.source).toBe("serveur");
  expect(h.appeler.mock.calls.map(c => c[0].requete)).toEqual([
    { tool: "m10_lister_signaux", args: {} }, { tool: "m10_lister_references", args: { limite: 8, decalage: 0 } },
  ]);
  const cache = await lireCacheSection(h.depot, personne.personne, "memoire_signaux");
  expect(cache?.misAJourLe).toBe("2026-10-07T15:00:00.000Z");
  expect(cache?.resultat).toEqual({ ok: true, resultat: f.signaux_ouverts.enveloppe.resultat });
});

test("hors ligne aucune requête : cache personnel marqué, aucun statut ou dossier gardé", async () => {
  const h = setup(); await h.chargeur.chargerSignaux(); await h.chargeur.chargerReferences();
  h.appeler.mockClear(); h.horsLigne();
  expect((await h.chargeur.chargerSignaux())?.source).toBe("cache");
  expect((await h.chargeur.chargerReferences())?.source).toBe("cache");
  expect((await h.chargeur.chargerStatutDecision("id-fictif"))?.source).toBe("aucune");
  expect((await h.chargeur.chargerDossier(FIXTURES_DOSSIER_M10.reponses.dossier_complet.args.revision_ligne_id))?.source).toBe("aucune");
  expect(h.appeler).not.toHaveBeenCalled();
  definirPersonneConfirmee({ ...personne, personne: "autre.fictif" });
  expect((await h.chargeur.chargerSignaux())?.source).toBe("aucune");
});

test("le rôle retiré à jeton/personne égaux interdit aussi tout cache sans réseau", async () => {
  const h = setup(); await h.chargeur.chargerSignaux(); h.appeler.mockClear(); h.obtenirDepot.mockClear(); h.horsLigne();
  definirPersonneConfirmee({ ...personne, role: "seller" });
  expect(await h.chargeur.chargerSignaux()).toBeNull();
  expect(h.appeler).not.toHaveBeenCalled(); expect(h.obtenirDepot).not.toHaveBeenCalled();
});

test.each([
  { ok: true, resultat: { accepte: false, verdict: { code: "REJ-FICTIF", detail: "Refus fictif" } } },
  { ok: true, resultat: { accepte: false, verdict: 9 } },
  { ok: false, erreur: "hors_portee_role", details: "Refus fictif" },
])("le serveur qui refuse ne cède jamais à un ancien cache (%j)", async env => {
  const h = setup(); await h.chargeur.chargerSignaux();
  h.appeler.mockResolvedValue({ ok: true, result: env });
  expect((await h.chargeur.chargerSignaux())?.source).toBe("refus");
});

test("une réponse tardive à l'ancienne personne ne s'affiche pas et n'écrit pas son cache", async () => {
  const h = setup(); let finir!: (v: ResultatAppelOutil) => void;
  h.appeler.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const lecture = h.chargeur.chargerSignaux();
  while (h.appeler.mock.calls.length === 0) await Promise.resolve();
  definirPersonneConfirmee({ ...personne, personne: "autre.fictif" });
  finir({ ok: true, result: f.signaux_ouverts.enveloppe });
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(await lireCacheSection(h.depot, personne.personne, "memoire_signaux")).toBeNull();
});

test("dossier/statuts servent sans SQLite ; la panne cache n'empêche pas une lecture serveur informative", async () => {
  const h = setup(); h.obtenirDepot.mockRejectedValue(new Error("cache fictif indisponible"));
  expect((await h.chargeur.chargerStatutDecision("id-fictif"))?.source).toBe("serveur");
  expect((await h.chargeur.chargerDossier(FIXTURES_DOSSIER_M10.reponses.dossier_complet.args.revision_ligne_id))?.source).toBe("serveur");
  expect(h.obtenirDepot).not.toHaveBeenCalled();
  expect((await h.chargeur.chargerSignaux())?.source).toBe("serveur");
});

test("une page d'un autre décalage ne remplace pas la page demandée", async () => {
  const h = setup();
  expect((await h.chargeur.chargerReferences(8))?.source).toBe("aucune");
});

const dossierAffaireFictif = fixturesPaquet.reponses.origine_recue;
const argsPaquet = dossierAffaireFictif.arguments;
test("paquet : façade appareil et arguments exacts, sans démarrer SQLite ni écrire de cache", async () => {
  const h = setup(); h.appeler.mockResolvedValue({ ok: true, result: dossierAffaireFictif.enveloppe });
  expect((await h.chargeur.chargerPaquetAffaire(argsPaquet.affaire_id, argsPaquet.horodatage))?.source).toBe("serveur");
  expect(h.appeler.mock.calls.map(v => v[0].requete)).toEqual([{ tool: "m10_lire_paquet_affaire_appareil", args: argsPaquet }]);
  expect(h.obtenirDepot).not.toHaveBeenCalled();
  h.horsLigne(); h.appeler.mockClear();
  expect((await h.chargeur.chargerPaquetAffaire(argsPaquet.affaire_id, argsPaquet.horodatage))?.source).toBe("aucune");
  expect(h.appeler).not.toHaveBeenCalled(); expect(h.obtenirDepot).not.toHaveBeenCalled();
});
test.each(["seller", "employee", "client"])("paquet : rôle %s refusé avant HTTP et dépôt", async role => {
  const h = setup(); definirPersonneConfirmee({ ...personne, role });
  expect(await h.chargeur.chargerPaquetAffaire(argsPaquet.affaire_id, argsPaquet.horodatage)).toBeNull();
  expect(h.appeler).not.toHaveBeenCalled(); expect(h.obtenirDepot).not.toHaveBeenCalled();
});
test("paquet : arguments invalides et réponse liée à une autre affaire ferment sans fallback", async () => {
  const h = setup();
  expect((await h.chargeur.chargerPaquetAffaire("../fictif", argsPaquet.horodatage))?.source).toBe("aucune");
  expect(h.appeler).not.toHaveBeenCalled();
  h.appeler.mockResolvedValue({ ok: true, result: dossierAffaireFictif.enveloppe });
  expect((await h.chargeur.chargerPaquetAffaire("autre-fictive", argsPaquet.horodatage))?.source).toBe("aucune");
  expect(h.obtenirDepot).not.toHaveBeenCalled();
});
test("paquet : retrait rôle à personne et jeton égaux masque la réponse tardive", async () => {
  const h = setup(); let finir!: (v: ResultatAppelOutil) => void;
  h.appeler.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const lecture = h.chargeur.chargerPaquetAffaire(argsPaquet.affaire_id, argsPaquet.horodatage);
  definirPersonneConfirmee({ ...personne, role: "employee" });
  finir({ ok: true, result: dossierAffaireFictif.enveloppe });
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "lecture_remplacee" } });
  expect(h.obtenirDepot).not.toHaveBeenCalled();
});
test("paquet : réseau perdu pendant HTTP ferme une réponse valide sans cache", async () => {
  const h = setup(); let finir!: (v: ResultatAppelOutil) => void;
  h.appeler.mockImplementationOnce(() => new Promise(r => { finir = r; }));
  const lecture = h.chargeur.chargerPaquetAffaire(argsPaquet.affaire_id, argsPaquet.horodatage);
  h.horsLigne(); finir({ ok: true, result: dossierAffaireFictif.enveloppe });
  expect(await lecture).toMatchObject({ source: "aucune", raison: { code: "hors_ligne" } });
  expect(h.obtenirDepot).not.toHaveBeenCalled();
});
