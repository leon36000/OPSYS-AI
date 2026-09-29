import { STATUTS_DE_VOLET, VOLETS_DE_PREPARATION } from "../m4/dispatch";
import enCA from "../i18n/locales/en-CA";
import frCA from "../i18n/locales/fr-CA";
import { direLeManque, MANQUES_CONNUS } from "./manquesM4";
import { jetonSur, texteSansChemin } from "./texteSur";

const LANGUES = [
  ["fr-CA", frCA],
  ["en-CA", enCA],
] as const;

type Arbre = { readonly [cle: string]: Arbre | string };

function resoudre(ressources: unknown, chemin: string): unknown {
  return chemin.split(".").reduce<unknown>((noeud, segment) => (typeof noeud === "object" && noeud !== null ? (noeud as Arbre)[segment] : undefined), ressources);
}

/** Toutes les feuilles d'un arbre de textes, en `chemin -> texte`. */
function feuilles(noeud: unknown, chemin: string): Record<string, string> {
  if (typeof noeud === "string") {
    return { [chemin]: noeud };
  }
  return Object.entries(noeud as Arbre).reduce<Record<string, string>>((acc, [nom, enfant]) => ({ ...acc, ...feuilles(enfant, `${chemin}.${nom}`) }), {});
}

const ENTREES = Object.entries(MANQUES_CONNUS).map(([cle, texte]) => {
  const [volet, statut, code] = cle.split(":");
  return { cle, volet, statut, code, texte };
});

