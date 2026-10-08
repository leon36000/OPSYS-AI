import { encoderBase64Standard } from "./base64";
import { decouperEnBlocs, TAILLE_BLOC_OCTETS } from "./decoupage";
import { preparerEnvoiFichier } from "./envoiOrchestrateur";
import { calculerEtatEnvoiFichier } from "./etatEnvoi";
import { evaluerPreparationCompletion } from "../ecrans/complete";
import type { ConfigurationEnvoiFichier } from "./envoiOrchestrateur";
import type { CandidatFichierM4 } from "./candidats";
import { DepotOutboxMemoire } from "../outbox/depot";
import type { DepotOutbox } from "../outbox/depot";
import type { FonctionDigestSha256 } from "./empreinte";

const HORLOGE = { maintenant: new Date("2026-09-28T18:32:00.000Z"), decalageMinutesUTC: -240 };
let compteur = 0;
const idDeterministe = () => `mut-${++compteur}`;

beforeEach(() => {
  compteur = 0;
});

/** Digest FACTICE : ne calcule jamais un vrai SHA-256, renvoie toujours le même octet — suffit
 * à tester la logique de comparaison (verifierEmpreinteFichier), pas l'algorithme lui-même (déjà
 * couvert par `empreinte.test.ts`/`verification.test.ts` contre l'oracle Node `crypto`). */
const digestFixe: FonctionDigestSha256 = async () => new Uint8Array(32).fill(0xab).buffer as ArrayBuffer;
const SHA_ATTENDU_PAR_DIGEST_FIXE = "ab".repeat(32);

const FICHIER_1600_OCTETS: CandidatFichierM4 = {
  mutationId: "photo-1",
  proprietaire: "jdupont",
  chantierId: "I1",
  uri: "file:///opsys-photos/I1/apres/a.jpg",
  sha256: SHA_ATTENDU_PAR_DIGEST_FIXE,
  tailleOctets: TAILLE_BLOC_OCTETS + 1600,
  typeMime: "image/jpeg",
};

function creerConfig(
  depot: DepotOutbox,
  octetsSurDisque: Uint8Array<ArrayBuffer>,
  overrides: Partial<ConfigurationEnvoiFichier> = {},
): ConfigurationEnvoiFichier {
  return {
    depot,
    lireOctets: jest.fn().mockResolvedValue(octetsSurDisque),
    digest: digestFixe,
    genererId: idDeterministe,
    horloge: HORLOGE,
    obtenirEtatServeur: jest.fn().mockResolvedValue({ existe:false,complet:false,blocsRecus:[],reference:null }),
    courante:()=>true, proprietaire:"jdupont",verifierCandidat:async()=>true,
    ...overrides,
  };
}

function octetsDeTaille(taille: number): Uint8Array<ArrayBuffer> {
  const octets = Uint8Array.from({ length: taille }, (_, i) => i % 256);
  if(taille>=3)octets.set([0xff,0xd8,0xff]); // magic fictive JPEG, pas décodage/photo authentique
  return octets;
}

