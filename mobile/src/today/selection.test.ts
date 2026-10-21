import { ETATS_ACTIFS_AUJOURDHUI, filtrerChantiersActifs } from "./selection";
import type { InterventionM4, StatutInterventionM4 } from "../m4/interventions";

function intervention(id: string, statut: StatutInterventionM4): InterventionM4 {
  return { intervention_id: id, statut, lead_id: `L-${id}`, type_travaux: "gouttieres", devis_id: null };
}

describe("filtrerChantiersActifs", () => {
  test("exclut les statuts terminaux, jamais rien à faire aujourd'hui pour eux", () => {
    const interventions = [
      intervention("I1", "completed_verified"),
      intervention("I2", "completed_pending_review"),
      intervention("I3", "annulee"),
    ];
    expect(filtrerChantiersActifs(interventions)).toEqual([]);
  });

  test("exclut reportee : sortie du flux du jour tant qu'elle n'est pas replanifiee", () => {
    expect(filtrerChantiersActifs([intervention("I1", "reportee")])).toEqual([]);
  });

  test("exclut a_planifier : née d'un devis accepté, pas encore cédulée, elle n'est à personne (le serveur ne la donne pas à l'employé)", () => {
    expect(filtrerChantiersActifs([intervention("I1", "a_planifier")])).toEqual([]);
  });

  test("retient exactement les quatre statuts actifs documentés", () => {
    expect(ETATS_ACTIFS_AUJOURDHUI).toEqual(["en_route", "sur_site", "en_revue", "planifiee"]);
  });

  test("ordonne par urgence (en_route, sur_site, en_revue, planifiee), pas par ordre d'arrivée", () => {
    const interventions = [
      intervention("Z", "planifiee"),
      intervention("A", "en_revue"),
      intervention("M", "en_route"),
      intervention("B", "sur_site"),
    ];
    expect(filtrerChantiersActifs(interventions).map((i) => i.intervention_id)).toEqual(["M", "B", "A", "Z"]);
  });

  test("à statut égal, tri stable par intervention_id (déterministe)", () => {
    const interventions = [intervention("I2", "planifiee"), intervention("I1", "planifiee")];
    expect(filtrerChantiersActifs(interventions).map((i) => i.intervention_id)).toEqual(["I1", "I2"]);
  });

  test("ne mute jamais le tableau reçu", () => {
    const interventions = [intervention("I1", "planifiee")];
    filtrerChantiersActifs(interventions);
    expect(interventions).toEqual([intervention("I1", "planifiee")]);
  });

  test("liste vide -> liste vide", () => {
    expect(filtrerChantiersActifs([])).toEqual([]);
  });
});
