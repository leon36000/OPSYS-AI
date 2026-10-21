import { lirePageLeads } from "../m2/listeLeads";
import type { FiltreLeads, LeadListe, PageLeads } from "../m2/listeLeads";
import { NON_CALCULABLES_FICTIFS, REGLES_FICTIVES, SEGMENT_URGENT, leadBrut, pageBrute } from "./donneesDeTest";
import type { OptionsPageBrute } from "./donneesDeTest";
import { cleFiltre, demarrerLecture, fusionnerPage, memeFiltre } from "./lectureLeads";

const AUCUN: FiltreLeads = { statut: null, segment: null };
const T0 = "2026-09-29T18:00:00.000Z";

function ids(prefixe: string, de: number, jusqua: number): Record<string, unknown>[] {
  return Array.from({ length: jusqua - de }, (_, i) => leadBrut(`${prefixe}-${String(de + i).padStart(2, "0")}`));
}

/** Une page brute ET sa lecture : le serveur les rend ensemble. */
function page(options: OptionsPageBrute): { brute: Record<string, unknown>; lue: PageLeads } {
  const brute = pageBrute(options);
  const lue = lirePageLeads(brute);
  if (lue === null) {
    throw new Error("page de test illisible");
  }
  return { brute, lue };
}

function premiere(options: OptionsPageBrute, filtre: FiltreLeads = AUCUN) {
  const { brute, lue } = page({ ...options, filtre });
  const lus = demarrerLecture(filtre, lue, brute, T0);
  if (lus === null) {
    throw new Error("première page refusée");
  }
  return lus;
}

describe("demarrerLecture", () => {
  test("la première page, avec le filtre demandé : lue telle quelle, brute gardée pour le cache", () => {
    const { brute, lue } = page({ leads: ids("a", 0, 3), total: 8, regles: REGLES_FICTIVES, nonCalculables: NON_CALCULABLES_FICTIFS });
    const lus = demarrerLecture(AUCUN, lue, brute, T0);
    expect(lus).toMatchObject({
      filtre: AUCUN,
      total: 8,
      suivant: 3,
      reste: 5,
      illisibles: 0,
      indetermines: 0,
      misAJourLe: T0,
      pagesBrutes: [brute],
    });
    expect(lus?.leads.map((l) => l.leadId)).toEqual(["a-00", "a-01", "a-02"]);
    expect(lus?.segmentsNonCalculables).toEqual(NON_CALCULABLES_FICTIFS);
    expect(lus?.regles).toEqual(REGLES_FICTIVES);
  });

  test("une page qui n'est pas la première (décalage 5) n'est pas une lecture de départ", () => {
    const { brute, lue } = page({ leads: ids("a", 5, 8), decalage: 5, total: 8 });
    expect(demarrerLecture(AUCUN, lue, brute, T0)).toBeNull();
  });

  test("le serveur a répondu pour un autre filtre : ce n'est pas la liste demandée", () => {
    const { brute, lue } = page({ leads: ids("a", 0, 2), filtre: { statut: "qualifie", segment: null } });
    expect(demarrerLecture(AUCUN, lue, brute, T0)).toBeNull();
    expect(demarrerLecture({ statut: "qualifie", segment: null }, lue, brute, T0)).not.toBeNull();
  });

  test("filtres : égalité et clé de cache distinctes pour chaque combinaison", () => {
    expect(memeFiltre(AUCUN, { statut: null, segment: null })).toBe(true);
    expect(memeFiltre(AUCUN, { statut: "nouveau", segment: null })).toBe(false);
    expect(cleFiltre(AUCUN)).toBe("*|*");
    expect(cleFiltre({ statut: "qualifie", segment: "hot_lead" })).toBe("qualifie|hot_lead");
    expect(cleFiltre({ statut: null, segment: "hot_lead" })).not.toBe(cleFiltre({ statut: "hot_lead", segment: null }));
  });
});

