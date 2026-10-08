import type { CashLibreDeM8 } from "../m8/vueExecutive";
import { COMPOSANTES_DU_CASH_LIBRE } from "../m5/tresorerie";
import { libelleDeCatalogue, message, montantOuTexte } from "./adminCommun";
import type { Message } from "./adminCommun";
import type { LangueMontant } from "./quotes";
import { texteSansChemin } from "./texteSur";

export interface VueComposanteConstatM8 {
  readonly id: string;
  readonly libelle: Message;
  readonly valeur: Message;
  readonly plancher: Message | null;
}

export interface VueCashConstatM8 {
  readonly genre: "manque" | "inconnu" | "lu";
  readonly lignes: readonly Message[];
  /** Les trois textes dédiés ci-dessous, s'ils sont montrables ; ne pas les rendre une seconde fois. */
  readonly textes: readonly string[];
  readonly composantes: readonly VueComposanteConstatM8[];
  readonly manques: readonly Message[];
  readonly reserves: readonly Message[];
  readonly lecture: string | null;
  readonly mention: string | null;
  readonly nonRepris: string | null;
}

const COMPOSANTES = ["solde", ...COMPOSANTES_DU_CASH_LIBRE];
/** Valeur exacte fermée du catalogue m5.cash_libre_constate.json : ces barres séparent les validateurs,
 * et ne désignent pas un chemin. Toute autre mention passe par le filtre partagé. */
const MENTION_M5 = "Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle.";
const m = (cle: string, params?: Message["params"]): Message => message(`admin.cashConstatM8.${cle}`, params);
function mentionSure(texte: string): string | null {
  return texte === MENTION_M5 ? texte : texteSansChemin(texte);
}
/** Le `$` après les chiffres est le symbole monétaire du texte natif. On valide une copie où seuls ces
 * marqueurs deviennent CAD ; le texte original reste celui de M5. $(...), $HOME, chemins et commandes
 * restent visibles au filtre et donc masqués. Aucun montant n'est lu ni transformé en nombre. */
function lectureSure(texte: string): string | null {
  const verification = texte.replace(/\b([0-9]+(?:\.[0-9]+)?)\s*\$(?=$|[\s.,;:!?)])/g, "$1 CAD");
  return texteSansChemin(verification) === null ? null : texte;
}
function vueVide(genre: VueCashConstatM8["genre"], lignes: readonly Message[]): VueCashConstatM8 {
  return { genre, lignes, textes: [], composantes: [], manques: [], reserves: [],
    lecture: null, mention: null, nonRepris: null };
}
function lignesFiltrees(textes: readonly string[], cle: string, variable: string, masquee: string): readonly Message[] {
  return textes.map((texte) => {
    const sur = texteSansChemin(texte);
    return sur === null ? m(masquee) : m(cle, { [variable]: sur });
  });
}

/** Modèle pur T4.19-c du constat M5 repris par M8. Les montants, flags et âges sont ceux du DTO validé,
 * sans somme, signe inféré, âge recalculé ni seuil. Les dates sont civiles : aucun décalage de fuseau.
 * Le renvoi à Trésorerie reste informatif ; aLire n'est ni rendu en commande ni une action. */
export function presenterCashConstatM8(
  cash: CashLibreDeM8,
  langue: LangueMontant,
  _decalage: number,
): VueCashConstatM8 {
  if (cash.genre === "inconnu") {
    const statut = texteSansChemin(cash.statut);
    return vueVide("inconnu", [statut === null ? m("statutMasque") : m("inconnu", { statut }), m("renvoiTresorerie")]);
  }
  const source = texteSansChemin(cash.source);
  const lignes: Message[] = [source === null ? m("sourceMasquee") : m("source", { source })];
  if (cash.genre === "manque") {
    return { ...vueVide("manque", [...lignes, m("manque"), m("renvoiTresorerie")]),
      manques: lignesFiltrees(cash.manque, "manqueLigne", "manque", "manqueMasque") };
  }

  const c = cash.constat;
  lignes.push(m("nConstats", { nombre: cash.nConstatsRecus }), m("constat", { sequence: c.sequence, date: c.dateReference }));
  if (cash.age.jours !== null && cash.age.aujourdHui !== null) {
    lignes.push(m("age", { jours: cash.age.jours, jour: cash.age.aujourdHui }));
  } else {
    if (cash.age.aujourdHui !== null) lignes.push(m("jourAge", { jour: cash.age.aujourdHui }));
    const raison = texteSansChemin(cash.age.raison);
    lignes.push(raison === null ? m("ageRaisonMasquee") : m("ageInconnu", { raison }));
  }
  lignes.push(m(c.statut));

  const mention = mentionSure(c.mention);
  const lecture = mention === null ? null : lectureSure(c.lecture);
  const nonRepris = texteSansChemin(cash.nonRepris);
  if (lecture === null && mention !== null) lignes.push(m("lectureMasquee"));
  if (mention === null) lignes.push(m("mentionMasquee"));
  if (nonRepris === null) lignes.push(m("nonReprisMasque"));
  const composantes: VueComposanteConstatM8[] = [];
  // Aucun chiffre n'est montré sans la mention qui qualifie les analyses financières de M5.
  if (mention !== null) {
    if (c.cashLibreCad !== null) lignes.push(m("montant", { montant: montantOuTexte(c.cashLibreCad, langue) }));
    if (c.auPlusCad !== null) lignes.push(m("auPlus", { montant: montantOuTexte(c.auPlusCad, langue) }));
    if (c.enDeficit === true) lignes.push(m("deficit"));
    if (c.composantes !== null) {
      for (const [id, montant] of Object.entries(c.composantes)) {
        const plancher = c.planchersCad?.[id];
        composantes.push({ id, libelle: libelleDeCatalogue("admin.chiffres.composantes", id, COMPOSANTES),
          valeur: montant === null ? message("admin.chiffres.composante.nonCalculable") :
            message("admin.chiffres.composante.montant", { montant: montantOuTexte(montant, langue) }),
          plancher: plancher === undefined ? null :
            message("admin.chiffres.composante.plancher", { montant: montantOuTexte(plancher, langue) }) });
      }
    }
  }
  if (c.composantesOmises !== null) lignes.push(m("composantesOmises", { nombre: c.composantesOmises }));
  lignes.push(m("renvoiTresorerie"));
  return { genre: "lu", lignes, composantes,
    manques: lignesFiltrees(c.manque, "manqueLigne", "manque", "manqueMasque"),
    reserves: lignesFiltrees(c.reserves, "reserve", "code", "reserveMasquee"),
    lecture, mention, nonRepris,
    textes: [lecture, mention, nonRepris].filter((texte): texte is string => texte !== null) };
}
