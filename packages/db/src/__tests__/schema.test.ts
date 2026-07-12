// RED: structural assertions on the Prisma schema.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const schema = readFileSync(fileURLToPath(new URL('../schema.prisma', import.meta.url)), 'utf8');

describe('prisma schema', () => {
  it('declares the postgresql datasource without provider-specific extensions', () => {
    // Phase 2 portability: the hosted PostgreSQL has no pgvector, so the schema
    // must not require the `vector` extension (or the preview feature for it).
    expect(schema).toMatch(/provider\s*=\s*"postgresql"/);
    expect(schema).not.toMatch(/extensions\s*=\s*\[[^\]]*vector[^\]]*\]/);
    expect(schema).not.toMatch(/previewFeatures\s*=\s*\[[^\]]*postgresqlExtensions[^\]]*\]/);
  });

  it('defines every Phase-1 model', () => {
    for (const model of [
      'User',
      'Job',
      'JobEmbedding',
      'Resume',
      'Application',
      'ApprovalRequest',
      'Contact',
      'EmailThread',
      'StoryEntry',
      'AgentRun',
    ]) {
      expect(schema).toMatch(new RegExp(`model\\s+${model}\\s*\\{`));
    }
  });

  it('stores the job embedding as a portable Float[] column', () => {
    expect(schema).toMatch(/model\s+JobEmbedding\s*\{[\s\S]*?vector\s+Float\[\]/);
  });

  it('keeps a resume formatHash and links tailored resumes to a parent + source job', () => {
    expect(schema).toMatch(/formatHash\s+String/);
    expect(schema).toMatch(/parentId\s+String\?/);
    expect(schema).toMatch(/sourceJobId\s+String\?/);
  });
});
