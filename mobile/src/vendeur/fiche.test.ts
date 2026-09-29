import { composerFiche, estFicheBruteValide, historiqueDuLead } from "./fiche";
import type { FicheBrute, LectureBrute } from "./fiche";
import { lireClient360 } from "../m2/client360";
import { CLIENT_DE_LEAD_BRUT, SUGGESTION_BRUTE, client360Brut } from "./donneesDeTest";

const accepte = (valeur: unknown): LectureBrute => ({ genre: "accepte", valeur });
const refuse = (code: string, detail = ""): LectureBrute => ({ genre: "refuse", verdict: { code, detail } });
const T = "2026-09-29T18:00:00.000Z";

function brute(surcharge: Partial<FicheBrute> = {}): FicheBrute {
  return {
    suggestion: accepte(SUGGESTION_BRUTE),
    clientDuLead: accepte(CLIENT_DE_LEAD_BRUT),
    vue: accepte(client360Brut()),
    misAJourLe: T,
    ...surcharge,
  };
}

describe("composerFiche", () => {
  test("suggestion avec sa règle et Client 360 du client du lead, date de lecture portée", () => {
    const fiche = composerFiche("lead-a-01", brute());
    expect(fiche.leadId).toBe("lead-a-01");
    expect(fiche.misAJourLe).toBe(T);
    expect(fiche.suggestion).toMatchObject({ genre: "lue", valeur: { regle: "transmettre_m3", suggestion: "Transmettre le dossier à M3 pour estimation." } });
    expect(fiche.client).toMatchObject({ genre: "lue", valeur: { clientId: "a2f9b5d094369843521d099715b97ef817491c0e2309406bd46d75c41301a346" } });
  });

  test("le refus du serveur sur la suggestion (lead clos) n'empêche pas de lire le client", () => {
    const fiche = composerFiche("lead-a-01", brute({ suggestion: refuse("REJ-CONVERSATION-CLOSE", "lead clos") }));
    expect(fiche.suggestion).toEqual({ genre: "verdict", verdict: { code: "REJ-CONVERSATION-CLOSE", detail: "lead clos" } });
    expect(fiche.client.genre).toBe("lue");
  });

  test("le lead n'est pas à ce vendeur : le refus du serveur, tel quel, sur la suggestion ET le client", () => {
    const refus = refuse("REJ-LEAD-NON-ASSIGNE", "lead lead-b-01 non assigné");
    const fiche = composerFiche("lead-b-01", brute({ suggestion: refus, clientDuLead: refus, vue: null }));
    const attendu = { genre: "verdict", verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead lead-b-01 non assigné" } };
    expect(fiche.suggestion).toEqual(attendu);
    expect(fiche.client).toEqual(attendu);
  });

  test("le Client 360 refusé garde son verdict", () => {
    const fiche = composerFiche("lead-a-01", brute({ vue: refuse("REJ-LEAD-NON-ASSIGNE", "client introuvable") }));
    expect(fiche.client).toEqual({ genre: "verdict", verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "client introuvable" } });
  });

  test.each([
    ["la suggestion parle d'un autre lead", brute({ suggestion: accepte({ ...SUGGESTION_BRUTE, lead_id: "lead-b-09" }) }), "suggestion"],
    ["la suggestion est illisible", brute({ suggestion: accepte({ lead_id: "lead-a-01" }) }), "suggestion"],
    ["le client du lead parle d'un autre lead", brute({ clientDuLead: accepte({ ...CLIENT_DE_LEAD_BRUT, lead_id: "lead-b-09" }) }), "client"],
    ["le client du lead est illisible", brute({ clientDuLead: accepte({ lead_id: "lead-a-01" }) }), "client"],
    ["le Client 360 est celui d'un autre client", brute({ vue: accepte(client360Brut({ client_id: "b7c3e1a9d5f2468013579bdf02468ace13579bdf02468ace13579bdf02468ace" })) }), "client"],
    ["le Client 360 est illisible", brute({ vue: accepte({ client_id: "a2f9b5d094369843521d099715b97ef817491c0e2309406bd46d75c41301a346" }) }), "client"],
    ["le Client 360 manque alors que le client est connu", brute({ vue: null }), "client"],
  ] as const)("%s : reponse_illisible, jamais un mélange de fiches", (_nom, entree, partieAttendue) => {
    const fiche = composerFiche("lead-a-01", entree);
    expect(fiche[partieAttendue]).toEqual({ genre: "verdict", verdict: expect.objectContaining({ code: "reponse_illisible" }) });
  });
});

