import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import { OUTIL_LISTER_DEMANDES } from "../approbations/chargeur";
import { lireCacheSection } from "./cache";
import { config, enveloppeEnErreur, fauxTransport, reponse, transportEnEchec, transportHorsLigne } from "./donneesDeTest";
import { creerChargeurAVoir, epurerPourLeCache, interpreterAVoir, SECTION_A_VOIR } from "./aVoir";

function serveur(nom: string) {
  return fauxTransport({ [OUTIL_LISTER_DEMANDES]: () => reponse(nom) });
}

describe("l'accueil « À voir » : les demandes en attente et les attentes des départements", () => {
  test("la lecture en ligne : trois attentes de la première page, la suite comptée, aucune demande, le propriétaire", async () => {
    const lu = await creerChargeurAVoir(config(serveur("a_voir"))).chargerAVoir();

    expect(lu.source).toBe("serveur");
    if (lu.source !== "serveur") {
      return;
    }
    const liste = lu.valeur;
    expect(liste).toMatchObject({ totalEnAttente: 0, reste: 0, proprietaire: true, illisibles: 0 });
    expect(liste.attentes).toMatchObject({ total: 7, reste: 4, suivant: 3, decalage: 0 });
    expect(liste.attentes?.items.map((a) => a.type)).toEqual(["facture_brouillon", "chantier_a_reviser", "completion_en_revue"]);
    expect(liste.attentes?.items[2]).toMatchObject({ niveau: "N4", departementNom: "Field Ops" });
  });

  test("l'appel : le nom nu, aucun argument (la première page), rien qui désigne une personne", async () => {
    const transport = serveur("a_voir");
    await creerChargeurAVoir(config(transport)).chargerAVoir();
    expect(transport.mock.calls[0][0].requete).toEqual({ tool: "m9_lister_demandes_approbation", args: {} });
    expect(SECTION_A_VOIR.cache).toBe("a_voir");
  });

  test("une demande en attente : son outil, son niveau, son département ; hors ligne, elle est relue du cache SANS ses arguments", async () => {
    const depot = new DepotCleValeurMemoire();
    const en_ligne = await creerChargeurAVoir(config(serveur("a_voir_avec_demande"), { depot })).chargerAVoir();
    expect(en_ligne.source === "serveur" && en_ligne.valeur.demandes[0]).toMatchObject({
      outil: "m4_resoudre_revue_completion",
      niveau: "N4",
      departementNom: "Field Ops",
      decidable: true,
    });
    expect(en_ligne.source === "serveur" && en_ligne.valeur.demandes[0].arguments).toMatchObject({ decision: "verifiee" });

    // Ce que le cache garde : ni arguments, ni motif, ni description d'outil (l'accueil ne les montre pas).
    const gardee = JSON.stringify(await lireCacheSection(depot, "nathan", "a_voir"));
    expect(gardee).not.toContain("Bris de 16 pi");
    expect(gardee).not.toContain("Revue HUMAINE d'une complétion");
    expect(gardee).toContain("m4_resoudre_revue_completion");

    const hors_ligne = await creerChargeurAVoir(config(transportHorsLigne(), { depot })).chargerAVoir();
    expect(hors_ligne.source).toBe("cache");
    if (hors_ligne.source !== "cache") {
      return;
    }
    expect(hors_ligne.raisonHorsLigne).toEqual({ code: "erreur_reseau", detail: "Network request failed" });
    expect(hors_ligne.misAJourLe).toBe("2026-09-29T18:03:22.000Z");
    expect(hors_ligne.valeur.demandes[0]).toMatchObject({
      id: en_ligne.source === "serveur" ? en_ligne.valeur.demandes[0].id : "",
      outil: "m4_resoudre_revue_completion",
      niveau: "N4",
      arguments: null,
    });
    expect(hors_ligne.valeur.demandes[0].id).toMatch(/^[0-9a-f]{12}$/);
    expect(hors_ligne.valeur.demandes[0].descriptionOutil).toBeNull();
    expect(hors_ligne.valeur.demandes[0].motifDemande).toBeNull();
    // Les attentes des départements, elles, sont gardées telles quelles (des résumés, sans donnée personnelle).
    expect(hors_ligne.valeur.attentes?.items.map((a) => a.resume)).toEqual(
      en_ligne.source === "serveur" ? en_ligne.valeur.attentes?.items.map((a) => a.resume) : [],
    );
  });

  test("le cache de l'accueil est celui de la PERSONNE : une autre personne du même téléphone ne le relit pas", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurAVoir(config(serveur("a_voir"), { depot })).chargerAVoir();
    const autre = await creerChargeurAVoir(config(transportHorsLigne(), { depot, personne: "sophie" })).chargerAVoir();
    expect(autre.source).toBe("aucune");
  });

  test("un refus de la porte (403) n'est jamais remplacé par le cache", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurAVoir(config(serveur("a_voir"), { depot })).chargerAVoir();
    const refuse = await creerChargeurAVoir(config(transportEnEchec(403, "tool_call_blocked", "hors portée"), { depot })).chargerAVoir();
    expect(refuse).toEqual({ source: "refus", verdict: { code: "tool_call_blocked", detail: "hors portée" } });
  });

  test("le refus d'une personne qui n'est plus admin (refus_metier) n'est pas remplacé par le cache non plus", async () => {
    const depot = new DepotCleValeurMemoire();
    await creerChargeurAVoir(config(serveur("a_voir"), { depot })).chargerAVoir();
    const refuse = await creerChargeurAVoir(
      config(fauxTransport({ [OUTIL_LISTER_DEMANDES]: () => enveloppeEnErreur("refus_metier", "REJ-IDENTITE-APPAREIL-INVALIDE") }), { depot }),
    ).chargerAVoir();
    expect(refuse).toMatchObject({ source: "refus", verdict: { code: "refus_metier" } });
  });

  test("sans réseau ni cache : aucune, avec sa raison ; une instance sans rien à voir est lue comme telle (pas un échec)", async () => {
    expect(await creerChargeurAVoir(config(transportHorsLigne())).chargerAVoir()).toMatchObject({ source: "aucune" });
    const vide = await creerChargeurAVoir(config(serveur("a_voir_vide"))).chargerAVoir();
    expect(vide.source === "serveur" && vide.valeur).toMatchObject({ demandes: [], totalEnAttente: 0, attentes: { items: [], total: 0 } });
  });
});