describe("preparerEnvoiFichier — cas nominal", () => {
  test("découpe, encode et enfile un bloc par mutation, dans l'ordre, avec les bons args", async () => {
    const depot = new DepotOutboxMemoire();
    const octets = octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets);
    const config = creerConfig(depot, octets);

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    expect(resultat).toEqual({ ok: true, blocsEnfiles: 2, pret:false });

    const lignes = await depot.lister();
    expect(lignes).toHaveLength(2);
    expect(lignes.map((m) => m.type)).toEqual(["fichier_bloc", "fichier_bloc"]);
    expect(lignes.map((m) => m.statut)).toEqual(["en_attente", "en_attente"]);
    expect(lignes.map((m) => m.chantierId)).toEqual(["I1", "I1"]);
    expect(lignes.map((m) => m.proprietaire)).toEqual(["jdupont", "jdupont"]);

    const blocsAttendus = decouperEnBlocs(octets);
    expect(lignes[0].payload).toEqual({
      empreinte_sha256: SHA_ATTENDU_PAR_DIGEST_FIXE,
      taille_octets: FICHIER_1600_OCTETS.tailleOctets,
      type_mime: "image/jpeg",
      index_bloc: 0,
      nombre_blocs: 2,
      bloc_base64: encoderBase64Standard(blocsAttendus[0]),
    });
    expect(lignes[1].payload.index_bloc).toBe(1);
    expect(lignes[1].payload.bloc_base64).toBe(encoderBase64Standard(blocsAttendus[1]));

    // Chaque bloc porte sa PROPRE clé d'idempotence (son propre mutation.id), jamais partagée.
    expect(lignes[0].id).not.toBe(lignes[1].id);
  });

  test("idempotent : un second appel avec les mutations déjà en file n'enfile rien de plus", async () => {
    const depot = new DepotOutboxMemoire();
    const octets = octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets);
    const config = creerConfig(depot, octets);

    await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    const enFile = await depot.lister();

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, enFile);
    expect(resultat).toEqual({ ok: true, blocsEnfiles: 0, pret:false });
    expect(await depot.lister()).toHaveLength(2); // jamais dupliqué
  });

  test("legacy envoyé sans état live reste indisponible, pas de nouvelle clé", async () => {
    const depot = new DepotOutboxMemoire();
    const config = creerConfig(depot, octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets));

    await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    const enFile = await depot.lister();
    for (const m of enFile) {
      await depot.mettreAJour({ ...m, statut: "envoyee" });
    }
    const complet = await depot.lister();
    (config.lireOctets as jest.Mock).mockClear(); // ne compter que les appels de CE second essai

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, complet);
    expect(resultat).toEqual({ ok: false, pret:false, raison:"etat_indisponible" });
    expect(config.lireOctets).toHaveBeenCalledTimes(1); // statuts legacy ne dispensent jamais de relecture
  });
});

describe("preparerEnvoiFichier — reprise via m4_etat_fichier (mission item 1)", () => {
  test("ne réenfile que les blocs que le serveur n'a PAS déjà reçus", async () => {
    const depot = new DepotOutboxMemoire();
    const octets = octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets);
    const config = creerConfig(depot, octets, {
      obtenirEtatServeur: jest.fn().mockResolvedValue({ existe: true, complet: false, blocsRecus: [0], reference: null }),
    });

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    expect(resultat).toEqual({ ok: true, blocsEnfiles: 1, pret:false });
    const lignes = await depot.lister();
    expect(lignes).toHaveLength(1); // pas de nouvel UUID pour un reçu serveur seul
    expect(lignes.find((m) => m.type === "fichier_bloc")?.payload.index_bloc).toBe(1);
    let etat = await depot.lister();
    expect(calculerEtatEnvoiFichier(etat, "I1", SHA_ATTENDU_PAR_DIGEST_FIXE)).toMatchObject({ statut: "en_cours", blocsEnvoyes: 0, nombreBlocs: 2 });
    const blocManquant = etat.find((m) => m.type === "fichier_bloc")!;
    await depot.mettreAJour({ ...blocManquant, statut: "envoyee" }); // accusé valide après vidange
    etat = await depot.lister();
    expect(calculerEtatEnvoiFichier(etat, "I1", SHA_ATTENDU_PAR_DIGEST_FIXE)).toMatchObject({ statut: "en_cours", blocsEnvoyes: 0, nombreBlocs: 2 });
    expect(evaluerPreparationCompletion({
      checklistComplete: true, photosApresSha256: [SHA_ATTENDU_PAR_DIGEST_FIXE], signatureSha256: null,
      signatureRequise: false, notes: "", mutations: etat, chantierId: "I1",
    })).toMatchObject({ pret: false });
  });

  test("si le serveur a déjà tous les blocs, l'état durable devient complet sans nouvel envoi", async () => {
    const depot = new DepotOutboxMemoire();
    const config = creerConfig(depot, octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets), {
      obtenirEtatServeur: jest.fn().mockResolvedValue({ existe: true, complet: true, blocsRecus: [0, 1], reference: `fichier:sha256:${SHA_ATTENDU_PAR_DIGEST_FIXE}` }),
    });
    expect(await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, [])).toEqual({ ok: true, blocsEnfiles: 0, pret:true });
    expect(await depot.lister()).toEqual([]); // disponibilité live, aucun UUID/permission en cache
  });

  test("redémarrage après insertion partielle enfile uniquement les indices absents", async () => {
    const base = new DepotOutboxMemoire();
    let appels = 0;
    const depot = { ...base, async inserer(m: Parameters<typeof base.inserer>[0]) {
      appels += 1;
      if (appels === 2) throw new Error("disk full");
      return base.inserer(m);
    }, lister: () => base.lister(), obtenir: (id: string) => base.obtenir(id), mettreAJour: (m: Parameters<typeof base.mettreAJour>[0]) => base.mettreAJour(m) };
    const config = creerConfig(depot, octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets));
    await expect(preparerEnvoiFichier(config, FICHIER_1600_OCTETS, [])).rejects.toThrow("disk full");
    const reprises = creerConfig(depot, octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets));
    expect(await preparerEnvoiFichier(reprises, FICHIER_1600_OCTETS, await base.lister())).toEqual({ ok: true, blocsEnfiles: 1, pret:false });
    expect((await base.lister()).map((m) => m.payload.index_bloc).sort()).toEqual([0, 1]);
  });

  test("préparations concurrentes du même fichier n'enfilent qu'une mutation par indice", async () => {
    const depot = new DepotOutboxMemoire();
    const config = creerConfig(depot, octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets));
    await Promise.all([
      preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []),
      preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []),
    ]);
    const lignes = await depot.lister();
    expect(lignes.map((m) => m.payload.index_bloc).sort()).toEqual([0, 1]);
  });

  test("échec de m4_etat_fichier (hors ligne) -> jamais bloquant, envoie tous les blocs", async () => {
    const depot = new DepotOutboxMemoire();
    const octets = octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets);
    const config = creerConfig(depot, octets, {
      obtenirEtatServeur: jest.fn().mockRejectedValue(new Error("hors ligne")),
    });

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    expect(resultat).toEqual({ ok: false, pret:false, raison:"etat_indisponible" });
    expect(await depot.lister()).toEqual([]);
  });
});

