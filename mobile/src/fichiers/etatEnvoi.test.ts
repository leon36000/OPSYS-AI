import { encoderBase64Standard } from "./base64";
import { calculerEtatEnvoiFichier } from "./etatEnvoi";
import { construireReferenceFichier } from "./protocole";
import type { MutationOutbox, StatutMutation, TypeMutation } from "../outbox/types";

const SHA = "a".repeat(64);

function blocMutation(index: number, statut: StatutMutation, overrides: Partial<MutationOutbox> = {}): MutationOutbox {
  return {
    id: `bloc-${index}`,
    sequence: index + 1,
    type: "fichier_bloc" as TypeMutation,
    chantierId: "I1",
    payload: { empreinte_sha256: SHA, index_bloc: index, nombre_blocs: 3, taille_octets:524291,type_mime:"image/jpeg",
      bloc_base64:encoderBase64Standard(new Uint8Array(index===2 ? 3 : 262144)) },
    resumeAccepte:statut==="envoyee" ? {reference:construireReferenceFichier(SHA),complet:true,blocsRecus:[0,1,2]} : null,
    dependsOn: null,
    statut,
    tentatives: 0,
    createdAtLocal: "2026-09-28T08:00:00-04:00",
    prochaineTentativeA: null,
    proprietaire: "PERSONNE-FICTIVE",
    ...overrides,
  };
}

describe("calculerEtatEnvoiFichier", () => {
  test("des lignes dupliquées pour le même index ne prouvent jamais la complétude", () => {
    const etat = calculerEtatEnvoiFichier([blocMutation(0, "envoyee"), blocMutation(0, "envoyee")], "I1", SHA);
    expect(etat).toMatchObject({ statut: "en_cours", blocsEnvoyes: 1, nombreBlocs: 3 });
  });
  test("aucune mutation -> non_demarre", () => {
    expect(calculerEtatEnvoiFichier([], "I1", SHA)).toEqual({
      statut: "non_demarre",
      reference: null,
      blocsEnvoyes: 0,
      nombreBlocs: 0,
    });
  });

  test("blocs en file, pas tous envoyés -> en_cours", () => {
    const mutations = [blocMutation(0, "envoyee"), blocMutation(1, "en_attente"), blocMutation(2, "envoi")];
    expect(calculerEtatEnvoiFichier(mutations, "I1", SHA)).toEqual({
      statut: "en_cours",
      reference: null,
      blocsEnvoyes: 1,
      nombreBlocs: 3,
    });
  });

  test("tous les blocs envoyés -> complet, référence déterministe", () => {
    const mutations = [blocMutation(0, "envoyee"), blocMutation(1, "envoyee"), blocMutation(2, "envoyee")];
    expect(calculerEtatEnvoiFichier(mutations, "I1", SHA)).toEqual({
      statut: "complet",
      reference: construireReferenceFichier(SHA),
      blocsEnvoyes: 3,
      nombreBlocs: 3,
    });
  });

  test("un bloc en échec permanent -> echec_permanent MÊME si les autres sont envoyés", () => {
    const mutations = [blocMutation(0, "envoyee"), blocMutation(1, "echec_permanent"), blocMutation(2, "envoyee")];
    expect(calculerEtatEnvoiFichier(mutations, "I1", SHA)).toEqual({
      statut: "echec_permanent",
      reference: null,
      blocsEnvoyes: 2,
      nombreBlocs: 3,
    });
  });

  test("ignore les blocs d'un AUTRE chantier ou d'une AUTRE empreinte", () => {
    const mutations = [
      blocMutation(0, "envoyee"),
      { ...blocMutation(1, "envoyee"), chantierId: "I2" },
      { ...blocMutation(2, "envoyee"), payload: { empreinte_sha256: "sha-autre", index_bloc: 2, nombre_blocs: 3, bloc_base64: "x" } },
    ];
    expect(calculerEtatEnvoiFichier(mutations, "I1", SHA)).toEqual({
      statut: "en_cours",
      reference: null,
      blocsEnvoyes: 1,
      nombreBlocs: 3,
    });
  });

  test("ignore les mutations d'un autre type (ex. photo_upload brouillon)", () => {
    const mutations: MutationOutbox[] = [
      blocMutation(0, "envoyee"),
      {
        id: "photo-1",
        sequence: 1,
        type: "photo_upload",
        chantierId: "I1",
        payload: { empreinte_sha256: SHA },
        dependsOn: null,
        statut: "brouillon",
        tentatives: 0,
        createdAtLocal: "2026-09-28T08:00:00-04:00",
        prochaineTentativeA: null,
        proprietaire: null,
      },
    ];
    expect(calculerEtatEnvoiFichier(mutations, "I1", SHA).nombreBlocs).toBe(3);
  });
});

describe("B1 état local strict (fictif)", () => {
  test("legacy trois statuts envoyee sans reçu lié ne sont jamais complets", () => {
    expect(calculerEtatEnvoiFichier([0,1,2].map(i => blocMutation(i, "envoyee",{resumeAccepte:null})), "I1", SHA).statut).toBe("en_cours");
  });
  test("count discordant ou indice hors count ferme l'état", () => {
    const rows = [0,1,2].map(i => blocMutation(i, "envoyee"));
    expect(calculerEtatEnvoiFichier([...rows, blocMutation(3, "envoyee")], "I1", SHA).statut).toBe("en_cours");
    expect(calculerEtatEnvoiFichier([...rows, { ...blocMutation(2,"envoyee"), payload: { empreinte_sha256: SHA, index_bloc:2,nombre_blocs:2 } }], "I1", SHA).statut).toBe("en_cours");
  });
});
