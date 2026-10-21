import { construireArgumentsPointer, interpreterResultatPointage } from "./pointage";
import type { ContextePointageM4 } from "./pointage";

const CONTEXTE: ContextePointageM4 = {
  fixGps: { latitude: 45.5017, longitude: -73.5673 },
  appareilId: "APP-1",
  fenetreTravail: { debut: "2026-09-28T00:00:00-04:00", fin: "2026-09-28T23:59:59-04:00" },
  referentielVilles: { "jeton-mtl": { latitude: 45.5017, longitude: -73.5673, rayon_km: 25 } },
  ville: "Montreal",
  sel: "sel-de-test",
};

describe("construireArgumentsPointer", () => {
  test("assemble les args EXACTS de m4_pointer (snake_case, dix clés, rien de plus)", () => {
    const args = construireArgumentsPointer("interv-1", "T1", "arrivee", "2026-09-28T14:32:00-04:00", CONTEXTE);

    expect(args).toEqual({
      intervention_id: "interv-1",
      technicien_id: "T1",
      action: "arrivee",
      horodatage: "2026-09-28T14:32:00-04:00",
      fix_gps: { latitude: 45.5017, longitude: -73.5673 },
      attestation: { fictif: true, appareil_id: "APP-1" },
      fenetre_travail: { debut: "2026-09-28T00:00:00-04:00", fin: "2026-09-28T23:59:59-04:00" },
      referentiel_villes: { "jeton-mtl": { latitude: 45.5017, longitude: -73.5673, rayon_km: 25 } },
      ville: "Montreal",
      sel: "sel-de-test",
    });
    expect(Object.keys(args).sort()).toEqual(
      [
        "action",
        "attestation",
        "fenetre_travail",
        "fix_gps",
        "horodatage",
        "intervention_id",
        "referentiel_villes",
        "sel",
        "technicien_id",
        "ville",
      ].sort(),
    );
  });

  test.each(["arrivee", "depart", "pause_debut", "pause_fin"] as const)(
    "accepte l'action réelle de pointage.ACTIONS : %s",
    (action) => {
      const args = construireArgumentsPointer("i", "t", action, "2026-09-28T14:32:00-04:00", CONTEXTE);
      expect(args.action).toBe(action);
    },
  );

  test("attestation.fictif est TOUJOURS true (seul mode que le serveur accepte aujourd'hui)", () => {
    const args = construireArgumentsPointer("i", "t", "depart", "2026-09-28T15:00:00-04:00", CONTEXTE);
    expect(args.attestation.fictif).toBe(true);
  });
});

describe("interpreterResultatPointage — succès métier (accepte: true)", () => {
  test("extrait l'accusé quand accepte:true", () => {
    const accuse = {
      intervention_id: "i1",
      technicien_id: "t1",
      action: "arrivee",
      horodatage: "2026-09-28T14:32:00-04:00",
      ligne_id: "L1",
      gps_coherent: true,
      statut: "sur_site",
      demande_id: null,
    };
    const resultat = interpreterResultatPointage({
      ok: true,
      resultat: { accepte: true, resultat: accuse },
      rejoue: false,
    });
    expect(resultat).toEqual({ accepte: true, accuse });
  });

  test("gps_coherent:false reste un SUCCÈS (routage en_revue côté serveur, pas un rejet)", () => {
    const accuse = {
      intervention_id: "i1",
      technicien_id: "t1",
      action: "arrivee",
      horodatage: "2026-09-28T14:32:00-04:00",
      ligne_id: "L1",
      gps_coherent: false,
      statut: "en_revue",
      demande_id: "D1",
    };
    const resultat = interpreterResultatPointage({ ok: true, resultat: { accepte: true, resultat: accuse } });
    expect(resultat.accepte).toBe(true);
  });

  test("rejoue:true (idempotence, IDEMPOTENCE.md §6) est traité EXACTEMENT comme rejoue:false", () => {
    const enveloppe = { ok: true, resultat: { accepte: true, resultat: { statut: "sur_site" } } };
    const sansRejeu = interpreterResultatPointage(enveloppe);
    const avecRejeu = interpreterResultatPointage({ ...enveloppe, rejoue: true });
    expect(avecRejeu).toEqual(sansRejeu);
    expect(avecRejeu.accepte).toBe(true);
  });
});

describe("interpreterResultatPointage — rejet métier (accepte: false)", () => {
  test("extrait le verdict (code, detail) quand accepte:false", () => {
    const resultat = interpreterResultatPointage({
      ok: true,
      resultat: {
        accepte: false,
        verdict: { code: "REJ-PUNCH-HORS-HEURES", statut: "", detail: "Pointage hors fenêtre [..]" },
      },
    });
    expect(resultat).toEqual({
      accepte: false,
      verdict: { code: "REJ-PUNCH-HORS-HEURES", detail: "Pointage hors fenêtre [..]" },
    });
  });

  test("un rejet reste un rejet même rejoué (rejoue:true, orthogonal à accepte)", () => {
    const enveloppe = {
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-CONTRAT-INVALIDE", detail: "x" } },
      rejoue: true,
    };
    const resultat = interpreterResultatPointage(enveloppe);
    expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-CONTRAT-INVALIDE", detail: "x" } });
  });

  test("erreur au niveau outils.executer (ok:false) est aussi traitée comme un rejet définitif", () => {
    const resultat = interpreterResultatPointage({ ok: false, erreur: "arguments_invalides", details: "champ manquant" });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "arguments_invalides", detail: "champ manquant" } });
  });
});

describe("interpreterResultatPointage — formes non reconnues (défensif, jamais un crash)", () => {
  test.each([null, undefined, "texte", 42, {}, { ok: true }, { ok: true, resultat: {} }])(
    "forme inattendue %p -> traitée comme un succès sans accusé, jamais un throw",
    (valeur) => {
      expect(() => interpreterResultatPointage(valeur)).not.toThrow();
      expect(interpreterResultatPointage(valeur)).toEqual({ accepte: true, accuse: null });
    },
  );
});
