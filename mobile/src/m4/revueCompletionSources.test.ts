import {
  construireArgumentsDossierRevueCompletion, construireArgumentsPropositionRevueCompletion,
  construireArgumentsDecisionRevueCompletion, empreinteArgumentsPropositionRevueCompletion,
  empreinteArgumentsDecisionRevueCompletion, lireDossierRevueCompletion,
  lireCreationPropositionRevueCompletion, lireDecisionRevueCompletion, figerPayloadDecisionRevueCompletion,
} from "./revueCompletionSources";
import { empreinteArgumentsClassementVariance } from "../m6/classementVariance";

// Fixtures RAM explicitement FICTIVES d'après contrat r2 / enveloppes r4-r5.
// Aucune réponse SQL, Cap, Gateway, autorité réelle ou maillon durable n'est revendiqué.
const hash = (c: string) => c.repeat(64);
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const P_HASH = "c04b85d577f9f561ae3695495f0b29f8d33efff9a2dcf0aa8b780e87eb1c5c67";
const D_HASH = "16890b312b6261c78167159f837894ede2253db036b135c272dc28783d600d3a";
const referenceVariance = () => ({ type: "m6.variance_chantier", evenement_id: "m6-variance-WCT-FICTIF-evaluee", empreinte_charge: hash("a") });
const selection = () => ({ wct_id: "WCT-FICTIF", reference_variance: referenceVariance(), position_ligne: 0, materiau_id: "MAT-FICTIF" });
const sources = () => ({
  wct_id: "WCT-FICTIF", chantier_id: "CHANTIER-M3-FICTIF", completion_ligne_id: hash("c"),
  transition_attendue_ligne_id: hash("d"), reference_variance: referenceVariance(),
  classements: [{ position_ligne: 0, materiau_id: "MAT-FICTIF", reference: null }],
});
const argsP = () => ({
  intervention_id: "INTERVENTION-FICTIVE", decision: "correction", horodatage: "2026-10-09T10:00:00.123456-04:00",
  motif: "Correction fictive.", sources: sources(),
});
const metaP = () => ({ personne: "ADMIN-FICTIF", appareil_id: "DEVICE-P-FICTIF", intention_uuid: "UUID-P-FICTIF" });
const metaD = () => ({
  personne: "OWNER-FICTIF", appareil_id: "DEVICE-D-FICTIF", intention_uuid: "UUID-D-FICTIF",
  horodatage_appareil_declare: "2026-10-09T10:01:00.123456-04:00",
});
const preuveP = () => ({
  demande_id: "APP-FICTIVE", departement: "m04-field-ops", outil: "m4_resoudre_revue_completion_sources",
  niveau: "N4", empreinte_arguments: P_HASH, proposant: { ...metaP(), role: "admin" },
});
const courant = () => ({
  version_schema: 1, lecture: "courante", intervention_id: "INTERVENTION-FICTIVE", statut: "completed_pending_review",
  wct: { wct_id: "WCT-FICTIF", intervention_id: "INTERVENTION-FICTIVE", chantier_id: "CHANTIER-M3-FICTIF" },
  reference_completion: { ligne_id: hash("c"), hash_maillon: hash("b") },
  reference_transition: { ligne_id: hash("d") },
  source_variance: { ...referenceVariance(), statut_variance: "evaluee", signal_critique: true,
    seuil_pourcentage: 15.5, horodatage_completion: "2026-10-09T09:00:00.000001-04:00" },
  lignes_critiques: [{ selection: selection(), source_ligne: { materiau: "Matériau FICTIF", unite: null,
    quantite_prevue: "2.00", quantite_reelle: "3", ecart_pourcentage: null, critique: true }, classement_courant: null }],
  sources: sources(), couverture: { positions_critiques: [0], positions_sans_classement: [0] },
  bornes: { limite_arguments_caracteres: 1500, limite_enveloppe_caracteres: 5400 },
});
const preuveD = () => ({
  version_schema: 2, demande_approbation_id: "APP-FICTIVE",
  association_decision: { ...metaD(), personne: undefined, empreinte_arguments: D_HASH },
  empreinte_arguments_proposition: P_HASH, intervention_id: "INTERVENTION-FICTIVE",
  wct_id: "WCT-FICTIF", chantier_id: "CHANTIER-M3-FICTIF", statut: "completed_pending_review", decision: "correction",
  ligne_id: hash("e"), tete_chaine: hash("f"), sources: sources(), approuve_par: "OWNER-FICTIF",
  role_approbateur: "nathan_owner", horodatage_decision_serveur: "2026-10-09T14:01:01.000001Z",
});
function resolution() {
  const p = preuveD();
  // association4, pas de personne locale/autorité en plus dans la preuve.
  return { ...p, association_decision: {
    appareil_id: p.association_decision.appareil_id, intention_uuid: p.association_decision.intention_uuid,
    empreinte_arguments: p.association_decision.empreinte_arguments,
    horodatage_appareil_declare: p.association_decision.horodatage_appareil_declare,
  } };
}
const historique = () => ({
  version_schema: 1, lecture: "historique",
  demande: { id: "APP-FICTIVE", cree_le: "2026-10-09T14:00:00.000001Z", departement: "m04-field-ops",
    outil: "m4_resoudre_revue_completion_sources", niveau: "N4", arguments: argsP(), statut: "executee",
    decide_par: "OWNER-FICTIF", decide_role: "nathan_owner", decide_le: "2026-10-09T14:01:01.000001Z", motif_decision: null },
  proposition: preuveP(), issue: { ok: true, accepte: true }, preuve_completion: resolution(),
  bornes: { limite_arguments_caracteres: 1500, limite_enveloppe_caracteres: 5400 },
});
const couple = (v: unknown) => ({ ok: true, resultat: { accepte: true, resultat: v } });
const payloadD = () => ({
  arguments_decision: { demande_id: "APP-FICTIVE", decision: "approuver" },
  outil_proposition: "m4_resoudre_revue_completion_sources",
  capture_proposition: { demande_id: "APP-FICTIVE", empreinte_arguments: P_HASH, sources: sources() },
  destination_origine: { personne: "OWNER-FICTIF", appareil_id: "DEVICE-D-FICTIF", url_base: "https://fictif.invalid" },
});
const ackP = () => ({
  ok: true, version_schema: 1, statut: "en_attente_approbation", demande_id: "APP-FICTIVE",
  details: "Création fictive N4.", preuve_proposition: preuveP(), rejoue: false,
});
const ackD = () => ({
  ok: true, resultat: { accepte: true, resultat: { demande_id: "APP-FICTIVE", decision: "approuver", statut: "executee",
    outil: "m4_resoudre_revue_completion_sources", departement: "m04-field-ops", niveau: "N4",
    decide_par: "OWNER-FICTIF", role: "nathan_owner", decide_le: "2026-10-09T14:01:01.000001Z",
    preuve_completion: resolution(), issue: { ok: true, accepte: true } } }, rejoue: false,
});

