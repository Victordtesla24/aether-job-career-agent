// RED: repositories delegate to the injected Prisma client with correct args.
import { describe, it, expect, vi } from 'vitest';
import type { PrismaClient } from '@prisma/client';
import { JobRepository } from '../repositories/job.repository.js';
import { ResumeRepository } from '../repositories/resume.repository.js';
import { ApplicationRepository } from '../repositories/application.repository.js';
import { UserRepository } from '../repositories/user.repository.js';

/** A mock delegate exposing the CRUD methods repositories use. */
function makeDelegate() {
  return {
    create: vi.fn().mockResolvedValue({ id: 'new' }),
    findUnique: vi.fn().mockResolvedValue({ id: 'x' }),
    findFirst: vi.fn().mockResolvedValue({ id: 'first' }),
    findMany: vi.fn().mockResolvedValue([{ id: 'a' }, { id: 'b' }]),
    update: vi.fn().mockResolvedValue({ id: 'updated' }),
    upsert: vi.fn().mockResolvedValue({ id: 'up' }),
  };
}

describe('JobRepository', () => {
  it('creates a job from unchecked input', async () => {
    const job = makeDelegate();
    const repo = new JobRepository({ job } as unknown as PrismaClient);
    const data = { userId: 'u1', title: 'SWE', company: 'Acme', description: 'd', source: 'seek' };
    await repo.create(data);
    expect(job.create).toHaveBeenCalledWith({ data });
  });

  it('finds a job by id', async () => {
    const job = makeDelegate();
    const repo = new JobRepository({ job } as unknown as PrismaClient);
    await repo.findById('j1');
    expect(job.findUnique).toHaveBeenCalledWith({ where: { id: 'j1' } });
  });

  it('lists jobs for a user, newest first', async () => {
    const job = makeDelegate();
    const repo = new JobRepository({ job } as unknown as PrismaClient);
    const rows = await repo.listByUser('u1');
    expect(job.findMany).toHaveBeenCalledWith({
      where: { userId: 'u1' },
      orderBy: { createdAt: 'desc' },
    });
    expect(rows).toHaveLength(2);
  });

  it('updates job status', async () => {
    const job = makeDelegate();
    const repo = new JobRepository({ job } as unknown as PrismaClient);
    await repo.updateStatus('j1', 'applied');
    expect(job.update).toHaveBeenCalledWith({ where: { id: 'j1' }, data: { status: 'applied' } });
  });
});

describe('ResumeRepository', () => {
  it('finds a resume by user + formatHash', async () => {
    const resume = makeDelegate();
    const repo = new ResumeRepository({ resume } as unknown as PrismaClient);
    await repo.findByFormatHash('u1', 'abc123');
    expect(resume.findFirst).toHaveBeenCalledWith({
      where: { userId: 'u1', formatHash: 'abc123' },
    });
  });
});

describe('ApplicationRepository', () => {
  it('updates application status', async () => {
    const application = makeDelegate();
    const repo = new ApplicationRepository({ application } as unknown as PrismaClient);
    await repo.updateStatus('a1', 'submitted');
    expect(application.update).toHaveBeenCalledWith({
      where: { id: 'a1' },
      data: { status: 'submitted' },
    });
  });
});

describe('UserRepository', () => {
  it('finds a user by email', async () => {
    const user = makeDelegate();
    const repo = new UserRepository({ user } as unknown as PrismaClient);
    await repo.findByEmail('a@b.com');
    expect(user.findUnique).toHaveBeenCalledWith({ where: { email: 'a@b.com' } });
  });

  it('upserts a user by email', async () => {
    const user = makeDelegate();
    const repo = new UserRepository({ user } as unknown as PrismaClient);
    await repo.upsertByEmail({ email: 'a@b.com', name: 'A' });
    expect(user.upsert).toHaveBeenCalledWith({
      where: { email: 'a@b.com' },
      create: { email: 'a@b.com', name: 'A' },
      update: { name: 'A' },
    });
  });
});
