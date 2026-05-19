import { createFileRoute } from "@tanstack/react-router";
import { useRef, useState } from "react";
import {
  Plane, Upload, FileText, AlertTriangle, CloudSun, MapPin,
  Clock, Gauge, Fuel, ArrowRight, Loader2, ShieldAlert, CheckCircle2,
} from "lucide-react";

export const Route = createFileRoute("/")({ component: QuickBrief });

type Strip = {
  commercial_flight?: string;
  atc_flight?: string;
  date_of_flight?: string;
  dep_iata?: string;
  dep_icao?: string;
  dep_name?: string;
  dest_iata?: string;
  dest_icao?: string;
  dest_name?: string;
  alt_iata?: string;
  alt_icao?: string;
  alt_name?: string;
  std_utc?: string;
  std_local?: string;
  sta_utc?: string;
  sta_local?: string;
  flight_time?: string;
  ofp_version?: string;
  reg?: string;
  engine_type?: string;
  dep_rwy?: string;
  arr_rwy?: string;
  fl_min?: string;
  fl_max?: string;
  cost_index?: string;
  ramp_fuel?: string;
  ezfw?: string;
  etow?: string;
  elwt?: string;
  max_shear_rate?: string;
  highest_mora?: string;
};

type AirportWeather = {
  icao?: string;
  iata?: string;
  name?: string;
  window_label?: string;
  metar?: string;
  taf?: string[] | string;
};

type Notam = {
  notam_id?: string;
  validity?: string;
  raw_text?: string;
};

type Briefing = {
  strip: Strip;
  dispatch_notes?: string[];
  dep_weather?: AirportWeather | null;
  dest_weather?: AirportWeather | null;
  alt_weather?: AirportWeather | null;
  dep_notams?: Notam[];
  dest_notams?: Notam[];
  alt_notams?: Notam[];
  error?: string;
};

const join = (parts: (string | undefined | null)[], sep = " · ") =>
  parts.map((p) => (p ?? "").toString().trim()).filter(Boolean).join(sep) || "—";

const fmtTime = (v?: string) => {
  if (!v) return "—";
  const m = v.match(/^(\d{1,2}):(\d{2})$/);
  return m ? `${+m[1]}h ${+m[2]}m` : v;
};

function cleanNotam(notam: { raw_text?: string; notam_id?: string }) {
  let text = notam.raw_text ?? "";
  const id = (notam.notam_id ?? "").trim();

  if (id) {
    const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    text = text.replace(new RegExp("^" + escaped + "\\s*", "i"), "");
    text = text.replace(new RegExp("\\b" + escaped + "\\b\\s*(?=COMPANY NOTAM\\s*-)", "i"), "");
    text = text.replace(new RegExp("\\b" + escaped + "\\b\\s*(?=-\\s*CHART NOTAM)", "i"), "");
  }

  text = text.replace(/^VALID:?\s*\d{10}\s*-\s*(?:\d{10}|UFN|PERM)(?:\s+EST)?\s*/i, "");
  text = text.replace(
    /^-\s*(?:CHART NOTAM|COMPANY NOTAM)\s+VALID:?\s*\d{10}\s*-\s*(?:\d{10}|UFN|PERM)(?:\s+EST)?\s*/i,
    "",
  );
  text = text.replace(/^(?:CHART NOTAM|COMPANY NOTAM)\s*-\s*/i, "");
  text = text.replace(/^(?:CHART NOTAM|COMPANY NOTAM)\s+/i, "");
  text = text.replace(/^\-\s*/, "");
  text = text.trim();

  return text || "(no text)";
}

