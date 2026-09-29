import fs from "node:fs";
import path from "node:path";

import { fusionnerPagePrevision } from "../m5/pagesPrevision";
import { COMPOSANTES_DU_CASH_LIBRE, FREQUENCES_FISCALES, STATUTS_ALERTE_PREVISION, STATUTS_ECHEANCE, VALIDATIONS_CPA } from "../m5/tresorerie";
import type { PrevisionTresorerie } from "../m5/tresorerie";
import {
  STATUTS_DE_VOLET,
  STATUTS_DU_DISPATCH,
  TYPES_DE_DEMANDE_DE_REVUE,
  VERDICTS_DE_PREPARATION,
  VOLETS_DE_PREPARATION,
} from "../m4/dispatch";
import { SENS_DE_SEUIL, STATUTS_SEUIL_EVALUE, UNITES_CONNUES } from "../m8/vueExecutive";
import { presenterAVoir, vueAccueil } from "../ecrans/admin";
import { message, presenterSection } from "../ecrans/adminCommun";
import { presenterGroupes, presenterDigest, presenterPreparation } from "../ecrans/chantiers";
import {
  decisionSuitePrevision,
  presenterEcheances,
  presenterPrevision,
  presenterTresorerie,
} from "../ecrans/chiffres";
import {
  aVoirDe,
  digestDe,
  duCache,
  duServeur,
  echeancesDe,
  interventionsDe,
  preparationDe,
  previsionDe,
  tresorerieDe,
  vueExecutiveDe,
} from "../ecrans/donneesDeVue";
import { presenterVueExecutive } from "../ecrans/vueExecutive";
import enCA from "../i18n/locales/en-CA";
import frCA from "../i18n/locales/fr-CA";

/**
 * Les textes du profil admin (`admin.*`, PLAN T4.20) : les mêmes clés et les mêmes variables en fr-CA et en en-CA, les
 * catalogues de libellés ÉPINGLÉS à ceux du serveur, et — le test qui compte — chaque texte que les modèles de vue
 * PRODUISENT (toutes les réponses réelles du moteur y passent) existe dans les deux langues avec exactement les variables
 * qu'il reçoit. Un texte manquant, une variable oubliée ou mal orthographiée se verrait à l'écran comme « {{montant}} ».
 */

const LANGUES = [
  ["fr-CA", frCA],
  ["en-CA", enCA],
] as const;

type Arbre = { readonly [cle: string]: Arbre | string };

/** Aplatit un arbre de textes en `chemin -> texte`. */
function aplatir(noeud: unknown, chemin = ""): Record<string, string> {
  if (typeof noeud === "string") {
    return { [chemin]: noeud };
  }
  if (typeof noeud === "object" && noeud !== null) {
    return Object.entries(noeud).reduce<Record<string, string>>(
      (acc, [cle, valeur]) => ({ ...acc, ...aplatir(valeur, chemin === "" ? cle : `${chemin}.${cle}`) }),
      {},
    );
  }
  return {};
}

const marques = (texte: string): string[] => (texte.match(/\{\{\s*\w+\s*\}\}/g) ?? []).map((m) => m.replace(/[{}\s]/g, "")).sort();

function resoudre(arbre: unknown, cle: string): unknown {
  return cle.split(".").reduce<unknown>((noeud, morceau) => {
    return typeof noeud === "object" && noeud !== null && Object.prototype.hasOwnProperty.call(noeud, morceau)
      ? (noeud as Arbre)[morceau]
      : undefined;
  }, arbre);
}

