"""Deterministic keyword and pattern evidence for the routers.

SRS 8.2 asks for rules first and a supervised router later, so these tables are
the actual routing policy rather than a placeholder. They are kept as data so
the routing benchmark can attribute a wrong decision to a specific pattern.

Weights are coarse on purpose: 3.0 for a phrase that almost determines the
label, 2.0 for a strong signal, 1.0 for a supporting term.
"""

from __future__ import annotations

from .schema import LearnerLevel, Subdomain, TaskType, TeachingMode

Pattern = tuple[str, float]

# ---------------------------------------------------------------------------
# Task type
# ---------------------------------------------------------------------------

TASK_PATTERNS: dict[TaskType, tuple[Pattern, ...]] = {
    TaskType.DEFINITION: (
        (r"\bwhat (?:is|are) (?:a |an |the )?\w+\??$", 3.0),
        (r"\bdefine\b", 3.0),
        (r"\bdefinition of\b", 3.0),
        (r"\bmeaning of\b", 2.0),
        (r"\bwhat does .{1,40} (?:mean|stand for)\b", 2.5),
        (r"\bfull form of\b", 2.0),
    ),
    TaskType.PROCESS_EXPLANATION: (
        (r"\bhow does\b", 2.5),
        (r"\bhow do\b", 2.5),
        (r"\bhow is\b", 2.0),
        # "how X occurs" carries the same intent as "how does X occur" and is
        # the phrasing in the SRS 8.1 worked example.
        (r"\bhow\b.{0,40}\b(?:occurs?|happens?|works?|takes place|proceeds?)\b", 3.0),
        (r"\bsteps? (?:of|in|involved)\b", 3.0),
        (r"\bstages? of\b", 3.0),
        (r"\bmechanism of\b", 3.0),
        (r"\bpathway\b", 2.0),
        (r"\bprocess of\b", 3.0),
        (r"\bcycle\b", 1.0),
        (r"\boccurs?\b", 1.0),
        (r"\bsequence of events\b", 3.0),
    ),
    TaskType.COMPARISON: (
        (r"\bdifference between\b", 3.0),
        (r"\bcompare\b", 3.0),
        (r"\bcontrast\b", 2.5),
        (r"\bversus\b|\bvs\.?\b", 3.0),
        (r"\bsimilarit(?:y|ies)\b", 2.5),
        (r"\bdistinguish between\b", 3.0),
        (r"\bhow (?:does|do|is|are) .{1,40} differ\b", 3.0),
    ),
    TaskType.NUMERICAL: (
        (r"\bcalculate\b", 3.0),
        (r"\bcompute\b", 3.0),
        (r"\bwhat (?:is|are) the (?:probability|frequency|ratio|percentage)\b", 3.0),
        (r"\bhow many\b", 2.0),
        (r"\bwhat proportion\b", 2.5),
        (r"\bhardy[- ]weinberg\b", 3.0),
        (r"\bpunnett\b", 2.5),
        (r"\ballele frequenc(?:y|ies)\b", 2.5),
        (r"\bdilution\b", 2.0),
        (r"\bmichaelis\b|\bkm\b|\bvmax\b", 2.0),
        (r"\bgrowth rate\b", 2.0),
        (r"\d+\s*%", 1.5),
        (r"\bratio of\b", 1.5),
    ),
    TaskType.MISCONCEPTION_CORRECTION: (
        (r"\bis it true that\b", 3.0),
        (r"\bmisconception\b", 3.0),
        (r"\bmyth\b", 2.5),
        (r"\bam i (?:right|wrong|correct)\b", 3.0),
        (r"\bi (?:thought|think|believe(?:d)?)\b", 2.0),
        (r"\bwhy is .{1,50} wrong\b", 2.5),
        (r"\bcommon (?:mistake|error)s?\b", 2.5),
        (r"\bisn'?t it\b", 2.0),
    ),
    TaskType.RESEARCH_PAPER: (
        (r"\bthis (?:paper|study|article|preprint)\b", 3.0),
        (r"\babstract\b", 1.5),
        (r"\bthe authors?\b", 2.5),
        (r"\bmethodolog(?:y|ies)\b", 2.0),
        (r"\bp[- ]?value\b", 2.0),
        (r"\bcohort\b|\bsample size\b", 1.5),
        (r"\bdoi\b|\bpmid\b|\bpmc\d+\b", 3.0),
        (r"\bet al\b", 2.5),
        (r"\bsummari[sz]e the (?:paper|study|article)\b", 3.0),
    ),
    TaskType.EXAM_ANSWER: (
        (r"\b\d+\s*marks?\b", 3.0),
        (r"\bexam\b", 2.5),
        (r"\bboard (?:exam|question)\b", 3.0),
        (r"\blong answer\b", 3.0),
        (r"\bshort answer\b", 3.0),
        (r"\bwrite (?:a |an )?note on\b", 2.5),
        (r"\bneet\b|\bcbse\b|\bicse\b|\bjee\b", 3.0),
        (r"\bmodel answer\b", 3.0),
    ),
    TaskType.QUIZ_GENERATION: (
        (r"\b(?:make|create|generate|give me|set) .{0,20}(?:quiz|mcqs?|questions?)\b", 3.0),
        (r"\bmultiple choice\b", 3.0),
        (r"\bmcq\b", 3.0),
        (r"\btest me\b", 3.0),
        (r"\bpractice questions?\b", 2.5),
    ),
    TaskType.REVISION: (
        (r"\brevision notes?\b", 3.0),
        (r"\bflash ?cards?\b", 3.0),
        (r"\bcheat ?sheet\b", 3.0),
        (r"\bquick recap\b", 3.0),
        (r"\bsummar(?:y|ise|ize) .{0,20}for revision\b", 3.0),
        (r"\bmnemonic\b", 2.5),
        (r"\bkey points\b", 2.0),
    ),
    TaskType.SUMMARY: (
        (r"\bsummari[sz]e\b", 2.5),
        (r"\bin brief\b", 2.0),
        (r"\btl;?dr\b", 3.0),
        (r"\boverview of\b", 2.0),
        (r"\bbriefly (?:explain|describe)\b", 2.0),
    ),
    TaskType.CONCEPT_EXPLANATION: (
        # "explain" is a generic instruction verb that appears in process,
        # comparison, and exam requests alike, so it only breaks ties.
        (r"\bexplain\b", 1.0),
        (r"\bwhy (?:does|do|is|are)\b", 2.5),
        (r"\bhelp me understand\b", 3.0),
        (r"\bconcept of\b", 2.5),
        (r"\bwhat happens (?:if|when)\b", 2.0),
        (r"\bsignificance of\b", 2.0),
        (r"\brole of\b", 1.5),
        (r"\bimportance of\b", 1.5),
    ),
    TaskType.FACTUAL_RECALL: (
        (r"\bwhich\b", 1.5),
        (r"\bwhere (?:is|are|does)\b", 2.0),
        (r"\bwhen (?:did|does|is)\b", 2.0),
        (r"\bwho (?:discovered|proposed|described)\b", 2.5),
        (r"\bname the\b", 2.5),
        (r"\blist the\b", 2.0),
        (r"\bhow many chromosomes\b", 2.0),
    ),
    TaskType.CONVERSATIONAL: (
        (r"^\s*(?:hi|hello|hey|thanks|thank you|ok(?:ay)?|good (?:morning|evening))\b", 3.0),
        (r"\bwho are you\b", 3.0),
        (r"\bwhat can you do\b", 3.0),
    ),
}

