import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { Link, useLocalSearchParams } from "expo-router";
import { useTranslation } from "react-i18next";

import { actionsDisponiblesJob, phaseDepuisStatutServeur, resoudreActionJob } from "@/ecrans/job";
import type { ActionJob, PhaseJob } from "@/ecrans/job";
import { BandeauIdentite } from "@/identite/BandeauIdentite";
import { construireArgumentsDemarrerRoute } from "@/m4/interventions";
import { obtenirContextePointageProvisoire } from "@/m4/contextePointageProvisoire";
import { construireArgumentsPointer } from "@/m4/pointage";
import { genererMutationId } from "@/outbox/id";
import { creerMutation, formaterHorodatageLocal, soumettreMutation } from "@/outbox/mutation";
import { declencherVidange, obtenirDepot } from "@/outbox/service";
import { obtenirConfigurationAppel } from "@/protocole/configuration";
import { usePersonneAppairee } from "@/roles/contexte";
import { obtenirStatutChantier } from "@/today/service";
import type { ResultatStatutChantier } from "@/today/statut";

/**
 * `job/[id]/index.tsx` (M4.7, R12 §5 étape 3, PLAN T1.4-e) : statut du chantier et transitions
 * légales (en route/arrivé/pause), par la file sortante — voir `src/ecrans/job.ts` pour la
 * décision documentée sur « démarrer » (aucune transition serveur distincte, regroupée dans
 * « arrivé », `etats.py`). Verdict serveur affiché sur un échec définitif, même patron que
 * `punch.tsx` (T1.4-d).
 *
 * Le technicien n'est plus saisi (PLAN T1.4-c5) : c'est la personne que le serveur a confirmée pour cet
 * appareil (`usePersonneAppairee`), que le serveur confronte de toute façon à l'identité du jeton.
 *
 * Écran non testé en rendu (même limite que `punch.tsx`/`today.tsx`) : `src/ecrans/job.ts`,
 * `src/today/statut.ts`, `src/m4/interventions.ts` portent la logique, testée là.
 */
