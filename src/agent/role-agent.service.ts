import { BadRequestException, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Row } from '../csv/csv-store.service';
import { Competency, DictionaryService, slugify } from '../dictionary/dictionary.service';
import { LlmService } from '../llm/llm.service';
import { analysisPrompt, analysisSystem, crlContext, describePrompt, describeSystem } from './prompts';
import { checkLevelSet, roleKeywords } from './quality';
import {
  LevelSet, RoleAnalysis, levelSetSchema, levelSetValidator, roleAnalysisSchema, roleAnalysisValidator,
} from './schemas';

export interface GenerateRoleInput {
  title: string;
  seniority?: string;
  context?: string;
  includeCore?: boolean;
  overwrite?: boolean;
}

interface Target {
  competency: Competency;
  primary: boolean;
}

const LEVEL_NAMES = ['Understands', 'Applies', 'Solves', 'Delivers', 'Performs at Role Scope'];

async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  });
  await Promise.all(workers);
  return out;
}

@Injectable()
export class RoleAgentService {
  private readonly logger = new Logger(RoleAgentService.name);
  private readonly concurrency: number;
  private readonly maxRevisions: number;

  constructor(
    private readonly dict: DictionaryService,
    private readonly llm: LlmService,
    config: ConfigService,
  ) {
    this.concurrency = Number(config.get('CONCURRENCY', 3));
    this.maxRevisions = Number(config.get('MAX_REVISIONS', 2));
  }

  async generate(input: GenerateRoleInput) {
    const seniority = input.seniority?.trim() || 'Fresher';
    const title = input.title?.trim();
    if (!title) throw new BadRequestException('title is required');
    const slug = slugify(title, seniority);

    if (!input.overwrite) {
      const existing = await this.dict.roleDescriptions(slug);
      if (existing.length) return { slug, cached: true, rows: existing.length, descriptions: existing };
    }

    const [competencies, scale, roles] = await Promise.all([
      this.dict.competencies(),
      this.dict.crlScale(),
      this.dict.roles(),
    ]);
    const crl = crlContext(scale.levels, scale.rules);
    const families = Array.from(new Set(roles.map((r) => r['Role family']).filter(Boolean)));

    // Step 1: analyse the role
    this.logger.log(`Analysing "${title}" (${seniority})`);
    const analysis = await this.llm.generateJson<RoleAnalysis>({
      task: 'analyse-role',
      system: analysisSystem(crl),
      prompt: analysisPrompt({ title, seniority, context: input.context, dictionary: competencies, families }),
      schema: roleAnalysisSchema,
      validator: roleAnalysisValidator,
      temperature: 0.3,
      mock: () => mockAnalysis(title, competencies),
    });

    // Resolve competency references and give new competencies real IDs
    const { targets, newRows, warnings } = await this.resolve(analysis, competencies, input.includeCore !== false);

    // Step 2: describe each competency, with a check-and-revise loop
    const keywords = roleKeywords(analysis.tasks.map((t) => t.task), analysis.tools);
    const results = await mapLimit(targets, this.concurrency, (t) =>
      this.describe(crl, analysis, seniority, t, keywords),
    );

    // Step 3: save
    const now = new Date().toISOString();
    const rows: Row[] = results.flatMap(({ target, set, issues }) =>
      [...set.levels].sort((a, b) => a.crl - b.crl).map((l) => ({
        'Role slug': slug,
        Role: analysis.roleTitle,
        Seniority: seniority,
        'Role family': analysis.family,
        'Competency ID': target.competency.id,
        Competency: target.competency.name,
        Type: target.competency.type,
        Primary: target.competency.type === 'Core' ? '' : target.primary ? 'Yes' : 'No',
        CRL: `CRL ${l.crl}`,
        'Level name': LEVEL_NAMES[l.crl - 1],
        Description: l.description,
        'Observable signs': l.observableSigns.join(' | '),
        'Typical task': l.typicalTask,
        'Rule note': ruleNote(target.competency, l.crl, seniority),
        'Quality status': issues.length ? 'Needs review' : 'Passed checks',
        'Quality issues': issues.join(' | '),
        Model: this.llm.modelName,
        'Generated at': now,
      })),
    );

    await this.dict.addCompetencies(newRows);
    const roleComps = targets.filter((t) => t.competency.type === 'Role');
    await this.dict.upsertRole({
      'Role family': analysis.family,
      'Fresher role': seniority === 'Fresher' ? analysis.roleTitle : `${analysis.roleTitle} (${seniority})`,
      'Role objective': analysis.objective,
      'Primary role competencies': roleComps.filter((t) => t.primary).map((t) => t.competency.id).join('; '),
      'Secondary role competencies': roleComps.filter((t) => !t.primary).map((t) => t.competency.id).join('; '),
      'Core competencies': 'C01-C06 (all six)',
      'Typical tools': analysis.tools.join(', '),
      Status: 'AI-generated hypothesis - confirm with employer task ratings',
    });
    await this.dict.replaceRoleDescriptions(slug, rows);

    return {
      slug,
      cached: false,
      role: analysis.roleTitle,
      family: analysis.family,
      objective: analysis.objective,
      tasks: analysis.tasks,
      tools: analysis.tools,
      competencies: targets.map((t) => ({ id: t.competency.id, name: t.competency.name, type: t.competency.type, primary: t.primary })),
      newCompetencies: newRows.map((r) => ({ id: r['ID'], name: r['Competency'] })),
      needsReview: results.filter((r) => r.issues.length).map((r) => ({ id: r.target.competency.id, issues: r.issues })),
      warnings,
      rows: rows.length,
    };
  }