# ---------------------------------------------------------------------------
# Biology subdomain
# ---------------------------------------------------------------------------

SUBDOMAIN_TERMS: dict[Subdomain, tuple[Pattern, ...]] = {
    Subdomain.CELL_BIOLOGY: (
        (r"\bcell (?:membrane|wall|cycle|organelle|division|junction)\b", 3.0),
        (r"\bmitochondri(?:a|on)\b", 2.5),
        (r"\bribosome\b", 2.0),
        (r"\bendoplasmic reticulum\b", 3.0),
        (r"\bgolgi\b", 3.0),
        (r"\blysosome\b", 3.0),
        (r"\bcytoskeleton\b|\bcytoplasm\b", 2.0),
        (r"\bmitosis\b", 2.5),
        (r"\bapoptosis\b", 2.0),
        (r"\bnucleus\b", 1.5),
        (r"\borganelle\b", 2.5),
    ),
    Subdomain.MOLECULAR_BIOLOGY: (
        (r"\bdna replication\b", 3.0),
        (r"\btranscription\b", 2.5),
        (r"\btranslation\b", 2.5),
        (r"\bmrna\b|\btrna\b|\brrna\b", 2.5),
        (r"\bpolymerase\b", 2.5),
        (r"\bhelicase\b|\bligase\b|\bprimase\b", 3.0),
        (r"\boperon\b", 3.0),
        (r"\bcodon\b|\banticodon\b", 2.5),
        (r"\bgene expression\b", 2.5),
        (r"\bcentral dogma\b", 3.0),
        (r"\bnucleotide\b", 2.0),
    ),
    Subdomain.GENETICS: (
        (r"\bmendel\w*\b", 3.0),
        (r"\ballele\b", 2.5),
        (r"\bgenotype\b|\bphenotype\b", 2.5),
        (r"\bheterozygous\b|\bhomozygous\b", 3.0),
        (r"\bpunnett\b", 3.0),
        (r"\bdominant\b|\brecessive\b", 2.0),
        (r"\bhardy[- ]weinberg\b", 3.0),
        (r"\bpedigree\b", 2.5),
        (r"\bchromosom\w+\b", 1.5),
        (r"\blinkage\b|\bcrossing over\b", 2.5),
        (r"\bmeiosis\b", 2.0),
        (r"\bmutation\b", 1.5),
    ),
    Subdomain.MICROBIOLOGY: (
        (r"\bbacteri\w+\b", 2.5),
        (r"\bvirus(?:es)?\b|\bviral\b", 2.5),
        (r"\bfung(?:us|i|al)\b", 2.0),
        (r"\barchaea\b", 3.0),
        (r"\bantibiotic\b", 2.5),
        (r"\bpathogen\b", 2.0),
        (r"\bgram[- ](?:positive|negative|stain)\b", 3.0),
        (r"\bbiofilm\b", 2.5),
        (r"\bplasmid\b", 2.0),
        (r"\bculture medium\b|\bagar\b", 2.5),
    ),
    Subdomain.BOTANY: (
        (r"\bphotosynthesis\b", 2.5),
        (r"\bchloroplast\b|\bchlorophyll\b", 2.5),
        (r"\bstomata?\b", 3.0),
        (r"\bxylem\b|\bphloem\b", 3.0),
        (r"\btranspiration\b", 3.0),
        (r"\bplant\b", 1.5),
        (r"\bgermination\b", 2.5),
        (r"\bpollination\b", 2.5),
        (r"\broot\b|\bleaf\b|\bstem\b", 1.0),
        (r"\bcalvin cycle\b", 2.5),
    ),
    Subdomain.ZOOLOGY: (
        (r"\banimal\b", 1.5),
        (r"\bvertebrate\b|\binvertebrate\b", 3.0),
        (r"\bmammal\w*\b|\breptil\w+\b|\bamphibian\w*\b", 2.5),
        (r"\barthropod\b|\bmollusc\b|\bannelid\b", 3.0),
        (r"\bphylum\b", 2.0),
        (r"\bmetamorphosis\b", 2.5),
    ),
    Subdomain.ECOLOGY: (
        (r"\becosystem\b", 3.0),
        (r"\bfood (?:chain|web)\b", 3.0),
        (r"\bbiodiversity\b", 3.0),
        (r"\btrophic level\b", 3.0),
        (r"\bpopulation (?:growth|density|dynamics)\b", 2.5),
        (r"\bhabitat\b|\bniche\b", 2.5),
        (r"\bsuccession\b", 2.5),
        (r"\bbiogeochemical\b|\bnitrogen cycle\b|\bcarbon cycle\b", 3.0),
        (r"\bconservation\b", 2.0),
    ),
    Subdomain.EVOLUTION: (
        (r"\bnatural selection\b", 3.0),
        (r"\bdarwin\w*\b", 3.0),
        (r"\bevolution\w*\b", 2.5),
        (r"\bspeciation\b", 3.0),
        (r"\bphylogen\w+\b", 2.5),
        (r"\bcommon ancestor\b", 2.5),
        (r"\badaptation\b", 1.5),
        (r"\bgenetic drift\b", 3.0),
        (r"\bfossil\b", 2.0),
    ),
    Subdomain.PHYSIOLOGY: (
        (r"\bhomeostasis\b", 3.0),
        (r"\bcirculat\w+\b|\brespirat\w+ system\b|\bdigestive\b|\bexcretory\b", 2.5),
        (r"\bblood pressure\b|\bheart rate\b", 2.5),
        (r"\bnephron\b|\bkidney\b", 2.5),
        (r"\bhormone\b|\bendocrine\b", 2.5),
        (r"\binsulin\b|\bglucagon\b|\bthyroid\b", 2.5),
        (r"\bmuscle contraction\b", 2.5),
        (r"\bglomerul\w+\b", 2.5),
    ),
    Subdomain.ANATOMY: (
        (r"\banatom\w+\b", 3.0),
        (r"\bskeleton\b|\bbone\b|\bjoint\b", 2.0),
        (r"\bstructure of the (?:heart|lung|eye|ear|brain|liver)\b", 3.0),
        (r"\bventricle\b|\batrium\b", 2.5),
        (r"\balveoli\b", 2.5),
        (r"\btissue\b", 1.5),
    ),
    Subdomain.IMMUNOLOGY: (
        (r"\bimmun\w+\b", 2.5),
        (r"\bantibod(?:y|ies)\b|\bantigen\b", 3.0),
        (r"\bt[- ]cells?\b|\bb[- ]cells?\b", 3.0),
        (r"\bvaccin\w+\b", 2.5),
        (r"\bmhc\b|\bhla\b", 3.0),
        (r"\binflammation\b", 2.0),
        (r"\blymphocyte\b|\bmacrophage\b", 3.0),
        (r"\bcytokine\b", 2.5),
    ),
    Subdomain.BIOCHEMISTRY: (
        (r"\benzyme\b|\bcatalys\w+\b", 2.5),
        (r"\bglycolysis\b", 3.0),
        (r"\bkrebs\b|\bcitric acid cycle\b|\btca cycle\b", 3.0),
        (r"\belectron transport chain\b", 3.0),
        (r"\batp\b", 2.0),
        (r"\bprotein (?:folding|structure)\b", 2.5),
        (r"\bamino acid\b", 2.0),
        (r"\bmetabolis\w+\b", 2.5),
        (r"\bsubstrate\b|\bactive site\b", 2.5),
        (r"\bmichaelis\b", 3.0),
        (r"\blipid\b|\bcarbohydrate\b", 1.5),
    ),
    Subdomain.BIOTECHNOLOGY: (
        (r"\bcrispr\b", 3.0),
        (r"\bpcr\b", 3.0),
        (r"\brecombinant\b", 3.0),
        (r"\bcloning\b", 2.5),
        (r"\bgenetic engineering\b", 3.0),
        (r"\bgel electrophoresis\b", 3.0),
        (r"\brestriction enzyme\b", 3.0),
        (r"\btransgenic\b|\bgmo\b", 3.0),
        (r"\bbioreactor\b|\bfermentation\b", 2.0),
    ),
    Subdomain.NEUROSCIENCE: (
        (r"\bneuron\b|\bneural\b", 3.0),
        (r"\bsynap\w+\b", 3.0),
        (r"\baction potential\b", 3.0),
        (r"\bneurotransmitter\b", 3.0),
        (r"\bbrain\b", 1.5),
        (r"\bmyelin\b|\baxon\b|\bdendrite\b", 3.0),
        (r"\bnervous system\b", 2.5),
        (r"\breflex arc\b", 3.0),
    ),
    Subdomain.DEVELOPMENTAL_BIOLOGY: (
        (r"\bembryo\w*\b", 3.0),
        (r"\bmorphogen\w+\b", 3.0),
        (r"\bgastrulation\b|\bblastula\b|\bneurulation\b", 3.0),
        (r"\bdifferentiation\b", 2.0),
        (r"\bstem cells?\b", 2.5),
        (r"\borganogenesis\b", 3.0),
        (r"\bhox genes?\b", 3.0),
    ),
    Subdomain.BIOINFORMATICS: (
        (r"\bsequence alignment\b", 3.0),
        (r"\bblast\b", 2.5),
        (r"\bgenom\w+ (?:assembly|annotation)\b", 3.0),
        (r"\bfasta\b|\bfastq\b", 3.0),
        (r"\bphylogenetic tree\b", 2.5),
        (r"\bin silico\b", 2.5),
        (r"\bngs\b|\brna[- ]seq\b", 3.0),
        (r"\buniprot\b|\bncbi\b|\bensembl\b", 2.5),
    ),
}