export default function EcranChantier() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const interventionId = typeof id === "string" ? id : "";

  const personne = usePersonneAppairee();
  const [resultatStatut, setResultatStatut] = useState<ResultatStatutChantier | null>(null);
  const [phase, setPhase] = useState<PhaseJob | null>(null);
  const [chargementStatut, setChargementStatut] = useState(false);
  const [enTraitement, setEnTraitement] = useState(false);
  const [erreurIdentite, setErreurIdentite] = useState(false);
  const [erreurAppareil, setErreurAppareil] = useState(false);
  const [dernierVerdict, setDernierVerdict] = useState<{ code: string; detail: string } | null>(null);

  const chargerStatut = useCallback(async () => {
    if (!interventionId) {
      return;
    }
    setChargementStatut(true);
    try {
      const resultat = await obtenirStatutChantier(interventionId);
      setResultatStatut(resultat);
      const statut = resultat && resultat.source !== "aucune" ? resultat.statut : null;
      setPhase(phaseDepuisStatutServeur(statut));
    } finally {
      setChargementStatut(false);
    }
  }, [interventionId]);

  useEffect(() => {
    void chargerStatut();
  }, [chargerStatut]);

  const surAction = useCallback(
    async (action: ActionJob) => {
      if (!interventionId || phase === null) {
        return;
      }
      // Fail-closed : sans personne confirmée par le serveur, aucune mutation n'est créée (PLAN T1.4-c5).
      if (!personne) {
        setErreurIdentite(true);
        return;
      }
      const technicienId = personne;
      const resolue = resoudreActionJob(phase, action);
      if (!resolue) {
        return; // fail-closed : ne devrait pas arriver, actionsDisponiblesJob(phase) filtre déjà.
      }
      // Mission T1.4-e item 3 : même identité d'appareil PARTOUT — voir
      // src/m4/contextePointageProvisoire.ts et app/(employee)/punch.tsx.
      const configuration = obtenirConfigurationAppel();
      if (!configuration) {
        setErreurAppareil(true);
        return;
      }
      setErreurIdentite(false);
      setErreurAppareil(false);
      setEnTraitement(true);
      try {
        const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };
        const horodatageLocal = formaterHorodatageLocal(horloge);

        const payload =
          resolue.typeMutation === "job_status_change"
            ? { ...construireArgumentsDemarrerRoute(interventionId, technicienId, horodatageLocal) }
            : {
                ...construireArgumentsPointer(
                  interventionId,
                  technicienId,
                  resolue.action,
                  horodatageLocal,
                  obtenirContextePointageProvisoire(configuration.appareilId),
                ),
              };

        const brouillon = creerMutation(
          { type: resolue.typeMutation, chantierId: interventionId, payload },
          genererMutationId,
          horloge,
        );
        const enAttente = soumettreMutation(brouillon);
        const depot = await obtenirDepot();
        await depot.inserer(enAttente);

        setPhase(resolue.phaseSuivante);
        setDernierVerdict(null);

        const rapport = await declencherVidange();
        if (rapport) {
          const echec = rapport.echecsPermanents.find((e) => e.id === enAttente.id);
          if (echec) {
            setDernierVerdict(echec.verdict);
          }
        }
        await chargerStatut();
      } finally {
        setEnTraitement(false);
      }
    },
    [interventionId, phase, personne, chargerStatut],
  );

  const actions = phase !== null ? actionsDisponiblesJob(phase) : [];
  const statutAffiche = resultatStatut && resultatStatut.source !== "aucune" ? resultatStatut.statut : null;

  return (
    <View style={styles.conteneur}>
      <Text style={styles.titre}>{t("job.titre")}</Text>
      <Text style={styles.identifiant}>{interventionId}</Text>
      <BandeauIdentite />

      {chargementStatut ? <ActivityIndicator /> : null}
      <Text style={styles.statut}>
        {statutAffiche ? t(`today.statut.${statutAffiche}`) : t("job.statutInconnu")}
      </Text>
      {resultatStatut?.source === "cache" ? <Text style={styles.avis}>{t("job.source.cache")}</Text> : null}
      {resultatStatut?.source === "aucune" ? <Text style={styles.avis}>{t("job.source.aucune")}</Text> : null}

      {erreurIdentite ? <Text style={styles.erreur}>{t("identite.absente")}</Text> : null}
      {erreurAppareil ? <Text style={styles.erreur}>{t("job.appareilNonAppaire")}</Text> : null}

      <View style={styles.boutons}>
        {actions.map((action) => (
          <Pressable
            key={action}
            style={({ pressed }) => [styles.bouton, pressed ? styles.boutonPresse : null]}
            disabled={enTraitement}
            onPress={() => void surAction(action)}
          >
            <Text style={styles.boutonTexte}>{t(`job.boutons.${libelleBouton(action, phase)}`)}</Text>
          </Pressable>
        ))}
      </View>

      {enTraitement ? <ActivityIndicator /> : null}
      {dernierVerdict ? (
        <Text style={styles.erreur}>
          {t("job.verdict.echecPermanentAvecVerdict", { code: dernierVerdict.code, detail: dernierVerdict.detail })}
        </Text>
      ) : null}

      <View style={styles.liens}>
        <Link href={{ pathname: "/job/[id]/checklist", params: { id: interventionId } }} style={styles.lien}>
          {t("job.liens.checklist")}
        </Link>
        <Link href={{ pathname: "/job/[id]/photos", params: { id: interventionId } }} style={styles.lien}>
          {t("job.liens.photos")}
        </Link>
        <Link href={{ pathname: "/job/[id]/signature", params: { id: interventionId } }} style={styles.lien}>
          {t("job.liens.signature")}
        </Link>
        <Link href={{ pathname: "/job/[id]/complete", params: { id: interventionId } }} style={styles.lien}>
          {t("job.liens.complete")}
        </Link>
      </View>
    </View>
  );
}

function libelleBouton(action: ActionJob, phase: PhaseJob | null): "enRoute" | "arrive" | "pauseDebut" | "pauseFin" {
  if (action === "enRoute") {
    return "enRoute";
  }
  if (action === "arrive") {
    return "arrive";
  }
  return phase === "en_pause" ? "pauseFin" : "pauseDebut";
}

const styles = StyleSheet.create({
  conteneur: { flex: 1, padding: 16, gap: 10 },
  titre: { fontSize: 20, fontWeight: "600" },
  identifiant: { color: "#888", fontSize: 12 },
  statut: { fontSize: 18, fontWeight: "600", marginTop: 4 },
  avis: { color: "#666", fontSize: 13 },
  erreur: { color: "#b00020" },
  boutons: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  bouton: { backgroundColor: "#1c6f5c", paddingVertical: 10, paddingHorizontal: 16, borderRadius: 6 },
  boutonPresse: { opacity: 0.7 },
  boutonTexte: { color: "#fff", fontWeight: "600" },
  liens: { flexDirection: "row", gap: 16, marginTop: 16 },
  lien: { color: "#1c6f5c", fontWeight: "600" },
});
