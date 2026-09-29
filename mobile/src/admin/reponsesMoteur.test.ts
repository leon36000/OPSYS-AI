import { OUTIL_LISTER_DEMANDES, construireArgumentsListerDemandes } from "../approbations/chargeur";
import {
  construireArgumentsDigest,
  construireArgumentsListerInterventions,
  construireArgumentsPreparation,
  lireDigest,
  lireInterventions,
  lirePreparation,
  OUTIL_LISTER_INTERVENTIONS,
  OUTIL_PRODUIRE_DIGEST,
  OUTIL_VERIFIER_PREPARATION,
  STATUTS_DU_DISPATCH,
} from "../m4/dispatch";
import {
  construireArgumentsEcheances,
  construireArgumentsEtatTresorerie,
  construireArgumentsPrevision,
  lireEcheancesFiscales,
  lireEtatTresorerie,
  lirePrevisionTresorerie,
  OUTIL_ECHEANCES_FISCALES,
  OUTIL_ETAT_TRESORERIE,
  OUTIL_PREVOIR_TRESORERIE,
} from "../m5/tresorerie";
import { construireArgumentsVueExecutive, lireVueExecutive, OUTIL_VUE_EXECUTIVE } from "../m8/vueExecutive";
import { interpreterAVoir } from "./aVoir";
import { appel, FICTIF, FIXTURE, reponse } from "./donneesDeTest";
import { interpreter } from "./enveloppe";
import type { LectureSection } from "./enveloppe";

/**
 * Le pont entre le moteur et l'app (PLAN T4.20). `fixtures/reponses-moteur.json` est la VRAIE sortie du moteur, enregistrée
 * par `tests/e2e/test_admin_appareil.py` (qui la compare, forme pour forme, à ce que le moteur répond aujourd'hui) :
 *  - chaque réponse passe par le lecteur de son outil, et l'app la classe comme le moteur l'a voulue (lue, ou refusée
 *    avec le verdict du moteur) ;
 *  - chaque appel enregistré est EXACTEMENT ce que les constructeurs d'arguments de l'app envoient : un argument de plus,
 *    de moins ou renommé serait refusé par le moteur (`arguments_invalides`) — ici, il fait échouer ce test.
 */

const AUJOURD_HUI = "2026-09-29";
const JOUR_DU_DIGEST = "2026-09-21";
const REFERENCE_DU_DIGEST = "2026-09-21T18:00:00-04:00";

type Attendu = { readonly lue: true } | { readonly refus: string };
interface Ligne {
  readonly lire: (brut: unknown) => LectureSection<unknown>;
  readonly attendu: Attendu;
}

const couple = (lecteur: (valeur: unknown) => unknown | null) => (brut: unknown) => interpreter(brut, "couple", lecteur as (v: unknown) => unknown);
const directe = (lecteur: (valeur: unknown) => unknown | null) => (brut: unknown) => interpreter(brut, "directe", lecteur as (v: unknown) => unknown);
const interventions = (statut: string) => directe((valeur) => lireInterventions(valeur, statut));

const LUE: Attendu = { lue: true };