# ---------------------------------------------------------------------------
# Learner level
# ---------------------------------------------------------------------------

LEVEL_PATTERNS: dict[LearnerLevel, tuple[Pattern, ...]] = {
    LearnerLevel.ELEMENTARY: (
        (r"\b(?:class|grade|std\.?|standard)\s*[1-5]\b", 3.0),
        (r"\bprimary school\b", 3.0),
        (r"\bfor (?:a )?(?:kid|child|children)\b", 3.0),
        (r"\bexplain like i'?m (?:five|5)\b", 3.0),
        (r"\bvery simple\b", 2.0),
    ),
    LearnerLevel.MIDDLE_SCHOOL: (
        (r"\b(?:class|grade|std\.?|standard)\s*[6-8]\b", 3.0),
        (r"\bmiddle school\b", 3.0),
    ),
    LearnerLevel.HIGH_SCHOOL: (
        (r"\b(?:class|grade|std\.?|standard)\s*(?:9|10|ix|x)\b", 3.0),
        (r"\bhigh school\b", 3.0),
        (r"\bsecondary school\b", 2.5),
        (r"\bgcse\b", 3.0),
    ),
    LearnerLevel.SENIOR_SECONDARY: (
        (r"\b(?:class|grade|std\.?|standard)\s*(?:11|12|xi|xii)\b", 3.0),
        (r"\bsenior secondary\b", 3.0),
        (r"\bhigher secondary\b", 3.0),
        (r"\ba[- ]levels?\b", 3.0),
        (r"\bneet\b|\bcbse board\b", 2.5),
        (r"\bplus (?:one|two)\b", 2.5),
    ),
    LearnerLevel.UNDERGRADUATE: (
        (r"\bundergrad\w*\b", 3.0),
        (r"\bbsc\b|\bb\.sc\b|\bbachelor'?s?\b", 3.0),
        (r"\bfirst year (?:college|university)\b", 2.5),
        (r"\bcollege level\b", 2.5),
        (r"\bsemester\b", 1.5),
    ),
    LearnerLevel.POSTGRADUATE: (
        (r"\bpostgrad\w*\b", 3.0),
        (r"\bmsc\b|\bm\.sc\b|\bmaster'?s?\b", 3.0),
        (r"\bgraduate (?:course|student|level)\b", 2.5),
    ),
    LearnerLevel.RESEARCH: (
        (r"\bphd\b|\bdoctoral\b", 3.0),
        (r"\bresearch level\b", 3.0),
        (r"\bfor (?:my|a) (?:thesis|dissertation|manuscript)\b", 3.0),
        (r"\bstate of the art\b", 2.0),
        (r"\bliterature review\b", 2.5),
    ),
    LearnerLevel.GENERAL_PUBLIC: (
        (r"\bin (?:simple|plain) (?:terms|english|words)\b", 2.5),
        (r"\bfor (?:a )?(?:layman|beginner|non[- ]?scientist)\b", 3.0),
        (r"\bi'?m (?:just )?curious\b", 2.0),
    ),
}

