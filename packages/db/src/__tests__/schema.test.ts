// RED: structural assertions on the Prisma schema.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const schema = readFileSync(fileURLToPath(new URL('../schema.prisma', import.meta.url)), 'utf8');

describe('prisma schema', () => {
  it('declares the postgresql datasource with the pgvector extension', () => {
    expect(schema).toMatch(/provider\s*=\s*"postgresql"/);
    expect(schema).toMatch(/extensions\s*=\s*\[[^\]]*vector[^\]]*\]/);
  });

  it('enables the postgresqlExtensions preview feature', () => {
    expect(schema).toMatch(/previewFeatures\s*=\s*\[[^\]]*postgresqlExtensions[^\]]*\]/);
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

  it('stores the job embedding as a pgvector column', () => {
    expect(schema).toMatch(/vector\s+Unsupported\("vector\(1536\)"\)/);
  });

  it('keeps a resume formatHash and links tailored resumes to a parent + source job', () => {
    expect(schema).toMatch(/formatHash\s+String/);
    expect(schema).toMatch(/parentId\s+String\?/);
    expect(schema).toMatch(/sourceJobId\s+String\?/);
  });
});
