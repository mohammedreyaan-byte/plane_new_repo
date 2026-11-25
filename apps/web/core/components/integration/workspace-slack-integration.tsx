/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useState } from "react";
import { observer } from "mobx-react";
import { Check, CheckCircle2, Hash, MessageSquare, RefreshCw, Send, Unplug } from "lucide-react";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { AlertModalCore, EModalWidth, ModalCore } from "@plane/ui";
// services
import { gmcFeaturesService, startProviderOAuth, type SlackSettings } from "@/services/gmc-features.service";

const errorMessage = (error: unknown) => {
  const detail = error as { error?: string; message?: string } | undefined;
  return detail?.error ?? detail?.message ?? "The request could not be completed.";
};

const EMPTY_SETTINGS: SlackSettings = {
  connected: false,
  default_channel_id: "",
  channels: [],
  events: {},
  notifications: [],
  event_catalog: [],
};

const channelName = (settings: SlackSettings, id: string) =>
  settings.channels.find((channel) => channel.channel_id === id)?.channel_name ?? "the selected channel";

const eventLabel = (settings: SlackSettings, key: string) =>
  settings.event_catalog.find((event) => event.key === key)?.label ?? key;

/** Workspace settings > Integrations > Slack: real OAuth, channel subscriptions and message history. */
export const WorkspaceSlackIntegration = observer(function WorkspaceSlackIntegration({
  workspaceSlug,
}: {
  workspaceSlug: string;
}) {
  const [slack, setSlack] = useState<SlackSettings>(EMPTY_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);
  const [connectOpen, setConnectOpen] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      setSlack(await gmcFeaturesService.getSlackSettings(workspaceSlug));
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load Slack settings", message: errorMessage(error) });
    } finally {
      setIsLoading(false);
    }
  }, [workspaceSlug]);

  useEffect(() => {
    void load();
  }, [load]);

  const connect = async () => {
    setBusy(true);
    try {
      await startProviderOAuth(workspaceSlug, "slack");
      await load();
      setConnectOpen(false);
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Slack connected", message: "Workspace channels are ready to use." });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Connection failed", message: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await gmcFeaturesService.disconnectSlack(workspaceSlug);
      await load();
      setDisconnectOpen(false);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Slack disconnected",
        message: "Notifications for this workspace have stopped.",
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to disconnect", message: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  const update = async (data: { default_channel_id?: string; events?: Record<string, boolean> }, title: string) => {
    try {
      await gmcFeaturesService.updateSlackSettings(workspaceSlug, data);
      await load();
      setToast({ type: TOAST_TYPE.SUCCESS, title, message: "Slack settings were saved." });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to save settings", message: errorMessage(error) });
    }
  };

  const toggleEvent = (key: string) => {
    const nextValue = !slack.events[key];
    void update(
      { events: { ...slack.events, [key]: nextValue } },
      `${eventLabel(slack, key)} ${nextValue ? "enabled" : "disabled"}`
    );
  };

  const selectChannel = (id: string) => {
    void update({ default_channel_id: id }, "Default channel updated");
  };

  const refreshChannels = async () => {
    setBusy(true);
    try {
      const channels = await gmcFeaturesService.refreshSlackChannels(workspaceSlug);
      await load();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Channels refreshed",
        message: `${channels.length} channels are available for this workspace.`,
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Channel refresh failed", message: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  const sendTestMessage = async () => {
    setBusy(true);
    try {
      await gmcFeaturesService.sendSlackTest(workspaceSlug, slack.default_channel_id);
      await load();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Test message sent",
        message: `Delivered to ${channelName(slack, slack.default_channel_id)}.`,
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Test message failed", message: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  const latestMessage = slack.notifications[0];

  return (
    <section className="space-y-6" aria-label="Slack integration">
      <div className="rounded-md border border-subtle p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-layer-2">
              <MessageSquare className="size-5 text-accent-primary" aria-hidden="true" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-16 font-medium text-primary">Slack</h2>
                <span
                  className={`rounded-sm px-2 py-0.5 text-10 font-medium ${
                    slack.connected ? "bg-success-subtle text-success-primary" : "bg-layer-2 text-secondary"
                  }`}
                >
                  {slack.connected ? "Connected" : "Not connected"}
                </span>
              </div>
              <p className="mt-1 max-w-2xl text-12 text-secondary">
                Post Plane work item updates to a Slack channel. Choose the channel and the events that should send
                notifications.
              </p>
              {slack.connected && (
                <p className="mt-2 text-11 text-tertiary">
                  {slack.team_name || slack.team_id} · {slack.team_id}
                </p>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {slack.connected ? (
              <>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => void sendTestMessage()}
                  disabled={busy || !slack.default_channel_id}
                  aria-label="Send Slack test message"
                >
                  <Send className="size-4" aria-hidden="true" /> Test connection
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setDisconnectOpen(true)}
                  aria-label="Disconnect Slack"
                >
                  <Unplug className="size-4" aria-hidden="true" /> Disconnect
                </Button>
              </>
            ) : (
              <Button variant="primary" size="sm" onClick={() => setConnectOpen(true)} aria-label="Connect Slack">
                <MessageSquare className="size-4" aria-hidden="true" /> Connect Slack
              </Button>
            )}
          </div>
        </div>
      </div>

      {!slack.connected ? (
        <div className="rounded-md border border-dashed border-subtle px-6 py-12 text-center">
          <MessageSquare className="mx-auto size-8 text-tertiary" aria-hidden="true" />
          <h3 className="mt-3 text-14 font-medium text-primary">Connect a Slack workspace</h3>
          <p className="mx-auto mt-1 max-w-md text-12 text-secondary">
            {isLoading
              ? "Loading Slack settings..."
              : "Authorize Plane, pick a default channel, then choose which work item events should post updates."}
          </p>
          <Button
            variant="primary"
            size="sm"
            className="mt-4"
            onClick={() => setConnectOpen(true)}
            aria-label="Connect Slack"
          >
            Connect Slack
          </Button>
        </div>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-md border border-subtle">
              <div className="border-b border-subtle px-4 py-3">
                <h3 className="text-14 font-medium text-primary">Default channel</h3>
                <p className="text-12 text-secondary">Selected events post to this channel.</p>
              </div>
              <div className="space-y-3 px-4 py-4">
                <label className="block space-y-1 text-11 text-secondary">
                  Slack channel
                  <div className="relative">
                    <Hash
                      className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-tertiary"
                      aria-hidden="true"
                    />
                    <select
                      aria-label="Slack default channel"
                      className="w-full appearance-none rounded-sm border border-subtle bg-surface-2 py-2 pr-3 pl-8 text-12 text-primary focus:border-accent-strong focus:outline-none"
                      value={slack.default_channel_id}
                      onChange={(event) => selectChannel(event.target.value)}
                    >
                      {slack.channels.map((channel) => (
                        <option key={channel.id} value={channel.channel_id}>
                          {channel.channel_name} · {channel.member_count} members
                        </option>
                      ))}
                    </select>
                  </div>
                </label>
                <div className="flex items-center justify-between gap-3 rounded-sm bg-surface-2 px-3 py-2 text-11 text-secondary">
                  <span>
                    <span className="font-medium text-primary">{slack.team_name || "Slack workspace"}</span> · connected
                    {slack.integration?.created_at
                      ? ` ${new Date(slack.integration.created_at).toLocaleDateString()}`
                      : ""}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => void refreshChannels()}
                    disabled={busy}
                    aria-label="Refresh Slack channels"
                  >
                    <RefreshCw className="size-3.5" aria-hidden="true" /> Refresh
                  </Button>
                </div>
              </div>
            </div>

            <div className="rounded-md border border-subtle">
              <div className="border-b border-subtle px-4 py-3">
                <h3 className="text-14 font-medium text-primary">Latest delivered message</h3>
                <p className="text-12 text-secondary">Real message activity from this integration.</p>
              </div>
              <div className="px-4 py-4">
                {latestMessage ? (
                  <div className="rounded-md border border-subtle bg-surface-2 p-3">
                    <div className="flex items-center gap-2">
                      <div className="flex size-7 items-center justify-center rounded-sm bg-accent-subtle text-accent-primary">
                        <MessageSquare className="size-4" aria-hidden="true" />
                      </div>
                      <div>
                        <p className="text-12 font-medium text-primary">Plane</p>
                        <p className="text-10 text-tertiary">
                          {latestMessage.sent_at ? new Date(latestMessage.sent_at).toLocaleString() : "Pending"} ·{" "}
                          {latestMessage.status}
                        </p>
                      </div>
                    </div>
                    <p className="mt-3 text-12 text-primary">
                      {latestMessage.work_item_identifier ? (
                        <a
                          href={`/${workspaceSlug}/browse/${latestMessage.work_item_identifier}/`}
                          target="_blank"
                          rel="noreferrer"
                          className="font-medium text-accent-primary hover:underline"
                        >
                          {latestMessage.work_item_identifier}
                        </a>
                      ) : (
                        "Workspace message"
                      )}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2 text-10">
                      <span className="rounded-sm bg-layer-2 px-2 py-0.5 text-secondary">
                        Event: {eventLabel(slack, latestMessage.event_type)}
                      </span>
                      <span className="rounded-sm bg-layer-2 px-2 py-0.5 text-secondary">
                        Channel: {channelName(slack, latestMessage.channel)}
                      </span>
                    </div>
                    {latestMessage.error && <p className="mt-2 text-11 text-danger-primary">{latestMessage.error}</p>}
                  </div>
                ) : (
                  <p className="py-6 text-center text-12 text-secondary">
                    No messages have been sent by this integration yet.
                  </p>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-md border border-subtle">
            <div className="border-b border-subtle px-4 py-3">
              <h3 className="text-14 font-medium text-primary">Event subscriptions</h3>
              <p className="text-12 text-secondary">Toggle which work item events post to Slack.</p>
            </div>
            <div className="divide-y divide-subtle">
              {slack.event_catalog.map((event) => (
                <label
                  key={event.key}
                  className="flex cursor-pointer items-start justify-between gap-4 px-4 py-3 hover:bg-surface-1"
                >
                  <span>
                    <span className="block text-12 font-medium text-primary">{event.label}</span>
                    <span className="font-mono mt-0.5 block text-10 text-tertiary">{event.key}</span>
                  </span>
                  <input
                    type="checkbox"
                    aria-label={`Slack event ${event.label}`}
                    checked={Boolean(slack.events[event.key])}
                    onChange={() => toggleEvent(event.key)}
                    className="accent-accent-primary mt-0.5 size-4 shrink-0"
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="rounded-md border border-subtle">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle px-4 py-3">
              <div>
                <h3 className="text-14 font-medium text-primary">Recent Slack notifications</h3>
                <p className="text-12 text-secondary">Messages delivered by this integration.</p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void sendTestMessage()}
                disabled={busy || !slack.default_channel_id}
                aria-label="Send test Slack notification"
              >
                <Send className="size-3.5" aria-hidden="true" /> Send test message
              </Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-12">
                <thead className="bg-surface-2 text-secondary">
                  <tr>
                    <th className="px-4 py-2 font-medium">Event</th>
                    <th className="px-4 py-2 font-medium">Work item</th>
                    <th className="px-4 py-2 font-medium">Channel</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">Time</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-subtle">
                  {slack.notifications.map((notification) => (
                    <tr key={notification.id} data-testid="slack-notification">
                      <td className="px-4 py-3 text-primary">{eventLabel(slack, notification.event_type)}</td>
                      <td className="px-4 py-3">
                        {notification.work_item_identifier ? (
                          <a
                            href={`/${workspaceSlug}/browse/${notification.work_item_identifier}/`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-accent-primary hover:underline"
                          >
                            {notification.work_item_identifier}
                          </a>
                        ) : (
                          <span className="text-secondary">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-secondary">{channelName(slack, notification.channel)}</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1 rounded-sm bg-success-subtle px-2 py-0.5 text-10 text-success-primary">
                          <CheckCircle2 className="size-3" aria-hidden="true" /> {notification.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-tertiary">
                        {notification.sent_at ? new Date(notification.sent_at).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {slack.notifications.length === 0 && (
                <p className="border-t border-subtle px-4 py-6 text-center text-12 text-secondary">
                  No messages sent yet. Use Test connection to send one.
                </p>
              )}
            </div>
          </div>
        </>
      )}

      <ModalCore isOpen={connectOpen} handleClose={() => setConnectOpen(false)} width={EModalWidth.XXL}>
        <div className="space-y-4 p-6">
          <div className="flex items-center gap-2">
            <MessageSquare className="size-5 text-primary" aria-hidden="true" />
            <h3 className="text-16 font-medium text-primary">Connect Slack</h3>
          </div>
          <p className="text-12 text-secondary">
            Plane will open the Slack authorization page in a secure popup. Tokens are exchanged by the backend and
            stored encrypted.
          </p>
          <ul className="space-y-1.5 text-11 text-secondary">
            {["View channel lists", "Post messages to selected channels", "Read work item event subscriptions"].map(
              (scope) => (
                <li key={scope} className="flex items-center gap-2">
                  <Check className="size-3.5 text-success-primary" aria-hidden="true" /> {scope}
                </li>
              )
            )}
          </ul>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setConnectOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void connect()}
              disabled={busy}
              aria-label="Authorize Slack workspace"
            >
              Authorize with Slack
            </Button>
          </div>
        </div>
      </ModalCore>

      <AlertModalCore
        isOpen={disconnectOpen}
        handleClose={() => setDisconnectOpen(false)}
        handleSubmit={() => void disconnect()}
        isSubmitting={false}
        title="Disconnect Slack?"
        content="All event subscriptions will stop posting to Slack. Message history remains available for audit."
      />
    </section>
  );
});