// ---------------------------------------------------------------------------------------------------------------------
// Les catalogues
// ---------------------------------------------------------------------------------------------------------------------
const CATALOGUES: readonly (readonly [string, readonly string[]])[] = [
  ["admin.chiffres.composantes", ["solde", ...COMPOSANTES_DU_CASH_LIBRE]],
  ["admin.chiffres.alerte.statuts", STATUTS_ALERTE_PREVISION],
  ["admin.chiffres.echeances.statuts", STATUTS_ECHEANCE],
  ["admin.chiffres.echeances.frequences", FREQUENCES_FISCALES],
  ["admin.chiffres.echeances.validations", VALIDATIONS_CPA],
  ["admin.chiffres.vue.seuilStatuts", STATUTS_SEUIL_EVALUE],
  ["admin.chiffres.vue.sens", SENS_DE_SEUIL],
  ["admin.unites", [...UNITES_CONNUES, "autre"]],
  ["admin.chantiers.statuts", STATUTS_DU_DISPATCH],
  ["admin.chantiers.volets", VOLETS_DE_PREPARATION],
  ["admin.chantiers.statutsDeVolet", STATUTS_DE_VOLET],
  ["admin.chantiers.verdicts", VERDICTS_DE_PREPARATION],
  ["admin.chantiers.typesDeRevue", TYPES_DE_DEMANDE_DE_REVUE],
  // Les issues de « Voir plus » : les deux raisons de relire (`RaisonRelecturePrevision`), un refus et un échec.
  ["admin.chiffres.prevision.suite", ["prevision_changee", "incoherente", "refus", "echec"]],
];

describe.each(LANGUES)("textes du profil admin (%s)", (_langue, ressources) => {
  const textes = aplatir(ressources.admin);

  test("aucun texte vide", () => {
    for (const [chemin, texte] of Object.entries(textes)) {
      expect(`${chemin}: ${texte.trim()}`).not.toBe(`${chemin}: `);
    }
  });

  test.each(CATALOGUES)("le catalogue %s a exactement les valeurs du serveur (rien en trop, rien en moins)", (chemin, valeurs) => {
    const catalogue = resoudre(ressources, chemin);
    expect(typeof catalogue).toBe("object");
    expect(Object.keys(catalogue as Arbre).sort()).toEqual([...valeurs].sort());
    for (const valeur of valeurs) {
      const texte = (catalogue as Arbre)[valeur];
      expect(typeof texte === "string" ? texte.trim() : "").not.toBe("");
    }
  });

  test("un refus, une copie et une absence disent le code et le détail du serveur, ou la date et la raison", () => {
    expect(ressources.admin.commun.cache).toContain("{{date}}");
    expect(ressources.admin.commun.cache).toContain("{{code}}");
    for (const cle of ["refus", "aucune"] as const) {
      expect(ressources.admin.commun[cle]).toContain("{{code}}");
      expect(ressources.admin.commun[cle]).toContain("{{detail}}");
    }
    expect(ressources.admin.commun.manqueLigne).toContain("{{code}}");
    expect(ressources.admin.commun.manqueLigne).toContain("{{detail}}");
  });

  test("« non calculable » et « à configurer » sont dits en toutes lettres, jamais par un tiret ou un zéro", () => {
    const paires: readonly (readonly [string, RegExp])[] = [
      ["chiffres.composante.nonCalculable", /calculable/i],
      ["chiffres.cashLibre.nonCalculable", /calculable/i],
      ["chiffres.tresorerie.soldeInconnu", /calculable/i],
      ["chiffres.prevision.nonCalculable", /calculable/i],
      ["chiffres.prevision.semaineNonCalculable", /calculable/i],
      ["chiffres.vue.mesureNonCalculable", /calculable/i],
      ["chiffres.vue.margeNonCalculable", /calculable/i],
      ["chiffres.vue.seuilsAConfigurer", /(configur)/i],
      ["chiffres.alerte.statuts.SEUIL_A_CONFIGURER", /(configur)/i],
    ];
    for (const [cle, motif] of paires) {
      expect(textes[cle]).toMatch(motif);
    }
  });
});

describe("fr-CA et en-CA disent la même chose", () => {
  const fr = aplatir(frCA.admin);
  const en = aplatir(enCA.admin);

  test("les mêmes clés", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(fr).sort());
  });

  test("les mêmes variables d'interpolation, clé par clé", () => {
    for (const chemin of Object.keys(fr)) {
      expect({ chemin, marques: marques(en[chemin]) }).toEqual({ chemin, marques: marques(fr[chemin]) });
    }
  });
});

