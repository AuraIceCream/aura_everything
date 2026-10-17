"""Declared study styles and neutral scope; no learned biology classifier."""
import re
from ..routing.schema import Classification, CONTEXT_LEVEL_POLICY, LearnerLevel, Route, TeachingMode


class StudyRouter:
    def __init__(self, domain='general'):
        self.domain = domain

    def route(self, query, learner_level=None, teaching_mode=None, context_level=None):
        depth = max(1, min(4, 2 if context_level is None else int(context_level)))
        level = LearnerLevel(learner_level or LearnerLevel.HIGH_SCHOOL)
        mode = TeachingMode(teaching_mode or TeachingMode.GUIDED_EXPLANATION)
        policy = CONTEXT_LEVEL_POLICY[depth]
        label = lambda value: Classification(str(value), 1.0, source='study_policy')
        task = 'concept_explanation'
        for pattern,value in (
            (r'\b(?:quiz|practice questions|flashcards|test me)\b','quiz_generation'),
            (r'\b(?:compare|contrast|difference|versus|vs)\b','comparison'),
            (r'\b(?:calculate|compute|convert|dilution|arithmetic|what(?:\s+is(?:\s+the)?)?\s+total|sum of)\b','numerical'),
            (r'\b(?:procedure|protocol|steps|workflow|method|process)\b','process_explanation'),
            (r'\b(?:summari[sz]e|summary|overview|main points|study guide|revision notes)\b','summary'),
            (r'\b(?:limitations|critique|evaluate|evidence for|conclusions)\b','research_paper'),
            (r'^\s*(?:define|what (?:is|are))\b','definition')):
            if re.search(pattern,query,re.I):
                task=value; break
        return Route(query, label(task), label('user_material'), (), label(level), label(mode),
                     depth, True, self.domain == 'biology', False, policy['retrieve'], policy['rerank'],
                     policy['max_revisions'], domain=self.domain, evidence_scope='pack_only')
