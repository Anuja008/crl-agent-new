import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { GoogleGenAI, Schema } from '@google/genai';
import { ZodType } from 'zod';

export interface JsonRequest<T> {
  /** Short label for logs, e.g. "analyse-role". */
  task: string;
  system: string;
  prompt: string;
  /** Gemini response schema: forces the model to return this JSON shape. */
  schema: Schema;
  /** Zod schema: checks the JSON really matches before we use it. */
  validator: ZodType<T>;
  temperature?: number;
  /** Used only when LLM_PROVIDER=mock, so the pipeline can be tested without an API key. */
  mock: () => T;
}

const RETRYABLE = new Set([408, 429, 500, 502, 503, 504]);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

@Injectable()
export class LlmService {
  private readonly logger = new Logger(LlmService.name);
  private readonly provider: string;
  private readonly model: string;
  private readonly temperature: number;
  private readonly client?: GoogleGenAI;
  private readonly azureEndpoint?: string;
  private readonly azureApiKey?: string;

  constructor(config: ConfigService) {
    this.provider = config.get<string>('LLM_PROVIDER', 'gemini').trim().toLowerCase();
    this.temperature = Number(config.get<string>('LLM_TEMPERATURE', config.get<string>('GEMINI_TEMPERATURE', '0.7')));
    if (this.provider === 'gemini') {
      this.model = config.get<string>('GEMINI_MODEL', 'gemini-2.5-flash');
      const apiKey = config.get<string>('GEMINI_API_KEY');
      if (!apiKey) throw new Error('GEMINI_API_KEY is not set. Set it, or use LLM_PROVIDER=mock.');
      this.client = new GoogleGenAI({ apiKey });
    } else if (this.provider === 'azure' || this.provider === 'azure-openai') {
      this.model = config.get<string>('AZURE_OPENAI_MODEL', '');
      this.azureEndpoint = config.get<string>('AZURE_OPENAI_ENDPOINT', '').replace(/\/+$/, '');
      this.azureApiKey = config.get<string>('AZURE_OPENAI_API_KEY');
      if (!this.azureEndpoint || !this.azureApiKey || !this.model) {
        throw new Error('Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_MODEL when LLM_PROVIDER=azure.');
      }
    } else if (this.provider === 'mock') {
      this.model = 'mock';
    } else {
      throw new Error(`Unsupported LLM_PROVIDER "${this.provider}". Use gemini, azure, or mock.`);
    }
  }

  get modelName(): string {
    return this.model;
  }

  async generateJson<T>(req: JsonRequest<T>): Promise<T> {
    if (this.provider === 'mock') return req.validator.parse(req.mock());

    const maxAttempts = 4;
    let lastError: unknown;
    let prompt = req.prompt;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const text = this.provider === 'gemini'
          ? (await this.client!.models.generateContent({
              model: this.model,
              contents: prompt,
              config: {
                systemInstruction: req.system,
                responseMimeType: 'application/json',
                responseSchema: req.schema,
                temperature: req.temperature ?? this.temperature,
              },
            })).text ?? ''
          : await this.generateAzureJson(req, prompt);
        const parsed = req.validator.safeParse(JSON.parse(text));
        if (parsed.success) return parsed.data;

        // Wrong shape: tell the model what was wrong and try again.
        lastError = parsed.error;
        this.logger.warn(`[${req.task}] invalid JSON shape (attempt ${attempt}): ${parsed.error.message}`);
        prompt = `${req.prompt}\n\nYour previous answer did not match the required format:\n${parsed.error.message}\nReturn corrected JSON only.`;
      } catch (err: any) {
        lastError = err;
        const status = err?.status ?? err?.code;
        const isJsonError = err instanceof SyntaxError;
        if (!isJsonError && !RETRYABLE.has(Number(status))) throw err;
        const wait = 1000 * 2 ** (attempt - 1);
        this.logger.warn(`[${req.task}] attempt ${attempt} failed (${status ?? err?.message}); retrying in ${wait} ms`);
        await sleep(wait);
      }
    }
    throw new Error(`[${req.task}] failed after ${maxAttempts} attempts: ${String((lastError as any)?.message ?? lastError)}`);
  }

  private async generateAzureJson<T>(req: JsonRequest<T>, prompt: string): Promise<string> {
    const response = await fetch(`${this.azureEndpoint}/openai/v1/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'api-key': this.azureApiKey! },
      body: JSON.stringify({
        model: this.model,
        messages: [
          { role: 'system', content: `${req.system}\nReturn an object matching the supplied JSON schema.` },
          { role: 'user', content: prompt },
        ],
        temperature: req.temperature ?? this.temperature,
        response_format: {
          type: 'json_schema',
          json_schema: { name: req.task.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 64), strict: true, schema: toJsonSchema(req.schema) },
        },
      }),
    });
    if (!response.ok) {
      const detail = await response.text();
      const error = new Error(`Azure OpenAI request failed (${response.status}): ${detail}`) as Error & { status: number };
      error.status = response.status;
      throw error;
    }
    const result = await response.json() as { choices?: Array<{ message?: { content?: string } }> };
    const content = result.choices?.[0]?.message?.content;
    if (!content) throw new Error('Azure OpenAI returned an empty response.');
    return content;
  }
}

/** Convert the subset of Gemini Schema used by this project into Azure JSON Schema. */
function toJsonSchema(schema: Schema): Record<string, unknown> {
  const typeNames: Record<string, string> = {
    TYPE_UNSPECIFIED: 'object', STRING: 'string', NUMBER: 'number', INTEGER: 'integer',
    BOOLEAN: 'boolean', ARRAY: 'array', OBJECT: 'object', NULL: 'null',
  };
  const rawType = String(schema.type ?? 'OBJECT').split('.').pop()!;
  const result: Record<string, unknown> = { type: typeNames[rawType] ?? rawType.toLowerCase() };
  if (schema.description) result.description = schema.description;
  if (schema.properties) {
    result.properties = Object.fromEntries(Object.entries(schema.properties).map(([key, value]) => [key, toJsonSchema(value)]));
    result.additionalProperties = false;
  }
  if (schema.required?.length) result.required = schema.required;
  if (schema.items) result.items = toJsonSchema(schema.items);
  return result;
}
