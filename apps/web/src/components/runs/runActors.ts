/* The run's agents/phases as named actors, for the Live Workbench activity
   timeline. Only "Quincy" (PM) is an established persona (see PmMessage);
   the rest are display labels for the other graph roles/phases and are
   trivially adjustable. A milestone is one honest line about work that
   actually happened — never model chatter. */

import buildArt from "../../assets/personas/build.webp";
import deliverArt from "../../assets/personas/deliver.webp";
import designArt from "../../assets/personas/design.webp";
import engineArt from "../../assets/personas/engine.webp";
import gateArt from "../../assets/personas/gate.webp";
import planArt from "../../assets/personas/plan.webp";
import reviewArt from "../../assets/personas/review.webp";
import testArt from "../../assets/personas/test.webp";

export interface RunActor {
  /** Display name shown in the timeline. */
  actor: string;
  /** Present-tense label while the node is the active phase. */
  active: string;
  /** Past-tense label once the node has produced its update. */
  done: string;
}

export const RUN_ACTORS: Record<string, RunActor> = {
  plan: { actor: "The Chart-Maker", active: "is planning the work", done: "prepared the plan" },
  design: { actor: "The Architect", active: "is designing the approach", done: "prepared the design" },
  supervise: { actor: "The Chart-Maker", active: "is re-scoping the work", done: "re-scoped the work" },
  author_tests: {
    actor: "The Assayer",
    active: "is authoring the acceptance tests",
    done: "authored the acceptance tests",
  },
  implement: { actor: "The Smith", active: "is implementing the change", done: "implemented the change" },
  quality_revise: { actor: "The Smith", active: "is revising for quality", done: "revised for quality" },
  capture: { actor: "The Smith", active: "is summarizing the work", done: "summarized the work" },
  test: { actor: "The Engine", active: "is running validation", done: "ran validation" },
  hygiene: {
    actor: "The Engine",
    active: "is tidying up (format, lint and types)",
    done: "tidied up the code",
  },
  hygiene_fix: {
    actor: "The Smith",
    active: "is fixing lint and type issues",
    done: "fixed the lint and type issues",
  },
  scan: { actor: "The Engine", active: "is scanning for secrets", done: "scanned for secrets" },
  review: { actor: "The Tribune", active: "is reviewing the change", done: "reviewed the change" },
  review_fix: {
    actor: "The Smith",
    active: "is addressing the review feedback",
    done: "addressed the review feedback",
  },
  fix: { actor: "The Smith", active: "is fixing the failing tests", done: "picked up the failing tests" },
  reason: {
    actor: "The Smith",
    active: "is reasoning about the stall",
    done: "reasoned about the stall",
  },
  critic: { actor: "The Critic", active: "is judging the outcome", done: "judged the outcome" },
  gate: { actor: "Justice", active: "is evaluating the delivery gate", done: "evaluated the gate" },
  deliver: { actor: "Mercury", active: "is delivering", done: "delivered the change" },
};

export function actorFor(node: string): RunActor {
  return RUN_ACTORS[node] ?? { actor: node, active: `is running ${node}`, done: `ran ${node}` };
}

/* The renaissance engravings (2026-08-13). Full-body portraits; circular avatar
   crops show the head via object-top. Only The Critic has no art — AgentAvatar
   falls back to a monogram at the same box size, so rows stay aligned. */
export const ACTOR_AVATARS: Record<string, string> = {
  "The Chart-Maker": planArt,
  "The Architect": designArt,
  "The Assayer": testArt,
  "The Smith": buildArt,
  "The Engine": engineArt,
  "The Tribune": reviewArt,
  Justice: gateArt,
  Mercury: deliverArt,
  // The PM chat persona keeps its product name; same art as the planner stage.
  Quincy: planArt,
};

export function avatarFor(actor: string): string | undefined {
  return ACTOR_AVATARS[actor];
}

/** Fine-grained coder tool milestones (from the implement node's activity
 *  stream). All are Forge (the coder) doing real work — never model chatter. */
const ACTIVITY_VERB: Record<string, string> = {
  file_read: "read",
  file_written: "wrote",
  file_deleted: "deleted",
  search: "searched for",
  list_files: "surveyed the repo",
  running_validation: "ran validation",
  sandbox_exec: "ran in the sandbox",
};

export function activityLine(kind: string, detail?: string): string {
  const verb = ACTIVITY_VERB[kind] ?? kind.replace(/_/g, " ");
  return detail ? `${verb} ${detail}` : verb;
}
