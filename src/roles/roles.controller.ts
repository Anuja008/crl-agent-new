import { Body, Controller, Get, NotFoundException, Param, Post, Query } from '@nestjs/common';
import { RoleAgentService } from '../agent/role-agent.service';
import { DictionaryService } from '../dictionary/dictionary.service';
import { GenerateRoleDto } from './generate-role.dto';

@Controller()
export class RolesController {
  constructor(
    private readonly agent: RoleAgentService,
    private readonly dict: DictionaryService,
  ) {}

  /** Generate (or return cached) CRL 1-5 descriptions for a new role and save them to the CSV dictionary. */
  @Post('roles/generate')
  generate(@Body() dto: GenerateRoleDto) {
    return this.agent.generate(dto);
  }

  /** All roles in the mapping file. */
  @Get('roles')
  roles() {
    return this.dict.roles();
  }

  /** Stored descriptions for one role, e.g. /roles/fresher-qa-engineer-manual/descriptions */
  @Get('roles/:slug/descriptions')
  async descriptions(@Param('slug') slug: string, @Query('competency') competency?: string) {
    const rows = await this.dict.roleDescriptions(slug);
    if (!rows.length) throw new NotFoundException(`No descriptions for "${slug}". Generate them with POST /roles/generate.`);
    return competency ? rows.filter((r) => r['Competency ID'] === competency) : rows;
  }

  @Get('competencies')
  competencies() {
    return this.dict.competencies();
  }

  @Get('crl-scale')
  crlScale() {
    return this.dict.crlScale();
  }
}
