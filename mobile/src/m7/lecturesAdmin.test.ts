import { lireDemandesAvisM7, lireFileApprobationM7 } from "./lecturesAdmin";
import { FIXTURES_LECTURES_ADMIN_M7 as capture } from "./fixturesLecturesAdmin";

const directe = (resultat: unknown) => ({ ok: true, resultat });
const proposition = capture.captures.file_propose.enveloppe.resultat[0];
const page = capture.captures.avis.enveloppe.resultat;
const demande = page.demandes[0];

test("les captures HTTP fictives DIRECTES se lisent sans couche couple ni compteur legacy inventé", () => {
  expect(capture.fictif).toBe(true);
  expect(capture.capture_sha256).toBe("3d40a740721d23702808269cd1a2bfb80cafd72a2c52afb799c7451e44f8f9ec");
  const file = lireFileApprobationM7(capture.captures.file_propose.enveloppe);
  expect(file).toEqual({ ok: true, value: [{
    id: proposition.id, title: proposition.title, body: proposition.body, surface: proposition.surface,
    type: proposition.type, approval_status: "PROPOSE", proposer: "agent",
    propose_timestamp: "2026-10-07T22:42:11.231014+00:00", approver: "", approval_timestamp: "",
    timestamp: "2026-09-15T07:00:00-04:00",
  }] });
  expect(lireDemandesAvisM7(capture.captures.avis.enveloppe)).toEqual({ ok: true, value: page });
  expect(lireFileApprobationM7(directe({ accepte: true, resultat: [proposition] })).ok).toBe(false);
  expect(lireDemandesAvisM7(directe({ accepte: true, resultat: page })).ok).toBe(false);
});

test("le corps JSON éventuel reste du texte exact ; dates legacy vides sans date inventée", () => {
  const body = '{"texte":"Brouillon fictif","montant":null}';
  const lu = lireFileApprobationM7(directe([{ ...proposition, body, timestamp: "", approval_timestamp: "" }]));
  expect(lu.ok && lu.value[0].body).toBe(body);
  expect(lu.ok && lu.value[0].timestamp).toBe("");
  expect(lireFileApprobationM7(directe([{ ...proposition, body: { texte: "x" } }])).ok).toBe(false);
});

test("file vide et neuf propositions distinctes sont légales, sans limite de huit inventée", () => {
  expect(lireFileApprobationM7(directe([]))).toEqual({ ok: true, value: [] });
  const file = Array.from({ length: 9 }, (_, i) => ({ ...proposition, id: `id-fictif-${i}` }));
  const lu = lireFileApprobationM7(directe(file));
  expect(lu.ok && lu.value).toHaveLength(9);
});

test("l'avis est un brouillon sans consentement marketing inféré et sans données du registre privé", () => {
  const lu = lireDemandesAvisM7(directe({ ...page, demandes: [{ ...demande, nature_travaux: null,
    ville: null, lead_id: "privé-fictif", consentement: { ...demande.consentement, consentement_marketing: true } }] }));
  expect(lu).toEqual({ ok: true, value: { ...page, demandes: [{ ...demande, nature_travaux: null }] } });
  expect(lireDemandesAvisM7(directe({ ...page, demandes: [{ ...demande, approval_status: "APPROVED" }] })).ok).toBe(false);
});

test("avis : huit lignes au plus et reste natif sans curseur fabriqué", () => {
  expect(lireDemandesAvisM7(directe({ total: 0, demandes: [], reste: 0 }))).toEqual({ ok: true, value: { total: 0, demandes: [], reste: 0 } });
  const demandes = Array.from({ length: 8 }, (_, i) => ({ ...demande, id: `avis-${i}`, wct_id: `wct-${i}` }));
  expect(lireDemandesAvisM7(directe({ total: 12, demandes, reste: 4 }))).toEqual({ ok: true, value: { total: 12, demandes, reste: 4 } });
  expect(lireDemandesAvisM7(directe({ total: 1, demandes: [], reste: 1 })).ok).toBe(false);
  expect(lireDemandesAvisM7(directe({ total: 9, demandes: [...demandes, { ...demande, id: "neuvieme", wct_id: "wct9" }], reste: 0 })).ok).toBe(false);
});

