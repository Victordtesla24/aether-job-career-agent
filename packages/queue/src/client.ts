/**
 * BullMQ/Redis queue client.
 *
 * The heavy `Queue` instantiation is created lazily via {@link createQueue} so
 * unit tests can exercise the pure connection/name helpers without a live Redis.
 */
import { Queue, type QueueOptions } from 'bullmq';

/** Canonical Phase-1 queue names. */
export const QUEUE_NAMES = {
  discovery: 'discovery',
  tailoring: 'tailoring',
  application: 'application',
} as const;

export type QueueName = (typeof QUEUE_NAMES)[keyof typeof QUEUE_NAMES];

/** Minimal ioredis-compatible connection descriptor. */
export interface RedisConnectionOptions {
  host: string;
  port: number;
}

/**
 * Parse a Redis URL into connection options. Falls back to `process.env.REDIS_URL`.
 * Returns `null` when no URL is available, letting the caller decide how to fail.
 */
export function getRedisConnectionOptions(url?: string): RedisConnectionOptions | null {
  const target = url ?? process.env.REDIS_URL;
  if (!target) return null;
  const parsed = new URL(target);
  return {
    host: parsed.hostname,
    port: parsed.port ? Number(parsed.port) : 6379,
  };
}

/**
 * Create a BullMQ queue bound to the given (or discovered) Redis connection.
 * Throws when no connection is configured — callers must ensure REDIS_URL is set.
 */
export function createQueue<T = unknown>(
  name: QueueName,
  options?: Partial<QueueOptions> & { url?: string },
): Queue<T> {
  const connection = getRedisConnectionOptions(options?.url);
  if (!connection) {
    throw new Error('REDIS_URL is not configured; cannot create a queue');
  }
  const { url: _url, connection: _conn, ...rest } = options ?? {};
  return new Queue<T>(name, { connection, ...rest });
}
