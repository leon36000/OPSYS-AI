import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";
import { useSessionAppareil } from "../roles/contexte";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import { rechercherAffaireMemoire } from "../m10/service";
import { construireArgumentsRechercheAffaire } from "../m10/rechercheAffaire";
import type { RechercheAffaireM10 } from "../m10/rechercheAffaire";
import type { ResultatSection } from "./lecture";
import { presenterSection } from "../ecrans/adminCommun";
import { presenterRechercheAffaire } from "../ecrans/rechercheAffaire";
import { BoutonSecondaire, Carte, EtatSection, Lignes, stylesAdmin as styles } from "./composants";

interface Props {
  readonly connected: boolean;
  readonly bloque: boolean;
  readonly autorisee: () => boolean;
  readonly onOuvrir: (affaireId: string) => void;
  readonly onInvalider: () => void;
}
/** Lecture indépendante : aucune intention, aucun cache et aucune modification du contrôleur d'arbitrage. */
export function RechercheAffaireM10({ connected, bloque, autorisee, onOuvrir, onInvalider }: Props) {
  const { t } = useTranslation();
  const session = useSessionAppareil();
  const [affaire, setAffaire] = useState("");
  const [requete, setRequete] = useState("");
  const [resultat, setResultat] = useState<ResultatSection<RechercheAffaireM10>>();
  const [enCours, setEnCours] = useState(false);
  const generation = useRef(0);
  const garde = useRef<(() => boolean) | null>(null);
  const gardeSaisie = useRef<(() => boolean) | null>(null);
  const captureRendu = capturerSessionAdminLecture();
  const generationRendu = generation.current;
  const dernieresProps = useRef({ connected, bloque, autorisee, onInvalider });
  dernieresProps.current = { connected, bloque, autorisee, onInvalider };
  const invalider = useCallback(() => {
    ++generation.current; garde.current = null; setResultat(undefined); setEnCours(false);
    dernieresProps.current.onInvalider();
  }, []);
  useEffect(() => { invalider(); return () => { ++generation.current; garde.current = null; }; }, [connected, invalider]);
  useEffect(() => {
    gardeSaisie.current = null; setAffaire(""); setRequete(""); invalider();
    return () => { ++generation.current; garde.current = null; gardeSaisie.current = null; };
  }, [session, invalider]);
  function changer(valeur: string, champ: "affaire" | "requete") {
    if (!captureRendu.session || !captureRendu.courante()) return;
    const ancienneSaisieCourante = gardeSaisie.current?.() === true;
    invalider();
    if (!ancienneSaisieCourante) { setAffaire(""); setRequete(""); }
    gardeSaisie.current = captureRendu.courante;
    if (champ === "affaire") setAffaire(valeur); else setRequete(valeur);
  }
  // Une nouvelle identité ne voit ni n'envoie les champs d'une garde devenue obsolète.
  const affaireVisible = gardeSaisie.current?.() === true ? affaire : "";
  const requeteVisible = gardeSaisie.current?.() === true ? requete : "";
  let argumentsValides = false;
  try { construireArgumentsRechercheAffaire(affaireVisible, requeteVisible); argumentsValides = true; } catch { /* saisie à compléter */ }
  async function rechercher(decalage = 0) {
    const p = dernieresProps.current;
    if (!captureRendu.session || !captureRendu.courante() || generationRendu !== generation.current ||
        !p.connected || p.bloque || !p.autorisee() || enCours) return;
    let args;
    try { args = construireArgumentsRechercheAffaire(affaireVisible, requeteVisible, decalage); } catch { return; }
    const capture = captureRendu;
    if (!capture.session || !capture.courante()) { invalider(); return; }
    const n = ++generation.current;
    garde.current = capture.courante;
    const courante = () => n === generation.current && capture.courante() && dernieresProps.current.connected && dernieresProps.current.autorisee();
    setResultat(undefined); setEnCours(true); p.onInvalider();
    try {
      const r = await rechercherAffaireMemoire(args.affaire_id, args.requete, args.decalage);
      if (courante()) setResultat(r?.source === "cache" || r === null ?
        { source: "aucune", raison: { code: "lecture_indisponible", detail: "" } } : r);
    } catch {
      if (courante()) setResultat({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } });
    } finally { if (courante()) setEnCours(false); }
  }
  const permis = connected && !bloque && autorisee();
  const visible = connected && autorisee() && garde.current?.() === true;
  const page = visible && resultat?.source === "serveur" ? resultat.valeur : null;
  return <Carte>
    <Text style={styles.sousTitre}>{t("admin.rechercheAffaire.titre")}</Text>
    <Text style={styles.avis}>{t("admin.rechercheAffaire.note")}</Text>
    <TextInput accessibilityLabel={t("admin.rechercheAffaire.saisieAffaire")} placeholder={t("admin.rechercheAffaire.saisieAffaire")}
      value={affaireVisible} onChangeText={v => changer(v, "affaire")} autoCapitalize="none" autoCorrect={false} editable={permis} />
    <TextInput accessibilityLabel={t("admin.rechercheAffaire.saisieRequete")} placeholder={t("admin.rechercheAffaire.saisieRequete")}
      value={requeteVisible} onChangeText={v => changer(v, "requete")} autoCapitalize="none" autoCorrect={false} editable={permis} />
    {(affaireVisible !== "" || requeteVisible !== "") && !argumentsValides ? <Text style={styles.avis}>{t("admin.rechercheAffaire.saisieInvalide")}</Text> : null}
    <BoutonSecondaire texte={t("admin.rechercheAffaire.rechercher")} desactive={!permis || enCours || !argumentsValides} onPress={() => void rechercher()} />
    {!connected ? <Text style={styles.avis}>{t("admin.rechercheAffaire.horsLigne")}</Text> : null}
    {visible && enCours ? <ActivityIndicator /> : null}
    {visible && !enCours && resultat ? <EtatSection vue={presenterSection(resultat, -new Date().getTimezoneOffset(), presenterRechercheAffaire)} rendre={v => <>
      <Lignes items={v.lignes} />
      {v.resultats.map(r => <View key={r.cle}><Lignes items={r.lignes} /></View>)}
      {page?.affaire.connue ? <BoutonSecondaire texte={t("admin.paquetAffaire.ouvrir")} desactive={!permis}
        onPress={() => {
          if (generationRendu === generation.current && captureRendu.courante() && dernieresProps.current.connected &&
              !dernieresProps.current.bloque && dernieresProps.current.autorisee() && garde.current?.()) onOuvrir(page.affaire_id);
        }} /> : null}
      {page?.pagination.suivant !== null && page?.pagination.suivant !== undefined ?
        <BoutonSecondaire texte={t("admin.rechercheAffaire.suite")} desactive={!permis}
          onPress={() => void rechercher(page.pagination.suivant!)} /> : null}
    </>} /> : null}
  </Carte>;
}
