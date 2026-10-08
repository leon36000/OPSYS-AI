import { dateDigestM1Valide, identifiantTransfertM1Valide, lireDigestM1, lireTransfertM1 } from "./contrat";
import { FIXTURES_M1 } from "./fixtures";

const f = FIXTURES_M1.reponses;
function copie(): Record<string, unknown> { return JSON.parse(JSON.stringify(f.plainte_ouverte.enveloppe.resultat.resultat)); }
const envelopper = (v: unknown) => ({ ok: true, resultat: { accepte: true, resultat: v } });

test.each(["plainte_ouverte", "urgence_ouverte", "rappel_non_assigne", "rappel_assigne", "transfert_omissions", "plainte_stop"] as const)("fiche native %s gardée exactement", nom => {
  const c = f[nom], r = lireTransfertM1(c.enveloppe, c.args.transfert_id);
  expect(r).toEqual({ ok: true, value: c.enveloppe.resultat.resultat });
});
test.each(["digest_vide", "digest_date", "digest_autre_jour"] as const)("digest natif %s gardé en texte intégral", nom => {
  const c = f[nom]; expect(lireDigestM1(c.enveloppe, c.args.date_reference)).toEqual({ ok: true, value: c.enveloppe.resultat });
});
test("une autre fiche ne confirme pas le transfert demandé", () => {
  expect(lireTransfertM1(f.plainte_ouverte.enveloppe, f.urgence_ouverte.args.transfert_id).ok).toBe(false);
});
test("un autre digest ne confirme pas la date demandée", () => {
  expect(lireDigestM1(f.digest_date.enveloppe, "2024-02-29").ok).toBe(false);
});
test("inconnu, refus nominal et troncature ne deviennent jamais une fiche vide", () => {
  expect(lireTransfertM1(f.transfert_inconnu.enveloppe)).toMatchObject({ ok: false, code: "REJ-TRANSFERT-INCONNU" });
  expect(lireDigestM1(f.digest_date_invalide.enveloppe)).toMatchObject({ ok: false, code: "REJ-DIGEST-DATE-INVALIDE" });
  expect(lireTransfertM1({ ...f.plainte_ouverte.enveloppe, tronque: true })).toMatchObject({ ok: false, code: "reponse_tronquee" });
  expect(lireDigestM1({ ...f.digest_date.enveloppe, tronque: true })).toMatchObject({ ok: false, code: "reponse_tronquee" });
});
test("dates calendaires ASCII et vrais IDs tr20hex seulement", () => {
  expect(dateDigestM1Valide("2024-02-29")).toBe(true);
  for (const v of ["2023-02-29", "0000-01-01", "２０２６-１０-０７", "2026-10-07\n", "2026-1-01", null]) expect(dateDigestM1Valide(v)).toBe(false);
  expect(identifiantTransfertM1Valide(f.plainte_ouverte.args.transfert_id)).toBe(true);
  for (const v of [f.plainte_ouverte.args.transfert_id + "\n", "sms:plainte-fictive", "lead-fictif", null]) expect(identifiantTransfertM1Valide(v)).toBe(false);
});
test("clôture et contact natifs optionnels ont leur état propre", () => {
  const v = copie(); v.statut = "clos"; v.contact = { telephone: "514-555-0142", courriel: "fictif@example.test" };
  for (const k of ["brouillon_reponse", "envoye", "gabarit"]) delete v[k];
  v.cloture = { par: "owner.fictif", role: "nathan_owner", voie: "approbation", motif: "Client rappelé en personne.", clos_le: "2026-09-16T12:00:00Z" };
  expect(lireTransfertM1(envelopper(v))).toEqual({ ok: true, value: v });
  delete v.cloture; expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
});
test("STOP et juridique ne peuvent porter un brouillon présenté comme envoyé", () => {
  const v = copie(); v.client_retire_des_messages = true;
  expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
  v.client_retire_des_messages = false; v.categories = ["avocat"]; v.termes = {}; v.niveau = "N5";
  expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
  v.brouillon_reponse = null; v.sans_brouillon = "sujet_legal_reponse_humaine";
  expect(lireTransfertM1(envelopper(v)).ok).toBe(true);
  v.envoye = true; expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
});
test("omis, rappel nullable et nombres JSON sûrs restent cohérents", () => {
  const v = copie(); v.messages_suivants_omis = 1;
  expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
  v.messages_suivants_omis = Number.MAX_SAFE_INTEGER + 1;
  expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
  const r: Record<string, unknown> = JSON.parse(JSON.stringify(f.rappel_non_assigne.enveloppe.resultat.resultat));
  r.suivi_rappel = { ...f.rappel_non_assigne.enveloppe.resultat.resultat.suivi_rappel, role: "admin" };
  expect(lireTransfertM1(envelopper(r)).ok).toBe(false);
});
test("snapshot indépendant refuse getter, héritage, cycles, trous et faux constructeurs sans les appeler", () => {
  let appels = 0;
  const v = copie(); Object.defineProperty(v, "resume", { get: () => { appels++; return "injection"; }, enumerable: true });
  expect(lireTransfertM1(envelopper(v)).ok).toBe(false); expect(appels).toBe(0);
  const herite = Object.create(copie()); expect(lireTransfertM1(envelopper(herite)).ok).toBe(false);
  const cycle = copie(); cycle.contact = cycle; expect(lireTransfertM1(envelopper(cycle)).ok).toBe(false);
  const trou = copie(); trou.messages_couverts = new Array(1); expect(lireTransfertM1(envelopper(trou)).ok).toBe(false);
  const faux = copie(), proto = Object.create(null);
  Object.defineProperty(proto, "constructor", { value: function Object() { return null; } });
  Object.setPrototypeOf(faux, proto); expect(lireTransfertM1(envelopper(faux)).ok).toBe(false);
  const natif = copie(), lu = lireTransfertM1(envelopper(natif)); expect(lu.ok).toBe(true);
  natif.resume = "mutation locale"; if (lu.ok) expect(lu.value.resume).not.toBe(natif.resume);
});
test("grammaire digest entière requise, sans DTO console ni grille reconstruite", () => {
  for (const texte of ["", "DIGEST - Période de référence : 2026-09-15", f.digest_date.enveloppe.resultat.replace("- texte: signal: 15\n", ""), f.digest_date.enveloppe.resultat + "\ncontact: 5145550142"]) {
    expect(lireDigestM1({ ok: true, resultat: texte }).ok).toBe(false);
  }
  expect(lireDigestM1({ ok: true, resultat: { grille: [] } }).ok).toBe(false);
});
test("contact null et destinataire configuré sont des valeurs serveur explicites", () => {
  const v = copie(); v.contact = null; v.destinataire = "admin"; v.verdict_destinataire = null;
  expect(lireTransfertM1(envelopper(v))).toEqual({ ok: true, value: v });
  delete v.contact; expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
});
test("rappel avec tentative garde les dates et nullable prochaine échéance", () => {
  const v: Record<string, unknown> = JSON.parse(JSON.stringify(f.rappel_assigne.enveloppe.resultat.resultat));
  const suivi = { ...f.rappel_assigne.enveloppe.resultat.resultat.suivi_rappel, tentatives_sans_contact: 1,
    derniere_tentative_le: "2026-10-08T02:00:00Z", prochaine_tentative_le: null };
  v.suivi_rappel = suivi; expect(lireTransfertM1(envelopper(v))).toEqual({ ok: true, value: v });
  v.suivi_rappel = { ...suivi, derniere_tentative_le: null };
  expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
});
test("extraits Unicode sont bornés en points de code Python et conservés sans normalisation", () => {
  const v = copie();
  const texte = "😀".repeat(350);
  v.messages_couverts = [{ ...f.plainte_ouverte.enveloppe.resultat.resultat.messages_couverts[0], texte }];
  expect(lireTransfertM1(envelopper(v))).toEqual({ ok: true, value: v });
  v.messages_couverts = [{ ...f.plainte_ouverte.enveloppe.resultat.resultat.messages_couverts[0], texte: texte + "😀" }];
  expect(lireTransfertM1(envelopper(v)).ok).toBe(false);
});
test("constructeurs getters/faux Array, propriétés extra et nombres non finis sont fermés", () => {
  let appels = 0;
  const v = copie(), proto = Object.create(null);
  Object.defineProperty(proto, "constructor", { get: () => { appels++; return Object; } });
  Object.setPrototypeOf(v, proto); expect(lireTransfertM1(envelopper(v)).ok).toBe(false); expect(appels).toBe(0);
  const tab = [f.plainte_ouverte.enveloppe.resultat.resultat.messages_couverts[0]], p = Object.create(Object.prototype);
  Object.defineProperty(p, "constructor", { value: function Array() { return []; } });
  Object.setPrototypeOf(tab, p); const a = copie(); a.messages_couverts = tab;
  expect(lireTransfertM1(envelopper(a)).ok).toBe(false);
  for (const valeur of [NaN, Infinity, -1, 0.5]) { const n = copie(); n.messages_couverts_omis = valeur; expect(lireTransfertM1(envelopper(n)).ok).toBe(false); }
  const extra = copie(); extra.role = "admin"; expect(lireTransfertM1(envelopper(extra)).ok).toBe(false);
});
