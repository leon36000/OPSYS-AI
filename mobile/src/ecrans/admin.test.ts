import { presenterAVoir, vueAccueil } from "./admin";
import { aVoirDe, duCache, duServeur } from "./donneesDeVue";

describe("l'accueil « À voir » du propriétaire", () => {
  test("le serveur dit qu'il n'y a rien : « rien à voir », et seulement dans ce cas", () => {
    const vue = presenterAVoir(aVoirDe("a_voir_vide"), -240);
    expect(vue.rienAVoir).toBe(true);
    expect(vue.demandes).toEqual([]);
    expect(vue.attentes).toEqual({ genre: "aucune" });
    expect(vue.totalEnAttente).toEqual({ cle: "admin.aVoir.demandes.total", params: { total: 0 } });
    expect(vue.resteDemandes).toBeNull();
    expect(vue.illisibles).toBeNull();
  });

  test("des attentes de départements : chacune dit ce que son département a écrit, dans l'ordre du serveur", () => {
    const vue = presenterAVoir(aVoirDe("a_voir"), -240);
    expect(vue.rienAVoir).toBe(false);
    expect(vue.demandes).toEqual([]);
    if (vue.attentes.genre !== "presentes") {
      throw new Error("des attentes devraient être présentes");
    }
    expect(vue.attentes.items.map((a) => a.cle)).toEqual([
      "m05-financecore:facture_brouillon:fac-DEVIS-ADM-A-fictif",
      expect.stringMatching(/^m05-financecore:chantier_a_reviser:variance-/),
      expect.stringMatching(/^m04-field-ops:completion_en_revue:/),
    ]);
    const [facture, , completion] = vue.attentes.items;
    // Le résumé est celui du département, tel quel (rien n'est reformulé ni reclassé « critique »).
    expect(facture.resume).toBe("Facture fac-DEVIS-ADM-A-fictif prête à envoyer (689.85 $)");
    expect(facture.departement).toEqual({ cle: "approvals.departement", params: { nom: "FinanceCore" } });
    expect(facture.niveau).toEqual({ cle: "approvals.niveau", params: { niveau: "N4" } });
    expect(facture.geste).toEqual({ cle: "approvals.attentes.geste", params: { geste: "envoyer" } });
    expect(completion.geste?.params?.geste).toContain("m4_resoudre_revue_completion");
    // « Depuis » est l'instant du serveur ramené à l'heure de l'appareil.
    expect(facture.depuis).toEqual({ cle: "approvals.depuis", params: { date: "2026-09-21 11:00" } });
    // Quatre autres attentes existent que le serveur n'a pas montrées : dit, avec le renvoi à l'écran des approbations.
    expect(vue.attentes.reste).toEqual({ cle: "admin.aVoir.attentes.reste", params: { nombre: 4 } });
    expect(vue.attentes.illisibles).toBeNull();
    expect(vue.attentes.departementsIllisibles).toBeNull();
  });

  test("une demande d'approbation : l'outil, le département, le niveau et depuis quand ; rien qui ne se décide ici", () => {
    const vue = presenterAVoir(aVoirDe("a_voir_avec_demande"), -240);
    expect(vue.rienAVoir).toBe(false);
    expect(vue.totalEnAttente.params).toEqual({ total: 1 });
    expect(vue.demandes).toHaveLength(1);
    const [demande] = vue.demandes;
    expect(demande.outil).toBe("m4_resoudre_revue_completion");
    expect(demande.departement).toEqual({ cle: "approvals.departement", params: { nom: "Field Ops" } });
    expect(demande.niveau).toEqual({ cle: "approvals.niveau", params: { niveau: "N4" } });
    expect(demande.id).toMatch(/^[0-9a-f]{12}$/);
    expect(vue.proprietaire).toBe(true);
  });

  test("MINIMISATION : ni les arguments, ni le motif, ni la description de l'outil n'arrivent à la vue", () => {
    const texte = JSON.stringify(presenterAVoir(aVoirDe("a_voir_avec_demande"), -240));
    // Le motif et les arguments exacts de la demande (l'écran des approbations les montre, pas l'accueil).
    expect(texte).not.toContain("Bris de 16 pi");
    expect(texte).not.toContain("2026-09-25T07:00:00-04:00");
    expect(texte).not.toContain('"decision"');
    expect(texte).not.toContain("intervention_id");
    // La description de l'outil.
    expect(texte).not.toContain("Revue HUMAINE");
  });

  test("le moteur ne donne pas les attentes : inconnues, jamais « aucune », et donc jamais « rien à voir »", () => {
    const liste = { ...aVoirDe("a_voir_vide"), attentes: null };
    const vue = presenterAVoir(liste, -240);
    expect(vue.attentes).toEqual({ genre: "inconnues" });
    expect(vue.rienAVoir).toBe(false);
  });

  test("des éléments illisibles, des demandes non montrées ou un département muet empêchent le « rien à voir »", () => {
    const base = aVoirDe("a_voir_vide");
    expect(presenterAVoir({ ...base, illisibles: 2 }, -240)).toMatchObject({
      rienAVoir: false,
      illisibles: { cle: "admin.aVoir.demandes.illisibles", params: { nombre: 2 } },
    });
    expect(presenterAVoir({ ...base, reste: 5, totalEnAttente: 5 }, -240)).toMatchObject({
      rienAVoir: false,
      resteDemandes: { cle: "admin.aVoir.demandes.reste", params: { nombre: 5 } },
    });
    const attentes = { items: [], total: 0, reste: 0, decalage: 0, suivant: null, illisibles: 0, departementsIllisibles: ["m05-financecore"] };
    const muet = presenterAVoir({ ...base, attentes }, -240);
    expect(muet.rienAVoir).toBe(false);
    expect(muet.attentes).toMatchObject({
      genre: "presentes",
      departementsIllisibles: { cle: "approvals.attentes.departementsIllisibles", params: { departements: "m05-financecore" } },
    });
  });

  test("une personne qui n'est pas le propriétaire le voit : la décision lui est fermée", () => {
    expect(presenterAVoir({ ...aVoirDe("a_voir_vide"), proprietaire: false }, -240).proprietaire).toBe(false);
  });

  test("le département sans nom est nommé par son identifiant", () => {
    const liste = aVoirDe("a_voir_avec_demande");
    const sansNom = { ...liste, demandes: liste.demandes.map((d) => ({ ...d, departementNom: null })) };
    expect(presenterAVoir(sansNom, -240).demandes[0].departement.params).toEqual({ nom: "m04-field-ops" });
  });

  test("un niveau absent est dit inconnu, jamais deviné", () => {
    const liste = aVoirDe("a_voir_avec_demande");
    const sansNiveau = { ...liste, demandes: liste.demandes.map((d) => ({ ...d, niveau: null })) };
    expect(presenterAVoir(sansNiveau, -240).demandes[0].niveau).toEqual({ cle: "approvals.niveauInconnu" });
  });
});