  private async resolve(analysis: RoleAnalysis, competencies: Competency[], includeCore: boolean) {
    const byId = new Map(competencies.map((c) => [c.id.toUpperCase(), c]));
    const byName = new Map(competencies.map((c) => [c.name.toLowerCase(), c]));
    const warnings: string[] = [];

    // Proposed competencies that duplicate an existing name are reused instead.
    const proposals = analysis.newCompetencies.filter((p) => {
      const dup = byName.get(p.proposedName.toLowerCase());
      if (dup) warnings.push(`"${p.proposedName}" already exists as ${dup.id}; reused it.`);
      return !dup;
    });
    const newIds = await this.dict.nextCompetencyIds(proposals.length);
    const created = new Map<string, Competency>();
    const newRows: Row[] = proposals.map((p, i) => {
      const c: Competency = {
        id: newIds[i], type: 'Role', name: p.proposedName, definition: p.definition,
        includes: p.includes, excludes: p.excludes, status: 'Candidate (AI-proposed, needs review)',
      };
      created.set(p.proposedName.toLowerCase(), c);
      return {
        ID: c.id, Type: 'Role', Competency: c.name, Definition: c.definition, Includes: c.includes,
        'Excludes (belongs elsewhere)': c.excludes, 'Role families': analysis.family,
        'Example fresher tasks': analysis.tasks.filter((t) => t.competencyRef.toLowerCase() === p.proposedName.toLowerCase()).map((t) => t.task).join('; '),
        'Typical tools': analysis.tools.join(', '), Status: c.status,
      };
    });

    const lookup = (ref: string) =>
      byId.get(ref.trim().toUpperCase()) ?? byName.get(ref.trim().toLowerCase()) ?? created.get(ref.trim().toLowerCase());

    // Point task references at real IDs, so later prompts see consistent IDs
    for (const t of analysis.tasks) {
      const c = lookup(t.competencyRef);
      if (c) t.competencyRef = c.id;
    }

    const targets: Target[] = [];
    const seen = new Set<string>();
    for (const rc of analysis.roleCompetencies) {
      const c = lookup(rc.ref);
      if (!c) { warnings.push(`Unknown competency "${rc.ref}" was dropped.`); continue; }
      if (c.type === 'Core') continue; // core are added below
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      targets.push({ competency: c, primary: rc.primary });
    }
    if (!targets.length) throw new BadRequestException('The model did not return any usable role competencies. Try again or add context.');
    if (!targets.some((t) => t.primary)) targets[0].primary = true;

    if (includeCore) competencies.filter((c) => c.type === 'Core').forEach((c) => targets.push({ competency: c, primary: false }));
    return { targets, newRows, warnings };
  }

