import {
  PREFIXE_AUTEUR_SYSTEME,
  construireArgumentsClient360,
  construireArgumentsSuggerer,
  construireArgumentsTrouverClient,
  interpreterResultatClient360,
  interpreterResultatClientDeLead,
  interpreterResultatSuggestion,
} from "./client360";
import {
  CLIENT_DE_LEAD_BRUT,
  SUGGESTION_BRUTE,
  client360Brut,
  enveloppeAcceptee,
  enveloppeRefusee,
} from "../vendeur/donneesDeTest";

describe("arguments : exactement ceux des schémas, jamais une personne", () => {
  test("suggestion, client du lead, client 360", () => {
    expect(construireArgumentsSuggerer("lead-1", "2026-09-29T12:00:00-04:00")).toEqual({
      lead_id: "lead-1",
      horodatage: "2026-09-29T12:00:00-04:00",
    });
    expect(construireArgumentsTrouverClient("lead-1")).toEqual({ lead_id: "lead-1" });
    expect(construireArgumentsClient360("c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00")).toEqual({ client_id: "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00" });
  });
});

describe("prochaine action suggérée, avec sa règle citée", () => {
  test("règle, texte fixe et motif du serveur, tels quels", () => {
    const lecture = interpreterResultatSuggestion(enveloppeAcceptee(SUGGESTION_BRUTE));
    expect(lecture).toEqual({
      ok: true,
      valeur: {
        leadId: "lead-a-01",
        statut: "qualifie",
        regle: "transmettre_m3",
        suggestion: "Transmettre le dossier à M3 pour estimation.",
        motif: SUGGESTION_BRUTE.motif,
      },
    });
  });

  test("un lead clos ou d'un autre : refus du serveur, verdict tel quel, aucune suggestion inventée", () => {
    expect(interpreterResultatSuggestion(enveloppeRefusee("REJ-CONVERSATION-CLOSE", "lead l1 clos (statut=perdu)"))).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-CONVERSATION-CLOSE", detail: "lead l1 clos (statut=perdu)" },
    });
    expect(interpreterResultatSuggestion(enveloppeRefusee("REJ-LEAD-NON-ASSIGNE", "lead inconnu")).ok).toBe(false);
  });

  test.each(["lead_id", "statut", "regle", "suggestion", "motif"])(
    "sans %s : illisible, la règle n'est pas devinée",
    (cle) => {
      const brut = { ...SUGGESTION_BRUTE, [cle]: undefined };
      expect(interpreterResultatSuggestion(enveloppeAcceptee(brut))).toMatchObject({ ok: false, genre: "illisible" });
    },
  );
});

describe("client du lead", () => {
  test("lead_id et client_id lus", () => {
    expect(interpreterResultatClientDeLead(enveloppeAcceptee(CLIENT_DE_LEAD_BRUT))).toEqual({
      ok: true,
      valeur: { leadId: "lead-a-01", clientId: "a2f9b5d094369843521d099715b97ef817491c0e2309406bd46d75c41301a346" },
    });
  });

  test("un lead sans client : refus du serveur ; une réponse sans client_id : illisible", () => {
    expect(interpreterResultatClientDeLead(enveloppeRefusee("REJ-TRANSITION-ILLEGALE", "non lié à un client"))).toMatchObject({
      ok: false,
      genre: "refus",
    });
    expect(interpreterResultatClientDeLead(enveloppeAcceptee({ lead_id: "l1" }))).toMatchObject({ ok: false, genre: "illisible" });
  });
});

