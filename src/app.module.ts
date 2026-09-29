import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { RoleAgentService } from './agent/role-agent.service';
import { CsvStoreService } from './csv/csv-store.service';
import { DictionaryService } from './dictionary/dictionary.service';
import { LlmService } from './llm/llm.service';
import { RolesController } from './roles/roles.controller';

@Module({
  imports: [ConfigModule.forRoot({ isGlobal: true })],
  controllers: [RolesController],
  providers: [CsvStoreService, DictionaryService, LlmService, RoleAgentService],
})
export class AppModule {}
