/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import { observer } from "mobx-react";
import { Button } from "@plane/propel/button";
import type { IEmailDeliveryLog } from "@plane/types";
// hooks
import { useInstance } from "@/hooks/store";

const STATE_LABELS: Record<IEmailDeliveryLog["state"], string> = {
  delivered: "Delivered",
  failed: "Failed",
  pending: "Pending",
};

export const EmailDeliveryLog = observer(function EmailDeliveryLog() {
  const { emailDeliveryLog, fetchEmailDeliveryLog, fetchEmailDeliveryLogDetail } = useInstance();
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [details, setDetails] = useState<Record<string, IEmailDeliveryLog>>({});

  const load = useCallback(
    async (refreshing = false) => {
      if (refreshing) setIsRefreshing(true);
      else setIsLoading(true);
      try {
        await fetchEmailDeliveryLog();
        setError("");
      } catch (err) {
        setError((err as { error?: string })?.error || "Failed to load the email delivery log");
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [fetchEmailDeliveryLog]
  );

  useEffect(() => {
    void load();
  }, [load]);

  const toggleDetail = async (log: IEmailDeliveryLog) => {
    const nextExpanded = !expanded[log.id];
    setExpanded((current) => ({ ...current, [log.id]: nextExpanded }));
    if (!nextExpanded || details[log.id]) return;
    try {
      const detail = await fetchEmailDeliveryLogDetail(log.id);
      setDetails((current) => ({ ...current, [log.id]: detail }));
    } catch (err) {
      setError((err as { error?: string })?.error || "Failed to load the delivery detail");
    }
  };

  if (isLoading) return <div className="text-13 text-tertiary">Loading the email delivery log...</div>;

  return (
    <section className="max-w-4xl space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-16 font-medium text-primary">Delivery log</h3>
          <p className="text-13 text-tertiary">
            The 100 most recent delivery attempts. Credentials and bodies are never shown.
          </p>
        </div>
        <Button variant="secondary" size="sm" loading={isRefreshing} onClick={() => void load(true)}>
          Refresh
        </Button>
      </div>
      {error && <div className="text-13 text-danger-primary">{error}</div>}
      {!error && (!emailDeliveryLog || emailDeliveryLog.length === 0) && (
        <div className="rounded-md border border-subtle p-4 text-13 text-tertiary">No email delivery attempts yet.</div>
      )}
      {!error && emailDeliveryLog && emailDeliveryLog.length > 0 && (
        <div className="divide-y divide-subtle rounded-md border border-subtle">
          {emailDeliveryLog.map((log) => (
            <div key={log.id} className="p-3 text-13">
              <button
                type="button"
                className="flex w-full items-center justify-between gap-4 text-left"
                onClick={() => void toggleDetail(log)}
              >
                <span className="min-w-0">
                  <span className="font-medium text-primary">{log.entity_name || "Email notification"}</span>
                  <span className="ml-2 text-tertiary">{log.receiver_email || "Unknown recipient"}</span>
                </span>
                <span className="shrink-0 text-tertiary">
                  {STATE_LABELS[log.state]} · {log.created_at}
                </span>
              </button>
              {log.last_error && <div className="mt-2 text-danger-primary">{log.last_error}</div>}
              {expanded[log.id] && (
                <div className="mt-2 space-y-1 text-tertiary">
                  <div>Entity: {log.entity || "—"}</div>
                  <div>Attempts: {log.attempts}</div>
                  <div>Next retry: {log.next_retry_at || "—"}</div>
                  <div>Sent at: {log.sent_at || "—"}</div>
                  {details[log.id]?.data ? (
                    <div>Additional context is available in the API detail response.</div>
                  ) : null}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
});
