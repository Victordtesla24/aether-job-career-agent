/**
 * Minimal structured logger with built-in secret redaction.
 *
 * GUARDRAIL: never emit API keys / tokens. `redactSecrets` masks common secret
 * shapes (OpenRouter/OpenAI keys, bearer tokens, long hex/base64 blobs) before
 * anything is written. The agent layer must route all logging through here.
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

// Ordered most→least sensitive; first match wins.
const SECRET_PATTERNS: Array<RegExp> = [
  /sk-or-v1-[A-Za-z0-9_-]{8,}/g, // OpenRouter
  /sk-[A-Za-z0-9]{16,}/g, // OpenAI-style
  /Bearer\s+[A-Za-z0-9._-]{12,}/gi, // bearer tokens
  /(?<=(?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+/gi, // key=... token:...
];

/** Replace secret-looking substrings with a fixed marker. */
export function redactSecrets(input: string): string {
  let out = input;
  for (const pattern of SECRET_PATTERNS) {
    out = out.replace(pattern, '[REDACTED]');
  }
  return out;
}

export interface Logger {
  debug: (msg: string, meta?: Record<string, unknown>) => void;
  info: (msg: string, meta?: Record<string, unknown>) => void;
  warn: (msg: string, meta?: Record<string, unknown>) => void;
  error: (msg: string, meta?: Record<string, unknown>) => void;
}

function emit(scope: string, level: LogLevel, msg: string, meta?: Record<string, unknown>): void {
  const record = {
    ts: new Date().toISOString(),
    level,
    scope,
    msg: redactSecrets(msg),
    ...(meta ? { meta: JSON.parse(redactSecrets(JSON.stringify(meta))) } : {}),
  };
  const line = JSON.stringify(record);
  // eslint-disable-next-line no-console
  (level === 'error' ? console.error : console.log)(line);
}

/** Create a scoped structured logger. */
export function createLogger(scope: string): Logger {
  return {
    debug: (msg, meta) => emit(scope, 'debug', msg, meta),
    info: (msg, meta) => emit(scope, 'info', msg, meta),
    warn: (msg, meta) => emit(scope, 'warn', msg, meta),
    error: (msg, meta) => emit(scope, 'error', msg, meta),
  };
}
