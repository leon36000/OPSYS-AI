import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";

import {
  CHOIX_CLIENT_VIDES,
  TEXTE_CONSENTEMENT_DEMANDE_AVIS,
  TEXTE_CONSENTEMENT_PHOTOS,
  VERSION_TEXTE_CONSENTEMENT_CLIENT,
  basculerConsentement,
  choisirSatisfaction,
  choixClientVerrouilles,
  construireChampsClient,
} from "./consentementClient";
import type { ChoixClient } from "./consentementClient";

/** Empreinte SHA-256 du texte présenté au client sous `consentement-client-fr-CA-v1` : les deux énoncés,
 * dans cet ordre, séparés d'un saut de ligne. Changer un mot change cette empreinte : il faut alors une
 * NOUVELLE version (`consentement-client-fr-CA-v2`), pas seulement mettre cette valeur à jour — le
 * serveur a déjà gardé « v1 » avec des consentements réels. */
const EMPREINTE_TEXTE_V1 = "eabdb18c5e60009deb37f850f29eb52d52c9c04df6d54e7b474ca612f30c0bad";

/** Le format que le serveur exige (`outils.py`, `_FORMAT_VERSION_TEXTE_CONSENTEMENT`). */
const FORMAT_VERSION_SERVEUR = /^[A-Za-z0-9._-]{1,64}$/;

function choix(surcharge: Partial<ChoixClient>): ChoixClient {
  return { ...CHOIX_CLIENT_VIDES, ...surcharge };
}

describe("état initial : rien n'est consenti d'avance", () => {
  test("aucune case cochée, aucune réponse de satisfaction", () => {
    expect(CHOIX_CLIENT_VIDES).toEqual({ consentementDemandeAvis: false, consentementPhotos: false, satisfaction: null });
  });

  test("sans aucun choix, aucun champ n'est envoyé : « Terminer » part comme avant", () => {
    expect(construireChampsClient(CHOIX_CLIENT_VIDES)).toEqual({});
    expect(Object.keys(construireChampsClient(CHOIX_CLIENT_VIDES))).toEqual([]);
  });
});

describe("construireChampsClient : absence = non consenti", () => {
  test("demande d'avis cochée seule : sa clé et la version du texte, jamais le consentement aux photos", () => {
    const champs = construireChampsClient(choix({ consentementDemandeAvis: true }));
    expect(champs).toEqual({
      consentement_demande_avis: true,
      consentement_version_texte: VERSION_TEXTE_CONSENTEMENT_CLIENT,
    });
    expect("consentement_marketing" in champs).toBe(false); // l'un n'est jamais déduit de l'autre
  });

  test("photos cochées seules : consentement_marketing et la version, jamais la demande d'avis", () => {
    const champs = construireChampsClient(choix({ consentementPhotos: true }));
    expect(champs).toEqual({
      consentement_marketing: true,
      consentement_version_texte: VERSION_TEXTE_CONSENTEMENT_CLIENT,
    });
    expect("consentement_demande_avis" in champs).toBe(false);
  });

  test("les deux cochées : les deux clés, une seule version", () => {
    expect(construireChampsClient(choix({ consentementDemandeAvis: true, consentementPhotos: true }))).toEqual({
      consentement_demande_avis: true,
      consentement_marketing: true,
      consentement_version_texte: VERSION_TEXTE_CONSENTEMENT_CLIENT,
    });
  });

  test("une case décochée n'envoie JAMAIS de `false` : pas de clé du tout", () => {
    for (const champs of [
      construireChampsClient(CHOIX_CLIENT_VIDES),
      construireChampsClient(choix({ consentementDemandeAvis: true })),
      construireChampsClient(choix({ consentementPhotos: true })),
    ]) {
      expect(Object.values(champs).filter((valeur) => valeur === false)).toEqual([]);
    }
  });

  test("la satisfaction seule n'est pas un consentement : ni version, ni consentement", () => {
    expect(construireChampsClient(choix({ satisfaction: "satisfait" }))).toEqual({ client_satisfait: true });
    expect(construireChampsClient(choix({ satisfaction: "insatisfait" }))).toEqual({ client_satisfait: false });
  });

  test("sans réponse de satisfaction, `client_satisfait` n'est pas envoyé (jamais un « oui » par défaut)", () => {
    expect("client_satisfait" in construireChampsClient(choix({ consentementDemandeAvis: true }))).toBe(false);
  });

  test("consentement et satisfaction se combinent, sans autre clé", () => {
    const champs = construireChampsClient(choix({ consentementDemandeAvis: true, satisfaction: "satisfait" }));
    expect(Object.keys(champs).sort()).toEqual(["client_satisfait", "consentement_demande_avis", "consentement_version_texte"]);
  });

  test("l'appareil ne fournit ni qui a recueilli le consentement, ni quand, ni photos ni description", () => {
    const tout = construireChampsClient(
      choix({ consentementDemandeAvis: true, consentementPhotos: true, satisfaction: "satisfait" }),
    );
    for (const cle of ["consentement_recueilli_par", "consentement_recueilli_le", "photos", "description_factuelle"]) {
      expect(cle in tout).toBe(false); // le serveur pose les deux premières ; les deux autres ne sont pas la parole du client
    }
  });
});