describe("interpreterAVoir : un refus reste un refus, une panne reste une panne", () => {
  test("le refus de l'outil (`accepte: false`) est un refus", () => {
    expect(interpreterAVoir({ ok: true, resultat: { accepte: false, verdict: { code: "reserve_au_proprietaire", detail: "d" } } })).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "reserve_au_proprietaire", detail: "d" },
    });
  });

  test("une sortie tronquée est une panne, une réponse mal formée est illisible", () => {
    expect(interpreterAVoir({ ok: true, tronque: true, apercu: "{" })).toMatchObject({ ok: false, genre: "technique" });
    expect(interpreterAVoir({ ok: true, resultat: { accepte: true, resultat: { demandes: "aucune" } } })).toMatchObject({ ok: false, genre: "illisible" });
    expect(interpreterAVoir(null)).toMatchObject({ ok: false, genre: "illisible" });
  });
});

describe("epurerPourLeCache", () => {
  test("ne retire que les arguments, le motif et la description ; tout le reste est intact", () => {
    const brute = reponse("a_voir_avec_demande");
    const epuree: any = epurerPourLeCache(brute);
    const avant = brute.resultat.resultat.demandes[0];
    const apres = epuree.resultat.resultat.demandes[0];

    expect(apres).toEqual({ ...avant, arguments: null, motif_demande: null, description_outil: null });
    expect(epuree.resultat.resultat.attentes).toEqual(brute.resultat.resultat.attentes);
    expect(epuree.resultat.resultat.total_en_attente).toBe(1);
    // La réponse d'origine n'est pas modifiée : la lecture en ligne garde ses arguments.
    expect(brute.resultat.resultat.demandes[0].arguments).not.toBeNull();
  });

  test("ce qui n'a pas la forme attendue est rendu tel quel (jamais une erreur)", () => {
    for (const brut of [null, "x", { ok: true }, { ok: true, resultat: { accepte: false } }, { ok: true, resultat: { accepte: true, resultat: { demandes: "x" } } }]) {
      expect(epurerPourLeCache(brut)).toEqual(brut);
    }
  });

  test("un élément de la liste qui n'est pas un objet est laissé tel quel", () => {
    const brut = { ok: true, resultat: { accepte: true, resultat: { demandes: ["x", { id: "d", arguments: { a: 1 } }] } } };
    const epuree: any = epurerPourLeCache(brut);
    expect(epuree.resultat.resultat.demandes[0]).toBe("x");
    expect(epuree.resultat.resultat.demandes[1].arguments).toBeNull();
  });
});
