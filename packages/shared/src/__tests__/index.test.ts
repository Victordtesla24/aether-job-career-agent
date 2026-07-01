// RED: assert the shared package exports exist
import { describe, it, expect } from 'vitest';

describe('packages/shared', () => {
  it('exports a VERSION constant', async () => {
    const { VERSION } = await import('../index.js');
    expect(typeof VERSION).toBe('string');
    expect(VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it('exports Result type utilities', async () => {
    const { ok, err } = await import('../index.js');
    expect(ok('test')).toEqual({ success: true, data: 'test' });
    expect(err('boom')).toEqual({ success: false, error: 'boom' });
  });

  it('exports isOk / isErr guards', async () => {
    const { ok, err, isOk, isErr } = await import('../index.js');
    expect(isOk(ok('x'))).toBe(true);
    expect(isErr(ok('x'))).toBe(false);
    expect(isErr(err('e'))).toBe(true);
    expect(isOk(err('e'))).toBe(false);
  });

  it('exports a structured logger that never emits secrets', async () => {
    const { createLogger } = await import('../index.js');
    const logger = createLogger('test');
    expect(typeof logger.info).toBe('function');
    expect(typeof logger.error).toBe('function');
    // redaction helper masks obvious secret-like values
    const { redactSecrets } = await import('../index.js');
    const masked = redactSecrets('key=sk-or-v1-abcdef1234567890 rest');
    expect(masked).not.toContain('sk-or-v1-abcdef1234567890');
    expect(masked).toContain('[REDACTED]');
  });
});
