# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Production API endpoints for the five GMC frontend features."""

import json
from datetime import timedelta
from typing import Any, Dict

from django.db import transaction
from django.http import HttpResponse
from django.utils.html import escape
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import (
    AutomationRuleSerializer,
    AutomationRunSerializer,
    ExternalAccountIntegrationSerializer,
    ExternalMessageLogSerializer,
    ExternalRepositorySerializer,
    ExternalWebhookEventSerializer,
    GmcImporterSerializer,
    InitiativeSerializer,
    SlackChannelSubscriptionSerializer,
)
from plane.bgtasks.gmc_automation_task import evaluate_issue_event
from plane.bgtasks.gmc_import_task import process_import_job
from plane.bgtasks.gmc_slack_task import dispatch_slack_event, send_slack_test_message
from plane.bgtasks.gmc_webhook_task import process_webhook_event
from plane.db.models import (
    APIToken,
    AutomationRule,
    AutomationRun,
    ExternalAccountIntegration,
    ExternalMessageLog,
    ExternalRepository,
    ExternalWebhookEvent,
    Importer,
    Initiative,
    Issue,
    IssueType,
    Label,
    Module,
    SlackChannelSubscription,
    State,
    User,
    Workspace,
    WorkspaceMember,
)
from plane.license.utils.encryption import encrypt_data
from plane.utils.gmc_integrations import (
    IntegrationConfigurationError,
    ProviderAPIError,
    exchange_code_for_token,
    fetch_provider_account,
    fetch_repositories,
    fetch_slack_channels,
    is_provider_configured,
    oauth_authorize_url,
    provider_config,
    verify_webhook_signature,
)

from .base import BaseAPIView

PROVIDERS = ("github", "gitlab", "slack")
PROVIDER_LABELS = {"github": "GitHub", "gitlab": "GitLab", "slack": "Slack"}
PROVIDER_DESCRIPTIONS = {
    "github": "Connect GitHub to sync repositories and link pull requests and commits.",
    "gitlab": "Connect GitLab to sync projects and link merge requests and commits.",
    "slack": "Post real Plane work item events to Slack channels.",
}
SLACK_EVENT_KEYS = (
    "work_item.created",
    "work_item.state_changed",
    "work_item.assigned",
    "work_item.commented",
    "work_item.deleted",
)


def _error(exc: Exception, fallback: str) -> Response:
    message = str(exc) if isinstance(exc, (IntegrationConfigurationError, ProviderAPIError, ValueError)) else fallback
    return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)


def _workspace(slug: str) -> Workspace:
    return Workspace.objects.get(slug=slug)


def _get_integration(slug: str, provider: str) -> ExternalAccountIntegration:
    return ExternalAccountIntegration.objects.get(
        workspace__slug=slug, provider=provider.lower(), is_active=True
    )


def _get_or_create_token(user, workspace) -> APIToken:
    token = APIToken.objects.filter(user=user, workspace=workspace, user_type=0).first()
    if token:
        return token
    return APIToken.objects.create(user=user, workspace=workspace, label="GMC integration token", user_type=0)


class AppIntegrationListEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="WORKSPACE")
    def get(self, request, slug):
        payload = []
        for provider in PROVIDERS:
            payload.append(
                {
                    "id": provider,
                    "provider": provider,
                    "title": PROVIDER_LABELS[provider],
                    "description": PROVIDER_DESCRIPTIONS[provider],
                    "network": 1,
                    "verified": True,
                    "configured": is_provider_configured(provider),
                    "scopes": provider_config(provider)["scopes"] if is_provider_configured(provider) else [],
                }
            )
        return Response(payload)


class WorkspaceIntegrationListEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def get(self, request, slug):
        integrations = ExternalAccountIntegration.objects.filter(workspace__slug=slug, is_active=True)
        return Response(ExternalAccountIntegrationSerializer(integrations, many=True).data)


class WorkspaceIntegrationDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def delete(self, request, slug, provider):
        integration = _get_integration(slug, provider)
        with transaction.atomic():
            ExternalAccountIntegration.objects.filter(pk=integration.pk).update(
                is_active=False,
                access_token="",
                refresh_token="",
                webhook_secret="",
            )
            SlackChannelSubscription.objects.filter(integration=integration).update(is_active=False)
            ExternalRepository.objects.filter(integration=integration).update(is_sync_enabled=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProviderOAuthAuthorizeEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def post(self, request, slug, provider):
        provider = provider.lower()
        if provider not in PROVIDERS:
            return Response({"error": "Unknown provider"}, status=status.HTTP_404_NOT_FOUND)
        from plane.db.models import OAuthAuthorizationRequest

        authorization = OAuthAuthorizationRequest.objects.create(
            workspace=_workspace(slug),
            user=request.user,
            provider=provider,
            redirect_uri=request.data.get("redirect_uri", ""),
            scopes=provider_config(provider)["scopes"],
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        try:
            authorize_url = oauth_authorize_url(provider, str(authorization.state))
        except IntegrationConfigurationError as exc:
            authorization.delete()
            return _error(exc, "Provider is not configured")
        return Response({"authorize_url": authorize_url, "state": str(authorization.state)})


class ProviderOAuthCallbackEndpoint(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, provider):
        from plane.db.models import OAuthAuthorizationRequest

        provider = provider.lower()
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")
        if error or not code or not state:
            return self._html(False, "Authorization was cancelled or rejected.")
        authorization = OAuthAuthorizationRequest.objects.filter(
            state=state, provider=provider, used_at__isnull=True, expires_at__gt=timezone.now()
        ).select_related("workspace", "user").first()
        if not authorization:
            return self._html(False, "Authorization state is invalid or expired.")
        try:
            token_data = exchange_code_for_token(provider, code)
            access_token = token_data.get("access_token", "")
            if not access_token:
                raise ProviderAPIError("Provider did not return an access token")
            account = fetch_provider_account(provider, access_token)
            if provider == "slack":
                team = token_data.get("team", {})
                account = {"id": team.get("id", ""), "name": team.get("name", "")}
                if not account["id"]:
                    raise ProviderAPIError("Slack team information is missing")

            config = provider_config(provider)
            with transaction.atomic():
                integration, _ = ExternalAccountIntegration.objects.update_or_create(
                    workspace=authorization.workspace,
                    provider=provider,
                    provider_account_id=str(account["id"]),
                    defaults={
                        "project": None,
                        "account_name": account.get("name", ""),
                        "host": config.get("host", ""),
                        "scopes": token_data.get("scope", "").split(",") if isinstance(token_data.get("scope"), str) else token_data.get("scope", []),
                        "metadata": {"authed_user": token_data.get("authed_user", {}), "token_type": token_data.get("token_type", "")},
                        "is_active": True,
                    },
                )
                integration.set_access_token(access_token)
                refresh_token = token_data.get("refresh_token", "")
                if refresh_token:
                    integration.refresh_token = encrypt_data(refresh_token)
                if config.get("webhook_secret"):
                    integration.set_webhook_secret(config["webhook_secret"])
                integration.save()

                if provider in ("github", "gitlab"):
                    for repo in fetch_repositories(provider, access_token):
                        ExternalRepository.objects.update_or_create(
                            integration=integration,
                            external_id=repo["external_id"],
                            defaults={
                                "workspace": authorization.workspace,
                                "provider": provider,
                                "full_name": repo["full_name"],
                                "url": repo["url"],
                                "metadata": repo.get("metadata", {}),
                                "last_synced_at": timezone.now(),
                            },
                        )
                if provider == "slack":
                    existing = {
                        item.channel_id: item for item in SlackChannelSubscription.objects.filter(integration=integration)
                    }
                    for channel in fetch_slack_channels(access_token):
                        subscription = existing.get(channel["channel_id"])
                        if subscription is None:
                            subscription = SlackChannelSubscription(
                                workspace=authorization.workspace,
                                integration=integration,
                                channel_id=channel["channel_id"],
                                channel_name=channel["channel_name"],
                                member_count=channel["member_count"],
                                events={key: False for key in SLACK_EVENT_KEYS},
                            )
                        else:
                            subscription.channel_name = channel["channel_name"]
                            subscription.member_count = channel["member_count"]
                            subscription.is_active = True
                        subscription.save()
                authorization.used_at = timezone.now()
                authorization.save(update_fields=["used_at"])
        except (IntegrationConfigurationError, ProviderAPIError, KeyError) as exc:
            return self._html(False, f"Authorization failed: {exc}")
        return self._html(True, f"{PROVIDER_LABELS[provider]} connected")

    @staticmethod
    def _html(success: bool, message: str) -> HttpResponse:
        safe_message = json.dumps(message).replace("<", "\\u003c").replace(">", "\\u003e")
        return HttpResponse(
            f"<!doctype html><html><body><p>{escape(message)}</p><script>"
            f"if(window.opener){{window.opener.postMessage({{success: {str(success).lower()}, message: {safe_message}}}, '*');}}"
            f"window.close();</script></body></html>",
            content_type="text/html",
        )


class RepositoryListEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def get(self, request, slug, provider):
        integration = _get_integration(slug, provider)
        repositories = ExternalRepository.objects.filter(integration=integration)
        return Response(ExternalRepositorySerializer(repositories, many=True).data)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def post(self, request, slug, provider):
        integration = _get_integration(slug, provider)
        if provider not in ("github", "gitlab"):
            return Response({"error": "Repository sync is only supported for GitHub and GitLab"}, status=400)
        try:
            repositories = fetch_repositories(provider, integration.get_access_token())
        except (IntegrationConfigurationError, ProviderAPIError) as exc:
            return _error(exc, "Repository refresh failed")
        with transaction.atomic():
            for repo in repositories:
                ExternalRepository.objects.update_or_create(
                    integration=integration,
                    external_id=repo["external_id"],
                    defaults={
                        "workspace": integration.workspace,
                        "provider": provider,
                        "full_name": repo["full_name"],
                        "url": repo["url"],
                        "metadata": repo.get("metadata", {}),
                        "last_synced_at": timezone.now(),
                    },
                )
            ExternalAccountIntegration.objects.filter(pk=integration.pk).update(last_synced_at=timezone.now())
        return Response(ExternalRepositorySerializer(ExternalRepository.objects.filter(integration=integration), many=True).data)


class RepositoryDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def patch(self, request, slug, provider, repository_id):
        integration = _get_integration(slug, provider)
        repository = ExternalRepository.objects.get(pk=repository_id, integration=integration)
        serializer = ExternalRepositorySerializer(
            repository, data={"is_sync_enabled": request.data.get("is_sync_enabled")}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(last_synced_at=timezone.now())
        return Response(serializer.data)


class WebhookEventListEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def get(self, request, slug, provider):
        integration = ExternalAccountIntegration.objects.filter(workspace__slug=slug, provider=provider).first()
        events = ExternalWebhookEvent.objects.filter(workspace__slug=slug, provider=provider)
        if integration:
            events = events.filter(integration=integration)
            for repo in ExternalRepository.objects.filter(integration=integration, is_sync_enabled=True):
                events = events | ExternalWebhookEvent.objects.filter(detail__icontains=repo.full_name)
        return Response(ExternalWebhookEventSerializer(events.distinct()[:100], many=True).data)


class ProviderWebhookEndpoint(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, provider):
        provider = provider.lower()
        slug = request.query_params.get("workspace")
        if not slug:
            return Response({"error": "workspace query parameter is required"}, status=400)
        integration = ExternalAccountIntegration.objects.filter(
            workspace__slug=slug, provider=provider, is_active=True
        ).first()
        if not integration:
            return Response({"error": "No active integration for this workspace"}, status=404)
        secret = integration.get_webhook_secret()
        if not verify_webhook_signature(provider, request.body, dict(request.headers), secret):
            return Response({"error": "Invalid webhook signature"}, status=401)
        payload = request.data if isinstance(request.data, dict) else {}
        if provider == "slack" and payload.get("type") == "url_verification":
            return Response({"challenge": payload.get("challenge", "")}, status=200)
        delivery_id = (
            request.headers.get("X-Github-Delivery")
            or request.headers.get("X-Gitlab-Event-Uuid")
            or request.headers.get("X-Slack-Event-Id")
            or str(timezone.now().timestamp())
        )
        if ExternalWebhookEvent.objects.filter(delivery_id=delivery_id).exists():
            return Response({"status": "duplicate"}, status=200)
        event = ExternalWebhookEvent.objects.create(
            workspace=integration.workspace,
            integration=integration,
            provider=provider,
            event_type=request.headers.get("X-Github-Event") or request.headers.get("X-Gitlab-Event") or payload.get("type", "event"),
            delivery_id=delivery_id,
            signature_verified=True,
            status="received",
            payload=payload,
        )
        process_webhook_event.delay(str(event.id))
        return Response({"status": "accepted", "id": str(event.id)}, status=202)


class InitiativeEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id):
        initiatives = Initiative.objects.filter(project_id=project_id).select_related("owner")
        return Response(InitiativeSerializer(initiatives, many=True).data)

    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def post(self, request, slug, project_id):
        serializer = InitiativeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(project_id=project_id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class InitiativeDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id, pk):
        initiative = Initiative.objects.get(project_id=project_id, pk=pk)
        return Response(InitiativeSerializer(initiative).data)

    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def patch(self, request, slug, project_id, pk):
        initiative = Initiative.objects.get(project_id=project_id, pk=pk)
        serializer = InitiativeSerializer(initiative, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def delete(self, request, slug, project_id, pk):
        initiative = Initiative.objects.get(project_id=project_id, pk=pk)
        initiative.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InitiativeOptionsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id):
        members = WorkspaceMember.objects.filter(workspace__slug=slug, is_active=True).select_related("member")
        modules = Module.objects.filter(project_id=project_id).values("id", "name")
        epics = Issue.objects.filter(project_id=project_id, type__name__iexact="epic").values("id", "name")
        return Response(
            {
                "members": [
                    {"id": str(item.member_id), "display_name": item.member.display_name or item.member.email}
                    for item in members
                ],
                "modules": [{"id": str(item["id"]), "name": item["name"]} for item in modules],
                "epics": [{"id": str(item["id"]), "name": item["name"]} for item in epics],
            }
        )


class AutomationRuleEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id):
        rules = AutomationRule.objects.filter(project_id=project_id)
        return Response(AutomationRuleSerializer(rules, many=True).data)

    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def post(self, request, slug, project_id):
        serializer = AutomationRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(project_id=project_id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AutomationRuleDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def patch(self, request, slug, project_id, pk):
        rule = AutomationRule.objects.get(project_id=project_id, pk=pk)
        serializer = AutomationRuleSerializer(rule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def delete(self, request, slug, project_id, pk):
        rule = AutomationRule.objects.get(project_id=project_id, pk=pk)
        rule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AutomationRunEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id):
        runs = AutomationRun.objects.filter(project_id=project_id).select_related("rule", "work_item")
        return Response(AutomationRunSerializer(runs[:100], many=True).data)


class AutomationOptionsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id):
        work_items = Issue.objects.filter(project_id=project_id).values(
            "id", "project__identifier", "sequence_id", "name"
        )[:200]
        states = State.objects.filter(project_id=project_id).values("id", "name")
        labels = Label.objects.filter(project_id=project_id).values("id", "name")
        members = WorkspaceMember.objects.filter(workspace__slug=slug, is_active=True).values(
            "member_id", "member__display_name", "member__email"
        )
        issue_types = IssueType.objects.filter(
            workspace__slug=slug, is_active=True, project_issue_types__project_id=project_id
        ).values("id", "name").distinct()
        return Response(
            {
                "work_items": [
                    {
                        "id": str(item["id"]),
                        "identifier": f"{item['project__identifier']}-{item['sequence_id']}",
                        "name": item["name"],
                    }
                    for item in work_items
                ],
                "states": [{"id": str(item["id"]), "name": item["name"]} for item in states],
                "labels": [{"id": str(item["id"]), "name": item["name"]} for item in labels],
                "members": [
                    {
                        "id": str(item["member_id"]),
                        "display_name": item["member__display_name"] or item["member__email"],
                    }
                    for item in members
                ],
                "priorities": [
                    {"value": value, "label": label} for value, label in Issue.PRIORITY_CHOICES if value != "none"
                ],
                "types": [{"id": str(item["id"]), "name": item["name"]} for item in issue_types],
            }
        )


class AutomationRuleTestEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def post(self, request, slug, project_id, pk):
        issue_id = request.data.get("issue_id")
        if not issue_id:
            return Response({"error": "A work item is required for a test run"}, status=400)
        if not Issue.objects.filter(project_id=project_id, pk=issue_id).exists():
            return Response({"error": "Work item does not exist in this project"}, status=404)
        run_ids = evaluate_issue_event(
            trigger="test",
            project_id=project_id,
            issue_id=str(issue_id),
            actor_id=str(request.user.id),
            rule_id=str(pk),
            dry_run=True,
        )
        return Response({"run_ids": run_ids}, status=status.HTTP_202_ACCEPTED)


class ImportEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id):
        jobs = Importer.objects.filter(project_id=project_id)
        return Response(GmcImporterSerializer(jobs, many=True).data)

    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def post(self, request, slug, project_id):
        service = request.data.get("service", "csv")
        config: Dict[str, Any] = {}
        metadata: Dict[str, Any] = {}
        try:
            if service == "csv":
                upload = request.FILES.get("file")
                if not upload:
                    return Response({"error": "A CSV file is required"}, status=400)
                if upload.size > 5 * 1024 * 1024:
                    return Response({"error": "CSV file exceeds the 5 MB limit"}, status=400)
                config["csv_content"] = encrypt_data(upload.read().decode("utf-8-sig"))
                metadata["file_name"] = upload.name
            elif service == "jira":
                for key in ("site_url", "email", "api_token", "project_key"):
                    config[key] = encrypt_data(str(request.data.get(key, "")))
                metadata["project_key"] = request.data.get("project_key", "")
            elif service == "github":
                for key in ("token", "owner", "repo"):
                    config[key] = encrypt_data(str(request.data.get(key, "")))
                config["include_issues"] = bool(request.data.get("include_issues", True))
                config["include_prs"] = bool(request.data.get("include_prs", True))
                metadata["repo"] = request.data.get("repo", "")
            else:
                return Response({"error": "Unsupported import source"}, status=400)
        except Exception as exc:
            return _error(exc, "Import configuration could not be saved")

        workspace = _workspace(slug)
        importer = Importer.objects.create(
            project_id=project_id,
            workspace=workspace,
            service=service,
            initiated_by=request.user,
            token=_get_or_create_token(request.user, workspace),
            metadata=metadata,
            config=config,
            data={},
            file_name=metadata.get("file_name", ""),
            status="queued",
        )
        process_import_job.delay(str(importer.id))
        return Response(GmcImporterSerializer(importer).data, status=status.HTTP_202_ACCEPTED)


class ImportDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id, pk):
        importer = Importer.objects.get(project_id=project_id, pk=pk)
        return Response(GmcImporterSerializer(importer).data)

    @allow_permission([ROLE.ADMIN], level="PROJECT")
    def delete(self, request, slug, project_id, pk):
        importer = Importer.objects.get(project_id=project_id, pk=pk)
        importer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ImportErrorsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST], level="PROJECT")
    def get(self, request, slug, project_id, pk):
        importer = Importer.objects.get(project_id=project_id, pk=pk)
        content = "\n".join(importer.error_log or [])
        return HttpResponse(content or "No import errors were recorded.", content_type="text/plain")


class SlackEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def get(self, request, slug):
        integration = ExternalAccountIntegration.objects.filter(workspace__slug=slug, provider="slack", is_active=True).first()
        if not integration:
            return Response(
                {
                    "connected": False,
                    "channels": [],
                    "events": {key: False for key in SLACK_EVENT_KEYS},
                    "notifications": [],
                    "event_catalog": [
                        {"key": key, "label": key.replace("work_item.", "").replace("_", " ").title()}
                        for key in SLACK_EVENT_KEYS
                    ],
                }
            )
        subscriptions = SlackChannelSubscription.objects.filter(integration=integration, is_active=True)
        default = subscriptions.filter(is_default=True).first() or subscriptions.first()
        events = default.events if default else {}
        logs = ExternalMessageLog.objects.filter(integration=integration).select_related("work_item")[:100]
        return Response(
            {
                "connected": True,
                "integration": ExternalAccountIntegrationSerializer(integration).data,
                "team_id": integration.provider_account_id,
                "team_name": integration.account_name,
                "default_channel_id": default.channel_id if default else "",
                "channels": SlackChannelSubscriptionSerializer(subscriptions, many=True).data,
                "events": events,
                "notifications": ExternalMessageLogSerializer(logs, many=True).data,
                "event_catalog": [
                    {"key": key, "label": key.replace("work_item.", "").replace("_", " ").title()}
                    for key in SLACK_EVENT_KEYS
                ],
            }
        )

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def patch(self, request, slug):
        integration = _get_integration(slug, "slack")
        channel_id = request.data.get("default_channel_id")
        events = request.data.get("events")
        if events is not None and not isinstance(events, dict):
            return Response({"error": "events must be an object"}, status=400)
        with transaction.atomic():
            subscriptions = SlackChannelSubscription.objects.filter(integration=integration, is_active=True)
            if channel_id:
                if not subscriptions.filter(channel_id=channel_id).exists():
                    return Response({"error": "Channel is not part of this integration"}, status=400)
                subscriptions.update(is_default=False)
                subscriptions.filter(channel_id=channel_id).update(is_default=True)
            if events is not None:
                for subscription in subscriptions:
                    subscription.events = events
                    subscription.save(update_fields=["events"])
        return self.get(request, slug=slug)

    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def delete(self, request, slug):
        integration = _get_integration(slug, "slack")
        ExternalAccountIntegration.objects.filter(pk=integration.pk).update(is_active=False, access_token="")
        SlackChannelSubscription.objects.filter(integration=integration).update(is_active=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SlackChannelsEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def post(self, request, slug):
        integration = _get_integration(slug, "slack")
        try:
            channels = fetch_slack_channels(integration.get_access_token())
        except (IntegrationConfigurationError, ProviderAPIError) as exc:
            return _error(exc, "Slack channel refresh failed")
        with transaction.atomic():
            for channel in channels:
                subscription, created = SlackChannelSubscription.objects.get_or_create(
                    integration=integration,
                    channel_id=channel["channel_id"],
                    defaults={
                        "workspace": integration.workspace,
                        "channel_name": channel["channel_name"],
                        "member_count": channel["member_count"],
                        "events": {key: False for key in SLACK_EVENT_KEYS},
                    },
                )
                if not created:
                    subscription.channel_name = channel["channel_name"]
                    subscription.member_count = channel["member_count"]
                    subscription.is_active = True
                    subscription.save(update_fields=["channel_name", "member_count", "is_active"])
            ExternalAccountIntegration.objects.filter(pk=integration.pk).update(last_synced_at=timezone.now())
        return Response(
            SlackChannelSubscriptionSerializer(
                SlackChannelSubscription.objects.filter(integration=integration, is_active=True), many=True
            ).data
        )


class SlackTestEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN], level="WORKSPACE", capability="integration.manage")
    def post(self, request, slug):
        integration = _get_integration(slug, "slack")
        channel_id = request.data.get("channel_id") or request.data.get("default_channel_id")
        if not channel_id:
            return Response({"error": "A channel is required"}, status=400)
        if not SlackChannelSubscription.objects.filter(integration=integration, channel_id=channel_id, is_active=True).exists():
            return Response({"error": "Channel is not part of this integration"}, status=400)
        log_id = send_slack_test_message.delay(str(integration.id), str(channel_id)).get(timeout=30)
        return Response({"log_id": log_id}, status=status.HTTP_202_ACCEPTED)
