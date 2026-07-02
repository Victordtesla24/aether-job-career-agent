import type { PrismaClient, Prisma, JobStatus } from '@prisma/client';

/**
 * Data-access for jobs. All reads/writes are expected to be user-scoped by the
 * caller (multi-tenant isolation is enforced at the service layer).
 */
export class JobRepository {
  constructor(private readonly prisma: PrismaClient) {}

  create(data: Prisma.JobUncheckedCreateInput) {
    return this.prisma.job.create({ data });
  }

  findById(id: string) {
    return this.prisma.job.findUnique({ where: { id } });
  }

  listByUser(userId: string) {
    return this.prisma.job.findMany({ where: { userId }, orderBy: { createdAt: 'desc' } });
  }

  updateStatus(id: string, status: JobStatus) {
    return this.prisma.job.update({ where: { id }, data: { status } });
  }
}
