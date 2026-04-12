import type { ExecutionProfile, Model } from './types';

function thinkingRank(thinking?: string | null): number {
  switch (thinking) {
    case 'low':
      return 0;
    case 'medium':
      return 1;
    case 'high':
      return 2;
    case 'xhigh':
      return 3;
    default:
      return 99;
  }
}

export function profileLabel(option: Model): string {
  return option.label ?? `${option.provider} · ${option.name} · ${option.thinking ?? 'medium'}`;
}

export function executionProfileFromOption(option: Model | undefined | null): ExecutionProfile | null {
  if (!option) {
    return null;
  }
  return {
    agent: option.agent ?? option.provider_id ?? null,
    model: option.model ?? option.model_id ?? option.id,
    thinking: option.thinking ?? 'medium',
  };
}

export function optionIdFromExecutionProfile(
  profile: ExecutionProfile | null | undefined,
  options: Model[],
): string {
  if (!profile) {
    return '';
  }
  const agent = profile.agent ?? '';
  const model = profile.model ?? '';
  const thinking = profile.thinking ?? '';

  const exact = options.find(
    (option) =>
      (option.agent ?? option.provider_id ?? '') === agent
      && (option.model ?? option.model_id ?? option.id) === model
      && (option.thinking ?? '') === thinking,
  );
  if (exact) {
    return exact.id;
  }

  const sameModel = options
    .filter(
      (option) =>
        (option.agent ?? option.provider_id ?? '') === agent
        && (option.model ?? option.model_id ?? option.id) === model,
    )
    .sort((left, right) => thinkingRank(left.thinking) - thinkingRank(right.thinking));
  if (sameModel.length > 0) {
    return sameModel[0].id;
  }

  const modelOnly = options
    .filter((option) => (option.model ?? option.model_id ?? option.id) === model)
    .sort((left, right) => thinkingRank(left.thinking) - thinkingRank(right.thinking));
  if (modelOnly.length > 0) {
    return modelOnly[0].id;
  }

  const sameProvider = options.filter(
    (option) => (option.agent ?? option.provider_id ?? '') === agent,
  );
  return sameProvider[0]?.id ?? '';
}

export function groupedProfileOptions(options: Model[]): Array<{ provider: string; options: Model[] }> {
  const groups = new Map<string, Model[]>();
  for (const option of options) {
    const provider = option.provider;
    const existing = groups.get(provider) ?? [];
    existing.push(option);
    groups.set(provider, existing);
  }
  return Array.from(groups.entries()).map(([provider, providerOptions]) => ({
    provider,
    options: providerOptions,
  }));
}
