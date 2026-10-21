import fixtures from "./fixturesPaquetAffaireNative.json";
import { construireArgumentsPaquetAffaire, lirePaquetAffaire } from "./paquetAffaire";
import { creerChargeurLecturesMemoire } from "./lectures";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";

// Captures d'une préparation fictive avec vrai Gateway DEVICE ; ces tests ne rejouent aucun login/HTTP.
test.each(Object.entries(fixtures.positives))("capture DEVICE %s : contrat entier, références exactes et vue restrictive", (_nom, e) => {
  expect(fixtures.fictif).toBe(true);
  expect(e.requete.tool).toBe("m10_lire_paquet_affaire_appareil");
  expect(e.statut_http).toBe(200);
  expect(e.enveloppe).toEqual(e.gateway.result);
  expect(construireArgumentsPaquetAffaire(e.arguments.affaire_id, e.arguments.horodatage)).toEqual(e.arguments);
  const lu = lirePaquetAffaire(e.enveloppe, e.arguments.affaire_id, e.arguments.horodatage);
  expect(lu.ok).toBe(true);
  if (!lu.ok) throw new Error(lu.code);
  expect(lu.value.affaire_id).toBe(e.arguments.affaire_id);
  expect(lu.value.horodatage).toBe(e.arguments.horodatage);
  expect(lu.value.confidentialite.agent).toBeNull();
  for (const couche of lu.value.couches) for (const fait of couche.faits) {
    expect(["PUBLIC_INTERNAL", "INTERNAL"]).toContain(fait.confidentialite);
  }
});

test("la capture du même paquet après redémarrage reste strictement égale", () => {
  expect(fixtures.positives.restart.enveloppe).toEqual(fixtures.positives["omissions-consolidation"].enveloppe);
});

test.each(Object.entries(fixtures.refus))("refus DEVICE %s : verdict natif conservé sans paquet partiel", (_nom, e) => {
  const lu = lirePaquetAffaire(e.enveloppe, e.arguments.affaire_id, e.arguments.horodatage);
  expect(lu).toEqual({ ok: false, code: e.enveloppe.resultat.verdict.code, detail: e.enveloppe.resultat.verdict.detail });
});

test.each(Object.entries(fixtures.positives))("chargeur câblé à la réponse Gateway %s sans dépôt ni autre outil", async (_nom, e) => {
  const appeler = jest.fn(async (_p: ParametresAppelOutil) => e.gateway as ResultatAppelOutil);
  const obtenirDepot = jest.fn(async () => { throw new Error("SQLite interdit pour cette lecture"); });
  const chargeur = creerChargeurLecturesMemoire({
    capturerSession: () => ({ session: { urlBase: "https://gateway.fictif.test", jeton: "fictif", appareilId: "fictif", personne: "admin.fictif" }, courante: () => true }),
    obtenirDepot, appelerOutil: appeler, fetchImpl: fetch, enLigne: () => true,
    horloge: () => ({ maintenant: new Date("2026-10-08T08:00:00Z"), decalageMinutesUTC: -240 }),
  });
  const lu = await chargeur.chargerPaquetAffaire(e.arguments.affaire_id, e.arguments.horodatage);
  expect(lu?.source).toBe("serveur");
  expect(appeler).toHaveBeenCalledTimes(1);
  expect(appeler.mock.calls[0][0].requete).toEqual({ tool: "m10_lire_paquet_affaire_appareil", args: e.arguments });
  expect(appeler.mock.calls[0][0].requete).not.toHaveProperty("agentId");
  expect(obtenirDepot).not.toHaveBeenCalled();
});