describe("l'accueil selon ce que le chargeur a pu lire", () => {
  test("au serveur : la vue, sans bandeau hors ligne", () => {
    const vue = vueAccueil(duServeur(aVoirDe("a_voir_vide")), -240);
    expect(vue).toMatchObject({ genre: "contenu", horsLigne: null });
  });

  test("dans le cache : la vue est marquée (date et raison)", () => {
    const vue = vueAccueil(duCache(aVoirDe("a_voir_vide"), "delai_depasse"), -240);
    expect(vue).toMatchObject({
      genre: "contenu",
      horsLigne: { cle: "admin.commun.cache", params: { date: "2026-09-28 09:30", code: "delai_depasse" } },
    });
  });

  test("refusée : le verdict, pas de contenu", () => {
    const vue = vueAccueil({ source: "refus", verdict: { code: "http_403", detail: "hors portée" } }, -240);
    expect(vue.genre).toBe("refus");
    expect(vue).not.toHaveProperty("contenu");
  });

  test("ni serveur ni cache : « aucune », jamais une liste vide qui dirait « rien à voir »", () => {
    const vue = vueAccueil({ source: "aucune", raison: { code: "erreur_reseau", detail: "x" } }, -240);
    expect(vue.genre).toBe("aucune");
    expect(vue).not.toHaveProperty("contenu");
  });
});
