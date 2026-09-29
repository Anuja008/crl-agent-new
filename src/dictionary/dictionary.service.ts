import { Injectable } from '@nestjs/common';
import { CsvStoreService, Row } from '../csv/csv-store.service';

export const FILES = {
  competencies: 'competency_dictionary.csv',
  crlScale: 'crl_scale.csv',
  roles: 'role_competency_mapping.csv',
  descriptions: 'role_crl_descriptions.csv',
} as const;

export const COMPETENCY_COLUMNS = [
  'ID', 'Type', 'Competency', 'Definition', 'Includes', 'Excludes (belongs elsewhere)',
  'Role families', 'Example fresher tasks', 'Typical tools', 'Status',
];

export const ROLE_COLUMNS = [
  'Role family', 'Fresher role', 'Role objective', 'Primary role competencies',
  'Secondary role competencies', 'Core competencies', 'Typical tools', 'Status',
];

export const DESCRIPTION_COLUMNS = [
  'Role slug', 'Role', 'Seniority', 'Role family', 'Competency ID', 'Competency', 'Type', 'Primary',
  'CRL', 'Level name', 'Description', 'Observable signs', 'Typical task', 'Rule note',
  'Quality status', 'Quality issues', 'Model', 'Generated at',
];

export interface Competency {
  id: string;
  type: 'Core' | 'Role';
  name: string;
  definition: string;
  includes: string;
  excludes: string;
  status: string;
}

export interface CrlLevel {
  crl: number;
  name: string;
  tag: string;
  meaning: string;
  question: string;
  aiMeaning: string;
  notThisLevelIf: string;
  misreading: string;
}

export const slugify = (title: string, seniority: string) =>
  `${seniority}-${title}`.toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

@Injectable()
export class DictionaryService {
  constructor(private readonly store: CsvStoreService) {}

  async competencies(): Promise<Competency[]> {
    const rows = await this.store.read(FILES.competencies);
    return rows.map((r) => ({
      id: r['ID'],
      type: r['Type'] === 'Core' ? 'Core' : 'Role',
      name: r['Competency'],
      definition: r['Definition'],
      includes: r['Includes'],
      excludes: r['Excludes (belongs elsewhere)'],
      status: r['Status'],
    }));
  }

  /** CRL 1-5 levels plus the scale rules, from crl_scale.csv. */
  async crlScale(): Promise<{ levels: CrlLevel[]; rules: string[] }> {
    const rows = await this.store.read(FILES.crlScale);
    const levels = rows
      .filter((r) => /^CRL \d$/.test(r['CRL']))
      .map((r) => ({
        crl: Number(r['CRL'].replace('CRL ', '')),
        name: r['Level name'],
        tag: r['Tag'],
        meaning: r['Universal meaning (locked)'],
        question: r['Key assessor question'],
        aiMeaning: r['What it means when AI is used'],
        notThisLevelIf: r['Not this level if'],
        misreading: r['Common misreading to avoid'],
      }));
    const rules = rows.filter((r) => r['CRL'] === 'Rule').map((r) => r['Level name']);
    if (levels.length !== 5) throw new Error(`crl_scale.csv must contain CRL 1-5, found ${levels.length}`);
    return { levels, rules };
  }

  async roles(): Promise<Row[]> {
    return this.store.read(FILES.roles);
  }

  async roleDescriptions(slug?: string): Promise<Row[]> {
    const rows = await this.store.read(FILES.descriptions);
    return slug ? rows.filter((r) => r['Role slug'] === slug) : rows;
  }

  /** Next free R-number, skipping any IDs already taken. */
  async nextCompetencyIds(count: number): Promise<string[]> {
    const used = new Set((await this.competencies()).map((c) => c.id));
    const ids: string[] = [];
    for (let n = 1; ids.length < count; n++) {
      const id = `R${String(n).padStart(2, '0')}`;
      if (!used.has(id)) ids.push(id);
    }
    return ids;
  }

  async addCompetencies(rows: Row[]): Promise<void> {
    if (!rows.length) return;
    await this.store.update(FILES.competencies, COMPETENCY_COLUMNS, (existing) => {
      const ids = new Set(existing.map((r) => r['ID']));
      return [...existing, ...rows.filter((r) => !ids.has(r['ID']))];
    });
  }

  /** Adds the role, or replaces it if a role with the same title already exists. */
  async upsertRole(row: Row): Promise<void> {
    await this.store.update(FILES.roles, ROLE_COLUMNS, (existing) => [
      ...existing.filter((r) => r['Fresher role'] !== row['Fresher role']),
      row,
    ]);
  }

  /** Replaces all description rows for one role. */
  async replaceRoleDescriptions(slug: string, rows: Row[]): Promise<void> {
    await this.store.update(FILES.descriptions, DESCRIPTION_COLUMNS, (existing) => [
      ...existing.filter((r) => r['Role slug'] !== slug),
      ...rows,
    ]);
  }
}