describe("Client 360", () => {
  test("contact, opportunités, interactions : lus, chacun avec son lead", () => {
    const lecture = interpreterResultatClient360(enveloppeAcceptee(client360Brut()));
    expect(lecture.ok).toBe(true);
    if (!lecture.ok) {
      return;
    }
    const vue = lecture.valeur;
    expect(vue.clientId).toBe("a2f9b5d094369843521d099715b97ef817491c0e2309406bd46d75c41301a346");
    expect(vue.contact).toEqual({ nom: "Cliente Fictive", courriel: "cliente@exemple-fictif.test" });
    expect(vue.opportunites.map((o) => [o.leadId, o.statut, o.typeTravaux, o.service])).toEqual([
      ["lead-a-01", "qualifie", "renovation_totale", null],
      ["lead-a-02", "avis", null, "gouttieres"],
    ]);
    expect(vue.opportunites[0].prochaineAction).toEqual({
      description: "Appeler le client (fictif)",
      echeance: "2026-09-05T09:00:00-04:00",
    });
    expect(vue.opportunites[1].prochaineAction).toBeNull();
    expect(vue.interactionsRecentes.map((i) => [i.leadId, i.auteur])).toEqual([
      ["lead-a-02", "vendeur.fictif"],
      ["lead-a-01", "vendeur.fictif"],
      ["lead-a-01", "system:m3"],
    ]);
    expect(vue.illisibles).toBe(0);
    expect("system:m3".startsWith(PREFIXE_AUTEUR_SYSTEME)).toBe(true);
  });

  test("la provenance expose campagne et UTM serveur; les champs absents restent inconnus", () => {
    const brut = client360Brut();
    const opportunities = brut.opportunites as Array<Record<string, unknown>>;
    opportunities[0] = {
      ...opportunities[0],
      source: "facebook",
      campagne: "automne-2026",
      utm: { utm_source: "facebook", utm_campaign: "automne-2026", utm_content: "gouttieres-a1" },
    };
    const lecture = interpreterResultatClient360(enveloppeAcceptee(brut));
    expect(lecture.ok && lecture.valeur.opportunites[0]).toMatchObject({
      source: "facebook",
      campagne: "automne-2026",
      utm: { utm_source: "facebook", utm_campaign: "automne-2026", utm_content: "gouttieres-a1" },
    });
    expect(lecture.ok && lecture.valeur.opportunites[1].utm).toBeNull();
  });

  test("UTM absent (ou propriété omise) demeure inconnu", () => {
    const brut = client360Brut();
    const opportunities = brut.opportunites as Array<Record<string, unknown>>;
    opportunities[0] = { ...opportunities[0], utm: undefined, source: undefined, campagne: undefined };
    const lecture = interpreterResultatClient360(enveloppeAcceptee(brut));
    expect(lecture.ok && lecture.valeur.opportunites[0]).toMatchObject({ source: null, campagne: null, utm: null });
  });

  test.each([
    ["clé inconnue", { utm_source: "facebook", utm_id: "inventé" }],
    ["valeur non texte", { utm_source: 12 }],
    ["valeur vide", { utm_source: " " }],
    ["objet vide", {}],
    ["UTM non objet", "utm_source=facebook"],
  ])("une provenance UTM mal formée (%s) invalide seulement son opportunité et est comptée", (_cas, utm) => {
    const brut = client360Brut();
    const opportunities = brut.opportunites as Array<Record<string, unknown>>;
    opportunities[0] = { ...opportunities[0], utm };
    const lecture = interpreterResultatClient360(enveloppeAcceptee(brut));
    expect(lecture.ok && lecture.valeur.opportunites).toHaveLength(1);
    expect(lecture.ok && lecture.valeur.illisibles).toBe(1);
  });

  test("le contact absent ou nul est nul : dit absent par l'écran, jamais inventé", () => {
    for (const contact of [null, undefined]) {
      const lecture = interpreterResultatClient360(enveloppeAcceptee(client360Brut({ contact })));
      expect(lecture.ok && lecture.valeur.contact).toBeNull();
    }
  });

  test("un contact qui n'est pas un objet rend toute la vue illisible", () => {
    expect(interpreterResultatClient360(enveloppeAcceptee(client360Brut({ contact: "Cliente" })))).toMatchObject({
      ok: false,
      genre: "illisible",
    });
  });

  test("une opportunité ou une interaction mal formée est comptée, jamais tue", () => {
    const vue = client360Brut({
      opportunites: [{ statut: "qualifie" }, ...(client360Brut().opportunites as unknown[])],
      interactions_recentes: [{ lead_id: "l1", auteur: "x", resume: "", horodatage: "t" }, 42],
    });
    const lecture = interpreterResultatClient360(enveloppeAcceptee(vue));
    expect(lecture.ok && lecture.valeur.illisibles).toBe(3);
    expect(lecture.ok && lecture.valeur.opportunites).toHaveLength(2);
    expect(lecture.ok && lecture.valeur.interactionsRecentes).toHaveLength(0);
  });

  test.each([
    ["sans client_id", { client_id: undefined }],
    ["opportunites qui n'est pas une liste", { opportunites: null }],
    ["interactions_recentes manquant", { interactions_recentes: undefined }],
  ])("vue illisible (%s) : jamais un Client 360 vide", (_nom, surcharge) => {
    expect(interpreterResultatClient360(enveloppeAcceptee(client360Brut(surcharge)))).toMatchObject({
      ok: false,
      genre: "illisible",
    });
  });

  test("un client dont aucune opportunité n'est au vendeur : le refus du serveur, identique à un client inconnu", () => {
    const refus = interpreterResultatClient360(enveloppeRefusee("REJ-LEAD-NON-ASSIGNE", "client introuvable"));
    expect(refus).toEqual({ ok: false, genre: "refus", verdict: { code: "REJ-LEAD-NON-ASSIGNE", detail: "client introuvable" } });
  });

  test("une réponse tronquée par le socle n'est jamais lue comme la vue", () => {
    expect(interpreterResultatClient360({ ok: true, tronque: true, apercu: "{\"accepte\": true" })).toMatchObject({
      ok: false,
      genre: "technique",
      verdict: { code: "reponse_tronquee" },
    });
  });
});
