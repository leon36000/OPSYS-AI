import { lirePageLeads } from "../m2/listeLeads";
import type { FiltreLeads } from "../m2/listeLeads";
import { NON_CALCULABLES_FICTIFS, REGLES_FICTIVES, SEGMENT_URGENT, leadBrut, pageBrute } from "../vendeur/donneesDeTest";
import type { ResultatLeads } from "../vendeur/chargeurLeads";
import { demarrerLecture } from "../vendeur/lectureLeads";
import {
  basculerSegment,
  basculerStatut,
  etatSegment,
  lignesDeDonnee,
  listeVide,
  presenterLead,
  vueLeads,
} from "./leads";

const AUCUN: FiltreLeads = { statut: null, segment: null };

function lus(leads: Record<string, unknown>[], options: Parameters<typeof pageBrute>[0] extends infer O ? Partial<O> : never = {}) {
  const brute = pageBrute({ leads, ...options });
  return demarrerLecture(AUCUN, lirePageLeads(brute)!, brute, "2026-09-29T18:00:00.000Z")!;
}

describe("filtres", () => {
  test("toucher un statut le choisit, le retoucher revient à « tous »", () => {
    const qualifie = basculerStatut(AUCUN, "qualifie");
    expect(qualifie).toEqual({ statut: "qualifie", segment: null });
    expect(basculerStatut(qualifie, "qualifie")).toEqual(AUCUN);
    expect(basculerStatut(qualifie, "nouveau")).toEqual({ statut: "nouveau", segment: null });
  });

  test("statut et segment se combinent sans se toucher", () => {
    const les_deux = basculerSegment(basculerStatut(AUCUN, "qualifie"), "hot_lead");
    expect(les_deux).toEqual({ statut: "qualifie", segment: "hot_lead" });
    expect(basculerSegment(les_deux, "hot_lead")).toEqual({ statut: "qualifie", segment: null });
    expect(basculerStatut(les_deux, "qualifie")).toEqual({ statut: null, segment: "hot_lead" });
  });

  test("ne modifie jamais le filtre reçu", () => {
    const filtre = { statut: "nouveau", segment: null };
    basculerStatut(filtre, "qualifie");
    basculerSegment(filtre, "hot_lead");
    expect(filtre).toEqual({ statut: "nouveau", segment: null });
  });
});

describe("etatSegment — un segment non calculable est dit tel, avec ce qui manque", () => {
  test("M2 dit que le segment n'est calculable pour aucun lead : non calculable, manque X, tel quel", () => {
    expect(etatSegment("needs_photos", NON_CALCULABLES_FICTIFS)).toEqual({
      calculable: false,
      manque: "non calculable, manque l'état des photos du lead (M3 les qualifie, rien n'atteint M2)",
    });
    expect(etatSegment("dormant_lead", NON_CALCULABLES_FICTIFS)).toMatchObject({ calculable: false });
  });

  test("un segment que M2 ne cite pas parmi les non calculables est calculable", () => {
    expect(etatSegment("hot_lead", NON_CALCULABLES_FICTIFS)).toEqual({ calculable: true });
    expect(etatSegment("hot_lead", [])).toEqual({ calculable: true });
  });

  test("sans lecture encore : présumé calculable (le serveur refusera, et ce refus sera montré comme non calculable)", () => {
    expect(etatSegment("quote_sent", null)).toEqual({ calculable: true });
  });
});

describe("lignesDeDonnee", () => {
  test("une ligne par clé : le texte tel quel, le reste en JSON, rien d'abrégé", () => {
    expect(lignesDeDonnee({ statut: "converti", jours_ecoules: 12, urgence_declaree: true, autre: null })).toEqual([
      { cle: "statut", valeur: "converti" },
      { cle: "jours_ecoules", valeur: "12" },
      { cle: "urgence_declaree", valeur: "true" },
      { cle: "autre", valeur: "null" },
    ]);
    expect(lignesDeDonnee({})).toEqual([]);
  });
});

