import { message } from "./adminCommun";
import type { Message } from "./adminCommun";
import { jetonSur } from "./texteSur";

/**
 * Ce que le propriétaire lit d'un MANQUE de M4 (`m4_verifier_preparation`, volet par volet) : ce qu'il faut faire, en mots
 * simples, dans les deux langues de l'app (PLAN T1.4-n). Logique PURE, testée (`manquesM4.test.ts`).
 *
 * **Le texte de M4 n'est jamais montré.** Le `manque` d'un volet est écrit pour un AGENT : il cite le fichier du serveur où
 * écrire (`/srv/opsys/entreprise.yaml`), les commandes à taper (`opsys-metier equipes declarer --depuis <fichier> --par ...`)
 * et des pages de documentation. Un propriétaire sur son téléphone n'a rien à faire de tout cela, et un chemin du serveur ne
 * quitte pas le serveur. L'app le REMPLACE par une phrase qu'elle possède, choisie par le CODE du manque :
 *  - le code d'un volet est son `detail` quand c'est un code (`REJ-EQUIPES-NON-CONFIGUREES`, `partiel`...) ; un manque sans
 *    code (`detail` absent : « aucune équipe admissible », un volet non vérifiable) se dit par son volet et son statut
 *    seulement ; un `detail` PRÉSENT qui n'est pas un code (une phrase, un chemin) n'est pas « aucun code » : M4 ne le
 *    produit pas, l'app ne devine donc pas et dit « à configurer côté serveur » ;
 *  - `MANQUES_CONNUS` associe (volet, statut, code) à un texte ; la table est épinglée à ce que M4 sait produire par
 *    `tests/e2e/test_manques_m4_appareil.py` ;
 *  - un manque que la table ne connaît pas (une version plus récente du serveur) donne « à configurer côté serveur » avec son
 *    code, JAMAIS le texte brut.
 *
 * Un code n'est montré que s'il est un JETON (lettres, chiffres, `_`, `.`, `-`) : une phrase, un chemin ou une commande n'en
 * sont jamais un.
 */

/**
 * (volet : statut : code) -> clé du texte (`admin.chantiers.manques.<clé>`). Le code est vide pour un manque qui n'en a pas.
 * Chaque entrée est une sortie réelle de `preparation.py` ; ajouter un manque à M4 sans l'ajouter ici le fait dire « à
 * configurer côté serveur » (`inconnu`), avec son code, et fait échouer l'E2E qui épingle cette table.
 */
export const MANQUES_CONNUS: Readonly<Record<string, string>> = {
  "soumission:manque:": "soumission.absente",
  "adresse:manque:REJ-COORDONNEES-A-CONFIRMER": "adresse.aConfirmer",
  "adresse:manque:REJ-LOCALISATION-DETRUITE": "adresse.detruite",
  "equipe:manque:REJ-EQUIPES-NON-CONFIGUREES": "equipe.nonDeclarees",
  "equipe:manque:REJ-PROFIL-INVALIDE": "equipe.profilInvalide",
  "equipe:manque:REJ-CHAMP-MANQUANT": "equipe.reglagesIncomplets",
  "equipe:manque:": "equipe.aucuneAdmissible",
  "equipe:non_verifiable:": "equipe.nonVerifiable",
  "materiel:manque:partiel": "materiel.partiel",
  "materiel:manque:a_commander": "materiel.aCommander",
  "materiel:non_verifiable:": "materiel.nonVerifiable",
  "meteo:manque:REJ-METEO-NON-CONFIGUREE": "meteo.nonDeclarees",
  "meteo:manque:REJ-PROFIL-INVALIDE": "meteo.profilInvalide",
  "meteo:manque:REJ-CHAMP-MANQUANT": "meteo.seuilsIncomplets",
  "meteo:non_verifiable:": "meteo.nonVerifiable",
};

export interface ManqueDit {
  /** Ce qu'il faut faire, en mots simples (une clé i18n de l'app). */
  readonly texte: Message;
  /** Le code du manque, seulement s'il est un jeton sûr : pour le support, jamais le texte de M4. */
  readonly code: Message | null;
  /** `false` : la table ne connaît pas ce manque ; le texte est « à configurer côté serveur ». */
  readonly connu: boolean;
}

export interface ManqueAExprimer {
  readonly nom: string;
  readonly statut: string;
  /** Le `detail` du volet tel que M4 l'a écrit : `null` (M4 ne donne aucun code) ou une chaîne, dont seul un code sûr sert. */
  readonly detail: string | null;
}

/** Dit le manque d'un volet qui n'est pas prêt. Un volet prêt n'a aucun manque : appeler cette fonction pour lui est une
 * erreur de l'appelant (`presenterVolet` ne le fait jamais). */
export function direLeManque(volet: ManqueAExprimer): ManqueDit {
  const code = jetonSur(volet.detail);
  // « Aucun code » n'est que `null` : une chaîne qui n'est pas un code (vide, phrase, chemin) ne tombe jamais sur une entrée sans code.
  const cle = volet.detail !== null && code === null ? undefined : MANQUES_CONNUS[`${volet.nom}:${volet.statut}:${code ?? ""}`];
  const messageDuCode = code === null ? null : message("admin.chantiers.manques.code", { code });
  if (cle !== undefined) {
    return { texte: message(`admin.chantiers.manques.${cle}`), code: messageDuCode, connu: true };
  }
  // Le code montré est celui du serveur s'il en donne un ; sinon le volet et son statut, jamais son texte.
  const montre = code ?? `${jetonSur(volet.nom) ?? "?"}/${jetonSur(volet.statut) ?? "?"}`;
  return { texte: message("admin.chantiers.manques.inconnu", { code: montre }), code: messageDuCode, connu: false };
}
