import type { PrismaClient, Prisma, ApplicationStatus } from '@prisma/client';

/** Data-access for job applications (approval-gated at the service layer). */
export class ApplicationRepository {
  constructor(private readonly prisma: PrismaClient) {}

  create(data: Prisma.ApplicationUncheckedCreateInput) {
    return this.prisma.application.create({ data });
  }

  findById(id: string) {
    return this.prisma.application.findUnique({ where: { id } });
  }

  listByUser(userId: string) {
    return this.prisma.application.findMany({ where: { userId }, orderBy: { createdAt: 'desc' } });
  }

  updateStatus(id: string, status: ApplicationStatus) {
    return this.prisma.application.update({ where: { id }, data: { status } });
  }
}
