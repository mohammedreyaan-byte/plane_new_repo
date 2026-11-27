/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState, Fragment } from "react";
import { Dialog, Transition } from "@headlessui/react";
// plane imports
import { Button } from "@plane/propel/button";
// ui
import { Input } from "@plane/ui";
// hooks
import { useInstance } from "@/hooks/store";

type Props = {
  isOpen: boolean;
  handleClose: () => void;
  onTested?: () => Promise<void> | void;
};

enum ESendEmailSteps {
  SEND_EMAIL = "SEND_EMAIL",
  QUEUED = "QUEUED",
  SUCCESS = "SUCCESS",
  FAILED = "FAILED",
}

const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 30;

export function SendTestEmailModal(props: Props) {
  const { isOpen, handleClose, onTested } = props;
  const { sendTestEmail, fetchSmtpTestStatus } = useInstance();

  // state
  const [receiverEmail, setReceiverEmail] = useState("");
  const [sendEmailStep, setSendEmailStep] = useState<ESendEmailSteps>(ESendEmailSteps.SEND_EMAIL);
  const [statusMessage, setStatusMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  // refs keep the poll isolated from modal close/unmount
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);

  const clearPollTimer = () => {
    if (pollTimer.current !== null) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  const notifyTested = async () => {
    if (onTested) await onTested();
  };

  const finish = async (step: ESendEmailSteps, message: string) => {
    if (!isMounted.current) return;
    setSendEmailStep(step);
    setStatusMessage(message);
    setIsLoading(false);
    await notifyTested();
  };

  const pollTestStatus = async (attempt = 0) => {
    try {
      const status = await fetchSmtpTestStatus();
      if (!isMounted.current || sendEmailStep === ESendEmailSteps.FAILED) return;

      if (status.state === "success") {
        clearPollTimer();
        await finish(ESendEmailSteps.SUCCESS, status.message || "Test email sent successfully");
        return;
      }
      if (status.state === "failed") {
        clearPollTimer();
        await finish(ESendEmailSteps.FAILED, status.message || "Failed to send email");
        return;
      }
      if (attempt + 1 >= MAX_POLL_ATTEMPTS) {
        clearPollTimer();
        await finish(ESendEmailSteps.FAILED, "The email worker did not report a result in time. Please try again.");
        return;
      }
      pollTimer.current = setTimeout(() => void pollTestStatus(attempt + 1), POLL_INTERVAL_MS);
    } catch (error) {
      clearPollTimer();
      const message = (error as { error?: string })?.error || "Failed to read the test email result";
      await finish(ESendEmailSteps.FAILED, message);
    }
  };

  // reset state
  const resetState = () => {
    clearPollTimer();
    setReceiverEmail("");
    setSendEmailStep(ESendEmailSteps.SEND_EMAIL);
    setStatusMessage("");
    setIsLoading(false);
  };

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
      clearPollTimer();
    };
  }, []);

  useEffect(() => {
    if (!isOpen) resetState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const setErrorState = (message: string) => {
    setSendEmailStep(ESendEmailSteps.FAILED);
    setStatusMessage(message);
    setIsLoading(false);
  };

  const handleSubmit = async (e: React.MouseEvent<HTMLButtonElement, MouseEvent>) => {
    e.preventDefault();
    if (!receiverEmail.trim()) {
      setErrorState("A valid receiver email is required");
      return;
    }

    clearPollTimer();
    setSendEmailStep(ESendEmailSteps.QUEUED);
    setStatusMessage("Queued for delivery. Waiting for the email worker...");
    setIsLoading(true);
    try {
      const status = await sendTestEmail(receiverEmail.trim());
      if (!isMounted.current) return;
      if (status.state === "success") {
        await finish(ESendEmailSteps.SUCCESS, status.message || "Test email sent successfully");
        return;
      }
      if (status.state === "failed") {
        await finish(ESendEmailSteps.FAILED, status.message || "Failed to send email");
        return;
      }
      await pollTestStatus(0);
    } catch (error) {
      const message = (error as { error?: string })?.error || "Failed to queue the test email";
      await finish(ESendEmailSteps.FAILED, message);
    }
  };

  const title =
    sendEmailStep === ESendEmailSteps.SEND_EMAIL
      ? "Send test email"
      : sendEmailStep === ESendEmailSteps.QUEUED
        ? "Sending test email"
        : sendEmailStep === ESendEmailSteps.SUCCESS
          ? "Email sent"
          : "Failed";

  return (
    <Transition.Root show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-20" onClose={handleClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-backdrop transition-opacity" />
        </Transition.Child>
        <div className="fixed inset-0 z-20 overflow-y-auto">
          <div className="my-10 flex justify-center p-4 text-center sm:p-0 md:my-20">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-300"
              enterFrom="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
              enterTo="opacity-100 translate-y-0 sm:scale-100"
              leave="ease-in duration-200"
              leaveFrom="opacity-100 translate-y-0 sm:scale-100"
              leaveTo="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
            >
              <Dialog.Panel className="relative w-full transform rounded-lg bg-surface-1 p-5 px-4 text-left shadow-raised-200 transition-all sm:max-w-xl">
                <h3 className="text-16 leading-6 font-medium text-primary">{title}</h3>
                <div className="pt-6 pb-2">
                  {sendEmailStep === ESendEmailSteps.SEND_EMAIL && (
                    <Input
                      id="receiver_email"
                      type="email"
                      value={receiverEmail}
                      onChange={(e) => setReceiverEmail(e.target.value)}
                      placeholder="recipient@example.invalid"
                      className="w-full resize-none text-16"
                      tabIndex={0}
                    />
                  )}
                  {sendEmailStep === ESendEmailSteps.QUEUED && (
                    <div className="text-13 text-tertiary">{statusMessage}</div>
                  )}
                  {sendEmailStep === ESendEmailSteps.SUCCESS && (
                    <div className="flex flex-col gap-y-4 text-13">
                      <p>
                        We have sent the test email to {receiverEmail}. Please check your spam folder if you cannot find
                        it.
                      </p>
                      {statusMessage && <p className="text-tertiary">{statusMessage}</p>}
                      <p>If you still cannot find it, recheck your SMTP configuration and trigger a new test email.</p>
                    </div>
                  )}
                  {sendEmailStep === ESendEmailSteps.FAILED && (
                    <div className="text-13 text-danger-primary">{statusMessage}</div>
                  )}
                  <div className="mt-5 flex items-center justify-end gap-2">
                    <Button variant="secondary" size="lg" onClick={handleClose} tabIndex={0}>
                      {sendEmailStep === ESendEmailSteps.SEND_EMAIL ? "Cancel" : "Close"}
                    </Button>
                    {sendEmailStep === ESendEmailSteps.SEND_EMAIL && (
                      <Button variant="primary" size="lg" loading={isLoading} onClick={handleSubmit} tabIndex={0}>
                        Send email
                      </Button>
                    )}
                  </div>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition.Root>
  );
}
