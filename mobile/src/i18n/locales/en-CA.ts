import type { RessourcesCommunes } from "./fr-CA";

/** Réserve (R12 §3) — même forme que fr-CA (`RessourcesCommunes`), valeurs différentes. */
const enCA: RessourcesCommunes = {
  pairing: {
    titre: "Device pairing",
    explication:
      "This device is not yet paired with the OPSYS gateway. The pairing protocol " +
      "(QR code or setup code) will be enabled in a future step.",
    etatNonApparie: "Status: not paired",
  },
  groupes: {
    employee: { accueil: "Home — employee" },
    seller: { accueil: "Home — seller" },
    admin: { accueil: "Home — admin" },
    client: { accueil: "Home — client" },
  },
};

export default enCA;
