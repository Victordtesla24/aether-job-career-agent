// RED: queue connection parsing + typed job builders.
import { describe, it, expect } from 'vitest';
import { getRedisConnectionOptions, QUEUE_NAMES } from '../client.js';
import { DISCOVERY_JOB, buildDiscoveryJob } from '../jobs/discovery.job.js';
import { TAILORING_JOB, buildTailoringJob } from '../jobs/tailoring.job.js';
import { APPLICATION_JOB, buildApplicationJob } from '../jobs/application.job.js';

describe('getRedisConnectionOptions', () => {
  it('parses host and port from a redis url', () => {
    const opts = getRedisConnectionOptions('redis://cache.internal:6380');
    expect(opts).toEqual({ host: 'cache.internal', port: 6380 });
  });

  it('defaults the port to 6379 when omitted', () => {
    const opts = getRedisConnectionOptions('redis://localhost');
    expect(opts).toEqual({ host: 'localhost', port: 6379 });
  });

  it('returns null when no url is provided or discoverable', () => {
    const prev = process.env.REDIS_URL;
    delete process.env.REDIS_URL;
    expect(getRedisConnectionOptions()).toBeNull();
    if (prev !== undefined) process.env.REDIS_URL = prev;
  });
});

describe('QUEUE_NAMES', () => {
  it('exposes the three phase-1 queues', () => {
    expect(QUEUE_NAMES).toEqual({
      discovery: 'discovery',
      tailoring: 'tailoring',
      application: 'application',
    });
  });
});

describe('job builders', () => {
  it('builds a discovery job with a stable name and typed payload', () => {
    const job = buildDiscoveryJob({ userId: 'u1', query: 'senior engineer', sources: ['seek'] });
    expect(job.name).toBe(DISCOVERY_JOB);
    expect(job.data).toEqual({ userId: 'u1', query: 'senior engineer', sources: ['seek'] });
  });

  it('builds a tailoring job', () => {
    const job = buildTailoringJob({ userId: 'u1', jobId: 'j1', resumeId: 'r1' });
    expect(job.name).toBe(TAILORING_JOB);
    expect(job.data.jobId).toBe('j1');
  });

  it('builds an application job', () => {
    const job = buildApplicationJob({ userId: 'u1', applicationId: 'a1' });
    expect(job.name).toBe(APPLICATION_JOB);
    expect(job.data.applicationId).toBe('a1');
  });
});
