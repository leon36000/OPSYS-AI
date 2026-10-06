import { estObjet, lireEnveloppeMetier } from "../protocole/enveloppeOutil";
import { lireListeM7, lireOwnerM9 } from "./contrat";
import type { AppelM7, LigneContenuM7, SessionM7 } from "./contrat";

export interface EtatMarketing {
  readonly statut:
    | "inactif"
    | "chargement"
    | "pret"
    | "hors_ligne"
    | "erreur"
    | "decision_en_cours"
    | "decision_incertaine"
    | "relecture_impossible";
  readonly items: readonly LigneContenuM7[];
  readonly owner: boolean;
  readonly message: string | null;
  readonly suivant: number | null;
  readonly reste: number;
  readonly marqueCourante?: import("./contrat").PreuveMarqueM7 | null;
}

export interface DependancesMarketing {
  readonly obtenirSession: () => SessionM7 | null;
  readonly enLigne: () => boolean;
  readonly appeler: AppelM7;
  readonly maintenant: () => string;
  readonly genererId: () => string;
}

function etatVide(statut: "inactif" | "hors_ligne" | "erreur", message: string | null = null): EtatMarketing {
  return { statut, items: [], owner: false, message, suivant: null, reste: 0 };
}

export function creerControleMarketing(d: DependancesMarketing) {
  let state: EtatMarketing = etatVide("inactif");
  let generation = 0;
  let busy = false;
  let sessionCle: string | null = null;
  let online = false;

  function cle(session: SessionM7 | null): string | null {
    return session
      ? `${session.urlBase}\0${session.jeton}\0${session.appareilId}\0${session.personne}`
      : null;
  }

  function etat(): EtatMarketing {
    if (!online) return state.statut === "inactif" ? state : etatVide("hors_ligne", "Connexion indisponible.");
    if (sessionCle !== null && cle(d.obtenirSession()) !== sessionCle) return etatVide("inactif");
    return state;
  }

  function actualiserConnectivite(connectee: boolean): void {
    if (online === connectee) return;
    online = connectee;
    if (!connectee) {
      generation++;
      state = etatVide("hors_ligne", "Connexion indisponible.");
    }
  }

  function invalider(): void {
    generation++;
    sessionCle = null;
    state = etatVide("inactif");
    // `busy` reste verrouillé jusqu'à la fin de la mutation en vol.
  }

  function invaliderSiIdentiteChangee(captured: string, run: number): boolean {
    if (run !== generation) return true;
    if (cle(d.obtenirSession()) !== captured) {
      invalider();
      return true;
    }
    return false;
  }

  async function chargerInterne(offset: number, lectureDeMutation = false): Promise<void> {
    if (busy && !lectureDeMutation) return;

    const session = d.obtenirSession();
    const captured = cle(session);
    if (!session || !captured || !online || !d.enLigne()) {
      state = etatVide(session ? "hors_ligne" : "inactif", session ? "Connexion indisponible." : null);
      return;
    }

    if (sessionCle !== null && sessionCle !== captured) {
      generation++;
      state = etatVide("inactif");
    }
    sessionCle = captured;
    const run = ++generation;
    state = {
      ...state,
      statut: lectureDeMutation ? "decision_en_cours" : "chargement",
      items: offset === 0 ? [] : state.items,
      owner: false,
      message: null,
    };

    try {
      let owner = lireOwnerM9({});
      try {
        owner = lireOwnerM9(await d.appeler("m9_lister_demandes_approbation", {}));
      } catch {
        // M7 reste lisible pour un admin, mais aucune décision n'est offerte sans preuve M9.
      }
      if (invaliderSiIdentiteChangee(captured, run)) return;

      const parsed = lireListeM7(
        await d.appeler("m7_lister_contenus_chantier", { limite: 8, decalage: offset }),
      );
      if (invaliderSiIdentiteChangee(captured, run)) return;
      if (!online || !d.enLigne()) {
        state = etatVide("hors_ligne", "Connexion indisponible.");
        return;
      }
      if (!parsed.ok || parsed.value.decalage !== offset) {
        state = { ...etatVide("erreur", "La réponse du serveur est invalide. Rechargez la liste.") };
        return;
      }

      const items = offset ? [...state.items, ...parsed.value.items] : [...parsed.value.items];
      if (new Set(items.map((item) => item.contenu_id)).size !== items.length) {
        state = etatVide("erreur", "Pagination périmée; rechargez la liste.");
        return;
      }
      state = {
        statut: "pret",
        items,
        owner: owner.ok && owner.value,
        message: null,
        suivant: parsed.value.suivant,
        reste: parsed.value.reste,
        marqueCourante: parsed.value.marqueCourante,
      };
    } catch (error) {
      // Temporary diagnostic while validating readback paths.
      if (run === generation) state = etatVide("erreur", "Lecture serveur impossible.");
    }
  }

  async function charger(offset = 0): Promise<void> {
    return chargerInterne(offset);
  }

  function peutDecider(item: LigneContenuM7): boolean {
    const visible = etat();
    const current = visible.marqueCourante;
    const present = visible.items.some(
      (candidate) => candidate.contenu_id === item.contenu_id && candidate.revision === item.revision,
    );
    const proofMatches = item.marque_source !== null && current !== null && current !== undefined &&
      item.marque_source.source === current.source &&
      item.marque_source.revision === current.revision &&
      item.marque_source.sha256 === current.sha256;

    return !busy && online && d.enLigne() && cle(d.obtenirSession()) === sessionCle &&
      visible.statut === "pret" && visible.owner && present &&
      item.approval_status === "PROPOSE" && item.fraicheur_marque === "courante" && proofMatches;
  }

  async function decider(id: string, decision: "approuver" | "rejeter", motif = "") {
    const visible = etat();
    const original = visible.items.find((item) => item.contenu_id === id);
    const session = d.obtenirSession();
    const captured = cle(session);
    const motifNettoye = motif.trim();
    if (decision === "rejeter" && (motifNettoye.length < 5 || motifNettoye.length > 500)) {
      state = { ...visible, message: "Le motif doit contenir entre 5 et 500 caractères." };
      return { ok: false as const, code: "motif_invalide" };
    }
    if (busy || !session || captured !== sessionCle || !online || !d.enLigne() ||
      !original || !peutDecider(original)) {
      return { ok: false as const, code: "action_indisponible" };
    }

    busy = true;
    const mutationGeneration = generation;
    state = { ...visible, statut: "decision_en_cours", message: null };
    let incertaine = false;
    let acceptee = false;
    let refusee = false;

    try {
      const timestamp = d.maintenant();
      const args = {
        contenu_id: id,
        decision,
        horodatage: timestamp,
        ...(decision === "rejeter" ? { motif: motifNettoye } : {}),
      };
      const raw = await d.appeler("m7_decider_contenu", args, {
        idempotencyKey: d.genererId(),
        deviceId: session.appareilId,
        deviceTimestamp: timestamp,
      });
      const resultat = lireEnveloppeMetier(raw);
      if (resultat.ok && estObjet(resultat.valeur) &&
        resultat.valeur.contenu_id === id &&
        resultat.valeur.approval_status === (decision === "approuver" ? "APPROVED" : "REJECTED") &&
        resultat.valeur.plateforme === original.plateforme &&
        resultat.valeur.par === session.personne &&
        resultat.valeur.source === "appareil" &&
        typeof resultat.valeur.horodatage === "string" && resultat.valeur.horodatage.trim() !== "" &&
        typeof resultat.valeur.empreinte_texte === "string" && /^[0-9a-f]{64}$/.test(resultat.valeur.empreinte_texte) &&
        typeof resultat.valeur.prochaine_etape === "string" && resultat.valeur.prochaine_etape.trim() !== "") {
        acceptee = true;
      } else if (!resultat.ok && resultat.genre === "refus") {
        refusee = true;
      } else {
        incertaine = true;
      }
    } catch {
      incertaine = true;
    }

    if (mutationGeneration !== generation || cle(d.obtenirSession()) !== captured) {
      busy = false;
      return { ok: false as const, code: "identite_changee" };
    }

    // Garder le verrou jusqu'au bout de la relecture empêche une action concurrente.
    await chargerInterne(0, true);
    busy = false;
    const relu = etat();
    if (cle(d.obtenirSession()) !== captured || relu.statut === "inactif") {
      return { ok: false as const, code: "identite_changee" };
    }
    if (relu.statut !== "pret") {
      if (relu.statut === "hors_ligne") return { ok: false as const, code: "relecture_impossible" };
      state = {
        ...relu,
        statut: "relecture_impossible",
        owner: false,
        message: "Décision envoyée ou incertaine; relecture impossible. Ne pas renvoyer.",
        items: [],
        suivant: null,
        reste: 0,
      };
      return { ok: false as const, code: "relecture_impossible" };
    }

    const observed = relu.items.find((item) => item.contenu_id === id);
    const statusAttendu = decision === "approuver" ? "APPROVED" : "REJECTED";
    if (incertaine || (acceptee && !observed) ||
      (acceptee && observed?.approval_status !== statusAttendu && observed?.approval_status !== "CONSENTEMENT_RETIRE")) {
      state = {
        ...relu,
        statut: "decision_incertaine",
        owner: false,
        message: "Réponse de décision incertaine; l’état a été relu. Aucun renvoi automatique.",
        suivant: null,
      };
      return { ok: false as const, code: "decision_incertaine" };
    }
    if (acceptee && observed?.approval_status === "CONSENTEMENT_RETIRE") {
      state = { ...relu, message: "Consentement retiré; le contenu reste bloqué." };
    } else if (refusee) {
      state = { ...relu, message: "Décision refusée par le serveur; la liste a été relue." };
    }
    return { ok: acceptee, code: acceptee ? "relue" : "refus_serveur_relue" };
  }

  function chargerSuite(): Promise<void> {
    const visible = etat();
    if (busy || visible.suivant === null) return Promise.resolve();
    return chargerInterne(visible.suivant);
  }

  return { etat, charger, chargerSuite, decider, peutDecider, invalider, actualiserConnectivite };
}