describe("estFicheBruteValide — le conteneur relu du cache", () => {
  test("la fiche brute que ce module écrit est valide, avec ou sans vue", () => {
    expect(estFicheBruteValide(JSON.parse(JSON.stringify(brute())))).toBe(true);
    expect(estFicheBruteValide(brute({ vue: null, clientDuLead: refuse("REJ-TRANSITION-ILLEGALE") }))).toBe(true);
  });

  test.each([
    ["null", null],
    ["sans date", { ...brute(), misAJourLe: undefined }],
    ["date illisible", { ...brute(), misAJourLe: "hier" }],
    ["suggestion d'un genre inconnu", { ...brute(), suggestion: { genre: "peut-etre", valeur: 1 } }],
    ["refus sans verdict lisible", { ...brute(), suggestion: { genre: "refuse", verdict: { code: 3 } } }],
    ["accepté sans donnée", { ...brute(), clientDuLead: { genre: "accepte" } }],
    ["vue absente (undefined au lieu de null)", (({ vue: _vue, ...reste }) => reste)(brute())],
  ])("refusé : %s", (_nom, valeur) => {
    expect(estFicheBruteValide(valeur)).toBe(false);
  });
});

describe("historiqueDuLead", () => {
  const client = lireClient360(client360Brut())!;

  test("les interactions de CE lead, la plus récente d'abord, l'écriture du système marquée", () => {
    const historique = historiqueDuLead(client, "lead-a-01");
    expect(historique.interactions.map((i) => [i.auteur, i.systeme])).toEqual([
      ["system:m3", true],
      ["vendeur.fictif", false],
    ]);
    expect(historique.interactions[0].resume).toBe("Relancer le client (fictif)");
  });

  test("les interactions des autres opportunités du client sont comptées, pas montrées", () => {
    expect(historiqueDuLead(client, "lead-a-01").autresOpportunites).toBe(1);
    expect(historiqueDuLead(client, "lead-a-02")).toMatchObject({ autresOpportunites: 2 });
    expect(historiqueDuLead(client, "lead-a-02").interactions.map((i) => i.resume)).toEqual(["Appel de suivi (fictif)"]);
  });

  test("l'ordre est celui des instants (décalages différents), pas celui du texte", () => {
    // « 2026-09-29T23:00-04:00 » (= 03:00 UTC le 30) est APRÈS « 2026-09-30T01:00+00:00 » (= 01:00 UTC le 30),
    // alors que le texte de la première précède celui de la seconde.
    const vue = lireClient360(
      client360Brut({
        interactions_recentes: [
          { lead_id: "L", auteur: "a", resume: "premier", horodatage: "2026-09-30T01:00:00+00:00" },
          { lead_id: "L", auteur: "a", resume: "second", horodatage: "2026-09-29T23:00:00-04:00" },
        ],
      }),
    )!;
    expect("2026-09-29T23:00:00-04:00" < "2026-09-30T01:00:00+00:00").toBe(true);
    expect(historiqueDuLead(vue, "L").interactions.map((i) => i.resume)).toEqual(["second", "premier"]);
  });

  test("sans aucune interaction : liste vide, dite vide par l'écran", () => {
    const vide = lireClient360(client360Brut({ interactions_recentes: [] }))!;
    expect(historiqueDuLead(vide, "lead-a-01")).toEqual({ interactions: [], autresOpportunites: 0 });
  });
});