/** Chaque réponse de la fixture, le lecteur de son outil et ce que l'app doit en faire. */
const LIGNES: Readonly<Record<string, Ligne>> = {
  a_voir_vide: { lire: interpreterAVoir, attendu: LUE },
  a_voir: { lire: interpreterAVoir, attendu: LUE },
  a_voir_avec_demande: { lire: interpreterAVoir, attendu: LUE },
  vue_executive_vide: { lire: directe(lireVueExecutive), attendu: LUE },
  vue_executive: { lire: directe(lireVueExecutive), attendu: LUE },
  tresorerie_sans_solde: { lire: directe(lireEtatTresorerie), attendu: LUE },
  tresorerie: { lire: directe(lireEtatTresorerie), attendu: LUE },
  tresorerie_sans_paies: { lire: directe(lireEtatTresorerie), attendu: LUE },
  prevision_horizon_a_declarer: { lire: couple(lirePrevisionTresorerie), attendu: { refus: "REJ-PREVISION-HORIZON-A-CONFIGURER" } },
  echeances_frequence_a_declarer: { lire: couple(lireEcheancesFiscales), attendu: { refus: "REJ-FISCAL-FREQUENCE-A-DECLARER" } },
  interventions_planifiee_vide: { lire: interventions("planifiee"), attendu: LUE },
  digest_vide: { lire: couple(lireDigest), attendu: LUE },
  digest: { lire: couple(lireDigest), attendu: LUE },
  preparation_inconnue: { lire: couple(lirePreparation), attendu: { refus: "REJ-TRANSITION-ILLEGALE" } },
  preparation_terminee: { lire: couple(lirePreparation), attendu: { refus: "REJ-TRANSITION-ILLEGALE" } },
  preparation_lead_v2: { lire: couple(lirePreparation), attendu: LUE },
  preparation_lead_v1: { lire: couple(lirePreparation), attendu: LUE },
  preparation_a_planifier: { lire: couple(lirePreparation), attendu: LUE },
  prevision: { lire: couple(lirePrevisionTresorerie), attendu: LUE },
  prevision_sans_paies: { lire: couple(lirePrevisionTresorerie), attendu: LUE },
  prevision_sans_seuil: { lire: couple(lirePrevisionTresorerie), attendu: LUE },
  prevision_sans_alerte: { lire: couple(lirePrevisionTresorerie), attendu: LUE },
  prevision_longue_page_1: { lire: couple(lirePrevisionTresorerie), attendu: LUE },
  prevision_longue_page_2: { lire: couple(lirePrevisionTresorerie), attendu: LUE },
  echeances: { lire: couple(lireEcheancesFiscales), attendu: LUE },
  echeances_en_retard: { lire: couple(lireEcheancesFiscales), attendu: LUE },
  ...Object.fromEntries(STATUTS_DU_DISPATCH.map((statut) => [`interventions_${statut}`, { lire: interventions(statut), attendu: LUE }])),
  // Les refus du serveur : l'app les classe en refus (jamais en panne), avec le mot du moteur.
  interventions_statut_inconnu: { lire: interventions("inconnu"), attendu: { refus: "arguments_invalides" } },
  refus_identite_vue_executive: { lire: directe(lireVueExecutive), attendu: { refus: "refus_metier" } },
  refus_identite_tresorerie: { lire: directe(lireEtatTresorerie), attendu: { refus: "REJ-IDENTITE-APPAREIL-INVALIDE" } },
  refus_identite_interventions: { lire: interventions("planifiee"), attendu: { refus: "refus_metier" } },
};

describe("les réponses réelles du moteur, lues par l'app", () => {
  test("la fixture est fictive, et la table couvre chacune de ses réponses (une réponse de plus force une ligne de plus)", () => {
    expect(FICTIF).toBe(true);
    expect(FIXTURE.fictif).toBe(true);
    expect(Object.keys(FIXTURE.reponses).sort()).toEqual(Object.keys(LIGNES).sort());
  });

  test.each(Object.entries(LIGNES))("%s : l'app la classe comme le moteur l'a voulue", (nom, { lire, attendu }) => {
    const lu = lire(reponse(nom));
    if ("lue" in attendu) {
      expect({ nom, ok: lu.ok }).toEqual({ nom, ok: true });
    } else {
      expect(lu).toMatchObject({ ok: false, genre: "refus", verdict: { code: attendu.refus } });
    }
  });

  test("un refus du moteur n'a jamais la forme d'une panne passagère (un cache ne peut donc pas le remplacer)", () => {
    for (const [nom, { lire, attendu }] of Object.entries(LIGNES)) {
      if (!("refus" in attendu)) {
        continue;
      }
      const lu = lire(reponse(nom));
      expect({ nom, genre: lu.ok ? "lue" : lu.genre }).toEqual({ nom, genre: "refus" });
    }
  });
});

