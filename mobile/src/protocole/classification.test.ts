import { estStatutReessayable } from "./classification";

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
