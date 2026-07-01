import type { PrismaClient, Prisma } from '@prisma/client';

/** Data-access for versioned, tailored resumes. */
export class ResumeRepository {
  constructor(private readonly prisma: PrismaClient) {}

  create(data: Prisma.ResumeUncheckedCreateInput) {
    return this.prisma.resume.create({ data });
  }

  findById(id: string) {
    return this.prisma.resume.findUnique({ where: { id } });
  }

  listByUser(userId: string) {
    return this.prisma.resume.findMany({ where: { userId }, orderBy: { createdAt: 'desc' } });
  }

  /** Find a resume for a user by its immutable format hash (dedupe on re-upload). */
  findByFormatHash(userId: string, formatHash: string) {
    return this.prisma.resume.findFirst({ where: { userId, formatHash } });
  }
}
