import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Parse API timestamps of the form "YYYY-MM-DD HH:mm:ss-OF"
 * (space separator, no colon in UTC offset) into a Date.
 */
export function parseApiDate(s: string): Date {
  const iso = s
    .replace(' ', 'T')
    .replace(/([+-]\d{2})$/, '$1:00')
  return new Date(iso)
}
