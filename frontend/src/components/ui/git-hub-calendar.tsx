"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { addDays, format, startOfWeek, subDays, differenceInCalendarDays } from "date-fns";
import "./git-hub-calendar.css";

export interface ContributionDay {
  date: string;
  count: number;
  received?: number;
  pending?: number;
  ignored?: number;
}

interface GitHubCalendarProps {
  data: ContributionDay[];
  selectedDate?: string;
  onPeriodChange?: (period: string) => void;
  onDaySelect?: (date: string) => void;
  colors?: string[];
}

// Stable variation keeps the weather from jumping when live mail data refreshes.
function weatherVariation(seed: number) {
  const value = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return value - Math.floor(value);
}

export function GitHubCalendar({ data, selectedDate, onPeriodChange, onDaySelect, colors = ["#e8edf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"] }: GitHubCalendarProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const [todayKey, setTodayKey] = useState(() => new Date().toISOString().slice(0, 10));
  const [period, setPeriod] = useState("rolling");
  const [seasonEffects, setSeasonEffects] = useState(true);
  useEffect(() => setSelected(selectedDate ?? null), [selectedDate]);
  useEffect(() => {
    const timer = window.setInterval(() => setTodayKey(new Date().toISOString().slice(0, 10)), 30000);
    return () => window.clearInterval(timer);
  }, []);
  const today = new Date(`${todayKey}T00:00:00`);
  const years = Array.from(new Set(data.map(day => Number(day.date.slice(0, 4)))).values()).filter(Number.isFinite).sort((a, b) => b - a);
  const rangeStart = period === "rolling" ? subDays(today, 364) : new Date(Number(period), 0, 1);
  const rangeEnd = period === "rolling" ? today : new Date(Number(period), 11, 31);
  const start = startOfWeek(rangeStart, { weekStartsOn: 0 });
  const length = differenceInCalendarDays(rangeEnd, start) + 1;
  const weeks = Math.ceil(length / 7);
  const seasonBands: { season: "snow" | "heat" | "rain"; week: number; weeks: number }[] = [];
  for (let week = 0; week < weeks; week++) {
    const weekStart = addDays(start, week * 7);
    const month = (weekStart < rangeStart ? rangeStart : weekStart).getMonth();
    const season = month <= 1 || month >= 10 ? "snow" : month <= 5 ? "heat" : "rain";
    const previous = seasonBands[seasonBands.length - 1];
    if (previous?.season === season) previous.weeks++;
    else seasonBands.push({ season, week, weeks: 1 });
  }
  const rangeStartKey = format(rangeStart, "yyyy-MM-dd");
  const rangeEndKey = format(rangeEnd, "yyyy-MM-dd");
  const values = new Map(data.map(day => [day.date, day]));
  const dayData = (key: string): ContributionDay | undefined => values.get(key);
  const displayDate = (key: string) => format(new Date(`${key}T00:00:00`), "dd/MM/yyyy");
  return <section className="github-calendar" aria-label="Employee reply completion calendar">
    <div className="github-calendar-toolbar">
      <div className="github-periods" role="group" aria-label="Calendar period">
      {["rolling", ...years.map(String)].map(value => <button type="button" key={value} aria-pressed={period === value} onClick={() => { setPeriod(value); setSelected(null); onPeriodChange?.(value); }}>{value === "rolling" ? "Last 365 days" : value}</button>)}
      </div>
      <button type="button" className="github-season-toggle" aria-pressed={seasonEffects} onClick={() => setSeasonEffects(value => !value)}>Season effects {seasonEffects ? "on" : "off"}</button>
    </div>
    <div className="github-calendar-scroll">
      <div className="github-calendar-layout" style={{ gridTemplateColumns: `32px repeat(${weeks}, 14px)` }}>
        <div />
        {Array.from({ length: weeks }, (_, week) => {
          const date = addDays(start, week * 7);
          const previous = addDays(date, -7);
          const visibleDate = date < rangeStart ? rangeStart : date;
          const previousVisibleDate = previous < rangeStart ? rangeStart : previous;
          const label = week === 0 || visibleDate.getMonth() !== previousVisibleDate.getMonth();
          return <span className="github-month" key={week}>{label ? format(visibleDate, "MMM") : ""}</span>;
        })}
        {Array.from({ length: 7 }, (_, weekday) => <div className="github-weekday" key={`label-${weekday}`} style={{ gridColumn: 1, gridRow: weekday + 2 }}>{["", "Mon", "", "Wed", "", "Fri", ""][weekday]}</div>)}
        {Array.from({ length }, (_, index) => {
          const key = format(addDays(start, index), "yyyy-MM-dd");
          if (key < rangeStartKey || key > rangeEndKey) return null;
          const day = dayData(key);
          const count = day?.count ?? 0;
          const rate = day?.received ? Math.min(1, count / day.received) : 0;
          const level = day?.received !== undefined ? (rate <= 0 ? 0 : rate < .5 ? 1 : rate < .75 ? 2 : rate < 1 ? 3 : 4) : Math.min(4, Math.max(0, count));
          const received = day?.received ?? 0;
          const replied = day?.count ?? 0;
          const description = `${displayDate(key)}: ${received} received, ${replied} replied, ${day?.pending ?? 0} pending, ${day?.ignored ?? 0} ignored`;
          return <button type="button" key={key} className="github-day" style={{ gridColumn: Math.floor(index / 7) + 2, gridRow: index % 7 + 2, backgroundColor: colors[level] || colors[colors.length - 1] }} title={description} aria-label={description} aria-pressed={selected === key} onClick={() => { setSelected(key); onDaySelect?.(key); }} />;
        })}
        {seasonEffects && seasonBands.map(band => {
          const particles = Math.max(3, Math.ceil(band.weeks * (band.season === "rain" ? 2 : band.season === "snow" ? 1.4 : .45)));
          return <div key={`${period}-${band.week}`} className={`github-weather github-weather-${band.season}`} aria-hidden="true" style={{ gridColumn: `${band.week + 2} / span ${band.weeks}`, gridRow: "2 / span 7" }}>
            {band.season === "heat" && <svg className="github-summer-sun" viewBox="0 0 32 32" focusable="false"><circle cx="16" cy="16" r="6" /><path d="M16 2v4m0 20v4M2 16h4m20 0h4M6 6l3 3m14 14 3 3M6 26l3-3M23 9l3-3" /></svg>}
            {Array.from({ length: particles }, (_, index) => {
              const seed = band.week * 53 + index * 7;
              return <span className="github-weather-particle" key={index} style={{ left: `${(index + .1 + weatherVariation(seed) * .8) / particles * 100}%`, top: band.season === "heat" ? `${15 + weatherVariation(seed + 1) * 70}%` : undefined, animationDelay: `${-weatherVariation(seed + 2) * 20}s`, animationDuration: `${(band.season === "rain" ? 1.4 : band.season === "snow" ? 5 : 7) + weatherVariation(seed + 3) * (band.season === "rain" ? 1.2 : 6)}s`, "--weather-drift": `${-12 + weatherVariation(seed + 4) * 24}px`, "--weather-scale": .65 + weatherVariation(seed + 5) * .7 } as CSSProperties}>
              {band.season === "snow" && <svg viewBox="0 0 12 12" focusable="false"><path d="M6 1v10M1.7 3.5l8.6 5M1.7 8.5l8.6-5" /></svg>}
            </span>; })}
          </div>;
        })}
      </div>
    </div>
    <div className="github-legend"><span>Reply completion</span><span>Low</span>{colors.map((color, index) => <span key={index} className="github-swatch" style={{ backgroundColor: color }} />)}<span>High</span></div>
  </section>;
}