describe("presenterLead", () => {
  test("la carte : règle citée (énoncé du serveur) et donnée déclenchante, par segment", () => {
    const l = lus([leadBrut("lead-1", { urgence_declaree: true, segments: [SEGMENT_URGENT] })], { regles: REGLES_FICTIVES });
    const carte = presenterLead(l.leads[0], l.regles);
    expect(carte).toMatchObject({ leadId: "lead-1", statut: "qualifie", travaux: "renovation_totale", ville: "Repentigny", urgent: true });
    expect(carte.segments).toEqual([
      {
        segment: "hot_lead",
        regle: "urgence_declaree_lead_ouvert",
        enonce: REGLES_FICTIVES.urgence_declaree_lead_ouvert,
        donnee: [
          { cle: "urgence_declaree", valeur: "true" },
          { cle: "statut", valeur: "qualifie" },
        ],
      },
    ]);
  });

  test("l'énoncé d'une règle que le serveur n'a pas donné est absent (null), jamais inventé", () => {
    const l = lus([leadBrut("lead-1", { segments: [SEGMENT_URGENT] })], { regles: {} });
    expect(presenterLead(l.leads[0], l.regles).segments[0].enonce).toBeNull();
  });

  test("« urgent » seulement si l'urgence est déclarée : absente (null) ou fausse n'est pas urgent", () => {
    for (const urgence of [null, false]) {
      const l = lus([leadBrut("lead-1", { urgence_declaree: urgence })]);
      expect(presenterLead(l.leads[0], l.regles).urgent).toBe(false);
    }
  });

  test("les valeurs absentes restent absentes (null) ; le non calculable propre au lead est porté", () => {
    const l = lus([
      leadBrut("lead-1", { travaux: null, ville: null, derniere_activite: null, prochaine_action: null, non_calculables: [NON_CALCULABLES_FICTIFS[1]] }),
    ]);
    expect(presenterLead(l.leads[0], l.regles)).toMatchObject({
      travaux: null,
      ville: null,
      derniereActivite: null,
      prochaineAction: null,
      nonCalculables: [NON_CALCULABLES_FICTIFS[1]],
    });
  });
});

describe("vueLeads", () => {
  const liste = lus([leadBrut("lead-1")]);

  test("sans appairage : dit tel quel", () => {
    expect(vueLeads(null)).toEqual({ genre: "sans_appairage" });
  });

  test("lecture en ligne : la liste, sans mention de cache", () => {
    expect(vueLeads({ source: "serveur", lus: liste })).toEqual({ genre: "liste", lus: liste, cache: null });
  });

  test("cache hors ligne : la liste MARQUÉE comme cache, avec la date du cache et la raison", () => {
    const raison = { code: "erreur_reseau", detail: "Network request failed" };
    const resultat: ResultatLeads = { source: "cache", lus: liste, raisonHorsLigne: raison };
    expect(vueLeads(resultat)).toEqual({
      genre: "liste",
      lus: liste,
      cache: { misAJourLe: "2026-09-29T18:00:00.000Z", raison },
    });
  });

  test("le refus d'un segment non calculable est un segment non calculable, pas une erreur ni une liste vide", () => {
    const verdict = { code: "REJ-SEGMENT-NON-CALCULABLE", detail: "segment quote_sent : non calculable, manque le fait « devis envoyé »" };
    expect(vueLeads({ source: "refus", verdict })).toEqual({ genre: "segment_non_calculable", verdict });
  });

  test("un autre refus du serveur : son verdict, tel quel", () => {
    const verdict = { code: "REJ-IDENTITE-APPAREIL-INVALIDE", detail: "rôle retiré" };
    expect(vueLeads({ source: "refus", verdict })).toEqual({ genre: "refus", verdict });
  });

  test("ni serveur ni cache : aucune, avec la raison", () => {
    const raison = { code: "erreur_reseau", detail: "Network request failed" };
    expect(vueLeads({ source: "aucune", raison })).toEqual({ genre: "aucune", raison });
  });
});

describe("listeVide — « aucun lead » n'est dit que quand c'est vrai", () => {
  test("total 0, rien d'illisible ni d'indéterminé : vide", () => {
    expect(listeVide(lus([], { total: 0 }))).toBe(true);
  });

  test("des leads illisibles ou indéterminés : jamais « aucun lead »", () => {
    const mauvais = { ...leadBrut("x"), segments: "hot_lead" };
    const illisible = lus([mauvais], { total: 1 });
    expect(illisible.leads).toHaveLength(0);
    expect(illisible.illisibles).toBe(1);
    expect(listeVide(illisible)).toBe(false);
    expect(listeVide(lus([], { total: 0, indetermines: 2 }))).toBe(false);
  });
});