describe("les appels enregistrés sont exactement ce que les constructeurs de l'app envoient", () => {
  const ATTENDUS: Readonly<Record<string, { outil: string; args: Record<string, unknown> }>> = {
    a_voir_vide: { outil: OUTIL_LISTER_DEMANDES, args: construireArgumentsListerDemandes(undefined) },
    a_voir: { outil: OUTIL_LISTER_DEMANDES, args: construireArgumentsListerDemandes(undefined) },
    a_voir_avec_demande: { outil: OUTIL_LISTER_DEMANDES, args: construireArgumentsListerDemandes(undefined) },
    vue_executive_vide: { outil: OUTIL_VUE_EXECUTIVE, args: construireArgumentsVueExecutive() },
    vue_executive: { outil: OUTIL_VUE_EXECUTIVE, args: construireArgumentsVueExecutive() },
    refus_identite_vue_executive: { outil: OUTIL_VUE_EXECUTIVE, args: construireArgumentsVueExecutive() },
    tresorerie_sans_solde: { outil: OUTIL_ETAT_TRESORERIE, args: construireArgumentsEtatTresorerie() },
    tresorerie: { outil: OUTIL_ETAT_TRESORERIE, args: construireArgumentsEtatTresorerie() },
    tresorerie_sans_paies: { outil: OUTIL_ETAT_TRESORERIE, args: construireArgumentsEtatTresorerie() },
    refus_identite_tresorerie: { outil: OUTIL_ETAT_TRESORERIE, args: construireArgumentsEtatTresorerie() },
    prevision_horizon_a_declarer: { outil: OUTIL_PREVOIR_TRESORERIE, args: construireArgumentsPrevision(AUJOURD_HUI) },
    prevision: { outil: OUTIL_PREVOIR_TRESORERIE, args: construireArgumentsPrevision(AUJOURD_HUI) },
    prevision_sans_paies: { outil: OUTIL_PREVOIR_TRESORERIE, args: construireArgumentsPrevision(AUJOURD_HUI) },
    prevision_sans_seuil: { outil: OUTIL_PREVOIR_TRESORERIE, args: construireArgumentsPrevision(AUJOURD_HUI) },
    prevision_sans_alerte: { outil: OUTIL_PREVOIR_TRESORERIE, args: construireArgumentsPrevision(AUJOURD_HUI) },
    prevision_longue_page_1: { outil: OUTIL_PREVOIR_TRESORERIE, args: construireArgumentsPrevision(AUJOURD_HUI) },
    // La page suivante demande le rang que M5 a donné (`prochain_depart` de la première page : 19).
    prevision_longue_page_2: { outil: OUTIL_PREVOIR_TRESORERIE, args: construireArgumentsPrevision(AUJOURD_HUI, 19) },
    echeances_frequence_a_declarer: { outil: OUTIL_ECHEANCES_FISCALES, args: construireArgumentsEcheances(AUJOURD_HUI) },
    echeances: { outil: OUTIL_ECHEANCES_FISCALES, args: construireArgumentsEcheances(AUJOURD_HUI) },
    echeances_en_retard: { outil: OUTIL_ECHEANCES_FISCALES, args: construireArgumentsEcheances(AUJOURD_HUI) },
    interventions_planifiee_vide: { outil: OUTIL_LISTER_INTERVENTIONS, args: construireArgumentsListerInterventions("planifiee") },
    interventions_statut_inconnu: { outil: OUTIL_LISTER_INTERVENTIONS, args: construireArgumentsListerInterventions("inconnu") },
    refus_identite_interventions: { outil: OUTIL_LISTER_INTERVENTIONS, args: construireArgumentsListerInterventions("planifiee") },
    ...Object.fromEntries(
      STATUTS_DU_DISPATCH.map((statut) => [
        `interventions_${statut}`,
        { outil: OUTIL_LISTER_INTERVENTIONS, args: construireArgumentsListerInterventions(statut) },
      ]),
    ),
    digest_vide: { outil: OUTIL_PRODUIRE_DIGEST, args: construireArgumentsDigest(JOUR_DU_DIGEST, REFERENCE_DU_DIGEST) },
    digest: { outil: OUTIL_PRODUIRE_DIGEST, args: construireArgumentsDigest(JOUR_DU_DIGEST, REFERENCE_DU_DIGEST) },
  };

  test("chaque appel enregistré a son constructeur, et chaque réponse a son appel", () => {
    const sansPreparation = Object.keys(FIXTURE.appels).filter((nom) => !nom.startsWith("preparation_"));
    expect(sansPreparation.sort()).toEqual(Object.keys(ATTENDUS).sort());
    expect(Object.keys(FIXTURE.appels).sort()).toEqual(Object.keys(FIXTURE.reponses).sort());
  });

  test.each(Object.entries(ATTENDUS))("%s", (nom, attendu) => {
    const enregistre = appel(nom);
    expect(enregistre.outil).toBe(attendu.outil);
    expect(enregistre.args).toEqual(attendu.args);
  });

  test.each(["preparation_inconnue", "preparation_terminee", "preparation_lead_v2", "preparation_lead_v1", "preparation_a_planifier"])(
    "%s : le numéro d'intervention est le seul argument",
    (nom) => {
      const enregistre = appel(nom);
      expect(enregistre.outil).toBe(OUTIL_VERIFIER_PREPARATION);
      expect(enregistre.args).toEqual(construireArgumentsPreparation(String(enregistre.args.intervention_id)));
      expect(Object.keys(enregistre.args)).toEqual(["intervention_id"]);
    },
  );

  test("aucun appel n'envoie une personne, un rôle ni un montant : le serveur les tient du jeton d'appareil", () => {
    for (const enregistre of Object.values(FIXTURE.appels)) {
      for (const interdit of ["personne", "role", "roles", "autorise_couts", "montant", "seuil", "horizon_semaines"]) {
        expect(Object.keys(enregistre.args)).not.toContain(interdit);
      }
    }
  });
});
