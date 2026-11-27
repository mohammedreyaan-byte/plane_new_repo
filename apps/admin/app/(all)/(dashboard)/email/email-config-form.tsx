/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
// types
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IInstanceSmtpConfiguration, TInstanceSmtpConfigurationUpdate } from "@plane/types";
// ui
import { CustomSelect } from "@plane/ui";
// components
import type { TControllerInputFormField } from "@/components/common/controller-input";
import { ControllerInput } from "@/components/common/controller-input";
// hooks
import { useInstance } from "@/hooks/store";
// local components
import { SendTestEmailModal } from "./test-email-modal";

type IInstanceEmailForm = {
  config: IInstanceSmtpConfiguration;
  onSaved: () => Promise<void> | void;
  onTested: () => Promise<void> | void;
};

type EmailFormValues = {
  EMAIL_HOST: string;
  EMAIL_PORT: string;
  EMAIL_HOST_USER: string;
  EMAIL_HOST_PASSWORD: string;
  EMAIL_USE_TLS: string;
  EMAIL_USE_SSL: string;
  EMAIL_FROM: string;
  EMAIL_TIMEOUT: string;
  ENABLE_SMTP: string;
};

type TEmailSecurityKeys = "EMAIL_USE_TLS" | "EMAIL_USE_SSL" | "NONE";

const EMAIL_SECURITY_OPTIONS: { [key in TEmailSecurityKeys]: string } = {
  EMAIL_USE_TLS: "TLS (STARTTLS)",
  EMAIL_USE_SSL: "SSL",
  NONE: "No email security",
};