describe("le texte présenté est versionné", () => {
  test("la version respecte le format que le serveur exige", () => {
    expect(VERSION_TEXTE_CONSENTEMENT_CLIENT).toMatch(FORMAT_VERSION_SERVEUR);
  });

  test("l'empreinte du texte est celle de sa version : modifier un mot exige une nouvelle version", () => {
    const empreinte = bytesToHex(
      sha256(utf8ToBytes(`${TEXTE_CONSENTEMENT_DEMANDE_AVIS}\n${TEXTE_CONSENTEMENT_PHOTOS}`)),
    );
    expect(VERSION_TEXTE_CONSENTEMENT_CLIENT).toBe("consentement-client-fr-CA-v1");
    expect(empreinte).toBe(EMPREINTE_TEXTE_V1);
  });

  test("les deux énoncés sont distincts, en français, à la première personne du client", () => {
    expect(TEXTE_CONSENTEMENT_DEMANDE_AVIS).not.toBe(TEXTE_CONSENTEMENT_PHOTOS);
    for (const texte of [TEXTE_CONSENTEMENT_DEMANDE_AVIS, TEXTE_CONSENTEMENT_PHOTOS]) {
      expect(texte.startsWith("J'accepte que ")).toBe(true);
      expect(texte).toContain("Je peux refuser"); // libre de refuser, sans conséquence
      expect(texte).toContain("retirer mon consentement en tout temps"); // droit de retrait (Loi 25)
    }
  });

  test("chaque énoncé dit ce à quoi le client consent, et seulement cela", () => {
    expect(TEXTE_CONSENTEMENT_DEMANDE_AVIS).toContain("me demander de laisser un avis");
    expect(TEXTE_CONSENTEMENT_DEMANDE_AVIS).not.toContain("photos");
    expect(TEXTE_CONSENTEMENT_PHOTOS).toContain("photos");
    expect(TEXTE_CONSENTEMENT_PHOTOS).toContain("floutées"); // visages, plaques, adresse : POLITIQUE-photos §5
    expect(TEXTE_CONSENTEMENT_PHOTOS).not.toContain("avis");
  });
});

describe("gestes de l'écran (fonctions pures)", () => {
  test("cocher puis décocher revient à l'état vide : le client peut se raviser avant l'envoi", () => {
    const coche = basculerConsentement(CHOIX_CLIENT_VIDES, "consentementDemandeAvis");
    expect(coche).toEqual({ ...CHOIX_CLIENT_VIDES, consentementDemandeAvis: true });
    expect(basculerConsentement(coche, "consentementDemandeAvis")).toEqual(CHOIX_CLIENT_VIDES);
  });

  test("chaque case ne touche qu'elle-même, jamais l'autre", () => {
    expect(basculerConsentement(CHOIX_CLIENT_VIDES, "consentementPhotos")).toEqual({
      ...CHOIX_CLIENT_VIDES, consentementPhotos: true,
    });
    const deux = basculerConsentement(basculerConsentement(CHOIX_CLIENT_VIDES, "consentementPhotos"), "consentementDemandeAvis");
    expect(deux.consentementPhotos && deux.consentementDemandeAvis).toBe(true);
  });

  test("basculer ne modifie jamais l'état d'origine", () => {
    const avant = Object.freeze({ ...CHOIX_CLIENT_VIDES });
    basculerConsentement(avant, "consentementPhotos");
    expect(avant).toEqual(CHOIX_CLIENT_VIDES);
  });

  test("toucher deux fois la même réponse de satisfaction l'efface ; l'autre la remplace", () => {
    const satisfait = choisirSatisfaction(CHOIX_CLIENT_VIDES, "satisfait");
    expect(satisfait.satisfaction).toBe("satisfait");
    expect(choisirSatisfaction(satisfait, "satisfait").satisfaction).toBeNull();
    expect(choisirSatisfaction(satisfait, "insatisfait").satisfaction).toBe("insatisfait");
  });

  test("répondre sur la satisfaction ne touche à aucun consentement", () => {
    const avant = basculerConsentement(CHOIX_CLIENT_VIDES, "consentementDemandeAvis");
    expect(choisirSatisfaction(avant, "insatisfait").consentementDemandeAvis).toBe(true);
  });
});

describe("choixClientVerrouilles : ce qui est parti est ce que le client a accepté", () => {
  const LIBRE = { enTraitement: false, completionEnvoyee: false, statutMutationCompletion: null } as const;

  test("avant « Terminer » : libres", () => {
    expect(choixClientVerrouilles(LIBRE)).toBe(false);
  });

  test("pendant l'envoi : verrouillés", () => {
    expect(choixClientVerrouilles({ ...LIBRE, enTraitement: true })).toBe(true);
  });

  test.each(["en_attente", "envoi", "envoyee"] as const)("complétion en file ou partie (%s) : verrouillés", (statut) => {
    expect(choixClientVerrouilles({ ...LIBRE, statutMutationCompletion: statut })).toBe(true);
  });

  test("complétion acceptée par le serveur : verrouillés, même sans mutation locale connue", () => {
    expect(choixClientVerrouilles({ ...LIBRE, completionEnvoyee: true })).toBe(true);
  });

  test("rejet définitif : libérés, l'employé peut redemander au client puis renvoyer", () => {
    expect(choixClientVerrouilles({ ...LIBRE, statutMutationCompletion: "echec_permanent" })).toBe(false);
  });
});