// ---------------------------------------------------------------------------------------------------------------------
// Tout ce que les modèles de vue produisent
// ---------------------------------------------------------------------------------------------------------------------
interface MessageTrouve {
  readonly cle: string;
  readonly params: Record<string, unknown> | undefined;
  readonly ou: string;
}

/** Les options que i18next lit dans le second argument de `t` : une variable qui porterait l'un de ces noms serait avalée. */
const NOMS_RESERVES = new Set([
  "count",
  "context",
  "ordinal",
  "ns",
  "lng",
  "lngs",
  "fallbackLng",
  "defaultValue",
  "replace",
  "returnObjects",
  "returnDetails",
  "joinArrays",
  "postProcess",
  "interpolation",
  "skipInterpolation",
  "keySeparator",
  "nsSeparator",
]);

function collecter(valeur: unknown, ou: string, sortie: MessageTrouve[]): void {
  if (Array.isArray(valeur)) {
    valeur.forEach((element, index) => collecter(element, `${ou}[${index}]`, sortie));
    return;
  }
  if (typeof valeur !== "object" || valeur === null) {
    return;
  }
  const objet = valeur as Record<string, unknown>;
  // Un Message n'a que `cle` (et `params`) : un objet qui a une propriété `cle` ET d'autres (une échéance, une attente) n'en est pas un.
  const cle = objet.cle;
  const estUnMessage =
    typeof cle === "string" &&
    Object.keys(objet).every((nom) => nom === "cle" || nom === "params") &&
    (objet.params === undefined || (typeof objet.params === "object" && objet.params !== null));
  if (estUnMessage) {
    sortie.push({ cle, params: objet.params as Record<string, unknown> | undefined, ou });
    return;
  }
  for (const [nom, element] of Object.entries(objet)) {
    collecter(element, `${ou}.${nom}`, sortie);
  }
}

