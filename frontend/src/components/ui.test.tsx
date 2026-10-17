import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { demoAnswer } from "../test/fixtures";
import { AnswerView } from "./ui";

describe("AnswerView", () => {
  it('does not auto-fetch remote images from model/source Markdown', () => {
    const { container } = render(<AnswerView privateEvidence markdown={'![private diagram](https://evil.example/track)'} onCitation={() => undefined} />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText(/private diagram/)).toBeInTheDocument();
  });
  it("renders grounded answer signals and opens inline citations", () => {
    const openCitation = vi.fn();
    render(<AnswerView answer={demoAnswer} markdown={demoAnswer.markdown} onCitation={openCitation} />);
    expect(screen.getByText("Core idea")).toBeInTheDocument();
    expect(screen.getAllByText("verified")).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: /open citation/i })[0]);
    expect(openCitation).toHaveBeenCalled();
  });

  it("does not render unsafe model-authored HTML", () => {
    const { container } = render(<AnswerView markdown={'<script>alert("x")</script>\n\nSafe text'} onCitation={() => undefined} />);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("Safe text")).toBeInTheDocument();
  });
});