test.each([-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, "1", null, undefined])("compteurs avis invalides %p", valeur => {
  for (const cle of ["total", "reste"]) expect(lireDemandesAvisM7(directe({ ...page, [cle]: valeur })).ok).toBe(false);
});

test("cohérence des compteurs et unicité ID/WCT, sans suppression silencieuse de lignes", () => {
  for (const invalide of [{ ...page, total: 2 }, { ...page, reste: 1 },
    { ...page, total: Number.MAX_SAFE_INTEGER, reste: Number.MAX_SAFE_INTEGER },
    { total: 2, demandes: [demande, demande], reste: 0 },
    { total: 2, demandes: [demande, { ...demande, id: "autre-id" }], reste: 0 },
    { total: 2, demandes: [demande, {}], reste: 0 }]) {
    expect(lireDemandesAvisM7(directe(invalide)).ok).toBe(false);
  }
  expect(lireFileApprobationM7(directe([proposition, proposition])).ok).toBe(false);
  expect(lireFileApprobationM7(directe([proposition, {}])).ok).toBe(false);
});

test("consentement : trois faits exacts nécessaires ; fuseau, microsecondes et espace conservés", () => {
  for (const date of ["2026-09-15T15:05:00.123456+00:00", "2026-09-15 11:05:00-04:00", "2024-02-29T12:00:00Z"]) {
    const lu = lireDemandesAvisM7(directe({ ...page, demandes: [{ ...demande, consentement: { ...demande.consentement, recueilli_le: date } }] }));
    expect(lu.ok && lu.value.demandes[0].consentement.recueilli_le).toBe(date);
  }
  for (const date of ["", "hier", "2026-09-15", "2026-09-15T15:05:00", "2026-02-30T12:00:00Z", "2026-09-15T24:00:00Z"]) {
    expect(lireDemandesAvisM7(directe({ ...page, demandes: [{ ...demande, consentement: { ...demande.consentement, recueilli_le: date } }] })).ok).toBe(false);
  }
  for (const cle of ["recueilli_par", "recueilli_le", "version_texte"]) {
    expect(lireDemandesAvisM7(directe({ ...page, demandes: [{ ...demande, consentement: { ...demande.consentement, [cle]: "" } }] })).ok).toBe(false);
  }
});

test("refus natifs et troncature technique sont explicites, aucun aperçu lu comme donnée", () => {
  for (const lire of [lireFileApprobationM7, lireDemandesAvisM7]) {
    expect(lire(capture.captures.identite_revoquee_0.enveloppe)).toEqual({ ok: false,
      ...capture.captures.identite_revoquee_0.enveloppe.resultat.verdict });
    expect(lire({ ok: false, erreur: "hors_portee_role", details: ["admin requis"] })).toEqual({ ok: false, code: "hors_portee_role", detail: "admin requis" });
    expect(lire({ ok: true, tronque: true, apercu: "[]" })).toMatchObject({ ok: false, code: "reponse_tronquee" });
  }
});

test("getters, héritages, listes creuses et prototypes altérés refusés sans exécuter d'accesseur", () => {
  const getter = jest.fn(() => "INTERDIT");
  const acces = Object.defineProperty({ ...demande }, "texte", { get: getter });
  const index = Object.defineProperty([], "0", { get: getter });
  const listeHeritee = Object.setPrototypeOf([demande], Object.create(Array.prototype));
  for (const demandes of [[acces], [Object.create(demande)], index, Array(1), listeHeritee]) {
    expect(lireDemandesAvisM7(directe({ ...page, demandes })).ok).toBe(false);
  }
  const verdict = Object.defineProperty({}, "code", { get: getter });
  const details = Object.defineProperty([], "0", { get: getter });
  for (const lire of [lireFileApprobationM7, lireDemandesAvisM7]) {
    for (const brut of [Object.create({ ok: true, resultat: [] }),
      Object.defineProperty({}, "ok", { get: getter }),
      directe({ accepte: false, verdict }), { ok: false, erreur: "arguments_invalides", details }]) {
      expect(lire(brut).ok).toBe(false);
    }
  }
  expect(getter).not.toHaveBeenCalled();
});

