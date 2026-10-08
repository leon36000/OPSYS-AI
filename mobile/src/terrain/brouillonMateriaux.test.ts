import { lireBrouillonMateriaux, sauverBrouillonMateriaux } from "./brouillonMateriaux";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { creerLigneVide } from "../ecrans/materials";

const cible = { urlBase: "https://fictif.invalid", appareilId: "APPAREIL-FICTIF", personne: "PERSONNE-FICTIVE", interventionId: "INT-FICTIF" };
const draft = () => ({ wctId: "WCT-FICTIF", chantierId: "CHANTIER-M3-FICTIF", sourcePrevu: null, positionsImportees: [], intentionId: null,
  lignes: [{ ...creerLigneVide("LIGNE-FICTIVE"), materiauId: "SKU-FICTIF", quantiteTexte: "12.", unite: "pi" }] });
test('reprise depuis le même dépôt conserve la saisie inachevée sans quantité inventée', async () => {
  const depot = new DepotCleValeurMemoire(); await sauverBrouillonMateriaux(depot, cible, draft());
  const reprise = await lireBrouillonMateriaux(depot, cible);
  expect(reprise).toEqual({ genre: "present", valeur: draft() });
  expect(depot.cles()).toHaveLength(1);
});
test.each(['urlBase', 'appareilId', 'personne', 'interventionId'] as const)('%s différent ne relit pas le brouillon', async champ => {
  const depot = new DepotCleValeurMemoire(); await sauverBrouillonMateriaux(depot, cible, draft());
  expect(await lireBrouillonMateriaux(depot, { ...cible, [champ]: "AUTRE-FICTIF" })).toEqual({ genre: "absent" });
  expect(await lireBrouillonMateriaux(depot, cible)).toEqual({ genre: "present", valeur: draft() });
});
test('écritures sérialisées : un ancien write lent ne remplace pas la nouvelle saisie', async () => {
  const depot = new DepotCleValeurMemoire(), ecrire = depot.ecrire.bind(depot); let terminer!: () => void;
  let premier = true;
  depot.ecrire = async (cle, valeur) => { if (premier) { premier = false; await new Promise<void>(resolve => { terminer = resolve; }); } await ecrire(cle, valeur); };
  const a = sauverBrouillonMateriaux(depot, cible, draft()); await Promise.resolve(); await Promise.resolve();
  const derniere = { ...draft(), lignes: [{ ...draft().lignes[0], quantiteTexte: "15,25" }] };
  const b = sauverBrouillonMateriaux(depot, cible, derniere); terminer(); await Promise.all([a, b]);
  expect(await lireBrouillonMateriaux(depot, cible)).toEqual({ genre: "present", valeur: derniere });
});
test('un write échoué est visible, la suite peut préserver le dernier brouillon', async () => {
  const depot = new DepotCleValeurMemoire(), original = depot.ecrire.bind(depot); let premier = true;
  depot.ecrire = async (cle, valeur) => { if (premier) { premier = false; throw new Error("FICTIF DISQUE"); } await original(cle, valeur); };
  await expect(sauverBrouillonMateriaux(depot, cible, draft())).rejects.toThrow();
  await sauverBrouillonMateriaux(depot, cible, draft()); expect((await lireBrouillonMateriaux(depot, cible)).genre).toBe('present');
});
test('stockage malformé conservé et signalé, sans remplacement par vide', async () => {
  const depot = new DepotCleValeurMemoire(); await sauverBrouillonMateriaux(depot, cible, draft());
  const [cle] = depot.cles(); await depot.ecrire(cle, '{"FICTIF":');
  expect(await lireBrouillonMateriaux(depot, cible)).toEqual({ genre: 'illisible' }); expect(await depot.lire(cle)).toBe('{"FICTIF":');
});
test('jeton et contexte serveur ne sont jamais stockés dans le brouillon', async () => {
  const depot = new DepotCleValeurMemoire(); await sauverBrouillonMateriaux(depot, cible, draft());
  const valeur = await depot.lire(depot.cles()[0]); expect(valeur).not.toMatch(/jeton|source_configuration|hash_maillon|prix|cout/);
});
test("v2 conserve notes brutes/captures/UUID après réouverture sans stocker DTO courant",async()=>{
 const d=new DepotCleValeurMemoire(),valeur={...draft(),intentionId:"UUID-FICTIF",preuves:[{ligneId:"LIGNE-FICTIVE",note:"FICTIF note inachevée\n",captureIds:["CAPTURE-FICTIVE"]}]};
 await sauverBrouillonMateriaux(d,cible,valeur);const nouveau=new DepotCleValeurMemoire();for(const k of d.cles()){const raw=await d.lire(k);if(raw!==null){expect(JSON.parse(raw).version).toBe(2);await nouveau.ecrire(k,raw);}}
 expect(await lireBrouillonMateriaux(nouveau,cible)).toEqual({genre:"present",valeur});
});