export function InstanceEmailForm(props: IInstanceEmailForm) {
  const { config, onSaved, onTested } = props;
  // states
  const [isSendTestEmailModalOpen, setIsSendTestEmailModalOpen] = useState(false);
  // store hooks
  const { updateSmtpConfiguration } = useInstance();
  // form data
  const {
    handleSubmit,
    watch,
    setValue,
    control,
    formState: { errors, isValid, isDirty, isSubmitting },
  } = useForm<EmailFormValues>({
    mode: "onChange",
    defaultValues: {
      EMAIL_HOST: config.EMAIL_HOST || "",
      EMAIL_PORT: config.EMAIL_PORT || "",
      EMAIL_HOST_USER: config.EMAIL_HOST_USER || "",
      EMAIL_HOST_PASSWORD: "",
      EMAIL_USE_TLS: config.EMAIL_USE_TLS || "0",
      EMAIL_USE_SSL: config.EMAIL_USE_SSL || "0",
      EMAIL_FROM: config.EMAIL_FROM || "",
      EMAIL_TIMEOUT: config.EMAIL_TIMEOUT || "10",
      ENABLE_SMTP: config.ENABLE_SMTP || "0",
    },
  });

  const emailFormFields: TControllerInputFormField[] = [
    {
      key: "EMAIL_HOST",
      type: "text",
      label: "Host",
      placeholder: "smtp.example.invalid",
      error: Boolean(errors.EMAIL_HOST),
      required: true,
    },
    {
      key: "EMAIL_PORT",
      type: "text",
      label: "Port",
      placeholder: "587",
      error: Boolean(errors.EMAIL_PORT),
      required: true,
    },
    {
      key: "EMAIL_FROM",
      type: "text",
      label: "Sender email address",
      description: "The address recipients see in the From header. Use an address approved by your mail administrator.",
      placeholder: "notifications@example.invalid",
      error: Boolean(errors.EMAIL_FROM),
      required: true,
    },
    {
      key: "EMAIL_TIMEOUT",
      type: "text",
      label: "Connection timeout (seconds)",
      placeholder: "10",
      error: Boolean(errors.EMAIL_TIMEOUT),
      required: true,
    },
  ];

  const optionalEmailFormFields: TControllerInputFormField[] = [
    {
      key: "EMAIL_HOST_USER",
      type: "text",
      label: "Username",
      description: "Leave blank if the relay does not require authentication.",
      placeholder: "smtp-user@example.invalid",
      error: Boolean(errors.EMAIL_HOST_USER),
      required: false,
    },
    {
      key: "EMAIL_HOST_PASSWORD",
      type: "password",
      label: "Password",
      description: config.EMAIL_HOST_PASSWORD_SET
        ? "A password is saved. Leave blank to keep it."
        : "Optional. Never displayed after saving.",
      placeholder: "Leave blank to keep the current value",
      error: Boolean(errors.EMAIL_HOST_PASSWORD),
      required: false,
    },
  ];

  const onSubmit = async (formData: EmailFormValues) => {
    const payload: TInstanceSmtpConfigurationUpdate = {
      EMAIL_HOST: formData.EMAIL_HOST,
      EMAIL_PORT: formData.EMAIL_PORT,
      EMAIL_HOST_USER: formData.EMAIL_HOST_USER,
      EMAIL_USE_TLS: formData.EMAIL_USE_TLS,
      EMAIL_USE_SSL: formData.EMAIL_USE_SSL,
      EMAIL_FROM: formData.EMAIL_FROM,
      EMAIL_TIMEOUT: formData.EMAIL_TIMEOUT,
      ENABLE_SMTP: config.ENABLE_SMTP,
    };
    // An empty password means "keep the stored credential".
    if (formData.EMAIL_HOST_PASSWORD) payload.EMAIL_HOST_PASSWORD = formData.EMAIL_HOST_PASSWORD;

    try {
      await updateSmtpConfiguration(payload);
      await onSaved();
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Success",
        message: "Email settings updated successfully",
      });
    } catch (error) {
      const message = (error as { error?: string })?.error || "Failed to update email settings";
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error",
        message,
      });
    }
  };

  const useTLSValue = watch("EMAIL_USE_TLS");
  const useSSLValue = watch("EMAIL_USE_SSL");
  const emailSecurityKey: TEmailSecurityKeys = useMemo(() => {
    if (useTLSValue === "1") return "EMAIL_USE_TLS";
    if (useSSLValue === "1") return "EMAIL_USE_SSL";
    return "NONE";
  }, [useTLSValue, useSSLValue]);

  const handleEmailSecurityChange = (key: TEmailSecurityKeys) => {
    if (key === "EMAIL_USE_SSL") {
      setValue("EMAIL_USE_TLS", "0", { shouldDirty: true });
      setValue("EMAIL_USE_SSL", "1", { shouldDirty: true });
    }
    if (key === "EMAIL_USE_TLS") {
      setValue("EMAIL_USE_TLS", "1", { shouldDirty: true });
      setValue("EMAIL_USE_SSL", "0", { shouldDirty: true });
    }
    if (key === "NONE") {
      setValue("EMAIL_USE_TLS", "0", { shouldDirty: true });
      setValue("EMAIL_USE_SSL", "0", { shouldDirty: true });
    }
  };

  const testStatus = (config.EMAIL_LAST_TEST_STATUS || "").toLowerCase();
  const testStatusLabel: Record<string, string> = {
    queued: "Queued",
    success: "Successful",
    failed: "Failed",
  };
  const testStatusMessage = testStatus
    ? `${testStatusLabel[testStatus] || testStatus}${config.EMAIL_LAST_TEST_AT ? ` · ${config.EMAIL_LAST_TEST_AT}` : ""}`
    : "";

  return (
    <div className="space-y-8">
      <div>
        <SendTestEmailModal
          isOpen={isSendTestEmailModalOpen}
          handleClose={() => setIsSendTestEmailModalOpen(false)}
          onTested={onTested}
        />
        <div className="grid-col grid w-full max-w-4xl grid-cols-1 items-start justify-between gap-10 lg:grid-cols-2">
          {emailFormFields.map((field) => (
            <ControllerInput
              key={field.key}
              control={control}
              type={field.type}
              name={field.key}
              label={field.label}
              description={field.description}
              placeholder={field.placeholder}
              error={field.error}
              required={field.required}
            />
          ))}
          <div className="flex flex-col gap-1">
            <h4 className="text-13 text-tertiary">Email security</h4>
            <CustomSelect
              value={emailSecurityKey}
              label={EMAIL_SECURITY_OPTIONS[emailSecurityKey]}
              onChange={handleEmailSecurityChange}
              buttonClassName="rounded-md border-subtle"
              input
            >
              {Object.entries(EMAIL_SECURITY_OPTIONS).map(([key, value]) => (
                <CustomSelect.Option key={key} value={key} className="w-full">
                  {value}
                </CustomSelect.Option>
              ))}
            </CustomSelect>
          </div>
        </div>
        <div className="my-6 flex flex-col gap-6 border-t border-subtle pt-4">
          <div className="flex w-full max-w-xl flex-col gap-y-10 px-1">
            <div className="mr-8 flex items-center gap-10 pt-4">
              <div className="grow">
                <div className="text-13 font-medium text-primary">Authentication</div>
                <div className="text-11 font-regular text-tertiary">
                  Optional. Configure credentials when your relay requires them.
                </div>
              </div>
            </div>
          </div>
          <div className="grid-col grid w-full max-w-4xl grid-cols-1 items-center justify-between gap-10 lg:grid-cols-2">
            {optionalEmailFormFields.map((field) => (
              <ControllerInput
                key={field.key}
                control={control}
                type={field.type}
                name={field.key}
                label={field.label}
                description={field.description}
                placeholder={field.placeholder}
                error={field.error}
                required={field.required}
              />
            ))}
          </div>
        </div>
      </div>
      {testStatus && (
        <div className="max-w-4xl rounded-md border border-subtle p-3 text-13 text-tertiary">
          <div
            className={`font-medium ${testStatus === "failed" ? "text-danger-primary" : ""} ${testStatus === "queued" ? "text-tertiary" : ""}`}
          >
            Last test email: {testStatusMessage}
          </div>
          {config.EMAIL_LAST_TEST_MESSAGE && <div className="mt-1 text-tertiary">{config.EMAIL_LAST_TEST_MESSAGE}</div>}
        </div>
      )}
      <div className="flex max-w-4xl items-center gap-4 py-1">
        <Button
          variant="primary"
          size="lg"
          onClick={handleSubmit(onSubmit)}
          loading={isSubmitting}
          disabled={!isValid || !isDirty}
        >
          {isSubmitting ? "Saving" : "Save changes"}
        </Button>
        <Button
          variant="secondary"
          size="lg"
          onClick={() => setIsSendTestEmailModalOpen(true)}
          loading={isSubmitting}
          disabled={!isValid}
        >
          Send test email
        </Button>
      </div>
    </div>
  );
}
