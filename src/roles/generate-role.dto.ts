import { IsBoolean, IsOptional, IsString, MaxLength, MinLength } from 'class-validator';

export class GenerateRoleDto {
  /** Job title, e.g. "Cloud Support Associate" */
  @IsString() @MinLength(2) @MaxLength(120)
  title: string;

  /** Defaults to "Fresher" */
  @IsOptional() @IsString() @MaxLength(40)
  seniority?: string;

  /** Optional job posting text or employer notes; makes the output more specific */
  @IsOptional() @IsString() @MaxLength(8000)
  context?: string;

  /** Also write role-specific CRL descriptions for the six core competencies (default true) */
  @IsOptional() @IsBoolean()
  includeCore?: boolean;

  /** Regenerate even if this role already exists (default false) */
  @IsOptional() @IsBoolean()
  overwrite?: boolean;
}
