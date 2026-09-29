import fs from "node:fs";
import path from "node:path";

import { interpreter } from "../admin/enveloppe";
import { lirePreparation } from "../m4/dispatch";
import type { Preparation } from "../m4/dispatch";
import enCA from "../i18n/locales/en-CA";
import frCA from "../i18n/locales/fr-CA";
import type { Message } from "./adminCommun";
import { presenterPreparation } from "./chantiers";
import { direLeManque, MANQUES_CONNUS } from "./manquesM4";
import { texteSansChemin } from "./texteSur";

/**
 * Les vraies réponses du moteur (`m4_verifier_preparation` par la porte d'appareil `admin`, capturées par
 * `tests/e2e/test_manques_m4_appareil.py` : `admin/fixtures/manques-m4.json`) passent par les lecteurs et le modèle de vue
 * de l'app (PLAN T1.4-n, constat 4). Ce que le propriétaire lirait de chaque manque, dans les deux langues, ne cite ni le
 * fichier du serveur ni ses commandes ; la table de l'app couvre tout ce que M4 a dit.
 */

interface Fixture {
  readonly fictif: boolean;
  readonly appels: Record<string, { readonly outil: string; readonly args: Record<string, string> }>;
  readonly reponses: Record<string, any>;
}

const FIXTURE: Fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "admin", "fixtures", "manques-m4.json"), "utf8"));

const LANGUES = [
  ["fr-CA", frCA],
  ["en-CA", enCA],
] as const;

function resoudre(ressources: unknown, chemin: string): unknown {
  return chemin
    .split(".")
    .reduce<unknown>((noeud, segment) => (typeof noeud === "object" && noeud !== null ? (noeud as Record<string, unknown>)[segment] : undefined), ressources);
}

/** Ce que `t(cle, params)` afficherait : le texte de la langue, ses `{{variables}}` remplies. */
function rendre(m: Message, ressources: unknown): string {
  const texte = resoudre(ressources, m.cle);
  if (typeof texte !== "string") {
    throw new Error(`texte absent : ${m.cle}`);
  }
  return texte.replace(/\{\{(\w+)\}\}/g, (_tout, nom: string) => String(m.params?.[nom]));
}

function preparationDe(nom: string): Preparation {
  const lu = interpreter(FIXTURE.reponses[nom], "couple", lirePreparation);
  if (!lu.ok) {
    throw new Error(`${nom} : préparation illisible : ${lu.verdict.code}`);
  }
  return lu.valeur;
}

const SCENARIOS = Object.keys(FIXTURE.reponses);

/** Ce que le propriétaire doit lire pour chaque volet qui n'est pas prêt, par scénario (clé du texte sous `manques`). */
const PHRASES_ATTENDUES: Record<string, Record<string, string>> = {
  sans_rien_declare: {
    adresse: "adresse.aConfirmer",
    equipe: "equipe.nonDeclarees",
    materiel: "materiel.aCommander",
    meteo: "meteo.nonDeclarees",
  },
  profils_illisibles: {
    adresse: "adresse.aConfirmer",
    equipe: "equipe.profilInvalide",
    materiel: "materiel.partiel",
    meteo: "meteo.profilInvalide",
  },
  reglages_incomplets: {
    adresse: "adresse.aConfirmer",
    equipe: "equipe.reglagesIncomplets",
    materiel: "materiel.partiel",
    meteo: "meteo.seuilsIncomplets",
  },
  aucune_equipe_admissible: {
    adresse: "adresse.aConfirmer",
    equipe: "equipe.aucuneAdmissible",
    materiel: "materiel.partiel",
  },
  lead_v1_profils_complets: {
    adresse: "adresse.aConfirmer",
    equipe: "equipe.nonVerifiable",
    materiel: "materiel.nonVerifiable",
    meteo: "meteo.nonVerifiable",
  },
  materiel_sans_charge: {
    adresse: "adresse.aConfirmer",
    materiel: "materiel.nonVerifiable",
  },
};

