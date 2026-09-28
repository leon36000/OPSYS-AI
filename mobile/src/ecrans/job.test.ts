import {
  actionsDisponiblesJob,
  phaseDepuisStatutServeur,
  resoudreActionJob,
} from "./job";
import type { ActionJob, PhaseJob } from "./job";

const PHASES: readonly PhaseJob[] = ["planifiee", "en_route", "sur_place", "en_pause"];
const ACTIONS: readonly ActionJob[] = ["enRoute", "arrive", "pause"];

describe("resoudreActionJob — matrice complète", () => {
  test.each(
    PHASES.flatMap((phase) => ACTIONS.map((action) => [phase, action] as const)),
  )("phase=%s action=%s", (phase, action) => {
    const resultat = resoudreActionJob(phase, action);
    const attenduLegal: Partial<Record<PhaseJob, ActionJob>> = {
      planifiee: "enRoute",
      en_route: "arrive",
      sur_place: "pause",
      en_pause: "pause",
    };
    if (attenduLegal[phase] === action) {
      expect(resultat).not.toBeNull();
    } else {
      expect(resultat).toBeNull();
    }
  });

  test("planifiee + enRoute -> job_status_change, phase en_route", () => {
    expect(resoudreActionJob("planifiee", "enRoute")).toEqual({
      phaseSuivante: "en_route",
      typeMutation: "job_status_change",
    });
  });

  test("en_route + arrive -> punch_in/arrivee, phase sur_place", () => {
    expect(resoudreActionJob("en_route", "arrive")).toEqual({
      phaseSuivante: "sur_place",
      typeMutation: "punch_in",
      action: "arrivee",
    });
  });

  test("sur_place + pause -> punch_out/pause_debut, phase en_pause", () => {
    expect(resoudreActionJob("sur_place", "pause")).toEqual({
      phaseSuivante: "en_pause",
      typeMutation: "punch_out",
      action: "pause_debut",
    });
  });

  test("en_pause + pause -> punch_in/pause_fin, retour à sur_place", () => {
    expect(resoudreActionJob("en_pause", "pause")).toEqual({
      phaseSuivante: "sur_place",
      typeMutation: "punch_in",
      action: "pause_fin",
    });
  });
});

describe("actionsDisponiblesJob", () => {
  test("planifiee -> [enRoute] seulement", () => {
    expect(actionsDisponiblesJob("planifiee")).toEqual(["enRoute"]);
  });

  test("en_route -> [arrive] seulement", () => {
    expect(actionsDisponiblesJob("en_route")).toEqual(["arrive"]);
  });

  test("sur_place -> [pause] seulement", () => {
    expect(actionsDisponiblesJob("sur_place")).toEqual(["pause"]);
  });

  test("en_pause -> [pause] seulement (le même bouton bascule en fin de pause)", () => {
    expect(actionsDisponiblesJob("en_pause")).toEqual(["pause"]);
  });
});

describe("phaseDepuisStatutServeur", () => {
  test("planifiee -> planifiee", () => {
    expect(phaseDepuisStatutServeur("planifiee")).toBe("planifiee");
  });

  test("en_route -> en_route", () => {
    expect(phaseDepuisStatutServeur("en_route")).toBe("en_route");
  });

  test("sur_site -> sur_place, JAMAIS en_pause (pas dérivable d'un statut serveur)", () => {
    expect(phaseDepuisStatutServeur("sur_site")).toBe("sur_place");
  });

  test.each<StatutInterventionM4OuNull>([
    "en_revue",
    "reportee",
    "completed_pending_review",
    "completed_verified",
    "annulee",
    null,
  ])("statut hors flux (%s) -> null, aucun bouton deviné", (statut) => {
    expect(phaseDepuisStatutServeur(statut)).toBeNull();
  });
});

type StatutInterventionM4OuNull = Parameters<typeof phaseDepuisStatutServeur>[0];