  private async describe(crl: string, analysis: RoleAnalysis, seniority: string, target: Target, keywords: string[]) {
    let feedback: string[] | undefined;
    let best: { set: LevelSet; issues: string[] } | undefined;

    for (let attempt = 0; attempt <= this.maxRevisions; attempt++) {
      const set = await this.llm.generateJson<LevelSet>({
        task: `describe-${target.competency.id}`,
        system: describeSystem(crl),
        prompt: describePrompt({
          roleTitle: analysis.roleTitle, seniority, objective: analysis.objective, analysis,
          competency: target.competency, isPrimary: target.primary, feedback,
        }),
        schema: levelSetSchema,
        validator: levelSetValidator,
        mock: () => mockLevels(analysis.roleTitle, target.competency, analysis.tools),
      });
      const issues = checkLevelSet(set, keywords);
      if (!best || issues.length < best.issues.length) best = { set, issues };
      if (!issues.length) break;
      this.logger.warn(`${target.competency.id}: ${issues.length} issue(s), revising (attempt ${attempt + 1})`);
      feedback = issues;
    }
    return { target, ...best! };
  }
}

function ruleNote(c: Competency, crl: number, seniority: string): string {
  const notes: string[] = [];
  const behavioural = ['C04', 'C05', 'C06'].includes(c.id);
  if (behavioural && crl === 1) notes.push('Not used for decisions');
  if (behavioural && crl >= 4 && seniority === 'Fresher') notes.push('Freshers capped at CRL 3; needs real work over time');
  if (c.id === 'C06' && crl === 3) notes.push('Needs a multi-day task with check-ins');
  if (c.type === 'Role' && crl === 5) notes.push('Needs real work evidence (internship or multi-day simulation)');
  return notes.join('; ');
}

/* ---------- Mock outputs (LLM_PROVIDER=mock) ---------- */

function mockAnalysis(title: string, dict: Competency[]): RoleAnalysis {
  const roleComps = dict.filter((c) => c.type === 'Role');
  const t = title.toLowerCase();
  const picked = roleComps.filter((c) => c.name.toLowerCase().split(/\W+/).some((w) => w.length > 4 && t.includes(w)));
  const chosen = (picked.length >= 2 ? picked : roleComps.slice(0, 3)).slice(0, 3);
  return {
    roleTitle: title,
    family: 'Mock family',
    objective: `Delivers the core work of a ${title} to the team's standards.`,
    tasks: chosen.flatMap((c) => [
      { task: `Prepare ${c.name.toLowerCase()} work for a ${title} brief`, competencyRef: c.id },
      { task: `Review ${c.name.toLowerCase()} output with the team lead`, competencyRef: c.id },
    ]),
    roleCompetencies: chosen.map((c, i) => ({ ref: c.id, primary: i === 0, whyNeeded: `Needed for ${title} tasks` })),
    newCompetencies: [],
    tools: ['Excel', 'Jira'],
  };
}

function mockLevels(role: string, c: Competency, tools: string[]): LevelSet {
  const n = c.name.toLowerCase();
  const tool = tools[0] ?? 'the team tools';
  return {
    levels: [
      { crl: 1, description: `Explains the main ideas behind ${n} as used by a ${role}, and describes when each applies in daily work.`, observableSigns: ['Explains key terms correctly', 'Gives a relevant example'], typicalTask: `Short viva on ${n} for a ${role}` },
      { crl: 2, description: `Completes a practised ${n} task for a ${role} using a known template in ${tool}, and asks a reviewer when inputs change.`, observableSigns: ['Output matches the template', 'Asks when inputs change'], typicalTask: `Familiar ${n} exercise in ${tool}` },
      { crl: 3, description: `Handles an unseen ${n} problem from a ${role} brief without being guided to the answer, and checks any AI-drafted parts before using them.`, observableSigns: ['Reaches a workable result alone', 'Catches an error in AI output'], typicalTask: `Timed unseen ${n} case` },
      { crl: 4, description: `Takes a small ${role} brief to a finished, checked result for ${n}, then justifies the key decisions and trade-offs in a live review.`, observableSigns: ['Every part of the brief is covered', 'Justifies two decisions'], typicalTask: `Take-home ${n} deliverable with live defence` },
      { crl: 5, description: `Carries out the ${n} part of a ${role} job in real work over several weeks, meeting review standards and escalating blockers early.`, observableSigns: ['Work passes review', 'Blockers raised before deadlines'], typicalTask: `Internship or multi-day simulation` },
    ],
  };
}