describe("les réponses réelles du moteur : la préparation d'une intervention et ses manques", () => {
  test("la fixture est fictive et porte les six scénarios, chacun lu par `m4_verifier_preparation` sous son nom nu", () => {
    expect(FIXTURE.fictif).toBe(true);
    expect(SCENARIOS.sort()).toEqual(Object.keys(PHRASES_ATTENDUES).sort());
    for (const appel of Object.values(FIXTURE.appels)) {
      expect(appel.outil).toBe("m4_verifier_preparation");
    }
  });

  test.each(SCENARIOS)("%s : la réponse est lue par l'app, jamais « prête », et chaque manque est de la table", (nom) => {
    const preparation = preparationDe(nom);
    expect(preparation.pret).toBe(false);
    for (const volet of preparation.volets.filter((v) => v.statut !== "ok")) {
      const dit = direLeManque(volet);
      expect({ scenario: nom, volet: volet.nom, connu: dit.connu }).toEqual({ scenario: nom, volet: volet.nom, connu: true });
    }
  });

  test.each(SCENARIOS)("%s : chaque volet qui n'est pas prêt se dit par la phrase attendue, et le code du serveur", (nom) => {
    const vue = presenterPreparation(preparationDe(nom));
    const dits: Record<string, string> = {};
    for (const [index, volet] of preparationDe(nom).volets.entries()) {
      const ligne = vue.volets[index];
      if (volet.statut === "ok") {
        expect(ligne.manque).toBeNull();
        continue;
      }
      expect(ligne.manque?.cle.startsWith("admin.chantiers.manques.")).toBe(true);
      dits[volet.nom] = (ligne.manque as Message).cle.replace("admin.chantiers.manques.", "");
    }
    expect(dits).toEqual(PHRASES_ATTENDUES[nom]);
    // « À fournir » dit la même chose, volet par volet.
    expect(Object.fromEntries(vue.aFournir.map((a) => [a.volet.cle.replace("admin.chantiers.volets.", ""), a.manque.cle.replace("admin.chantiers.manques.", "")]))).toEqual(
      PHRASES_ATTENDUES[nom],
    );
  });

  test("le texte de M4 cite bien le fichier du serveur et ses commandes : sans cela, il n'y aurait rien à taire", () => {
    const brut = (nom: string, volet: string): string => FIXTURE.reponses[nom].resultat.resultat.volets[volet].manque;
    expect(texteSansChemin(brut("sans_rien_declare", "equipe"))).toBeNull();
    expect(brut("sans_rien_declare", "equipe")).toContain("opsys-metier equipes declarer");
    expect(brut("sans_rien_declare", "meteo")).toContain("opsys-metier meteo declarer");
    // Le message d'un profil invalide nomme le fichier du serveur lui-même.
    expect(brut("profils_illisibles", "equipe")).toContain("/srv/opsys/entreprise.yaml");
    expect(texteSansChemin(brut("profils_illisibles", "meteo"))).toBeNull();
  });

  test.each(SCENARIOS)("%s : la vue ne répète aucun texte de M4 (ni manque, ni détail d'un volet qui manque)", (nom) => {
    const brut = FIXTURE.reponses[nom].resultat.resultat as {
      volets: Record<string, { statut: string; manque: string | null; detail: string | null }>;
      a_fournir: { manque: string | null }[];
    };
    const vue = JSON.stringify(presenterPreparation(preparationDe(nom)));
    for (const volet of Object.values(brut.volets)) {
      if (volet.manque !== null) {
        expect(vue).not.toContain(volet.manque);
      }
    }
    for (const a of brut.a_fournir) {
      if (a.manque !== null) {
        expect(vue).not.toContain(a.manque);
      }
    }
  });

  describe.each(LANGUES)("ce que le propriétaire lit en %s", (_langue, ressources) => {
    test.each(SCENARIOS)("%s : aucun texte affiché ne cite un chemin du serveur, une commande ou un fichier de configuration", (nom) => {
      const vue = presenterPreparation(preparationDe(nom));
      const affiches: string[] = [];
      for (const volet of vue.volets) {
        for (const m of [volet.nom, volet.statut, volet.manque, volet.code]) {
          if (m !== null) {
            affiches.push(rendre(m, ressources));
          }
        }
        if (volet.detail !== null) {
          affiches.push(volet.detail);
        }
      }
      for (const a of vue.aFournir) {
        affiches.push(rendre(a.volet, ressources), rendre(a.manque, ressources));
      }
      expect(affiches.length).toBeGreaterThan(8);
      for (const texte of affiches) {
        expect({ scenario: nom, texte, sur: texteSansChemin(texte) === texte }).toEqual({ scenario: nom, texte, sur: true });
        expect(texte).not.toMatch(/\{\{|undefined|null/);
      }
    });
  });

  test("les (volet, statut, code) que M4 a dits dans ces scénarios sont tous dans la table de l'app", () => {
    const vus = new Set<string>();
    for (const nom of SCENARIOS) {
      for (const volet of preparationDe(nom).volets.filter((v) => v.statut !== "ok")) {
        vus.add(`${volet.nom}:${volet.statut}:${volet.detail ?? ""}`);
      }
    }
    expect([...vus].filter((cle) => !(cle in MANQUES_CONNUS)).sort()).toEqual([]);
    // Onze des quinze entrées se voient sur le moteur ; les autres (sans devis, position détruite, profil sans réglages
    // pour un lead v1...) sont prouvées par `tests/e2e/test_manques_m4_appareil.py` avec M4 lui-même.
    expect(vus.size).toBeGreaterThanOrEqual(12);
  });
});
