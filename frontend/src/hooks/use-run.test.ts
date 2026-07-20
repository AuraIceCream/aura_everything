import { describe, expect, it } from "vitest";
import { demoAnswer, traceEvents } from "../lib/mock-data";
import { initialRunState, runReducer } from "./use-run";

describe("runReducer", () => {
  it("preserves streamed text and trace events until completion", () => {
    let state = runReducer(initialRunState, { type: "start" });
    state = runReducer(state, { type: "created", runId: "run-1" });
    state = runReducer(state, { type: "trace", event: traceEvents[0] });
    state = runReducer(state, { type: "answer.delta", delta: "Evidence " });
    state = runReducer(state, { type: "answer.delta", delta: "matters." });
    expect(state.markdown).toBe("Evidence matters.");
    expect(state.trace).toHaveLength(1);
    state = runReducer(state, { type: "answer.completed", answer: demoAnswer });
    expect(state.status).toBe("complete");
    expect(state.answer?.citations).toHaveLength(3);
  });

  it("moves a malformed or disconnected run into a safe failure state", () => {
    const state = runReducer(initialRunState, { type: "run.failed", error: "Stream disconnected" });
    expect(state.status).toBe("failed");
    expect(state.error).toMatch(/disconnected/);
  });
});

