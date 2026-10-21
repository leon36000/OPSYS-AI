import { lireSignauxM10, lireStatutDecisionM10, lireStatutRevisionM10, lireReferencesM10 } from "./contrat";
import { FIXTURES_M10 } from "./fixtures";
const f = FIXTURES_M10.reponses;
const copie = <T>(v: T): T => JSON.parse(JSON.stringify(v));

test("classes et tableaux sous-classés restent refusés malgré l'admission JSON inter-realm", () => {
  class Enveloppe { ok = true; resultat = f.signaux_ouverts.enveloppe.resultat; }
  expect(lireSignauxM10(new Enveloppe()).ok).toBe(false);
  class Signaux extends Array<unknown> { constructor(...items: unknown[]) { super(...items); } }
  const brut = { ...f.signaux_ouverts.enveloppe, resultat: { ...f.signaux_ouverts.enveloppe.resultat,
    signaux: new Signaux(...f.signaux_ouverts.enveloppe.resultat.signaux) } };
  expect(lireSignauxM10(brut).ok).toBe(false);
});

test("une classe renommée Object au prototype terminal ne devient pas du JSON natif", () => {
  const C = class Object { ok = true; resultat = f.signaux_ouverts.enveloppe.resultat; };
  Object.setPrototypeOf(C.prototype, null);
  expect(lireSignauxM10(new C()).ok).toBe(false);
});
test("une sous-classe renommée Array et reparentée ne devient pas un tableau JSON natif", () => {
  class C extends Array<unknown> { constructor(...v: unknown[]) { super(...v); } }
  const tableau = new C(...f.signaux_ouverts.enveloppe.resultat.signaux);
  Object.defineProperty(C, "name", { value: "Array" });
  Object.setPrototypeOf(C.prototype, Object.prototype);
  const brut = { ...f.signaux_ouverts.enveloppe, resultat: { ...f.signaux_ouverts.enveloppe.resultat,
    signaux: tableau } };
  expect(lireSignauxM10(brut).ok).toBe(false);
});

test("lectures natives DIRECT : null reste inconnu, omissions volume annoncées", () => {
  expect(lireStatutDecisionM10(f.decision_inconnue.enveloppe)).toEqual({ ok: true, value: { statut: null } });
  expect(lireStatutRevisionM10(f.revision_inconnue.enveloppe)).toEqual({ ok: true, value: { statut: null } });
  const r = lireSignauxM10(f.signaux_volume.enveloppe);
  expect(r.ok).toBe(true);
  if (r.ok) { expect(r.value.signaux).toHaveLength(7); expect(r.value.nb_omis).toBe(43); }
});

test("un compteur divergent et un signal ouvert traité ne créent pas de ligne partielle", () => {
  const divergent = copie(f.signaux_ouverts.enveloppe);
  const compteur = { ...divergent, resultat: { ...divergent.resultat, nb_total: 2 } };
  expect(lireSignauxM10(compteur).ok).toBe(false);
  const traite = { ...divergent, resultat: { ...divergent.resultat,
    signaux: [{ ...divergent.resultat.signaux[0], traite_par: "admin", traite_le: "2026-10-07T10:00:00Z", motif: "Motif valide" }] } };
  expect(lireSignauxM10(traite).ok).toBe(false);
});

test("le refus natif est conservé et un COUPLE à la place d’un DIRECT est illisible", () => {
  expect(lireSignauxM10(f.lecture_revoquee.enveloppe)).toEqual({ ok: false,
    code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "cette lecture exige une personne admin active confirmée en base" });
  expect(lireStatutDecisionM10({ ok: true, resultat: { accepte: true, resultat: { statut: "validee" } } }).ok).toBe(false);
  expect(lireReferencesM10({ ok: true, resultat: { decisions: [], revisions: [] } }).ok).toBe(false);
});

const page = f.catalogue_page_2.enveloppe.resultat.resultat;
const catalogue = (patch: Record<string, unknown> = {}) => ({ ok: true,
  resultat: { accepte: true, resultat: { ...page, ...patch } } });
const revisionNative = page.revisions[0];

