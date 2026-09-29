import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { parse } from 'csv-parse/sync';
import { stringify } from 'csv-stringify/sync';
import { promises as fs } from 'fs';
import * as path from 'path';

export type Row = Record<string, string>;

/**
 * Reads and writes CSV files in DATA_DIR.
 * - Writes go to a temp file first, then rename, so a crash never leaves a half-written CSV.
 * - A per-file lock stops two requests from writing the same file at once.
 * - Files are written with a UTF-8 BOM so Excel opens them correctly.
 */
@Injectable()
export class CsvStoreService {
  private readonly logger = new Logger(CsvStoreService.name);
  private readonly dataDir: string;
  private readonly locks = new Map<string, Promise<unknown>>();

  constructor(config: ConfigService) {
    this.dataDir = path.resolve(config.get<string>('DATA_DIR', './data'));
  }

  filePath(name: string): string {
    return path.join(this.dataDir, name);
  }

  async read(name: string): Promise<Row[]> {
    try {
      const raw = await fs.readFile(this.filePath(name), 'utf8');
      return parse(raw, { columns: true, bom: true, skip_empty_lines: true, relax_column_count: true }) as Row[];
    } catch (err: any) {
      if (err?.code === 'ENOENT') return [];
      throw err;
    }
  }

  async write(name: string, columns: string[], rows: Row[]): Promise<void> {
    const target = this.filePath(name);
    const tmp = `${target}.${process.pid}.${Date.now()}.tmp`;
    const body = stringify(rows, { header: true, columns });
    await fs.mkdir(this.dataDir, { recursive: true });
    await fs.writeFile(tmp, '\ufeff' + body, 'utf8');
    await fs.rename(tmp, target);
  }

  /** Runs `fn` while holding the lock for `name`. Calls for the same file run one after another. */
  async withLock<T>(name: string, fn: () => Promise<T>): Promise<T> {
    const previous = this.locks.get(name) ?? Promise.resolve();
    let release!: () => void;
    const current = new Promise<void>((resolve) => (release = resolve));
    const chained = previous.then(() => current);
    this.locks.set(name, chained);
    await previous;
    try {
      return await fn();
    } finally {
      release();
      if (this.locks.get(name) === chained) this.locks.delete(name);
    }
  }

  /**
   * Read, change and write a file under one lock.
   * If the file has no header yet, `defaultColumns` are used.
   */
  async update(name: string, defaultColumns: string[], change: (rows: Row[]) => Row[]): Promise<void> {
    await this.withLock(name, async () => {
      const rows = await this.read(name);
      const columns = rows.length ? Object.keys(rows[0]) : defaultColumns;
      for (const c of defaultColumns) if (!columns.includes(c)) columns.push(c);
      const next = change(rows);
      await this.write(name, columns, next);
      this.logger.log(`Wrote ${next.length} rows to ${name}`);
    });
  }
}
