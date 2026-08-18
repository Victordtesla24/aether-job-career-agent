/**
 * Display labels for discovery source keys — keep in sync with
 * `SOURCE_DISPLAY_NAMES` in
 * `apps/api/app/services/discovery/adapter_registry.py`.
 *
 * Never invent boards that have no adapter (no jora / workforce).
 */
export const SOURCE_DISPLAY_NAMES: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workable: "Workable",
  smartrecruiters: "SmartRecruiters",
  adzuna: "Adzuna",
  remotive: "Remotive",
  remoteok: "RemoteOK",
  wellfound: "Wellfound",
  seek: "Seek",
  linkedin: "LinkedIn",
  indeed: "Indeed",
};

/** Every known discovery source id (adapter registry order not required). */
export const ALL_SOURCE_IDS = Object.keys(SOURCE_DISPLAY_NAMES);

export function sourceDisplayName(source: string): string {
  return SOURCE_DISPLAY_NAMES[source] ?? source;
}