describe("preparerEnvoiFichier — refus fail-closed, jamais d'envoi", () => {
  test("empreinte relue différente de celle capturée -> refusé, aucun bloc enfilé", async () => {
    const depot = new DepotOutboxMemoire();
    const octetsDifferents = octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets);
    const config = creerConfig(depot, octetsDifferents, {
      digest: async () => new Uint8Array(32).fill(0xcd).buffer as ArrayBuffer, // hex "cd" != sha256 capturé "ab"
    });

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    expect(resultat).toEqual({ ok: false, pret:false, raison: "empreinte_discordante", sha256Capture: "ab".repeat(32), sha256Relu: "cd".repeat(32) });
    expect(await depot.lister()).toEqual([]);
  });

  test("type MIME non permis (extension non reconnue) -> refusé avant toute lecture disque", async () => {
    const depot = new DepotOutboxMemoire();
    const config = creerConfig(depot, octetsDeTaille(10));
    const fichier: CandidatFichierM4 = { ...FICHIER_1600_OCTETS, typeMime: null };

    const resultat = await preparerEnvoiFichier(config, fichier, []);
    expect(resultat).toEqual({ ok: false, pret:false, raison: "type_non_permis" });
    expect(config.lireOctets).not.toHaveBeenCalled();
    expect(await depot.lister()).toEqual([]);
  });

  test("taille hors bornes du contrat -> refusé avant toute lecture disque", async () => {
    const depot = new DepotOutboxMemoire();
    const config = creerConfig(depot, octetsDeTaille(10));
    const fichier: CandidatFichierM4 = { ...FICHIER_1600_OCTETS, tailleOctets: 0 };

    const resultat = await preparerEnvoiFichier(config, fichier, []);
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.raison).toBe("taille_invalide");
    }
    expect(config.lireOctets).not.toHaveBeenCalled();
  });

  test("un bloc déjà en échec permanent -> refusé, jamais une nouvelle tentative automatique", async () => {
    const depot = new DepotOutboxMemoire();
    const config = creerConfig(depot, octetsDeTaille(10));

    const mutationEnEchec = {
      id: "bloc-echec",
      sequence: 1,
      type: "fichier_bloc" as const,
      chantierId: "I1",
      payload: { empreinte_sha256: SHA_ATTENDU_PAR_DIGEST_FIXE, index_bloc: 0, nombre_blocs: 2, type_mime:"image/jpeg",taille_octets:FICHIER_1600_OCTETS.tailleOctets, bloc_base64: encoderBase64Standard(octetsDeTaille(262144)) },
      dependsOn: null,
      statut: "echec_permanent" as const,
      tentatives: 3,
      createdAtLocal: "2026-09-28T08:00:00-04:00",
      prochaineTentativeA: null,
      proprietaire: "jdupont",
    };

    await depot.inserer(mutationEnEchec);
    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, [mutationEnEchec]);
    expect(resultat).toEqual({ ok: false, pret:false, raison: "echec_permanent" });
    expect(config.lireOctets).not.toHaveBeenCalled();
  });
});