function tousLesMessages(): MessageTrouve[] {
  const sortie: MessageTrouve[] = [];
  const langues = ["fr-CA", "en-CA"] as const;
  const decalages = [-240, 0];
  for (const langue of langues) {
    for (const decalage of decalages) {
      for (const nom of ["tresorerie", "tresorerie_sans_solde", "tresorerie_sans_paies"]) {
        collecter(presenterTresorerie(tresorerieDe(nom), langue, decalage), `tresorerie:${nom}:${langue}`, sortie);
      }
      for (const nom of [
        "prevision",
        "prevision_sans_seuil",
        "prevision_sans_paies",
        "prevision_sans_alerte",
        "prevision_longue_page_1",
        "prevision_longue_page_2",
      ]) {
        collecter(presenterPrevision(previsionDe(nom), langue, decalage), `prevision:${nom}:${langue}`, sortie);
      }
      for (const nom of ["echeances", "echeances_en_retard"]) {
        collecter(presenterEcheances(echeancesDe(nom), langue), `echeances:${nom}:${langue}`, sortie);
      }
      for (const nom of ["vue_executive", "vue_executive_vide"]) {
        collecter(presenterVueExecutive(vueExecutiveDe(nom), langue, decalage), `vue:${nom}:${langue}`, sortie);
      }
    }
  }
  const premiere = previsionDe("prevision_longue_page_1");
  const seconde = previsionDe("prevision_longue_page_2");
  if (premiere.genre === "prevision") {
    const fusion = fusionnerPagePrevision(premiere as PrevisionTresorerie, seconde);
    if (fusion.genre === "fusionnee") {
      collecter(presenterPrevision(fusion.prevision, "fr-CA", -240), "prevision:fusionnee", sortie);
    }
  }
  collecter(presenterPrevision({ genre: "masquee", role: "employee", horizonSemaines: 6, mention: "m" }, "fr-CA", -240), "prevision:masquee", sortie);
  const groupes = STATUTS_DU_DISPATCH.map((statut) => ({ statut, resultat: duServeur(interventionsDe(`interventions_${statut}`, statut)) }));
  collecter(presenterGroupes(groupes, -240), "chantiers:groupes", sortie);
  collecter(
    presenterGroupes(
      [
        { statut: "planifiee", resultat: { source: "aucune", raison: { code: "reponse_tronquee", detail: "d" } } },
        { statut: "sur_site", resultat: { source: "refus", verdict: { code: "c", detail: "d" } } },
        { statut: "reportee", resultat: duCache(interventionsDe("interventions_planifiee", "planifiee")) },
        { statut: "annulee", resultat: duServeur({ statut: "annulee", interventions: [], illisibles: 3 }) },
      ],
      -240,
    ),
    "chantiers:groupes-degrades",
    sortie,
  );
  for (const nom of ["digest", "digest_vide"]) {
    collecter(presenterDigest(digestDe(nom), -240), `chantiers:${nom}`, sortie);
  }
  for (const nom of ["preparation_lead_v2", "preparation_lead_v1", "preparation_a_planifier"]) {
    collecter(presenterPreparation(preparationDe(nom)), `chantiers:${nom}`, sortie);
  }
  for (const nom of ["a_voir_vide", "a_voir", "a_voir_avec_demande"]) {
    collecter(presenterAVoir(aVoirDe(nom), -240), `aVoir:${nom}`, sortie);
  }
  const liste = aVoirDe("a_voir_avec_demande");
  collecter(presenterAVoir({ ...liste, illisibles: 2, reste: 3 }, -240), "aVoir:demandes-degradees", sortie);
  collecter(
    presenterAVoir(
      {
        ...liste,
        attentes: { items: [], total: 1, reste: 2, decalage: 0, suivant: 0, illisibles: 1, departementsIllisibles: ["m05-financecore"] },
      },
      -240,
    ),
    "aVoir:attentes-degradees",
    sortie,
  );
  collecter(presenterAVoir({ ...liste, attentes: null }, -240), "aVoir:attentes-inconnues", sortie);
  collecter(vueAccueil(duCache(liste), -240), "aVoir:cache", sortie);
  collecter(vueAccueil({ source: "refus", verdict: { code: "c", detail: "d" } }, -240), "aVoir:refus", sortie);
  collecter(presenterSection({ source: "aucune", raison: { code: "c", detail: "d" } }, -240, () => null), "section:aucune", sortie);
  for (const suite of [
    { genre: "a_relire", raison: "prevision_changee" },
    { genre: "a_relire", raison: "incoherente" },
    { genre: "refus", verdict: { code: "c", detail: "d" } },
    { genre: "echec", verdict: { code: "c", detail: "d" } },
  ] as const) {
    collecter(decisionSuitePrevision(suite), `suite:${suite.genre}`, sortie);
  }
  collecter(message("admin.commun.inconnu", { valeur: "x" }), "inconnu", sortie);
  return sortie;
}

describe("chaque texte que les modèles de vue produisent existe dans les deux langues, avec exactement ses variables", () => {
  const messages = tousLesMessages();
  const cles = [...new Set(messages.map((m) => m.cle))].sort();

  test("les modèles de vue produisent bien des textes, de chaque partie de l'écran", () => {
    expect(messages.length).toBeGreaterThan(400);
    for (const partie of ["admin.aVoir", "admin.chiffres.tresorerie", "admin.chiffres.prevision", "admin.chiffres.echeances", "admin.chiffres.vue", "admin.chantiers", "admin.commun", "admin.unites", "approvals"]) {
      expect(cles.some((cle) => cle.startsWith(`${partie}.`))).toBe(true);
    }
  });

  test.each(LANGUES)("(%s) chaque clé produite est un texte, et ses variables sont exactement celles qu'elle reçoit", (_langue, ressources) => {
    for (const cle of cles) {
      const texte = resoudre(ressources, cle);
      expect({ cle, texte: typeof texte }).toEqual({ cle, texte: "string" });
      for (const message of messages.filter((m) => m.cle === cle)) {
        const attendues = Object.keys(message.params ?? {}).sort();
        expect({ cle, ou: message.ou, variables: marques(texte as string) }).toEqual({ cle, ou: message.ou, variables: attendues });
      }
    }
  });

  test("chaque variable a une valeur (texte ou nombre) : jamais « undefined » ni un objet à l'écran", () => {
    for (const trouve of messages) {
      for (const [nom, valeur] of Object.entries(trouve.params ?? {})) {
        expect({ cle: trouve.cle, ou: trouve.ou, nom, genre: typeof valeur }).toEqual({
          cle: trouve.cle,
          ou: trouve.ou,
          nom,
          genre: typeof valeur === "number" ? "number" : "string",
        });
        if (typeof valeur === "number") {
          expect(Number.isFinite(valeur)).toBe(true);
        }
      }
    }
  });

  test("aucune variable ne porte le nom d'une option de i18next (elle serait avalée, ou changerait la clé lue)", () => {
    for (const trouve of messages) {
      for (const nom of Object.keys(trouve.params ?? {})) {
        expect({ cle: trouve.cle, nom, reserve: NOMS_RESERVES.has(nom) }).toEqual({ cle: trouve.cle, nom, reserve: false });
      }
    }
  });
});

