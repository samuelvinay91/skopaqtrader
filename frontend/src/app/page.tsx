"use client";

import { useEffect, useState } from "react";

interface SystemStatus {
  version: string;
  mode: string;
  broker: {
    name: string;
    token_valid: boolean;
    token_remaining: string | null;
    token_warning: string | null;
  };
  services: {
    supabase: boolean;
    redis: boolean;
    llms: Record<string, boolean>;
  };
}

export default function Home() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const backendUrl =
      process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

    fetch(`${backendUrl}/api/status`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setStatus)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-gray-400">
          Connecting to backend...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-lg p-6">
        <h2 className="text-red-400 font-semibold mb-2">
          Backend Unavailable
        </h2>
        <p className="text-gray-400 text-sm">
          Could not connect to the SkopaqTrader backend. Make sure it is running
          with <code className="text-gray-300">skopaq serve</code>.
        </p>
        <p className="text-gray-500 text-xs mt-2">Error: {error}</p>
      </div>
    );
  }

  if (!status) return null;

  const activeLlms = Object.entries(status.services.llms)
    .filter(([, v]) => v)
    .map(([k]) => k);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h2 className="text-2xl font-bold">System Status</h2>
        <span
          className={`text-xs px-2 py-1 rounded-full font-medium ${
            status.mode === "paper"
              ? "bg-yellow-900/50 text-yellow-400"
              : "bg-green-900/50 text-green-400"
          }`}
        >
          {status.mode.toUpperCase()}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Broker */}
        <StatusCard
          title="Broker"
          value={status.broker.name}
          status={status.broker.token_valid ? "ok" : "error"}
          detail={
            status.broker.token_valid
              ? `Token expires in ${status.broker.token_remaining}`
              : status.broker.token_warning || "Token invalid"
          }
        />

        {/* Supabase */}
        <StatusCard
          title="Database"
          value="Supabase"
          status={status.services.supabase ? "ok" : "warning"}
          detail={
            status.services.supabase ? "Connected" : "Not configured"
          }
        />

        {/* Redis */}
        <StatusCard
          title="Cache"
          value="Upstash Redis"
          status={status.services.redis ? "ok" : "warning"}
          detail={status.services.redis ? "Connected" : "Not configured"}
        />

        {/* LLMs */}
        <StatusCard
          title="LLM Models"
          value={`${activeLlms.length} active`}
          status={activeLlms.length > 0 ? "ok" : "error"}
          detail={
            activeLlms.length > 0
              ? activeLlms.join(", ")
              : "No LLM keys configured"
          }
        />
      </div>
    </div>
  );
}

function StatusCard({
  title,
  value,
  status,
  detail,
}: {
  title: string;
  value: string;
  status: "ok" | "warning" | "error";
  detail: string;
}) {
  const colors = {
    ok: "border-green-800 bg-green-900/10",
    warning: "border-yellow-800 bg-yellow-900/10",
    error: "border-red-800 bg-red-900/10",
  };

  const dots = {
    ok: "bg-green-400",
    warning: "bg-yellow-400",
    error: "bg-red-400",
  };

  return (
    <div className={`border rounded-lg p-4 ${colors[status]}`}>
      <div className="flex items-center gap-2 mb-1">
        <div className={`w-2 h-2 rounded-full ${dots[status]}`} />
        <span className="text-sm text-gray-400">{title}</span>
      </div>
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-gray-500 mt-1">{detail}</div>
    </div>
  );
}
