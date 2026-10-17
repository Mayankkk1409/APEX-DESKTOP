export type AssistantPlan = {
  id: string;
  name: string;
  subtitle: string | null;
  description: string;
  monthly_price: string;
  annual_checkout: string;
  equivalent_monthly: string;
  twelve_monthly_total: string;
  memos: string;
  horizon: string;
  indicators: string;
  assistant: string;
  alerts: string;
  daily_questions: number | null;
};

export type AssistantEntitlement = {
  plan_id: string;
  plan_name: string;
  daily_questions: number | null;
  used: number;
  unlimited: boolean;
  resets_at: string;
  reset_note: string;
  provider_configured: boolean;
  checkout_available: boolean;
  separate_from_every_plan: string;
};

export type AssistantPlansResponse = {
  plans: AssistantPlan[];
  separate_from_every_plan: string;
  checkout_available: boolean;
};

export type AssistantAskResult = {
  kind: "answer" | "upgrade" | "limit" | "boundary" | "error";
  text: string;
  plan_id: string;
  plan_name: string;
  daily_questions: number | null;
  used: number;
  unlimited: boolean;
  resets_at: string;
  reset_note: string;
  plans: AssistantPlan[] | null;
  separate_from_every_plan: string | null;
  checkout_available: boolean;
};

export type BillingPeriod = "monthly" | "annual";