# Terminology whose presence implies the asker already operates at that level.
ADVANCED_VOCABULARY: tuple[Pattern, ...] = (
    (r"\ballosteric\b", 2.0),
    (r"\bepigenetic\w*\b", 2.0),
    (r"\bproteom\w+\b|\btranscriptom\w+\b|\bmetabolom\w+\b", 2.5),
    (r"\bkinetics\b", 1.5),
    (r"\bin vitro\b|\bin vivo\b|\bin silico\b", 1.5),
    (r"\bknock(?:out|down)\b", 2.0),
    (r"\bimmunoprecipitat\w+\b|\bwestern blot\b|\bqpcr\b", 2.5),
    (r"\bconfidence interval\b|\bp[- ]?value\b", 2.0),
    (r"\bupstream regulator\b|\bsignal(?:ling|ing) cascade\b", 2.0),
    (r"\bstoichiometr\w+\b", 2.0),
)

SIMPLE_REQUEST_MARKERS: tuple[Pattern, ...] = (
    (r"\bsimple\b", 1.5),
    (r"\beasy\b", 1.5),
    (r"\bbasic\b", 1.0),
    (r"\bin short\b", 1.0),
    (r"\bwith (?:an )?example\b", 0.5),
)

# ---------------------------------------------------------------------------
# Teaching mode
# ---------------------------------------------------------------------------

