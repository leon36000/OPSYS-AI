import { estRefusAppareil, estStatutReessayable } from "./classification";

describe("estStatutReessayable", () => {
  test.each([
    [100, false],
    [200, false],
    [301, false],
    [400, false],
    [401, false],
    [403, false],
    [404, false],
    [405, false],
    [407, false],
    [408, true],
    [409, false],
    [422, false],
    [428, false],
    [429, true],
    [430, false],
    [499, false],
    [500, true],
    [502, true],
    [503, true],
    [599, true],
    [600, false],
  ] as const)("status=%i -> réessayable=%s", (status, attendu) => {
    expect(estStatutReessayable(status)).toBe(attendu);
  });
});

describe("estRefusAppareil", () => {
  const refus403 = (raison: string) => ({
    status: 403,
    erreur: { message: `OPSYS device is not authorized to call "m4_pointer" (${raison}).` },
  });

  test("401 : le jeton est inconnu ou révoqué, avec ou sans corps lisible", () => {
    expect(estRefusAppareil({ status: 401 })).toBe(true);
    expect(estRefusAppareil({ status: 401, erreur: { message: "Unauthorized" } })).toBe(true);
  });

  test.each(["device_unknown", "role_unknown"])("403 nommant %s : c'est l'appareil qui est refusé", (raison) => {
    expect(estRefusAppareil(refus403(raison))).toBe(true);
  });

  test.each(["tool_out_of_scope", "server_unknown"])(
    "403 nommant %s : c'est la mutation qui est refusée, pas l'appareil",
    (raison) => {
      expect(estRefusAppareil(refus403(raison))).toBe(false);
    },
  );

  test("403 sans raison connue (deviceId du corps, autre refus) : jamais lu comme un refus d'appareil", () => {
    expect(estRefusAppareil({ status: 403 })).toBe(false);
    expect(
      estRefusAppareil({
        status: 403,
        erreur: { message: "Request body deviceId does not match the authenticated device." },
      }),
    ).toBe(false);
  });

  test.each([undefined, 200, 400, 404, 408, 429, 500, 503])("status=%s : pas un refus d'appareil", (status) => {
    expect(estRefusAppareil({ status, erreur: { message: "OPSYS device (device_unknown)" } })).toBe(false);
  });
});
