import { lireClient360 } from "../m2/client360";
import type { RapportVidange } from "../outbox/vidangeur";
import type { ResultatFiche } from "../vendeur/chargeurFiche";
import { composerFiche } from "../vendeur/fiche";
import { CLIENT_DE_LEAD_BRUT, SUGGESTION_BRUTE, client360Brut } from "../vendeur/donneesDeTest";
import { accuseNoteDepuisResume, issueNote, lignesContact, opportunitesDuClient, travauxDeOpportunite, vueFiche } from "./lead";

const client = lireClient360(client360Brut())!;

const RAPPORT_VIDE: RapportVidange = {
  envoyees: [],
  resultatsAcceptes: [],
  remisesEnAttente: [],
  echecsPermanents: [],
  bloquees: [],
  quarantaine: [],
  arret: null,
  ignoreeVerrouActif: false,
};

describe("vueFiche", () => {
  const fiche = composerFiche("lead-a-01", {
    suggestion: { genre: "accepte", valeur: SUGGESTION_BRUTE },
    clientDuLead: { genre: "accepte", valeur: CLIENT_DE_LEAD_BRUT },
    vue: { genre: "accepte", valeur: client360Brut() },
    misAJourLe: "2026-09-29T18:00:00.000Z",
  });

  test("sans appairage : dit tel quel", () => {
    expect(vueFiche(null)).toEqual({ genre: "sans_appairage" });
  });

  test("en ligne : la fiche, sans mention de cache", () => {
    expect(vueFiche({ source: "serveur", fiche })).toEqual({ genre: "fiche", fiche, cache: null });
  });

  test("cache : la fiche MARQUÉE comme cache, avec sa date et la raison", () => {
    const raison = { code: "erreur_reseau", detail: "Network request failed" };
    const resultat: ResultatFiche = { source: "cache", fiche, raisonHorsLigne: raison };
    expect(vueFiche(resultat)).toEqual({
      genre: "fiche",
      fiche,
      cache: { misAJourLe: "2026-09-29T18:00:00.000Z", raison },
    });
  });

  test("ni serveur ni cache : aucune, avec la raison", () => {
    const raison = { code: "erreur_reseau", detail: "Network request failed" };
    expect(vueFiche({ source: "aucune", raison })).toEqual({ genre: "aucune", raison });
  });
});

describe("Client 360 : contact et opportunités", () => {
  test("le contact tel que M2 l'a ingéré, une ligne par clé", () => {
    expect(lignesContact(client)).toEqual([
      { cle: "nom", valeur: "Cliente Fictive" },
      { cle: "courriel", valeur: "cliente@exemple-fictif.test" },
    ]);
  });

  test("un contact absent ou vide est absent (null), jamais des lignes inventées", () => {
    expect(lignesContact(lireClient360(client360Brut({ contact: null }))!)).toBeNull();
    expect(lignesContact(lireClient360(client360Brut({ contact: {} }))!)).toBeNull();
  });

  test("l'opportunité de CE lead, puis les autres du client", () => {
    const { courante, autres } = opportunitesDuClient(client, "lead-a-01");
    expect(courante?.leadId).toBe("lead-a-01");
    expect(autres.map((o) => o.leadId)).toEqual(["lead-a-02"]);
  });

  test("le Client 360 ne porte pas ce lead (jamais inventé) : courante nulle", () => {
    expect(opportunitesDuClient(client, "lead-inconnu").courante).toBeNull();
    expect(opportunitesDuClient(client, "lead-inconnu").autres).toHaveLength(2);
  });

  test("les travaux : le service d'un lead v2 ou le type de travaux d'un lead v1, jamais l'un déduit de l'autre", () => {
    const [v1, v2] = client.opportunites;
    expect(travauxDeOpportunite(v1)).toBe("renovation_totale");
    expect(travauxDeOpportunite(v2)).toBe("gouttieres");
    expect(travauxDeOpportunite({ ...v1, typeTravaux: null, service: null })).toBeNull();
  });
});

describe("issueNote — ce qui est arrivé à la note qu'on vient d'écrire", () => {
  const accuse = { leadId: "lead-a-01", ligneId: "abc", horodatage: "2026-09-29T14:03:22-04:00" };

  test("acceptée par le serveur : enregistrée, avec l'accusé", () => {
    const rapport = { ...RAPPORT_VIDE, envoyees: ["n1"], resultatsAcceptes: [{ id: "n1", resume: accuse }] };
    expect(issueNote(rapport, "n1")).toEqual({ genre: "enregistree", accuse });
  });

  test("refusée (lead d'un autre, clos) : le verdict du serveur, tel quel", () => {
    const verdict = { code: "REJ-LEAD-NON-ASSIGNE", detail: "lead inconnu" };
    const rapport = { ...RAPPORT_VIDE, echecsPermanents: [{ id: "n1", verdict }] };
    expect(issueNote(rapport, "n1")).toEqual({ genre: "refusee", verdict });
  });

  test("hors ligne (remise en attente) ou pas de vidange : en file", () => {
    expect(issueNote({ ...RAPPORT_VIDE, remisesEnAttente: ["n1"] }, "n1")).toEqual({ genre: "en_file" });
    expect(issueNote(null, "n1")).toEqual({ genre: "en_file" });
    expect(issueNote(RAPPORT_VIDE, "n1")).toEqual({ genre: "en_file" });
  });

  test("l'issue d'une AUTRE mutation n'est jamais lue pour celle-ci", () => {
    const rapport = {
      ...RAPPORT_VIDE,
      resultatsAcceptes: [{ id: "autre", resume: accuse }],
      echecsPermanents: [{ id: "autre-2", verdict: { code: "X", detail: "" } }],
    };
    expect(issueNote(rapport, "n1")).toEqual({ genre: "en_file" });
  });

  test("un accusé de forme inattendue n'est jamais présenté comme enregistré", () => {
    const rapport = { ...RAPPORT_VIDE, resultatsAcceptes: [{ id: "n1", resume: { leadId: "l" } }] };
    expect(issueNote(rapport, "n1")).toEqual({ genre: "en_file" });
    expect(accuseNoteDepuisResume(null)).toBeNull();
    expect(accuseNoteDepuisResume("ok")).toBeNull();
    expect(accuseNoteDepuisResume(accuse)).toEqual(accuse);
  });
});
