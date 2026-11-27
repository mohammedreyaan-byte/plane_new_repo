/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TInstanceEmailConfigurationKeys =
  | "EMAIL_HOST"
  | "EMAIL_PORT"
  | "EMAIL_HOST_USER"
  | "EMAIL_HOST_PASSWORD"
  | "EMAIL_USE_TLS"
  | "EMAIL_USE_SSL"
  | "EMAIL_FROM"
  | "ENABLE_SMTP"
  | "EMAIL_TIMEOUT"
  | "EMAIL_LAST_TEST_STATUS"
  | "EMAIL_LAST_TEST_MESSAGE"
  | "EMAIL_LAST_TEST_AT";

/**
 * Response of the dedicated instance SMTP endpoint.
 * The password is write-only: only whether a value is stored is returned.
 */
export interface IInstanceSmtpConfiguration {
  ENABLE_SMTP: string;
  EMAIL_HOST: string;
  EMAIL_PORT: string;
  EMAIL_HOST_USER: string;
  EMAIL_HOST_PASSWORD_SET: boolean;
  EMAIL_USE_TLS: string;
  EMAIL_USE_SSL: string;
  EMAIL_FROM: string;
  EMAIL_TIMEOUT: string;
  EMAIL_LAST_TEST_STATUS?: string;
  EMAIL_LAST_TEST_MESSAGE?: string;
  EMAIL_LAST_TEST_AT?: string;
}

export type TInstanceSmtpConfigurationUpdate = Partial<
  Pick<
    IInstanceSmtpConfiguration,
    | "ENABLE_SMTP"
    | "EMAIL_HOST"
    | "EMAIL_PORT"
    | "EMAIL_HOST_USER"
    | "EMAIL_USE_TLS"
    | "EMAIL_USE_SSL"
    | "EMAIL_FROM"
    | "EMAIL_TIMEOUT"
  >
> & {
  EMAIL_HOST_PASSWORD?: string;
};

/** Result of the asynchronous admin "Send test email" action. */
export interface IInstanceSmtpTestStatus {
  state: "idle" | "queued" | "success" | "failed";
  status: string;
  message: string;
  at: string;
}

/** Safe, non-secret summary of one delivery attempt. */
export interface IEmailDeliveryLog {
  id: string;
  receiver_email: string;
  entity_name: string;
  entity_identifier: string | null;
  entity: string;
  state: "delivered" | "failed" | "pending";
  attempts: number;
  last_error: string;
  next_retry_at: string | null;
  processed_at: string | null;
  sent_at: string | null;
  created_at: string;
  data?: unknown;
  old_value?: string | null;
  new_value?: string | null;
}