// B1 rouges : statuts legacy ne constituent pas une lecture live ni une permission.
describe("readiness live B1 (fictif)", () => {
  test("legacy envoyé est relu et absence serveur ne produit jamais prêt", async () => {
    const depot = new DepotOutboxMemoire(), config = creerConfig(depot, octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets));
    await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    for (const m of await depot.lister()) await depot.mettreAJour({ ...m, statut: "envoyee", resumeAccepte: null });
    const lire = jest.fn(async () => octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets));
    const serveur = jest.fn(async () => ({ existe: false, complet: false, blocsRecus: [], reference: null }));
    const c = { ...config, lireOctets: lire, obtenirEtatServeur: serveur };
    const r = await preparerEnvoiFichier(c, FICHIER_1600_OCTETS, await depot.lister());
    expect(lire).toHaveBeenCalledTimes(1); expect(serveur).toHaveBeenCalledTimes(1);
    expect(r).toMatchObject({ pret: false }); expect((await depot.lister()).map(m => m.id)).toEqual(["mut-1", "mut-2"]);
  });
  test("révocation pendant hash interdit lecture serveur et nouvelle mutation", async () => {
    const depot = new DepotOutboxMemoire(); let actuelle = true;
    const serveur = jest.fn(async () => ({ existe: false, complet: false, blocsRecus: [], reference: null }));
    const config = { ...creerConfig(depot, octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets)), courante: () => actuelle,
      digest: async () => { actuelle = false; return new Uint8Array(32).fill(0xab).buffer; }, obtenirEtatServeur: serveur };
    expect(await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, [])).toMatchObject({ ok: false, raison: "contexte_change", pret: false });
    expect(serveur).not.toHaveBeenCalled(); expect(await depot.lister()).toEqual([]);
  });
});

describe("B1 snapshots et captures indépendantes (fictif)",()=>{
  test("état callback getter/prototype fermé sans lecture du getter",async()=>{
    const depot=new DepotOutboxMemoire();let n=0;const etat={existe:true,complet:false,blocsRecus:[0],reference:null};
    Object.defineProperty(etat,"complet",{enumerable:true,get:()=>{n++;return false;}});
    const c=creerConfig(depot,octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets),{obtenirEtatServeur:async()=>etat});
    expect(await preparerEnvoiFichier(c,FICHIER_1600_OCTETS,[])).toMatchObject({pret:false,raison:"etat_indisponible"});expect(n).toBe(0);expect(await depot.lister()).toEqual([]);
  });
  test("seconde invocation ne partage pas le prêt d'une capture précédente",async()=>{
    const depot=new DepotOutboxMemoire();const c=creerConfig(depot,octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets),{
      obtenirEtatServeur:async()=>({existe:true,complet:true,blocsRecus:[0,1],reference:`fichier:sha256:${SHA_ATTENDU_PAR_DIGEST_FIXE}`})});
    const premier=preparerEnvoiFichier(c,FICHIER_1600_OCTETS,[]);
    const second=preparerEnvoiFichier({...c,courante:()=>false},FICHIER_1600_OCTETS,[]);
    expect(await premier).toMatchObject({pret:true});expect(await second).toMatchObject({pret:false,raison:"contexte_change"});
  });
});