// ---------------------------------------------------------------------------------------------------------------------
// Les clés nommées dans les sources (branches que la fixture n'exerce pas, écrans)
// ---------------------------------------------------------------------------------------------------------------------
const RACINE = path.join(__dirname, "..", "..");

function sansCommentaires(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/(?<=[;,{}()\s])\/\/[^\n"'`]*$/gm, "");
}

const SOURCES_AVEC_TEXTES = [
  "src/ecrans/admin.ts",
  "src/ecrans/adminCommun.ts",
  "src/ecrans/chiffres.ts",
  "src/ecrans/vueExecutive.ts",
  "src/ecrans/chantiers.ts",
  "src/admin/composants.tsx",
  "src/admin/vuesChiffres.tsx",
  "app/(admin)/admin.tsx",
  "app/(admin)/chiffres.tsx",
  "app/(admin)/chantiers.tsx",
];

describe("les clés i18n nommées dans les sources existent dans les deux langues", () => {
  test.each(SOURCES_AVEC_TEXTES)("%s", (fichier) => {
    const source = sansCommentaires(fs.readFileSync(path.join(RACINE, fichier), "utf8"));
    const litterales = [...source.matchAll(/["'](admin\.[A-Za-z0-9_.]+|approvals\.[A-Za-z0-9_.]+)["']/g)].map((m) => m[1]);
    const catalogues = [...source.matchAll(/`((?:admin|approvals)\.[A-Za-z0-9_.]*?)\.?\$\{/g)].map((m) => m[1]);
    const prefixes = [...source.matchAll(/libelleDeCatalogue\(\s*["']([A-Za-z0-9_.]+)["']/g)].map((m) => m[1]);
    for (const [, ressources] of LANGUES) {
      for (const cle of litterales) {
        const trouve = resoudre(ressources, cle);
        expect({ fichier, cle, genre: typeof trouve === "string" || typeof trouve === "object" ? "present" : "absent" }).toEqual({
          fichier,
          cle,
          genre: "present",
        });
      }
      for (const prefixe of [...catalogues, ...prefixes]) {
        expect({ fichier, prefixe, genre: typeof resoudre(ressources, prefixe) }).toEqual({ fichier, prefixe, genre: "object" });
      }
    }
  });

  test("les `t(...)` des écrans n'ont pas de variables : tout texte à variables vient d'un modèle de vue, testé ci-dessus", () => {
    for (const fichier of ["app/(admin)/admin.tsx", "app/(admin)/chiffres.tsx", "app/(admin)/chantiers.tsx", "src/admin/vuesChiffres.tsx", "src/admin/composants.tsx"]) {
      const source = sansCommentaires(fs.readFileSync(path.join(RACINE, fichier), "utf8"));
      const appels = [...source.matchAll(/\bt\(\s*([^)]*)\)/g)].map((m) => m[1]);
      for (const appel of appels) {
        // `t("cle")` (statique) ou `t(m.cle, m.params as ...)` (message d'un modèle de vue) ; jamais `t("cle", { ... })`.
        expect({ fichier, appel, variablesEnLigne: /["'`]\s*,\s*\{/.test(appel) }).toEqual({ fichier, appel, variablesEnLigne: false });
      }
    }
  });
});
