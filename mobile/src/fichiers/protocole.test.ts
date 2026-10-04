import {
  construireArgumentsDeposerFichier,
  construireArgumentsEtatFichier,
  construireReferenceFichier,
  interpreterResultatDeposerFichier,
  interpreterResultatEtatFichier,
} from "./protocole";

const SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

describe("construireArgumentsDeposerFichier / construireArgumentsEtatFichier", () => {
  test("args exacts du contrat, rien de plus", () => {
    expect(construireArgumentsDeposerFichier(SHA, 300, "image/jpeg", 0, 2, "QUJD")).toEqual({
      empreinte_sha256: SHA,
      taille_octets: 300,
      type_mime: "image/jpeg",
      index_bloc: 0,
      nombre_blocs: 2,
      bloc_base64: "QUJD",
    });
  });

  test("args exacts de m4_etat_fichier", () => {
    expect(construireArgumentsEtatFichier(SHA)).toEqual({ empreinte_sha256: SHA });
  });
});

describe("construireReferenceFichier", () => {
  test("forme exacte du contrat", () => {
    expect(construireReferenceFichier(SHA)).toBe(`fichier:sha256:${SHA}`);
  });
});

describe("interpreterResultatDeposerFichier", () => {
  test("bloc accepté, fichier pas encore complet -> reference null", () => {
    const resultat = interpreterResultatDeposerFichier({
      ok: true,
      resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [0] } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { reference: null, complet: false, blocsRecus: [0] } });
  });

  test("dernier bloc accepté -> complet true, référence déterministe", () => {
    const reference = construireReferenceFichier(SHA);
    const resultat = interpreterResultatDeposerFichier({
      ok: true,
      resultat: { accepte: true, resultat: { reference, complet: true, blocs_recus: [0, 1] } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { reference, complet: true, blocsRecus: [0, 1] } });
  });

  test("rejet métier -> accepte:false avec le verdict, jamais un succès silencieux", () => {
    const resultat = interpreterResultatDeposerFichier({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", detail: "hachage recalculé différent" } },
    });
    expect(resultat).toEqual({
      accepte: false,
      verdict: { code: "REJ-FICHIER-EMPREINTE-DISCORDANTE", detail: "hachage recalculé différent" },
    });
  });

  test("erreur technique (ok:false) -> accepte:false", () => {
    const resultat = interpreterResultatDeposerFichier({ ok: false, erreur: "invalid_request", details: "type_mime invalide" });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "invalid_request", detail: "type_mime invalide" } });
  });

  test("forme non reconnue ou accusé incomplet -> rejet récupérable, jamais envoyé", () => {
    const attendu = { accepte: false, verdict: { code: "accuse_invalide", detail: "Réponse métier de dépôt de fichier inconnue." } };
    expect(interpreterResultatDeposerFichier(null)).toEqual(attendu);
    expect(interpreterResultatDeposerFichier(undefined)).toEqual(attendu);
    expect(interpreterResultatDeposerFichier({ ok: true, resultat: { accepte: true, resultat: {} } }).accepte).toBe(false);
  });

  test("un accusé valide d'un bloc non final demeure accepté", () => {
    expect(interpreterResultatDeposerFichier({ ok: true, resultat: { accepte: true, resultat: { reference: null, complet: false, blocs_recus: [0] } } }))
      .toEqual({ accepte: true, resultat: { reference: null, complet: false, blocsRecus: [0] } });
  });
});

describe("interpreterResultatEtatFichier", () => {
  test("fichier connu, incomplet -> blocs déjà reçus portés", () => {
    const resultat = interpreterResultatEtatFichier({
      ok: true,
      resultat: { accepte: true, resultat: { existe: true, complet: false, blocs_recus: [0, 2], reference: null } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { existe: true, complet: false, blocsRecus: [0, 2], reference: null } });
  });

  test("fichier inconnu du serveur -> existe:false, jamais une erreur", () => {
    const resultat = interpreterResultatEtatFichier({
      ok: true,
      resultat: { accepte: true, resultat: { existe: false, complet: false, blocs_recus: [], reference: null } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { existe: false, complet: false, blocsRecus: [], reference: null } });
  });

  test("fichier complet -> reference portée", () => {
    const reference = construireReferenceFichier(SHA);
    const resultat = interpreterResultatEtatFichier({
      ok: true,
      resultat: { accepte: true, resultat: { existe: true, complet: true, blocs_recus: [0, 1], reference } },
    });
    expect(resultat).toEqual({ accepte: true, resultat: { existe: true, complet: true, blocsRecus: [0, 1], reference } });
  });

  test("rejet métier (ex. empreinte hors forme attendue) -> accepte:false", () => {
    const resultat = interpreterResultatEtatFichier({
      ok: true,
      resultat: { accepte: false, verdict: { code: "REJ-FICHIER-PARAMETRES-INVALIDES", detail: "empreinte_sha256 invalide" } },
    });
    expect(resultat).toEqual({ accepte: false, verdict: { code: "REJ-FICHIER-PARAMETRES-INVALIDES", detail: "empreinte_sha256 invalide" } });
  });

  test("réponse inconnue ou état incomplet ne se transforme pas en fichier absent", () => {
    expect(interpreterResultatEtatFichier({})).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
    expect(interpreterResultatEtatFichier({ ok: true, resultat: { accepte: true, resultat: {} } })).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  });
});
