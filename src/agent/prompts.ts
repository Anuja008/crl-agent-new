import { Competency, CrlLevel } from '../dictionary/dictionary.service';
import { RoleAnalysis } from './schemas';

export const BANNED_WORDS = [
  'good', 'strong', 'appropriate', 'appropriately', 'sufficient', 'moderately', 'effectively',
  'effective', 'well', 'deep', 'solid', 'excellent', 'proficient', 'seamlessly', 'robust',
];

export function crlContext(levels: CrlLevel[], rules: string[]): string {
  const lines = levels.map(
    (l) =>
      `CRL ${l.crl} - ${l.name} (${l.tag})
  Meaning: ${l.meaning}
  Assessor question: ${l.question}
  With AI: ${l.aiMeaning}
  Not this level if: ${l.notThisLevelIf}
  Avoid this misreading: ${l.misreading}`,
  );
  return `THE CRL SCALE (locked; never change what a level means)
${lines.join('\n\n')}

SCALE RULES
${rules.map((r) => `- ${r}`).join('\n')}`;
}

/* ---------- Step 1 ---------- */

export function analysisSystem(crl: string): string {
  return `You are a job analyst for HAVET, which rates candidates using the Candidate Readiness Level (CRL) framework.
Your job: break a job role into the real work a new hire does, and map that work to competencies from a fixed dictionary.

${crl}

HOW TO ANALYSE A ROLE
1. Start from tasks, not skills. List 6-12 concrete tasks a new hire at the given seniority does in the first three months.
2. Map each task to ONE competency ID from the dictionary.
3. Pick 2-6 ROLE competencies (IDs starting with R). Do not list core competencies C01-C06; they apply to every role automatically.
4. Mark a competency primary only if a hire without it would fail the job.
5. Reuse existing competencies wherever they fit, even if the name is not perfect. Propose a new competency ONLY when no existing one covers the work, at most 3, and explain why.
6. Competencies describe capabilities, never tools. Put tools (languages, software, platforms) in "tools".
7. Use plain, specific words. No marketing language.`;
}

export function analysisPrompt(input: {
  title: string;
  seniority: string;
  context?: string;
  dictionary: Competency[];
  families: string[];
}): string {
  const dict = input.dictionary
    .map((c) => `${c.id} | ${c.type} | ${c.name} | ${c.definition} | Excludes: ${c.excludes || '-'}`)
    .join('\n');
  return `ROLE TO ANALYSE
Title: ${input.title}
Seniority: ${input.seniority}
${input.context ? `Extra context from the employer or job posting:\n${input.context}\n` : ''}
EXISTING ROLE FAMILIES
${input.families.join(', ')}

COMPETENCY DICTIONARY (ID | Type | Name | Definition | Excludes)
${dict}

Return the analysis as JSON.`;
}

/* ---------- Step 2 ---------- */

export function describeSystem(crl: string): string {
  return `You write CRL level descriptions for HAVET. Assessors use them to rate real candidates, so they must be concrete and checkable.

${crl}

WRITING RULES
1. Write for THIS role. Use the role's real tasks, work products, tools and situations. A description that would fit any role is a failure.
2. Keep the universal meaning of each level exactly. Only make it concrete.
   - CRL 1: explains concepts in their own words. No doing yet.
   - CRL 2: does familiar, practised tasks using known methods or templates; seeks guidance when things change.
   - CRL 3: solves an unseen problem within a defined scope WITHOUT being guided to the solution (asking for information or escalating is fine).
   - CRL 4: owns a defined piece of work from brief to a complete, quality-checked result, and JUSTIFIES decisions and trade-offs.
   - CRL 5: performs a representative set of the role's real responsibilities over time, under real constraints, priorities and escalation.
3. Each level must add something the level below does not have. Never reuse the same sentence pattern for every level.
4. Sound like an experienced practitioner describing what they would actually see, not a template. Vary sentence openings.
5. Plain words, 15-50 words per description. Active voice.
6. Never use these vague words: ${BANNED_WORDS.join(', ')}. Say what the assessor would see instead.
7. Observable signs: 2-4 per level, each checkable yes or no by watching the task or reviewing the output.
8. Where AI tools are normal in this role, say how the level treats AI use (for example, checking AI output at CRL 3, owning AI-produced parts at CRL 4).
9. Scope the tasks to the stated seniority. A fresher's CRL 4 is a small complete piece of work, not a whole system.

EXAMPLE OF THE DIFFERENCE (Software Testing, QA Engineer, CRL 3)
Too generic: "Solves unfamiliar testing problems independently and appropriately."
Right: "Given a feature they have never seen, writes test cases that cover wrong inputs and edge cases, finds the serious defects without hints, and writes bug reports a developer can reproduce first time."`;
}

export function describePrompt(input: {
  roleTitle: string;
  seniority: string;
  objective: string;
  analysis: RoleAnalysis;
  competency: Competency;
  isPrimary: boolean;
  feedback?: string[];
}): string {
  const tasks = input.analysis.tasks.map((t) => `- ${t.task} [${t.competencyRef}]`).join('\n');
  const own = input.analysis.tasks.filter((t) => t.competencyRef === input.competency.id).map((t) => `- ${t.task}`);
  return `ROLE
Title: ${input.roleTitle}
Seniority: ${input.seniority}
Objective: ${input.objective}
Tools used: ${input.analysis.tools.join(', ') || 'not specified'}

ALL TASKS IN THIS ROLE
${tasks}

COMPETENCY TO DESCRIBE
${input.competency.id} ${input.competency.name} (${input.competency.type}${input.isPrimary ? ', primary for this role' : ''})
Definition: ${input.competency.definition}
Includes: ${input.competency.includes || '-'}
Excludes: ${input.competency.excludes || '-'}
${own.length ? `Tasks in this role that use it:\n${own.join('\n')}` : 'Show how this competency appears in the tasks above.'}

Write CRL 1 to 5 for this competency in this role.${
    input.feedback?.length
      ? `\n\nYOUR PREVIOUS VERSION FAILED THESE CHECKS. Fix every one:\n${input.feedback.map((f) => `- ${f}`).join('\n')}`
      : ''
  }`;
}
