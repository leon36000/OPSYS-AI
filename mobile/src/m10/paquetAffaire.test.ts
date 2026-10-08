import { construireArgumentsPaquetAffaire, estAffairePaquetM10Valide, lirePaquetAffaire, COUCHES_PAQUET_AFFAIRE } from "./paquetAffaire";
import fixture from "./fixturesPaquetAffaire.json";
const exemples = fixture.reponses;
const args = exemples.signal_ouvert.arguments;
const copie = () => JSON.parse(JSON.stringify(exemples.signal_ouvert.enveloppe));
const lire = (v: unknown) => lirePaquetAffaire(v, args.affaire_id, args.horodatage);
const illisible = { ok: false, code: "reponse_illisible" };

test("fixtures fictives produites par les modules canoniques en RAM, jamais HTTP inventé", () => {
  expect(fixture.fictif).toBe(true);
  expect(fixture.provenance.sources_sha256).toHaveProperty(["departments/m10-memoire/src/m10_memoire/paquets.py"]);
});
test.each(Object.entries(exemples))("ouvre le DIRECT natif pur %s sans reconstruire ses faits", (_, e) => {
  const r = lirePaquetAffaire(e.enveloppe, e.arguments.affaire_id, e.arguments.horodatage);
  expect(r).toEqual({ ok: true, value: e.enveloppe.resultat });
  if (r.ok) expect(r.value.couches.map(c => c.nom)).toEqual(COUCHES_PAQUET_AFFAIRE);
});
test("même devis envoyé et accepté : provenance distincte, identifiant commun légal", () => {
  const faits = exemples.devis_meme_identifiant.enveloppe.resultat.couches[2].faits;
  expect(faits.filter(f => f.identifiant === "DEVIS-FICTIF").map(f => f.source).sort()).toEqual(["m3.devis_accepte", "m3.devis_envoye"]);
});
test("confidentialité retenue ne devient pas une absence d'origine", () => {
  const p = exemples.opportunite.enveloppe.resultat;
  expect(p.affaire).toEqual({ connue: true, origine_recue: true, origine: "m2.client_associe", verdict: null });
  expect(p.confidentialite.nb_retenus).toBeGreaterThan(0);
  expect(p.couches[2].faits).toEqual([]);
});
test("conserve premier fait dépassant la part1000 et omission11jours limitée à10 sans âge dérivé", () => {
  expect(exemples.premier_fait_hors_budget.enveloppe.resultat.couches[2].caracteres).toBeGreaterThan(1000);
  const c = exemples.omis_jours.enveloppe.resultat.consolidation;
  expect(c.nb_a_consolider).toBe(11); expect(c.a_consolider).toHaveLength(10);
});
test("arguments exactement liés à affaire et référence d'origine, opportunité canonique entière", () => {
  const id = "L".repeat(64) + "~opp~" + "W".repeat(128);
  expect(estAffairePaquetM10Valide(id)).toBe(true);
  expect(construireArgumentsPaquetAffaire(id, args.horodatage)).toEqual({ affaire_id: id, horodatage: args.horodatage });
  expect(lirePaquetAffaire(copie(), "AUTRE-FICTIF", args.horodatage)).toMatchObject(illisible);
  expect(lirePaquetAffaire(copie(), args.affaire_id, "2026-10-01T12:00:00Z")).toMatchObject(illisible);
});
test.each(["", "../LEAD", " LEAD", "LEAD\n", "a".repeat(65), "L~opp~", "L~opp~"+"w".repeat(129), "L~opp~W~opp~Z"])("affaire invalide %s", id => {
  expect(estAffairePaquetM10Valide(id)).toBe(false); expect(() => construireArgumentsPaquetAffaire(id, args.horodatage)).toThrow();
});
test.each(["2026-02-30T00:00:00Z", "2026-10-01", "2026-10-01T12:00:00", "2026-10-01T12:00:00+24:00", args.horodatage + "\n"])("référence invalide %s", h => {
  expect(() => construireArgumentsPaquetAffaire(args.affaire_id, h)).toThrow(); expect(lirePaquetAffaire(copie(), args.affaire_id, h)).toMatchObject(illisible);
});
test.each([
  ["six faits", (v: ReturnType<typeof copie>) => { const c=v.resultat.couches[2]; while(c.faits.length<6)c.faits.push({...c.faits[0],identifiant:"fictif-"+c.faits.length});c.nb_inclus=6;c.nb_total=6;c.nb_omis=0;c.tronque=false; }],
  ["ordre", (v: ReturnType<typeof copie>) => v.resultat.couches.reverse()],
  ["couche manquante", (v: ReturnType<typeof copie>) => v.resultat.couches.pop()],
  ["champ ajouté", (v: ReturnType<typeof copie>) => v.resultat.recommandation = "décider"],
  ["agent nommé", (v: ReturnType<typeof copie>) => v.resultat.confidentialite.agent = "m10-memoire"],
  ["règle inconnue", (v: ReturnType<typeof copie>) => v.resultat.confidentialite.regle = "v2"],
  ["compteur négatif", (v: ReturnType<typeof copie>) => v.resultat.signaux.nb_clos = -1],
  ["compteur non sûr", (v: ReturnType<typeof copie>) => v.resultat.confidentialite.nb_retenus = Number.MAX_SAFE_INTEGER + 1],
  ["compteur infini", (v: ReturnType<typeof copie>) => v.resultat.caracteres_utilises = Infinity],
  ["somme compteurs incohérente", (v: ReturnType<typeof copie>) => v.resultat.caracteres_utilises++],
  ["budget inconnu", (v: ReturnType<typeof copie>) => v.resultat.budget_caracteres = 4001],
  ["inclusion incohérente", (v: ReturnType<typeof copie>) => v.resultat.couches[2].nb_inclus++],
  ["omission incohérente", (v: ReturnType<typeof copie>) => v.resultat.couches[2].nb_omis++],
  ["bool faux", (v: ReturnType<typeof copie>) => v.resultat.couches[2].vide = true],
  ["troncature fausse", (v: ReturnType<typeof copie>) => v.resultat.couches[2].tronque = true],
  ["signal visible sans compteur", (v: ReturnType<typeof copie>) => v.resultat.signaux.nb_ouverts = 0],
  ["signal ouvert traité", (v: ReturnType<typeof copie>) => v.resultat.couches[3].faits[0].traite_par = "fictif"],
  ["signal statut inconnu", (v: ReturnType<typeof copie>) => v.resultat.couches[3].faits[0].etat = "inconnu"],
  ["signal clos sans traitement", (v: ReturnType<typeof copie>) => v.resultat.couches[3].faits[0].etat = "clos"],
  ["jours sans omission", (v: ReturnType<typeof copie>) => {v.resultat.consolidation={nb_a_consolider:1,a_consolider:[{affaire_id:args.affaire_id,jour:"2026-09-01"}]};}],
  ["origine contradictoire", (v: ReturnType<typeof copie>) => v.resultat.affaire.origine = "m2.client_associe"],
  ["verdict absent", (v: ReturnType<typeof copie>) => { v.resultat.affaire.origine_recue = false; v.resultat.affaire.origine = null; }],
  ["fait date newline", (v: ReturnType<typeof copie>) => v.resultat.couches[2].faits[0].horodatage += "\n"],
  ["fait date impossible", (v: ReturnType<typeof copie>) => v.resultat.couches[2].faits[0].horodatage = "2026-02-30T00:00:00Z"],
  ["résumé hors borne Unicode", (v: ReturnType<typeof copie>) => v.resultat.couches[2].faits[0].resume = "😀".repeat(201)],
  ["identifiant vide", (v: ReturnType<typeof copie>) => v.resultat.couches[2].faits[0].identifiant = ""],
  ["doublon même provenance", (v: ReturnType<typeof copie>) => { const c=v.resultat.couches[3]; c.faits.push(c.faits[0]); c.nb_total++;c.nb_inclus++; }],
])("ferme la corruption %s", (_, modifier) => { const v = copie(); modifier(v); expect(lire(v)).toMatchObject(illisible); });
test.each(["SENSITIVE", "CLIENT_PRIVATE", "FINANCIAL", "SECRET_REF", "LEGAL_LOCKED", "inconnu", null])("aucun fait confidentiel %s", c => {
  const v=copie();v.resultat.couches[2].faits[0].confidentialite=c; expect(lire(v)).toMatchObject(illisible);
});
test("jours de consolidation : affaire exacte, borne10 et calendrier sans supposition", () => {
  const e=exemples.omis_jours; const original=()=>JSON.parse(JSON.stringify(e.enveloppe));
  for(const modifier of [
    (v: ReturnType<typeof copie>)=>v.resultat.consolidation.a_consolider[0].affaire_id="autre",
    (v: ReturnType<typeof copie>)=>v.resultat.consolidation.a_consolider[0].jour="2026-02-30",
    (v: ReturnType<typeof copie>)=>v.resultat.consolidation.a_consolider.reverse(),
    (v: ReturnType<typeof copie>)=>v.resultat.consolidation.a_consolider.pop(),
    (v: ReturnType<typeof copie>)=>v.resultat.consolidation.a_consolider.push(v.resultat.consolidation.a_consolider[0]),
  ]) {const v=original();modifier(v);expect(lirePaquetAffaire(v,e.arguments.affaire_id,e.arguments.horodatage)).toMatchObject(illisible);}
});
test("refus exact prioritaire à la troncature, aucun succès partiel/couple", () => {
  const refus={ok:true,tronque:true,resultat:{accepte:false,verdict:{code:"REJ-IDENTITE-APPAREIL-INVALIDE",detail:"admin retiré fictif"}}};
  expect(lire(refus)).toEqual({ok:false,...refus.resultat.verdict});
  expect(lire({ok:false,erreur:"refus_metier",details:"refus fictif"})).toEqual({ok:false,code:"refus_metier",detail:"refus fictif"});
  expect(lire({ok:true,resultat:{accepte:false,verdict:{code:"X"}}})).toMatchObject(illisible);
  expect(lire({ok:false,erreur:"refus_metier",details:["fictif",{}]})).toMatchObject(illisible);
  expect(lire({ok:true,resultat:{accepte:true,resultat:copie().resultat}})).toMatchObject(illisible);
  expect(lire({...copie(),tronque:true})).toMatchObject({ok:false,code:"reponse_tronquee"});
});
test("snapshot entier refuse getter sans l'exécuter, prototype, cycle, symbole, sparse, nonJSON", () => {
  let appels=0;const v=copie();Object.defineProperty(v.resultat,"secret",{enumerable:true,get(){appels++;return "secret";}});
  expect(lire(v)).toMatchObject(illisible);expect(appels).toBe(0);
  const proto=copie();Object.setPrototypeOf(proto.resultat,{cache:true});expect(lire(proto)).toMatchObject(illisible);
  const cycle=copie();cycle.cycle=cycle;expect(lire(cycle)).toMatchObject(illisible);
  const sym=copie();sym[Symbol("secret")]=1;expect(lire(sym)).toMatchObject(illisible);
  const sparse=copie();delete sparse.resultat.couches[1];expect(lire(sparse)).toMatchObject(illisible);
  const nonJSON=copie();nonJSON.resultat.secret=undefined;expect(lire(nonJSON)).toMatchObject(illisible);
});
test("la lecture isole les faits originaux, aucun champ sensible ignoré même sur refus", () => {
  const v=copie();const r=lire(v);const resume=v.resultat.couches[2].faits[0].resume;v.resultat.couches[2].faits[0].resume="modifié";
  expect(r.ok&&r.value.couches[2].faits[0].resume).toBe(resume);
  const refus={ok:true,resultat:{accepte:false,verdict:{code:"X",detail:"fictif"}},extra:NaN};expect(lire(refus)).toMatchObject(illisible);
});
test("inconnue reste inconnue même avec règle globale ; signal clos conserve son traitement natif", () => {
  const p=exemples.inconnue_regle_globale.enveloppe.resultat;
  expect(p.affaire).toEqual({connue:false,origine_recue:false,origine:null,verdict:"AMONT-AFFAIRE-INCONNUE"});
  expect(p.couches[0].faits.length).toBeGreaterThan(0);
  const s=exemples.signal_clos.enveloppe.resultat.couches[3].faits[0];
  expect(s).toMatchObject({etat:"clos",traite_par:"amina.admin"});
  expect(exemples.signal_clos.enveloppe.resultat.signaux.nb_clos).toBe(1);
});