TEACHING_PATTERNS: dict[TeachingMode, tuple[Pattern, ...]] = {
    TeachingMode.SOCRATIC: (
        (r"\bdon'?t (?:give|tell) me the answer\b", 3.0),
        (r"\bgive me (?:a )?hints?\b", 3.0),
        (r"\bguide me\b", 2.5),
        (r"\bsocratic\b", 3.0),
        (r"\bhelp me work (?:it|this) out\b", 3.0),
    ),
    TeachingMode.TEACH_BACK: (
        (r"\bcheck my understanding\b", 3.0),
        (r"\bis my (?:explanation|understanding|answer) (?:right|correct)\b", 3.0),
        (r"\blet me explain\b", 2.5),
        (r"\bhere'?s what i (?:think|understand)\b", 3.0),
        (r"\bgrade my answer\b", 3.0),
    ),
    TeachingMode.EXAM: (
        (r"\b\d+\s*marks?\b", 3.0),
        (r"\bexam\b|\bboard question\b", 2.5),
        (r"\bmodel answer\b", 3.0),
        (r"\bhow (?:should|do) i (?:write|answer)\b", 2.5),
    ),
    TeachingMode.REVISION: (
        (r"\brevision\b", 3.0),
        (r"\bflash ?cards?\b", 3.0),
        (r"\bquick(?:ly)? (?:revise|recap)\b", 3.0),
        (r"\bmnemonic\b", 2.5),
        (r"\bnight before\b", 2.5),
    ),
    TeachingMode.HOMEWORK_SUPPORT: (
        (r"\bhomework\b", 3.0),
        (r"\bassignment\b", 3.0),
        (r"\bworksheet\b", 2.5),
        (r"\bdue tomorrow\b", 2.0),
    ),
    TeachingMode.MISCONCEPTION_REPAIR: (
        (r"\bis it true\b", 2.5),
        (r"\bi (?:thought|assumed|believed)\b", 2.5),
        (r"\bmisconception\b", 3.0),
        (r"\bwhy (?:am i|is that) wrong\b", 3.0),
    ),
    TeachingMode.RESEARCH: (
        (r"\bcitations?\b|\breferences?\b", 2.0),
        (r"\bevidence for\b", 2.0),
        (r"\bcurrent (?:consensus|literature)\b", 3.0),
        (r"\bwith sources\b", 3.0),
    ),
    TeachingMode.DIRECT_ANSWER: (
        (r"\bjust (?:tell|give) me\b", 3.0),
        (r"\bquick(?:ly)? answer\b", 3.0),
        (r"\bin one (?:line|sentence)\b", 3.0),
        (r"\bshort(?:ly)?\b", 1.0),
    ),
}