describe("fusionnerPage — la page demandée se recolle sans doublon ni trou", () => {
  test("pages lues bout à bout : 8 leads en 3 pages, dans l'ordre du serveur, chacun une fois", () => {
    let lus = premiere({ leads: ids("a", 0, 3), total: 8 });
    for (const [de, jusqua] of [
      [3, 6],
      [6, 8],
    ]) {
      const suite = page({ leads: ids("a", de, jusqua), decalage: de, total: 8 });
      const fusion = fusionnerPage(lus, suite.lue, suite.brute);
      expect(fusion.genre).toBe("fusionnee");
      if (fusion.genre !== "fusionnee") {
        return;
      }
      lus = fusion.lus;
    }
    expect(lus.leads.map((l: LeadListe) => l.leadId)).toEqual(
      Array.from({ length: 8 }, (_, i) => `a-${String(i).padStart(2, "0")}`),
    );
    expect(lus.suivant).toBeNull();
    expect(lus.reste).toBe(0);
    expect(lus.pagesBrutes).toHaveLength(3);
    expect(lus.misAJourLe).toBe(T0);
  });

  test("règles unies, non-calculables et indéterminés du dernier mot du serveur, illisibles cumulés", () => {
    const lus = premiere({ leads: ids("a", 0, 2), total: 4, regles: { r1: "règle un" } });
    const mauvais = { ...leadBrut("a-x"), segments: "hot_lead" };
    const suite = page({
      leads: [leadBrut("a-02"), mauvais],
      decalage: 2,
      total: 4,
      regles: { r2: "règle deux" },
      nonCalculables: NON_CALCULABLES_FICTIFS,
      indetermines: 3,
    });
    const fusion = fusionnerPage(lus, suite.lue, suite.brute);
    expect(fusion.genre === "fusionnee" && fusion.lus).toMatchObject({
      regles: { r1: "règle un", r2: "règle deux" },
      segmentsNonCalculables: NON_CALCULABLES_FICTIFS,
      indetermines: 3,
      illisibles: 1,
    });
  });

  test("la page n'est pas celle qu'on a demandée : relue depuis le début (incohérente)", () => {
    const lus = premiere({ leads: ids("a", 0, 3), total: 8 });
    const trop_loin = page({ leads: ids("a", 5, 8), decalage: 5, total: 8 });
    expect(fusionnerPage(lus, trop_loin.lue, trop_loin.brute)).toEqual({ genre: "a_relire", raison: "incoherente" });
    const deja_lue = page({ leads: ids("a", 0, 3), decalage: 0, total: 8 });
    expect(fusionnerPage(lus, deja_lue.lue, deja_lue.brute)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("rien ne suit : aucune page à recoller (incohérente), pas de recollage dans le vide", () => {
    const lus = premiere({ leads: ids("a", 0, 3), total: 3 });
    expect(lus.suivant).toBeNull();
    const suite = page({ leads: ids("a", 3, 4), decalage: 3, total: 4 });
    expect(fusionnerPage(lus, suite.lue, suite.brute)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("le filtre de la page diffère : incohérente", () => {
    const lus = premiere({ leads: ids("a", 0, 3), total: 8 }, { statut: "qualifie", segment: null });
    const suite = page({ leads: ids("a", 3, 6), decalage: 3, total: 8, filtre: { statut: "nouveau", segment: null } });
    expect(fusionnerPage(lus, suite.lue, suite.brute)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("suivant qui ne correspond pas au nombre de leads rendus : incohérente (un trou se cacherait)", () => {
    const lus = premiere({ leads: ids("a", 0, 3), total: 9 });
    const suite = page({ leads: ids("a", 3, 5), decalage: 3, total: 9, reste: 4, suivant: 7 });
    expect(fusionnerPage(lus, suite.lue, suite.brute)).toEqual({ genre: "a_relire", raison: "incoherente" });
  });

  test("le total a changé entre deux pages : la liste a changé, relue depuis le début", () => {
    const lus = premiere({ leads: ids("a", 0, 3), total: 8 });
    const suite = page({ leads: ids("a", 3, 6), decalage: 3, total: 9 });
    expect(fusionnerPage(lus, suite.lue, suite.brute)).toEqual({ genre: "a_relire", raison: "liste_changee" });
  });

  test("un lead de la page est déjà affiché (les rangs ont glissé) : la liste a changé", () => {
    const lus = premiere({ leads: ids("a", 0, 3), total: 8 });
    const suite = page({ leads: [leadBrut("a-02"), leadBrut("a-03"), leadBrut("a-04")], decalage: 3, total: 8 });
    expect(fusionnerPage(lus, suite.lue, suite.brute)).toEqual({ genre: "a_relire", raison: "liste_changee" });
  });

  test("les leads lus ne sont jamais modifiés en place (l'état de l'écran reste intact)", () => {
    const lus = premiere({ leads: [leadBrut("a-00", { segments: [SEGMENT_URGENT] })], total: 2 });
    const avant = JSON.stringify(lus);
    const suite = page({ leads: [leadBrut("a-01")], decalage: 1, total: 2 });
    fusionnerPage(lus, suite.lue, suite.brute);
    expect(JSON.stringify(lus)).toBe(avant);
  });
});
