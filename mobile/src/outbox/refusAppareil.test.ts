import { ecouterRefusAppareil, signalerRefusAppareil } from "./refusAppareil";

describe("pont de refus d'appareil (file sortante -> cycle d'identité)", () => {
  test("signaler prévient chaque écouteur, une fois par signal", () => {
    const a = jest.fn();
    const b = jest.fn();
    const retirerA = ecouterRefusAppareil(a);
    const retirerB = ecouterRefusAppareil(b);

    signalerRefusAppareil();

    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    retirerA();
    retirerB();
  });

  test("un écouteur retiré n'est plus prévenu", () => {
    const ecouteur = jest.fn();
    const retirer = ecouterRefusAppareil(ecouteur);
    retirer();

    signalerRefusAppareil();

    expect(ecouteur).not.toHaveBeenCalled();
  });

  test("signaler sans écouteur ne fait rien et ne lève pas", () => {
    expect(() => signalerRefusAppareil()).not.toThrow();
  });

  test("un écouteur qui lève n'empêche pas les autres d'être prévenus, ni le signal de revenir", () => {
    const erreurs = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const casse = jest.fn(() => {
      throw new Error("écouteur cassé");
    });
    const sain = jest.fn();
    const retirerCasse = ecouterRefusAppareil(casse);
    const retirerSain = ecouterRefusAppareil(sain);

    expect(() => signalerRefusAppareil()).not.toThrow();

    expect(casse).toHaveBeenCalledTimes(1);
    expect(sain).toHaveBeenCalledTimes(1);
    expect(erreurs).toHaveBeenCalledTimes(1);
    retirerCasse();
    retirerSain();
    erreurs.mockRestore();
  });
});
