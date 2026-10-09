import captureNull from "./fixturesClassementNullSQL.json";
import fixtures from "./fixturesClassementVariancesSQL.json";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import type { MutationOutbox } from "../outbox/types";
const capture = (phase: string) => fixtures.captures.find(c => c.phase === phase)!;
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const api = () => require("./classementVariance") as typeof import("./classementVariance");
const horloge = { maintenant: new Date("2026-10-08T17:00:00Z"), decalageMinutesUTC: -240 };
const args = () => capture("classement_v1").request.arguments as unknown as import("./classementVariance").ArgumentsClassementVarianceM6;
function mutation(): MutationOutbox {
  return { ...api().creerMutationClassementVariance(args(), () => "9a276b43-3d42-4a55-a22f-03fe7a784a10", horloge, { appareilId: "APP-CLASSEMENT-FICTIF", urlBase: "https://fictif.invalid" }),
    proprietaire: "admin.contexte.fictif" };
}
test("le vrai descripteur classe la cause dans la file durable et ferme les refus HTTP incertains", () => {
  const d = DESCRIPTEURS_MUTATION.get("variance_cause_classification");
  expect(d).toBeDefined(); expect(d?.tool).toBe("m6_classer_cause_variance_appareil");
  expect(d?.serialiserParChantier).toBe(true); expect(d?.conserverRefusHttpIncertains).toBe(true);
});
test("les deux listes SQL réelles conservent source et dernier classement sans recalcul", () => {
  for (const phase of ["liste_initiale", "liste_classee"]) {
    const c = capture(phase);
    const lu = api().lireVariancesClassables(c.enveloppe, c.request.arguments);
    expect(lu.ok).toBe(true);
    if (lu.ok) expect(lu.value).toEqual((c.enveloppe.resultat as any).resultat);
  }
});
test("l'historique SQL garde les références v1/v2 et la page bornée courante", () => {
  for (const phase of ["historique_v1_v2", "historique_page1"]) {
    const c = capture(phase); const lu = api().lireHistoriqueClassements(c.enveloppe, c.request.arguments);
    expect(lu.ok).toBe(true);
    if (lu.ok) expect(lu.value).toEqual((c.enveloppe.resultat as any).resultat);
  }
});
test("ACK v1 et reprise v1 après v2 restent liés à leur propre intention", () => {
  const m = mutation();
  for (const rejoue of [false, true]) {
    const lu = api().interpreterClassementVariance({ ...capture("classement_v1").enveloppe, rejoue }, m);
    expect(lu.accepte).toBe(true);
    if (lu.accepte) expect(lu.resume.reference.index).toBe(0);
  }
  expect(api().interpreterClassementVariance(capture("classement_v2").enveloppe, m).accepte).toBe(false);
});
test.each(["selection", "cause", "motif", "reference_precedente", "auteur", "horodatage_appareil_declare", "references_pieces"])("ACK %s remplacé ne libère pas une intention", key => {
  const c = clone(capture("classement_v1").enveloppe) as any;
  const r = c.resultat.resultat;
  if (key === "selection") r.selection.position_ligne++;
  else if (key === "cause") r.cause = "breakage";
  else if (key === "motif") r.motif = "Autre motif fictif";
  else if (key === "reference_precedente") r.reference_precedente = r.reference;
  else if (key === "auteur") r.auteur.personne = "autre.admin.fictif";
  else if (key === "horodatage_appareil_declare") r.horodatage_appareil_declare = "2026-10-08T17:00:01+00:00";
  else r.references_pieces = [capture("liste_initiale").enveloppe.resultat.resultat!.lignes![0].pieces_disponibles_a_selectionner[0]];
  expect(api().interpreterClassementVariance(c, mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test("registre ACK faux et reçu local non lié restent inconnus", () => {
  const c = clone(capture("classement_v1").enveloppe) as any; c.resultat.registre.taille = 9;
  expect(api().interpreterClassementVariance(c, mutation()).accepte).toBe(false);
  const lu = api().interpreterClassementVariance(capture("classement_v1").enveloppe, mutation());
  expect(lu.accepte).toBe(true);
  if (lu.accepte) {
    const m = { ...mutation(), statut: "envoyee" as const, resumeAccepte: lu.resume };
    expect(api().validerRecuClassementVariance(m)).toBe(true);
    expect(api().validerRecuClassementVariance({ ...m, payload: { ...m.payload, cause: "breakage" } })).toBe(false);
  }
});
test.each(["IDENTITE-INVALIDE", "SOURCE-INCOHERENTE", "SORTIE-TROP-VOLUMINEUSE"])("refus préclaim %s garde l'issue inconnue", suffix => {
  expect(api().interpreterClassementVariance({ ok: false, erreur: `REJ-M6-CLASSEMENT-${suffix}`, details: "FICTIF" }, mutation()))
    .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test("le refus frais de révision périmée reste définitif", () => {
  expect(api().interpreterClassementVariance(capture("revision_perimee").enveloppe, mutation()))
    .toMatchObject({ accepte: false, verdict: { code: "REJ-M6-CLASSEMENT-REVISION-PERIMEE" } });
});
test.each(["autre_objet", "page_sans_progres", "position_page", "champ_prix"])("liste incohérente %s fermée en entier", kind => {
  const c = clone(capture("liste_initiale")) as any; const r = c.enveloppe.resultat.resultat;
  if (kind === "autre_objet") r.lignes[0].selection.wct_id = "AUTRE-WCT-FICTIF";
  else if (kind === "page_sans_progres") { r.lignes = []; r.pagination.affichees = 0; r.pagination.decalage_suivant = 0; }
  else if (kind === "position_page") r.lignes[0].selection.position_ligne = -1;
  else r.lignes[0].source_ligne.prix = "10.00";
  expect(api().lireVariancesClassables(c.enveloppe, c.request.arguments).ok).toBe(false);
});
test("getter jamais exécuté et cause/motif laissés intacts sans choix automatique", () => {
  const getter = jest.fn(); const v = Object.defineProperty({}, "ok", { get: getter, enumerable: true });
  expect(api().lireVariancesClassables(v, capture("liste_initiale").request.arguments).ok).toBe(false); expect(getter).not.toHaveBeenCalled();
  expect(() => api().creerMutationClassementVariance({ ...args(), cause: "" } as any, () => "UUID-FICTIF", horloge, { appareilId: "APP-CLASSEMENT-FICTIF", urlBase: "https://fictif.invalid" })).toThrow();
  const m = mutation(); expect(api().argumentsRpcClassementVariance(m)).toEqual(args());
  expect(m.payload.motif).toBe(args().motif); expect(m.statut).toBe("en_attente");
});
test("un ACK d'un autre appareil ne confirme pas l'intention créée pour cet appareil", () => {
  const c = clone(capture("classement_v1").enveloppe) as any;
  c.resultat.resultat.appareil_id = "AUTRE-APPAREIL-FICTIF";
  expect(api().interpreterClassementVariance(c, mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});

test("le vrai NON_PREVU lié à une PERTE garde son ratio inconnu, sans zéro inventé", () => {
  const lu = api().lireVariancesClassables(captureNull.response, captureNull.request.arguments);
  expect(lu.ok).toBe(true);
  if (lu.ok) {
    expect(lu.value.lignes[0].source_ligne.ecart_pourcentage).toBeNull();
    expect(lu.value.lignes[0].source_ligne.quantite_prevue).toBe("0.0");
    expect(lu.value.lignes[0].source_ligne.unite).toBeNull();
  }
});
