import type { components } from "./api/ahdt";

export type DTKind = components["schemas"]["DTKind"];

export const PERSON_TWINS = [
  "cardiovascular", "respiratory", "nervous", "sensory", "digestive", "hepatobiliary",
  "renal_urinary", "endocrine", "immune_lymphatic", "haematological", "musculoskeletal",
  "integumentary", "reproductive", "whole_body", "behavioural_cognitive", "social",
  "population",
] as const;

export type PersonTwin = (typeof PERSON_TWINS)[number];

export function isPersonTwin(value: string): value is PersonTwin {
  return (PERSON_TWINS as readonly string[]).includes(value);
}
