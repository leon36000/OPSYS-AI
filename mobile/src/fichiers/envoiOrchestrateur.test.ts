import { encoderBase64Standard } from "./base64";
import { decouperEnBlocs, TAILLE_BLOC_OCTETS } from "./decoupage";
import { preparerEnvoiFichier } from "./envoiOrchestrateur";
import type { ConfigurationEnvoiFichier } from "./envoiOrchestrateur";
import type { CandidatFichierM4 } from "./candidats";
import { DepotOutboxMemoire } from "../outbox/depot";
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
const digestFixe: FonctionDigestSha256 = async () => Uint8Array.from([0xab]).buffer as ArrayBuffer;
const SHA_ATTENDU_PAR_DIGEST_FIXE = "ab";

const FICHIER_1600_OCTETS: CandidatFichierM4 = {
  mutationId: "photo-1",
  chantierId: "I1",
  uri: "file:///opsys-photos/I1/apres/a.jpg",
  sha256: SHA_ATTENDU_PAR_DIGEST_FIXE,
  tailleOctets: TAILLE_BLOC_OCTETS + 1600,
  typeMime: "image/jpeg",
};

function creerConfig(
  depot: DepotOutboxMemoire,
  octetsSurDisque: Uint8Array<ArrayBuffer>,
  overrides: Partial<ConfigurationEnvoiFichier> = {},
): ConfigurationEnvoiFichier {
  return {
    depot,
    lireOctets: jest.fn().mockResolvedValue(octetsSurDisque),
    digest: digestFixe,
    genererId: idDeterministe,
    horloge: HORLOGE,
    obtenirEtatServeur: jest.fn().mockResolvedValue(null),
    ...overrides,
  };
}

function octetsDeTaille(taille: number): Uint8Array<ArrayBuffer> {
  return Uint8Array.from({ length: taille }, (_, i) => i % 256) as Uint8Array<ArrayBuffer>;
}

describe("preparerEnvoiFichier — cas nominal", () => {
  test("découpe, encode et enfile un bloc par mutation, dans l'ordre, avec les bons args", async () => {
    const depot = new DepotOutboxMemoire();
    const octets = octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets);
    const config = creerConfig(depot, octets);

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    expect(resultat).toEqual({ ok: true, blocsEnfiles: 2 });

    const lignes = await depot.lister();
    expect(lignes).toHaveLength(2);
    expect(lignes.map((m) => m.type)).toEqual(["fichier_bloc", "fichier_bloc"]);
    expect(lignes.map((m) => m.statut)).toEqual(["en_attente", "en_attente"]);
    expect(lignes.map((m) => m.chantierId)).toEqual(["I1", "I1"]);

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
    expect(resultat).toEqual({ ok: true, blocsEnfiles: 0 });
    expect(await depot.lister()).toHaveLength(2); // jamais dupliqué
  });

  test("déjà complet (tous les blocs envoyee) -> rien à refaire", async () => {
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
    expect(resultat).toEqual({ ok: true, blocsEnfiles: 0 });
    expect(config.lireOctets).not.toHaveBeenCalled(); // court-circuit : jamais de relecture disque inutile
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
    expect(resultat).toEqual({ ok: true, blocsEnfiles: 1 });
    const lignes = await depot.lister();
    expect(lignes).toHaveLength(1);
    expect(lignes[0].payload.index_bloc).toBe(1);
  });

  test("échec de m4_etat_fichier (hors ligne) -> jamais bloquant, envoie tous les blocs", async () => {
    const depot = new DepotOutboxMemoire();
    const octets = octetsDeTaille(FICHIER_1600_OCTETS.tailleOctets);
    const config = creerConfig(depot, octets, {
      obtenirEtatServeur: jest.fn().mockRejectedValue(new Error("hors ligne")),
    });

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    expect(resultat).toEqual({ ok: true, blocsEnfiles: 2 });
  });
});

describe("preparerEnvoiFichier — refus fail-closed, jamais d'envoi", () => {
  test("empreinte relue différente de celle capturée -> refusé, aucun bloc enfilé", async () => {
    const depot = new DepotOutboxMemoire();
    const octetsDifferents = octetsDeTaille(500);
    const config = creerConfig(depot, octetsDifferents, {
      digest: async () => Uint8Array.from([0xcd]).buffer as ArrayBuffer, // hex "cd" != sha256 capturé "ab"
    });

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, []);
    expect(resultat).toEqual({ ok: false, raison: "empreinte_discordante", sha256Capture: "ab", sha256Relu: "cd" });
    expect(await depot.lister()).toEqual([]);
  });

  test("type MIME non permis (extension non reconnue) -> refusé avant toute lecture disque", async () => {
    const depot = new DepotOutboxMemoire();
    const config = creerConfig(depot, octetsDeTaille(10));
    const fichier: CandidatFichierM4 = { ...FICHIER_1600_OCTETS, typeMime: null };

    const resultat = await preparerEnvoiFichier(config, fichier, []);
    expect(resultat).toEqual({ ok: false, raison: "type_non_permis" });
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
      payload: { empreinte_sha256: SHA_ATTENDU_PAR_DIGEST_FIXE, index_bloc: 0, nombre_blocs: 2, bloc_base64: "QQ==" },
      dependsOn: null,
      statut: "echec_permanent" as const,
      tentatives: 3,
      createdAtLocal: "2026-09-28T08:00:00-04:00",
      prochaineTentativeA: null,
      proprietaire: null,
    };

    const resultat = await preparerEnvoiFichier(config, FICHIER_1600_OCTETS, [mutationEnEchec]);
    expect(resultat).toEqual({ ok: false, raison: "echec_permanent" });
    expect(config.lireOctets).not.toHaveBeenCalled();
  });
});
