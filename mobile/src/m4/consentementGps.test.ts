import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import { soumettreMutation } from "../outbox/mutation";
import { selectionnerProchainesEnvoyables } from "../outbox/planification";
import type { MutationOutbox } from "../outbox/types";
import {
  ACTIONS_CONSENTEMENT_GPS,
  CHANTIER_ID_CONSENTEMENT_GPS,
  PREFIXE_REFERENCE_PREUVE_CONSENTEMENT,
  VERSION_POLITIQUE_GEOLOCALISATION,
  construireArgumentsDefinirConsentementGps,
  creerMutationConsentementGps,
  interpreterResultatDefinirConsentementGps,
} from "./consentementGps";

// Heure avancée de l'Est (Québec) : -4 h. L'horloge est INJECTÉE : aucune heure système n'est lue.
const HORLOGE = { maintenant: new Date("2026-09-28T14:32:10.000Z"), decalageMinutesUTC: -240 };

describe("construireArgumentsDefinirConsentementGps", () => {
  test("les cinq clés exactes du schéma serveur, rien d'autre (additionalProperties: false)", () => {
    const args = construireArgumentsDefinirConsentementGps("marc.fictif", "retire", "2026-09-28T10:32:10-04:00", "mut-1");

    expect(Object.keys(args).sort()).toEqual(["action", "horodatage", "preuve", "technicien_id", "version_politique"]);
    expect(args).toEqual({
      technicien_id: "marc.fictif",
      action: "retire",
      horodatage: "2026-09-28T10:32:10-04:00",
      version_politique: VERSION_POLITIQUE_GEOLOCALISATION,
      preuve: { fictif: true, reference: "app:consentement-gps:mut-1" },
    });
  });

  test("le retrait ET le don sont des actions du catalogue fermé du serveur (consentement.ACTIONS_CONSENTEMENT)", () => {
    expect(ACTIONS_CONSENTEMENT_GPS).toEqual(["donne", "retire"]);
    for (const action of ACTIONS_CONSENTEMENT_GPS) {
      expect(construireArgumentsDefinirConsentementGps("marc.fictif", action, "2026-09-28T10:32:10-04:00", "m").action).toBe(
        action,
      );
    }
  });

  test("l'identifiant de technicien est celui fourni, jamais un autre : le serveur le confronte à la personne authentifiée", () => {
    expect(construireArgumentsDefinirConsentementGps("lea.fictif", "retire", "h", "m").technicien_id).toBe("lea.fictif");
  });

  test("la preuve est la seule forme que le serveur accepte en mode ombre : fictive, avec une référence, jamais le document", () => {
    const { preuve } = construireArgumentsDefinirConsentementGps("marc.fictif", "retire", "h", "mut-9");

    expect(Object.keys(preuve).sort()).toEqual(["fictif", "reference"]);
    expect(preuve.fictif).toBe(true);
    expect(preuve.reference.startsWith(PREFIXE_REFERENCE_PREUVE_CONSENTEMENT)).toBe(true);
    expect(VERSION_POLITIQUE_GEOLOCALISATION).toBe("POLITIQUE-geolocalisation-proposition-P0-7");
  });
});

describe("creerMutationConsentementGps", () => {
  test("mutation gps_consent_change en brouillon, id = celui généré, preuve renvoyant à ce même id", () => {
    const mutation = creerMutationConsentementGps({ technicienId: "marc.fictif", action: "retire" }, () => "mut-42", HORLOGE);

    expect(mutation.id).toBe("mut-42");
    expect(mutation.type).toBe("gps_consent_change");
    expect(mutation.statut).toBe("brouillon");
    expect(mutation.chantierId).toBe(CHANTIER_ID_CONSENTEMENT_GPS);
    expect(mutation.dependsOn).toBeNull();
    expect(mutation.payload).toEqual({
      technicien_id: "marc.fictif",
      action: "retire",
      horodatage: "2026-09-28T10:32:10-04:00",
      version_politique: VERSION_POLITIQUE_GEOLOCALISATION,
      preuve: { fictif: true, reference: "app:consentement-gps:mut-42" },
    });
  });

  test("le générateur d'id n'est tiré QU'UNE fois : la preuve désigne exactement la mutation envoyée", () => {
    let appels = 0;
    const mutation = creerMutationConsentementGps(
      { technicienId: "marc.fictif", action: "donne" },
      () => {
        appels += 1;
        return `mut-${appels}`;
      },
      HORLOGE,
    );

    expect(appels).toBe(1);
    expect(mutation.id).toBe("mut-1");
    expect((mutation.payload.preuve as { reference: string }).reference).toBe("app:consentement-gps:mut-1");
  });

  test("l'heure de l'appareil porte son décalage, jamais Z/UTC (R12 §4) : affichage seulement, le serveur fait foi", () => {
    const mutation = creerMutationConsentementGps({ technicienId: "marc.fictif", action: "retire" }, () => "m", HORLOGE);

    expect(mutation.createdAtLocal).toBe("2026-09-28T10:32:10-04:00");
    expect(mutation.payload.horodatage).toBe(mutation.createdAtLocal);
    expect(String(mutation.payload.horodatage).endsWith("Z")).toBe(false);
  });

  test("le payload de deux mutations distinctes ne partage rien : chaque retrait a sa propre référence", () => {
    const a = creerMutationConsentementGps({ technicienId: "marc.fictif", action: "retire" }, () => "a", HORLOGE);
    const b = creerMutationConsentementGps({ technicienId: "marc.fictif", action: "retire" }, () => "b", HORLOGE);

    expect((a.payload.preuve as { reference: string }).reference).not.toBe((b.payload.preuve as { reference: string }).reference);
  });
});