# Task type implies a default presentation when nothing else is stated.
TASK_DEFAULT_MODE: dict[TaskType, TeachingMode] = {
    TaskType.FACTUAL_RECALL: TeachingMode.DIRECT_ANSWER,
    TaskType.DEFINITION: TeachingMode.DIRECT_ANSWER,
    TaskType.CONCEPT_EXPLANATION: TeachingMode.GUIDED_EXPLANATION,
    TaskType.PROCESS_EXPLANATION: TeachingMode.GUIDED_EXPLANATION,
    TaskType.COMPARISON: TeachingMode.GUIDED_EXPLANATION,
    TaskType.NUMERICAL: TeachingMode.HOMEWORK_SUPPORT,
    TaskType.MISCONCEPTION_CORRECTION: TeachingMode.MISCONCEPTION_REPAIR,
    TaskType.RESEARCH_PAPER: TeachingMode.RESEARCH,
    TaskType.EXAM_ANSWER: TeachingMode.EXAM,
    TaskType.QUIZ_GENERATION: TeachingMode.REVISION,
    TaskType.REVISION: TeachingMode.REVISION,
    TaskType.SUMMARY: TeachingMode.DIRECT_ANSWER,
    TaskType.CONVERSATIONAL: TeachingMode.DIRECT_ANSWER,
}