describe("la table des manques que M4 sait dire", () => {
  test("chaque entrée est « volet:statut:code », d'un volet et d'un statut que l'app connaît, jamais « ok »", () => {
    expect(ENTREES.length).toBeGreaterThan(10);
    for (const entree of ENTREES) {
      expect({ cle: entree.cle, parties: entree.cle.split(":").length }).toEqual({ cle: entree.cle, parties: 3 });
      expect({ cle: entree.cle, volet: (VOLETS_DE_PREPARATION as readonly string[]).includes(entree.volet) }).toEqual({ cle: entree.cle, volet: true });
      expect({ cle: entree.cle, statut: (STATUTS_DE_VOLET as readonly string[]).includes(entree.statut) }).toEqual({ cle: entree.cle, statut: true });
      expect(entree.statut).not.toBe("ok");
      // Un code est vide (un manque qui n'en a pas) ou un jeton sûr : c'est lui que l'écran affiche.
      expect({ cle: entree.cle, code: entree.code === "" || jetonSur(entree.code) === entree.code }).toEqual({ cle: entree.cle, code: true });
    }
  });

  test("aucune clé en double : la table est une correspondance, pas une liste d'essais", () => {
    expect(new Set(ENTREES.map((e) => e.cle)).size).toBe(ENTREES.length);
  });

  test.each(LANGUES)("(%s) chaque entrée pointe un texte qui existe, sans variable, sans chemin ni commande", (_langue, ressources) => {
    for (const entree of ENTREES) {
      const texte = resoudre(ressources, `admin.chantiers.manques.${entree.texte}`);
      expect({ cle: entree.cle, texte: typeof texte }).toEqual({ cle: entree.cle, texte: "string" });
      expect(texte).not.toMatch(/\{\{/);
      expect({ cle: entree.cle, sur: texteSansChemin(texte as string) === texte }).toEqual({ cle: entree.cle, sur: true });
    }
  });

  test.each(LANGUES)("(%s) aucun texte mort : chaque phrase de `manques` est celle d'une entrée, du code ou de l'inconnu", (_langue, ressources) => {
    const toutes = Object.keys(feuilles(resoudre(ressources, "admin.chantiers.manques"), "")).map((chemin) => chemin.slice(1));
    const utilisees = new Set([...ENTREES.map((e) => e.texte), "code", "inconnu"]);
    expect(toutes.filter((chemin) => !utilisees.has(chemin)).sort()).toEqual([]);
    expect([...utilisees].filter((chemin) => !toutes.includes(chemin)).sort()).toEqual([]);
  });

  test.each(LANGUES)("(%s) les phrases de « code » et « inconnu » ne prennent que le code", (_langue, ressources) => {
    expect(resoudre(ressources, "admin.chantiers.manques.code")).toContain("{{code}}");
    expect(resoudre(ressources, "admin.chantiers.manques.inconnu")).toContain("{{code}}");
    for (const cle of ["code", "inconnu"]) {
      const variables = [...String(resoudre(ressources, `admin.chantiers.manques.${cle}`)).matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]);
      expect(variables).toEqual(["code"]);
    }
  });

  test("« à configurer côté serveur » et son code se lisent, en français comme en anglais", () => {
    expect(resoudre(frCA, "admin.chantiers.manques.inconnu")).toMatch(/configurer côté serveur/);
    expect(resoudre(enCA, "admin.chantiers.manques.inconnu")).toMatch(/set up on the server/);
  });
});

describe("direLeManque : ce qu'il faut faire, jamais le texte de M4", () => {
  test.each(ENTREES)("$cle : une phrase connue, et son code seulement s'il en a un", ({ volet, statut, code, texte }) => {
    const dit = direLeManque({ nom: volet, statut, detail: code === "" ? null : code });
    expect(dit).toEqual({
      texte: { cle: `admin.chantiers.manques.${texte}` },
      code: code === "" ? null : { cle: "admin.chantiers.manques.code", params: { code } },
      connu: true,
    });
  });

  test("le détail d'un volet sans code (« aucune équipe admissible ») est une phrase de M4 : il ne sert pas de code", () => {
    const dit = direLeManque({ nom: "equipe", statut: "manque", detail: "aucune équipe admissible : compétences insuffisantes" });
    expect(dit.connu).toBe(false);
    expect(dit.code).toBeNull();
    expect(dit.texte).toEqual({ cle: "admin.chantiers.manques.inconnu", params: { code: "equipe/manque" } });
  });

  test("un code que la table ne connaît pas : « à configurer côté serveur » avec ce code", () => {
    const dit = direLeManque({ nom: "equipe", statut: "manque", detail: "REJ-NOUVEAU-MANQUE" });
    expect(dit).toEqual({
      texte: { cle: "admin.chantiers.manques.inconnu", params: { code: "REJ-NOUVEAU-MANQUE" } },
      code: { cle: "admin.chantiers.manques.code", params: { code: "REJ-NOUVEAU-MANQUE" } },
      connu: false,
    });
  });

  test("un statut de volet que la table ne connaît pas pour ce code : inconnu, jamais la phrase d'un autre statut", () => {
    // « partiel » est connu pour le matériel « manque » ; pour la météo, ou sous un autre statut, il ne l'est pas.
    expect(direLeManque({ nom: "meteo", statut: "manque", detail: "partiel" }).connu).toBe(false);
    expect(direLeManque({ nom: "materiel", statut: "non_verifiable", detail: "partiel" }).connu).toBe(false);
    expect(direLeManque({ nom: "materiel", statut: "manque", detail: "partiel" }).connu).toBe(true);
  });

  test("un volet que l'app ne connaît pas, sans code : son nom et son statut, jamais son texte", () => {
    const dit = direLeManque({ nom: "assurance", statut: "manque", detail: null });
    expect(dit.texte).toEqual({ cle: "admin.chantiers.manques.inconnu", params: { code: "assurance/manque" } });
    expect(dit.code).toBeNull();
  });

  test.each([
    ["un chemin du serveur", "/srv/opsys/entreprise.yaml"],
    ["une commande", "opsys-metier equipes declarer --par moi"],
    ["un nom de fichier", "entreprise.yaml"],
    ["une phrase", "déclare les équipes puis écris le fichier"],
    ["un texte vide", ""],
  ])("%s en guise de code n'est jamais montré", (_nom, detail) => {
    const dit = direLeManque({ nom: "equipe", statut: "manque", detail });
    expect(dit.connu).toBe(false);
    expect(dit.code).toBeNull();
    expect(JSON.stringify(dit)).not.toMatch(/srv|opsys-metier|entreprise|déclare|fichier/);
  });

  test("un nom ou un statut qui n'est pas un jeton est remplacé par « ? » : rien du serveur n'est répété tel quel", () => {
    const dit = direLeManque({ nom: "/srv/x", statut: "écris `cmd`", detail: null });
    expect(dit.texte).toEqual({ cle: "admin.chantiers.manques.inconnu", params: { code: "?/?" } });
  });

  test("un « : » dans le nom ou le statut ne se confond jamais avec une entrée de la table", () => {
    for (const entree of ENTREES) {
      const morceaux = [entree.volet, entree.statut, entree.code];
      // Toutes les façons de déplacer un « : » d'un morceau à l'autre donnent la même clé recomposée : elle ne doit pas gagner.
      const dit = direLeManque({ nom: `${morceaux[0]}:${morceaux[1]}`, statut: "", detail: entree.code === "" ? null : entree.code });
      expect({ cle: entree.cle, connu: dit.connu }).toEqual({ cle: entree.cle, connu: false });
    }
  });

  test("le résultat ne porte que la phrase, le code et « connu » : le texte de M4 n'y a pas de place", () => {
    const dit = direLeManque({ nom: "equipe", statut: "manque", detail: "REJ-EQUIPES-NON-CONFIGUREES" });
    expect(Object.keys(dit).sort()).toEqual(["code", "connu", "texte"]);
  });
});