describe("ordre dans la file sortante", () => {
  function enAttente(mutation: MutationOutbox, sequence: number): MutationOutbox {
    return { ...soumettreMutation(mutation), sequence };
  }

  test("un retrait part AVANT les pointages en attente, quel que soit l'identifiant d'intervention (hexadécimal)", () => {
    const pointage = (id: string, chantierId: string, sequence: number): MutationOutbox => ({
      id,
      sequence,
      type: "punch_in",
      chantierId,
      payload: {},
      dependsOn: null,
      statut: "en_attente",
      tentatives: 0,
      createdAtLocal: "2026-09-28T10:00:00-04:00",
      prochaineTentativeA: null,
    });
    // Pointages créés AVANT le retrait (séquences 1 à 4), dont des identifiants qui se trient avant « c ».
    const pointages = [
      pointage("p1", "00ab12", 1),
      pointage("p2", "0f9e00", 2),
      pointage("p3", "1c77aa", 3),
      pointage("p4", "ffee01", 4),
    ];
    const retrait = enAttente(
      creerMutationConsentementGps({ technicienId: "marc.fictif", action: "retire" }, () => "retrait", HORLOGE),
      5,
    );

    const ordre = selectionnerProchainesEnvoyables([...pointages, retrait], new Date("2026-09-28T15:00:00.000Z")).map(
      (m) => m.id,
    );

    expect(ordre[0]).toBe("retrait");
    expect(ordre.slice(1)).toEqual(["p1", "p2", "p3", "p4"]);
  });
});

describe("descripteur de la file sortante", () => {
  test("gps_consent_change -> m4_definir_consentement_gps (PLAN T1.4-k)", () => {
    expect(DESCRIPTEURS_MUTATION.get("gps_consent_change")?.tool).toBe("m4_definir_consentement_gps");
  });

  test("le descripteur lit l'accusé : actif=false après un retrait est rendu tel quel, jamais maquillé", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("gps_consent_change")!.interpreterResultat;
    const accuse = {
      technicien_id: "marc.fictif",
      action: "retire",
      horodatage: "2026-09-28T14:32:11+00:00",
      ligne_id: "L1",
      actif: false,
      tete_chaine: "t",
    };

    expect(interpreter({ ok: true, resultat: { accepte: true, resultat: accuse }, rejoue: false })).toEqual({
      accepte: true,
      resume: accuse,
    });
  });

  test("un retrait refusé (autre personne) -> accepte:false avec le verdict, jamais un succès silencieux", () => {
    const interpreter = DESCRIPTEURS_MUTATION.get("gps_consent_change")!.interpreterResultat;
    const verdict = { code: "REJ-IDENTITE-FOURNIE-DIFFERENTE", detail: "technicien_id ne correspond pas à la personne" };

    expect(interpreter({ ok: true, resultat: { accepte: false, verdict } })).toEqual({ accepte: false, verdict });
  });
});

describe("interpreterResultatDefinirConsentementGps", () => {
  test("accepté -> l'accusé du serveur, tel quel", () => {
    const accuse = {
      technicien_id: "marc.fictif",
      action: "donne",
      horodatage: "2026-09-28T14:32:11+00:00",
      ligne_id: "L1",
      actif: true,
      tete_chaine: "t",
    };

    expect(interpreterResultatDefinirConsentementGps({ ok: true, resultat: { accepte: true, resultat: accuse } })).toEqual({
      accepte: true,
      accuse,
    });
  });

  test.each([
    ["REJ-IDENTITE-FOURNIE-DIFFERENTE", "consentement d'un autre"],
    ["REJ-IDENTITE-APPAREIL-INVALIDE", "personne désactivée"],
    ["REJ-CONSENTEMENT-INVALIDE", "preuve réelle non supportée"],
  ])("rejet métier %s -> accepte:false, code et détail lus", (code, detail) => {
    const resultat = interpreterResultatDefinirConsentementGps({
      ok: true,
      resultat: { accepte: false, verdict: { code, detail, statut: "" } },
    });

    expect(resultat).toEqual({ accepte: false, verdict: { code, detail } });
  });

  test("verdict sans code -> REJ-INCONNU, jamais un succès", () => {
    expect(interpreterResultatDefinirConsentementGps({ ok: true, resultat: { accepte: false } })).toEqual({
      accepte: false,
      verdict: { code: "REJ-INCONNU", detail: "" },
    });
  });

  test("échec technique (ok:false) -> verdict avec l'erreur du serveur", () => {
    expect(
      interpreterResultatDefinirConsentementGps({ ok: false, erreur: "arguments_invalides", details: "preuve manquante" }),
    ).toEqual({ accepte: false, verdict: { code: "arguments_invalides", detail: "preuve manquante" } });
  });

  test.each([[null], [undefined], ["texte"], [42], [{}], [{ ok: true }]])(
    "forme non reconnue %p -> succès sans accusé (le serveur a répondu 200), jamais un plantage",
    (brut) => {
      expect(interpreterResultatDefinirConsentementGps(brut)).toEqual({ accepte: true, accuse: null });
    },
  );
});
