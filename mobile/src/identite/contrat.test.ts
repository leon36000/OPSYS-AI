import { estRoleNomme, interpreterReponseIdentite, ROLES_NOMMES, type ResultatLectureIdentite } from "./contrat";

const APPAREIL = "a".repeat(64);

function succes(identite: Record<string, unknown>) {
  return { ok: true, identite };
}

function refus(reason: string) {
  return { ok: false, error: { type: "forbidden", reason, message: "refus" } };
}

describe("estRoleNomme", () => {
  test("les trois rôles nommés d'un appareil, et rien d'autre", () => {
    expect([...ROLES_NOMMES].sort()).toEqual(["admin", "employee", "seller"]);
    for (const role of ROLES_NOMMES) {
      expect(estRoleNomme(role)).toBe(true);
    }
  });

  test.each(["operator", "client", "ADMIN", "admin ", " employee", "", "owner", "nathan_owner", "__proto__", "toString"])(
    "le rôle %j n'est pas un rôle nommé",
    (role) => {
      expect(estRoleNomme(role)).toBe(false);
    },
  );

  test.each([undefined, null, 3, {}, ["admin"], true])("une valeur qui n'est pas une chaîne (%j) n'est pas un rôle nommé", (valeur) => {
    expect(estRoleNomme(valeur)).toBe(false);
  });
});

describe("interpreterReponseIdentite — 200", () => {
  test.each(ROLES_NOMMES)("une identité complète d'un rôle nommé (%s), de CET appareil, est confirmée", (role) => {
    const resultat = interpreterReponseIdentite(200, succes({ appareilId: APPAREIL, personne: "jdupont", role }), APPAREIL);
    expect(resultat).toEqual({ genre: "confirmee", identite: { appareilId: APPAREIL, personne: "jdupont", role } });
  });

  test("garde la personne telle que le serveur la donne (ni rognée, ni réécrite)", () => {
    const resultat = interpreterReponseIdentite(
      200,
      succes({ appareilId: APPAREIL, personne: "Jean Dupont", role: "employee" }),
      APPAREIL,
    );
    expect(resultat).toEqual({
      genre: "confirmee",
      identite: { appareilId: APPAREIL, personne: "Jean Dupont", role: "employee" },
    });
  });

  test("l'identité d'un AUTRE appareil n'est jamais adoptée, même bien formée", () => {
    const resultat = interpreterReponseIdentite(
      200,
      succes({ appareilId: "b".repeat(64), personne: "nathan_owner", role: "admin" }),
      APPAREIL,
    );
    expect(resultat).toEqual({ genre: "refusee", motif: "reponse_invalide" });
  });

  test("le rôle de transport « operator » n'est pas un profil : refusé, jamais un défaut", () => {
    const resultat = interpreterReponseIdentite(200, succes({ appareilId: APPAREIL, personne: "jdupont", role: "operator" }), APPAREIL);
    expect(resultat).toEqual({ genre: "refusee", motif: "role_inconnu" });
  });

  test.each(["ADMIN", "admin ", "client", "", "proprietaire"])("le rôle inconnu %j est refusé (role_inconnu)", (role) => {
    const resultat = interpreterReponseIdentite(200, succes({ appareilId: APPAREIL, personne: "jdupont", role }), APPAREIL);
    expect(resultat).toEqual({ genre: "refusee", motif: "role_inconnu" });
  });

  test.each([
    ["rôle absent", { appareilId: APPAREIL, personne: "jdupont" }],
    ["rôle numérique", { appareilId: APPAREIL, personne: "jdupont", role: 3 }],
    ["personne absente", { appareilId: APPAREIL, role: "employee" }],
    ["personne vide", { appareilId: APPAREIL, personne: "", role: "employee" }],
    ["personne d'espaces", { appareilId: APPAREIL, personne: "   ", role: "employee" }],
    ["personne numérique", { appareilId: APPAREIL, personne: 42, role: "employee" }],
    ["appareil absent", { personne: "jdupont", role: "employee" }],
  ])("identité incomplète (%s) : refusée, aucun profil", (_nom, identite) => {
    expect(interpreterReponseIdentite(200, succes(identite), APPAREIL)).toEqual({
      genre: "refusee",
      motif: "reponse_invalide",
    });
  });

  test.each([
    ["ok:false", { ok: false, identite: { appareilId: APPAREIL, personne: "jdupont", role: "employee" } }],
    ["ok absent", { identite: { appareilId: APPAREIL, personne: "jdupont", role: "employee" } }],
    ["identité absente", { ok: true }],
    ["identité nulle", { ok: true, identite: null }],
    ["identité en tableau", { ok: true, identite: [] }],
    ["corps en tableau", []],
    ["corps chaîne", "ok"],
    ["corps nul", null],
  ])("corps JSON qui n'est pas une identité (%s) : refusé", (_nom, corps) => {
    expect(interpreterReponseIdentite(200, corps, APPAREIL)).toEqual({ genre: "refusee", motif: "reponse_invalide" });
  });

  test("corps illisible (pas du JSON : portail captif, proxy) : indisponible, le serveur n'a rien dit", () => {
    const resultat = interpreterReponseIdentite(200, undefined, APPAREIL);
    expect(resultat.genre).toBe("indisponible");
  });
});

describe("interpreterReponseIdentite — refus et pannes", () => {
  test("401 : jeton refusé (inconnu ou révoqué)", () => {
    expect(interpreterReponseIdentite(401, { error: { type: "unauthorized" } }, APPAREIL)).toEqual({
      genre: "refusee",
      motif: "jeton_refuse",
    });
    expect(interpreterReponseIdentite(401, undefined, APPAREIL)).toEqual({ genre: "refusee", motif: "jeton_refuse" });
  });

  test("403 device_unknown : appareil non attribué (jamais attribué, ou révoqué)", () => {
    expect(interpreterReponseIdentite(403, refus("device_unknown"), APPAREIL)).toEqual({
      genre: "refusee",
      motif: "appareil_non_attribue",
    });
  });

  test("403 role_unknown : rôle inconnu de la passerelle", () => {
    expect(interpreterReponseIdentite(403, refus("role_unknown"), APPAREIL)).toEqual({
      genre: "refusee",
      motif: "role_inconnu",
    });
  });

  test.each([
    ["device_required", refus("device_required")],
    ["raison inconnue", refus("autre_chose")],
    ["sans raison", { ok: false, error: { type: "forbidden" } }],
    ["corps illisible", undefined],
    ["corps nul", null],
  ])("403 sans raison connue (%s) : refus inattendu", (_nom, corps) => {
    expect(interpreterReponseIdentite(403, corps, APPAREIL)).toEqual({ genre: "refusee", motif: "refus_inattendu" });
  });

  test.each([400, 404, 405, 410])("HTTP %i (ex. un core plus ancien sans cette route) : refus inattendu, jamais un profil", (status) => {
    expect(interpreterReponseIdentite(status, { error: "x" }, APPAREIL)).toEqual({
      genre: "refusee",
      motif: "refus_inattendu",
    });
  });

  test.each([408, 429, 500, 502, 503, 504])("HTTP %i : indisponible (réessayable), rien n'est dit de l'attribution", (status) => {
    const resultat: ResultatLectureIdentite = interpreterReponseIdentite(status, undefined, APPAREIL);
    expect(resultat.genre).toBe("indisponible");
  });
});