function QuickBrief() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<Briefing | null>(null);

  const handleSubmit = async () => {
    setError("");
    const file = fileRef.current?.files?.[0];

    if (!file) {
      setError("Please choose a PDF file first.");
      return;
    }

    setLoading(true);
    setData(null);

    try {
      const fd = new FormData();
      fd.append("file", file);

      const res = await fetch("https://quickbrief-yox8.onrender.com", {
        method: "POST",
        body: fd,
      });

      const contentType = res.headers.get("content-type") || "";

      if (!res.ok) {
        const message = contentType.includes("application/json")
          ? ((await res.json())?.error ?? `API ${res.status}`)
          : await res.text();
        throw new Error(message || `API ${res.status}`);
      }

      const json = (await res.json()) as Briefing;

      if (json.error) {
        throw new Error(json.error);
      }

      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate briefing.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto max-w-[1240px] px-4 py-6 sm:px-6 sm:py-8">
      <header
        className="mb-5 rounded-[28px] border border-white/60 p-5 sm:p-7"
        style={{ background: "var(--gradient-hero)", boxShadow: "var(--shadow-soft)", backdropFilter: "blur(14px)" }}
      >
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className="grid h-11 w-11 place-items-center rounded-xl text-[13px] font-extrabold tracking-widest text-primary-foreground"
              style={{ background: "var(--gradient-mark)", boxShadow: "0 10px 22px oklch(0.48 0.09 195 / 0.22)" }}
            >
              QB
            </div>
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground">QuickBrief</div>
              <h1 className="text-lg font-bold tracking-tight">OFP Briefing Reader</h1>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white/80 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              <Plane className="h-3.5 w-3.5" /> OFP parser
            </span>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-[1.5fr_1fr]">
          <div className="rounded-2xl border border-border bg-[var(--surface)] p-5 backdrop-blur-md">
            <div className="mb-1 flex items-center gap-2">
              <Upload className="h-4 w-4 text-primary" />
              <h2 className="text-base font-bold tracking-tight">Upload OFP PDF</h2>
            </div>

            <p className="mb-4 text-[13px] text-muted-foreground">
              Drop in your operational flight plan and get a clean, scannable briefing.
            </p>

            <label
              htmlFor="ofp-file"
              className="flex cursor-pointer items-center gap-3 rounded-xl border border-dashed border-foreground/15 bg-white/70 px-4 py-3 transition hover:border-primary/40 hover:bg-white"
            >
              <FileText className="h-5 w-5 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-semibold">{fileName || "Choose a PDF…"}</div>
                <div className="text-[11px] text-muted-foreground">PDF up to 25 MB</div>
              </div>

              <input
                id="ofp-file"
                ref={fileRef}
                type="file"
                accept="application/pdf"
                className="hidden"
                onChange={(e) => setFileName(e.target.files?.[0]?.name ?? "")}
              />
            </label>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={handleSubmit}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-[13px] font-bold text-primary-foreground transition disabled:opacity-60"
                style={{ background: "var(--gradient-mark)", boxShadow: "0 10px 22px oklch(0.48 0.09 195 / 0.22)" }}
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                {loading ? "Generating…" : "Generate Brief"}
              </button>
            </div>

            {error && <p className="mt-3 text-[13px] text-destructive">{error}</p>}
          </div>

          <div className="flex flex-col justify-between gap-4 rounded-2xl border border-border bg-[var(--surface)] p-5 backdrop-blur-md">
            <div>
              <div className="mb-1 flex items-center gap-2">
                <ShieldAlert className="h-4 w-4 text-[var(--warning)]" />
                <h2 className="text-base font-bold tracking-tight">Operational use</h2>
              </div>
              <p className="text-[13px] leading-relaxed text-muted-foreground">
                Information only. Always cross-check against the full Briefing Package and Company Documentation before flight.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[oklch(0.65_0.15_60/0.12)] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-[var(--warning)]">
                <CheckCircle2 className="h-3.5 w-3.5" /> Information only
              </span>
            </div>
          </div>
        </div>
      </header>

      {!data ? (
        <section
          className="grid place-items-center rounded-[22px] border border-border bg-[var(--surface)] px-6 py-20 text-center backdrop-blur-md"
          style={{ boxShadow: "var(--shadow-soft)" }}
        >
          <div className="max-w-sm">
            <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-primary/10 text-primary">
              <Plane className="h-7 w-7" />
            </div>
            <h2 className="mb-1.5 text-xl font-bold tracking-tight">Your briefing will appear here</h2>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Upload an OFP PDF to see summary, weather and key NOTAMs in a single, scannable view.
            </p>
          </div>
        </section>
      ) : (
        <Results data={data} />
      )}

      <footer className="mt-8 text-center text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
        QuickBrief · Built for the flight deck
      </footer>
    </main>
  );
}

