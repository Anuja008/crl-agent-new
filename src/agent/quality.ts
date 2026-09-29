import { BANNED_WORDS } from './prompts';
import { LevelSet } from './schemas';

const words = (s: string) => s.toLowerCase().match(/[a-z][a-z'-]*/g) ?? [];

function similarity(a: string, b: string): number {
  const A = new Set(words(a).filter((w) => w.length > 3));
  const B = new Set(words(b).filter((w) => w.length > 3));
  if (!A.size || !B.size) return 0;
  let shared = 0;
  A.forEach((w) => B.has(w) && shared++);
  return shared / new Set([...A, ...B]).size;
}

/**
 * Rule-based checks. Returns a list of problems in plain words; empty means it passed.
 * These are fed back to the model when it is asked to rewrite.
 */
export function checkLevelSet(set: LevelSet, roleKeywords: string[]): string[] {
  const issues: string[] = [];
  const levels = [...set.levels].sort((a, b) => a.crl - b.crl);

  const crls = levels.map((l) => l.crl).join(',');
  if (crls !== '1,2,3,4,5') issues.push(`Levels must be exactly CRL 1,2,3,4,5; got ${crls}.`);

  const banned = new RegExp(`\\b(${BANNED_WORDS.join('|')})\\b`, 'i');
  for (const l of levels) {
    const n = words(l.description).length;
    if (n < 12 || n > 60) issues.push(`CRL ${l.crl} description has ${n} words; keep it between 15 and 50.`);
    const hit = `${l.description} ${l.observableSigns.join(' ')}`.match(banned);
    if (hit) issues.push(`CRL ${l.crl} uses the vague word "${hit[1]}". Replace it with what the assessor would see.`);
  }

  const byCrl = (n: number) => levels.find((l) => l.crl === n);
  const l3 = byCrl(3), l4 = byCrl(4), l5 = byCrl(5), l1 = byCrl(1);
  if (l1 && !/\b(explain|describe|identif|name|distinguish|recogni|trace|outline)/i.test(l1.description))
    issues.push('CRL 1 must be about explaining or describing concepts, not doing the work.');
  if (l3 && !/\b(without (being )?(guided|guidance|help|hints|prompting|step-by-step)|unguided|on (their|his|her) own|alone)\b/i.test(l3.description))
    issues.push('CRL 3 must make clear the candidate solves it without being guided to the solution.');
  if (l4 && !/\b(justif|defend|explain(s|ing)? (why|the|their) (choice|decision|trade))/i.test(l4.description))
    issues.push('CRL 4 must say the candidate justifies or defends their decisions and trade-offs.');
  if (l5 && !/\b(real|live|production|over time|ongoing|day-to-day|actual)\b/i.test(l5.description))
    issues.push('CRL 5 must be about real work over time, under real constraints.');

  for (let i = 0; i < levels.length; i++)
    for (let j = i + 1; j < levels.length; j++)
      if (similarity(levels[i].description, levels[j].description) > 0.6)
        issues.push(`CRL ${levels[i].crl} and CRL ${levels[j].crl} read almost the same. Make each level distinct.`);

  // Role specificity: at least three levels should mention something from this role.
  const keys = roleKeywords.map((k) => k.toLowerCase()).filter((k) => k.length > 3);
  if (keys.length) {
    const specific = levels.filter((l) => {
      const text = `${l.description} ${l.typicalTask}`.toLowerCase();
      return keys.some((k) => text.includes(k));
    }).length;
    if (specific < 3)
      issues.push('The descriptions are too generic. Refer to this role\'s actual tasks, work products and tools in at least three levels.');
  }
  return issues;
}

/** Words from the role's tasks and tools, used to test whether descriptions are role-specific. */
export function roleKeywords(tasks: string[], tools: string[]): string[] {
  const stop = new Set(['with', 'from', 'into', 'that', 'their', 'this', 'using', 'based', 'within', 'about', 'other', 'which', 'when', 'where', 'they', 'them', 'make', 'work']);
  const fromTasks = tasks.flatMap(words).filter((w) => w.length > 4 && !stop.has(w));
  return Array.from(new Set([...fromTasks, ...tools.map((t) => t.toLowerCase())]));
}
