"""Build a benchmark that can actually discriminate a RAG pipeline (SRS 25).

The existing 441-question bank cannot. Measured over 50 of its questions, the
bare model already knows 87.8% of the required concepts and retrieval supplies
87.8%, overlapping on ~82%; the union is 93.6%. A perfect pipeline could
therefore beat the raw model by under six points, because the questions ask for
textbook biology a 4B model has thoroughly memorised. Retrieval cannot beat
memory at recalling memorised things.

This bank asks for the kind of fact retrieval is *for*: specific named subunits,
consensus sequences, particular caspases, named cofactors — content a small
model tends to answer vaguely or approximately, and which a Wikipedia/NLM/
GeneOntology/Reactome corpus states precisely.

**Pre-registration.** Each question carries a ``target`` or ``control`` tag,
fixed before any run:

* ``target``  — predicted: the bare model is vague or partly wrong; retrieval
  supplies the specifics. The pipeline should gain.
* ``control`` — predicted: core textbook material the model knows cold.
  The pipeline should show **no** gain. These exist to catch a rigged bank: a
  pipeline that wins everywhere is winning for the wrong reason.

Answer keys were written from established biology, not from corpus text, and
deliberately before inspecting what retrieval returns for any of them. They are
not to be adjusted after seeing scores — doing so is how a benchmark stops
measuring anything.

The honest failure mode to watch for: if the baseline scores *high* on the
target set, the selection hypothesis was simply wrong, and that is a real
result rather than something to tune away.

    python aura_bio_system/benchmarks/build_retrieval_bank.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from aura_bio.evaluation.schema import AnswerKey, BenchmarkQuestion, Difficulty, write_jsonl

# (id, question, subdomain, task_type, level, difficulty, must_include, tag)
_ROWS: tuple[tuple, ...] = (
    # ---------------- target: specific, retrievable, easy to be vague about ----
    ("ret-001", "Which subunit of the bacterial RNA polymerase holoenzyme recognises the "
     "-10 and -35 promoter elements, and what are those consensus sequences?",
     "molecular_biology", "factual_recall", "undergraduate", Difficulty.HARD,
     ("sigma", "-10", "-35", "TATAAT", "TTGACA"), "target"),
    ("ret-002", "In telomerase, which component is the reverse transcriptase and which "
     "component provides the template for telomere synthesis?",
     "molecular_biology", "factual_recall", "undergraduate", Difficulty.HARD,
     ("TERT", "reverse transcriptase", "RNA template"), "target"),
    ("ret-003", "Which protein complex acts as the replicative helicase in eukaryotes, and "
     "which factors license the origin before it is activated?",
     "molecular_biology", "concept_explanation", "undergraduate", Difficulty.HARD,
     ("MCM", "ORC", "Cdc6", "Cdt1"), "target"),
    ("ret-004", "Name the initiator caspase of the intrinsic apoptotic pathway and the "
     "initiator caspase of the extrinsic pathway, and state what activates each.",
     "cell_biology", "comparison", "undergraduate", Difficulty.HARD,
     ("caspase-9", "caspase-8", "cytochrome c", "death receptor"), "target"),
    ("ret-005", "Which enzyme catalyses the first committed step of carbon fixation in C4 "
     "plants, in which cell type does it act, and what is the immediate product?",
     "botany", "process_explanation", "undergraduate", Difficulty.HARD,
     ("PEP carboxylase", "mesophyll", "bundle sheath", "oxaloacetate"), "target"),
    ("ret-006", "What two second messengers does phospholipase C generate from PIP2, and "
     "what does each do downstream?",
     "biochemistry", "process_explanation", "undergraduate", Difficulty.HARD,
     ("IP3", "diacylglycerol", "calcium", "protein kinase C"), "target"),
    ("ret-007", "Which enzyme complex reduces atmospheric nitrogen to ammonia in "
     "diazotrophs, and how is it protected from oxygen in legume root nodules?",
     "microbiology", "process_explanation", "undergraduate", Difficulty.HARD,
     ("nitrogenase", "ammonia", "leghemoglobin", "oxygen"), "target"),
    ("ret-008", "How are proteins marked for degradation by the proteasome, and what is "
     "the name of the complex that degrades them?",
     "cell_biology", "process_explanation", "undergraduate", Difficulty.MEDIUM,
     ("ubiquitin", "26S", "proteasome", "ATP"), "target"),
    ("ret-009", "Which respiratory chain complex does cyanide inhibit, and what is that "
     "complex also called?",
     "biochemistry", "factual_recall", "undergraduate", Difficulty.MEDIUM,
     ("complex IV", "cytochrome c oxidase", "oxygen"), "target"),
    ("ret-010", "Which enzyme is deficient in classical phenylketonuria, which substrate "
     "accumulates, and which amino acid becomes conditionally essential?",
     "biochemistry", "concept_explanation", "undergraduate", Difficulty.HARD,
     ("phenylalanine hydroxylase", "phenylalanine", "tyrosine"), "target"),
    ("ret-011", "What is the role of the signal recognition particle in protein targeting, "
     "and where does it deliver the ribosome?",
     "cell_biology", "process_explanation", "undergraduate", Difficulty.HARD,
     ("signal recognition particle", "signal", "endoplasmic reticulum", "translocon"), "target"),
    ("ret-012", "Which cells secrete pulmonary surfactant, and what physical problem does "
     "surfactant solve?",
     "physiology", "factual_recall", "senior_secondary", Difficulty.MEDIUM,
     ("type II", "surface tension", "alveoli"), "target"),
    ("ret-013", "How is most carbon dioxide carried in the blood, which enzyme catalyses "
     "the conversion, and what ion exchange accompanies it in the red cell?",
     "physiology", "process_explanation", "undergraduate", Difficulty.HARD,
     ("bicarbonate", "carbonic anhydrase", "chloride shift"), "target"),
    ("ret-014", "Which enzyme do statins inhibit, in which pathway, and what is that "
     "pathway's committed intermediate?",
     "biochemistry", "concept_explanation", "undergraduate", Difficulty.HARD,
     ("HMG-CoA reductase", "cholesterol", "mevalonate"), "target"),
    ("ret-015", "Which structure in the kidney secretes renin, and what three stimuli "
     "trigger its release?",
     "physiology", "concept_explanation", "undergraduate", Difficulty.HARD,
     ("juxtaglomerular", "renin", "macula densa", "blood pressure"), "target"),
    ("ret-016", "In CRISPR-Cas9 genome editing, what is the PAM sequence, why is it "
     "required, and what does Cas9 do once bound?",
     "biotechnology", "process_explanation", "undergraduate", Difficulty.MEDIUM,
     ("PAM", "guide RNA", "double-strand break", "Cas9"), "target"),
    ("ret-017", "Which enzyme deficiency causes the most common human enzymopathy "
     "affecting red cells, and which cofactor does that enzyme produce?",
     "biochemistry", "concept_explanation", "undergraduate", Difficulty.HARD,
     ("glucose-6-phosphate dehydrogenase", "NADPH", "pentose phosphate"), "target"),
    ("ret-018", "What post-translational modification does vitamin K enable in clotting "
     "factors, and which drug antagonises it?",
     "biochemistry", "concept_explanation", "undergraduate", Difficulty.HARD,
     ("carboxylation", "clotting factor", "warfarin"), "target"),
    ("ret-019", "Which aquaporin is inserted into the collecting duct membrane under "
     "hormonal control, and which hormone controls it?",
     "physiology", "factual_recall", "undergraduate", Difficulty.HARD,
     ("aquaporin", "collecting duct", "vasopressin", "water"), "target"),
    ("ret-020", "Describe how the nuclear pore complex achieves selective transport, "
     "naming the repeat motif and the GTPase gradient involved.",
     "cell_biology", "process_explanation", "postgraduate", Difficulty.HARD,
     ("nucleoporin", "FG", "Ran", "importin"), "target"),
    ("ret-021", "Which enzyme terminates acetylcholine signalling at the neuromuscular "
     "junction, and what are the products of that reaction?",
     "neuroscience", "process_explanation", "undergraduate", Difficulty.MEDIUM,
     ("acetylcholinesterase", "acetylcholine", "choline", "acetate"), "target"),
    ("ret-022", "Which enzyme converts androgens to estrogens, and name two tissues where "
     "it is expressed.",
     "physiology", "factual_recall", "undergraduate", Difficulty.HARD,
     ("aromatase", "androgen", "estrogen"), "target"),
    ("ret-023", "How do bacterial chaperonins such as GroEL and GroES assist protein "
     "folding, and what powers the cycle?",
     "biochemistry", "process_explanation", "postgraduate", Difficulty.HARD,
     ("GroEL", "GroES", "folding", "ATP"), "target"),
    ("ret-024", "Which enzyme do fluoroquinolone antibiotics target in bacteria, and what "
     "topological problem does that enzyme solve?",
     "microbiology", "concept_explanation", "undergraduate", Difficulty.HARD,
     ("DNA gyrase", "topoisomerase", "supercoil"), "target"),
    ("ret-025", "Which enzyme does methotrexate inhibit, what does that enzyme produce, "
     "and why does inhibiting it block DNA synthesis?",
     "biochemistry", "concept_explanation", "postgraduate", Difficulty.HARD,
     ("dihydrofolate reductase", "tetrahydrofolate", "thymidylate"), "target"),
    ("ret-026", "What distinguishes MHC class I from MHC class II in terms of which cells "
     "express them and which T cell subset they engage?",
     "immunology", "comparison", "undergraduate", Difficulty.MEDIUM,
     ("MHC class I", "MHC class II", "CD8", "CD4"), "target"),
    ("ret-027", "In the Calvin cycle, which enzyme carboxylates ribulose-1,5-bisphosphate "
     "and what is the first stable three-carbon product?",
     "botany", "process_explanation", "undergraduate", Difficulty.MEDIUM,
     ("rubisco", "ribulose-1,5-bisphosphate", "3-phosphoglycerate"), "target"),
    ("ret-028", "Which viral enzyme integrates retroviral DNA into the host genome, and "
     "what is the integrated form called?",
     "microbiology", "factual_recall", "undergraduate", Difficulty.HARD,
     ("integrase", "provirus", "host genome"), "target"),

    # ---------------- control: core textbook, model should already be strong ---
    ("ret-c01", "What is photosynthesis? Give the overall word equation.",
     "botany", "definition", "high_school", Difficulty.EASY,
     ("carbon dioxide", "water", "glucose", "oxygen", "light"), "control"),
    ("ret-c02", "List the stages of mitosis in order.",
     "cell_biology", "process_explanation", "high_school", Difficulty.EASY,
     ("prophase", "metaphase", "anaphase", "telophase"), "control"),
    ("ret-c03", "Describe the structure of DNA.",
     "molecular_biology", "concept_explanation", "high_school", Difficulty.EASY,
     ("double helix", "nucleotide", "base pair", "sugar-phosphate"), "control"),
    ("ret-c04", "What is the function of the mitochondrion?",
     "cell_biology", "definition", "high_school", Difficulty.EASY,
     ("ATP", "respiration", "energy"), "control"),
    ("ret-c05", "Define osmosis.",
     "cell_biology", "definition", "high_school", Difficulty.EASY,
     ("water", "membrane", "concentration"), "control"),
    ("ret-c06", "What are the four main classes of biological macromolecule?",
     "biochemistry", "factual_recall", "high_school", Difficulty.EASY,
     ("carbohydrate", "lipid", "protein", "nucleic acid"), "control"),
    ("ret-c07", "What is an enzyme and how does it speed up a reaction?",
     "biochemistry", "definition", "high_school", Difficulty.EASY,
     ("catalyst", "activation energy", "protein"), "control"),
    ("ret-c08", "What are the main differences between prokaryotic and eukaryotic cells?",
     "cell_biology", "comparison", "high_school", Difficulty.EASY,
     ("nucleus", "prokaryote", "eukaryote", "organelle"), "control"),
    ("ret-c09", "Explain natural selection.",
     "evolution", "concept_explanation", "high_school", Difficulty.EASY,
     ("variation", "adaptation", "environment"), "control"),
    ("ret-c10", "What is the role of red blood cells?",
     "physiology", "definition", "high_school", Difficulty.EASY,
     ("oxygen", "carbon dioxide", "transport"), "control"),
)


def build() -> list[BenchmarkQuestion]:
    return [
        BenchmarkQuestion(
            id=qid,
            question=text,
            subdomain=subdomain,
            task_type=task_type,
            level=level,
            difficulty=difficulty,
            answer_key=AnswerKey(must_include=keys),
            tags=(tag,),
        )
        for qid, text, subdomain, task_type, level, difficulty, keys, tag in _ROWS
    ]


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Build the retrieval-discriminating bank")
    parser.add_argument("--out", type=Path, default=here / "retrieval_bank.jsonl")
    args = parser.parse_args(argv)

    questions = build()
    count = write_jsonl(questions, args.out)
    target = [q for q in questions if "target" in q.tags]
    control = [q for q in questions if "control" in q.tags]
    print(f"{count} questions -> {args.out}")
    print(f"  target  {len(target):>3}  (predicted: pipeline gains)")
    print(f"  control {len(control):>3}  (predicted: no gain)")
    print(f"  concepts: {sum(len(q.answer_key.must_include) for q in questions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
