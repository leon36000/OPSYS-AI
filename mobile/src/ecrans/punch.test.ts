import {
  actionsDisponibles,
  deriverEtatSynchroAffiche,
  extraireHeureMinuteLocale,
  resoudreActionEmploye,
} from "./punch";
import type { PhasePointage } from "./punch";

describe("resoudreActionEmploye — graphe des transitions locales", () => {
  test("avant_arrivee + entree -> sur_place, punch_in, arrivee", () => {
    expect(resoudreActionEmploye("avant_arrivee", "entree")).toEqual({
      phaseSuivante: "sur_place",
      typeMutation: "punch_in",
      action: "arrivee",
    });
  });

  test("sur_place + sortie -> avant_arrivee, punch_out, depart", () => {
    expect(resoudreActionEmploye("sur_place", "sortie")).toEqual({
      phaseSuivante: "avant_arrivee",
      typeMutation: "punch_out",
      action: "depart",
    });
  });

  test("sur_place + pause -> en_pause, punch_out, pause_debut", () => {
    expect(resoudreActionEmploye("sur_place", "pause")).toEqual({
      phaseSuivante: "en_pause",
      typeMutation: "punch_out",
      action: "pause_debut",
    });
  });

  test("en_pause + pause -> sur_place, punch_in, pause_fin", () => {
    expect(resoudreActionEmploye("en_pause", "pause")).toEqual({
      phaseSuivante: "sur_place",
      typeMutation: "punch_in",
      action: "pause_fin",
    });
  });

  test.each<[PhasePointage, "entree" | "sortie" | "pause"]>([
    ["avant_arrivee", "sortie"],
    ["avant_arrivee", "pause"],
    ["sur_place", "entree"],
    ["en_pause", "entree"],
    ["en_pause", "sortie"],
  ])("%s + %s est HORS graphe -> null (fail-closed)", (phase, action) => {
    expect(resoudreActionEmploye(phase, action)).toBeNull();
  });
});

describe("actionsDisponibles", () => {
  test("avant_arrivee : seulement entree", () => {
    expect(actionsDisponibles("avant_arrivee")).toEqual(["entree"]);
  });

  test("sur_place : sortie et pause, jamais entree", () => {
    expect(actionsDisponibles("sur_place")).toEqual(["sortie", "pause"]);
  });

  test("en_pause : seulement pause (fin de pause)", () => {
    expect(actionsDisponibles("en_pause")).toEqual(["pause"]);
  });
});

describe("extraireHeureMinuteLocale", () => {
  test("ISO avec décalage négatif (EDT) -> heures/minutes extraites textuellement", () => {
    expect(extraireHeureMinuteLocale("2026-09-28T14:32:05-04:00")).toEqual({ heures: "14", minutes: "32" });
  });

  test("ISO avec décalage positif -> heures/minutes extraites sans conversion", () => {
    expect(extraireHeureMinuteLocale("2026-01-15T07:05:00+01:00")).toEqual({ heures: "07", minutes: "05" });
  });

  test("chaîne invalide -> null, jamais un throw", () => {
    expect(extraireHeureMinuteLocale("pas-une-date")).toBeNull();
  });

  test("reste correct quel que soit le fuseau du runtime qui l'exécute (pas de new Date(...))", () => {
    // Le point même de l'extraction textuelle : ce test doit passer identiquement que la
    // machine CI tourne en UTC, en Amérique/Montréal ou ailleurs.
    const original = process.env.TZ;
    try {
      process.env.TZ = "Pacific/Kiritimati"; // UTC+14, très loin de -04:00
      expect(extraireHeureMinuteLocale("2026-09-28T14:32:05-04:00")).toEqual({ heures: "14", minutes: "32" });
    } finally {
      process.env.TZ = original;
    }
  });
});

describe("deriverEtatSynchroAffiche", () => {
  test("brouillon/en_attente -> en_attente", () => {
    expect(deriverEtatSynchroAffiche("en_attente", null)).toEqual({ genre: "en_attente" });
    expect(deriverEtatSynchroAffiche("brouillon", null)).toEqual({ genre: "en_attente" });
  });

  test("envoi -> envoi (en cours)", () => {
    expect(deriverEtatSynchroAffiche("envoi", null)).toEqual({ genre: "envoi" });
  });

  test("envoyee -> envoyee", () => {
    expect(deriverEtatSynchroAffiche("envoyee", null)).toEqual({ genre: "envoyee" });
  });

  test("echec_permanent SANS verdict connu (redémarrage, pas encore revidangé) -> verdict null", () => {
    expect(deriverEtatSynchroAffiche("echec_permanent", null)).toEqual({ genre: "echec_permanent", verdict: null });
  });

  test("echec_permanent AVEC le verdict du serveur (mission item 2)", () => {
    const verdict = { code: "REJ-PUNCH-HORS-HEURES", detail: "hors fenêtre" };
    expect(deriverEtatSynchroAffiche("echec_permanent", verdict)).toEqual({ genre: "echec_permanent", verdict });
  });
});
