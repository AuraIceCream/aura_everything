import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Calculator, GitCompareArrows, ListOrdered, Target } from "lucide-react";
import { api } from "../lib/api";
import { Metric, PageHeader, StatusPill } from "../components/ui";
import type { EvaluationSummary } from "../types";

const label = (key: string) => key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function EvaluationPage() {
  const summary = useQuery({ queryKey: ["evaluation-summary"], queryFn: api.evaluationSummary });

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Evaluation"
        title="Benchmark and ablation"
        description="A curated biology question set for comparing the baseline model, basic RAG, the full pipeline, and the finetuned system on the same questions."
        action={<StatusPill tone="info">Deterministic grading</StatusPill>}
      />
      {summary.data && <EvaluationBody data={summary.data} />}
    </div>
  );
}

function EvaluationBody({ data }: { data: EvaluationSummary }) {
  const subdomains = Object.entries(data.by_subdomain).map(([name, count]) => ({
    name: label(name).replace("Biology", "Bio").replace("Developmental", "Dev"),
    count,
  }));
  const maxSub = Math.max(...subdomains.map((s) => s.count));

  return (
    <>
      <section className="metrics-grid">
        <Metric label="Benchmark questions" value={String(data.total)} helper="18 subdomains" />
        <Metric label="Numerical items" value={String(data.numeric_items)} helper="SymPy-checked" />
        <Metric label="Process-order items" value={String(data.process_items)} helper="Step sequence checked" />
        <Metric label="Adversarial items" value={String(data.adversarial_items)} helper="Hallucination bait" />
      </section>

      <section className="ablation-card">
        <div className="section-heading">
          <div><span className="eyebrow">SRS 25 ablation</span><h2>Four systems, one question set</h2></div>
          <span>Results populate once the local model is connected</span>
        </div>
        <div className="ablation-grid">
          {data.systems.map((system, index) => (
            <article key={system.id} className="ablation-system">
              <span className="ablation-index">0{index + 1}</span>
              <div>
                <strong>{system.label}</strong>
                <small>{system.detail}</small>
              </div>
              <StatusPill tone={index === 0 ? "danger" : index === data.systems.length - 1 ? "success" : "warning"}>
                config {system.srs_config}
              </StatusPill>
            </article>
          ))}
        </div>
        <div className="ablation-metrics">
          <span className="eyebrow">Metrics compared</span>
          <div className="metric-chips">
            <span><Target size={13} /> Concept recall</span>
            <span><Calculator size={13} /> Numeric accuracy</span>
            <span><ListOrdered size={13} /> Process order</span>
            <span><AlertTriangle size={13} /> Hallucination rate</span>
            <span><GitCompareArrows size={13} /> Faithfulness</span>
          </div>
        </div>
      </section>

      <section className="corpus-chart-card">
        <div className="section-heading">
          <div><span className="eyebrow">Coverage</span><h2>Questions by biology subdomain</h2></div>
          <span>{data.total} total</span>
        </div>
        <div className="coverage-chart" role="img" aria-label="Bar chart of benchmark questions per subdomain">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={subdomains} margin={{ top: 12, right: 12, left: -20, bottom: 40 }}>
              <CartesianGrid stroke="#e8ede9" vertical={false} />
              <XAxis dataKey="name" axisLine={false} tickLine={false} angle={-40} textAnchor="end" interval={0} tick={{ fill: "#71817e", fontSize: 9 }} />
              <YAxis axisLine={false} tickLine={false} tick={{ fill: "#899692", fontSize: 9 }} />
              <Tooltip cursor={{ fill: "#edf5f1" }} contentStyle={{ border: "1px solid #dce3de", borderRadius: 8, fontSize: 11 }} formatter={(value) => [`${value} questions`, "Count"]} />
              <Bar dataKey="count" radius={[5, 5, 0, 0]} maxBarSize={30}>
                {subdomains.map((entry, index) => (
                  <Cell key={index} fill={entry.count >= maxSub * 0.75 ? "#2d786f" : "#5aa89d"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="distribution-row">
        <DistributionCard title="Task type" data={data.by_task_type} />
        <DistributionCard title="Learner level" data={data.by_level} />
        <DistributionCard title="Difficulty" data={data.by_difficulty} />
      </section>
    </>
  );
}

function DistributionCard({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  return (
    <div className="distribution-card">
      <span className="eyebrow">{title}</span>
      <ul>
        {entries.map(([key, count]) => (
          <li key={key}>
            <span className="distribution-label">{label(key)}</span>
            <span className="distribution-track"><i style={{ width: `${(count / total) * 100}%` }} /></span>
            <b>{count}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}
