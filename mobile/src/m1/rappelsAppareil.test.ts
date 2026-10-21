// FICTIF : oracles RAM du contrat ROOT ; aucun JSON de producteur/HTTP n'est inventé.
import type { MutationOutbox } from "../outbox/types";
import capturesSQL from "./fixturesRappelsSQL.json";
import capturesCap from "./fixturesRappelsCapSQL.json";
const api = () => require("./rappelsAppareil") as typeof import("./rappelsAppareil");
const transfert = "tr-0123456789abcdef0123", snapshot = "a".repeat(64);
const uuid = "94a2d1de-c87c-40d0-a2ac-067b04088534";
const horloge = { maintenant: new Date("2026-10-09T04:00:00Z"), decalageMinutesUTC: -240 };
const cible = { personne: "admin.fictif", appareilId: "DEVICE-FICTIF", urlBase: "https://fictif.invalid" };
const suivi = () => ({ snapshot_suivi: snapshot, responsable: null, role: null, pris_en_charge_le: null,
  tentatives_sans_contact: 0, derniere_tentative_le: null, prochaine_tentative_le: null });
const rappel = (id = transfert) => ({ transfert_id: id, conversation_id: `sms-${"b".repeat(24)}`, lead_id: null,
  canal: "telephone", ouvert_le: "2026-10-08T12:00:00.123456-04:00", nombre_sources: 1,
  derniere_source: { ligne_id: "c".repeat(64), statut: "voicemail", recu_le: "2026-10-08T12:00:00.123456-04:00" }, suivi_rappel: suivi() });
const enveloppe = (rappels = [rappel()], apres: string | null = null, reste = 0) => ({ ok: true, resultat: { accepte: true, resultat: {
  rappels, page: { apres_transfert_id: apres, taille_page: 8, total: rappels.length + reste, retournes: rappels.length,
    reste, apres_suivant: reste ? rappels.at(-1)!.transfert_id : null } } } });
const mutation = (): MutationOutbox => ({ ...api().creerMutationPriseRappelM1({ transfert_id: transfert, snapshot_attendu: snapshot },
  () => uuid, horloge, cible), proprietaire: cible.personne });
const ack = () => ({ version: 1, transfert_id: transfert, action: "prise_en_charge", ligne_id: "d".repeat(64), precedent_ligne_id: "e".repeat(64),
  index: 7, snapshot_attendu: snapshot, par: cible.personne, role: "admin", voie: "appareil", appareil: cible.appareilId,
  intention_uuid: uuid, recu_le_serveur: "2026-10-09T04:00:01.123456+00:00", horodatage_appareil: "2026-10-09T00:00:00-04:00",
  suivi_rappel: { ...suivi(), snapshot_suivi: "f".repeat(64), responsable: cible.personne, role: "admin",
    pris_en_charge_le: "2026-10-09T04:00:01.123456+00:00" } });
