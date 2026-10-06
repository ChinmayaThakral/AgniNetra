import type { Feed } from "./schema";

export interface CityAir {
  city: string;
  pm25: number | null;
  category: string | null;
}

// The chosen city's forecast, or the feed's Delhi default when the feed carries no list.
export function cityAir(feed: Feed, city: string): CityAir {
  const air = feed.air?.find((a) => a.city === city);
  if (air) return { city: air.city, pm25: air.pm25_24h_mean, category: air.cpcb_category };
  const t = feed.tomorrow;
  return { city: t.city, pm25: t.pm25_24h_mean, category: t.cpcb_category };
}