function Results({ data }: { data: Briefing }) {
  const s = data.strip ?? {};

  return (
    <div className="grid gap-4 sm:gap-5">
      <section
        className="overflow-hidden rounded-[22px] border border-border bg-[var(--surface-strong)] p-5 sm:p-6"
        style={{ boxShadow: "var(--shadow-soft)" }}
      >
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
          <div className="flex items-center gap-4 sm:gap-6">
            <div>
              <div className="text-[10px] font-extrabold uppercase tracking-[0.16em] text-muted-foreground">Flight</div>
              <div className="font-mono text-2xl font-bold tracking-tight">{join([s.commercial_flight, s.atc_flight], " / ")}</div>
            </div>

            <div className="hidden h-10 w-px bg-border sm:block" />

            <div className="flex items-center gap-3 font-mono">
              <span className="text-2xl font-bold tracking-tight">{s.dep_iata || s.dep_icao || "—"}</span>
              <Plane className="h-5 w-5 -rotate-12 text-primary" />
              <span className="text-2xl font-bold tracking-tight">{s.dest_iata || s.dest_icao || "—"}</span>
            </div>
          </div>

          <div className="text-right">
            <div className="text-[10px] font-extrabold uppercase tracking-[0.16em] text-muted-foreground">Date</div>
            <div className="font-mono text-sm font-bold">{s.date_of_flight ?? "—"}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
  <KPI
    icon={<Clock />}
    label="STD / STA"
    value={`${join([s.std_utc, s.sta_utc], " → ")} UTC`}
    sub={`${join([s.std_local, s.sta_local], " · ")} Local`}
  />
  <KPI
    icon={<Gauge />}
    label="Flight time"
    value={fmtTime(s.flight_time)}
    sub={join([s.fl_min, s.fl_max], "–")}
  />
  <KPI
    icon={<MapPin />}
    label="Runways"
    value={join([s.dep_rwy && `DEP ${s.dep_rwy}`, s.arr_rwy && `ARR ${s.arr_rwy}`], " · ")}
  />
  <KPI icon={<Plane />} label="Aircraft" value={s.reg ?? "—"} sub={s.engine_type ?? "—"} />
  <KPI icon={<FileText />} label="OFP" value={s.ofp_version ?? "—"} />
</div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="grid gap-4">
          <Card title="Operational details" icon={<Gauge className="h-4 w-4" />}>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              <DataItem label="Departure" value={join([s.dep_name, s.dep_icao, s.dep_iata], " / ")} />
              <DataItem label="Destination" value={join([s.dest_name, s.dest_icao, s.dest_iata], " / ")} />
              <DataItem label="Alternate" value={join([s.alt_name, s.alt_icao, s.alt_iata], " / ")} />
              <DataItem label="Ramp fuel" value={s.ramp_fuel} icon={<Fuel className="h-3.5 w-3.5" />} />
              <DataItem label="EZFW" value={s.ezfw} />
              <DataItem label="ETOW" value={s.etow} />
              <DataItem label="ELWT" value={s.elwt} />
              <DataItem label="Max shear" value={s.max_shear_rate} />
              <DataItem label="MORA" value={s.highest_mora} />
              <DataItem label="Cost index" value={s.cost_index} />
            </div>
          </Card>

          <Card title="Dispatch notes" icon={<FileText className="h-4 w-4" />}>
            <div className="grid gap-2">
              {data.dispatch_notes?.length ? (
                data.dispatch_notes.map((n, i) => (
                  <div key={i} className="flex gap-3 rounded-xl border border-border/70 bg-white/70 p-3">
                    <div className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md bg-primary/10 text-[10px] font-bold text-primary">
                      {i + 1}
                    </div>
                    <p className="text-[13px] leading-relaxed">{n}</p>
                  </div>
                ))
              ) : (
                <p className="text-[13px] text-muted-foreground">No dispatch notes.</p>
              )}
            </div>
          </Card>
        </div>

        <Card title="Weather" icon={<CloudSun className="h-4 w-4" />}>
          <div className="grid gap-2.5">
            <WeatherCard label="Departure" tone="primary" wx={data.dep_weather} />
            <WeatherCard label="Destination" tone="accent" wx={data.dest_weather} />
            <WeatherCard label="Alternate" tone="muted" wx={data.alt_weather} />
          </div>
        </Card>
      </section>

      <Card title="Important airport NOTAMs" icon={<AlertTriangle className="h-4 w-4 text-[var(--warning)]" />}>
        <div className="grid gap-3 md:grid-cols-3">
          <NotamCard label="Departure" airport={data.dep_weather} items={data.dep_notams} />
          <NotamCard label="Destination" airport={data.dest_weather} items={data.dest_notams} />
          <NotamCard label="Alternate" airport={data.alt_weather} items={data.alt_notams} />
        </div>
      </Card>
    </div>
  );
}

