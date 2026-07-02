/**
 * Prisma client singleton.
 *
 * A single instance is reused across hot-reloads in development to avoid
 * exhausting the (capped) Postgres connection pool. The client connects lazily
 * on first query, so importing this module never opens a connection by itself.
 */
import { PrismaClient } from '@prisma/client';

const globalForPrisma = globalThis as unknown as { aetherPrisma?: PrismaClient };

export const prisma: PrismaClient =
  globalForPrisma.aetherPrisma ?? new PrismaClient({ log: ['warn', 'error'] });

if (process.env.NODE_ENV !== 'production') {
  globalForPrisma.aetherPrisma = prisma;
}