test("catalogue COUPLE natif : deux pages courantes et hors-page explicite", () => {
  for (const nom of ["catalogue_page_1", "catalogue_page_2", "catalogue_hors_page"] as const) {
    const r = lireReferencesM10(f[nom].enveloppe);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.affichees).toBe(r.value.decisions.length + r.value.revisions.length);
  }
  const r = lireReferencesM10(f.catalogue_page_2.enveloppe);
  if (!r.ok) throw new Error(r.detail);
  expect(r.value.decalage).toBe(8);
  expect(r.value.revisions[0].revision_ligne_id).toBe(revisionNative.reference.ligne_id);
  expect(lireReferencesM10(f.catalogue_pagination_invalide.enveloppe)).toMatchObject({ ok: false, code: "REJ-CATALOGUE-PAGINATION-INVALIDE" });
  expect(lireReferencesM10(f.catalogue_schema_invalide.enveloppe)).toMatchObject({ ok: false, code: "arguments_invalides" });
});

test.each([
  { affichees: 9 }, { limite: 0 }, { limite: 9 }, { reste: 1 }, { suivant: 8 },
  { total: 15 }, { decalage: -1 }, { borne_caracteres: 6000 }, { taille_caracteres: 5401 },
  { taille_caracteres: 0 }, { domaine: "development" }, { raison: "texte libre" },
])("un catalogue incohérent est refusé en entier (%p)", patch => {
  expect(lireReferencesM10(catalogue(patch)).ok).toBe(false);
});

test("taille annoncée est bornée, sans prétendre recalculer le JSON Python après snapshot", () => {
  expect(lireReferencesM10(catalogue({ taille_caracteres: 1234 })).ok).toBe(true);
});

test.each([
  { revision_ligne_id: "a".repeat(64) },
  { reference: { ...revisionNative.reference, registre: "developpement" } },
  { reference: { ...revisionNative.reference, hash_tete: "a".repeat(64) } },
  { reference_b: revisionNative.reference_a },
  { reference_statut: revisionNative.reference_a },
  { reference_statut: revisionNative.reference, statut: "distincts_confirmes" },
  { reference: { ...revisionNative.reference, resume: "texte interdit" } },
  { signalee_le: "2026-02-30T09:00:00Z" }, { statut_le: null }, { statut: null },
])("les liens et dates d’une révision ne sont jamais devinés (%p)", patch => {
  expect(lireReferencesM10(catalogue({ revisions: [{ ...revisionNative, ...patch }] })).ok).toBe(false);
});

test("IDs décisions opaques : Unicode, jointure emoji et espaces préservés ; contrôles refusés", () => {
  const d = page.decisions[0];
  const lire = (decision_id: unknown) => lireReferencesM10(catalogue({ decisions: [{ ...d, decision_id }, ...page.decisions.slice(1)] }));
  for (const identifiant of ["  Décision 👨‍👩‍👧‍👦  ", "😀".repeat(256)]) {
    const r = lire(identifiant); expect(r.ok).toBe(true);
    if (r.ok) expect(r.value.decisions[0].decision_id).toBe(identifiant);
  }
  for (const identifiant of ["", "  ", "DEC\n1", "\ud800", "😀".repeat(257), null]) expect(lire(identifiant).ok).toBe(false);
});

test("doublons de références de décisions et signaux refusés", () => {
  expect(lireReferencesM10(catalogue({ decisions: [page.decisions[0], page.decisions[0], ...page.decisions.slice(2)] })).ok).toBe(false);
  const natif = f.signaux_ouverts.enveloppe.resultat;
  expect(lireSignauxM10({ ok: true, resultat: { ...natif, signaux: [...natif.signaux, ...natif.signaux], nb_total: 2, nb_ouverts: 2 } }).ok).toBe(false);
});

test.each(["validee", "remplacee", "annulee", "proposee", "indetermine"])("statut décision natif %s", statut => {
  expect(lireStatutDecisionM10({ ok: true, resultat: { statut } })).toEqual({ ok: true, value: { statut } });
});
test.each(["en_attente", "distincts_confirmes", "obsolete_marquee", "indetermine"])("statut révision natif %s", statut => {
  expect(lireStatutRevisionM10({ ok: true, resultat: { statut } })).toEqual({ ok: true, value: { statut } });
});
test.each([undefined, false, 1, ["validee"], "inconnu"])("statut invalide %p ne devient pas null", statut => {
  expect(lireStatutDecisionM10({ ok: true, resultat: { statut } }).ok).toBe(false);
  expect(lireStatutRevisionM10({ ok: true, resultat: { statut } }).ok).toBe(false);
});

