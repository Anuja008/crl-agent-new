import { Schema, Type } from '@google/genai';
import { z } from 'zod';

/* ---------- Step 1: role analysis ---------- */

export const roleAnalysisValidator = z.object({
  roleTitle: z.string().min(2),
  family: z.string().min(2),
  objective: z.string().min(10),
  tasks: z
    .array(z.object({ task: z.string().min(5), competencyRef: z.string().min(2) }))
    .min(4)
    .max(15),
  roleCompetencies: z
    .array(z.object({ ref: z.string().min(2), primary: z.boolean(), whyNeeded: z.string().min(5) }))
    .min(2)
    .max(6),
  newCompetencies: z
    .array(
      z.object({
        proposedName: z.string().min(2),
        definition: z.string().min(10),
        includes: z.string(),
        excludes: z.string(),
        whyNotExisting: z.string().min(5),
      }),
    )
    .max(3),
  tools: z.array(z.string()).max(12),
});
export type RoleAnalysis = z.infer<typeof roleAnalysisValidator>;

export const roleAnalysisSchema: Schema = {
  type: Type.OBJECT,
  properties: {
    roleTitle: { type: Type.STRING, description: 'Clean job title, without seniority' },
    family: { type: Type.STRING, description: 'Role family, preferably one already in use' },
    objective: { type: Type.STRING, description: 'One sentence: what this role exists to achieve' },
    tasks: {
      type: Type.ARRAY,
      description: 'Real tasks a new hire does in the first three months',
      items: {
        type: Type.OBJECT,
        properties: {
          task: { type: Type.STRING },
          competencyRef: { type: Type.STRING, description: 'Existing competency ID (e.g. R05) or the exact proposedName of a new one' },
        },
        required: ['task', 'competencyRef'],
      },
    },
    roleCompetencies: {
      type: Type.ARRAY,
      description: '2-6 role competencies (not core C01-C06)',
      items: {
        type: Type.OBJECT,
        properties: {
          ref: { type: Type.STRING, description: 'Existing R-ID, or the exact proposedName of a new competency' },
          primary: { type: Type.BOOLEAN, description: 'true if the role cannot be done without it' },
          whyNeeded: { type: Type.STRING },
        },
        required: ['ref', 'primary', 'whyNeeded'],
      },
    },
    newCompetencies: {
      type: Type.ARRAY,
      description: 'Only when no existing competency covers the work. Usually empty.',
      items: {
        type: Type.OBJECT,
        properties: {
          proposedName: { type: Type.STRING },
          definition: { type: Type.STRING },
          includes: { type: Type.STRING },
          excludes: { type: Type.STRING, description: 'Nearby skills that belong to existing competencies, with their IDs' },
          whyNotExisting: { type: Type.STRING },
        },
        required: ['proposedName', 'definition', 'includes', 'excludes', 'whyNotExisting'],
      },
    },
    tools: { type: Type.ARRAY, items: { type: Type.STRING } },
  },
  required: ['roleTitle', 'family', 'objective', 'tasks', 'roleCompetencies', 'newCompetencies', 'tools'],
};

/* ---------- Step 2: CRL 1-5 descriptions for one competency in one role ---------- */

export const levelSetValidator = z.object({
  levels: z
    .array(
      z.object({
        crl: z.number().int().min(1).max(5),
        description: z.string().min(20),
        observableSigns: z.array(z.string().min(5)).min(2).max(4),
        typicalTask: z.string().min(10),
      }),
    )
    .length(5),
});
export type LevelSet = z.infer<typeof levelSetValidator>;

export const levelSetSchema: Schema = {
  type: Type.OBJECT,
  properties: {
    levels: {
      type: Type.ARRAY,
      description: 'Exactly five items, CRL 1 to 5 in order',
      items: {
        type: Type.OBJECT,
        properties: {
          crl: { type: Type.INTEGER },
          description: { type: Type.STRING, description: '1-2 sentences, 15-50 words, specific to this role' },
          observableSigns: {
            type: Type.ARRAY,
            description: '2-4 things an assessor can check yes or no',
            items: { type: Type.STRING },
          },
          typicalTask: { type: Type.STRING, description: 'A realistic task from this role that would show this level' },
        },
        required: ['crl', 'description', 'observableSigns', 'typicalTask'],
      },
    },
  },
  required: ['levels'],
};