function KPI({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-white/70 p-3.5">
      <div className="flex items-center gap-1.5 text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
        <span className="[&>svg]:h-3 [&>svg]:w-3">{icon}</span>
        {label}
      </div>
      <div className="mt-1.5 font-mono text-[15px] font-bold leading-tight tracking-tight">{value}</div>
      {sub && <div className="mt-1 truncate text-[11px] leading-snug text-muted-foreground">{sub}</div>}
    </div>
  );
}

function Card({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <article
      className="rounded-[22px] border border-border bg-[var(--surface)] p-5 backdrop-blur-md"
      style={{ boxShadow: "var(--shadow-soft)" }}
    >
      <div className="mb-4 flex items-center gap-2">
        {icon && <span className="text-primary">{icon}</span>}
        <h2 className="text-[15px] font-bold tracking-tight">{title}</h2>
      </div>
      {children}
    </article>
  );
}

function DataItem({ label, value, icon }: { label: string; value?: string; icon?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border/70 bg-white/70 p-3">
      <div className="flex items-center gap-1 text-[10px] font-extrabold uppercase tracking-[0.1em] text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-1 break-words font-mono text-[13px] font-bold leading-snug">{value || "—"}</div>
    </div>
  );
}

function WeatherCard({
  label,
  tone,
  wx,
}: {
  label: string;
  tone: "primary" | "accent" | "muted";
  wx: AirportWeather | null | undefined;
}) {
  const toneClass = {
    primary: "bg-primary/10 text-primary",
    accent: "bg-[oklch(0.72_0.14_75/0.15)] text-[var(--warning)]",
    muted: "bg-muted text-muted-foreground",
  }[tone];

  return (
    <div className="rounded-2xl border border-border bg-white/80 p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-wider ${toneClass}`}>
            {label}
          </span>
          <div className="mt-1.5 text-[15px] font-bold tracking-tight">{wx?.name ?? "—"}</div>
        </div>

        <div className="text-right font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
          {join([wx?.iata, wx?.icao], " / ")}
        </div>
      </div>

      <div className="mb-3 text-[11px] text-muted-foreground">{wx?.window_label ?? ""}</div>

      <div className="mb-2 border-t border-border pt-3">
        <div className="mb-1 text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">METAR</div>
        <div className="break-words font-mono text-[11.5px] leading-relaxed">{wx?.metar ?? "(none)"}</div>
      </div>

      <div className="border-t border-border pt-3">
        <div className="mb-1 text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">TAF</div>
        <div className="break-words font-mono text-[11.5px] leading-relaxed">
          {Array.isArray(wx?.taf) ? wx.taf.join(" ") : (wx?.taf ?? "(none)")}
        </div>
      </div>
    </div>
  );
}

function NotamCard({
  label,
  airport,
  items,
}: {
  label: string;
  airport: AirportWeather | null | undefined;
  items: Notam[] | undefined;
}) {
  return (
    <div className="flex min-h-[180px] flex-col rounded-2xl border border-border bg-white/80 p-4">
      <div className="mb-3 flex items-start justify-between gap-2 border-b border-border pb-3">
        <div>
          <div className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
          <div className="text-[14px] font-bold tracking-tight">{airport?.name ?? "—"}</div>
        </div>

        <div className="font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          {join([airport?.iata, airport?.icao], " / ")}
        </div>
      </div>

      {items?.length ? (
        <div className="grid gap-2">
          {items.map((n, i) => (
            <div key={i} className="rounded-xl border border-border/70 bg-[var(--surface-strong)] p-3">
              <div className="mb-1.5 flex flex-wrap gap-1.5">
                <span className="rounded-full bg-foreground/[0.06] px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider">
                  {n.notam_id ?? "NOTAM"}
                </span>
                <span className="rounded-full bg-[oklch(0.65_0.15_60/0.12)] px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-[var(--warning)]">
                  {n.validity ?? "—"}
                </span>
              </div>
              <div className="break-words font-mono text-[11.5px] leading-relaxed">{cleanNotam(n)}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid flex-1 place-items-center text-[13px] text-muted-foreground">No important NOTAMs found.</div>
      )}
    </div>
  );
}