test("projection indépendante et objets à prototype nul légaux", () => {
  const brut = Object.assign(Object.create(null), page, { demandes: [Object.assign(Object.create(null), demande)] });
  const lu = lireDemandesAvisM7(directe(brut));
  expect(lu).toEqual({ ok: true, value: page });
  brut.demandes[0].texte = "altéré après lecture";
  expect(lu.ok && lu.value.demandes[0].texte).toBe(demande.texte);
});

test("une propriété obligatoire absente, un statut inconnu ou un type erroné ferme la file entière", () => {
  for (const cle of ["id", "title", "body", "surface", "type", "proposer", "propose_timestamp", "approver", "approval_timestamp", "timestamp"]) {
    const incomplet: Record<string, unknown> = { ...proposition };
    delete incomplet[cle];
    expect(lireFileApprobationM7(directe([incomplet])).ok).toBe(false);
  }
  for (const changement of [{ approval_status: "CONSENTEMENT_RETIRE" }, { surface: "facebook" },
    { type: "publication" }, { proposer: "" }, { body: 42 }, { approval_status: "APPROVED", approver: "" }]) {
    expect(lireFileApprobationM7(directe([{ ...proposition, ...changement }])).ok).toBe(false);
  }
  for (const approval_status of ["APPROVED", "REJECTED"]) {
    const lu = lireFileApprobationM7(directe([{ ...proposition, approval_status, approver: "admin-fictif" }]));
    expect(lu.ok && lu.value[0].approval_status).toBe(approval_status);
    expect(lu.ok && lu.value[0].approval_timestamp).toBe("");
  }
});

test("les champs de l'avis sont propres et obligatoires, avertissements intégraux", () => {
  for (const cle of ["id", "wct_id", "nature_travaux", "ville", "texte", "approval_status", "avertissements", "consentement"]) {
    const incomplet: Record<string, unknown> = { ...demande };
    delete incomplet[cle];
    expect(lireDemandesAvisM7(directe({ ...page, demandes: [incomplet] })).ok).toBe(false);
  }
  for (const changement of [{ nature_travaux: 42 }, { ville: [] }, { avertissements: ["alerte", 42] }, { texte: "" }]) {
    expect(lireDemandesAvisM7(directe({ ...page, demandes: [{ ...demande, ...changement }] })).ok).toBe(false);
  }
  const avertissements = ["Libellé de service inconnu (fictif)"];
  const lu = lireDemandesAvisM7(directe({ ...page, demandes: [{ ...demande, avertissements }] }));
  expect(lu.ok && lu.value.demandes[0].avertissements).toEqual(avertissements);
});

test("consentement hérité/accessor et tableau enrichi ne peuvent contourner les lectures propres", () => {
  const getter = jest.fn(() => "2026-09-15T15:05:00Z");
  for (const consentement of [Object.create(demande.consentement),
    Object.defineProperty({ ...demande.consentement }, "recueilli_le", { get: getter })]) {
    expect(lireDemandesAvisM7(directe({ ...page, demandes: [{ ...demande, consentement }] })).ok).toBe(false);
  }
  const enrichie = Object.assign([proposition], { supplement: "non JSON" });
  expect(lireFileApprobationM7(directe(enrichie)).ok).toBe(false);
  const cycle: Record<string, unknown> = { ok: true };
  cycle.resultat = cycle;
  expect(lireFileApprobationM7(cycle).ok).toBe(false);
  expect(getter).not.toHaveBeenCalled();
});
