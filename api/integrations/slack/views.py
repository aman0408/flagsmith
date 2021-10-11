import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from slack_sdk.oauth import AuthorizeUrlGenerator

from integrations.common.views import IntegrationCommonViewSet
from integrations.slack.models import SlackConfiguration, SlackEnvironment
from integrations.slack.serializers import (
    SlackChannelListSerializer,
    SlackEnvironmentSerializer,
)

from . import slack


class SlackConfigurationViewSet(IntegrationCommonViewSet):
    serializer_class = SlackEnvironmentSerializer
    pagination_class = None  # set here to ensure documentation is correct
    model_class = SlackEnvironment

    @action(
        detail=False,
        methods=["GET"],
        url_path="channels",
        serializer_class=SlackChannelListSerializer,
    )
    def get_channels(self, request, *args, **kwargs):
        env = self.get_environment_from_request()
        try:
            config = SlackConfiguration.objects.get(project=env.project)
        except ObjectDoesNotExist:
            return Response(
                "Slack api token not found. Please generate the token using oauth",
                status.HTTP_400_BAD_REQUEST,
            )
        slack_token = config.api_token
        serializer = self.get_serializer(
            data=slack.get_channels_data(slack_token), many=True
        )
        serializer.is_valid()
        return Response(serializer.data)

    @action(detail=False, methods=["GET"], url_path="callback", permission_classes=[])
    def slack_oauth_callback(self, request, *args, **kwargs):
        code = request.GET.get("code")
        if not code:
            return Response(
                "code not found in query params",
                status.HTTP_400_BAD_REQUEST,
            )
        redirect_uri = self.reverse_action("slack-oauth-callback", kwargs=kwargs)

        env = self.get_environment_from_request()
        validate_state(request.GET.get("state"), request)
        bot_token = slack.get_bot_token(code, redirect_uri)
        conf = SlackConfiguration.objects.filter(project_id=env.project).first()
        if not conf:
            conf = SlackConfiguration(project=env.project)
        conf.api_token = bot_token
        conf.save()
        return Response("Success")

    @action(detail=False, methods=["GET"], url_path="oauth", permission_classes=[])
    def slack_oauth_init(self, request, *args, **kwargs):
        if not settings.SLACK_CLIENT_ID:
            return Response(
                data={"message": "Slack is not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        state = str(uuid.uuid4())[:6]
        request.session["state"] = state
        callback_uri = self.reverse_action("slack-oauth-callback", kwargs=kwargs)
        authorize_url_generator = AuthorizeUrlGenerator(
            client_id=settings.SLACK_CLIENT_ID,
            redirect_uri=callback_uri,
            scopes=["chat:write", "channels:read", "channels:join"],
        )
        return redirect(authorize_url_generator.generate(state))


def validate_state(state, request):
    state_before = request.session.pop("state", None)
    if state_before != state:
        raise ValueError(
            "State mismatch upon authorization completion." " Try new request."
        )
    return True