describe("dossier M4 sources — projection pure fictive", () => {
  test("courant garde ids distincts, nombres/textes/dates et hash de transition distinct du ligne_id", () => {
    const scenario = { fictif: true, dossier: courant() }, v = scenario.dossier;
    const r = lireDossierRevueCompletion(couple(v), { intervention_id: v.intervention_id, demande_id: null });
    expect(r).toEqual({ ok: true, value: v });
  });
  test("historique propre après décision ; aucune adoption de tête courante", () => {
    const v = historique();
    expect(lireDossierRevueCompletion(couple(v), { intervention_id: "INTERVENTION-FICTIVE", demande_id: "APP-FICTIVE" })).toEqual({ ok: true, value: v });
  });
  test("APP échec sans preuve est un fait historique, pas une négation D certaine", () => {
    const v = { ...historique(), demande: { ...historique().demande, statut: "echec" }, preuve_completion: null, issue: { ok: false } };
    expect(lireDossierRevueCompletion(couple(v), { intervention_id: "INTERVENTION-FICTIVE", demande_id: "APP-FICTIVE" }).ok).toBe(true);
  });
  test.each([{ ok: false }, { ok: true, accepte: false }])("preuve historique positive contradite par issue RAM reste illisible", issue => {
    // Contrefactuel RAM explicite : aucune capture producteur n'est modifiée.
    const v = { ...historique(), issue };
    expect(lireDossierRevueCompletion(couple(v), { intervention_id: "INTERVENTION-FICTIVE", demande_id: "APP-FICTIVE" }).ok).toBe(false);
  });
  test("zéro position critique conserve le signal global sans produire une décision", () => {
    const v = { ...courant(), lignes_critiques: [], sources: { ...sources(), classements: [] },
      couverture: { positions_critiques: [], positions_sans_classement: [] } };
    expect(lireDossierRevueCompletion(couple(v), { intervention_id: "INTERVENTION-FICTIVE", demande_id: null })).toEqual({ ok: true, value: v });
  });
  test("classement natif v1 sans intention rétroactive et v2 lié à ses vrais args5", () => {
    const c = { reference: { registre: "classements_variance", index: 3, hash_maillon: hash("9") },
      selection: selection(), cause: "waste", motif: "Cause FICTIVE.", reference_precedente: null,
      auteur: { personne: "ADMIN-FICTIF", role: "admin", source: "appareil" }, appareil_id: "DEVICE-P-FICTIF",
      classe_le: "2026-10-09T13:50:00Z", horodatage_appareil_declare: "2026-10-09T09:49:00-04:00", references_pieces: [] };
    for (const v2 of [false, true]) {
      const v = courant(), projection = v2 ? { ...c, version_schema: 2,
        intention: { appareil_id: c.appareil_id, intention_uuid: "CLS-FICTIF", empreinte_arguments:
          empreinteArgumentsClassementVariance({ selection: c.selection, cause: c.cause, motif: c.motif,
            classement_attendu: c.reference_precedente, references_pieces: c.references_pieces }) } } : c;
      const dto = { ...v, lignes_critiques: [{ ...v.lignes_critiques[0], classement_courant: projection }],
        sources: { ...v.sources, classements: [{ ...v.sources.classements[0], reference: c.reference }] },
        couverture: { positions_critiques: [0], positions_sans_classement: [] } };
      expect(lireDossierRevueCompletion(couple(dto), { intervention_id: v.intervention_id, demande_id: null })).toEqual({ ok: true, value: dto });
    }
  });
  test.each([
    ["extra", (v: ReturnType<typeof courant>) => ({ ...v, prix: 1 })],
    ["couverture omise", (v: ReturnType<typeof courant>) => ({ ...v, couverture: { positions_critiques: [], positions_sans_classement: [] } })],
    ["source étrangère", (v: ReturnType<typeof courant>) => ({ ...v, sources: { ...v.sources, wct_id: "AUTRE" } })],
    ["référence completion", (v: ReturnType<typeof courant>) => ({ ...v, reference_completion: { ...v.reference_completion, ligne_id: hash("8") } })],
    ["quantité nombre", (v: ReturnType<typeof courant>) => ({ ...v, lignes_critiques: [{ ...v.lignes_critiques[0], source_ligne: { ...v.lignes_critiques[0].source_ligne, quantite_prevue: 2 } }] })],
    ["nombre non fini", (v: ReturnType<typeof courant>) => ({ ...v, source_variance: { ...v.source_variance, seuil_pourcentage: Infinity } })],
    ["seuil entier inexact", (v: ReturnType<typeof courant>) => ({ ...v, source_variance: { ...v.source_variance, seuil_pourcentage: 2 ** 53 } })],
    ["statut inconnu", (v: ReturnType<typeof courant>) => ({ ...v, statut: "FUTUR-INCONNU" })],
    ["version bool", (v: ReturnType<typeof courant>) => ({ ...v, version_schema: true })],
  ])("%s est fermé sans projection partielle", (_n, changer) => {
    expect(lireDossierRevueCompletion(couple(changer(courant())), { intervention_id: "INTERVENTION-FICTIVE", demande_id: null }).ok).toBe(false);
  });
  test("enveloppe unique : aucun direct, rejoue T0 ou variante historique forcée", () => {
    expect(lireDossierRevueCompletion(courant(), { intervention_id: "INTERVENTION-FICTIVE", demande_id: null }).ok).toBe(false);
    expect(lireDossierRevueCompletion({ ...couple(courant()), rejoue: false }, { intervention_id: "INTERVENTION-FICTIVE", demande_id: null }).ok).toBe(false);
    expect(lireDossierRevueCompletion(couple(historique()), { intervention_id: "INTERVENTION-FICTIVE", demande_id: null }).ok).toBe(false);
  });
  test("getter/prototype/cycle restent fermés et aucun getter ne tourne", () => {
    let appels = 0; const v = courant();
    Object.defineProperty(v, "statut", { enumerable: true, get: () => { appels++; return "completed_pending_review"; } });
    expect(lireDossierRevueCompletion(couple(v), { intervention_id: "INTERVENTION-FICTIVE", demande_id: null }).ok).toBe(false);
    expect(appels).toBe(0);
    expect(lireDossierRevueCompletion(couple(Object.assign(Object.create({ prix: 1 }), courant())), { intervention_id: "INTERVENTION-FICTIVE", demande_id: null }).ok).toBe(false);
    const cycle: Record<string, unknown> = {}; cycle.boucle = cycle;
    expect(lireDossierRevueCompletion(couple(cycle), { intervention_id: "INTERVENTION-FICTIVE", demande_id: null }).ok).toBe(false);
  });
  test("capture duplicative et hash avec suffixe sont refusés", () => {
    const v = courant();
    expect(lireDossierRevueCompletion(couple({ ...v, sources: { ...v.sources, classements: [v.sources.classements[0], v.sources.classements[0]] } }),
      { intervention_id: v.intervention_id, demande_id: null }).ok).toBe(false);
    expect(lireDossierRevueCompletion(couple({ ...v, reference_completion: { ...v.reference_completion, hash_maillon: hash("b") + "\n" } }),
      { intervention_id: v.intervention_id, demande_id: null }).ok).toBe(false);
  });
  test("quantité grande reste texte ; limite annoncée couvre l'enveloppe entière", () => {
    const v = courant(), enorme = "1" + "0".repeat(200);
    v.lignes_critiques[0].source_ligne.quantite_prevue = enorme;
    expect(lireDossierRevueCompletion(couple(v), { intervention_id: v.intervention_id, demande_id: null })).toEqual({ ok: true, value: v });
    v.bornes.limite_enveloppe_caracteres = [...JSON.stringify(couple(v))].length - 1;
    expect(lireDossierRevueCompletion(couple(v), { intervention_id: v.intervention_id, demande_id: null }).ok).toBe(false);
    v.bornes.limite_enveloppe_caracteres = 5400; v.lignes_critiques[0].source_ligne.materiau = "M".repeat(5500);
    expect(lireDossierRevueCompletion(couple(v), { intervention_id: v.intervention_id, demande_id: null }).ok).toBe(false);
  });
  test("refus natif fermé reste refus ; une erreur ne devient pas dossier vide", () => {
    expect(lireDossierRevueCompletion({ ok: true, resultat: { accepte: false, verdict: { code: "REJ-FICTIF", detail: "Source fictive indisponible." } } },
      { intervention_id: "INTERVENTION-FICTIVE", demande_id: null })).toEqual({ ok: false, code: "REJ-FICTIF", detail: "Source fictive indisponible." });
    expect(lireDossierRevueCompletion({ ok: false, erreur: "budget_epuise" }, { intervention_id: "INTERVENTION-FICTIVE", demande_id: null }).ok).toBe(false);
  });
});

