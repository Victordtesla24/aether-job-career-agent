import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Jobs API client tests (P2-S02).
 *
 * `fetch` is stubbed so the suite runs fully offline: the assertion is that the
 * client returns a validated `Job[]` for a well-formed backend response. The
 * spec snippet omits the stub, but the network is unavailable in unit tests, so
 * mocking `fetch` is the faithful offline equivalent of the acceptance intent.
 */

const sampleJob = {
  id: 'ckjob0000000000000000001',
  title: 'Senior Software Engineer',
  company: 'Acme Pty Ltd',
  location: 'Sydney NSW',
  remote: false,
  description: 'Build scalable backend services.',
  requirements: ['Python', 'Go'],
  source: 'seek',
  sourceUrl: 'https://www.seek.com.au/job/74123456',
  status: 'discovered',
  fitScore: null,
  atsScore: null,
  saved: false,
  createdAt: '2026-07-01T00:00:00.000Z',
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('Jobs API client', () => {
  it('fetchJobs returns Job[]', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([sampleJob])),
    );
    const { fetchJobs } = await import('../../lib/api/jobs.js');
    const jobs = await fetchJobs({ status: 'discovered' });
    expect(Array.isArray(jobs)).toBe(true);
    expect(jobs).toHaveLength(1);
    expect(jobs[0].source).toBe('seek');
    expect(jobs[0].fitScore).toBeNull();
  });

  it('fetchJob returns a single validated Job', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(sampleJob)),
    );
    const { fetchJob } = await import('../../lib/api/jobs.js');
    const job = await fetchJob(sampleJob.id);
    expect(job.id).toBe(sampleJob.id);
    expect(job.title).toBe('Senior Software Engineer');
  });

  it('toggleSaveJob posts and returns the updated Job', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ ...sampleJob, saved: true }));
    vi.stubGlobal('fetch', fetchMock);
    const { toggleSaveJob } = await import('../../lib/api/jobs.js');
    const job = await toggleSaveJob(sampleJob.id);
    expect(job.saved).toBe(true);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('runScoutAgent posts query/location and resolves void', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ accepted: true }, 202));
    vi.stubGlobal('fetch', fetchMock);
    const { runScoutAgent } = await import('../../lib/api/jobs.js');
    await expect(
      runScoutAgent('Software Engineer', 'Sydney'),
    ).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
