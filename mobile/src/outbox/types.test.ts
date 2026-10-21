import type { TypeMutation } from "./types";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
test("P et D ont deux types distincts et des RPC exacts, sans altérer la décision générique", () => {
  const types: TypeMutation[] = ["completion_review_proposal", "completion_review_decision", "approval_decision"];
  expect(types.map(t => DESCRIPTEURS_MUTATION.get(t)?.tool)).toEqual([
    "m4_resoudre_revue_completion_sources", "m9_decider_demande_approbation", "m9_decider_demande_approbation",
  ]);
});
