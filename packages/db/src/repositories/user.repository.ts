import type { PrismaClient } from '@prisma/client';

export interface UpsertUserInput {
  email: string;
  name?: string;
  image?: string;
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
