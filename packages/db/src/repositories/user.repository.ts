import type { PrismaClient } from '@prisma/client';

export interface UpsertUserInput {
  email: string;
  name?: string;
  image?: string;
}

/** Input for creating a credentials-backed user (P2-S01). */
export interface CreateUserInput {
  email: string;
  /** A pre-computed bcrypt hash — never a plaintext password. */
  passwordHash: string;
  name?: string;
}

/** Data-access for user identity (backing NextAuth). */
export class UserRepository {
  constructor(private readonly prisma: PrismaClient) {}

  findById(id: string) {
    return this.prisma.user.findUnique({ where: { id } });
  }

  findByEmail(email: string) {
    return this.prisma.user.findUnique({ where: { email } });
  }

  /** Create a credentials-backed user. Stores only the bcrypt hash. */
  create(input: CreateUserInput) {
    return this.prisma.user.create({ data: input });
  }

  /** Create-or-update a user keyed by email (idempotent sign-in). */
  upsertByEmail(input: UpsertUserInput) {
    const { email, ...rest } = input;
    return this.prisma.user.upsert({
      where: { email },
      create: { email, ...rest },
      update: { ...rest },
    });
  }
}