describe("builders et signatures exactes — encodeur Python RAM, pas SQL", () => {
  test("P cinq args fermés, D motif réellement facultatif et omis, T0 deux clés", () => {
    const p = argsP();
    expect(construireArgumentsPropositionRevueCompletion(p.intervention_id, p.decision, p.horodatage, p.motif, p.sources)).toEqual(p);
    expect(construireArgumentsDossierRevueCompletion("INTERVENTION-FICTIVE")).toEqual({ intervention_id: "INTERVENTION-FICTIVE", demande_id: null });
    expect(construireArgumentsDecisionRevueCompletion("APP-FICTIVE", "approuver")).toEqual({ demande_id: "APP-FICTIVE", decision: "approuver" });
    expect(construireArgumentsDecisionRevueCompletion("APP-FICTIVE", "approuver", "")).toEqual({ demande_id: "APP-FICTIVE", decision: "approuver", motif: "" });
  });
  test("vecteurs véritables encodeur B : Unicode/nonBMP/contrôles et omission motif D", () => {
    expect(empreinteArgumentsPropositionRevueCompletion(argsP())).toBe(P_HASH);
    expect(empreinteArgumentsPropositionRevueCompletion({ ...argsP(), motif: "Québec 😀\t\r\n\u2028" })).toBe("fbedf36d0aa763c5d86296312d14228c518a501eee1d6e80cfe110e3eb096651");
    expect(empreinteArgumentsDecisionRevueCompletion({ demande_id: "APP-FICTIVE", decision: "approuver" })).toBe(D_HASH);
    expect(empreinteArgumentsDecisionRevueCompletion({ demande_id: "APP-FICTIVE", decision: "approuver", motif: "" })).toBe("709594f8b1daa29baad622d54ddb870d016e3c72aa16ee6a0bf000007acf7f88");
  });
  test("snapshot avant attente, aucune metadata locale RPC, aucune réparation de date/id", () => {
    const p = argsP(), copie = construireArgumentsPropositionRevueCompletion(p.intervention_id, p.decision, p.horodatage, p.motif, p.sources);
    p.sources.wct_id = "MODIFIE"; expect(copie.sources.wct_id).toBe("WCT-FICTIF");
    expect(() => construireArgumentsDossierRevueCompletion("", null)).toThrow();
    expect(() => construireArgumentsDecisionRevueCompletion("x".repeat(33), "approuver")).toThrow();
    expect(() => construireArgumentsPropositionRevueCompletion("INTERVENTION-FICTIVE", "correction", "2026-10-09", "FICTIF", sources())).toThrow();
    expect(() => construireArgumentsPropositionRevueCompletion("INTERVENTION-FICTIVE", "verifiee", argsP().horodatage, "FICTIF", sources())).toThrow();
    expect(empreinteArgumentsPropositionRevueCompletion({ ...argsP(), personne: "FAUX" })).toBeNull();
    let appels = 0;
    const getter = Object.defineProperty(argsP(), "motif", { enumerable: true, get: () => { appels++; return "FICTIF"; } });
    expect(empreinteArgumentsPropositionRevueCompletion(getter)).toBeNull(); expect(appels).toBe(0);
  });
  test.each(["2026-02-30T10:00:00Z", "20261009T10:00:00Z", "2026-W41-5T10:00:00Z", "2026-10-09T10:00Z",
    "2026-10-09T10:00:00.1234567Z", "2026-10-09T10:00:00Z\n"])("date %s ne subit aucune réparation", hora => {
    expect(() => construireArgumentsPropositionRevueCompletion("INTERVENTION-FICTIVE", "correction", hora, "FICTIF", sources())).toThrow();
  });
  test("budget P1500 entier et motif500 codepoints, pas de troncature silencieuse", () => {
    expect(() => construireArgumentsPropositionRevueCompletion("INTERVENTION-FICTIVE", "correction", argsP().horodatage, "😀".repeat(501), sources())).toThrow();
    expect(() => construireArgumentsPropositionRevueCompletion("INTERVENTION-FICTIVE", "correction", argsP().horodatage, "😀".repeat(500), sources())).not.toThrow();
    const grand = { ...sources(), classements: Array.from({ length: 8 }, (_, n) => ({ position_ligne: n, materiau_id: "MAT-FICTIF-" + n, reference: null })) };
    expect(() => construireArgumentsPropositionRevueCompletion("INTERVENTION-FICTIVE", "correction", argsP().horodatage, "M".repeat(500), grand)).toThrow();
  });
});