const reponse = (a = ack()) => ({ ok: true, resultat: { accepte: true, resultat: a } });
test("les deux builders ferment leurs arguments sans réparation ni heure métier", () => {
  expect(api().construireArgumentsRappelsM1()).toEqual({ apres_transfert_id: null, taille_page: 8 });
  expect(api().construireArgumentsPriseRappelM1(transfert, snapshot)).toEqual({ transfert_id: transfert, snapshot_attendu: snapshot });
  for (const v of [0, 9, true, 1.5, "8"]) expect(() => api().construireArgumentsRappelsM1(null, v as number)).toThrow();
  for (const v of [" tr-0123456789abcdef0123", "tr-ABCDEF01234567890123", "", null])
    expect(() => api().construireArgumentsPriseRappelM1(v as string, snapshot)).toThrow();
});
test("la page conserve les champs source sans contact ni message", () => {
  const r = api().lireRappelsM1(enveloppe(), api().construireArgumentsRappelsM1());
  expect(r.ok).toBe(true); if (r.ok) expect(r.value.rappels[0]).toEqual(rappel());
  expect(api().lireRappelsM1(enveloppe([]), api().construireArgumentsRappelsM1()).ok).toBe(true);
});
test.each(["contact", "telephone", "message", "call_id"])("un champ source privé %s ferme la page entière", cle => {
  const row = { ...rappel(), [cle]: "FICTIF privé" }; expect(api().lireRappelsM1(enveloppe([row]), api().construireArgumentsRappelsM1()).ok).toBe(false);
});
test("keyset exclusif, ordre, doublon et curseur sont liés aux données et à la requête", () => {
  const args = api().construireArgumentsRappelsM1(transfert);
  expect(api().lireRappelsM1(enveloppe([rappel()], transfert), args).ok).toBe(false);
  expect(api().lireRappelsM1(enveloppe([rappel(), rappel()]), api().construireArgumentsRappelsM1()).ok).toBe(false);
  const c = enveloppe(); c.resultat.resultat.page.apres_suivant = transfert;
  expect(api().lireRappelsM1(c, api().construireArgumentsRappelsM1()).ok).toBe(false);
  expect(api().lireRappelsM1(enveloppe(), { apres_transfert_id: null, taille_page: 8, agent_id: "M1" }).ok).toBe(false);
});
test("une page avec reste comporte la taille demandée ; total courant n'est pas un snapshot", () => {
  const rows = Array.from({ length: 8 }, (_, i) => rappel(`tr-${i.toString(16).padStart(20, "0")}`));
  expect(api().lireRappelsM1(enveloppe(rows, null, 1), api().construireArgumentsRappelsM1()).ok).toBe(true);
  expect(api().lireRappelsM1(enveloppe([rappel()], null, 1), api().construireArgumentsRappelsM1()).ok).toBe(false);
});
test("getters et prototypes ne sont pas consultés", () => {
  const getter = jest.fn(() => true), c = Object.defineProperty(enveloppe(), "ok", { get: getter, enumerable: true });
  expect(api().lireRappelsM1(c, api().construireArgumentsRappelsM1()).ok).toBe(false); expect(getter).not.toHaveBeenCalled();
  expect(api().lireRappelsM1(Object.create(enveloppe()), api().construireArgumentsRappelsM1()).ok).toBe(false);
});
test("hash, UUID et conversation ne tolèrent pas de suffixe newline malgré l'ancre regex", () => {
  expect(() => api().construireArgumentsPriseRappelM1(transfert, `${snapshot}\n`)).toThrow();
  expect(() => api().creerMutationPriseRappelM1({ transfert_id: transfert, snapshot_attendu: snapshot }, () => `${uuid}\n`, horloge, cible)).toThrow();
  expect(api().lireRappelsM1(enveloppe([{ ...rappel(), conversation_id: `${rappel().conversation_id}\n` }]), api().construireArgumentsRappelsM1()).ok).toBe(false);
});
test("ACK propre conserve les quinze champs et le préfixe v1 même après un état courant différent", () => {
  const m = mutation(), r = api().interpreterPriseRappelM1(reponse(), m);
  expect(r.accepte).toBe(true); if (r.accepte) expect(r.resume).toEqual(ack());
  expect(api().interpreterPriseRappelM1({ ...reponse(), rejoue: true }, m).accepte).toBe(true);
  expect(api().validerRecuPriseRappelM1({ ...m, statut: "envoyee", resumeAccepte: ack() })).toBe(true);
});
test.each(["transfert_id", "snapshot_attendu", "par", "appareil", "intention_uuid", "role", "action"])("ACK %s différent ne confirme pas l'intention", cle => {
  expect(api().interpreterPriseRappelM1(reponse({ ...ack(), [cle]: "FICTIF autre" }), mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test("l'heure est comparée exactement à la microseconde sans Date.parse permissif", () => {
  const m = mutation();
  expect(api().interpreterPriseRappelM1(reponse({ ...ack(), horodatage_appareil: "2026-10-09T04:00:00+00:00" }), m).accepte).toBe(true);
  for (const h of ["2026-10-09T00:00:00.000001-04:00", "20261009T00:00:00-04:00", "2026-10-09T00:00-04:00", "2026-02-30T00:00:00-04:00"])
    expect(api().interpreterPriseRappelM1(reponse({ ...ack(), horodatage_appareil: h }), m).accepte).toBe(false);
});
test("bool/index, suivi, predecessor ou champ extra invalident l'ACK entier", () => {
  for (const patch of [{ index: true }, { index: 0 }, { precedent_ligne_id: null }, { plus: true },
    { suivi_rappel: { ...ack().suivi_rappel, responsable: "autre.fictif" } }, { suivi_rappel: { ...ack().suivi_rappel, tentatives_sans_contact: 1 } }])
    expect(api().interpreterPriseRappelM1(reponse({ ...ack(), ...patch } as ReturnType<typeof ack>), mutation()).accepte).toBe(false);
});
test("refus préclaim, identité et namespace inconnu conservent la même intention", () => {
  const m = mutation();
  for (const code of ["REJ-M1-RAPPEL-SNAPSHOT-PERIME", "REJ-M1-RAPPEL-IDENTITE-INVALIDE", "REJ-IDENTITE-APPAREIL-INVALIDE"])
    expect(api().interpreterPriseRappelM1({ ok: false, erreur: code, details: "FICTIF" }, m)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  for (const code of ["REJ-M1-RAPPEL-IDENTITE-INVALIDE", "REJ-M6-PREUVES-WCT-INCONNU"])
    expect(api().interpreterPriseRappelM1({ ok: true, resultat: { accepte: false, verdict: { code, detail: "FICTIF" } } }, m)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  expect(api().interpreterPriseRappelM1({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-M1-RAPPEL-SNAPSHOT-PERIME", detail: "FICTIF" } } }, m)).toEqual({ accepte: false, verdict: { code: "REJ-M1-RAPPEL-SNAPSHOT-PERIME", detail: "FICTIF" } });
});
test("payload local fermé n'envoie que deux args et reste lié à personne/device/destination", () => {
  const m = mutation(); expect(m.chantierId).toBe(`rappel:${transfert}`);
  expect(api().argumentsRpcPriseRappelM1(m)).toEqual({ transfert_id: transfert, snapshot_attendu: snapshot });
  expect(api().verifierDestinationPriseRappelM1(m, cible)).toBe(true);
  expect(api().verifierDestinationPriseRappelM1(m, { ...cible, personne: "autre.fictif" })).toBe(false);
  expect(api().verifierDestinationPriseRappelM1(m, { ...cible, appareilId: "autre.fictif" })).toBe(false);
  expect(api().verifierDestinationPriseRappelM1(m, { ...cible, urlBase: "https://autre.invalid" })).toBe(false);
  expect(api().validerRecuPriseRappelM1({ ...m, statut: "envoyee", resumeAccepte: { ...ack(), intention_uuid: "autre" } })).toBe(false);
});
test.each(capturesSQL.captures.filter(c => c.request.nom === "m1_lister_rappels_appareil"))("capture SQL réelle $phase sans réécriture", c => {
  expect(JSON.stringify(JSON.parse(c.response_utf8))).toBe(JSON.stringify(c.response));
  expect(api().lireRappelsM1(c.response, c.request.arguments).ok).toBe(true);
});
test.each(capturesSQL.captures.filter(c => c.request.meta !== null))("ACK/cache SQL réel $phase lié aux métadonnées originales", c => {
  const meta = c.request.meta!;
  const lu = api().lirePriseRappelM1(c.response, c.request.arguments, { intention_uuid: meta.cle, appareil: meta.appareil,
    par: "admin-rappel-fictif", horodatage_appareil: meta.horodatage_appareil });
  if (c.phase.startsWith("refus_certain")) expect(lu).toMatchObject({ ok: false, code: "REJ-M1-RAPPEL-SNAPSHOT-PERIME" });
  else expect(lu.ok).toBe(true);
});
test("les deux fixtures sont BYTE-identiques à leurs captures réelles scellées", () => {
  const fs = require("node:fs") as typeof import("node:fs"), crypto = require("node:crypto") as typeof import("node:crypto");
  for (const [file, sha] of [["./fixturesRappelsSQL.json", "4671b37f695da1ce1e135a5155228ab917a6e937971b0794e46075bf6427199c"],
    ["./fixturesRappelsCapSQL.json", "0fc6c4eea437a8c179b7bf8e07a8a5165756fa8592fa0ae1ec9ce895788fef39"]])
    expect(crypto.createHash("sha256").update(fs.readFileSync(require.resolve(file))).digest("hex")).toBe(sha);
});
test.each(capturesCap.phases)("octets Cap réels $name : parser et issue distincts", c => {
  const crypto = require("node:crypto") as typeof import("node:crypto");
  expect(crypto.createHash("sha256").update(c.response_utf8).digest("hex")).toBe(c.response_sha256);
  expect(JSON.parse(c.response_utf8)).toEqual(c.response);
  if (c.tool === "m1_lister_rappels_appareil") {
    expect(api().lireRappelsM1(c.response, c.arguments).ok).toBe(c.name !== "lecture-meta-refuse"); return;
  }
  const cibleCap = { personne: "admin-rappel-fictif", appareilId: "APP-RAPPEL-FICTIF", urlBase: "https://fictif.invalid" };
  const m = { ...api().creerMutationPriseRappelM1(c.arguments as unknown as import("./rappelsAppareil").ArgumentsPriseRappelM1,
    () => c.mutation_uuid!, { maintenant: new Date("2026-10-09T04:00:00Z"), decalageMinutesUTC: 0 }, cibleCap), proprietaire: cibleCap.personne };
  const interpretation = api().interpreterPriseRappelM1(c.response, m);
  if (c.name.includes("inconnu") || c.name === "autre-corps-meme-UUID") expect(interpretation).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  else if (c.name.includes("refus")) expect(interpretation).toMatchObject({ accepte: false, verdict: { code: "REJ-M1-RAPPEL-SNAPSHOT-PERIME" } });
  else expect(interpretation.accepte).toBe(true);
});
