"""Prompt text for fact extraction and question generation."""

from __future__ import annotations

import json
from typing import Any

FACTS_SYSTEM = """\
You organize one person's resume and portfolio material into a list of distinct facts, to be used
for interview preparation.

Rules:
- Use only the sources provided. Never add numbers, tools, motivations, results or details that
  are not stated in them.
- The same achievement is often written several ways across different resumes and the website.
  Merge such paraphrases into ONE fact, and list every bullet index it came from.
- Keep genuinely different achievements as separate facts.
- Each statement is one sentence. When sources differ in detail, keep the specific details
  (numbers, methods, tools, outcomes) exactly as written in the sources.
- Set uses_website_text when the statement relies on the website page text.
- Set substantive to false for facts too thin to support technical interview questions.
- Do not include any person's name. Refer to the person as "you" or omit the subject.
"""

QUESTIONS_SYSTEM = """\
You write interview practice questions about a candidate's own work, for Data Scientist (DS)
and ML/AI Engineer (MLE) interviews. The candidate will answer them out loud or in writing.

DEPTHS (each question has exactly one depth and a difficulty inside its range):
- explain (difficulty 2-4): describe what was done and why it mattered.
- justify (4-6): defend a method or design choice and the alternatives considered.
- challenge (6-9): a skeptical interviewer probing weaknesses: leakage, small samples, metric
  choice, label quality, baselines, generalization, confounding, evaluation design.
- extend (6-10): how to scale, productionize, monitor, or redo it with more time, data or compute.

DIFFICULTY ANCHORS (apply within the depth's range): 1-2 recall; 3-4 apply a standard method to a
clean case; 5-6 multi-step reasoning or choosing between methods with tradeoffs; 7-8 subtle
pitfalls, edge cases, senior-level depth; 9-10 open-ended design or research-level reasoning with
several interacting issues.

ROLE (assigned from what the question tests, not from where the fact came from):
- ds: statistics, experimentation, analysis, interpreting and communicating results.
- mle: building, deploying, scaling or evaluating ML/LLM systems and engineering practices.
- both: genuinely tests both. Each fact's role_hint is only a hint.

TYPES: mostly free_text (with model_answer or answer_guidance, a rubric of 3-6 concrete,
checkable points, and 0-3 short interviewer follow_ups). Add a few short_answer (one-line answer
plus explanation) or multiple_choice (exactly 4 options, answer_index 0-3, explanation of why the
right answer is right and the strongest distractor is wrong) about concrete numbers and methods
stated in the facts. hints: 0-2. est_minutes: realistic (2-12). tags: 2-5 lowercase keywords.

GROUNDING RULE (most important):
- model_answer, rubric, answer, options and explanation may only use facts provided here.
  Never invent numbers, motivations, results, alternatives tried, team roles or other details.
- General domain knowledge (what a method is, standard pitfalls, how one would scale something)
  is allowed in challenge/extend answers, but must not be presented as something the candidate did.
- If a strong answer needs information the facts do not contain (why a choice was made, what was
  tried first, what someone else did, what happened next), set needs_user_input to true, leave
  model_answer null, and write answer_guidance: what a strong answer should cover and which of the
  candidate's facts to draw on. Do not fabricate a model answer.
- Never include any person's name.

Every question lists the fact_ids it is based on (from the provided facts). Avoid near-duplicate
prompts. Write prompts in the second person ("In your ... project, you ...").
"""

BEHAVIORAL_SYSTEM = """\
You write behavioral interview questions (STAR format) grounded in one of the candidate's
non-technical jobs or volunteer roles, for Data Scientist and ML/AI Engineer interviews.

Rules:
- type is always free_text; depth is null; difficulty 2-7; role is "both" unless the question
  clearly tests only DS or only MLE skills.
- Focus on leadership, training staff, handling problems, reliability, teamwork, prioritization.
- The rubric lists STAR elements and what interviewers listen for (3-6 checkable points).
- GROUNDING: only use facts provided. The candidate's specific story details (what exactly
  happened, outcomes) are not in the facts, so set needs_user_input to true, leave model_answer
  null, and write answer_guidance describing what a strong answer covers and which facts to use.
- Never include any person's name. Each question lists the fact_ids it uses.
"""


def entity_block(entity: dict[str, Any], doc_labels: dict[str, str]) -> str:
    lines = [
        f"Entity id: {entity['id']}",
        f"Name: {entity.get('org')}" + (f" — {entity['title']}" if entity.get("title") else ""),
        f"Type: {entity['type']}; dates: {entity.get('date') or 'n/a'}",
        "",
        "Bullets (index, resumes it appears on, text):",
    ]
    for i, b in enumerate(entity["bullets"]):
        srcs = ", ".join(doc_labels.get(s, s) for s in b["sources"])
        lines.append(f"[{i}] ({srcs}) {b['text']}")
    site = entity.get("website")
    lines += ["", "Website page text:", site["text"] if site else "(none)"]
    return "\n".join(lines)


def facts_user(entity: dict[str, Any], doc_labels: dict[str, str]) -> str:
    return (
        entity_block(entity, doc_labels)
        + "\n\nGroup these sources into distinct facts following the rules."
    )


def question_target(
    facts: list[dict[str, Any]], per_fact: tuple[int, int], behavioral: bool
) -> tuple[int, int]:
    """Total number of questions to request for an entity."""
    if behavioral:
        return 3, 5
    substantive = sum(1 for f in facts if f["substantive"])
    thin = len(facts) - substantive
    lo, hi = per_fact
    return max(1, substantive * lo), max(1, substantive * hi + thin)


def questions_user(
    entity: dict[str, Any],
    facts: list[dict[str, Any]],
    doc_labels: dict[str, str],
    per_fact: tuple[int, int],
    behavioral: bool,
) -> str:
    facts_json = json.dumps(
        [{k: f[k] for k in ("fact_id", "statement", "role_hint", "substantive")} for f in facts],
        indent=1,
        ensure_ascii=False,
    )
    total_lo, total_hi = question_target(facts, per_fact, behavioral)
    if behavioral:
        target = (
            f"Write between {total_lo} and {total_hi} behavioral questions in total, "
            "spread over the facts."
        )
    else:
        lo, hi = per_fact
        target = (
            f"Write between {total_lo} and {total_hi} questions in total: {lo}-{hi} for each "
            "substantive fact, covering all four depths where they make sense, and at most 1 for "
            "each non-substantive fact. Return every question in the single JSON object; do not "
            "stop early or return a sample."
        )
    return (
        entity_block(entity, doc_labels)
        + "\n\nFacts (use these fact_ids):\n"
        + facts_json
        + "\n\n"
        + target
        + "\n\nFill every field. Use null (or an empty list) for fields that do not apply to the "
        "question type. A needs_user_input question must have answer_guidance and a rubric."
    )