test("signaux traités, clos par règle, affaire manquante et compteurs globaux cohérents", () => {
  const natif = f.signaux_volume.enveloppe.resultat.signaux[0];
  for (const etat of ["pris_en_compte", "clos"] as const) {
    const resultat = { signaux: [{ ...natif, etat, affaire_id: null, traite_par: "regle:variance_reevaluee" }],
      nb_total: 1, nb_omis: 0, nb_ouverts: 0, nb_pris_en_compte: etat === "pris_en_compte" ? 1 : 0, nb_clos: etat === "clos" ? 1 : 0 };
    expect(lireSignauxM10({ ok: true, resultat }).ok).toBe(true);
    expect(lireSignauxM10({ ok: true, resultat: { ...resultat, signaux: [{ ...resultat.signaux[0], traite_le: null }] } }).ok).toBe(false);
  }
  const ouvert = f.signaux_ouverts.enveloppe.resultat;
  expect(lireSignauxM10({ ok: true, resultat: { ...ouvert, nb_ouverts: 0, nb_clos: 1 } }).ok).toBe(false);
});

test("snapshot profond sans exécuter getter, héritage, sparse, cycle ou entier unsafe", () => {
  const getter = jest.fn(() => f.signaux_ouverts.enveloppe.resultat);
  const brut = Object.defineProperty({ ok: true }, "resultat", { enumerable: true, get: getter });
  expect(lireSignauxM10(brut).ok).toBe(false); expect(getter).not.toHaveBeenCalled();
  const sparse = new Array(1);
  const natif = f.signaux_ouverts.enveloppe.resultat;
  for (const invalide of [Object.create(f.signaux_ouverts.enveloppe),
    { ok: true, resultat: { ...natif, signaux: sparse } },
    { ok: true, resultat: { ...natif, nb_total: Number.MAX_SAFE_INTEGER + 1 } }]) expect(lireSignauxM10(invalide).ok).toBe(false);
  const cycle: Record<string, unknown> = { ok: true }; cycle.resultat = cycle;
  expect(lireSignauxM10(cycle).ok).toBe(false);
  const source = copie(f.catalogue_page_2.enveloppe);
  const lu = lireReferencesM10(source);
  expect(lu.ok).toBe(true);
  Object.defineProperty(source.resultat.resultat.revisions[0].reference, "ligne_id", { value: "modifiée" });
  if (lu.ok) expect(lu.value.revisions[0].reference.ligne_id).toBe(revisionNative.reference.ligne_id);
});

test("troncature et champ sensible dans une décision ne produisent pas une référence partielle", () => {
  expect(lireReferencesM10({ ...catalogue(), tronque: true }).ok).toBe(false);
  expect(lireReferencesM10(catalogue({ decisions: [{ ...page.decisions[0], motif: "Texte privé" }, ...page.decisions.slice(1)] })).ok).toBe(false);
});

test("un verdict mal formé n’est pas converti en refus de serveur inventé", () => {
  for (const resultat of [{ accepte: false, verdict: { code: "REJ-EXPLICITE", detail: 42 } },
    { accepte: false, verdict: null }, { accepte: false, verdict: { code: "", detail: "message" } }]) {
    expect(lireSignauxM10({ ok: true, resultat })).toMatchObject({ ok: false, code: "reponse_illisible" });
    expect(lireReferencesM10({ ok: true, resultat })).toMatchObject({ ok: false, code: "reponse_illisible" });
  }
});

test("le motif traité garde les limites Unicode du backend, pas les unités UTF-16", () => {
  const natif = f.signaux_volume.enveloppe.resultat.signaux[0];
  const resultat = { signaux: [{ ...natif, motif: "😀".repeat(9) }], nb_total: 1,
    nb_omis: 0, nb_ouverts: 0, nb_pris_en_compte: 1, nb_clos: 0 };
  expect(lireSignauxM10({ ok: true, resultat }).ok).toBe(false);
});
