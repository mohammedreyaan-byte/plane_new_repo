/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, ExternalLink, GitBranch, Github, RefreshCw, Trash2 } from "lucide-react";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { AlertModalCore, EModalWidth, ModalCore, ToggleSwitch } from "@plane/ui";
// services
import {
  gmcFeaturesService,
  startProviderOAuth,
  type AppIntegration,
  type ExternalRepository,
  type WebhookEvent,
  type WorkspaceIntegration,
} from "@/services/gmc-features.service";

type Provider = "github" | "gitlab";

const PROVIDERS: Provider[] = ["github", "gitlab"];

const PROVIDER_META: Record<Provider, { label: string; description: string }> = {
  github: {
    label: "GitHub",
    description: "Connect an organization, sync repositories, and link pull requests and commits to work items.",
  },
  gitlab: {
    label: "GitLab",
    description: "Connect a GitLab group or self-managed host and link merge requests and commits to work items.",
  },
};

const errorMessage = (error: unknown) => {
  const detail = error as { error?: string; message?: string } | undefined;
  return detail?.error ?? detail?.message ?? "The request could not be completed.";
};

const emptyRepositories = (): Record<Provider, ExternalRepository[]> => ({ github: [], gitlab: [] });

/** Workspace settings > Integrations: real GitHub/GitLab OAuth, repo sync and webhook activity. */
export function WorkspaceGitIntegrations({ workspaceSlug }: { workspaceSlug: string }) {
  const [appIntegrations, setAppIntegrations] = useState<AppIntegration[]>([]);
  const [workspaceIntegrations, setWorkspaceIntegrations] = useState<WorkspaceIntegration[]>([]);
  const [repositories, setRepositories] = useState<Record<Provider, ExternalRepository[]>>(emptyRepositories);
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [connectingProvider, setConnectingProvider] = useState<Provider | null>(null);
  const [disconnectProvider, setDisconnectProvider] = useState<Provider | null>(null);
  const [busyProvider, setBusyProvider] = useState<Provider | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [available, connected, githubEvents, gitlabEvents] = await Promise.all([
        gmcFeaturesService.getAppIntegrations(workspaceSlug),
        gmcFeaturesService.getWorkspaceIntegrations(workspaceSlug),
        gmcFeaturesService.getWebhookEvents(workspaceSlug, "github"),
        gmcFeaturesService.getWebhookEvents(workspaceSlug, "gitlab"),
      ]);
      setAppIntegrations(available.filter((item) => item.provider !== "slack"));
      setWorkspaceIntegrations(connected.filter((item) => item.provider !== "slack"));
      setEvents(
        // A fresh array is sorted, so the source provider responses are never mutated.
        // oxlint-disable-next-line unicorn/no-array-sort
        [...githubEvents, ...gitlabEvents].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 100)
      );
      const connectedProviders = PROVIDERS.filter((provider) => connected.some((item) => item.provider === provider));
      const repositoryEntries = await Promise.all(
        connectedProviders.map(
          async (provider) => [provider, await gmcFeaturesService.getRepositories(workspaceSlug, provider)] as const
        )
      );
      const nextRepositories = emptyRepositories();
      for (const [provider, items] of repositoryEntries) {
        nextRepositories[provider] = items;
      }
      setRepositories(nextRepositories);
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to load integrations", message: errorMessage(error) });
    } finally {
      setIsLoading(false);
    }
  }, [workspaceSlug]);

  useEffect(() => {
    void load();
  }, [load]);

  const connectionFor = (provider: Provider) => workspaceIntegrations.find((item) => item.provider === provider);
  const appFor = (provider: Provider) => appIntegrations.find((item) => item.provider === provider);

  const completeConnection = async () => {
    if (!connectingProvider) return;
    const provider = connectingProvider;
    setBusyProvider(provider);
    try {
      await startProviderOAuth(workspaceSlug, provider);
      await load();
      setConnectingProvider(null);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: `${PROVIDER_META[provider].label} connected`,
        message: "Repository metadata is now available for this workspace.",
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Connection failed", message: errorMessage(error) });
    } finally {
      setBusyProvider(null);
    }
  };

  const disconnect = async () => {
    if (!disconnectProvider) return;
    const provider = disconnectProvider;
    setBusyProvider(provider);
    try {
      await gmcFeaturesService.deleteWorkspaceIntegration(workspaceSlug, provider);
      await load();
      setDisconnectProvider(null);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: `${PROVIDER_META[provider].label} disconnected`,
        message: "Repository sync and webhook processing were disabled for this workspace.",
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to disconnect", message: errorMessage(error) });
    } finally {
      setBusyProvider(null);
    }
  };

  const toggleRepository = async (provider: Provider, repository: ExternalRepository) => {
    try {
      const updated = await gmcFeaturesService.updateRepository(
        workspaceSlug,
        provider,
        repository.id,
        !repository.is_sync_enabled
      );
      setRepositories((previous) => ({
        ...previous,
        [provider]: previous[provider].map((item) => (item.id === updated.id ? updated : item)),
      }));
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Unable to update repository", message: errorMessage(error) });
    }
  };

  const refreshRepositories = async (provider: Provider) => {
    setBusyProvider(provider);
    try {
      const synced = await gmcFeaturesService.syncRepositories(workspaceSlug, provider);
      setRepositories((previous) => ({ ...previous, [provider]: synced }));
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Repositories refreshed",
        message: `${synced.length} repositories are available for sync.`,
      });
    } catch (error) {
      setToast({ type: TOAST_TYPE.ERROR, title: "Repository refresh failed", message: errorMessage(error) });
    } finally {
      setBusyProvider(null);
    }
  };

  const connectedCount = workspaceIntegrations.length;
  const syncingCount = useMemo(
    () =>
      PROVIDERS.reduce(
        (count, provider) => count + repositories[provider].filter((item) => item.is_sync_enabled).length,
        0
      ),
    [repositories]
  );
  const ProviderIcon = GitBranch;

  return (
    <section className="mt-8 space-y-6" aria-label="Git integrations">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-subtle bg-surface-2 px-4 py-3">
        <div>
          <p className="text-14 font-medium text-primary">
            {connectedCount} of {PROVIDERS.length} providers connected
          </p>
          <p className="text-12 text-secondary">
            {syncingCount} repositories syncing · webhook signatures are verified before links are created.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {PROVIDERS.map((provider) => {
            const connection = connectionFor(provider);
            return (
              <span
                key={provider}
                className="rounded-sm bg-layer-1 px-2 py-1 text-11 text-secondary"
                data-testid="git-provider-status"
              >
                {PROVIDER_META[provider].label}: {connection ? "Connected" : "Not connected"}
              </span>
            );
          })}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {PROVIDERS.map((provider) => {
          const connection = connectionFor(provider);
          const configured = appFor(provider)?.configured ?? false;
          const meta = PROVIDER_META[provider];
          const items = repositories[provider];
          return (
            <div key={provider} className="rounded-md border border-subtle" data-testid="git-provider-card">
              <div className="flex items-start justify-between gap-3 border-b border-subtle px-4 py-4">
                <div className="flex items-start gap-3">
                  <div className="grid size-10 shrink-0 place-items-center rounded-sm bg-layer-2">
                    {provider === "github" ? (
                      <Github className="size-5 text-primary" aria-hidden="true" />
                    ) : (
                      <ProviderIcon className="size-5 text-primary" aria-hidden="true" />
                    )}
                  </div>
                  <div>
                    <h3 className="text-14 font-medium text-primary">{meta.label}</h3>
                    <p className="mt-1 text-12 text-secondary">{meta.description}</p>
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded-sm px-2 py-1 text-11 ${
                    connection ? "bg-success-subtle text-success-primary" : "bg-layer-2 text-tertiary"
                  }`}
                >
                  {connection ? "Connected" : "Not connected"}
                </span>
              </div>

              <div className="space-y-4 px-4 py-4">
                {connection ? (
                  <>
                    <div className="flex flex-wrap items-center gap-2 text-12 text-secondary">
                      <CheckCircle2 className="size-4 text-success-primary" aria-hidden="true" />
                      <span>
                        {connection.account_name || connection.provider_account_id} · {connection.host}
                      </span>
                    </div>
                    <div>
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <p className="text-13 font-medium text-primary">Connected repositories</p>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => void refreshRepositories(provider)}
                          disabled={busyProvider === provider}
                          aria-label={`Refresh ${meta.label} repositories`}
                        >
                          <RefreshCw className="size-4" aria-hidden="true" /> Refresh
                        </Button>
                      </div>
                      <div className="divide-y divide-subtle rounded-sm border border-subtle">
                        {items.map((repository) => (
                          <div
                            key={repository.id}
                            className="flex items-center justify-between gap-3 px-3 py-2"
                            data-testid="git-repository-row"
                          >
                            <div className="min-w-0">
                              <p className="truncate text-12 text-primary">{repository.full_name}</p>
                              <p className="text-11 text-tertiary">
                                Last sync:{" "}
                                {repository.last_synced_at
                                  ? new Date(repository.last_synced_at).toLocaleString()
                                  : "not synced"}
                              </p>
                            </div>
                            <ToggleSwitch
                              value={repository.is_sync_enabled}
                              onChange={() => void toggleRepository(provider, repository)}
                              size="sm"
                              label={`Toggle sync for ${repository.full_name}`}
                            />
                          </div>
                        ))}
                        {items.length === 0 && (
                          <p className="px-3 py-4 text-center text-11 text-secondary">
                            No repositories were returned by this provider.
                          </p>
                        )}
                      </div>
                    </div>
                    <Button
                      variant="error-fill"
                      size="sm"
                      onClick={() => setDisconnectProvider(provider)}
                      aria-label={`Disconnect ${meta.label}`}
                    >
                      <Trash2 className="size-4" aria-hidden="true" /> Disconnect {meta.label}
                    </Button>
                  </>
                ) : (
                  <>
                    <p className="text-12 text-secondary">
                      {configured
                        ? "Authorize Plane to read repositories and receive pull request, merge request and push events."
                        : "Set the provider OAuth credentials in the API environment before connecting."}
                    </p>
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => setConnectingProvider(provider)}
                      aria-label={`Connect ${meta.label}`}
                    >
                      <ProviderIcon className="size-4" aria-hidden="true" /> Connect with {meta.label}
                    </Button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="rounded-md border border-subtle">
        <div className="border-b border-subtle px-4 py-3">
          <h3 className="text-14 font-medium text-primary">Recent webhook activity</h3>
          <p className="text-12 text-secondary">Work item references are linked only from signature-verified events.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-12">
            <thead className="bg-surface-2 text-secondary">
              <tr>
                <th className="px-4 py-2 font-medium">Event</th>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Signature</th>
                <th className="px-4 py-2 font-medium">Work item</th>
                <th className="px-4 py-2 font-medium">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-subtle">
              {events.map((event) => (
                <tr key={event.id} data-testid="git-webhook-event">
                  <td className="px-4 py-2 text-primary">{event.event_type}</td>
                  <td className="px-4 py-2 text-secondary">
                    {PROVIDER_META[event.provider as Provider]?.label ?? event.provider}
                  </td>
                  <td className="px-4 py-2 text-success-primary">
                    {event.signature_verified ? "HMAC verified" : "Unverified"}
                  </td>
                  <td className="px-4 py-2 text-accent-primary">{event.work_item_identifier || "—"}</td>
                  <td className="px-4 py-2 text-secondary">{event.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {events.length === 0 && (
            <p className="border-t border-subtle px-4 py-6 text-center text-12 text-secondary">
              {isLoading ? "Loading webhook activity..." : "No webhook events have been received yet."}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 border-t border-subtle px-4 py-3 text-12 text-secondary">
          <ExternalLink className="size-4" aria-hidden="true" />
          Linked pull requests, merge requests and commits are shown on each work item’s detail page.
        </div>
      </div>

      <ModalCore
        isOpen={connectingProvider !== null}
        handleClose={() => setConnectingProvider(null)}
        width={EModalWidth.LG}
      >
        <div className="space-y-4 p-6">
          <div className="flex items-center gap-3">
            {connectingProvider === "github" ? (
              <Github className="size-5 text-primary" aria-hidden="true" />
            ) : (
              <ProviderIcon className="size-5 text-primary" aria-hidden="true" />
            )}
            <h3 className="text-16 font-medium text-primary">
              Connect with {connectingProvider ? PROVIDER_META[connectingProvider].label : ""}
            </h3>
          </div>
          <p className="text-13 text-secondary">
            Plane will open the provider authorization page in a secure popup. Tokens are exchanged by the backend and
            stored encrypted.
          </p>
          <div className="rounded-sm border border-subtle bg-surface-2 px-3 py-2 text-12 text-secondary">
            {connectingProvider ? appFor(connectingProvider)?.scopes.join(", ") || "No scopes configured" : ""}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setConnectingProvider(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void completeConnection()}
              disabled={busyProvider !== null}
              aria-label="Authorize integration"
            >
              Authorize and connect
            </Button>
          </div>
        </div>
      </ModalCore>

      <AlertModalCore
        isOpen={disconnectProvider !== null}
        handleClose={() => setDisconnectProvider(null)}
        handleSubmit={() => void disconnect()}
        isSubmitting={false}
        title={`Disconnect ${disconnectProvider ? PROVIDER_META[disconnectProvider].label : ""}?`}
        content="Connected repositories will stop syncing and future webhook events will be ignored."
      />
    </section>
  );
}