# ---------------------------------------------------------------------------
# Context level (SRS 10)
# ---------------------------------------------------------------------------

TASK_BASE_CONTEXT: dict[TaskType, int] = {
    TaskType.CONVERSATIONAL: 0,
    TaskType.DEFINITION: 1,
    TaskType.FACTUAL_RECALL: 1,
    TaskType.SUMMARY: 1,
    TaskType.CONCEPT_EXPLANATION: 2,
    TaskType.PROCESS_EXPLANATION: 2,
    TaskType.COMPARISON: 2,
    TaskType.MISCONCEPTION_CORRECTION: 2,
    TaskType.NUMERICAL: 2,
    TaskType.QUIZ_GENERATION: 2,
    TaskType.REVISION: 2,
    TaskType.EXAM_ANSWER: 2,
    TaskType.RESEARCH_PAPER: 3,
}

DEEP_REASONING_MARKERS: tuple[Pattern, ...] = (
    (r"\bcompare .{1,60} (?:across|between) .{1,60}\b", 1.0),
    (r"\bcritically (?:evaluate|analyse|analyze)\b", 2.0),
    (r"\bwhat is the current (?:evidence|consensus|debate)\b", 2.0),
    (r"\bcontradictor\w+\b|\bconflicting\b", 1.5),
    (r"\bmulti[- ]?(?:step|factorial)\b", 1.0),
    (r"\bimplications? (?:of|for)\b", 1.0),
    (r"\bhow (?:might|could) .{1,60} affect\b", 1.0),
)

# Processes whose answers must be checked for step order (SRS 16.3).
ORDERED_PROCESSES: tuple[str, ...] = (
    "dna replication",
    "transcription",
    "translation",
    "mitosis",
    "meiosis",
    "glycolysis",
    "krebs cycle",
    "citric acid cycle",
    "electron transport chain",
    "photosynthesis",
    "calvin cycle",
    "immune response",
    "blood clotting",
    "cell cycle",
    "protein synthesis",
    "signal transduction",
    "urine formation",
    "digestion",
)