describe("preuve P de création et preuve propre D", () => {
  test.each([false, true])("P création uniquement, rejoue=%s sans certification heure P", rejoue => {
    expect(lireCreationPropositionRevueCompletion({ ...ackP(), rejoue }, argsP(), metaP()).ok).toBe(true);
  });
  test.each(["intention_uuid", "appareil_id", "personne"] as const)("P étranger %s reste inconnu", key => {
    const p = ackP(); p.preuve_proposition.proposant[key] = "AUTRE-FICTIF";
    expect(lireCreationPropositionRevueCompletion(p, argsP(), metaP()).ok).toBe(false);
  });
  test("P extra heure refusée car non scellée par le journal", () => {
    expect(lireCreationPropositionRevueCompletion({ ...ackP(), horodatage_appareil: argsP().horodatage }, argsP(), metaP()).ok).toBe(false);
  });
  test("pas de max Meta globale inventée ; signature P et propriétaire exacts restent requis", () => {
    const p = ackP(), m = { personne: "P".repeat(300), appareil_id: "A".repeat(300), intention_uuid: "U".repeat(300) };
    p.preuve_proposition.proposant = { ...m, role: "admin" };
    expect(lireCreationPropositionRevueCompletion(p, argsP(), m).ok).toBe(true);
    p.preuve_proposition.empreinte_arguments = hash("0");
    expect(lireCreationPropositionRevueCompletion(p, argsP(), m).ok).toBe(false);
  });
  test("D success lié à pair/hash/hora et sources P ; heure serveur originale", () => {
    const dto = ackD(); expect(lireDecisionRevueCompletion(dto, payloadD(), metaD()).ok).toBe(true);
    dto.resultat.resultat.preuve_completion.association_decision.horodatage_appareil_declare = "2026-10-09T14:01:00.123456Z";
    expect(lireDecisionRevueCompletion(dto, payloadD(), metaD()).ok).toBe(true);
    dto.resultat.resultat.preuve_completion.association_decision.horodatage_appareil_declare = "2026-10-09T14:01:00.123457Z";
    expect(lireDecisionRevueCompletion(dto, payloadD(), metaD()).ok).toBe(false);
  });
  test("D propre rejoué, issue facultative ; issue contradictoire et champs supplémentaires fermés", () => {
    const v = ackD(), { issue: _issue, ...sansIssue } = v.resultat.resultat;
    const dto = { ...v, rejoue: true, resultat: { ...v.resultat, resultat: sansIssue } };
    expect(lireDecisionRevueCompletion(dto, payloadD(), metaD()).ok).toBe(true);
    expect(lireDecisionRevueCompletion({ ...v, resultat: { ...v.resultat, resultat: { ...v.resultat.resultat, issue: { ok: true, accepte: false } } } },
      payloadD(), metaD()).ok).toBe(false);
    expect(lireDecisionRevueCompletion({ ...v, acteur: "FAUX" }, payloadD(), metaD()).ok).toBe(false);
    expect(lireDecisionRevueCompletion({ ...v, resultat: { ...v.resultat, resultat: { ...v.resultat.resultat, preuve_completion: {
      ...resolution(), version_schema: true } } } }, payloadD(), metaD()).ok).toBe(false);
  });
  test.each(["intention_uuid", "appareil_id", "empreinte_arguments"] as const)("D preuve autre %s reste inconnue", key => {
    const dto = ackD(); dto.resultat.resultat.preuve_completion.association_decision[key] = key === "empreinte_arguments" ? hash("8") : "AUTRE-FICTIF";
    expect(lireDecisionRevueCompletion(dto, payloadD(), metaD()).ok).toBe(false);
  });
  test("D source/app/proofP/auteur/hora serveur altérés restent inconnus", () => {
    for (const modifier of [
      (v: ReturnType<typeof ackD>) => { v.resultat.resultat.preuve_completion.sources.completion_ligne_id = hash("7"); },
      (v: ReturnType<typeof ackD>) => { v.resultat.resultat.preuve_completion.empreinte_arguments_proposition = hash("7"); },
      (v: ReturnType<typeof ackD>) => { v.resultat.resultat.preuve_completion.approuve_par = "AUTRE"; },
      (v: ReturnType<typeof ackD>) => { v.resultat.resultat.decide_le = "2026-10-09T14:01:01.000002Z"; },
      (v: ReturnType<typeof ackD>) => { v.resultat.resultat.outil = "m4_resoudre_revue_completion"; },
    ]) { const v = ackD(); modifier(v); expect(lireDecisionRevueCompletion(v, payloadD(), metaD()).ok).toBe(false); }
  });
  test.each(["refusee", "echec", "executee"])("statut %s sans preuve n'est pas terminal pour cette intention D", statut => {
    const v = ackD(); const dto = { ...v, resultat: { ...v.resultat, resultat: { ...v.resultat.resultat, statut, preuve_completion: null } } };
    expect(lireDecisionRevueCompletion(dto, payloadD(), metaD())).toMatchObject({ ok: false, code: "accuse_invalide" });
  });
  test.each(["deja_decidee", "reserve_au_proprietaire", "mutation_conflit", "REJ-TRANSITION-ILLEGALE"])("refus %s sans preuveD reste UNKNOWN", code => {
    expect(lireDecisionRevueCompletion({ ok: true, resultat: { accepte: false, verdict: { code, detail: "Refus FICTIF." } }, rejoue: false },
      payloadD(), metaD())).toMatchObject({ ok: false, code: "accuse_invalide" });
  });
  test("payload local fermé copié ; destination privée jamais dans args D", () => {
    const p = payloadD(), copie = figerPayloadDecisionRevueCompletion(p); expect(copie).toEqual(p);
    p.destination_origine.personne = "AUTRE"; expect(copie?.destination_origine.personne).toBe("OWNER-FICTIF");
    expect(figerPayloadDecisionRevueCompletion({ ...payloadD(), prix: 1 })).toBeNull();
    expect(figerPayloadDecisionRevueCompletion({ ...payloadD(), arguments_decision: { ...payloadD().arguments_decision, appareil_id: "FAUX" } })).toBeNull();
    expect(lireDecisionRevueCompletion(ackD(), payloadD(), { ...metaD(), personne: "AUTRE" }).ok).toBe(false);
  });
});
