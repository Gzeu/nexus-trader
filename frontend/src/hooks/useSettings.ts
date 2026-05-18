import useSWR from "swr";
import { apiFetch } from "@/lib/config";
import { SettingsResponse } from "@/types/settings";

const fetcher = (url: string) => apiFetch<SettingsResponse>(url);

export function useSettings() {
  const { data, error, isLoading, mutate } = useSWR<SettingsResponse>(
    "/api/v1/settings",
    fetcher,
    { revalidateOnFocus: false }
  );

  return { data, error, isLoading, mutate };
}
