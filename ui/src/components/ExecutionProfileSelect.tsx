import type { Model } from '../lib/types';
import { groupedProfileOptions, profileLabel } from '../lib/executionProfiles';

interface ExecutionProfileSelectProps {
  options: Model[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
  ariaLabel?: string;
  placeholder?: string;
  emptyLabel?: string;
}

export default function ExecutionProfileSelect({
  options,
  value,
  onChange,
  className,
  ariaLabel,
  placeholder = 'Choose execution profile',
  emptyLabel,
}: ExecutionProfileSelectProps) {
  const groups = groupedProfileOptions(options);

  return (
    <select
      aria-label={ariaLabel}
      className={className}
      value={value}
      disabled={options.length === 0}
      onChange={(event) => onChange(event.currentTarget.value)}
    >
      <option value="">{options.length === 0 ? 'Loading profiles...' : (emptyLabel ?? placeholder)}</option>
      {groups.map((group) => (
        <optgroup key={group.provider} label={group.provider}>
          {group.options.map((option) => (
            <option key={option.id} value={option.id}>
              {profileLabel(option)}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
