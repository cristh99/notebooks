import { useSQLQuery } from "@motherduck/react-sql-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export const REQUIRED_DATABASES = [
  { type: "database", path: "md:my_db", alias: "my_db" },
];

const N = (value: unknown): number => (value != null ? Number(value) : 0);

export default function MotherDuckOperationsControl() {
  const summary = useSQLQuery(`
    WITH flights AS (
      SELECT *
      FROM MD_LIST_FLIGHTS(
        "offset" => 0::UINTEGER,
        "limit" => 5000::UINTEGER
      )
    ), recent_queries AS (
      SELECT *
      FROM md_information_schema.query_history
      WHERE start_time >= current_timestamp - INTERVAL '24 hours'
    )
    SELECT
      (SELECT COUNT(*) FROM flights) AS total_flights,
      (SELECT COUNT(*) FROM flights
        WHERE schedule_status = 'SCHEDULE_STATUS_ACTIVE') AS active_schedules,
      (SELECT COUNT(*) FROM recent_queries) AS queries_24h,
      (SELECT COUNT(*) FROM recent_queries
        WHERE error_message IS NOT NULL) AS failed_24h
  `);

  const hourly = useSQLQuery(`
    WITH hours AS (
      SELECT hour_start
      FROM generate_series(
        date_trunc('hour', current_timestamp - INTERVAL '23 hours'),
        date_trunc('hour', current_timestamp),
        INTERVAL '1 hour'
      ) AS t(hour_start)
    ), activity AS (
      SELECT
        date_trunc('hour', start_time) AS hour_start,
        COUNT(*) AS queries,
        COUNT(*) FILTER (WHERE error_message IS NOT NULL) AS failed
      FROM md_information_schema.query_history
      WHERE start_time >= current_timestamp - INTERVAL '24 hours'
      GROUP BY 1
    )
    SELECT
      strftime(h.hour_start, '%m-%d %H:00') AS hour,
      COALESCE(a.queries, 0) AS queries,
      COALESCE(a.failed, 0) AS failed
    FROM hours h
    LEFT JOIN activity a USING (hour_start)
    ORDER BY h.hour_start
  `);

  const categories = useSQLQuery(`
    SELECT
      CASE
        WHEN lower(flight_name) LIKE '%ocr%' THEN 'OCR'
        WHEN lower(flight_name) LIKE '%acquisition%'
          OR lower(flight_name) LIKE '%ledger%'
          OR lower(flight_name) LIKE '%checkpoint%'
          THEN 'Adquisición / ledger'
        WHEN lower(flight_name) LIKE '%cost%'
          OR lower(flight_name) LIKE '%budget%'
          THEN 'Costos'
        WHEN lower(flight_name) LIKE '%legal%'
          OR lower(flight_name) LIKE '%evidence%'
          THEN 'Evidencia / legal'
        ELSE 'Otros'
      END AS category,
      COUNT(*) AS schedules
    FROM MD_LIST_FLIGHTS(
      "offset" => 0::UINTEGER,
      "limit" => 5000::UINTEGER
    )
    WHERE schedule_status = 'SCHEDULE_STATUS_ACTIVE'
    GROUP BY 1
    ORDER BY schedules DESC, category
  `);

  const latestSchedules = useSQLQuery(`
    SELECT
      flight_name,
      schedule_cron,
      strftime(updated_at, '%Y-%m-%d %H:%M') AS updated_utc,
      date_diff('minute', updated_at, current_timestamp) AS age_minutes
    FROM MD_LIST_FLIGHTS(
      "offset" => 0::UINTEGER,
      "limit" => 5000::UINTEGER
    )
    WHERE schedule_status = 'SCHEDULE_STATUS_ACTIVE'
    ORDER BY updated_at DESC, flight_name
    LIMIT 7
  `);

  const summaryRows = Array.isArray(summary.data) ? summary.data : [];
  const hourlyRows = (Array.isArray(hourly.data) ? hourly.data : []).map((row) => ({
    hour: String(row.hour ?? ""),
    queries: N(row.queries),
    failed: N(row.failed),
  }));
  const categoryRows = Array.isArray(categories.data) ? categories.data : [];
  const scheduleRows = Array.isArray(latestSchedules.data)
    ? latestSchedules.data
    : [];
  const s = summaryRows[0] ?? {};

  const kpis: Array<[string, unknown]> = [
    ["Flights", s.total_flights],
    ["Schedules activos", s.active_schedules],
    ["Consultas · 24 h", s.queries_24h],
    ["Fallos · 24 h", s.failed_24h],
  ];

  return (
    <div className="p-6" style={{ background: "#f8f8f8", color: "#231f20" }}>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Control operativo de MotherDuck</h1>
        <p className="text-sm mt-1" style={{ color: "#6a6a6a" }}>
          Inventario y actividad en vivo. Los conteos describen estado; no autorizan intervenciones.
        </p>
      </div>

      <div className="grid grid-cols-4 gap-8 mb-7">
        {kpis.map(([label, value]) => (
          <div key={label}>
            {summary.isLoading ? (
              <div className="h-12 w-24 bg-gray-200 animate-pulse rounded" />
            ) : summary.isError ? (
              <p className="text-5xl font-bold">—</p>
            ) : (
              <p className="text-5xl font-bold">{N(value).toLocaleString()}</p>
            )}
            <p className="text-sm mt-2" style={{ color: "#6a6a6a" }}>
              {label}
            </p>
          </div>
        ))}
      </div>
      {summary.isError ? (
        <p role="alert" className="text-xs mb-5" style={{ color: "#bc1200" }}>
          Resumen no disponible: {String(summary.error ?? "consulta fallida")}
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-8 mb-7">
        <section>
          <h2 className="text-lg font-semibold">Actividad por hora</h2>
          <p className="text-xs mb-3" style={{ color: "#6a6a6a" }}>
            Azul: consultas · rojo: fallos · UTC
          </p>
          {hourly.isLoading ? (
            <div className="bg-gray-100 animate-pulse rounded" style={{ height: 220 }} />
          ) : hourly.isError ? (
            <p role="alert" className="text-sm" style={{ color: "#bc1200" }}>
              {String(hourly.error ?? "consulta fallida")}
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={hourlyRows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
                <XAxis dataKey="hour" fontSize={10} interval="preserveStartEnd" />
                <YAxis fontSize={10} />
                <Tooltip />
                <Line type="linear" dataKey="queries" stroke="#0777b3" strokeWidth={2} dot={false} />
                <Line type="linear" dataKey="failed" stroke="#bc1200" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>

        <section>
          <h2 className="text-lg font-semibold mb-3">Schedules activos por función</h2>
          {categories.isLoading ? (
            <div className="animate-pulse space-y-2">
              <div className="h-4 bg-gray-200 rounded w-3/4" />
              <div className="h-4 bg-gray-200 rounded w-1/2" />
              <div className="h-4 bg-gray-200 rounded w-2/3" />
            </div>
          ) : categories.isError ? (
            <p role="alert" className="text-sm" style={{ color: "#bc1200" }}>
              {String(categories.error ?? "consulta fallida")}
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left" style={{ color: "#6a6a6a" }}>
                  <th className="pb-2 font-medium">Función</th>
                  <th className="pb-2 font-medium text-right">Schedules</th>
                </tr>
              </thead>
              <tbody>
                {categoryRows.map((row) => (
                  <tr key={String(row.category)}>
                    <td className="py-2">{String(row.category)}</td>
                    <td className="py-2 text-right font-semibold">{N(row.schedules)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <section>
        <h2 className="text-lg font-semibold mb-3">Schedules activos modificados recientemente</h2>
        {latestSchedules.isLoading ? (
          <div className="animate-pulse space-y-2">
            <div className="h-4 bg-gray-200 rounded w-full" />
            <div className="h-4 bg-gray-200 rounded w-5/6" />
            <div className="h-4 bg-gray-200 rounded w-4/6" />
          </div>
        ) : latestSchedules.isError ? (
          <p role="alert" className="text-sm" style={{ color: "#bc1200" }}>
            {String(latestSchedules.error ?? "consulta fallida")}
          </p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left" style={{ color: "#6a6a6a" }}>
                <th className="pb-2 font-medium">Flight</th>
                <th className="pb-2 font-medium">Cron UTC</th>
                <th className="pb-2 font-medium">Actualizado UTC</th>
                <th className="pb-2 font-medium text-right">Edad min</th>
              </tr>
            </thead>
            <tbody>
              {scheduleRows.map((row) => (
                <tr key={`${String(row.flight_name)}-${String(row.schedule_cron)}`}>
                  <td className="py-1 pr-4">{String(row.flight_name)}</td>
                  <td className="py-1 pr-4">{String(row.schedule_cron)}</td>
                  <td className="py-1 pr-4">{String(row.updated_utc)}</td>
                  <td className="py-1 text-right">{N(row.age_minutes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
