/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Loader, ToggleSwitch } from "@plane/ui";
// components
import { PageWrapper } from "@/components/common/page-wrapper";
// hooks
import { useInstance } from "@/hooks/store";
// types
import type { Route } from "./+types/page";
// local
import { InstanceEmailForm } from "./email-config-form";

const SWR_KEY = "INSTANCE_SMTP_CONFIGURATION";

const InstanceEmailPage = observer(function InstanceEmailPage(_props: Route.ComponentProps) {
  // store
  const { fetchSmtpConfiguration, updateSmtpConfiguration, smtpConfiguration } = useInstance();

  const { isLoading, mutate } = useSWR(SWR_KEY, () => fetchSmtpConfiguration());

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSMTPEnabled, setIsSMTPEnabled] = useState(false);
  const config = smtpConfiguration;

  const handleToggle = async () => {
    const nextValue = !isSMTPEnabled;
    setIsSubmitting(true);
    try {
      await updateSmtpConfiguration({ ENABLE_SMTP: nextValue ? "1" : "0" });
      await mutate();
      setIsSMTPEnabled(nextValue);
      setToast({
        title: nextValue ? "Email feature enabled" : "Email feature disabled",
        message: nextValue
          ? "SMTP is enabled. Save your settings and send a test email to verify delivery."
          : "SMTP delivery is disabled. No email will be sent.",
        type: TOAST_TYPE.SUCCESS,
      });
    } catch (error) {
      const message = (error as { error?: string })?.error || "Failed to update the email feature. Please try again.";
      setToast({
        title: "Error updating email",
        message,
        type: TOAST_TYPE.ERROR,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  useEffect(() => {
    if (config) {
      setIsSMTPEnabled(config.ENABLE_SMTP === "1");
    }
  }, [config]);

  return (
    <PageWrapper
      header={{
        title: "Secure emails from your own instance",
        description: (
          <>
            Plane can send useful emails to you and your users from your own instance without talking to the Internet.
            <div className="text-13 font-regular text-tertiary">
              Set it up below and send a test email before enabling delivery.&nbsp;
              <span className="text-danger-primary">Misconfigs can lead to email bounces and errors.</span>
            </div>
          </>
        ),
        actions: isLoading ? (
          <Loader>
            <Loader.Item width="24px" height="16px" className="rounded-full" />
          </Loader>
        ) : (
          <ToggleSwitch value={isSMTPEnabled} onChange={handleToggle} size="sm" disabled={isSubmitting} />
        ),
      }}
    >
      {!isSMTPEnabled && !isLoading && (
        <div className="max-w-4xl rounded-md border border-subtle p-4 text-13 text-tertiary">
          SMTP is disabled. No email will be sent. Enable it above to configure delivery.
        </div>
      )}
      {isSMTPEnabled && !isLoading && (
        <>
          {config ? (
            <InstanceEmailForm
              config={config}
              onSaved={async () => {
                await mutate();
              }}
              onTested={async () => {
                await mutate();
              }}
            />
          ) : (
            <Loader className="space-y-10">
              <Loader.Item height="50px" width="75%" />
              <Loader.Item height="50px" width="75%" />
              <Loader.Item height="50px" width="40%" />
              <Loader.Item height="50px" width="40%" />
              <Loader.Item height="50px" width="20%" />
            </Loader>
          )}
        </>
      )}
    </PageWrapper>
  );
});

export const meta: Route.MetaFunction = () => [{ title: "Email Settings - God Mode" }];

export default InstanceEmailPage;
